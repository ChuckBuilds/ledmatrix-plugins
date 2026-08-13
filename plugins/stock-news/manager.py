"""
Stock News Ticker Plugin for LEDMatrix

Live financial headlines with company logos, multi-colour segment rendering,
spread symbol fetching, market-hours throttling, and Vegas scroll integration.

Features:
- Yahoo Finance search API (publisher, price, timestamp) with RSS fallback
- Auto font size derived from display height when not configured
- Display styles: logo_and_ticker, ticker_only, logo_only
- Per-segment colours: symbol (yellow), headline (green), publisher/age (dim)
- Optional stock price display alongside headline
- Relative age display ("2h ago") from real publish timestamps
- Symbol fetches spread across update_interval — no budget burst
- Market-hours throttling to save requests overnight/weekends
- Per-day + per-hour request budget with startup adequacy warning
- Per-symbol max-headlines override (int or {AAPL: 2, default: 1})
- Stale-data indicator: dims colours when data is overdue
- Configurable item_gap between stories
- Vegas scroll integration with content caching
- on_config_change() live reload without plugin restart
- requests.Session with 4x retry + exponential backoff
"""

import logging
import random
import time
import requests
import html
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import defusedxml.ElementTree as ET

from src.plugin_system.base_plugin import BasePlugin
from src.common.scroll_helper import ScrollHelper
from src.common.logo_helper import LogoHelper

logger = logging.getLogger(__name__)

_YAHOO_SEARCH = "https://query1.finance.yahoo.com/v1/finance/search"
_YAHOO_RSS = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US"


class StockNewsTickerPlugin(BasePlugin):

    def __init__(self, plugin_id: str, config: Dict[str, Any],
                 display_manager, cache_manager, plugin_manager):
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)

        self.feeds_config = config.get('feeds', {})
        self.global_config = config.get('global', {})

        # Display dimensions
        self.display_width = self.display_manager.matrix.width
        self.display_height = self.display_manager.matrix.height

        self._apply_config()

        # State — persistent across update cycles
        self.all_news_items: list = []
        self._symbol_data: Dict[str, List] = {}   # per-symbol/feed headline cache
        self._logo_failed: set = set()            # symbols whose logo download failed this session
        self._feed_last_fetch: Dict[str, float] = {}
        self._fetch_index: int = 0                # rotating symbol index
        self._last_symbol_fetch: float = 0
        self._rotation_count: int = 0
        self._items_rotated: int = 0
        self._cycle_complete: bool = False
        self._vegas_cache: Optional[list] = None
        self._was_stale: bool = False
        self.last_update: float = 0
        self.initialized = True

        # HTTP session with retry/backoff
        self._session = self._create_session()

        # Logo infrastructure
        self._logo_dir = Path(__file__).parent / 'assets' / 'logos'
        self._logo_dir.mkdir(parents=True, exist_ok=True)
        self.logo_helper = LogoHelper(self.display_width, self.display_height, logger=self.logger)

        # Fonts and scroll
        self._fonts: dict = self._load_fonts()
        self.scroll_helper = ScrollHelper(self.display_width, self.display_height, logger=self.logger)
        self._configure_scroll_settings()
        self._register_fonts()

        # Expose enable_scrolling so the core display loop uses its high-FPS
        # (125 FPS) path instead of the 1 FPS default path used by static plugins
        self.enable_scrolling = True

        stock_symbols = self.feeds_config.get('stock_symbols', [])
        custom_feeds = self._get_custom_feeds()
        self.logger.info(
            "[Stock News] Initialized — symbols=%s, custom=%s, style=%s, font=%dpx, item_gap=%dpx",
            stock_symbols, list(custom_feeds.keys()), self.display_style,
            self.font_size, self.item_gap,
        )
        self._check_budget_adequacy()

    # -------------------------------------------------------------------------
    # Config helpers
    # -------------------------------------------------------------------------

    def _get_custom_feeds(self) -> Dict[str, str]:
        """Return custom_feeds as {name: url}. Accepts new list format or legacy dict format."""
        raw = self.feeds_config.get('custom_feeds', [])
        if isinstance(raw, list):
            return {item['name']: item['url'] for item in raw
                    if isinstance(item, dict) and 'name' in item and 'url' in item}
        return raw if isinstance(raw, dict) else {}

    @staticmethod
    def _parse_color(value: Any, default: List[int]) -> Tuple[int, int, int]:
        """Accept '#rrggbb' hex string (new) or [R, G, B] list (legacy) and return an (R, G, B) tuple."""
        if isinstance(value, str):
            v = value.lstrip('#')
            if len(v) == 3:
                v = v[0] * 2 + v[1] * 2 + v[2] * 2
            if len(v) == 6:
                try:
                    return (int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16))
                except ValueError:
                    pass
        if isinstance(value, (list, tuple)) and len(value) == 3:
            return tuple(value)  # type: ignore[return-value]
        return tuple(default)  # type: ignore[return-value]

    def _apply_config(self) -> None:
        """Read all config keys into instance vars. Called from __init__ and on_config_change."""
        gc = self.global_config
        fc = self.feeds_config

        # Auto font size: 0 or absent → derive from display height, snapped to
        # the pixel font's 8px design grid. height//3 lands on 10 for the common
        # 32px panel, and an off-grid size splits single design pixels across
        # screen pixels, so strokes come out alternating 1px and 2px wide. An
        # explicit font_size is honoured as typed -- fontmode still keeps it
        # hard-edged, it just may have that uneven stroke width.
        raw_fs = gc.get('font_size', 0)
        if raw_fs and int(raw_fs) > 0:
            self.font_size = int(raw_fs)
        else:
            self.font_size = self._snap_to_font_grid(
                max(6, min(16, self.display_height // 3))
            )

        # Item gap: 0 → use full display width (clean separation between stories)
        raw_gap = gc.get('item_gap', 0)
        self.item_gap = int(raw_gap) if raw_gap and int(raw_gap) > 0 else self.display_width

        # Scroll / duration
        self.display_duration = gc.get('display_duration', 30)
        self.scroll_speed = gc.get('scroll_speed', 1)
        self.scroll_delay = gc.get('scroll_delay', 0.01)
        self.dynamic_duration = gc.get('dynamic_duration', True)
        self.min_duration = gc.get('min_duration', 30)
        self.max_duration = gc.get('max_duration', 300)

        # Headlines
        self.max_headlines_per_symbol = gc.get('max_headlines_per_symbol', 1)  # int or dict
        self.headlines_per_rotation = gc.get('headlines_per_rotation', 2)
        self.max_headline_length = gc.get('max_headline_length', 120)

        # Rotation / shuffle
        self.rotation_enabled = gc.get('rotation_enabled', True)
        self.rotation_threshold = gc.get('rotation_threshold', 1)
        self.shuffle_headlines = gc.get('shuffle_headlines', True)

        # Display style
        self.display_style = gc.get('display_style', 'logo_and_ticker')
        # 0 → auto: fill the full display height so logos use all available vertical space
        raw_ls = gc.get('logo_size', 0)
        self.logo_size = int(raw_ls) if raw_ls and int(raw_ls) > 0 else self.display_height
        self.logo_fetch_enabled = gc.get('logo_fetch_enabled', True)
        self.logo_url_template = gc.get(
            'logo_url_template',
            'https://financialmodelingprep.com/image-stock/{symbol}.png'
        )

        # What to show
        self.show_publisher = gc.get('show_publisher', True)
        self.show_age = gc.get('show_age', True)
        self.show_price = gc.get('show_price', False)

        # Cross-plugin sync
        self.sync_with_stocks_plugin = gc.get('sync_with_stocks_plugin', False)

        # Eager fill: fetch every never-seen symbol at update() cadence until
        # each has data at least once, instead of waiting for the steady-state
        # per-symbol spacing. See update().
        self.eager_fetch_on_startup = gc.get('eager_fetch_on_startup', True)

        # Independent publisher / age styling — 0/'' auto-defaults to a small,
        # pixel-perfect size and font rather than matching the headline, so
        # the source/age read as a quiet afterthought instead of competing
        # with it for space. The 4x6 bitmap font rasterizes crisply at its
        # native 7px grid (see PIXEL_FONT_GRIDS) -- much cleaner at small
        # sizes than scaling PressStart2P down off its own 8px grid.
        raw_pub_fs = gc.get('publisher_font_size', 0)
        self.publisher_font_path = gc.get('publisher_font_path') or 'assets/fonts/4x6-font.ttf'
        self.publisher_font_size = (int(raw_pub_fs) if raw_pub_fs and int(raw_pub_fs) > 0
                                     else self._default_small_font_size(self.publisher_font_path))

        raw_age_fs = gc.get('age_font_size', 0)
        self.age_font_path = gc.get('age_font_path') or 'assets/fonts/4x6-font.ttf'
        self.age_font_size = (int(raw_age_fs) if raw_age_fs and int(raw_age_fs) > 0
                               else self._default_small_font_size(self.age_font_path))

        # Price coloring: 'fixed' always uses text_color; 'change' colors the
        # price green/red based on movement since market open.
        self.price_color_mode = gc.get('price_color_mode', 'fixed')

        # Colours
        self.text_color: Tuple = self._parse_color(fc.get('text_color'), [0, 255, 0])
        self.symbol_color: Tuple = self._parse_color(fc.get('symbol_color'), [255, 255, 0])
        self.publisher_color: Tuple = self._parse_color(fc.get('publisher_color'), [110, 110, 110])
        self.age_color: Tuple = self._parse_color(fc.get('age_color'), [110, 110, 110])
        self.price_up_color: Tuple = self._parse_color(fc.get('price_up_color'), [0, 255, 0])
        self.price_down_color: Tuple = self._parse_color(fc.get('price_down_color'), [255, 59, 48])

        # Rate limiting
        self.update_interval = gc.get('update_interval_seconds', 900)
        self.max_daily_requests = gc.get('max_daily_requests', 200)
        self.max_requests_per_hour = gc.get('max_requests_per_hour', 50)

        # Market hours
        self.respect_market_hours = gc.get('respect_market_hours', True)
        self.off_hours_multiplier = gc.get('off_hours_multiplier', 4)

        # Stale threshold
        self.stale_threshold_multiplier = gc.get('stale_threshold_multiplier', 2)

        # Background service
        self.background_config = gc.get('background_service', {
            'enabled': True, 'request_timeout': 30,
        })

    # -------------------------------------------------------------------------
    # Font / scroll
    # -------------------------------------------------------------------------

    #: Press Start 2P draws on an 8px grid; the 4x6 fallback on a 7px one.
    PIXEL_FONT_GRIDS = {'PressStart2P-Regular.ttf': 8, '4x6-font.ttf': 7}

    def _snap_to_font_grid(self, size: int) -> int:
        """Round an auto-derived size to the configured font's pixel grid."""
        font_name = Path(
            self.global_config.get('font_path', 'assets/fonts/PressStart2P-Regular.ttf')
        ).name
        grid = self.PIXEL_FONT_GRIDS.get(font_name, 0)
        if grid <= 0:
            return size
        return max(grid, int(round(size / grid)) * grid)

    def _default_small_font_size(self, font_path: str) -> int:
        """Small pixel-perfect default size for the publisher/age segments:
        the font's own design grid when known (crisp, no partial-pixel
        strokes), else half the headline size."""
        grid = self.PIXEL_FONT_GRIDS.get(Path(font_path).name, 0)
        return grid if grid > 0 else max(5, self.font_size // 2)

    @staticmethod
    def _pixel_draw(image: Image.Image) -> ImageDraw.ImageDraw:
        """
        Build an ImageDraw that renders text crisply on the LED grid.

        PIL anti-aliases by default, blending glyph edges into dim partial-lit
        pixels. On a 1:1 LED matrix those read as blur rather than smoothing --
        at the size this ticker auto-picks for a 32px panel, better than half of
        the lit pixels were partial. ``fontmode = "1"`` switches FreeType to
        1-bit rendering so every pixel is fully on or fully off.

        Every draw surface in this plugin -- including the throwaway ones used
        only to measure text -- goes through here, so measurement and rendering
        can never disagree about glyph metrics.
        """
        draw = ImageDraw.Draw(image)
        draw.fontmode = "1"
        return draw

    def _load_font(self, path: str, size: int) -> Optional[ImageFont.FreeTypeFont]:
        """Two-level fallback: given TTF → 4x6 bitmap. Returns None if neither loads."""
        for p in [path, 'assets/fonts/4x6-font.ttf']:
            try:
                font = ImageFont.truetype(p, size)
                self.logger.debug("[Stock News] Font: %s @ %dpx", p, size)
                return font
            except IOError:
                continue
        return None

    def _load_fonts(self) -> dict:
        """Load the main headline/symbol font plus independently configurable
        publisher and age fonts, each falling back to the main font on failure."""
        self._main_font_path = self.global_config.get('font_path', 'assets/fonts/PressStart2P-Regular.ttf')
        main_font = self._load_font(self._main_font_path, self.font_size)
        if main_font is None:
            self.logger.warning("[Stock News] No TTF font found, using PIL default")
            return {}

        publisher_font = self._load_font(self.publisher_font_path, self.publisher_font_size) or main_font
        age_font = self._load_font(self.age_font_path, self.age_font_size) or main_font

        return {'headline': main_font, 'symbol': main_font,
                'publisher': publisher_font, 'age': age_font}

    def _configure_scroll_settings(self) -> None:
        """Apply scroll speed / FPS to ScrollHelper using frame-based scrolling."""
        if 'scroll_pixels_per_second' in self.global_config:
            pps = float(self.global_config['scroll_pixels_per_second'])
        elif self.scroll_delay and self.scroll_delay > 0:
            pps = self.scroll_speed / self.scroll_delay
        else:
            pps = 25.0

        if 'scroll_target_fps' in self.global_config:
            fps = float(self.global_config['scroll_target_fps'])
        elif self.scroll_delay and self.scroll_delay > 0:
            fps = 1.0 / self.scroll_delay
        else:
            fps = 100.0

        # Convert to per-frame advancement for smooth, consistent scrolling.
        # Frame-based mode advances exactly pixels_per_frame each frame regardless
        # of wall-clock jitter, preventing multi-pixel jumps on slow frames.
        _MIN_PPF = 0.1  # minimum pixels-per-frame the scroll helper accepts
        pixels_per_frame = pps / fps if fps > 0 else pps / 100.0
        if pixels_per_frame < _MIN_PPF:
            # Lower effective FPS to preserve requested px/s rather than bumping px/frame
            effective_fps = min(fps, max(1.0, int(pps / _MIN_PPF)))
            pixels_per_frame = pps / effective_fps
        else:
            effective_fps = fps
        pixels_per_frame = min(5.0, pixels_per_frame)  # retain upper clamp

        if hasattr(self.scroll_helper, 'set_frame_based_scrolling'):
            self.scroll_helper.set_frame_based_scrolling(True)
        if hasattr(self.scroll_helper, 'set_scroll_delay'):
            self.scroll_helper.set_scroll_delay(1.0 / effective_fps)
        self.scroll_helper.set_scroll_speed(pixels_per_frame)

        if hasattr(self.scroll_helper, 'set_target_fps'):
            self.scroll_helper.set_target_fps(fps)

        self.logger.info(
            "[Stock News] Scroll: %.2f px/frame at %.0f FPS (%.1f px/s)",
            pixels_per_frame, fps, pixels_per_frame * fps,
        )

        self.scroll_helper.set_dynamic_duration_settings(
            enabled=self.dynamic_duration,
            min_duration=self.min_duration,
            max_duration=self.max_duration,
        )

    def _register_fonts(self) -> None:
        try:
            if not hasattr(self.plugin_manager, 'font_manager'):
                return
            fm = self.plugin_manager.font_manager
            fm.register_manager_font(self.plugin_id, f"{self.plugin_id}.headline",
                                     "press_start", self.font_size, self.text_color)
            fm.register_manager_font(self.plugin_id, f"{self.plugin_id}.symbol",
                                     "press_start", self.font_size, self.symbol_color)
            fm.register_manager_font(self.plugin_id, f"{self.plugin_id}.publisher",
                                     "four_by_six", self.publisher_font_size, self.publisher_color)
            fm.register_manager_font(self.plugin_id, f"{self.plugin_id}.age",
                                     "four_by_six", self.age_font_size, self.age_color)
        except Exception as e:
            self.logger.warning("[Stock News] Font registration error: %s", e)

    def _create_session(self) -> requests.Session:
        session = requests.Session()
        retry = Retry(total=4, backoff_factor=1,
                      status_forcelist=[429, 500, 502, 503, 504],
                      allowed_methods=["GET"])
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.headers.update({'User-Agent': 'LEDMatrix/2.0 (stock-news plugin)'})
        return session

    # -------------------------------------------------------------------------
    # Update — spread symbol fetches across time
    # -------------------------------------------------------------------------

    def update(self) -> None:
        if not self.initialized:
            return

        now = time.time()
        configured_symbols = self.feeds_config.get('stock_symbols', [])
        synced_symbols = self._get_stocks_plugin_symbols()
        # Merge: configured first, then any extras from stocks plugin (deduped, order preserved)
        stock_symbols = list(dict.fromkeys(configured_symbols + synced_symbols))
        custom_feeds = self._get_custom_feeds()
        fetched = False

        # Per-symbol interval: spread all symbols evenly within update_interval
        n = max(len(stock_symbols), 1)
        per_sym = max(60.0, self.update_interval / n)
        if not self._is_market_hours():
            per_sym = per_sym * self.off_hours_multiplier

        # Eager fill: on a fresh start (or after symbols are added via config
        # change) every symbol starts with zero cached headlines, and the
        # steady-state schedule below only fetches one symbol every `per_sym`
        # seconds — with 3 symbols on a 900s interval that's a 5-minute wait
        # per symbol, leaving the ticker sparse for a long time. Prioritize
        # any never-fetched symbol at plain update() cadence (ignoring
        # per_sym spacing, still budget-checked) until every symbol has data
        # at least once, then fall back to the normal spread schedule.
        unseen = [s for s in stock_symbols if s not in self._symbol_data] if self.eager_fetch_on_startup else []

        if unseen:
            symbol = unseen[0]
            max_h = self._get_symbol_max_headlines(symbol)
            items = self._fetch_stock_news(symbol, max_h)
            self._symbol_data[symbol] = items
            self._fetch_index = (stock_symbols.index(symbol) + 1) % len(stock_symbols)
            self._last_symbol_fetch = now
            fetched = True
        # Fetch exactly one symbol per call (rotating)
        elif stock_symbols and (now - self._last_symbol_fetch) >= per_sym:
            idx = self._fetch_index % len(stock_symbols)
            symbol = stock_symbols[idx]
            max_h = self._get_symbol_max_headlines(symbol)
            items = self._fetch_stock_news(symbol, max_h)
            self._symbol_data[symbol] = items
            self._fetch_index = (self._fetch_index + 1) % len(stock_symbols)
            self._last_symbol_fetch = now
            fetched = True

        # Custom feeds: one at a time, each at full update_interval
        for feed_name, feed_url in custom_feeds.items():
            last = self._feed_last_fetch.get(feed_name, 0)
            if now - last >= self.update_interval:
                items = self._fetch_rss_feed(feed_name, feed_url,
                                             max_items=self.headlines_per_rotation)
                self._symbol_data[f"_feed_{feed_name}"] = items
                self._feed_last_fetch[feed_name] = now
                fetched = True
                break  # one feed per update() call

        if fetched:
            self._rebuild_all_news_items()

    def _get_stocks_plugin_symbols(self) -> List[str]:
        """Return equity symbols from the ledmatrix-stocks plugin when sync is enabled."""
        if not self.sync_with_stocks_plugin:
            return []
        try:
            stocks_plugin = self.plugin_manager.get_plugin('ledmatrix-stocks')
            if stocks_plugin is None:
                return []
            stocks_cfg = getattr(stocks_plugin, 'config', {})
            symbols = stocks_cfg.get('stocks', {}).get('symbols', [])
            # Exclude index symbols (^GSPC) and crypto pairs (-USD, -USDT, -BTC, -ETH, -USDC)
            # Hyphenated equities like BRK-B and BF-B are preserved intentionally
            _CRYPTO_SUFFIXES = ('-USD', '-USDT', '-BTC', '-ETH', '-USDC', '-BUSD', '-EUR', '-GBP')
            equity = [
                s for s in symbols
                if s and not s.startswith('^') and not any(s.endswith(sfx) for sfx in _CRYPTO_SUFFIXES)
            ]
            return equity
        except Exception as e:
            self.logger.debug("[Stock News] Could not read ledmatrix-stocks symbols: %s", e)
            return []

    def _rebuild_all_news_items(self) -> None:
        """Rebuild all_news_items from per-symbol cached data."""
        configured = self.feeds_config.get('stock_symbols', [])
        stock_symbols = list(dict.fromkeys(configured + self._get_stocks_plugin_symbols()))
        custom_feeds = self._get_custom_feeds()

        all_items: list = []
        for sym in stock_symbols:
            all_items.extend(self._symbol_data.get(sym, []))
        for fn in custom_feeds:
            all_items.extend(self._symbol_data.get(f"_feed_{fn}", []))

        max_total = (
            sum(self._get_symbol_max_headlines(s) for s in stock_symbols)
            + len(custom_feeds) * self.headlines_per_rotation
        )
        self.all_news_items = all_items[:max_total] if len(all_items) > max_total else all_items

        if self.shuffle_headlines and self.all_news_items:
            random.shuffle(self.all_news_items)

        self.last_update = time.time()
        self.scroll_helper.clear_cache()
        self.scroll_helper.reset_scroll()
        self._vegas_cache = None
        self._rotation_count = 0
        self._items_rotated = 0
        self.logger.info("[Stock News] Rebuilt: %d items (%d symbols, %d custom feeds)",
                         len(self.all_news_items), len(stock_symbols), len(custom_feeds))

    # -------------------------------------------------------------------------
    # Data fetching
    # -------------------------------------------------------------------------

    def _get_symbol_max_headlines(self, symbol: str) -> int:
        """Return per-symbol headline limit, supporting int or dict config."""
        cfg = self.max_headlines_per_symbol
        if isinstance(cfg, dict):
            return int(cfg.get(symbol, cfg.get('default', 1)))
        return int(cfg)

    def _fetch_stock_news(self, symbol: str, max_h: int) -> List[Dict]:
        """Try YF search API first; fall back to RSS."""
        items = self._fetch_yf_api(symbol, max_h)
        if items:
            return items
        self.logger.debug("[Stock News] RSS fallback for %s", symbol)
        url = _YAHOO_RSS.format(symbol=symbol)
        items = self._fetch_rss_feed(symbol, url, max_items=max_h)
        for item in items:
            item['symbol'] = symbol
        return items

    def _fetch_yf_api(self, symbol: str, max_h: int) -> List[Dict]:
        """Yahoo Finance search API — returns publisher, timestamp, optional price."""
        bucket = int(time.time() // self.update_interval)
        cache_key = f"stock_yf_{symbol}_{bucket}"
        cached = self.cache_manager.get(cache_key)
        if cached:
            self.logger.debug("[Stock News] Cache hit (YF): %s", symbol)
            return cached

        if not self._check_request_budget():
            self.logger.warning("[Stock News] Budget exceeded — skipping %s", symbol)
            return []

        params = {
            'q': symbol,
            'lang': 'en-US',
            'region': 'US',
            'quotesCount': 1 if self.show_price else 0,
            'newsCount': max_h,
            'enableFuzzyQuery': False,
        }
        try:
            timeout = self.background_config.get('request_timeout', 30)
            resp = self._session.get(_YAHOO_SEARCH, params=params, timeout=timeout)
            self._record_request()  # count any response, including 4xx/5xx
            resp.raise_for_status()

            data = resp.json()

            # Extract price (and change since open, for up/down coloring) from quote if requested
            price: Optional[float] = None
            price_change: Optional[float] = None
            if self.show_price:
                quotes = data.get('quotes', [])
                if quotes:
                    price = quotes[0].get('regularMarketPrice') or quotes[0].get('price')
                    price_change = quotes[0].get('regularMarketChange')

            items: List[Dict] = []
            for raw in data.get('news', [])[:max_h]:
                title = raw.get('title', '').strip()
                if not title:
                    continue
                pub_ts = float(raw.get('providerPublishTime', 0) or 0)
                items.append({
                    'symbol': symbol,
                    'feed_name': symbol,
                    'title': self._clean_headline(title),
                    'link': raw.get('link', ''),
                    'publisher': raw.get('publisher', ''),
                    'published_ts': pub_ts,   # unix float — cache-safe
                    'price': price,
                    'price_change': price_change,
                })

            self.cache_manager.set(cache_key, items, ttl=self.update_interval * 2)
            self.logger.info("[Stock News] YF API: %d items for %s%s",
                             len(items), symbol,
                             f" @ ${price:.2f}" if price else "")
            return items

        except requests.RequestException as e:
            self.logger.warning("[Stock News] YF API error for %s: %s", symbol, e)
        except (ValueError, KeyError) as e:
            self.logger.warning("[Stock News] YF API parse error for %s: %s", symbol, e)
        except Exception as e:
            self.logger.warning("[Stock News] YF API unexpected error for %s: %s", symbol, e)
        return []

    def _fetch_rss_feed(self, feed_name: str, url: str, max_items: int = 3) -> List[Dict]:
        """Fetch and parse any RSS feed with caching and budget enforcement."""
        bucket = int(time.time() // self.update_interval)
        cache_key = f"stock_rss_{feed_name}_{bucket}"
        cached = self.cache_manager.get(cache_key)
        if cached:
            self.logger.debug("[Stock News] Cache hit (RSS): %s", feed_name)
            return cached

        if not self._check_request_budget():
            self.logger.warning("[Stock News] Budget exceeded — skipping RSS %s", feed_name)
            return []

        try:
            timeout = self.background_config.get('request_timeout', 30)
            resp = self._session.get(url, timeout=timeout)
            self._record_request()  # count any response, including 4xx/5xx
            resp.raise_for_status()

            root = ET.fromstring(resp.content)
            items: List[Dict] = []
            for rss_item in root.findall('.//item')[:max_items]:
                title_el = rss_item.find('title')
                if title_el is None or not title_el.text:
                    continue
                link_el = rss_item.find('link')
                pub_el = rss_item.find('pubDate')
                # Try to parse pubDate to unix timestamp
                pub_ts = 0.0
                if pub_el is not None and pub_el.text:
                    try:
                        from email.utils import parsedate_to_datetime
                        pub_ts = parsedate_to_datetime(pub_el.text).timestamp()
                    except Exception:
                        pass
                items.append({
                    'feed_name': feed_name,
                    'title': self._clean_headline(html.unescape(title_el.text.strip())),
                    'link': (link_el.text or '') if link_el is not None else '',
                    'publisher': '',
                    'published_ts': pub_ts,
                    'price': None,
                })

            self.cache_manager.set(cache_key, items, ttl=self.update_interval * 2)
            self.logger.info("[Stock News] RSS: %d items for %s", len(items), feed_name)
            return items

        except requests.RequestException as e:
            self.logger.error("[Stock News] RSS error for %s: %s", feed_name, e)
        except ET.ParseError as e:
            self.logger.error("[Stock News] RSS parse error for %s: %s", feed_name, e)
        except Exception as e:
            self.logger.error("[Stock News] RSS unexpected error for %s: %s", feed_name, e)
        return []

    def _check_request_budget(self) -> bool:
        today = datetime.now().strftime('%Y-%m-%d')
        if not hasattr(self, '_last_reset_date'):
            self._last_reset_date = ''
            self._requests_today = 0
            self._request_timestamps: list = []
        if self._last_reset_date != today:
            self._requests_today = 0
            self._last_reset_date = today
        if self._requests_today >= self.max_daily_requests:
            return False
        cutoff = time.time() - 3600
        self._request_timestamps = [t for t in self._request_timestamps if t > cutoff]
        return len(self._request_timestamps) < self.max_requests_per_hour

    def _record_request(self) -> None:
        self._requests_today += 1
        self._request_timestamps.append(time.time())

    def _check_budget_adequacy(self) -> None:
        """Warn at startup if symbol count may exhaust the hourly request budget."""
        stock_symbols = self.feeds_config.get('stock_symbols', [])
        custom_feeds = self._get_custom_feeds()
        n = max(len(stock_symbols), 1)
        per_sym = max(60.0, self.update_interval / n)
        sym_per_hour = 3600.0 / per_sym
        custom_per_hour = (3600.0 / self.update_interval) * len(custom_feeds)
        total_per_hour = sym_per_hour + custom_per_hour

        if total_per_hour > self.max_requests_per_hour:
            self.logger.warning(
                "[Stock News] Budget mismatch: ~%.0f req/hr estimated but limit is %d/hr. "
                "Raise max_requests_per_hour to %d, or reduce symbols from %d.",
                total_per_hour, self.max_requests_per_hour,
                int(total_per_hour) + 5, len(stock_symbols),
            )
        else:
            self.logger.info(
                "[Stock News] Budget OK: ~%.0f req/hr (%d symbols spread %.0fs apart, limit %d/hr)",
                total_per_hour, len(stock_symbols), per_sym, self.max_requests_per_hour,
            )

    def _is_market_hours(self) -> bool:
        """Approximate US equity market hours without external dependencies.

        Covers 9:00–16:30 ET in both EDT (UTC-4) and EST (UTC-5) by using
        a conservative UTC window of 13:00–22:00, Mon–Fri.
        """
        if not self.respect_market_hours:
            return True
        now = datetime.utcnow()
        if now.weekday() >= 5:
            return False
        h = now.hour + now.minute / 60.0
        return 13.0 <= h <= 22.0

    def _is_data_stale(self) -> bool:
        if self.last_update == 0:
            return False
        return (time.time() - self.last_update) > (self.update_interval * self.stale_threshold_multiplier)

    def _clean_headline(self, headline: str) -> str:
        if not headline:
            return ""
        headline = re.sub(r'\s+', ' ', headline.strip())
        headline = re.sub(r'^\s*-\s*', '', headline)
        limit = getattr(self, 'max_headline_length', 120)
        if len(headline) > limit:
            headline = headline[:limit - 3] + "..."
        return headline

    def _format_age(self, pub_ts: float) -> str:
        """Format a unix timestamp as a human-readable relative age."""
        if not pub_ts:
            return ""
        try:
            delta = time.time() - pub_ts
            if delta < 60:
                return "just now"
            elif delta < 3600:
                return f"{int(delta // 60)}m ago"
            elif delta < 86400:
                return f"{int(delta // 3600)}h ago"
            else:
                return f"{int(delta // 86400)}d ago"
        except Exception:
            return ""

    # -------------------------------------------------------------------------
    # Logo fetching
    # -------------------------------------------------------------------------

    def _get_symbol_logo(self, symbol: str) -> Optional[Image.Image]:
        """Return a logo PIL Image sized to display_height, downloading once if needed.

        Logos are constrained by height only (max_width is generous) so landscape
        company logos render at full panel height without being squeezed into a square.
        Failed downloads are remembered for the session to avoid repeated attempts.
        """
        if not self.logo_fetch_enabled:
            return None
        if symbol in self._logo_failed:
            return None

        # Sanitize symbol to safe filename characters — prevents path traversal
        safe_name = re.sub(r'[^A-Za-z0-9.\-]', '_', symbol)[:20]

        # Width can be up to 4× height — lets landscape logos breathe
        max_w = self.logo_size * 4

        logo_path = self._logo_dir / f"{safe_name}.png"
        if logo_path.exists():
            return self.logo_helper.load_logo(safe_name, logo_path,
                                              max_width=max_w,
                                              max_height=self.logo_size)

        # Download and cache to disk on first use (URL uses original symbol)
        url = self.logo_url_template.replace('{symbol}', symbol)
        try:
            resp = self._session.get(url, timeout=10)
            if resp.status_code == 200 and resp.content:
                logo_path.write_bytes(resp.content)
                self.logger.info("[Stock News] Downloaded logo for %s", symbol)
                return self.logo_helper.load_logo(safe_name, logo_path,
                                                  max_width=max_w,
                                                  max_height=self.logo_size)
            self.logger.debug("[Stock News] Logo not available for %s (HTTP %d)",
                              symbol, resp.status_code)
        except Exception as e:
            self.logger.debug("[Stock News] Logo fetch failed for %s: %s", symbol, e)

        self._logo_failed.add(symbol)
        return None

    # -------------------------------------------------------------------------
    # Display
    # -------------------------------------------------------------------------

    def display(self, display_mode: Optional[str] = None, force_clear: bool = False) -> None:
        if not self.initialized:
            self._display_error("Stock news ticker not initialized")
            return

        if not self.all_news_items:
            self._display_no_news()
            return

        # Rebuild if stale state changed (dimmed ↔ normal colours)
        currently_stale = self._is_data_stale()
        if currently_stale != self._was_stale:
            self._was_stale = currently_stale
            self.scroll_helper.clear_cache()
            self._vegas_cache = None

        if not self.scroll_helper.cached_image or force_clear:
            self._create_scrolling_image()
            if not self.scroll_helper.cached_image:
                self._display_no_news()
                return
            self._cycle_complete = False

        if force_clear:
            self.scroll_helper.reset_scroll()
            self._cycle_complete = False

        self.display_manager.set_scrolling_state(True)
        self.display_manager.process_deferred_updates()

        self.scroll_helper.update_scroll_position()

        if self.scroll_helper.is_scroll_complete():
            self._cycle_complete = True
            if self.rotation_enabled:
                self._rotation_count += 1
                if self._rotation_count >= self.rotation_threshold:
                    self._rotation_count = 0
                    self._rotate_headlines()
                    self.scroll_helper.clear_cache()
                    self.scroll_helper.reset_scroll()
                    return

        visible_portion = self.scroll_helper.get_visible_portion()
        if visible_portion:
            self.display_manager.image.paste(visible_portion, (0, 0))
            self.display_manager.update_display()

        self.scroll_helper.log_frame_rate()

    def _create_scrolling_image(self) -> None:
        try:
            item_images = [img for img in
                           (self._render_news_item(item) for item in self.all_news_items)
                           if img is not None]
            if not item_images:
                self.scroll_helper.clear_cache()
                return
            self.scroll_helper.create_scrolling_image(item_images, item_gap=self.item_gap)
            self._cycle_complete = False
            self.logger.info("[Stock News] Ticker: %d items, %dpx wide, gap=%dpx",
                             len(item_images), self.scroll_helper.total_scroll_width, self.item_gap)
        except Exception as e:
            self.logger.error("[Stock News] Failed to build ticker: %s", e)
            self.scroll_helper.clear_cache()

    def _render_news_item(self, news_item: dict) -> Optional[Image.Image]:
        """
        Render one news item as a full-height image strip with per-segment colours.

        Segments drawn left-to-right:
          logo (optional) | symbol: | $price | headline | • publisher | • age

        Publisher and age are independent segments (own colour/font/size each),
        not a single combined suffix string.
        """
        try:
            symbol = news_item.get('symbol', news_item.get('feed_name', '?'))
            title = news_item.get('title', '')
            publisher = news_item.get('publisher', '')
            pub_ts = news_item.get('published_ts', 0)
            price = news_item.get('price')
            price_change = news_item.get('price_change')

            font_sym = self._fonts.get('symbol')
            font_hl = self._fonts.get('headline')
            font_pub = self._fonts.get('publisher', font_hl)
            font_age = self._fonts.get('age', font_hl)

            logo = (self._get_symbol_logo(symbol)
                    if self.display_style in ('logo_and_ticker', 'logo_only') else None)

            # Stale: dim all colours
            stale = self._is_data_stale()
            sym_c = (80, 60, 0) if stale else self.symbol_color
            txt_c = (0, 80, 0) if stale else self.text_color
            pub_c = (60, 60, 60) if stale else self.publisher_color
            age_c = (60, 60, 60) if stale else self.age_color
            price_up_c = (0, 40, 0) if stale else self.price_up_color
            price_down_c = (40, 0, 0) if stale else self.price_down_color

            price_c = txt_c
            if self.price_color_mode == 'change' and price_change is not None:
                if price_change > 0:
                    price_c = price_up_c
                elif price_change < 0:
                    price_c = price_down_c

            # Build text segments: (text, colour, font)
            segments: List[Tuple[str, tuple, Any]] = []

            if self.display_style == 'logo_only':
                segments.append((f" {symbol}", sym_c, font_sym))
                if self.show_price and price is not None:
                    segments.append((f"  ${price:.2f}", price_c, font_sym))
            else:
                segments.append((f"{symbol}: ", sym_c, font_sym))
                if self.show_price and price is not None:
                    segments.append((f"${price:.2f}  ", price_c, font_hl))
                if title:
                    segments.append((title, txt_c, font_hl))
                # Publisher and age are independently styled (colour, font, size) —
                # rendered as separate segments, each with its own separator
                # prefix. Single-space padding keeps them a tight, closely-spaced
                # afterthought rather than a wide gap. A plain hyphen is used
                # (not a bullet glyph) since the small 4x6 pixel font -- the
                # default for these segments -- has no "•"/"·" in its glyph set.
                if self.show_publisher and publisher:
                    segments.append((" - " + publisher, pub_c, font_pub))
                if self.show_age and pub_ts:
                    age = self._format_age(pub_ts)
                    if age:
                        segments.append((" - " + age, age_c, font_age))

            # Measure segments. Each segment's own text height is kept (not
            # just the tallest one) so smaller publisher/age text can be
            # vertically centered on its own -- centering everything on the
            # headline's height would leave the smaller text hugging the top
            # instead of sitting level with it.
            draw_tmp = self._pixel_draw(Image.new('RGB', (1, 1)))
            widths: List[int] = []
            heights: List[int] = []
            for text, _, font in segments:
                if text:
                    bb = draw_tmp.textbbox((0, 0), text, font=font)
                    widths.append(bb[2] - bb[0])
                    heights.append(bb[3] - bb[1])
                else:
                    widths.append(0)
                    heights.append(0)

            logo_w = (logo.width + 4) if logo else 0
            total_w = max(logo_w + sum(widths), 1)

            img = Image.new('RGB', (total_w, self.display_height), (0, 0, 0))
            draw = self._pixel_draw(img)

            x = 0
            if logo:
                logo_y = max(0, (self.display_height - logo.height) // 2)
                mask = logo if logo.mode == 'RGBA' else None
                img.paste(logo, (x, logo_y), mask)
                x += logo.width + 4

            for (text, color, font), w, h in zip(segments, widths, heights):
                if text and w > 0:
                    y = max(0, (self.display_height - h) // 2)
                    draw.text((x, y), text, fill=color, font=font)
                    x += w

            return img

        except Exception as e:
            self.logger.warning("[Stock News] Render error: %s", e)
            return None

    def _rotate_headlines(self) -> None:
        if len(self.all_news_items) <= 1:
            return
        first = self.all_news_items[0]
        self.all_news_items = self.all_news_items[1:] + [first]
        self._items_rotated += 1
        self.logger.info("[Stock News] Rotated: '%s...' → end | '%s...' now first",
                         first.get('title', '')[:40],
                         self.all_news_items[0].get('title', '')[:40])
        if self.shuffle_headlines and self._items_rotated >= len(self.all_news_items):
            random.shuffle(self.all_news_items)
            self._items_rotated = 0
            self.logger.info("[Stock News] Full cycle — reshuffled")
        self._vegas_cache = None

    # -------------------------------------------------------------------------
    # Vegas scroll mode
    # -------------------------------------------------------------------------

    def get_vegas_content(self) -> Optional[list]:
        if not self.all_news_items:
            return None
        if self._vegas_cache is None:
            rendered = [self._render_news_item(item) for item in self.all_news_items]
            self._vegas_cache = [img for img in rendered if img is not None]
            total_px = sum(img.width for img in self._vegas_cache)
            self.logger.info("[Stock News] Vegas cache: %d items, %dpx total",
                             len(self._vegas_cache), total_px)
        return self._vegas_cache or None

    def get_vegas_content_type(self) -> str:
        return 'multi'

    # -------------------------------------------------------------------------
    # Fallback displays
    # -------------------------------------------------------------------------

    def _display_no_news(self) -> None:
        img = Image.new('RGB', (self.display_width, self.display_height), (0, 0, 0))
        draw = self._pixel_draw(img)
        text = "No Stock News"
        font = self._fit_fallback_font(draw, text)
        try:
            bb = draw.textbbox((0, 0), text, font=font)
            x = max(0, (self.display_width - (bb[2] - bb[0])) // 2)
            y = max(0, (self.display_height - (bb[3] - bb[1])) // 2)
            draw.text((x, y), text, fill=(180, 180, 180), font=font)
        except Exception:
            draw.text((4, self.display_height // 2 - 4), text, fill=(180, 180, 180))
        self.display_manager.image = img.copy()
        self.display_manager.update_display()

    def _fit_fallback_font(self, draw: ImageDraw.ImageDraw, text: str) -> Optional[ImageFont.FreeTypeFont]:
        """Pick the largest size <= self.font_size that fits `text` within
        display_width, for one-off fallback/error text.

        self.font_size is derived from display *height* only
        (_apply_config, "height // 3") -- correct for the scrolling
        headline ticker, which is free to run wider than the panel. A
        static, centered fallback message doesn't have that luxury: on the
        real 192x48 hardware panel (a taller panel, so a bigger derived
        font) "No Stock News" was wide enough to clip its trailing
        character against the canvas edge. This shrinks just for this
        message, leaving the scrolling ticker's own sizing untouched.
        """
        font = self._fonts.get('headline')
        if font is None or not hasattr(self, '_main_font_path'):
            return font
        for size in range(self.font_size, 5, -1):
            candidate = self._load_font(self._main_font_path, size)
            if candidate is None:
                break  # font file itself unavailable at this size; give up shrinking
            bb = draw.textbbox((0, 0), text, font=candidate)
            if (bb[2] - bb[0]) <= self.display_width:
                return candidate
            font = candidate  # smallest-so-far, in case we hit the floor without fitting
        return font

    def _display_error(self, message: str) -> None:
        img = Image.new('RGB', (self.display_width, self.display_height), (0, 0, 0))
        draw = self._pixel_draw(img)
        draw.text((4, self.display_height // 2 - 4), message, fill=(255, 0, 0))
        self.display_manager.image = img.copy()
        self.display_manager.update_display()

    # -------------------------------------------------------------------------
    # Config hot-reload
    # -------------------------------------------------------------------------

    def on_config_change(self, new_config: Dict[str, Any]) -> None:
        super().on_config_change(new_config)

        old_symbols = set(self.feeds_config.get('stock_symbols', []))
        old_custom_map = self._get_custom_feeds().copy()
        old_font_size = self.font_size
        old_font_path = self.global_config.get('font_path', '')
        old_publisher_font_size = getattr(self, 'publisher_font_size', 0)
        old_publisher_font_path = getattr(self, 'publisher_font_path', '')
        old_age_font_size = getattr(self, 'age_font_size', 0)
        old_age_font_path = getattr(self, 'age_font_path', '')

        self.feeds_config = new_config.get('feeds', {})
        self.global_config = new_config.get('global', {})
        self._apply_config()
        self._configure_scroll_settings()

        font_changed = (self.font_size != old_font_size or
                        self.global_config.get('font_path', '') != old_font_path or
                        self.publisher_font_size != old_publisher_font_size or
                        self.publisher_font_path != old_publisher_font_path or
                        self.age_font_size != old_age_font_size or
                        self.age_font_path != old_age_font_path)
        if font_changed:
            self._fonts = self._load_fonts()
            self._register_fonts()
            self.logger.info("[Stock News] Fonts reloaded at %dpx", self.font_size)

        new_symbols = set(self.feeds_config.get('stock_symbols', []))
        new_custom_map = self._get_custom_feeds()
        old_custom_keys = set(old_custom_map.keys())
        new_custom_keys = set(new_custom_map.keys())

        # Clear state for any feed whose URL changed (same name, different URL)
        for name in new_custom_keys & old_custom_keys:
            if new_custom_map[name] != old_custom_map.get(name):
                self._symbol_data.pop(f"_feed_{name}", None)
                self._feed_last_fetch.pop(name, None)
                self.logger.info("[Stock News] Feed URL changed for '%s' — will refetch", name)

        if new_symbols != old_symbols or new_custom_keys != old_custom_keys:
            # Drop stale per-symbol data for removed feeds
            for removed in (old_symbols - new_symbols):
                self._symbol_data.pop(removed, None)
            self.logger.info("[Stock News] Feed config changed — will refetch next cycle")
            self._last_symbol_fetch = 0  # trigger immediate fetch on next update()

        self._check_budget_adequacy()
        self.scroll_helper.clear_cache()
        self.scroll_helper.reset_scroll()
        self._vegas_cache = None

    # -------------------------------------------------------------------------
    # Utility
    # -------------------------------------------------------------------------

    def get_display_duration(self) -> float:
        if self.dynamic_duration:
            d = self.scroll_helper.get_dynamic_duration()
            if d > 0:
                return float(d)
        return float(self.display_duration)

    def get_info(self) -> Dict[str, Any]:
        info = super().get_info()
        stock_symbols = self.feeds_config.get('stock_symbols', [])
        info.update({
            'total_news_items': len(self.all_news_items),
            'stock_symbols': stock_symbols,
            'custom_feeds': list(self._get_custom_feeds().keys()),
            'last_update': self.last_update,
            'data_stale': self._is_data_stale(),
            'is_market_hours': self._is_market_hours(),
            'display_duration': self.display_duration,
            'dynamic_duration': self.dynamic_duration,
            'display_style': self.display_style,
            'font_size': self.font_size,
            'publisher_font_size': self.publisher_font_size,
            'publisher_font_path': self.publisher_font_path,
            'age_font_size': self.age_font_size,
            'age_font_path': self.age_font_path,
            'item_gap': self.item_gap,
            'show_publisher': self.show_publisher,
            'show_age': self.show_age,
            'show_price': self.show_price,
            'price_color_mode': self.price_color_mode,
            'eager_fetch_on_startup': self.eager_fetch_on_startup,
            'shuffle_headlines': self.shuffle_headlines,
            'rotation_enabled': self.rotation_enabled,
            'rotation_threshold': self.rotation_threshold,
            'logo_fetch_enabled': self.logo_fetch_enabled,
            'logo_size': self.logo_size,
            'respect_market_hours': self.respect_market_hours,
            'requests_today': getattr(self, '_requests_today', 0),
            'requests_this_hour': len(getattr(self, '_request_timestamps', [])),
            'max_daily_requests': self.max_daily_requests,
            'max_requests_per_hour': self.max_requests_per_hour,
            'update_interval_seconds': self.update_interval,
            'text_color': self.text_color,
            'symbol_color': self.symbol_color,
            'publisher_color': self.publisher_color,
            'age_color': self.age_color,
            'price_up_color': self.price_up_color,
            'price_down_color': self.price_down_color,
        })
        return info

    def cleanup(self) -> None:
        self.all_news_items = []
        self._symbol_data.clear()
        self._vegas_cache = None
        if hasattr(self, 'scroll_helper'):
            self.scroll_helper.clear_cache()
        if hasattr(self, '_session'):
            self._session.close()
        self.logger.info("[Stock News] Cleaned up")
