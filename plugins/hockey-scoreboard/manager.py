"""
Hockey Scoreboard Plugin for LEDMatrix

Displays live, recent, and upcoming hockey games across NHL, NCAA Men's, and NCAA Women's hockey.
Shows real-time scores, game status, powerplay situations, and team logos.

Features:
- Multiple league support (NHL, NCAA M/W)
- Live game tracking with periods and time
- Recent game results
- Upcoming game schedules
- Favorite team prioritization
- Powerplay and penalty indicators
- Shots on goal statistics
- Background data fetching

API Version: 1.0.0
"""

import logging
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from pathlib import Path

import pytz
import requests
from PIL import Image, ImageDraw

from src.plugin_system.base_plugin import BasePlugin

# Import hockey base classes from LEDMatrix
try:
    from src.base_classes.hockey import Hockey, HockeyLive
    from src.base_classes.sports import SportsRecent, SportsUpcoming
except ImportError:
    Hockey = None
    HockeyLive = None
    SportsRecent = None
    SportsUpcoming = None

logger = logging.getLogger(__name__)


class HockeyScoreboardPlugin(BasePlugin):
    """
    Hockey scoreboard plugin for displaying games across multiple leagues.
    
    Supports NHL, NCAA Men's, and NCAA Women's hockey with live, recent,
    and upcoming game modes.
    
    Configuration options:
        leagues: Enable/disable NHL, NCAA M, NCAA W
        display_modes: Enable live, recent, upcoming modes
        favorite_teams: Team abbreviations per league
        show_shots_on_goal: Display SOG statistics
        show_powerplay: Highlight powerplay situations
        background_service: Data fetching configuration
    """
    
    # ESPN API endpoints for each league
    ESPN_API_URLS = {
        'nhl': 'https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard',
        'ncaa_mens': 'https://site.api.espn.com/apis/site/v2/sports/hockey/mens-college-hockey/scoreboard',
        'ncaa_womens': 'https://site.api.espn.com/apis/site/v2/sports/hockey/womens-college-hockey/scoreboard'
    }
    
    def __init__(self, plugin_id: str, config: Dict[str, Any],
                 display_manager, cache_manager, plugin_manager):
        """Initialize the hockey scoreboard plugin."""
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)
        
        if Hockey is None:
            self.logger.error("Failed to import Hockey base classes. Plugin will not function.")
            self.initialized = False
            return
        
        # Configuration
        self.leagues = config.get('leagues', {
            'nhl': True,
            'ncaa_mens': False,
            'ncaa_womens': False
        })
        self.display_modes_config = config.get('display_modes', {
            'hockey_live': True,
            'hockey_recent': True,
            'hockey_upcoming': True
        })
        self.favorite_teams = config.get('favorite_teams', {})
        self.prioritize_favorites = config.get('prioritize_favorites', True)
        self.show_shots_on_goal = config.get('show_shots_on_goal', False)
        self.show_powerplay = config.get('show_powerplay', True)
        self.recent_games_hours = config.get('recent_games_hours', 24)
        self.upcoming_games_hours = config.get('upcoming_games_hours', 72)
        
        # Background service configuration
        self.background_config = config.get('background_service', {
            'enabled': True,
            'request_timeout': 30,
            'max_retries': 3,
            'priority': 2
        })
        
        # State
        self.current_games = []
        self.current_league = None
        self.current_display_mode = None
        self.last_update = 0
        self.initialized = True
        
        # Register fonts
        self._register_fonts()
        
        self.logger.info(f"Hockey scoreboard plugin initialized")
        self.logger.info(f"Enabled leagues: {[k for k, v in self.leagues.items() if v]}")
        self.logger.info(f"Display modes: {[k for k, v in self.display_modes_config.items() if v]}")
    
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
            
            # Score font
            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.score",
                family="press_start",
                size_px=12,
                color=(255, 200, 0)
            )
            
            # Status font (period, time)
            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.status",
                family="four_by_six",
                size_px=6,
                color=(0, 255, 0)
            )
            
            # Info font (shots, powerplay)
            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.info",
                family="four_by_six",
                size_px=6,
                color=(200, 200, 200)
            )
            
            self.logger.info("Hockey scoreboard fonts registered")
        except Exception as e:
            self.logger.warning(f"Error registering fonts: {e}")
    
    def update(self) -> None:
        """Update hockey game data for all enabled leagues."""
        if not self.initialized:
            return
        
        try:
            self.current_games = []
            
            # Fetch data for each enabled league
            for league_key, enabled in self.leagues.items():
                if enabled:
                    games = self._fetch_league_data(league_key)
                    if games:
                        self.current_games.extend(games)
            
            # Sort games - prioritize favorites if enabled
            if self.prioritize_favorites and self.favorite_teams:
                self.current_games.sort(
                    key=lambda g: (
                        0 if self._is_favorite_game(g) else 1,
                        g.get('start_time', '')
                    )
                )
            
            self.last_update = time.time()
            self.logger.debug(f"Updated hockey data: {len(self.current_games)} games")
            
        except Exception as e:
            self.logger.error(f"Error updating hockey data: {e}")
    
    def _fetch_league_data(self, league_key: str) -> List[Dict]:
        """Fetch game data for a specific league."""
        cache_key = f"hockey_{league_key}_{datetime.now().strftime('%Y%m%d')}"
        
        # Check cache first
        cached_data = self.cache_manager.get(cache_key)
        if cached_data:
            self.logger.debug(f"Using cached data for {league_key}")
            return cached_data
        
        # Fetch from API
        try:
            url = self.ESPN_API_URLS.get(league_key)
            if not url:
                self.logger.error(f"Unknown league key: {league_key}")
                return []
            
            self.logger.info(f"Fetching {league_key} data from ESPN API...")
            response = requests.get(url, timeout=self.background_config.get('request_timeout', 30))
            response.raise_for_status()
            
            data = response.json()
            games = self._process_api_response(data, league_key)
            
            # Cache for 5 minutes
            self.cache_manager.set(cache_key, games, ttl=300)
            
            return games
            
        except requests.RequestException as e:
            self.logger.error(f"Error fetching {league_key} data: {e}")
            return []
        except Exception as e:
            self.logger.error(f"Error processing {league_key} data: {e}")
            return []
    
    def _process_api_response(self, data: Dict, league_key: str) -> List[Dict]:
        """Process ESPN API response into standardized game format."""
        games = []
        
        try:
            events = data.get('events', [])
            
            for event in events:
                try:
                    game = self._extract_game_info(event, league_key)
                    if game:
                        games.append(game)
                except Exception as e:
                    self.logger.error(f"Error extracting game info: {e}")
                    continue
            
        except Exception as e:
            self.logger.error(f"Error processing API response: {e}")
        
        return games
    
    def _extract_game_info(self, event: Dict, league_key: str) -> Optional[Dict]:
        """Extract game information from ESPN event."""
        try:
            competition = event.get('competitions', [{}])[0]
            status = competition.get('status', {})
            competitors = competition.get('competitors', [])
            
            if len(competitors) < 2:
                return None
            
            # Find home and away teams
            home_team = next((c for c in competitors if c.get('homeAway') == 'home'), None)
            away_team = next((c for c in competitors if c.get('homeAway') == 'away'), None)
            
            if not home_team or not away_team:
                return None
            
            # Extract game details
            game = {
                'league': league_key,
                'game_id': event.get('id'),
                'home_team': {
                    'name': home_team.get('team', {}).get('displayName', 'Unknown'),
                    'abbrev': home_team.get('team', {}).get('abbreviation', 'UNK'),
                    'score': int(home_team.get('score', 0)),
                    'logo': home_team.get('team', {}).get('logo')
                },
                'away_team': {
                    'name': away_team.get('team', {}).get('displayName', 'Unknown'),
                    'abbrev': away_team.get('team', {}).get('abbreviation', 'UNK'),
                    'score': int(away_team.get('score', 0)),
                    'logo': away_team.get('team', {}).get('logo')
                },
                'status': {
                    'state': status.get('type', {}).get('state', 'unknown'),
                    'detail': status.get('type', {}).get('detail', ''),
                    'short_detail': status.get('type', {}).get('shortDetail', ''),
                    'period': status.get('period', 0),
                    'display_clock': status.get('displayClock', '')
                },
                'start_time': event.get('date', ''),
                'venue': competition.get('venue', {}).get('fullName', 'Unknown Venue')
            }
            
            # Add powerplay info if available
            situation = competition.get('situation', {})
            if situation:
                game['powerplay'] = situation.get('isPowerPlay', False)
                game['penalties'] = situation.get('penalties', '')
            
            # Add shots on goal if available
            if self.show_shots_on_goal:
                home_stats = home_team.get('statistics', [])
                away_stats = away_team.get('statistics', [])
                
                game['home_team']['shots'] = next(
                    (int(s.get('displayValue', 0)) for s in home_stats if s.get('name') == 'shots'),
                    0
                )
                game['away_team']['shots'] = next(
                    (int(s.get('displayValue', 0)) for s in away_stats if s.get('name') == 'shots'),
                    0
                )
            
            return game
            
        except Exception as e:
            self.logger.error(f"Error extracting game info: {e}")
            return None
    
    def _is_favorite_game(self, game: Dict) -> bool:
        """Check if game involves a favorite team."""
        league = game.get('league')
        favorites = self.favorite_teams.get(league, [])
        
        if not favorites:
            return False
        
        home_abbrev = game.get('home_team', {}).get('abbrev')
        away_abbrev = game.get('away_team', {}).get('abbrev')
        
        return home_abbrev in favorites or away_abbrev in favorites
    
    def display(self, display_mode: str = None, force_clear: bool = False) -> None:
        """
        Display hockey games.
        
        Args:
            display_mode: Which mode to display (hockey_live, hockey_recent, hockey_upcoming)
            force_clear: If True, clear display before rendering
        """
        if not self.initialized:
            self._display_error("Hockey plugin not initialized")
            return
        
        # Determine which display mode to use
        mode = display_mode or self.current_display_mode or 'hockey_live'
        self.current_display_mode = mode
        
        # Filter games by display mode
        filtered_games = self._filter_games_by_mode(mode)
        
        if not filtered_games:
            self._display_no_games(mode)
            return
        
        # Display the first game (rotation handled by LEDMatrix)
        game = filtered_games[0]
        self._display_game(game, mode)
    
    def _filter_games_by_mode(self, mode: str) -> List[Dict]:
        """Filter games based on display mode."""
        now = datetime.now(timezone.utc)
        filtered = []
        
        for game in self.current_games:
            state = game.get('status', {}).get('state')
            
            if mode == 'hockey_live' and state == 'in':
                filtered.append(game)
            elif mode == 'hockey_recent' and state == 'post':
                # Check if within recent_games_hours
                game_time = datetime.fromisoformat(game.get('start_time', '').replace('Z', '+00:00'))
                hours_ago = (now - game_time).total_seconds() / 3600
                if hours_ago <= self.recent_games_hours:
                    filtered.append(game)
            elif mode == 'hockey_upcoming' and state == 'pre':
                # Check if within upcoming_games_hours
                game_time = datetime.fromisoformat(game.get('start_time', '').replace('Z', '+00:00'))
                hours_ahead = (game_time - now).total_seconds() / 3600
                if hours_ahead <= self.upcoming_games_hours:
                    filtered.append(game)
        
        return filtered
    
    def _display_game(self, game: Dict, mode: str):
        """Display a single game."""
        try:
            matrix_width = self.display_manager.matrix.width
            matrix_height = self.display_manager.matrix.height
            
            # Create image
            img = Image.new('RGB', (matrix_width, matrix_height), (0, 0, 0))
            draw = ImageDraw.Draw(img)
            
            # Get team info
            home_team = game.get('home_team', {})
            away_team = game.get('away_team', {})
            status = game.get('status', {})
            
            # Display team names/abbreviations
            home_abbrev = home_team.get('abbrev', 'HOME')
            away_abbrev = away_team.get('abbrev', 'AWAY')
            
            # TODO: Add team logos if available
            # TODO: Use font manager for text rendering
            # TODO: Add scores, period, time display
            # TODO: Add powerplay indicator
            # TODO: Add shots on goal if enabled
            
            # For now, simple text display (placeholder)
            draw.text((5, 5), f"{away_abbrev} @ {home_abbrev}", fill=(255, 255, 255))
            draw.text((5, 15), f"{away_team.get('score', 0)} - {home_team.get('score', 0)}", fill=(255, 200, 0))
            draw.text((5, 25), status.get('short_detail', ''), fill=(0, 255, 0))
            
            self.display_manager.image = img.copy()
            self.display_manager.update_display()
            
        except Exception as e:
            self.logger.error(f"Error displaying game: {e}")
            self._display_error("Display error")
    
    def _display_no_games(self, mode: str):
        """Display message when no games are available."""
        img = Image.new('RGB', (self.display_manager.matrix.width,
                               self.display_manager.matrix.height),
                       (0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        message = {
            'hockey_live': "No Live Games",
            'hockey_recent': "No Recent Games",
            'hockey_upcoming': "No Upcoming Games"
        }.get(mode, "No Games")
        
        draw.text((5, 12), message, fill=(150, 150, 150))
        
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
        return self.config.get('display_duration', 15.0)
    
    def get_info(self) -> Dict[str, Any]:
        """Return plugin info for web UI."""
        info = super().get_info()
        info.update({
            'leagues': self.leagues,
            'total_games': len(self.current_games),
            'last_update': self.last_update,
            'enabled_modes': [k for k, v in self.display_modes_config.items() if v]
        })
        return info
    
    def cleanup(self) -> None:
        """Cleanup resources."""
        self.current_games = []
        self.logger.info("Hockey scoreboard plugin cleaned up")

