"""
News Ticker Plugin for LEDMatrix

Displays scrolling news headlines from RSS feeds including sports news from ESPN,
NCAA updates, and custom RSS sources. Shows breaking news and updates in a
continuous scrolling ticker format.

Features:
- Multiple RSS feed sources (ESPN, NCAA, custom feeds)
- Scrolling headline display
- Headline rotation and cycling
- Custom feed support
- Configurable scroll speed and colors
- Background data fetching

API Version: 1.0.0
"""

import logging
import os
import time
import requests
import xml.etree.ElementTree as ET
import html
import re
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path
from urllib.parse import urlparse
from PIL import Image, ImageDraw, ImageFont

from src.plugin_system.base_plugin import BasePlugin
from src.common.scroll_helper import ScrollHelper
from src.common.logo_helper import LogoHelper

logger = logging.getLogger(__name__)


class NewsTickerPlugin(BasePlugin):
    """
    News ticker plugin for displaying scrolling headlines from RSS feeds.

    Supports multiple predefined feeds (ESPN sports, NCAA) and custom RSS URLs
    with configurable display options and scrolling ticker format.

    Configuration options:
        feeds: Enable/disable predefined and custom RSS feeds
        display_options: Scroll speed, duration, colors, rotation
        background_service: Data fetching configuration
    """

    # Default RSS feeds
    DEFAULT_FEEDS = {
        'MLB': 'https://www.espn.com/espn/rss/mlb/news',
        'NFL': 'https://www.espn.com/espn/rss/nfl/news',
        'NCAA FB': 'https://www.espn.com/espn/rss/ncf/news',
        'NHL': 'https://www.espn.com/espn/rss/nhl/news',
        'NBA': 'https://www.espn.com/espn/rss/nba/news',
        'TOP SPORTS': 'https://www.espn.com/espn/rss/news',
        # Big-Ten-specific via Google News search. ESPN no longer publishes
        # a Big-Ten-only RSS feed (btn.com/feed/ returns HTML, bigten.org/rss
        # 404s, and the prior espn.com/blog/feed?blog=bigten was deprecated).
        'BIG10': 'https://news.google.com/rss/search?q=big+ten+football&hl=en-US&gl=US&ceid=US:en',
        'NCAA': 'https://www.espn.com/espn/rss/ncaa/news',
        'Other': 'https://www.coveringthecorner.com/rss/current.xml'
    }

    # Feed name to logo file mapping
    FEED_LOGO_MAP = {
        'MLB': 'mlbn.png',  # MLB Network logo
        'NFL': 'nfln.png',  # NFL Network logo
        'NCAA FB': 'espn.png',  # ESPN logo
        'NHL': 'espn.png',  # ESPN logo
        'NBA': 'espn.png',  # ESPN logo
        'TOP SPORTS': 'espn.png',  # ESPN logo
        'BIG10': 'espn.png',  # ESPN logo
        'NCAA': 'espn.png',  # ESPN logo
        'Other': 'espn.png'  # Default to ESPN
    }

    # Gaps handed to ScrollHelper.create_scrolling_image(). Kept as constants
    # because page sizing has to measure content with the exact same layout
    # arithmetic the scroll helper uses.
    ITEM_GAP = 32
    ELEMENT_GAP = 16

    # Mirrors DEFAULT_DYNAMIC_DURATION_CAP in the core's display_controller.
    # The controller caps every plugin at min(plugin cap, global cap) and falls
    # back to this value when display.dynamic_duration.max_duration_seconds is
    # unset, so page sizing has to assume the same ceiling — otherwise we build
    # a page longer than the controller will ever let us finish.
    CORE_DEFAULT_DURATION_CAP = 180.0

    def __init__(self, plugin_id: str, config: Dict[str, Any],
                 display_manager, cache_manager, plugin_manager):
        """Initialize the news ticker plugin."""
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)

        # Get display dimensions
        self.display_width = display_manager.width
        self.display_height = display_manager.height

        # Configuration
        self.feeds_config = config.get('feeds', {})
        self.global_config = config.get('global', {})

        # Display settings
        self.display_duration = self.global_config.get('display_duration', 30)
        
        # Scroll configuration - prefer display object (frame-based), fallback to legacy
        display_config = self.global_config.get('display', {})
        if display_config and ('scroll_speed' in display_config or 'scroll_delay' in display_config):
            # New format: use frame-based scrolling
            self.scroll_speed = display_config.get('scroll_speed', 1.0)
            self.scroll_delay = display_config.get('scroll_delay', 0.01)
            self.scroll_pixels_per_second = None
            self.logger.info(f"Using global.display.scroll_speed={self.scroll_speed} px/frame, global.display.scroll_delay={self.scroll_delay}s (frame-based mode)")
        else:
            # Legacy format: use global scroll_speed/scroll_delay
            self.scroll_speed = self.global_config.get('scroll_speed', 1.0)
            self.scroll_delay = self.global_config.get('scroll_delay', 0.01)
            self.scroll_pixels_per_second = self.global_config.get('scroll_pixels_per_second')
            if self.scroll_pixels_per_second is not None:
                self.logger.info(f"Using scroll_pixels_per_second={self.scroll_pixels_per_second} px/s (time-based mode)")
            else:
                self.logger.info(f"Using legacy scroll_speed={self.scroll_speed}, scroll_delay={self.scroll_delay}")

        # Dynamic duration settings
        dynamic_duration_config = self.global_config.get('dynamic_duration', {})
        if isinstance(dynamic_duration_config, bool):
            # Legacy: just a boolean
            self.dynamic_duration_enabled = dynamic_duration_config
            self.min_duration = self.global_config.get('min_duration', 30)
            self.max_duration = self.global_config.get('max_duration', 300)
            self.duration_buffer = self.global_config.get('duration_buffer', 0.1)
        else:
            # New format: object with settings
            self.dynamic_duration_enabled = dynamic_duration_config.get('enabled', True)
            self.min_duration = dynamic_duration_config.get('min_duration_seconds', 30)
            self.max_duration = dynamic_duration_config.get('max_duration_seconds', 300)
            self.duration_buffer = dynamic_duration_config.get('buffer_ratio', 0.1)

        self.rotation_enabled = self.global_config.get('rotation_enabled', True)
        self.rotation_threshold = self.global_config.get('rotation_threshold', 3)
        self.headlines_per_feed = self.global_config.get('headlines_per_feed', 2)
        self.font_size = self.global_config.get('font_size', 12)
        self.target_fps = self.global_config.get('target_fps') or self.global_config.get('scroll_target_fps', 100)

        # Headline paging settings
        self._load_paging_settings()

        # Colors
        self.text_color = tuple(self.feeds_config.get('text_color', [255, 255, 255]))
        self.separator_color = tuple(self.feeds_config.get('separator_color', [255, 0, 0]))

        # Per-element customization block. Headline and separator colors stay on
        # feeds.text_color / feeds.separator_color; customization only adds the
        # per-element fonts plus the source-prefix color that was hardcoded.
        customization = config.get('customization', {}) or {}
        source_text_cfg = customization.get('source_text', {}) or {}
        self.source_color = self._parse_color(source_text_cfg.get('text_color'), (150, 150, 150))

        # Migrate old custom_feeds format to new array format if needed
        self._migrate_custom_feeds_format()
        
        # Logo settings
        self.show_logos = self.feeds_config.get('show_logos', True)
        # Logo size defaults to display height minus 4 pixels for margin, but can be overridden
        default_logo_size = self.display_height - 4 if self.display_height > 4 else self.display_height
        self.logo_size = self.feeds_config.get('logo_size', default_logo_size)
        
        # Feed logo mapping - kept for backward compatibility during migration
        # New format uses logo objects in feed items
        self.feed_logo_map = self.feeds_config.get('feed_logo_map', {})

        # Background service configuration
        self.background_config = self.global_config.get('background_service', {
            'enabled': True,
            'request_timeout': 30,
            'max_retries': 3,
            'priority': 2
        })

        # State
        self.current_headlines = []
        # Headline set the current scroll strip was rendered from
        self._headlines_signature = None
        self.last_update = 0
        self.rotation_count = 0
        self._cycle_complete = False
        self._cycle_complete_at = 0.0
        # Index of the first headline in the page currently on screen, how many
        # headlines that page holds, and whether the next page is queued up but
        # not yet rendered.
        self._page_start = 0
        self._page_count = 0
        self._page_dirty = False
        # Rendered headline images, reused across cycles within one data refresh
        # so paging back and forth doesn't re-rasterise text every cycle.
        self._headline_image_cache: Dict[Tuple[str, str], Optional[Image.Image]] = {}
        self.initialized = True

        # Load fonts, then apply per-element font overrides (no-op at defaults)
        self._font_cache: Dict[Tuple[str, int], Any] = {}
        self.fonts = self._load_fonts()
        self._apply_font_customization(customization)

        # Initialize LogoHelper for news source logos
        self.logo_helper = LogoHelper(
            display_width=self.display_width,
            display_height=self.display_height,
            logger=self.logger
        )

        # Initialize ScrollHelper
        self.scroll_helper = ScrollHelper(self.display_width, self.display_height, logger=self.logger)
        
        # Enable scrolling for high FPS mode
        self.enable_scrolling = True
        self.logger.info(f"News ticker enable_scrolling set to: {self.enable_scrolling}")

        # Configure ScrollHelper with plugin settings
        self._configure_scroll_settings()

        # Log enabled feeds
        enabled_feeds = self.feeds_config.get('enabled_feeds', [])
        custom_feeds = self.feeds_config.get('custom_feeds', [])
        if isinstance(custom_feeds, list):
            custom_feed_names = [feed.get('name', '') for feed in custom_feeds if isinstance(feed, dict)]
        else:
            # Old format fallback
            custom_feed_names = list(custom_feeds.keys()) if isinstance(custom_feeds, dict) else []

        self.logger.info("News ticker plugin initialized")
        self.logger.info(f"Enabled predefined feeds: {enabled_feeds}")
        self.logger.info(f"Custom feeds: {custom_feed_names}")
        self.logger.info(f"Display dimensions: {self.display_width}x{self.display_height}")
        if hasattr(self.scroll_helper, 'frame_based_scrolling') and self.scroll_helper.frame_based_scrolling:
            pixels_per_second = self.scroll_speed / self.scroll_delay if self.scroll_delay > 0 else self.scroll_speed * 100
            self.logger.info(f"Scroll speed: {self.scroll_speed} px/frame, {self.scroll_delay}s delay ({pixels_per_second:.1f} px/s effective)")
        else:
            if hasattr(self, 'scroll_pixels_per_second') and self.scroll_pixels_per_second is not None:
                self.logger.info(f"Scroll speed: {self.scroll_pixels_per_second} px/s")
            else:
                pixels_per_second = self.scroll_speed / self.scroll_delay if self.scroll_delay > 0 else self.scroll_speed * 100
                self.logger.info(f"Scroll speed: {pixels_per_second:.1f} px/s")
        self.logger.info(
            "Dynamic duration settings: enabled=%s, min=%ss, max=%ss, buffer=%.2f",
            self.dynamic_duration_enabled,
            self.min_duration,
            self.max_duration,
            self.duration_buffer,
        )
        if self.paging_enabled:
            self.logger.info(
                "Headline paging enabled: budget=%.0fpx per cycle (cap=%.0fs at %.0f px/s), max_headlines_per_page=%s",
                self._page_width_budget() or 0.0,
                self._effective_duration_cap(),
                self._effective_pixels_per_second(),
                self.max_headlines_per_page or 'auto',
            )
        else:
            self.logger.info("Headline paging disabled - all headlines share one scroll cycle")

    @staticmethod
    def _pixel_draw(image: Image.Image) -> ImageDraw.ImageDraw:
        """
        Build an ImageDraw that renders text crisply on the LED grid.

        PIL anti-aliases by default, which blends glyph edges into dim
        partial-lit pixels. On a 1:1 LED matrix those half-lit pixels read as
        blur rather than as smoothing, and at the plugin's default font_size of
        12 a headline picks up ~150 of them. ``fontmode = "1"`` switches
        FreeType to 1-bit rendering so every pixel is fully on or fully off.

        Every draw surface in this plugin -- including the throwaway ones used
        only to measure text -- goes through here, so measurement and rendering
        can never disagree about glyph metrics.
        """
        draw = ImageDraw.Draw(image)
        draw.fontmode = "1"
        return draw

    def _load_fonts(self) -> Dict[str, ImageFont.FreeTypeFont]:
        """Load fonts for the news ticker display."""
        fonts = {}
        try:
            # Try to load Press Start 2P font
            font_path = self.global_config.get('font_path', 'assets/fonts/PressStart2P-Regular.ttf')
            fonts['headline'] = ImageFont.truetype(font_path, self.font_size)
            fonts['separator'] = ImageFont.truetype(font_path, self.font_size)
            fonts['info'] = ImageFont.truetype(font_path, 6)
            self.logger.info("Successfully loaded Press Start 2P font")
        except IOError:
            self.logger.warning("Press Start 2P font not found, trying 4x6 font")
            try:
                fonts['headline'] = ImageFont.truetype("assets/fonts/4x6-font.ttf", self.font_size)
                fonts['separator'] = ImageFont.truetype("assets/fonts/4x6-font.ttf", self.font_size)
                fonts['info'] = ImageFont.truetype("assets/fonts/4x6-font.ttf", 6)
                self.logger.info("Successfully loaded 4x6 font")
            except IOError:
                self.logger.warning("4x6 font not found, using default PIL font")
                default_font = ImageFont.load_default()
                fonts = {
                    'headline': default_font,
                    'separator': default_font,
                    'info': default_font
                }
        except Exception as e:
            self.logger.error(f"Error loading fonts: {e}")
            default_font = ImageFont.load_default()
            fonts = {
                'headline': default_font,
                'separator': default_font,
                'info': default_font
            }
        return fonts

    @staticmethod
    def _parse_color(color_value, default: Tuple[int, int, int]) -> Tuple[int, int, int]:
        """Parse an RGB list from config, falling back to `default` on bad input."""
        if color_value is None:
            return default
        try:
            color = tuple(int(c) for c in color_value)
            return color if len(color) == 3 else default
        except (ValueError, TypeError):
            return default

    def _load_element_font(self, element_cfg: Dict[str, Any],
                           default_name: str, default_size: int):
        """Resolve an element's configured font, or None for "keep the default".

        Returns None whenever the configured font/size equals the schema
        defaults, so a default (or merged-defaults) `customization` block leaves
        the fonts from _load_fonts() untouched and default rendering stays
        byte-identical — the web UI merges schema defaults into saved configs,
        so "key present" must not change output. Only a genuine non-default
        selection loads a custom face; load failures fall back to None with a
        warning rather than breaking the ticker.
        """
        name = element_cfg.get('font', default_name)
        try:
            size = int(element_cfg.get('font_size', default_size))
        except (TypeError, ValueError):
            size = default_size
        if name == default_name and size == default_size:
            return None
        key = (name, size)
        if key not in self._font_cache:
            font = None
            candidates = [
                os.path.join('assets', 'fonts', name),
                os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets', 'fonts', name),
            ]
            for path in candidates:
                if not os.path.exists(path):
                    continue
                try:
                    # FreeType handles .ttf and (at its native size) .bdf faces.
                    font = ImageFont.truetype(path, size)
                    break
                except Exception as e:
                    self.logger.warning(f"Could not load font {name}@{size}: {e}")
            if font is None and not any(os.path.exists(p) for p in candidates):
                self.logger.warning(f"Font file not found: {name}; using default font")
            self._font_cache[key] = font
        return self._font_cache[key]

    def _apply_font_customization(self, customization: Dict[str, Any]) -> None:
        """Apply the `customization` block's per-element font overrides.

        Overrides mutate self.fonts in place, so every measurement (textbbox)
        and draw call automatically uses the same face and scroll widths never
        disagree with rendering. At schema defaults every override resolves to
        None and self.fonts is left exactly as _load_fonts() built it.

        Schema-default sentinels: headline_text is PressStart2P-Regular.ttf @ 12
        (mirroring global.font_path / global.font_size defaults) and source_text
        is PressStart2P-Regular.ttf @ 6 (the hardcoded 'info' font size).
        """
        if not isinstance(customization, dict):
            return

        headline_cfg = customization.get('headline_text', {}) or {}
        headline_font = self._load_element_font(headline_cfg, 'PressStart2P-Regular.ttf', 12)
        if headline_font is not None:
            self.fonts['headline'] = headline_font
            # The separator has always shared the headline's face and size
            # (see _load_fonts); keep that pairing when the headline changes.
            self.fonts['separator'] = headline_font

        source_cfg = customization.get('source_text', {}) or {}
        source_font = self._load_element_font(source_cfg, 'PressStart2P-Regular.ttf', 6)
        if source_font is not None:
            self.fonts['info'] = source_font

    def _migrate_custom_feeds_format(self) -> None:
        """
        Migrate custom_feeds from old dict format to new array format.
        Also migrates feed_logo_map entries into the new logo object structure.
        
        Updates self.feeds_config and self.config in memory, then persists the
        migrated format to disk via ConfigManager to prevent re-running on each startup.
        """
        custom_feeds = self.feeds_config.get('custom_feeds')
        feed_logo_map = self.feeds_config.get('feed_logo_map', {})
        migration_performed = False

        if isinstance(custom_feeds, dict):
            self.logger.info("Migrating custom_feeds from dictionary to array format.")
            new_custom_feeds = []
            for name, url in custom_feeds.items():
                feed_obj = {
                    "name": name,
                    "url": url,
                    "enabled": True  # Default to enabled
                }
                if name in feed_logo_map:
                    logo_filename = feed_logo_map[name]
                    # Assuming logos are stored in a plugin-specific assets/logos directory
                    logo_path = f"plugins/{self.plugin_id}/assets/logos/{logo_filename}"
                    feed_obj["logo"] = {
                        "id": f"{name.lower().replace(' ', '-')}-logo",
                        "path": logo_path,
                        "uploaded_at": datetime.now(timezone.utc).isoformat()
                    }
                    self.logger.info(f"Migrated logo for '{name}' to new format.")
                new_custom_feeds.append(feed_obj)
            self.feeds_config['custom_feeds'] = new_custom_feeds
            # Remove old feed_logo_map after migration
            if 'feed_logo_map' in self.feeds_config:
                del self.feeds_config['feed_logo_map']
            migration_performed = True
            self.logger.info("Custom feeds migration complete.")
        elif custom_feeds is None:
            self.feeds_config['custom_feeds'] = []  # Ensure it's an empty list if not present
            migration_performed = True
        
        # Persist migrated config to disk if migration was performed
        if migration_performed and self.plugin_manager and hasattr(self.plugin_manager, 'config_manager') and self.plugin_manager.config_manager:
            try:
                # Update self.config to reflect the migrated format
                if 'feeds' not in self.config:
                    self.config['feeds'] = {}
                self.config['feeds'].update(self.feeds_config)
                
                # Get the full config from config_manager
                full_config = self.plugin_manager.config_manager.load_config()
                # Merge the migrated config into the existing plugin config (don't replace entire config)
                if self.plugin_id not in full_config:
                    full_config[self.plugin_id] = {}
                # Merge feeds config into existing plugin config
                if 'feeds' not in full_config[self.plugin_id]:
                    full_config[self.plugin_id]['feeds'] = {}
                full_config[self.plugin_id]['feeds'].update(self.feeds_config)
                # Remove feed_logo_map if it exists in the saved config
                if 'feeds' in full_config[self.plugin_id] and 'feed_logo_map' in full_config[self.plugin_id]['feeds']:
                    del full_config[self.plugin_id]['feeds']['feed_logo_map']
                
                # Save the full config back to disk
                self.plugin_manager.config_manager.save_config(full_config)
                self.logger.info("Persisted migrated custom_feeds format to disk.")
            except Exception as e:
                self.logger.error(f"Error persisting migrated config to disk: {e}", exc_info=True)
                # Continue even if save fails - migration is still applied in memory
        

    def _load_paging_settings(self) -> None:
        """Read the headline paging block from ``global`` config."""
        paging_config = self.global_config.get('headline_paging', {})
        if not isinstance(paging_config, dict):
            paging_config = {}
        self.paging_enabled = paging_config.get('enabled', True)
        self.max_headlines_per_page = paging_config.get('max_headlines_per_page', 0)
        self.page_hold_seconds = paging_config.get('page_hold_seconds', 2.0)
        self.duration_overrun_allowance = paging_config.get('duration_overrun_allowance', 0.25)

    def _read_core_duration_cap(self) -> float:
        """
        Read the display controller's global dynamic-duration cap.

        The controller holds a plugin for at most min(plugin cap, global cap),
        where the global cap is ``display.dynamic_duration.max_duration_seconds``
        and defaults to CORE_DEFAULT_DURATION_CAP when absent. Page sizing has to
        respect that ceiling to guarantee a page finishes scrolling.
        """
        try:
            config_manager = getattr(self.plugin_manager, 'config_manager', None)
            if config_manager:
                full_config = config_manager.load_config() or {}
                dynamic = (full_config.get('display', {}) or {}).get('dynamic_duration', {}) or {}
                cap_value = dynamic.get('max_duration_seconds')
                if cap_value is not None:
                    cap = float(cap_value)
                    if cap > 0:
                        return cap
        except (AttributeError, TypeError, ValueError, OSError) as e:
            self.logger.debug(f"Could not read core dynamic duration cap, assuming default: {e}")
        return self.CORE_DEFAULT_DURATION_CAP

    def _plugin_duration_cap(self) -> float:
        """
        Longest this plugin will ever ask to stay on screen, slack included.

        The overrun allowance has to be part of the cap, not just of
        get_cycle_duration(): the controller takes min(cycle duration, cap), so a
        cap set to the bare page duration would clip the very slack that lets a
        slow-running scroll reach the end.
        """
        base = float(self.max_duration) if self.max_duration and self.max_duration > 0 \
            else self.CORE_DEFAULT_DURATION_CAP
        return base * (1.0 + max(0.0, self.duration_overrun_allowance))

    def _effective_duration_cap(self) -> float:
        """Ceiling the controller will actually enforce: min(plugin cap, core cap)."""
        return min(self._plugin_duration_cap(), self._read_core_duration_cap())

    def _effective_pixels_per_second(self) -> float:
        """Nominal scroll rate in pixels per second, whichever mode is active."""
        if getattr(self, 'scroll_pixels_per_second', None):
            return float(self.scroll_pixels_per_second)
        if self.scroll_delay and self.scroll_delay > 0:
            return float(self.scroll_speed) / float(self.scroll_delay)
        return float(self.scroll_speed) * 100.0

    def _page_width_budget(self) -> Optional[float]:
        """
        Width of content, in pixels, that one display turn can actually scroll.

        Returns None when paging is disabled or the rate can't be determined,
        meaning "no limit — put every headline in one strip".
        """
        if not self.paging_enabled:
            return None

        pixels_per_second = self._effective_pixels_per_second()
        cap = self._effective_duration_cap()
        if pixels_per_second <= 0 or cap <= 0:
            return None

        # Work backwards from the cap through the two multipliers that sit
        # between raw scroll time and the wall the controller enforces:
        # ScrollHelper adds buffer_ratio when it derives the cycle duration, and
        # get_cycle_duration() adds overrun slack on top of that.
        divisor = (1.0 + max(0.0, self.duration_buffer)) * (1.0 + max(0.0, self.duration_overrun_allowance))
        usable_seconds = cap / divisor if divisor > 0 else cap

        # Never go below two panel-widths, or a narrow panel with a slow scroll
        # would produce pages that can't hold a single headline.
        return max(float(self.display_width * 2), pixels_per_second * usable_seconds)

    def _configure_scroll_settings(self) -> None:
        """
        Configure scroll helper with current settings.
        
        Assumes scroll configuration variables (scroll_speed, scroll_delay, etc.)
        and scroll_helper are already set up. This method applies those settings
        to the scroll_helper instance.
        """
        if not hasattr(self, 'scroll_helper') or not self.scroll_helper:
            return
        
        # Determine if we should use frame-based scrolling
        # Check if scroll_pixels_per_second is None (frame-based) or set (time-based)
        display_config = self.global_config.get('display', {})
        use_frame_based = (self.scroll_pixels_per_second is None and 
                          display_config and 
                          ('scroll_speed' in display_config or 'scroll_delay' in display_config))
        
        if use_frame_based:
            # Frame-based scrolling
            if hasattr(self.scroll_helper, 'set_frame_based_scrolling'):
                self.scroll_helper.set_frame_based_scrolling(True)
            self.scroll_helper.set_scroll_speed(self.scroll_speed)
            self.scroll_helper.set_scroll_delay(self.scroll_delay)
            pixels_per_second = self.scroll_speed / self.scroll_delay if self.scroll_delay > 0 else self.scroll_speed * 100
            self.logger.info(f"Effective scroll speed: {pixels_per_second:.1f} px/s ({self.scroll_speed} px/frame at {1.0/self.scroll_delay:.0f} FPS)")
        else:
            # Time-based scrolling (backward compatibility)
            if self.scroll_pixels_per_second is not None:
                pixels_per_second = self.scroll_pixels_per_second
            else:
                pixels_per_second = self.scroll_speed / self.scroll_delay if self.scroll_delay > 0 else self.scroll_speed * 100
            self.scroll_helper.set_scroll_speed(pixels_per_second)
            self.scroll_helper.set_scroll_delay(self.scroll_delay)
        
        # Set target FPS
        if hasattr(self.scroll_helper, 'set_target_fps'):
            self.scroll_helper.set_target_fps(self.target_fps)
        else:
            self.scroll_helper.target_fps = max(30.0, min(200.0, self.target_fps))
            self.scroll_helper.frame_time_target = 1.0 / self.scroll_helper.target_fps
        
        # Configure dynamic duration
        self.scroll_helper.set_dynamic_duration_settings(
            enabled=self.dynamic_duration_enabled,
            min_duration=self.min_duration,
            max_duration=self.max_duration,
            buffer=self.duration_buffer
        )

    def validate_config(self) -> bool:
        """Validate plugin configuration."""
        # Call parent validation first
        if not super().validate_config():
            return False
        
        # Validate feeds configuration
        if not isinstance(self.feeds_config, dict):
            self.logger.error("feeds configuration must be a dictionary")
            return False
        
        # Validate enabled_feeds is a list if present
        enabled_feeds = self.feeds_config.get('enabled_feeds', [])
        if not isinstance(enabled_feeds, list):
            self.logger.error("enabled_feeds must be a list")
            return False
        
        # Validate custom_feeds - support both old dict format and new array format
        custom_feeds = self.feeds_config.get('custom_feeds', [])
        if isinstance(custom_feeds, dict):
            # Old format validation
            for feed_name, feed_url in custom_feeds.items():
                if not isinstance(feed_url, str) or not feed_url.strip():
                    self.logger.error(f"Custom feed '{feed_name}' has invalid URL: must be a non-empty string")
                    return False
                try:
                    parsed = urlparse(feed_url)
                    if not parsed.scheme or not parsed.netloc:
                        self.logger.error(f"Custom feed '{feed_name}' has invalid URL format: {feed_url}")
                        return False
                except Exception as e:
                    self.logger.error(f"Custom feed '{feed_name}' URL validation error: {e}")
                    return False
        elif isinstance(custom_feeds, list):
            # New format validation
            feed_names = set()
            for idx, feed in enumerate(custom_feeds):
                if not isinstance(feed, dict):
                    self.logger.error(f"Custom feed at index {idx} must be an object")
                    return False
                
                feed_name = feed.get('name')
                if not isinstance(feed_name, str) or not feed_name.strip():
                    self.logger.error(f"Custom feed at index {idx} has invalid name: must be a non-empty string")
                    return False
                
                if feed_name in feed_names:
                    self.logger.error(f"Duplicate custom feed name: '{feed_name}'")
                    return False
                feed_names.add(feed_name)
                
                feed_url = feed.get('url')
                if not isinstance(feed_url, str) or not feed_url.strip():
                    self.logger.error(f"Custom feed '{feed_name}' has invalid URL: must be a non-empty string")
                    return False
                
                try:
                    parsed = urlparse(feed_url)
                    if not parsed.scheme or not parsed.netloc:
                        self.logger.error(f"Custom feed '{feed_name}' has invalid URL format: {feed_url}")
                        return False
                except Exception as e:
                    self.logger.error(f"Custom feed '{feed_name}' URL validation error: {e}")
                    return False
                
                # Validate logo object if present
                logo = feed.get('logo')
                if logo is not None:
                    if not isinstance(logo, dict):
                        self.logger.error(f"Custom feed '{feed_name}' has invalid logo: must be an object")
                        return False
                    if 'path' not in logo:
                        self.logger.error(f"Custom feed '{feed_name}' logo object must have 'path' field")
                        return False
        else:
            self.logger.error("custom_feeds must be either a dictionary (old format) or an array (new format)")
            return False
        
        # Validate global configuration
        if not isinstance(self.global_config, dict):
            self.logger.error("global configuration must be a dictionary")
            return False
        
        return True

    def on_config_change(self, new_config: Dict[str, Any]) -> None:
        """
        Handle configuration changes at runtime.
        
        Updates feeds configuration and clears cache to force refresh when
        custom feeds or enabled feeds change.
        """
        super().on_config_change(new_config)
        
        # Update feeds configuration
        old_feeds_config = self.feeds_config.copy() if self.feeds_config else {}
        self.feeds_config = new_config.get('feeds', {})
        
        # Migrate old format if needed
        self._migrate_custom_feeds_format()
        
        # Check if custom feeds changed
        old_custom_feeds = old_feeds_config.get('custom_feeds', [])
        new_custom_feeds = self.feeds_config.get('custom_feeds', [])
        
        # Check if enabled feeds changed
        old_enabled_feeds = set(old_feeds_config.get('enabled_feeds', []))
        new_enabled_feeds = set(self.feeds_config.get('enabled_feeds', []))
        
        # Compare custom feeds (handle both formats)
        def normalize_custom_feeds(feeds):
            if isinstance(feeds, dict):
                return sorted(feeds.items())
            elif isinstance(feeds, list):
                return sorted([(f.get('name'), f.get('url')) for f in feeds if isinstance(f, dict)])
            return []
        
        feeds_changed = (normalize_custom_feeds(old_custom_feeds) != normalize_custom_feeds(new_custom_feeds) or
                         old_enabled_feeds != new_enabled_feeds)
        
        if feeds_changed:
            # Get feed names for logging
            if isinstance(new_custom_feeds, list):
                custom_feed_names = [f.get('name') for f in new_custom_feeds if isinstance(f, dict)]
            else:
                custom_feed_names = list(new_custom_feeds.keys()) if isinstance(new_custom_feeds, dict) else []
            self.logger.info(f"Feeds configuration updated. Custom feeds: {custom_feed_names}, Enabled feeds: {list(new_enabled_feeds)}")
            # Clear headlines cache to force refresh
            self.current_headlines = []
            self._headline_image_cache = {}
            self._headlines_signature = None
            # A different feed set means the old page window means nothing
            self._page_start = 0
            self._page_count = 0
            self._page_dirty = False
            if hasattr(self, 'scroll_helper'):
                self.scroll_helper.clear_cache()
            # Trigger immediate update on next display cycle
            self.last_update = 0  # Force update() to run immediately
        
        # Update feed-related settings
        self.text_color = tuple(self.feeds_config.get('text_color', [255, 255, 255]))
        self.separator_color = tuple(self.feeds_config.get('separator_color', [255, 0, 0]))
        customization = new_config.get('customization', {}) or {}
        source_text_cfg = customization.get('source_text', {}) or {}
        self.source_color = self._parse_color(source_text_cfg.get('text_color'), (150, 150, 150))
        self.show_logos = self.feeds_config.get('show_logos', True)
        default_logo_size = self.display_height - 4 if self.display_height > 4 else self.display_height
        self.logo_size = self.feeds_config.get('logo_size', default_logo_size)
        # Keep feed_logo_map for backward compatibility
        self.feed_logo_map = self.feeds_config.get('feed_logo_map', {})
        
        # Update global config settings
        self.global_config = new_config.get('global', {})
        
        # Update display duration
        self.display_duration = self.global_config.get('display_duration', 30)
        
        # Update scroll configuration variables (handle both formats)
        display_config = self.global_config.get('display', {})
        if display_config and ('scroll_speed' in display_config or 'scroll_delay' in display_config):
            # New format: frame-based scrolling
            self.scroll_speed = display_config.get('scroll_speed', 1.0)
            self.scroll_delay = display_config.get('scroll_delay', 0.01)
            self.scroll_pixels_per_second = None
        else:
            # Legacy format: time-based scrolling
            self.scroll_speed = self.global_config.get('scroll_speed', 1.0)
            self.scroll_delay = self.global_config.get('scroll_delay', 0.01)
            self.scroll_pixels_per_second = self.global_config.get('scroll_pixels_per_second')
        
        # Update dynamic duration settings
        dynamic_duration_config = self.global_config.get('dynamic_duration', {})
        if isinstance(dynamic_duration_config, bool):
            # Legacy: just a boolean
            self.dynamic_duration_enabled = dynamic_duration_config
            self.min_duration = self.global_config.get('min_duration', 30)
            self.max_duration = self.global_config.get('max_duration', 300)
            self.duration_buffer = self.global_config.get('duration_buffer', 0.1)
        else:
            # New format: object with settings
            self.dynamic_duration_enabled = dynamic_duration_config.get('enabled', True)
            self.min_duration = dynamic_duration_config.get('min_duration_seconds', 30)
            self.max_duration = dynamic_duration_config.get('max_duration_seconds', 300)
            self.duration_buffer = dynamic_duration_config.get('buffer_ratio', 0.1)
        
        # Update other global settings
        self.rotation_enabled = self.global_config.get('rotation_enabled', True)
        self.rotation_threshold = self.global_config.get('rotation_threshold', 3)
        self.headlines_per_feed = self.global_config.get('headlines_per_feed', 2)
        self.font_size = self.global_config.get('font_size', 12)
        self.target_fps = self.global_config.get('target_fps') or self.global_config.get('scroll_target_fps', 100)

        # Reload paging settings - page size depends on scroll speed and the
        # duration cap, so any of those changing invalidates the current strip
        self._load_paging_settings()
        self._page_dirty = False
        if hasattr(self, 'scroll_helper'):
            self.scroll_helper.clear_cache()

        # Apply scroll settings to scroll_helper
        self._configure_scroll_settings()
        
        # Update background service configuration
        self.background_config = self.global_config.get('background_service', {
            'enabled': True,
            'request_timeout': 30,
            'max_retries': 3,
            'priority': 2
        })
        
        # Rebuild base fonts, then re-apply per-element customization. Always
        # rebuilding (rather than only when font_size changed) also clears a
        # stale override when customization is reset back to defaults.
        self.fonts = self._load_fonts()
        self._apply_font_customization(customization)

        # Colors and fonts are baked into the rendered headline images
        self._headline_image_cache = {}
        # ...and into the strip, so the same headlines must render again
        self._headlines_signature = None

    def _headline_signature(self) -> tuple:
        """Identify the headline set the current strip was rendered from.

        Feed name and title, in order: the two fields the rendered text is
        built from. Order matters -- rotation reorders the list without
        changing its contents, and that does need a rebuild.
        """
        return tuple(
            (headline.get('feed_name', ''), headline.get('title', ''))
            for headline in self.current_headlines
        )

    def update(self) -> None:
        """Update news headlines from all enabled feeds."""
        if not self.initialized:
            return

        try:
            self.current_headlines = []
            feed_stats = {'success': 0, 'failed': 0, 'total': 0}

            # Fetch from enabled predefined feeds
            enabled_feeds = self.feeds_config.get('enabled_feeds', [])
            for feed_name in enabled_feeds:
                if feed_name in self.DEFAULT_FEEDS:
                    feed_stats['total'] += 1
                    headlines = self._fetch_feed_headlines(feed_name, self.DEFAULT_FEEDS[feed_name])
                    if headlines:
                        self.current_headlines.extend(headlines)
                        feed_stats['success'] += 1
                    else:
                        feed_stats['failed'] += 1

            # Fetch from custom feeds (use array order)
            custom_feeds = self.feeds_config.get('custom_feeds', [])
            
            # Handle both old dict format (backward compatibility) and new array format
            if isinstance(custom_feeds, dict):
                # Old format - process all feeds
                feed_list = [(name, url) for name, url in custom_feeds.items()]
            elif isinstance(custom_feeds, list):
                # New format - filter by enabled and use array order
                feed_list = [
                    (feed.get('name'), feed.get('url'))
                    for feed in custom_feeds
                    if isinstance(feed, dict) and feed.get('enabled', True)
                ]
            else:
                feed_list = []
            
            for feed_name, feed_url in feed_list:
                if not feed_name or not feed_url:
                    continue
                feed_stats['total'] += 1
                headlines = self._fetch_feed_headlines(feed_name, feed_url)
                if headlines:
                    self.current_headlines.extend(headlines)
                    feed_stats['success'] += 1
                else:
                    feed_stats['failed'] += 1

            # Log feed status summary
            if feed_stats['total'] > 0:
                self.logger.info(
                    f"Feed update complete: {feed_stats['success']}/{feed_stats['total']} feeds successful, "
                    f"{len(self.current_headlines)} headlines retrieved"
                )
                if feed_stats['failed'] > 0:
                    self.logger.warning(f"{feed_stats['failed']} feed(s) failed to fetch headlines")

            # Limit total headlines and reset rotation tracking
            # Count enabled custom feeds
            custom_feeds_list = self.feeds_config.get('custom_feeds', [])
            if isinstance(custom_feeds_list, dict):
                enabled_custom_count = len(custom_feeds_list)
            else:
                enabled_custom_count = sum(1 for feed in custom_feeds_list if isinstance(feed, dict) and feed.get('enabled', True))
            
            max_headlines = len(enabled_feeds) * self.headlines_per_feed + enabled_custom_count * self.headlines_per_feed
            if len(self.current_headlines) > max_headlines:
                self.current_headlines = self.current_headlines[:max_headlines]

            # Reset rotation tracking for new content.
            #
            # Only when the headlines actually differ from the ones already
            # rendered. A refresh lands every update_interval and an RSS feed
            # mostly returns what it returned last time, so discarding here
            # unconditionally threw away a strip that was still correct and
            # made the next Vegas fetch rebuild it: measured on a 512x64 rig
            # at 427ms for a 10220x64 image, roughly every fifteen minutes,
            # on the render thread. The panel visibly stalled for it.
            signature = self._headline_signature()
            if self.current_headlines and signature != self._headlines_signature:
                self._headlines_signature = signature
                self.rotation_count = 0
                # Rendered text is tied to the headlines it came from
                self._headline_image_cache = {}
                # Deliberately keep _page_start rather than rewinding to the
                # first headline: a refresh lands every update_interval, and
                # restarting the page window each time is exactly what kept the
                # tail of the list from ever reaching the panel.
                self._page_start %= len(self.current_headlines)
                self._page_dirty = False
                # Clear scroll cache to force recreation of scrolling image
                if hasattr(self, 'scroll_helper'):
                    self.scroll_helper.clear_cache()

            self.last_update = time.time()
            self.logger.debug(f"Updated news headlines: {len(self.current_headlines)} total")

        except Exception as e:
            self.logger.error(f"Error updating news headlines: {e}")

    def _fetch_feed_headlines(self, feed_name: str, feed_url: str) -> List[Dict]:
        """Fetch headlines from a specific RSS feed."""
        cache_key = f"news_{feed_name}_{datetime.now().strftime('%Y%m%d%H')}"
        update_interval = self.global_config.get('update_interval', 300)

        # Check cache first - cache_manager handles TTL internally
        cached_data = self.cache_manager.get(cache_key, max_age=update_interval)
        if cached_data:
            self.logger.debug(f"Using cached headlines for {feed_name}")
            return cached_data

        try:
            self.logger.info(f"Fetching headlines from {feed_name}...")
            headers = {
                'User-Agent': 'LEDMatrix/1.0 (+https://github.com/ChuckBuilds/LEDMatrix)'
            }
            response = requests.get(feed_url, timeout=self.background_config.get('request_timeout', 30), headers=headers)
            response.raise_for_status()

            # Parse RSS XML
            root = ET.fromstring(response.content)
            headlines = []

            # Extract headlines from RSS items
            for item in root.findall('.//item')[:self.headlines_per_feed]:
                title = item.find('title')
                description = item.find('description')
                pub_date = item.find('pubDate')
                link = item.find('link')

                if title is not None and title.text:
                    headline = {
                        'feed_name': feed_name,
                        'title': html.unescape(title.text).strip(),
                        'description': html.unescape(description.text).strip() if description is not None else '',
                        'published': pub_date.text if pub_date is not None else '',
                        'link': link.text if link is not None else '',
                        'timestamp': datetime.now().isoformat()
                    }

                    # Clean up the title (remove extra whitespace, fix common issues)
                    headline['title'] = self._clean_headline(headline['title'])
                    headlines.append(headline)

            # Cache the results
            self.cache_manager.set(cache_key, headlines, ttl=update_interval * 2)

            return headlines

        except requests.RequestException as e:
            self.logger.error(f"Error fetching RSS feed {feed_name}: {e}")
            return []
        except ET.ParseError as e:
            self.logger.error(f"Error parsing RSS feed {feed_name}: {e}")
            return []
        except Exception as e:
            self.logger.error(f"Error processing RSS feed {feed_name}: {e}")
            return []

    def _clean_headline(self, headline: str) -> str:
        """Clean and format headline text."""
        if not headline:
            return ""

        # Remove extra whitespace
        headline = re.sub(r'\s+', ' ', headline.strip())

        # Remove common artifacts
        headline = re.sub(r'^\s*-\s*', '', headline)  # Remove leading dashes
        headline = re.sub(r'\s+', ' ', headline)  # Normalize whitespace

        return headline

    def display(self, display_mode: str = None, force_clear: bool = False) -> None:
        """
        Display scrolling news headlines.

        Args:
            display_mode: Should be 'news_ticker'
            force_clear: If True, clear display before rendering
        """
        if not self.initialized:
            self._display_error("News ticker plugin not initialized")
            return

        if not self.current_headlines:
            self._display_no_headlines()
            return

        # Create scrolling image if needed
        if not self.scroll_helper.cached_image or force_clear:
            self.logger.info("Creating news ticker image...")
            self._create_scrolling_image()
            if not self.scroll_helper.cached_image:
                self.logger.error("Failed to create news ticker image, showing fallback")
                self._display_no_headlines()
                return
            self.logger.info("News ticker image created successfully")
            self._cycle_complete = False

        if force_clear:
            self.scroll_helper.reset_scroll()
            self._cycle_complete = False

        # Signal scrolling state
        self.display_manager.set_scrolling_state(True)
        self.display_manager.process_deferred_updates()

        # Update scroll position using the scroll helper
        self.scroll_helper.update_scroll_position()
        if self.scroll_helper.is_scroll_complete():
            if not self._cycle_complete:
                self._on_scroll_cycle_complete()
                self._cycle_complete = True
                self._cycle_complete_at = time.time()
            elif self._page_dirty and (time.time() - self._cycle_complete_at) >= self.page_hold_seconds:
                # Still on screen after finishing a page. That happens when the
                # controller doesn't rotate away — most often because the news
                # ticker is the only mode in the rotation, so reset_cycle_state()
                # is never called. Roll onto the next page rather than sitting on
                # a frozen last frame.
                self.logger.debug("Parked on a finished page; rolling to the next one")
                self._start_next_page()

        # Get visible portion
        visible_portion = self.scroll_helper.get_visible_portion()
        if visible_portion:
            # Update display
            self.display_manager.image.paste(visible_portion, (0, 0))
            self.display_manager.update_display()

        # Log frame rate (less frequently to avoid spam)
        self.scroll_helper.log_frame_rate()

    def _on_scroll_cycle_complete(self) -> None:
        """Handle the moment the strip finishes one full pass."""
        scroll_info = self.scroll_helper.get_scroll_info()
        elapsed_time = scroll_info.get('elapsed_time')
        self.logger.info(
            "News ticker scroll cycle completed (elapsed=%.2fs, target=%.2fs)",
            elapsed_time if elapsed_time is not None else -1.0,
            scroll_info.get('dynamic_duration'),
        )

        if self.paging_enabled:
            # Queue the next page but leave the finished strip on screen. The
            # rebuild is deferred to reset_cycle_state()/force_clear (or the
            # page_hold_seconds fallback in display()) so a fresh page never
            # starts scrolling into a hand-off the controller is about to make.
            self._advance_page()
            self._page_dirty = True
        elif self.rotation_enabled:
            self.rotation_count += 1
            self.logger.debug(f"Rotation count: {self.rotation_count}/{self.rotation_threshold}")

            if self.rotation_count >= self.rotation_threshold:
                self._rotate_headlines()
                self.rotation_count = 0
                # Clear scroll cache to force recreation with new headline order
                self.scroll_helper.clear_cache()
                self.logger.info("Headlines rotated - scroll cache cleared for next cycle")

    def _render_headline_cached(self, headline: Dict[str, Any]) -> Optional[Image.Image]:
        """Render a headline, reusing the image for the life of the current data."""
        key = (headline.get('feed_name', ''), headline.get('title', ''))
        if key not in self._headline_image_cache:
            self._headline_image_cache[key] = self._render_headline(headline)
        return self._headline_image_cache[key]

    def _build_page_images(self) -> Tuple[List[Image.Image], int]:
        """
        Render the headlines that make up the current page.

        A page is the longest run of consecutive headlines starting at
        ``self._page_start`` whose combined scroll width still fits in the time
        the display controller will actually grant this plugin. Sizing the strip
        to the time budget is what stops the tail of a cycle from being
        guillotined mid-word: a headline that wouldn't finish is deferred to the
        next page instead of being drawn and then cut off.

        Returns:
            Tuple of (rendered images for this page, headlines consumed).
        """
        total = len(self.current_headlines)
        if total == 0:
            return [], 0

        self._page_start %= total
        budget = self._page_width_budget()
        limit = self.max_headlines_per_page if self.max_headlines_per_page > 0 else total

        images: List[Image.Image] = []
        # create_scrolling_image() prepends display_width px of blank lead-in.
        width = float(self.display_width)
        consumed = 0

        while consumed < total and len(images) < limit:
            headline = self.current_headlines[(self._page_start + consumed) % total]
            image = self._render_headline_cached(headline)
            consumed += 1
            if image is None:
                continue

            # Mirrors create_scrolling_image()'s layout: each item costs its own
            # width plus one element_gap, and item_gap sits between items.
            cost = image.width + self.ELEMENT_GAP + (self.ITEM_GAP if images else 0)
            if images and budget is not None and width + cost > budget:
                consumed -= 1  # defer this headline to the next page
                break

            images.append(image)
            width += cost

        # A single headline wider than the whole budget still gets its own page:
        # it can't be shown in full either way, but splitting it would be worse.
        return images, max(consumed, 1)

    def _advance_page(self) -> None:
        """Move the page window forward by exactly the headlines just shown."""
        total = len(self.current_headlines)
        if total == 0:
            return
        step = self._page_count if self._page_count > 0 else 1
        self._page_start = (self._page_start + step) % total
        self.logger.info(
            "Advanced to next headline page: starting at headline %d/%d ('%s')",
            self._page_start + 1,
            total,
            self.current_headlines[self._page_start].get('title', 'Unknown')[:50],
        )

    def _start_next_page(self) -> None:
        """Swap the finished strip for the queued page's, ready to scroll."""
        self._page_dirty = False
        self._cycle_complete = False
        self.scroll_helper.clear_cache()
        # Rebuild here rather than leaving it to the next display() call, so the
        # swap costs no blank frame. Skipped when every feed has gone empty --
        # display() falls through to the "no headlines" screen instead.
        if self.current_headlines:
            self._create_scrolling_image()

    def _create_scrolling_image(self) -> None:
        """Create the scrolling news ticker image for the current page."""
        try:
            headline_images, page_count = self._build_page_images()

            if not headline_images:
                self.logger.warning("No headline images created")
                self.scroll_helper.clear_cache()
                return

            self._page_count = page_count

            # Log headline widths for debugging
            headline_widths = [img.width for img in headline_images]
            total_headline_width = sum(headline_widths)
            self.logger.debug(
                "Preparing scrolling image: %d headlines, widths=%s, total=%dpx, budget=%s",
                len(headline_images), headline_widths, total_headline_width, self._page_width_budget()
            )

            # Use ScrollHelper to create the scrolling image
            self.scroll_helper.create_scrolling_image(
                headline_images,
                item_gap=self.ITEM_GAP,
                element_gap=self.ELEMENT_GAP
            )
            # Dynamic duration is automatically calculated by create_scrolling_image()
            self._cycle_complete = False
            self._page_dirty = False

            self.logger.info(
                "Created news ticker image: headlines %d-%d of %d, total_scroll_width=%dpx, dynamic_duration=%ds",
                self._page_start + 1,
                self._page_start + len(headline_images),
                len(self.current_headlines),
                self.scroll_helper.total_scroll_width,
                self.scroll_helper.get_dynamic_duration()
            )

        except Exception as e:
            self.logger.error(f"Error creating news ticker image: {e}")
            self.scroll_helper.clear_cache()

    def _get_feed_logo_path(self, feed_name: str) -> Optional[Path]:
        """
        Get the path to a feed's logo file.
        
        Priority order:
        1. Integrated logo from feed object (new format) - logo.path field
        2. User-configured feed_logo_map (backward compatibility)
        3. Predefined FEED_LOGO_MAP
        4. Infer from feed name
        5. Default fallback
        
        Checks directories in order:
        1. Uploaded logo path from feed object (if present)
        2. assets/news_logos/ (primary location for news logos)
        3. assets/broadcast_logos/ (fallback for broadcast network logos)
        4. Plugin assets/logos/ (plugin-specific logos)
        """
        # First check new format - integrated logo in feed object
        custom_feeds = self.feeds_config.get('custom_feeds', [])
        if isinstance(custom_feeds, list):
            for feed in custom_feeds:
                if isinstance(feed, dict) and feed.get('name') == feed_name:
                    logo_obj = feed.get('logo')
                    if isinstance(logo_obj, dict) and 'path' in logo_obj:
                        logo_path_str = logo_obj['path']
                        if logo_path_str:
                            # Try absolute path first, then relative to project root
                            logo_path = Path(logo_path_str)
                            if logo_path.is_absolute() and logo_path.exists():
                                self.logger.debug(f"Found logo for {feed_name} at {logo_path} (from feed object)")
                                return logo_path
                            # Try relative to project root
                            project_root = Path(__file__).parent.parent.parent
                            logo_path = project_root / logo_path_str
                            if logo_path.exists():
                                self.logger.debug(f"Found logo for {feed_name} at {logo_path} (from feed object, relative path)")
                                return logo_path
        
        # Fall back to old format - check user-configured logo map
        logo_filename = self.feed_logo_map.get(feed_name)
        
        # If not in user config, check predefined mapping
        if not logo_filename:
            logo_filename = self.FEED_LOGO_MAP.get(feed_name)
        
        # If still not found, try to infer from feed name
        if not logo_filename:
            feed_lower = feed_name.lower()
            if 'espn' in feed_lower:
                logo_filename = 'espn.png'
            elif 'nfl' in feed_lower:
                logo_filename = 'nfln.png'
            elif 'mlb' in feed_lower:
                logo_filename = 'mlbn.png'
            elif 'nba' in feed_lower or 'nhl' in feed_lower or 'ncaa' in feed_lower:
                logo_filename = 'espn.png'
            else:
                # Try using feed name as filename (normalized)
                # Remove spaces and special chars, convert to lowercase
                normalized = re.sub(r'[^a-zA-Z0-9]', '_', feed_name.lower())
                logo_filename = f"{normalized}.png"
        
        # Check directories in priority order
        project_root = Path(__file__).parent.parent.parent
        plugin_assets = Path(__file__).parent / 'assets' / 'logos'
        
        search_dirs = [
            project_root / 'assets' / 'news_logos',  # Primary location
            project_root / 'assets' / 'broadcast_logos',  # Fallback
            plugin_assets  # Plugin-specific
        ]
        
        for assets_dir in search_dirs:
            logo_path = assets_dir / logo_filename
            if logo_path.exists():
                self.logger.debug(f"Found logo for {feed_name} at {logo_path}")
                return logo_path
        
        self.logger.debug(f"No logo found for {feed_name} (searched for {logo_filename})")
        return None

    def _render_headline(self, headline: Dict[str, Any]) -> Optional[Image.Image]:
        """
        Render a single headline as a PIL Image.
        
        When a logo is present:
        - Logo replaces the "[Feed Name]: " prefix
        - Logo replaces the " • " separator
        - Format: [Logo] Title
        
        When a logo is missing:
        - Shows "[Feed Name]: " prefix
        - Shows " • " separator after title
        - Format: [Feed Name]: Title • 
        """
        try:
            title = headline.get('title', 'No title')
            feed_name = headline.get('feed_name', 'Unknown')

            # Calculate text dimensions
            draw_temp = self._pixel_draw(Image.new('RGB', (1, 1)))
            
            # Get text dimensions for title
            title_bbox = draw_temp.textbbox((0, 0), title, font=self.fonts['headline'])
            title_width = title_bbox[2] - title_bbox[0]
            title_height = title_bbox[3] - title_bbox[1]

            # Load logo if enabled
            logo = None
            logo_width = 0
            logo_spacing = 0
            if self.show_logos:
                logo_path = self._get_feed_logo_path(feed_name)
                if logo_path:
                    logo = self.logo_helper.load_logo(
                        feed_name,
                        logo_path,
                        max_width=self.logo_size,
                        max_height=self.logo_size
                    )
                    if logo:
                        logo_width = logo.width
                        logo_spacing = 4  # Space between logo and text

            # Determine what to show based on logo availability
            # If logo exists: show logo + title (no feed name, no separator)
            # If logo missing: show feed name + title + separator
            has_logo = logo is not None
            
            if has_logo:
                # With logo: [Logo] Title
                feed_text = ""
                separator_text = ""
            else:
                # Without logo: [Feed Name]: Title • 
                feed_text = f"{feed_name}: "
                separator_text = " • "

            # Calculate dimensions for feed name and separator (only if no logo)
            feed_width = 0
            feed_height = 0
            if feed_text:
                feed_bbox = draw_temp.textbbox((0, 0), feed_text, font=self.fonts['info'])
                feed_width = feed_bbox[2] - feed_bbox[0]
                feed_height = feed_bbox[3] - feed_bbox[1]

            separator_width = 0
            separator_height = 0
            if separator_text:
                separator_bbox = draw_temp.textbbox((0, 0), separator_text, font=self.fonts['separator'])
                separator_width = separator_bbox[2] - separator_bbox[0]
                separator_height = separator_bbox[3] - separator_bbox[1]

            # Calculate total width
            total_width = logo_width + logo_spacing + feed_width + title_width + separator_width + 32  # Add padding
            # Use full display height to ensure proper vertical centering when pasted by ScrollHelper
            total_height = self.display_height

            # Create image for this headline
            headline_img = Image.new('RGB', (total_width, total_height), (0, 0, 0))
            draw = self._pixel_draw(headline_img)

            # Draw components
            current_x = 0

            # Draw logo if available (replaces feed name and separator)
            if logo:
                # Center logo vertically within display height
                logo_y = (total_height - logo.height) // 2
                headline_img.paste(logo, (current_x, logo_y), logo if logo.mode == 'RGBA' else None)
                current_x += logo_width + logo_spacing

            # Draw feed name (only if no logo)
            if feed_text:
                feed_text_y = (total_height - feed_height) // 2
                draw.text((current_x, feed_text_y), feed_text, font=self.fonts['info'], fill=self.source_color)
                current_x += feed_width

            # Draw title
            title_y = (total_height - title_height) // 2
            draw.text((current_x, title_y), title, font=self.fonts['headline'], fill=self.text_color)
            current_x += title_width

            # Draw separator (only if no logo) - use bullet point separator
            if separator_text:
                separator_x = current_x + 8
                separator_y = (total_height - separator_height) // 2
                draw.text((separator_x, separator_y), separator_text, font=self.fonts['separator'], fill=self.separator_color)

            return headline_img

        except Exception as e:
            self.logger.error(f"Error rendering headline: {e}")
            return None

    def _display_no_headlines(self):
        """Display message when no headlines are available."""
        img = Image.new('RGB', (self.display_width, self.display_height), (0, 0, 0))
        draw = self._pixel_draw(img)

        # Determine the reason for no headlines
        enabled_feeds = self.feeds_config.get('enabled_feeds', [])
        custom_feeds = self.feeds_config.get('custom_feeds', {})
        total_feeds = len(enabled_feeds) + len(custom_feeds)

        if total_feeds == 0:
            message = "No Feeds Enabled"
        else:
            message = "No Headlines Available"

        font = self.fonts.get('headline', ImageFont.load_default())
        # Previously a fixed (5, 12) with no width check at all -- on a 64px
        # panel "No Feeds Enabled" ran straight off the right edge. Truncate
        # to the actual panel width (with an ellipsis, so it's visibly cut
        # rather than silently dropped) and center it, matching the pattern
        # used for similar fallback messages elsewhere in this plugin
        # family. No extra margin subtracted from display_width -- on the
        # real 192x48 panel this message happens to measure exactly 192px,
        # and reserving even a few px of margin would truncate text that
        # actually already fits edge-to-edge.
        message = self._truncate_to_width(draw, message, font, self.display_width)
        bbox = draw.textbbox((0, 0), message, font=font)
        x = max(0, (self.display_width - (bbox[2] - bbox[0])) // 2)
        y = max(0, (self.display_height - (bbox[3] - bbox[1])) // 2)
        draw.text((x, y), message, font=font, fill=(220, 220, 220))

        self.display_manager.image = img
        self.display_manager.update_display()

    @staticmethod
    def _truncate_to_width(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> str:
        """Trim text and append '..' so it fits max_width pixels."""
        if draw.textbbox((0, 0), text, font=font)[2] <= max_width:
            return text
        ellipsis = ".."
        trimmed = text
        while trimmed and draw.textbbox((0, 0), trimmed + ellipsis, font=font)[2] > max_width:
            trimmed = trimmed[:-1]
        return (trimmed.rstrip() + ellipsis) if trimmed else ellipsis

    def _display_error(self, message: str):
        """Display error message."""
        img = Image.new('RGB', (self.display_width, self.display_height), (0, 0, 0))
        draw = self._pixel_draw(img)
        draw.text((5, 12), message, font=self.fonts.get('headline', ImageFont.load_default()), fill=(255, 0, 0))

        self.display_manager.image = img
        self.display_manager.update_display()

    def supports_dynamic_duration(self) -> bool:
        """
        Tell the display controller this plugin sizes its own display time.

        This must be overridden. BasePlugin's implementation reads a top-level
        ``dynamic_duration`` key, but this plugin has always kept that block
        under ``global``, so the base class saw nothing and reported False. The
        controller then treated the ticker as fixed-duration: it never consulted
        is_cycle_complete() and cut the strip at a flat wall-clock time,
        mid-headline, no matter how much was left to scroll.
        """
        return bool(self.dynamic_duration_enabled)

    def get_dynamic_duration_cap(self) -> Optional[float]:
        """Longest the controller should wait for a scroll cycle to finish."""
        if not self.dynamic_duration_enabled:
            return None
        return self._plugin_duration_cap()

    def get_cycle_duration(self, display_mode: str = None) -> Optional[float]:
        """
        Time needed to scroll the current page from end to end.

        The controller uses this as a hard wall, so it carries overrun slack on
        top of the scroll helper's estimate: a Pi under load renders below the
        nominal frame rate and ScrollHelper drops the missed pixels instead of
        catching up, so the strip finishes a little behind schedule. Without the
        slack that wall lands mid-headline. It only costs real time when the
        scroll actually ran late — the controller still hands over the moment
        is_cycle_complete() flips.
        """
        _ = display_mode  # single-mode plugin; accepted for API consistency
        if not self.dynamic_duration_enabled:
            return None
        if not self.scroll_helper or not self.scroll_helper.cached_image:
            return None

        duration = self.scroll_helper.get_dynamic_duration()
        if not duration or duration <= 0:
            return None
        return float(duration) * (1.0 + max(0.0, self.duration_overrun_allowance))

    def reset_cycle_state(self) -> None:
        """Restart the ticker from the top when the controller comes back to it."""
        super().reset_cycle_state()
        self._cycle_complete = False
        self._cycle_complete_at = 0.0
        if self.scroll_helper:
            if self._page_dirty:
                # A page finished during the previous turn; render its successor.
                self._start_next_page()
            else:
                self.scroll_helper.reset_scroll()

    def is_cycle_complete(self) -> bool:
        """
        Check if the news ticker scroll cycle is complete.

        This method is called by the display controller to determine when
        to switch to the next plugin. Returns True only when the scroll
        has completed its full cycle, ensuring headlines aren't cut off.

        Returns:
            bool: True if scroll cycle is complete, False otherwise
        """
        if not self.dynamic_duration_enabled:
            # Nothing is pacing the hand-off, so never hold the display hostage.
            return True
        return self._cycle_complete

    def get_display_duration(self) -> float:
        """
        Get display duration, using dynamic duration if enabled.

        With dynamic duration active the controller reads this as the *minimum*
        time on screen and takes the real target from get_cycle_duration(). Only
        report a scroll-derived duration once a strip actually exists — the
        scroll helper otherwise returns its 60s placeholder, which used to be
        handed out as a flat duration on the very first turn.
        """
        if self.dynamic_duration_enabled and self.scroll_helper.cached_image:
            duration = self.scroll_helper.get_dynamic_duration()
            if duration > 0:
                return float(duration)

        # Fallback to configured duration
        return float(self.display_duration)

    def get_info(self) -> Dict[str, Any]:
        """Return plugin info for web UI."""
        info = super().get_info()
        
        # Get custom feed names (handle both formats)
        custom_feeds = self.feeds_config.get('custom_feeds', [])
        if isinstance(custom_feeds, list):
            custom_feed_names = [feed.get('name', '') for feed in custom_feeds if isinstance(feed, dict)]
        else:
            custom_feed_names = list(custom_feeds.keys()) if isinstance(custom_feeds, dict) else []
        
        info.update({
            'total_headlines': len(self.current_headlines),
            'enabled_feeds': self.feeds_config.get('enabled_feeds', []),
            'custom_feeds': custom_feed_names,
            'last_update': self.last_update,
            'display_duration': self.display_duration,
            'scroll_speed': self.scroll_speed,
            'rotation_enabled': self.rotation_enabled,
            'rotation_threshold': self.rotation_threshold,
            'headlines_per_feed': self.headlines_per_feed,
            'font_size': self.font_size,
            'text_color': self.text_color,
            'separator_color': self.separator_color,
            'show_logos': self.show_logos,
            'logo_size': self.logo_size,
            'feed_logo_map': self.feed_logo_map,
            'paging_enabled': self.paging_enabled,
            'page_start': self._page_start,
            'headlines_this_page': self._page_count,
            'page_width_budget': self._page_width_budget(),
            'duration_cap': self._effective_duration_cap()
        })
        return info

    def _rotate_headlines(self) -> None:
        """
        Rotate headlines to show fresh content.
        
        Moves the first headline to the end of the list, ensuring that
        different headlines are shown first on subsequent cycles. This
        provides content freshness without waiting for RSS feed updates.
        """
        if len(self.current_headlines) > 1:
            # Move first headline to end
            first_headline = self.current_headlines.pop(0)
            self.current_headlines.append(first_headline)
            self.logger.info(
                "Rotated headlines: '%s' moved to end (now showing: '%s' first)",
                first_headline.get('title', 'Unknown')[:50],
                self.current_headlines[0].get('title', 'Unknown')[:50]
            )

    def cleanup(self) -> None:
        """Cleanup resources."""
        self.current_headlines = []
        self._headline_image_cache = {}
        self._page_start = 0
        self._page_count = 0
        self._page_dirty = False
        if hasattr(self, 'scroll_helper'):
            self.scroll_helper.clear_cache()
        self.logger.info("News ticker plugin cleaned up")
