"""
Stocks Ticker Plugin for LEDMatrix

Displays scrolling stock tickers with prices, changes, and optional charts for stocks
and cryptocurrencies. Shows real-time market data in a continuous ticker format.

Features:
- Stock and cryptocurrency price tracking
- Real-time price updates and changes
- Optional chart display toggle
- Color-coded positive/negative changes
- Configurable display options
- Background data fetching

API Version: 1.0.0
"""

import logging
import time
import requests
import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from pathlib import Path

from src.plugin_system.base_plugin import BasePlugin

logger = logging.getLogger(__name__)


class StocksTickerPlugin(BasePlugin):
    """
    Stocks ticker plugin for displaying financial market data.

    Supports stocks and cryptocurrencies with real-time price tracking,
    change indicators, and optional chart display.

    Configuration options:
        stocks: Stock symbols and display options
        crypto: Cryptocurrency symbols and display options
        display_options: Scroll speed, duration, colors
        background_service: Data fetching configuration
    """

    def __init__(self, plugin_id: str, config: Dict[str, Any],
                 display_manager, cache_manager, plugin_manager):
        """Initialize the stocks ticker plugin."""
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)

        # Configuration
        self.stocks_config = config.get('stocks', {})
        self.crypto_config = config.get('crypto', {})
        self.global_config = config.get('global', {})

        # Display settings
        self.display_duration = self.global_config.get('display_duration', 30)
        self.scroll_speed = self.global_config.get('scroll_speed', 1)
        self.scroll_delay = self.global_config.get('scroll_delay', 0.01)
        self.dynamic_duration = self.global_config.get('dynamic_duration', True)
        self.min_duration = self.global_config.get('min_duration', 30)
        self.max_duration = self.global_config.get('max_duration', 300)
        self.toggle_chart = self.global_config.get('toggle_chart', False)
        self.font_size = self.global_config.get('font_size', 10)

        # Background service configuration
        self.background_config = self.global_config.get('background_service', {
            'enabled': True,
            'request_timeout': 30,
            'max_retries': 5,
            'priority': 2
        })

        # Colors for stocks
        stocks_text_color = tuple(self.stocks_config.get('text_color', [255, 255, 255]))
        stocks_positive_color = tuple(self.stocks_config.get('positive_color', [0, 255, 0]))
        stocks_negative_color = tuple(self.stocks_config.get('negative_color', [255, 0, 0]))

        # Colors for crypto
        crypto_text_color = tuple(self.crypto_config.get('text_color', [255, 215, 0]))
        crypto_positive_color = tuple(self.crypto_config.get('positive_color', [0, 255, 0]))
        crypto_negative_color = tuple(self.crypto_config.get('negative_color', [255, 0, 0]))

        # State
        self.stock_data = {}
        self.crypto_data = {}
        self.current_stock_index = 0
        self.scroll_position = 0
        self.last_update = 0
        self.chart_mode = False
        self.initialized = True

        # Register fonts
        self._register_fonts()

        # Log configuration
        stock_symbols = self.stocks_config.get('stock_symbols', [])
        crypto_symbols = self.crypto_config.get('crypto_symbols', [])

        self.logger.info("Stocks ticker plugin initialized")
        self.logger.info(f"Stock symbols: {stock_symbols}")
        self.logger.info(f"Crypto symbols: {crypto_symbols}")

    def _register_fonts(self):
        """Register fonts with the font manager."""
        try:
            if not hasattr(self.plugin_manager, 'font_manager'):
                return

            font_manager = self.plugin_manager.font_manager

            # Stock symbol font
            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.stock_symbol",
                family="press_start",
                size_px=self.font_size,
                color=tuple(self.stocks_config.get('text_color', [255, 255, 255]))
            )

            # Stock price font
            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.stock_price",
                family="press_start",
                size_px=self.font_size,
                color=tuple(self.stocks_config.get('positive_color', [0, 255, 0]))
            )

            # Stock change font
            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.stock_change",
                family="press_start",
                size_px=self.font_size - 2,
                color=tuple(self.stocks_config.get('text_color', [255, 255, 255]))
            )

            # Crypto symbol font
            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.crypto_symbol",
                family="press_start",
                size_px=self.font_size,
                color=tuple(self.crypto_config.get('text_color', [255, 215, 0]))
            )

            # Crypto price font
            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.crypto_price",
                family="press_start",
                size_px=self.font_size,
                color=tuple(self.crypto_config.get('positive_color', [0, 255, 0]))
            )

            # Info font (market cap, volume)
            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.info",
                family="four_by_six",
                size_px=6,
                color=(150, 150, 150)
            )

            self.logger.info("Stocks ticker fonts registered")
        except Exception as e:
            self.logger.warning(f"Error registering fonts: {e}")

    def update(self) -> None:
        """Update stock and crypto data."""
        if not self.initialized:
            return

        try:
            # Update stock data
            if self.stocks_config.get('stock_symbols'):
                self.stock_data = self._fetch_stock_data()

            # Update crypto data
            if self.crypto_config.get('enabled', True) and self.crypto_config.get('crypto_symbols'):
                self.crypto_data = self._fetch_crypto_data()

            self.last_update = time.time()
            self.logger.debug(f"Updated stock/crypto data")

        except Exception as e:
            self.logger.error(f"Error updating stock/crypto data: {e}")

    def _fetch_stock_data(self) -> Dict:
        """Fetch stock data for tracked symbols."""
        cache_key = f"stocks_data_{datetime.now().strftime('%Y%m%d%H%M')}"
        update_interval = self.global_config.get('update_interval_seconds', 60)

        # Check cache first
        cached_data = self.cache_manager.get(cache_key)
        if cached_data and (time.time() - self.last_update) < update_interval:
            self.logger.debug("Using cached stock data")
            return cached_data

        try:
            stock_symbols = self.stocks_config.get('stock_symbols', [])
            stock_data = {}

            # For now, return placeholder data since real stock APIs require API keys
            # In a real implementation, this would call financial data APIs
            for symbol in stock_symbols:
                stock_data[symbol] = {
                    'symbol': symbol,
                    'price': round(100 + (hash(symbol) % 200), 2),  # Mock price
                    'change': round((hash(symbol + 'change') % 20) - 10, 2),  # Mock change
                    'change_percent': round((hash(symbol + 'percent') % 10) - 5, 2),  # Mock percentage
                    'volume': (hash(symbol + 'vol') % 1000000) + 100000,  # Mock volume
                    'market_cap': (hash(symbol + 'cap') % 1000000000000) + 1000000000,  # Mock market cap
                    'last_updated': datetime.now().isoformat()
                }

            # Cache the results
            self.cache_manager.set(cache_key, stock_data, ttl=update_interval * 2)

            return stock_data

        except Exception as e:
            self.logger.error(f"Error fetching stock data: {e}")
            return {}

    def _fetch_crypto_data(self) -> Dict:
        """Fetch crypto data for tracked symbols."""
        cache_key = f"crypto_data_{datetime.now().strftime('%Y%m%d%H%M')}"
        update_interval = self.global_config.get('update_interval_seconds', 60)

        # Check cache first
        cached_data = self.cache_manager.get(cache_key)
        if cached_data and (time.time() - self.last_update) < update_interval:
            self.logger.debug("Using cached crypto data")
            return cached_data

        try:
            crypto_symbols = self.crypto_config.get('crypto_symbols', [])
            crypto_data = {}

            # For now, return placeholder data since real crypto APIs require API keys
            # In a real implementation, this would call cryptocurrency APIs
            for symbol in crypto_symbols:
                crypto_data[symbol] = {
                    'symbol': symbol,
                    'price': round(1000 + (hash(symbol) % 50000), 2),  # Mock price
                    'change': round((hash(symbol + 'change') % 1000) - 500, 2),  # Mock change
                    'change_percent': round((hash(symbol + 'percent') % 20) - 10, 2),  # Mock percentage
                    'volume': (hash(symbol + 'vol') % 100000000) + 1000000,  # Mock volume
                    'market_cap': (hash(symbol + 'cap') % 1000000000000) + 100000000000,  # Mock market cap
                    'last_updated': datetime.now().isoformat()
                }

            # Cache the results
            self.cache_manager.set(cache_key, crypto_data, ttl=update_interval * 2)

            return crypto_data

        except Exception as e:
            self.logger.error(f"Error fetching crypto data: {e}")
            return {}

    def display(self, display_mode: str = None, force_clear: bool = False) -> None:
        """
        Display scrolling stocks ticker.

        Args:
            display_mode: Should be 'stocks_ticker'
            force_clear: If True, clear display before rendering
        """
        if not self.initialized:
            self._display_error("Stocks ticker plugin not initialized")
            return

        if not self.stock_data and not self.crypto_data:
            self._display_no_data()
            return

        # Display scrolling ticker
        self._display_scrolling_ticker()

    def _display_scrolling_ticker(self):
        """Display scrolling stock/crypto ticker."""
        try:
            matrix_width = self.display_manager.matrix.width
            matrix_height = self.display_manager.matrix.height

            # Create base image
            img = Image.new('RGB', (matrix_width, matrix_height), (0, 0, 0))
            draw = ImageDraw.Draw(img)

            # For now, display first few items (placeholder for scrolling implementation)
            y_offset = 5
            items_displayed = 0
            max_items = 4

            # Display stock data first
            for symbol, data in list(self.stock_data.items())[:2]:
                if items_displayed >= max_items:
                    break

                if y_offset > matrix_height - 15:
                    break

                # TODO: Implement scrolling ticker display
                # TODO: Show symbol, price, change, percentage
                # TODO: Use font manager for text rendering
                # TODO: Add chart display if toggle_chart is enabled

                # Simple placeholder display
                price = data.get('price', 0)
                change = data.get('change', 0)
                change_str = f"+{change}" if change >= 0 else str(change)
                change_color = tuple(self.stocks_config.get('positive_color', [0, 255, 0])) if change >= 0 else tuple(self.stocks_config.get('negative_color', [255, 0, 0]))

                draw.text((5, y_offset), f"{symbol}:", fill=tuple(self.stocks_config.get('text_color', [255, 255, 255])))
                draw.text((50, y_offset), f"${price:.2f}", fill=tuple(self.stocks_config.get('positive_color', [0, 255, 0])))
                draw.text((100, y_offset), change_str, fill=change_color)

                y_offset += self.font_size + 5
                items_displayed += 1

            # Display crypto data
            for symbol, data in list(self.crypto_data.items())[:2]:
                if items_displayed >= max_items:
                    break

                if y_offset > matrix_height - 15:
                    break

                price = data.get('price', 0)
                change = data.get('change', 0)
                change_str = f"+{change}" if change >= 0 else str(change)
                change_color = tuple(self.crypto_config.get('positive_color', [0, 255, 0])) if change >= 0 else tuple(self.crypto_config.get('negative_color', [255, 0, 0]))

                draw.text((5, y_offset), f"{symbol}:", fill=tuple(self.crypto_config.get('text_color', [255, 215, 0])))
                draw.text((50, y_offset), f"${price:.2f}", fill=tuple(self.crypto_config.get('positive_color', [0, 255, 0])))
                draw.text((100, y_offset), change_str, fill=change_color)

                y_offset += self.font_size + 5
                items_displayed += 1

            self.display_manager.image = img.copy()
            self.display_manager.update_display()

        except Exception as e:
            self.logger.error(f"Error displaying stocks ticker: {e}")
            self._display_error("Display error")

    def _display_no_data(self):
        """Display message when no data is available."""
        img = Image.new('RGB', (self.display_manager.matrix.width,
                               self.display_manager.matrix.height),
                       (0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.text((5, 12), "No Stock Data", fill=(150, 150, 150))

        self.display_manager.image = img.copy()
        self.display_manager.update_display()

    def _display_error(self, message: str):
        """Display error message."""
        img = Image.new('RGB', (self.display_manager.matrix.width,
                               self.display_manager.matrix.height),
                       (0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.text((5, 12), message, fill=(255, 0, 0))

        self.display_manager.image = img.copy()
        self.display_manager.update_display()

    def get_display_duration(self) -> float:
        """Get display duration from config."""
        return self.display_duration

    def get_info(self) -> Dict[str, Any]:
        """Return plugin info for web UI."""
        info = super().get_info()
        info.update({
            'stock_symbols': self.stocks_config.get('stock_symbols', []),
            'crypto_symbols': self.crypto_config.get('crypto_symbols', []),
            'crypto_enabled': self.crypto_config.get('enabled', True),
            'toggle_chart': self.toggle_chart,
            'last_update': self.last_update,
            'display_duration': self.display_duration,
            'scroll_speed': self.scroll_speed,
            'show_change': self.stocks_config.get('show_change', True),
            'show_percentage': self.stocks_config.get('show_percentage', True),
            'show_volume': self.stocks_config.get('show_volume', False),
            'show_market_cap': self.stocks_config.get('show_market_cap', False)
        })
        return info

    def cleanup(self) -> None:
        """Cleanup resources."""
        self.stock_data = {}
        self.crypto_data = {}
        self.logger.info("Stocks ticker plugin cleaned up")
