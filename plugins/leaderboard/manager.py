"""
Leaderboard Plugin for LEDMatrix

Displays scrolling leaderboards and standings for multiple sports leagues.
Shows team rankings, records, and statistics in a scrolling ticker format.

Features:
- Multi-sport leaderboard display (NFL, NBA, MLB, NCAA, NHL)
- Conference and division filtering
- NCAA rankings vs standings
- Scrolling ticker format with dynamic duration
- Configurable scroll speed and display options
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

logger = logging.getLogger(__name__)


class LeaderboardPlugin(BasePlugin):
    """
    Leaderboard plugin for displaying sports standings and rankings.

    Supports multiple sports leagues with configurable display options,
    conference/division filtering, and scrolling ticker format.

    Configuration options:
        leagues: Enable/disable specific sports leagues
        display_options: Scroll speed, duration, filtering options
        background_service: Data fetching configuration
    """

    # ESPN API endpoints for standings
    ESPN_STANDINGS_URLS = {
        'nfl': 'https://site.api.espn.com/apis/v2/sports/football/nfl/standings',
        'nba': 'https://site.api.espn.com/apis/v2/sports/basketball/nba/standings',
        'mlb': 'https://site.api.espn.com/apis/v2/sports/baseball/mlb/standings',
        'nhl': 'https://site.api.espn.com/apis/v2/sports/hockey/nhl/standings',
        'ncaa_fb': 'https://site.api.espn.com/apis/v2/sports/football/college-football/standings',
        'ncaam_basketball': 'https://site.api.espn.com/apis/v2/sports/basketball/mens-college-basketball/standings',
        'ncaaw_basketball': 'https://site.api.espn.com/apis/v2/sports/basketball/womens-college-basketball/standings'
    }

    def __init__(self, plugin_id: str, config: Dict[str, Any],
                 display_manager, cache_manager, plugin_manager):
        """Initialize the leaderboard plugin."""
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)

        # Configuration
        self.leagues = config.get('leagues', {})
        self.global_config = config.get('global', {})

        # Display settings
        self.display_duration = self.global_config.get('display_duration', 30)
        self.scroll_speed = self.global_config.get('scroll_speed', 2)
        self.scroll_delay = self.global_config.get('scroll_delay', 0.01)
        self.dynamic_duration = self.global_config.get('dynamic_duration', True)
        self.min_duration = self.global_config.get('min_duration', 30)
        self.max_duration = self.global_config.get('max_duration', 300)
        self.loop = self.global_config.get('loop', True)

        # Background service configuration
        self.background_config = self.global_config.get('background_service', {
            'enabled': True,
            'request_timeout': 30,
            'max_retries': 3,
            'priority': 2
        })

        # State
        self.current_standings = []
        self.scroll_position = 0
        self.last_update = 0
        self.standings_image = None
        self.total_scroll_width = 0
        self.initialized = True

        # Register fonts
        self._register_fonts()

        # Log enabled leagues and their settings
        enabled_leagues = []
        for league_key, league_config in self.leagues.items():
            if league_config.get('enabled', False):
                enabled_leagues.append(league_key)

        self.logger.info("Leaderboard plugin initialized")
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

            # Record font
            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.record",
                family="press_start",
                size_px=8,
                color=(200, 200, 0)
            )

            # Rank font
            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.rank",
                family="press_start",
                size_px=8,
                color=(0, 255, 0)
            )

            # Conference font
            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.conference",
                family="four_by_six",
                size_px=6,
                color=(150, 150, 150)
            )

            self.logger.info("Leaderboard fonts registered")
        except Exception as e:
            self.logger.warning(f"Error registering fonts: {e}")

    def update(self) -> None:
        """Update standings data for all enabled leagues."""
        if not self.initialized:
            return

        try:
            self.current_standings = []

            # Fetch standings for each enabled league
            for league_key, league_config in self.leagues.items():
                if league_config.get('enabled', False):
                    standings_data = self._fetch_league_standings(league_key, league_config)
                    if standings_data:
                        self.current_standings.extend(standings_data)

            # Sort standings by league priority
            self._sort_standings()

            self.last_update = time.time()
            self.logger.debug(f"Updated standings data: {len(self.current_standings)} teams")

        except Exception as e:
            self.logger.error(f"Error updating standings data: {e}")

    def _sort_standings(self):
        """Sort standings by league and rank."""
        def sort_key(standing):
            league = standing.get('league', '')
            rank = standing.get('rank', 999)

            # League priority (NFL, NBA, MLB, NHL, NCAA)
            league_priority = {
                'nfl': 1,
                'nba': 2,
                'mlb': 3,
                'nhl': 4,
                'ncaa_fb': 5,
                'ncaam_basketball': 6,
                'ncaaw_basketball': 7
            }.get(league, 99)

            return (league_priority, rank)

        self.current_standings.sort(key=sort_key)

    def _fetch_league_standings(self, league_key: str, league_config: Dict) -> List[Dict]:
        """Fetch standings data for a specific league."""
        cache_key = f"standings_{league_key}_{datetime.now().strftime('%Y%m%d')}"
        update_interval = self.global_config.get('update_interval_seconds', 3600)

        # Check cache first
        cached_data = self.cache_manager.get(cache_key)
        if cached_data and (time.time() - self.last_update) < update_interval:
            self.logger.debug(f"Using cached standings data for {league_key}")
            return cached_data

        # Fetch from API
        try:
            url = self.ESPN_STANDINGS_URLS.get(league_key)
            if not url:
                self.logger.error(f"Unknown league key: {league_key}")
                return []

            self.logger.info(f"Fetching {league_key} standings from ESPN API...")
            response = requests.get(url, timeout=self.background_config.get('request_timeout', 30))
            response.raise_for_status()

            data = response.json()
            standings = self._process_standings_response(data, league_key, league_config)

            # Cache the results
            self.cache_manager.set(cache_key, standings, ttl=update_interval * 2)

            return standings

        except requests.RequestException as e:
            self.logger.error(f"Error fetching {league_key} standings: {e}")
            return []
        except Exception as e:
            self.logger.error(f"Error processing {league_key} standings: {e}")
            return []

    def _process_standings_response(self, data: Dict, league_key: str, league_config: Dict) -> List[Dict]:
        """Process ESPN standings API response into standardized format."""
        standings = []

        try:
            # Extract standings based on league structure
            if league_key in ['nfl', 'nba', 'nhl']:
                # Conference-based standings
                children = data.get('children', [])
                for conference in children:
                    entries = conference.get('standings', {}).get('entries', [])
                    conference_name = conference.get('name', '')

                    for entry in entries:
                        team = entry.get('team', {})
                        stats = entry.get('stats', [])

                        standing = {
                            'league': league_key,
                            'league_config': league_config,
                            'conference': conference_name,
                            'rank': entry.get('stats', [{}])[0].get('value', 0) if stats else 0,
                            'team': {
                                'name': team.get('displayName', 'Unknown'),
                                'abbrev': team.get('abbreviation', 'UNK'),
                                'logo': team.get('logo', '')
                            },
                            'record': self._extract_record(stats),
                            'stats': stats
                        }

                        # Filter by conference/division if specified
                        if self._should_include_standing(standing, league_config):
                            standings.append(standing)

            elif league_key in ['mlb']:
                # League/division-based standings
                children = data.get('children', [])
                for league_data in children:
                    divisions = league_data.get('standings', {}).get('entries', [])
                    league_name = league_data.get('name', '')

                    for division in divisions:
                        entries = division.get('children', [])
                        for entry in entries:
                            team = entry.get('team', {})
                            stats = entry.get('stats', [])

                            standing = {
                                'league': league_key,
                                'league_config': league_config,
                                'league_name': league_name,
                                'rank': entry.get('stats', [{}])[0].get('value', 0) if stats else 0,
                                'team': {
                                    'name': team.get('displayName', 'Unknown'),
                                    'abbrev': team.get('abbreviation', 'UNK'),
                                    'logo': team.get('logo', '')
                                },
                                'record': self._extract_record(stats),
                                'stats': stats
                            }

                            if self._should_include_standing(standing, league_config):
                                standings.append(standing)

            elif league_key.startswith('ncaa'):
                # NCAA rankings/standings
                rankings = data.get('rankings', [])
                for ranking in rankings:
                    entries = ranking.get('ranks', [])
                    for entry in entries[:25]:  # Top 25
                        team = entry.get('team', {})
                        record = entry.get('recordSummary', '')

                        standing = {
                            'league': league_key,
                            'league_config': league_config,
                            'rank': entry.get('current', 0),
                            'team': {
                                'name': team.get('displayName', 'Unknown'),
                                'abbrev': team.get('abbreviation', 'UNK'),
                                'logo': team.get('logo', '')
                            },
                            'record': record,
                            'points': entry.get('points', 0)
                        }

                        standings.append(standing)

        except Exception as e:
            self.logger.error(f"Error processing standings response: {e}")

        return standings

    def _extract_record(self, stats: List) -> str:
        """Extract win-loss record from stats."""
        if not stats:
            return "0-0"

        # Find wins and losses stats
        wins = 0
        losses = 0

        for stat in stats:
            if stat.get('name') == 'wins':
                wins = stat.get('value', 0)
            elif stat.get('name') == 'losses':
                losses = stat.get('value', 0)

        return f"{wins}-{losses}"

    def _should_include_standing(self, standing: Dict, league_config: Dict) -> bool:
        """Check if standing should be included based on configuration."""
        conference_filter = league_config.get('conference', 'both')
        division_filter = league_config.get('division', 'all')

        if conference_filter != 'both':
            standing_conference = standing.get('conference', '').lower()
            if conference_filter not in standing_conference:
                return False

        if division_filter != 'all':
            # Division filtering logic would go here
            pass

        return True

    def display(self, display_mode: str = None, force_clear: bool = False) -> None:
        """
        Display scrolling leaderboard.

        Args:
            display_mode: Should be 'leaderboard'
            force_clear: If True, clear display before rendering
        """
        if not self.initialized:
            self._display_error("Leaderboard plugin not initialized")
            return

        if not self.current_standings:
            self._display_no_standings()
            return

        # Display scrolling leaderboard
        self._display_scrolling_standings()

    def _display_scrolling_standings(self):
        """Display scrolling standings ticker."""
        try:
            matrix_width = self.display_manager.matrix.width
            matrix_height = self.display_manager.matrix.height

            # Create base image
            img = Image.new('RGB', (matrix_width, matrix_height), (0, 0, 0))
            draw = ImageDraw.Draw(img)

            # For now, display first few standings (placeholder for scrolling implementation)
            y_offset = 5
            for i, standing in enumerate(self.current_standings[:5]):  # Show first 5
                if y_offset > matrix_height - 15:
                    break

                team = standing.get('team', {})
                rank = standing.get('rank', 0)
                record = standing.get('record', '0-0')

                # TODO: Implement scrolling ticker display
                # TODO: Show rank, team name, record, conference
                # TODO: Use font manager for text rendering

                # Simple placeholder display
                draw.text((5, y_offset), f"{rank}. {team.get('abbrev', 'UNK')} {record}",
                         fill=(255, 255, 255))
                y_offset += 12

            self.display_manager.image = img.copy()
            self.display_manager.update_display()

        except Exception as e:
            self.logger.error(f"Error displaying leaderboard: {e}")
            self._display_error("Display error")

    def _display_no_standings(self):
        """Display message when no standings are available."""
        img = Image.new('RGB', (self.display_manager.matrix.width,
                               self.display_manager.matrix.height),
                       (0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.text((5, 12), "No Standings Available", fill=(150, 150, 150))

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
            'total_teams': len(self.current_standings),
            'enabled_leagues': [k for k, v in self.leagues.items() if v.get('enabled', False)],
            'last_update': self.last_update,
            'display_duration': self.display_duration,
            'scroll_speed': self.scroll_speed,
            'dynamic_duration': self.dynamic_duration,
            'min_duration': self.min_duration,
            'max_duration': self.max_duration
        })
        return info

    def cleanup(self) -> None:
        """Cleanup resources."""
        self.current_standings = []
        self.logger.info("Leaderboard plugin cleaned up")
