"""
Odds Ticker Plugin for LEDMatrix

Displays scrolling odds and betting lines for upcoming games across multiple sports leagues.
Shows point spreads, money lines, and over/under totals with team information.

Features:
- Multi-sport odds display (NFL, NBA, MLB, NCAA Football, NCAA Basketball)
- Scrolling ticker format
- Favorite team prioritization
- Broadcast channel logos
- Configurable scroll speed and display duration
- Background data fetching

API Version: 1.0.0
"""

import logging
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from pathlib import Path

import requests
from PIL import Image, ImageDraw

from src.plugin_system.base_plugin import BasePlugin

# Import odds manager for data access
try:
    from src.odds_manager import OddsManager
except ImportError:
    OddsManager = None

logger = logging.getLogger(__name__)


class OddsTickerPlugin(BasePlugin):
    """
    Odds ticker plugin for displaying betting odds across multiple sports.

    Supports NFL, NBA, MLB, NCAA Football, and NCAA Basketball with configurable
    display options and scrolling ticker format.

    Configuration options:
        leagues: Enable/disable specific sports for odds
        display_options: Scroll speed, duration, favorite teams only
        background_service: Data fetching configuration
    """

    def __init__(self, plugin_id: str, config: Dict[str, Any],
                 display_manager, cache_manager, plugin_manager):
        """Initialize the odds ticker plugin."""
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)

        if OddsManager is None:
            self.logger.error("Failed to import OddsManager. Plugin will not function.")
            self.initialized = False
            return

        # Configuration
        self.leagues = config.get('leagues', {})
        self.global_config = config.get('global', {})

        # Display settings
        self.display_duration = self.global_config.get('display_duration', 30)
        self.scroll_speed = self.global_config.get('scroll_speed', 2)
        self.scroll_delay = self.global_config.get('scroll_delay', 0.05)
        self.show_favorite_teams_only = self.global_config.get('show_favorite_teams_only', False)
        self.games_per_favorite_team = self.global_config.get('games_per_favorite_team', 1)
        self.max_games_per_league = self.global_config.get('max_games_per_league', 5)
        self.show_odds_only = self.global_config.get('show_odds_only', False)
        self.future_fetch_days = self.global_config.get('future_fetch_days', 7)

        # Background service configuration
        self.background_config = self.global_config.get('background_service', {
            'enabled': True,
            'request_timeout': 30,
            'max_retries': 3,
            'priority': 2
        })

        # State
        self.current_odds = []
        self.scroll_position = 0
        self.last_update = 0
        self.odds_manager = OddsManager(self.cache_manager, None)
        self.initialized = True

        # Register fonts
        self._register_fonts()

        # Log enabled leagues and their settings
        enabled_leagues = []
        for league_key, league_config in self.leagues.items():
            if league_config.get('enabled', False):
                enabled_leagues.append(league_key)

        self.logger.info("Odds ticker plugin initialized")
        self.logger.info(f"Enabled leagues: {enabled_leagues}")

    def _register_fonts(self):
        """Register fonts with the font manager."""
        try:
            if not hasattr(self.plugin_manager, 'font_manager'):
                return

            font_manager = self.plugin_manager.font_manager

            # Team name font
            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.team_name",
                family="press_start",
                size_px=10,
                color=(255, 255, 255)
            )

            # Odds font
            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.odds",
                family="press_start",
                size_px=10,
                color=(255, 200, 0)
            )

            # Info font (time, channel)
            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.info",
                family="four_by_six",
                size_px=6,
                color=(200, 200, 200)
            )

            self.logger.info("Odds ticker fonts registered")
        except Exception as e:
            self.logger.warning(f"Error registering fonts: {e}")

    def update(self) -> None:
        """Update odds data for all enabled leagues."""
        if not self.initialized:
            return

        try:
            self.current_odds = []

            # Fetch odds for each enabled league
            for league_key, league_config in self.leagues.items():
                if league_config.get('enabled', False):
                    odds_data = self._fetch_league_odds(league_key, league_config)
                    if odds_data:
                        # Add league info to each odds entry
                        for odds in odds_data:
                            odds['league_config'] = league_config
                        self.current_odds.extend(odds_data)

            # Sort odds by game time
            self._sort_odds()

            self.last_update = time.time()
            self.logger.debug(f"Updated odds data: {len(self.current_odds)} games")

        except Exception as e:
            self.logger.error(f"Error updating odds data: {e}")

    def _sort_odds(self):
        """Sort odds by game time."""
        def sort_key(odds):
            game_time = odds.get('game_time', '')
            # Convert to timestamp for sorting
            try:
                if isinstance(game_time, str):
                    # Simple string comparison for now
                    return game_time
                return 0
            except:
                return 0

        self.current_odds.sort(key=sort_key)

    def _fetch_league_odds(self, league_key: str, league_config: Dict) -> List[Dict]:
        """Fetch odds data for a specific league."""
        cache_key = f"odds_{league_key}_{datetime.now().strftime('%Y%m%d')}"
        update_interval = self.global_config.get('update_interval_seconds', 3600)

        # Check cache first
        cached_data = self.cache_manager.get(cache_key)
        if cached_data and (time.time() - self.last_update) < update_interval:
            self.logger.debug(f"Using cached odds data for {league_key}")
            return cached_data

        # Fetch from odds manager
        try:
            # Get upcoming games for this league
            games = self._get_upcoming_games(league_key, league_config)

            odds_data = []
            for game in games[:self.max_games_per_league]:
                game_odds = self._get_game_odds(game, league_key, league_config)
                if game_odds:
                    odds_data.append(game_odds)

            # Cache the results
            self.cache_manager.set(cache_key, odds_data, ttl=update_interval * 2)

            return odds_data

        except Exception as e:
            self.logger.error(f"Error fetching odds for {league_key}: {e}")
            return []

    def _get_upcoming_games(self, league_key: str, league_config: Dict) -> List[Dict]:
        """Get upcoming games for a league (placeholder implementation)."""
        # This would typically call the appropriate scoreboard API
        # For now, return empty list as this would need integration with the main LEDMatrix
        return []

    def _get_game_odds(self, game: Dict, league_key: str, league_config: Dict) -> Optional[Dict]:
        """Get odds for a specific game."""
        try:
            # Use odds manager to get odds data
            # This is a simplified version - in practice would integrate with the main odds system
            odds_info = {
                'league': league_key,
                'league_config': league_config,
                'game_id': game.get('game_id', ''),
                'home_team': game.get('home_team', {}),
                'away_team': game.get('away_team', {}),
                'game_time': game.get('start_time', ''),
                'odds': {
                    'spread': 'TBD',
                    'moneyline': 'TBD',
                    'total': 'TBD'
                }
            }

            return odds_info

        except Exception as e:
            self.logger.error(f"Error getting game odds: {e}")
            return None

    def display(self, display_mode: str = None, force_clear: bool = False) -> None:
        """
        Display scrolling odds ticker.

        Args:
            display_mode: Should be 'odds_ticker'
            force_clear: If True, clear display before rendering
        """
        if not self.initialized:
            self._display_error("Odds ticker plugin not initialized")
            return

        if not self.current_odds:
            self._display_no_odds()
            return

        # Display scrolling ticker
        self._display_scrolling_odds()

    def _display_scrolling_odds(self):
        """Display scrolling odds ticker."""
        try:
            matrix_width = self.display_manager.matrix.width
            matrix_height = self.display_manager.matrix.height

            # Create base image
            img = Image.new('RGB', (matrix_width, matrix_height), (0, 0, 0))
            draw = ImageDraw.Draw(img)

            # For now, display first set of odds (placeholder for scrolling implementation)
            if self.current_odds:
                odds = self.current_odds[0]

                # TODO: Implement scrolling ticker display
                # TODO: Show team names, odds, and channel logos
                # TODO: Use font manager for text rendering

                home_team = odds.get('home_team', {})
                away_team = odds.get('away_team', {})

                # Simple placeholder display
                draw.text((5, 5), f"{away_team.get('abbrev', 'AWAY')} @ {home_team.get('abbrev', 'HOME')}",
                         fill=(255, 255, 255))
                draw.text((5, 15), "Odds: TBD", fill=(255, 200, 0))

            self.display_manager.image = img.copy()
            self.display_manager.update_display()

        except Exception as e:
            self.logger.error(f"Error displaying odds ticker: {e}")
            self._display_error("Display error")

    def _display_no_odds(self):
        """Display message when no odds are available."""
        img = Image.new('RGB', (self.display_manager.matrix.width,
                               self.display_manager.matrix.height),
                       (0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.text((5, 12), "No Odds Available", fill=(150, 150, 150))

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

        # Get league-specific configurations
        leagues_config = {}
        for league_key, league_config in self.leagues.items():
            leagues_config[league_key] = {
                'enabled': league_config.get('enabled', False),
                'favorite_teams': league_config.get('favorite_teams', []),
                'display_modes': league_config.get('display_modes', {}),
                'recent_games_to_show': league_config.get('recent_games_to_show', 5),
                'upcoming_games_to_show': league_config.get('upcoming_games_to_show', 10),
                'update_interval_seconds': league_config.get('update_interval_seconds', 60)
            }

        info.update({
            'total_games': len(self.current_odds),
            'enabled_leagues': [k for k, v in self.leagues.items() if v.get('enabled', False)],
            'last_update': self.last_update,
            'display_duration': self.display_duration,
            'scroll_speed': self.scroll_speed,
            'show_favorite_teams_only': self.show_favorite_teams_only,
            'max_games_per_league': self.max_games_per_league,
            'leagues_config': leagues_config,
            'global_config': self.global_config,
            'background_config': self.background_config
        })
        return info

    def cleanup(self) -> None:
        """Cleanup resources."""
        self.current_odds = []
        self.logger.info("Odds ticker plugin cleaned up")
