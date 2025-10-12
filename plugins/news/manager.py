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
import time
import requests
import xml.etree.ElementTree as ET
import html
import re
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from pathlib import Path

from src.plugin_system.base_plugin import BasePlugin

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
        'MLB': 'http://espn.com/espn/rss/mlb/news',
        'NFL': 'http://espn.go.com/espn/rss/nfl/news',
        'NCAA FB': 'https://www.espn.com/espn/rss/ncf/news',
        'NHL': 'https://www.espn.com/espn/rss/nhl/news',
        'NBA': 'https://www.espn.com/espn/rss/nba/news',
        'TOP SPORTS': 'https://www.espn.com/espn/rss/news',
        'BIG10': 'https://www.espn.com/blog/feed?blog=bigten',
        'NCAA': 'https://www.espn.com/espn/rss/ncaa/news',
        'Other': 'https://www.coveringthecorner.com/rss/current.xml'
    }

    def __init__(self, plugin_id: str, config: Dict[str, Any],
                 display_manager, cache_manager, plugin_manager):
        """Initialize the news ticker plugin."""
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)

        # Configuration
        self.feeds_config = config.get('feeds', {})
        self.global_config = config.get('global', {})

        # Display settings
        self.display_duration = self.global_config.get('display_duration', 30)
        self.scroll_speed = self.global_config.get('scroll_speed', 2)
        self.scroll_delay = self.global_config.get('scroll_delay', 0.01)
        self.dynamic_duration = self.global_config.get('dynamic_duration', True)
        self.min_duration = self.global_config.get('min_duration', 30)
        self.max_duration = self.global_config.get('max_duration', 300)
        self.rotation_enabled = self.global_config.get('rotation_enabled', True)
        self.rotation_threshold = self.global_config.get('rotation_threshold', 3)
        self.headlines_per_feed = self.global_config.get('headlines_per_feed', 2)
        self.font_size = self.global_config.get('font_size', 12)

        # Colors
        self.text_color = tuple(self.feeds_config.get('text_color', [255, 255, 255]))
        self.separator_color = tuple(self.feeds_config.get('separator_color', [255, 0, 0]))

        # Background service configuration
        self.background_config = self.global_config.get('background_service', {
            'enabled': True,
            'request_timeout': 30,
            'max_retries': 3,
            'priority': 2
        })

        # State
        self.current_headlines = []
        self.current_headline_index = 0
        self.scroll_position = 0
        self.last_update = 0
        self.rotation_count = 0
        self.headlines_displayed = set()
        self.initialized = True

        # Register fonts
        self._register_fonts()

        # Log enabled feeds
        enabled_feeds = self.feeds_config.get('enabled_feeds', [])
        custom_feeds = list(self.feeds_config.get('custom_feeds', {}).keys())

        self.logger.info("News ticker plugin initialized")
        self.logger.info(f"Enabled predefined feeds: {enabled_feeds}")
        self.logger.info(f"Custom feeds: {custom_feeds}")

    def _register_fonts(self):
        """Register fonts with the font manager."""
        try:
            if not hasattr(self.plugin_manager, 'font_manager'):
                return

            font_manager = self.plugin_manager.font_manager

            # Headline font
            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.headline",
                family="press_start",
                size_px=self.font_size,
                color=self.text_color
            )

            # Separator font
            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.separator",
                family="press_start",
                size_px=self.font_size,
                color=self.separator_color
            )

            # Info font (source, time)
            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.info",
                family="four_by_six",
                size_px=6,
                color=(150, 150, 150)
            )

            self.logger.info("News ticker fonts registered")
        except Exception as e:
            self.logger.warning(f"Error registering fonts: {e}")

    def update(self) -> None:
        """Update news headlines from all enabled feeds."""
        if not self.initialized:
            return

        try:
            self.current_headlines = []

            # Fetch from enabled predefined feeds
            enabled_feeds = self.feeds_config.get('enabled_feeds', [])
            for feed_name in enabled_feeds:
                if feed_name in self.DEFAULT_FEEDS:
                    headlines = self._fetch_feed_headlines(feed_name, self.DEFAULT_FEEDS[feed_name])
                    if headlines:
                        self.current_headlines.extend(headlines)

            # Fetch from custom feeds
            custom_feeds = self.feeds_config.get('custom_feeds', {})
            for feed_name, feed_url in custom_feeds.items():
                headlines = self._fetch_feed_headlines(feed_name, feed_url)
                if headlines:
                    self.current_headlines.extend(headlines)

            # Limit total headlines and reset rotation tracking
            max_headlines = len(enabled_feeds) * self.headlines_per_feed + len(custom_feeds) * self.headlines_per_feed
            if len(self.current_headlines) > max_headlines:
                self.current_headlines = self.current_headlines[:max_headlines]

            # Reset rotation tracking for new content
            if self.current_headlines:
                self.headlines_displayed.clear()
                self.rotation_count = 0

            self.last_update = time.time()
            self.logger.debug(f"Updated news headlines: {len(self.current_headlines)} total")

        except Exception as e:
            self.logger.error(f"Error updating news headlines: {e}")

    def _fetch_feed_headlines(self, feed_name: str, feed_url: str) -> List[Dict]:
        """Fetch headlines from a specific RSS feed."""
        cache_key = f"news_{feed_name}_{datetime.now().strftime('%Y%m%d%H')}"
        update_interval = self.global_config.get('update_interval_seconds', 300)

        # Check cache first
        cached_data = self.cache_manager.get(cache_key)
        if cached_data and (time.time() - self.last_update) < update_interval:
            self.logger.debug(f"Using cached headlines for {feed_name}")
            return cached_data

        try:
            self.logger.info(f"Fetching headlines from {feed_name}...")
            response = requests.get(feed_url, timeout=self.background_config.get('request_timeout', 30))
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

        # Limit length for display
        if len(headline) > 100:
            headline = headline[:97] + "..."

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

        # Display scrolling headlines
        self._display_scrolling_headlines()

    def _display_scrolling_headlines(self):
        """Display scrolling news headlines."""
        try:
            matrix_width = self.display_manager.matrix.width
            matrix_height = self.display_manager.matrix.height

            # Create base image
            img = Image.new('RGB', (matrix_width, matrix_height), (0, 0, 0))
            draw = ImageDraw.Draw(img)

            # For now, display first few headlines (placeholder for scrolling implementation)
            y_offset = 5
            max_headlines = min(3, len(self.current_headlines))

            for i in range(max_headlines):
                if i >= len(self.current_headlines):
                    break

                headline = self.current_headlines[i]

                # TODO: Implement scrolling ticker display
                # TODO: Show headline text, source, and timing
                # TODO: Use font manager for text rendering

                # Simple placeholder display
                title = headline.get('title', 'No title')
                feed_name = headline.get('feed_name', 'Unknown')

                # Truncate for display
                if len(title) > 25:
                    title = title[:22] + "..."

                draw.text((5, y_offset), f"{feed_name}: {title}", fill=self.text_color)

                # Add separator between headlines
                if i < max_headlines - 1:
                    separator_y = y_offset + self.font_size + 2
                    draw.text((5, separator_y), "---", fill=self.separator_color)

                y_offset += self.font_size + 8

            self.display_manager.image = img.copy()
            self.display_manager.update_display()

        except Exception as e:
            self.logger.error(f"Error displaying news headlines: {e}")
            self._display_error("Display error")

    def _display_no_headlines(self):
        """Display message when no headlines are available."""
        img = Image.new('RGB', (self.display_manager.matrix.width,
                               self.display_manager.matrix.height),
                       (0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.text((5, 12), "No News Headlines", fill=(150, 150, 150))

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
            'total_headlines': len(self.current_headlines),
            'enabled_feeds': self.feeds_config.get('enabled_feeds', []),
            'custom_feeds': list(self.feeds_config.get('custom_feeds', {}).keys()),
            'last_update': self.last_update,
            'display_duration': self.display_duration,
            'scroll_speed': self.scroll_speed,
            'rotation_enabled': self.rotation_enabled,
            'rotation_threshold': self.rotation_threshold,
            'headlines_per_feed': self.headlines_per_feed,
            'font_size': self.font_size,
            'text_color': self.text_color,
            'separator_color': self.separator_color
        })
        return info

    def cleanup(self) -> None:
        """Cleanup resources."""
        self.current_headlines = []
        self.logger.info("News ticker plugin cleaned up")
