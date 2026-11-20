"""
Data Fetcher for Stock Ticker Plugin

Handles all API calls and data fetching for stock and cryptocurrency data
from Yahoo Finance.
"""

import re
import time
from pathlib import Path
from typing import Dict, Any, Iterable, Optional
from datetime import datetime

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

#: Logos the core's icon set lacks (ETFs such as VOO, SPY or QQQ have none)
#: are downloaded here once, from the source stock-news uses.
LOGO_CACHE_DIR = Path(__file__).resolve().parent / "assets" / "logos"
LOGO_URL = "https://financialmodelingprep.com/image-stock/{symbol}.png"
BUNDLED_ICON = "assets/stocks/ticker_icons/{symbol}.png"
_SAFE_SYMBOL = re.compile(r"[A-Z0-9][A-Z0-9.\-]{0,11}")


def downloaded_logo_path(symbol: str) -> Optional[Path]:
    """Where a downloaded logo for ``symbol`` lives; None for a symbol that
    cannot safely name a file."""
    if not _SAFE_SYMBOL.fullmatch(symbol or ""):
        return None
    return LOGO_CACHE_DIR / f"{symbol}.png"


def _round_money(value: float) -> float:
    """Cents, as always, from $0.10 up. Below that the value is kept whole:
    rounding a sub-cent coin to cents stored it as 0.0."""
    return round(value, 2) if abs(value) >= 0.1 else value


class StockDataFetcher:
    """Handles fetching stock and cryptocurrency data from Yahoo Finance API."""
    
    def __init__(self, config_manager, cache_manager, logger):
        """Initialize the data fetcher with configuration manager, cache manager, and logger."""
        self.config_manager = config_manager
        self.cache_manager = cache_manager
        self.logger = logger
        # Store config for compatibility with reload_config()
        self.config = config_manager.plugin_config
        
        # API configuration
        self.api_config = config_manager.api_config
        self.timeout = config_manager.timeout
        self.retry_count = config_manager.retry_count
        self.rate_limit_delay = config_manager.rate_limit_delay
        
        # Stock and crypto symbols
        self.stock_symbols = config_manager.stock_symbols
        self.crypto_symbols = config_manager.crypto_symbols
        
        # Symbols whose logo download failed, so it is tried once per run.
        self._logo_failed = set()

        # Initialize HTTP session
        self._init_http_session()

    def _init_http_session(self):
        """Initialize HTTP session with retry strategy."""
        self.session = requests.Session()
        
        # Configure retry strategy
        retry_strategy = Retry(
            total=self.retry_count,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
        # Set headers
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    _CHUNK_SIZE = 15  # symbols per burst; longer pause inserted between chunks

    def fetch_all_data(self) -> Dict[str, Any]:
        """Fetch data for all configured stocks and cryptocurrencies."""
        all_data = {}

        total_symbols = len(self.stock_symbols) + len(self.crypto_symbols)
        if total_symbols > 40 and self.config_manager.update_interval < 300:
            self.logger.warning(
                "Fetching %d symbols with update_interval=%ds — consider increasing "
                "update_interval to 300s or more to avoid rate limiting.",
                total_symbols, self.config_manager.update_interval
            )

        # Fetch stock data
        for i, symbol in enumerate(self.stock_symbols):
            try:
                data = self.fetch_stock_data(symbol, is_crypto=False)
                if data:
                    all_data[symbol] = data
                    self.logger.debug("Updated stock data for %s", symbol)
                else:
                    self.logger.warning("No data returned for stock %s", symbol)
            except Exception as e:
                self.logger.error("Error fetching stock data for %s: %s", symbol, e)
            finally:
                time.sleep(self.rate_limit_delay)
            if (i + 1) % self._CHUNK_SIZE == 0:
                time.sleep(1.0)

        # Fetch crypto data
        for i, symbol in enumerate(self.crypto_symbols):
            try:
                # Quote in USD unless the symbol already names a quote
                # currency. Testing for '-USD' specifically turned BTC-EUR into
                # BTC-EUR-USD, which Yahoo has no data for; any pair already
                # carries its quote after the hyphen.
                api_symbol = symbol if '-' in symbol else f"{symbol}-USD"
                data = self.fetch_stock_data(api_symbol, is_crypto=True)
                if data:
                    all_data[symbol] = data  # Store with original symbol name
                    self.logger.debug("Updated crypto data for %s", symbol)
                else:
                    self.logger.warning("No data returned for crypto %s", symbol)
            except Exception as e:
                self.logger.error("Error fetching crypto data for %s: %s", symbol, e)
            finally:
                time.sleep(self.rate_limit_delay)
            if (i + 1) % self._CHUNK_SIZE == 0:
                time.sleep(1.0)

        return all_data
    
    def fetch_stock_data(self, symbol: str, is_crypto: bool = False) -> Optional[Dict[str, Any]]:
        """Fetch data for a single stock or cryptocurrency."""
        api_symbol = symbol
        display_symbol = symbol.replace('-USD', '') if is_crypto else symbol
        
        # Check cache first. Crypto has its own prefix: stock SOL and crypto
        # SOL-USD both display as "SOL" and used to share one entry.
        cache_key = f"{'crypto' if is_crypto else 'stock'}_data_{display_symbol}"
        # Each type is cached for its own interval: crypto.update_interval for
        # crypto (it was read and never used), update_interval for stocks.
        cache_ttl = (self.config_manager.crypto_update_interval if is_crypto
                     else self.config_manager.update_interval)

        if self.cache_manager:
            # Half the interval: the entry is written partway through an
            # update, so a max_age of the full interval was still fresh at the
            # next scheduled update and every symbol refreshed only on every
            # other one.
            cached_data = self.cache_manager.get(cache_key, max_age=max(1, cache_ttl // 2))
            if cached_data:
                self.logger.debug("Using cached data for %s", display_symbol)
                return cached_data

        result = self._fetch_direct(api_symbol, display_symbol, is_crypto)
        
        # Cache the result if successful
        if result and self.cache_manager:
            self.cache_manager.set(cache_key, result)
            self.logger.debug("Cached data for %s (max_age: %ds)", display_symbol, cache_ttl)
        
        return result
    
    def _fetch_direct(self, api_symbol: str, display_symbol: str, is_crypto: bool) -> Optional[Dict[str, Any]]:
        """Fetch data directly from Yahoo Finance API."""
        try:
            
            # Build URL
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{api_symbol}"
            params = {
                'interval': '5m',
                'range': '1d'
            }
            
            # Make request
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            
            # Parse response
            data = response.json()
            
            if 'chart' not in data or not data['chart']['result']:
                self.logger.warning("No chart data found for %s", api_symbol)
                return None
            
            result = data['chart']['result'][0]
            meta = result.get('meta', {})
            
            # Extract current price and change
            current_price = meta.get('regularMarketPrice', 0)
            previous_close = meta.get('previousClose', 0)
            change = current_price - previous_close
            change_percent = (change / previous_close * 100) if previous_close > 0 else 0
            
            # Extract price history for chart
            price_history = []
            if 'timestamp' in result and 'indicators' in result:
                timestamps = result['timestamp']
                quotes = result['indicators'].get('quote', [{}])[0]
                closes = quotes.get('close', [])
                
                for i, timestamp in enumerate(timestamps):
                    if i < len(closes) and closes[i] is not None:
                        price_history.append({
                            'timestamp': datetime.fromtimestamp(timestamp),
                            'price': closes[i]
                        })
            
            # Create result data - matching old manager structure
            result_data = {
                'symbol': display_symbol,
                'name': meta.get('symbol', display_symbol),  # Use symbol as name if not available
                'price': _round_money(current_price),
                'change': _round_money(change),  # Dollar change (current_price - previous_close)
                'change_percent': round(change_percent, 2),  # Percentage change
                'open': previous_close,  # Store previous_close as "open" to match old structure
                'price_history': price_history,
                'is_crypto': is_crypto
            }
            
            return result_data
            
        except requests.exceptions.RequestException as e:
            self.logger.error("API request failed for %s: %s", api_symbol, e)
            return None
        except (KeyError, ValueError, TypeError) as e:
            self.logger.error("Error parsing API response for %s: %s", api_symbol, e)
            return None
        except Exception as e:
            self.logger.error("Unexpected error fetching data for %s: %s", api_symbol, e)
            return None
    
    def download_missing_logos(self, symbols: Iterable[str]) -> int:
        """Fetch a logo for each stock with neither a bundled icon nor a
        downloaded one. Each symbol is asked for once per run (a miss or
        error is remembered), so this costs nothing once logos exist.
        Returns the number saved."""
        saved = 0
        for symbol in symbols:
            path = downloaded_logo_path(symbol)
            if (path is None or symbol in self._logo_failed or path.exists()
                    or Path(BUNDLED_ICON.format(symbol=symbol)).exists()):
                continue
            try:
                resp = self.session.get(LOGO_URL.format(symbol=symbol), timeout=self.timeout)
                if resp.status_code == 200 and resp.content.startswith(b"\x89PNG"):
                    path.parent.mkdir(parents=True, exist_ok=True)
                    # Atomic: a half-written file would look present and fail to decode.
                    tmp = path.with_name(path.name + ".part")
                    tmp.write_bytes(resp.content)
                    tmp.replace(path)
                    self.logger.info("Downloaded logo for %s", symbol)
                    saved += 1
                    continue
                self.logger.debug("No logo available for %s (HTTP %s)", symbol, resp.status_code)
            except (requests.RequestException, OSError) as e:
                self.logger.debug("Logo download failed for %s: %s", symbol, e)
            self._logo_failed.add(symbol)
        return saved

    def cleanup(self):
        """Clean up resources."""
        if self.session:
            self.session.close()
