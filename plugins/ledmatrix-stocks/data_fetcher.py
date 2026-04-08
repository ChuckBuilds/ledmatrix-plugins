"""
Data Fetcher for Stock Ticker Plugin

Handles all API calls, data fetching, and background service integration
for stock and cryptocurrency data from Yahoo Finance.
"""

import re
import json
from typing import Dict, Any, Optional
from datetime import datetime

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Import common utilities
from src.common import APIHelper

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
        
        # Initialize HTTP session
        self._init_http_session()
        
        # Initialize API helper
        self.api_helper = APIHelper(cache_manager=cache_manager, logger=logger)
        
        # Background service
        self.background_service = None
        self._init_background_service()
    
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
    
    def _init_background_service(self):
        """Initialize background data service if available."""
        try:
            from src.background_data_service import get_background_service
            self.background_service = get_background_service(self.cache_manager)
            if self.background_service:
                self.logger.info("Background service initialized")
            else:
                self.logger.warning("Background service not available")
        except ImportError:
            self.logger.warning("Background service not available")
    
    def fetch_all_data(self) -> Dict[str, Any]:
        """Fetch data for all configured stocks and cryptocurrencies."""
        all_data = {}
        
        
        # Fetch stock data
        for symbol in self.stock_symbols:
            try:
                data = self.fetch_stock_data(symbol, is_crypto=False)
                if data:
                    all_data[symbol] = data
                    self.logger.debug("Updated stock data for %s", symbol)
                else:
                    self.logger.warning("No data returned for stock %s", symbol)
            except Exception as e:
                self.logger.error("Error fetching stock data for %s: %s", symbol, e)
        
        # Fetch crypto data
        for symbol in self.crypto_symbols:
            try:
                # Add -USD suffix for Yahoo Finance API if not already present
                api_symbol = symbol if symbol.endswith('-USD') else f"{symbol}-USD"
                data = self.fetch_stock_data(api_symbol, is_crypto=True)
                if data:
                    all_data[symbol] = data  # Store with original symbol name
                    self.logger.debug("Updated crypto data for %s", symbol)
                else:
                    self.logger.warning("No data returned for crypto %s", symbol)
            except Exception as e:
                self.logger.error("Error fetching crypto data for %s: %s", symbol, e)
        
        return all_data
    
    def fetch_stock_data(self, symbol: str, is_crypto: bool = False) -> Optional[Dict[str, Any]]:
        """Fetch data for a single stock or cryptocurrency."""
        api_symbol = symbol
        display_symbol = symbol.replace('-USD', '') if is_crypto else symbol
        
        # Check cache first
        cache_key = f"stock_data_{display_symbol}"
        cache_ttl = self.config_manager.update_interval if hasattr(self.config_manager, 'update_interval') else 300
        
        if self.cache_manager:
            cached_data = self.cache_manager.get(cache_key, max_age=cache_ttl)
            if cached_data:
                self.logger.debug("Using cached data for %s", display_symbol)
                return cached_data
        
        # Try background service first
        if self.background_service and hasattr(self.background_service, 'submit'):
            result = self._fetch_via_background_service(api_symbol, display_symbol, is_crypto)
        else:
            result = self._fetch_direct(api_symbol, display_symbol, is_crypto)
        
        # Cache the result if successful
        if result and self.cache_manager:
            self.cache_manager.set(cache_key, result)
            self.logger.debug("Cached data for %s (max_age: %ds)", display_symbol, cache_ttl)
        
        return result
    
    def _fetch_via_background_service(self, api_symbol: str, display_symbol: str, is_crypto: bool) -> Optional[Dict[str, Any]]:
        """Fetch data using background service."""
        def fetch_task():
            return self._fetch_direct(api_symbol, display_symbol, is_crypto)
        
        try:
            if hasattr(self.background_service, 'submit'):
                result = self.background_service.submit(fetch_task)
                return result
            else:
                return self._fetch_direct(api_symbol, display_symbol, is_crypto)
        except Exception as e:
            self.logger.error("Background service fetch failed for %s: %s", api_symbol, e)
            return self._fetch_direct(api_symbol, display_symbol, is_crypto)
    
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
                'price': round(current_price, 2),
                'change': round(change, 2),  # Dollar change (current_price - previous_close)
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
    
    def _extract_json_from_html(self, html: str) -> Dict:
        """Extract JSON data from HTML response (fallback method)."""
        try:
            # Look for JSON data in script tags
            pattern = r'root\.App\.main\s*=\s*({.*?});'
            match = re.search(pattern, html, re.DOTALL)
            
            if match:
                json_str = match.group(1)
                return json.loads(json_str)
            
            return {}
        except (json.JSONDecodeError, AttributeError) as e:
            self.logger.error("Error extracting JSON from HTML: %s", e)
            return {}
    
    def cleanup(self):
        """Clean up resources."""
        if self.session:
            self.session.close()
