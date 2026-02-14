"""
Baseball Scoreboard Plugin for LEDMatrix

Displays live, recent, and upcoming baseball games across MLB, MiLB, and NCAA Baseball.
Shows real-time scores, game status, innings, and team logos.

Features:
- Multiple league support (MLB, MiLB, NCAA Baseball)
- Live game tracking with innings and time
- Recent game results
- Upcoming game schedules
- Favorite team prioritization
- Background data fetching

API Version: 1.0.0
"""

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from pathlib import Path

import pytz
import requests
from PIL import Image, ImageDraw, ImageFont

# Pillow compatibility: Image.Resampling.LANCZOS is available in Pillow >= 9.1
try:
    RESAMPLE_FILTER = Image.Resampling.LANCZOS
except AttributeError:
    RESAMPLE_FILTER = Image.LANCZOS

from src.plugin_system.base_plugin import BasePlugin, VegasDisplayMode

# Import baseball base classes from LEDMatrix
try:
    from src.base_classes.baseball import Baseball, BaseballLive
    from src.base_classes.sports import SportsRecent, SportsUpcoming
except ImportError:
    Baseball = None
    BaseballLive = None
    SportsRecent = None
    SportsUpcoming = None

# Import data manager for background fetching
try:
    from data_manager import BaseballDataManager
    DATA_MANAGER_AVAILABLE = True
except ImportError:
    BaseballDataManager = None
    DATA_MANAGER_AVAILABLE = False

# Import scroll display components
try:
    from scroll_display import ScrollDisplayManager
    SCROLL_AVAILABLE = True
except ImportError:
    ScrollDisplayManager = None
    SCROLL_AVAILABLE = False

# Import odds manager
try:
    from odds_manager import BaseballOddsManager
except ImportError:
    BaseballOddsManager = None

# Import logo manager for auto-download support
try:
    from logo_manager import BaseballLogoManager
except ImportError:
    BaseballLogoManager = None

# Import rankings manager
try:
    from rankings_manager import BaseballRankingsManager
except ImportError:
    BaseballRankingsManager = None

logger = logging.getLogger(__name__)


class BaseballScoreboardPlugin(BasePlugin):
    """
    Baseball scoreboard plugin for displaying games across multiple leagues.

    Supports MLB, MiLB, and NCAA Baseball with live, recent, and upcoming game modes.

    Configuration options:
        leagues: Enable/disable MLB, MiLB, NCAA Baseball
        display_modes: Enable live, recent, upcoming modes
        favorite_teams: Team abbreviations per league
        show_records: Display team records
        show_ranking: Display team rankings
        background_service: Data fetching configuration
    """

    # ESPN API endpoints for each league
    ESPN_API_URLS = {
        'mlb': 'https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard',
        'milb': 'https://site.api.espn.com/apis/site/v2/sports/baseball/minor-league-baseball/scoreboard',
        'ncaa_baseball': 'https://site.api.espn.com/apis/site/v2/sports/baseball/college-baseball/scoreboard'
    }

    def __init__(self, plugin_id: str, config: Dict[str, Any],
                 display_manager, cache_manager, plugin_manager):
        """Initialize the baseball scoreboard plugin."""
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)

        if Baseball is None:
            self.logger.error("Failed to import Baseball base classes. Plugin will not function.")
            self.initialized = False
            return

        # Configuration - flattened structure for plugin system compatibility
        self.leagues = {
            'mlb': {
                'enabled': config.get('mlb_enabled', True),
                'favorite_teams': config.get('mlb_favorite_teams', []),
                'display_modes': {
                    'live': config.get('mlb_display_modes_live', True),
                    'recent': config.get('mlb_display_modes_recent', True),
                    'upcoming': config.get('mlb_display_modes_upcoming', True)
                },
                'recent_games_to_show': config.get('mlb_recent_games_to_show', 5),
                'upcoming_games_to_show': config.get('mlb_upcoming_games_to_show', 1),
                'background_service': {
                    'enabled': config.get('mlb_background_service_enabled', True),
                    'max_workers': config.get('mlb_background_service_max_workers', 3),
                    'request_timeout': config.get('mlb_background_service_request_timeout', 30),
                    'max_retries': config.get('mlb_background_service_max_retries', 3),
                    'priority': config.get('mlb_background_service_priority', 2)
                }
            },
            'milb': {
                'enabled': config.get('milb_enabled', False),
                'live_priority': config.get('milb_live_priority', False),
                'live_game_duration': config.get('milb_live_game_duration', 30),
                'test_mode': config.get('milb_test_mode', False),
                'update_interval_seconds': config.get('milb_update_interval_seconds', 3600),
                'live_update_interval': config.get('milb_live_update_interval', 30),
                'recent_update_interval': config.get('milb_recent_update_interval', 3600),
                'upcoming_update_interval': config.get('milb_upcoming_update_interval', 3600),
                'recent_games_to_show': config.get('milb_recent_games_to_show', 1),
                'upcoming_games_to_show': config.get('milb_upcoming_games_to_show', 1),
                'favorite_teams': config.get('milb_favorite_teams', []),
                'display_modes': {
                    'live': config.get('milb_display_modes_live', True),
                    'recent': config.get('milb_display_modes_recent', True),
                    'upcoming': config.get('milb_display_modes_upcoming', True)
                },
                'logo_dir': config.get('milb_logo_dir', 'assets/sports/milb_logos'),
                'show_records': config.get('milb_show_records', True),
                'upcoming_fetch_days': config.get('milb_upcoming_fetch_days', 7),
                'background_service': {
                    'enabled': config.get('milb_background_service_enabled', True),
                    'max_workers': config.get('milb_background_service_max_workers', 3),
                    'request_timeout': config.get('milb_background_service_request_timeout', 30),
                    'max_retries': config.get('milb_background_service_max_retries', 3),
                    'priority': config.get('milb_background_service_priority', 2)
                }
            },
            'ncaa_baseball': {
                'enabled': config.get('ncaa_baseball_enabled', False),
                'live_priority': config.get('ncaa_baseball_live_priority', True),
                'live_game_duration': config.get('ncaa_baseball_live_game_duration', 30),
                'show_odds': config.get('ncaa_baseball_show_odds', True),
                'test_mode': config.get('ncaa_baseball_test_mode', False),
                'update_interval_seconds': config.get('ncaa_baseball_update_interval_seconds', 3600),
                'live_update_interval': config.get('ncaa_baseball_live_update_interval', 30),
                'recent_games_to_show': config.get('ncaa_baseball_recent_games_to_show', 1),
                'upcoming_games_to_show': config.get('ncaa_baseball_upcoming_games_to_show', 1),
                'show_favorite_teams_only': config.get('ncaa_baseball_show_favorite_teams_only', True),
                'favorite_teams': config.get('ncaa_baseball_favorite_teams', []),
                'display_modes': {
                    'live': config.get('ncaa_baseball_display_modes_live', True),
                    'recent': config.get('ncaa_baseball_display_modes_recent', True),
                    'upcoming': config.get('ncaa_baseball_display_modes_upcoming', True)
                },
                'logo_dir': config.get('ncaa_baseball_logo_dir', 'assets/sports/ncaa_logos'),
                'show_records': config.get('ncaa_baseball_show_records', True),
                'show_all_live': config.get('ncaa_baseball_show_all_live', False)
            }
        }

        # Global settings
        self.global_config = config
        self.display_duration = config.get('display_duration', 15)
        self.show_records = config.get('show_records', False)
        self.show_ranking = config.get('show_ranking', False)


        # State
        self.current_games = []
        self.current_league = None
        self.current_display_mode = None
        self.last_update = 0
        # Thread safety lock for shared game state
        self._games_lock = threading.RLock()

        # Initialize scroll display manager if available
        self._scroll_manager = None
        if SCROLL_AVAILABLE and ScrollDisplayManager:
            try:
                self._scroll_manager = ScrollDisplayManager(
                    self.display_manager,
                    self.config,
                    self.logger
                )
                self.logger.info("Baseball scroll display manager initialized")
            except Exception as e:
                self.logger.warning(f"Could not initialize scroll display manager: {e}")
        else:
            self.logger.info("Scroll display not available - scroll mode disabled")

        # Initialize odds manager
        self._odds_manager = None
        if BaseballOddsManager:
            try:
                self._odds_manager = BaseballOddsManager(cache_manager, logger=self.logger)
                self.logger.info("Baseball odds manager initialized")
            except Exception as e:
                self.logger.warning(f"Could not initialize odds manager: {e}")

        # Initialize logo manager for auto-download support
        self._logo_manager = None
        if BaseballLogoManager:
            try:
                self._logo_manager = BaseballLogoManager(display_manager, self.logger)
                self.logger.info("Baseball logo manager initialized")
            except Exception as e:
                self.logger.warning(f"Could not initialize logo manager: {e}")

        # Initialize rankings manager
        self._rankings_manager = None
        self._team_rankings_cache: Dict[str, int] = {}
        if BaseballRankingsManager:
            try:
                self._rankings_manager = BaseballRankingsManager(self.logger)
                self.logger.info("Baseball rankings manager initialized")
            except Exception as e:
                self.logger.warning(f"Could not initialize rankings manager: {e}")

        self.initialized = True

        # Initialize data manager for background fetching
        self.data_manager = None
        if DATA_MANAGER_AVAILABLE:
            try:
                self.data_manager = BaseballDataManager(cache_manager, self.logger)
                self.logger.info("Baseball data manager initialized with background service support")
            except Exception as e:
                self.logger.warning(f"Could not initialize data manager, using sync fetching: {e}")

        # Load fonts for rendering
        self.fonts = self._load_fonts()

        # Register fonts
        self._register_fonts()

        # Log enabled leagues and their settings
        enabled_leagues = []
        for league_key, league_config in self.leagues.items():
            if league_config.get('enabled', False):
                enabled_leagues.append(league_key)

        self.logger.info("Baseball scoreboard plugin initialized")
        self.logger.info(f"Enabled leagues: {enabled_leagues}")

    def _load_fonts(self):
        """Load fonts used by the scoreboard - matching original managers."""
        fonts = {}
        try:
            fonts['score'] = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 10)
            fonts['time'] = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 8)
            fonts['team'] = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 8)
            fonts['status'] = ImageFont.truetype("assets/fonts/4x6-font.ttf", 6)
            fonts['detail'] = ImageFont.truetype("assets/fonts/4x6-font.ttf", 6)
            fonts['rank'] = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 10)
            self.logger.info("Successfully loaded fonts")
        except IOError as e:
            self.logger.warning(f"Fonts not found, using default PIL font: {e}")
            fonts['score'] = ImageFont.load_default()
            fonts['time'] = ImageFont.load_default()
            fonts['team'] = ImageFont.load_default()
            fonts['status'] = ImageFont.load_default()
            fonts['detail'] = ImageFont.load_default()
            fonts['rank'] = ImageFont.load_default()
        return fonts

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

            # Status font (inning, time)
            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.status",
                family="four_by_six",
                size_px=6,
                color=(0, 255, 0)
            )

            # Detail font (records, rankings)
            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.detail",
                family="four_by_six",
                size_px=6,
                color=(200, 200, 200)
            )

            self.logger.info("Baseball scoreboard fonts registered")
        except Exception as e:
            self.logger.warning(f"Error registering fonts: {e}")

    def _get_layout_offset(self, element: str, axis: str, default: int = 0) -> int:
        """
        Get layout offset for a specific element and axis.

        Args:
            element: Element name (e.g., 'home_logo', 'away_logo', 'score', 'status')
            axis: 'x_offset' or 'y_offset'
            default: Default value if not configured (default: 0)

        Returns:
            Offset value from config or default (always returns int)
        """
        try:
            layout_config = self.config.get('customization', {}).get('layout', {})
            element_config = layout_config.get(element, {})
            offset_value = element_config.get(axis, default)

            # Ensure we return an integer (handle float/string from config)
            if isinstance(offset_value, (int, float)):
                return int(offset_value)
            elif isinstance(offset_value, str):
                try:
                    return int(float(offset_value))
                except ValueError:
                    self.logger.warning(f"Invalid offset value '{offset_value}' for {element}.{axis}, using default {default}")
                    return default
            else:
                return default
        except Exception as e:
            self.logger.debug(f"Error getting layout offset for {element}.{axis}: {e}")
            return default

    def update(self) -> None:
        """Update baseball game data for all enabled leagues."""
        if not self.initialized:
            return

        try:
            # Fetch data for each enabled league (outside lock)
            new_games = []
            for league_key, league_config in self.leagues.items():
                if league_config.get('enabled', False):
                    games = self._fetch_league_data(league_key, league_config)
                    if games:
                        # Add league info to each game
                        for game in games:
                            game['league_config'] = league_config
                        new_games.extend(games)

            # Fetch odds for each game if enabled
            if self._odds_manager:
                for game in new_games:
                    league_config = game.get('league_config', {})
                    league = game.get('league', 'mlb')
                    show_odds = league_config.get('show_odds', self.config.get('show_odds', False))
                    if show_odds:
                        self._odds_manager.fetch_odds(game, league_config, 'baseball', league)

            # Fetch rankings if enabled
            if self.show_ranking and self._rankings_manager:
                self._fetch_all_rankings()

            # Update shared state under lock (protected by lock for thread safety)
            with self._games_lock:
                self.current_games = new_games
                # Sort games - prioritize live games and favorites
                self._sort_games()
                self.last_update = time.time()

            self.logger.debug(f"Updated baseball data: {len(self.current_games)} games")

        except Exception as e:
            self.logger.error(f"Error updating baseball data: {e}")

    def _sort_games(self):
        """Sort games by priority and favorites."""
        def sort_key(game):
            # Priority 1: Live games
            live_score = 0 if game.get('is_live') else 1

            # Priority 2: Favorite teams
            favorite_score = 0 if self._is_favorite_game(game) else 1

            # Priority 3: Start time (earlier games first for upcoming, later for recent)
            start_time = game.get('start_time', '')

            return (live_score, favorite_score, start_time)

        self.current_games.sort(key=sort_key)

    def _fetch_all_rankings(self):
        """Fetch team rankings for all enabled leagues that support rankings.

        Uses atomic swap to avoid concurrent read/write issues with display threads.
        """
        if not self._rankings_manager:
            return

        # ESPN league identifiers for rankings API
        league_mappings = {
            'mlb': ('baseball', 'mlb'),
            'ncaa_baseball': ('baseball', 'college-baseball'),
        }

        new_cache: Dict[str, int] = {}
        for league_key, league_config in self.leagues.items():
            if not league_config.get('enabled', False):
                continue
            if league_key not in league_mappings:
                continue

            sport, league_id = league_mappings[league_key]
            rankings = self._rankings_manager.fetch_rankings(sport, league_id, league_key)
            if rankings:
                new_cache.update(rankings)

        # Atomic swap under lock so display threads see a consistent snapshot
        with self._games_lock:
            self._team_rankings_cache = new_cache

    def _get_rankings_cache(self) -> Dict[str, int]:
        """Get the combined team rankings cache."""
        return self._team_rankings_cache

    def _fetch_league_data(self, league_key: str, league_config: Dict) -> List[Dict]:
        """Fetch game data for a specific league.

        Uses data_manager with background_data_service when available,
        falls back to direct synchronous API calls otherwise.
        """
        if self.data_manager:
            return self._fetch_via_data_manager(league_key, league_config)
        return self._fetch_league_data_sync(league_key, league_config)

    def _fetch_via_data_manager(self, league_key: str, league_config: Dict) -> List[Dict]:
        """Fetch game data via data_manager (supports background_data_service)."""
        try:
            if league_key == 'milb':
                milb_games = self.data_manager.fetch_milb_games(league_config)
                if not milb_games:
                    return []
                return [self._convert_milb_game(g) for g in milb_games.values()]
            else:
                result = self.data_manager.fetch_season_data(league_key, league_config)
                if result and 'events' in result:
                    return self._process_api_response(result, league_key, league_config)
                return []
        except Exception as e:
            self.logger.exception(f"Error fetching {league_key} via data manager, falling back to sync")
            return self._fetch_league_data_sync(league_key, league_config)

    def _convert_milb_game(self, milb_data: Dict) -> Dict:
        """Convert data_manager MiLB format to flat game dict format."""
        status_state = milb_data.get('status_state', 'pre')
        home_abbr = milb_data.get('home_team', '')
        away_abbr = milb_data.get('away_team', '')
        logo_dir = self.leagues.get('milb', {}).get('logo_dir', 'assets/sports/milb_logos')
        return {
            'league': 'milb',
            'id': milb_data.get('id'),
            'home_abbr': home_abbr,
            'away_abbr': away_abbr,
            'home_id': milb_data.get('home_id', ''),
            'away_id': milb_data.get('away_id', ''),
            'home_score': milb_data.get('home_score', '0'),
            'away_score': milb_data.get('away_score', '0'),
            'home_record': milb_data.get('home_record', ''),
            'away_record': milb_data.get('away_record', ''),
            'home_logo_path': Path(logo_dir) / f"{home_abbr}.png",
            'away_logo_path': Path(logo_dir) / f"{away_abbr}.png",
            'home_logo_url': None,
            'away_logo_url': None,
            'status_state': status_state,
            'status_text': milb_data.get('detailed_state', ''),
            'is_live': status_state == 'in',
            'is_final': status_state == 'post',
            'is_upcoming': status_state == 'pre',
            'start_time': milb_data.get('start_time', ''),
            'venue': '',
            'inning': milb_data.get('inning', 1),
            'inning_half': milb_data.get('inning_half', 'top'),
            'balls': milb_data.get('balls', 0),
            'strikes': milb_data.get('strikes', 0),
            'outs': milb_data.get('outs', 0),
            'bases_occupied': milb_data.get('bases_occupied', [False, False, False]),
        }

    def _fetch_league_data_sync(self, league_key: str, league_config: Dict) -> List[Dict]:
        """Synchronous fallback for fetching game data when data_manager is unavailable."""
        cache_key = f"baseball_{league_key}_{datetime.now().strftime('%Y%m%d')}"
        try:
            update_interval = int(league_config.get('update_interval_seconds', 60))
        except (ValueError, TypeError):
            update_interval = 60

        # Check cache first (use league-specific interval)
        cached_data = self.cache_manager.get(cache_key)
        if cached_data and (time.time() - self.last_update) < update_interval:
            self.logger.debug(f"Using cached data for {league_key}")
            return cached_data

        # Fetch from API
        try:
            url = self.ESPN_API_URLS.get(league_key)
            if not url:
                self.logger.error(f"Unknown league key: {league_key}")
                return []

            self.logger.info(f"Fetching {league_key} data from ESPN API (sync)...")
            response = requests.get(url, timeout=league_config.get('background_service', {}).get('request_timeout', 30))
            response.raise_for_status()

            data = response.json()
            games = self._process_api_response(data, league_key, league_config)

            # Cache for league-specific interval
            self.cache_manager.set(cache_key, games, ttl=update_interval * 2)

            return games

        except requests.RequestException as e:
            self.logger.error(f"Error fetching {league_key} data: {e}")
            return []
        except Exception as e:
            self.logger.error(f"Error processing {league_key} data: {e}")
            return []

    def _process_api_response(self, data: Dict, league_key: str, league_config: Dict) -> List[Dict]:
        """Process ESPN API response into standardized game format."""
        games = []

        try:
            events = data.get('events', [])

            for event in events:
                try:
                    game = self._extract_game_info(event, league_key, league_config)
                    if game:
                        games.append(game)
                except Exception as e:
                    self.logger.error(f"Error extracting game info: {e}")
                    continue

        except Exception as e:
            self.logger.error(f"Error processing API response: {e}")

        return games

    def _extract_game_info(self, event: Dict, league_key: str, league_config: Dict) -> Optional[Dict]:
        """Extract game information from ESPN event into flat dict format with baseball fields."""
        try:
            competition = event.get('competitions', [{}])[0]
            status = competition.get('status', {})
            competitors = competition.get('competitors', [])
            situation = competition.get('situation')
            game_date_str = event.get('date', '')

            if len(competitors) < 2:
                return None

            # Find home and away teams
            home_team = next((c for c in competitors if c.get('homeAway') == 'home'), None)
            away_team = next((c for c in competitors if c.get('homeAway') == 'away'), None)

            if not home_team or not away_team:
                return None

            try:
                home_abbr = home_team['team']['abbreviation']
            except KeyError:
                home_abbr = home_team.get('team', {}).get('name', 'UNK')[:3]
            try:
                away_abbr = away_team['team']['abbreviation']
            except KeyError:
                away_abbr = away_team.get('team', {}).get('name', 'UNK')[:3]

            status_state = status.get('type', {}).get('state', 'unknown').lower()

            # Get records
            home_record = home_team.get('records', [{}])[0].get('summary', '') if home_team.get('records') else ''
            away_record = away_team.get('records', [{}])[0].get('summary', '') if away_team.get('records') else ''
            if home_record in {'0-0', '0-0-0'}:
                home_record = ''
            if away_record in {'0-0', '0-0-0'}:
                away_record = ''

            # Determine logo directory based on league
            if league_key == 'ncaa_baseball':
                logo_dir = 'assets/sports/ncaa_logos'
            elif league_key == 'milb':
                logo_dir = league_config.get('logo_dir', 'assets/sports/milb_logos')
            else:
                logo_dir = 'assets/sports/mlb_logos'

            game = {
                'league': league_key,
                'league_config': league_config,
                'id': event.get('id'),
                'home_abbr': home_abbr,
                'away_abbr': away_abbr,
                'home_id': home_team.get('id'),
                'away_id': away_team.get('id'),
                'home_score': home_team.get('score', '0'),
                'away_score': away_team.get('score', '0'),
                'home_record': home_record,
                'away_record': away_record,
                'home_logo_path': Path(logo_dir) / f"{home_abbr}.png",
                'away_logo_path': Path(logo_dir) / f"{away_abbr}.png",
                'home_logo_url': home_team.get('team', {}).get('logo'),
                'away_logo_url': away_team.get('team', {}).get('logo'),
                'status_state': status_state,
                'status_text': status.get('type', {}).get('shortDetail', ''),
                'is_live': status_state == 'in',
                'is_final': status_state == 'post',
                'is_upcoming': status_state == 'pre',
                'start_time': game_date_str,
                'venue': competition.get('venue', {}).get('fullName', ''),
            }

            # Extract baseball-specific details for live games
            if status_state == 'in':
                inning = status.get('period', 1)
                status_detail = status.get('type', {}).get('detail', '').lower()
                status_short = status.get('type', {}).get('shortDetail', '').lower()

                # Determine inning half from status text
                inning_half = 'top'
                if 'end' in status_detail or 'end' in status_short:
                    inning_half = 'end'
                elif 'mid' in status_detail or 'mid' in status_short:
                    inning_half = 'mid'
                elif 'bottom' in status_detail or 'bot' in status_detail or 'bottom' in status_short or 'bot' in status_short:
                    inning_half = 'bottom'
                elif 'top' in status_detail or 'top' in status_short:
                    inning_half = 'top'

                # Get count and bases from situation
                count = situation.get('count') if situation else None
                outs = situation.get('outs', 0) if situation else 0

                if count:
                    balls = count.get('balls', 0)
                    strikes = count.get('strikes', 0)
                elif situation:
                    # Try alternative locations for count data
                    if 'summary' in situation:
                        try:
                            balls, strikes = map(int, situation['summary'].split('-'))
                        except (ValueError, AttributeError):
                            balls, strikes = 0, 0
                    else:
                        balls = situation.get('balls', 0)
                        strikes = situation.get('strikes', 0)
                else:
                    balls, strikes = 0, 0

                bases_occupied = [
                    situation.get('onFirst', False) if situation else False,
                    situation.get('onSecond', False) if situation else False,
                    situation.get('onThird', False) if situation else False,
                ]

                game.update({
                    'inning': inning,
                    'inning_half': inning_half,
                    'balls': balls,
                    'strikes': strikes,
                    'outs': outs,
                    'bases_occupied': bases_occupied,
                })
            else:
                game.update({
                    'inning': 1,
                    'inning_half': 'top',
                    'balls': 0,
                    'strikes': 0,
                    'outs': 0,
                    'bases_occupied': [False, False, False],
                })

            # Get series summary if available
            series = competition.get('series')
            if series:
                game['series_summary'] = series.get('summary', '')

            return game

        except Exception as e:
            self.logger.error(f"Error extracting game info: {e}")
            return None

    def _is_favorite_game(self, game: Dict) -> bool:
        """Check if game involves a favorite team."""
        league_config = game.get('league_config', {})
        favorites = league_config.get('favorite_teams', [])

        if not favorites:
            return False

        return game.get('home_abbr', '') in favorites or game.get('away_abbr', '') in favorites

    def display(self, display_mode: str = None, force_clear: bool = False) -> bool:
        """
        Display baseball games.

        Args:
            display_mode: Which mode to display (baseball_live, baseball_recent, baseball_upcoming)
            force_clear: If True, clear display before rendering
        
        Returns:
            True if content was displayed, False if no games available
        """
        if not self.initialized:
            self._display_error("Baseball plugin not initialized")
            return False

        # Determine which display mode to use - prioritize live games if enabled
        if not display_mode:
            # Auto-select mode based on available games and priorities
            if self._has_live_games():
                display_mode = 'baseball_live'
            else:
                # Fall back to recent or upcoming
                display_mode = 'baseball_recent' if self._has_recent_games() else 'baseball_upcoming'

        self.current_display_mode = display_mode

        # Filter games by display mode
        filtered_games = self._filter_games_by_mode(display_mode)

        if not filtered_games:
            self._display_no_games(display_mode)
            return False

        # Display the first game (rotation handled by LEDMatrix)
        try:
            game = filtered_games[0]
            self._display_game(game, display_mode)
            return True
        except Exception as e:
            self.logger.error(f"Error displaying game: {e}", exc_info=True)
            return False

    def _filter_games_by_mode(self, mode: str) -> List[Dict]:
        """Filter games based on display mode and per-league settings."""
        filtered = []

        # Make a copy of games list under lock for thread safety
        with self._games_lock:
            games_copy = list(self.current_games)

        for game in games_copy:
            league_key = game.get('league')
            league_config = game.get('league_config', {})
            status_state = game.get('status_state', '')

            # Check if this mode is enabled for this league
            display_modes = league_config.get('display_modes', {})
            mode_enabled = display_modes.get(mode.replace('baseball_', ''), False)
            if not mode_enabled:
                continue

            show_favorites_only = league_config.get('show_favorite_teams_only', False)
            show_all_live = league_config.get('show_all_live', False)
            if show_favorites_only and not (mode == 'baseball_live' and show_all_live) and not self._is_favorite_game(game):
                continue

            # Filter by game state and per-league limits
            if mode == 'baseball_live' and status_state == 'in':
                filtered.append(game)

            elif mode == 'baseball_recent' and status_state == 'post':
                recent_limit = league_config.get('recent_games_to_show', 5)
                recent_count = len([g for g in filtered if g.get('league') == league_key and g.get('is_final')])
                if recent_count >= recent_limit:
                    continue
                filtered.append(game)

            elif mode == 'baseball_upcoming' and status_state == 'pre':
                upcoming_limit = league_config.get('upcoming_games_to_show', 10)
                upcoming_count = len([g for g in filtered if g.get('league') == league_key and g.get('is_upcoming')])
                if upcoming_count >= upcoming_limit:
                    continue
                filtered.append(game)

        return filtered

    def _has_live_games(self) -> bool:
        """Check if there are any live games available."""
        with self._games_lock:
            return any(game.get('is_live') for game in self.current_games)

    def _has_recent_games(self) -> bool:
        """Check if there are any recent games available."""
        with self._games_lock:
            return any(game.get('is_final') for game in self.current_games)

    def has_live_content(self) -> bool:
        """
        Override BasePlugin method to indicate when plugin has live content.
        This is used by display controller for live priority system.
        """
        return self._has_live_games()
    
    def get_live_modes(self) -> list:
        """
        Override BasePlugin method to specify which modes to show during live priority.
        Only show the live mode, not recent/upcoming.
        """
        return ['baseball_live']

    def _load_team_logo(self, team_abbrev: str, league: str, game: Dict = None) -> Optional[Image.Image]:
        """Load and resize team logo, with auto-download via logo manager if available."""
        try:
            if not team_abbrev:
                return None

            # Get logo directory from league configuration
            league_config = self.leagues.get(league, {})
            logo_dir = league_config.get('logo_dir', 'assets/sports/mlb_logos')

            # Convert relative path to absolute path by finding LEDMatrix project root
            if not os.path.isabs(logo_dir):
                current_dir = os.path.dirname(os.path.abspath(__file__))
                ledmatrix_root = None
                for parent in [current_dir, os.path.dirname(current_dir), os.path.dirname(os.path.dirname(current_dir))]:
                    if os.path.exists(os.path.join(parent, 'assets', 'sports')):
                        ledmatrix_root = parent
                        break

                if ledmatrix_root:
                    logo_dir = os.path.join(ledmatrix_root, logo_dir)
                else:
                    logo_dir = os.path.abspath(logo_dir)

            logo_path = Path(logo_dir) / f"{team_abbrev}.png"

            # Use logo manager if available (supports auto-download of missing logos)
            if self._logo_manager:
                team_id = ''
                logo_url = None
                if game:
                    side = 'home' if game.get('home_abbr') == team_abbrev else 'away'
                    team_id = game.get(f'{side}_id', '')
                    logo_url = game.get(f'{side}_logo_url')

                if league == 'milb':
                    logo = self._logo_manager.load_milb_logo(team_abbrev, Path(logo_dir))
                else:
                    sport_key = 'college-baseball' if league == 'ncaa_baseball' else 'baseball'
                    logo = self._logo_manager.load_logo(
                        team_id, team_abbrev, logo_path,
                        logo_url=logo_url, sport_key=sport_key
                    )
                if logo:
                    return logo

            # Fallback: inline logo loading (no auto-download)
            logo_extensions = ['.png', '.jpg', '.jpeg']
            found_path = None
            abbrev_variations = [team_abbrev.upper(), team_abbrev.lower(), team_abbrev]

            for abbrev in abbrev_variations:
                for ext in logo_extensions:
                    potential_path = os.path.join(logo_dir, f"{abbrev}{ext}")
                    if os.path.exists(potential_path):
                        found_path = potential_path
                        break
                if found_path:
                    break

            if not found_path:
                return None

            with Image.open(found_path) as src:
                logo = src.convert('RGBA')
            max_width = int(self.display_manager.matrix.width * 1.5)
            max_height = int(self.display_manager.matrix.height * 1.5)
            logo.thumbnail((max_width, max_height), RESAMPLE_FILTER)

            return logo

        except Exception as e:
            self.logger.debug(f"Could not load logo for {team_abbrev}: {e}")
            return None

    def _draw_text_with_outline(self, draw: ImageDraw.Draw, text: str, position: tuple, font, fill=(255, 255, 255), outline_color=(0, 0, 0)):
        """Draw text with a black outline for better readability."""
        try:
            x, y = position
            # Draw outline
            for dx, dy in [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]:
                draw.text((x + dx, y + dy), text, font=font, fill=outline_color)
            # Draw main text
            draw.text((x, y), text, font=font, fill=fill)
        except Exception as e:
            self.logger.error(f"Error drawing text with outline: {e}")

    def _display_game(self, game: Dict, mode: str):
        """Display a single baseball game, routing to the appropriate renderer."""
        try:
            if mode == 'baseball_live':
                self._display_live_game(game)
            elif mode == 'baseball_recent':
                self._display_recent_game(game)
            elif mode == 'baseball_upcoming':
                self._display_upcoming_game(game)
            else:
                self._display_recent_game(game)
        except Exception as e:
            self.logger.error(f"Error displaying game: {e}", exc_info=True)
            self._display_error("Display error")

    def _paste_logos(self, main_img: Image.Image, game: Dict, inward_offset: int = 10):
        """Load and paste team logos onto the image. Returns (home_logo, away_logo) or (None, None)."""
        league = game.get('league', '')
        home_logo = self._load_team_logo(game.get('home_abbr', ''), league, game)
        away_logo = self._load_team_logo(game.get('away_abbr', ''), league, game)

        if not home_logo or not away_logo:
            return None, None

        center_y = main_img.height // 2
        home_x = main_img.width - home_logo.width + inward_offset + self._get_layout_offset('home_logo', 'x_offset')
        home_y = center_y - (home_logo.height // 2) + self._get_layout_offset('home_logo', 'y_offset')
        main_img.paste(home_logo, (home_x, home_y), home_logo)

        away_x = -inward_offset + self._get_layout_offset('away_logo', 'x_offset')
        away_y = center_y - (away_logo.height // 2) + self._get_layout_offset('away_logo', 'y_offset')
        main_img.paste(away_logo, (away_x, away_y), away_logo)

        return home_logo, away_logo

    def _get_team_display_text(self, abbr: str, record: str, show_records: bool, show_ranking: bool) -> str:
        """Get display text for a team (ranking or record), matching football/basketball pattern."""
        if show_ranking:
            rank = self._team_rankings_cache.get(abbr, 0)
            if rank > 0:
                return f"#{rank}"
            # Fall through to records if unranked
            if not show_records:
                return ''
        if show_records:
            return record
        return ''

    def _draw_records(self, draw: ImageDraw.Draw, game: Dict, width: int, height: int):
        """Draw team records or rankings at bottom corners if enabled."""
        league_config = game.get('league_config', {})
        show_records = league_config.get('show_records', self.show_records)
        show_ranking = league_config.get('show_ranking', self.show_ranking)

        if not show_records and not show_ranking:
            return

        record_font = self.fonts['detail']
        record_bbox = draw.textbbox((0, 0), "0-0", font=record_font)
        record_height = record_bbox[3] - record_bbox[1]
        record_y = height - record_height

        # Away team (bottom left)
        away_text = self._get_team_display_text(
            game.get('away_abbr', ''), game.get('away_record', ''),
            show_records, show_ranking
        )
        if away_text:
            self._draw_text_with_outline(draw, away_text, (0, record_y), record_font)

        # Home team (bottom right)
        home_text = self._get_team_display_text(
            game.get('home_abbr', ''), game.get('home_record', ''),
            show_records, show_ranking
        )
        if home_text:
            home_bbox = draw.textbbox((0, 0), home_text, font=record_font)
            home_w = home_bbox[2] - home_bbox[0]
            self._draw_text_with_outline(draw, home_text, (width - home_w, record_y), record_font)

    def _fetch_and_render_odds(self, draw: ImageDraw.Draw, game: Dict, width: int, height: int):
        """Render pre-fetched odds for a game if enabled.

        Odds data is populated during update() cycle — this method only renders.
        """
        if not self._odds_manager:
            return

        league_config = game.get('league_config', {})
        show_odds = league_config.get('show_odds', self.config.get('show_odds', False))
        if not show_odds:
            return

        odds = game.get('odds')
        if odds:
            self._odds_manager.render_odds(draw, odds, width, height, self.fonts)

    def _display_live_game(self, game: Dict):
        """Display a live baseball game with full scorebug: bases, outs, count, inning."""
        matrix_width = self.display_manager.matrix.width
        matrix_height = self.display_manager.matrix.height

        main_img = Image.new('RGBA', (matrix_width, matrix_height), (0, 0, 0, 255))
        overlay = Image.new('RGBA', (matrix_width, matrix_height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # Logos
        home_logo, away_logo = self._paste_logos(main_img, game, inward_offset=10)
        if not home_logo or not away_logo:
            self._display_text_fallback(game)
            return

        # --- Inning indicator (top center) ---
        inning_half = game.get('inning_half', 'top')
        inning_num = game.get('inning', 1)
        if game.get('is_final'):
            inning_text = "FINAL"
        elif inning_half == 'end':
            inning_text = f"E{inning_num}"
        elif inning_half == 'mid':
            inning_text = f"M{inning_num}"
        else:
            symbol = "▲" if inning_half == 'top' else "▼"
            inning_text = f"{symbol}{inning_num}"

        inning_font = self.fonts['time']
        inning_bbox = draw.textbbox((0, 0), inning_text, font=inning_font)
        inning_width = inning_bbox[2] - inning_bbox[0]
        inning_x = (matrix_width - inning_width) // 2 + self._get_layout_offset('status', 'x_offset')
        inning_y = 1 + self._get_layout_offset('status', 'y_offset')
        self._draw_text_with_outline(draw, inning_text, (inning_x, inning_y), inning_font)

        # --- Bases diamond + Outs circles ---
        bases_occupied = game.get('bases_occupied', [False, False, False])
        outs = game.get('outs', 0)

        # Geometry constants (from v2.5)
        base_diamond_size = 7
        out_circle_diameter = 3
        out_vertical_spacing = 2
        spacing_between_bases_outs = 3
        base_vert_spacing = 1
        base_horiz_spacing = 1

        base_cluster_height = base_diamond_size + base_vert_spacing + base_diamond_size
        base_cluster_width = base_diamond_size + base_horiz_spacing + base_diamond_size
        out_cluster_height = 3 * out_circle_diameter + 2 * out_vertical_spacing

        overall_start_y = inning_bbox[3] + 1  # just below inning text

        # Center bases horizontally
        bases_origin_x = (matrix_width - base_cluster_width) // 2

        # Outs column position depends on inning half
        if inning_half == 'top':
            outs_column_x = bases_origin_x - spacing_between_bases_outs - out_circle_diameter
        else:
            outs_column_x = bases_origin_x + base_cluster_width + spacing_between_bases_outs

        outs_column_start_y = overall_start_y + (base_cluster_height // 2) - (out_cluster_height // 2)

        # Draw bases as diamond polygons
        base_color_filled = (255, 255, 255)
        base_color_outline = (255, 255, 255)
        h_d = base_diamond_size // 2

        # 2nd base (top center)
        c2x = bases_origin_x + base_cluster_width // 2
        c2y = overall_start_y + h_d
        poly2 = [(c2x, overall_start_y), (c2x + h_d, c2y), (c2x, c2y + h_d), (c2x - h_d, c2y)]
        if bases_occupied[1]:
            draw.polygon(poly2, fill=base_color_filled)
        else:
            draw.polygon(poly2, outline=base_color_outline)

        base_bottom_y = c2y + h_d

        # 3rd base (bottom left)
        c3x = bases_origin_x + h_d
        c3y = base_bottom_y + base_vert_spacing + h_d
        poly3 = [(c3x, base_bottom_y + base_vert_spacing), (c3x + h_d, c3y), (c3x, c3y + h_d), (c3x - h_d, c3y)]
        if bases_occupied[2]:
            draw.polygon(poly3, fill=base_color_filled)
        else:
            draw.polygon(poly3, outline=base_color_outline)

        # 1st base (bottom right)
        c1x = bases_origin_x + base_cluster_width - h_d
        c1y = base_bottom_y + base_vert_spacing + h_d
        poly1 = [(c1x, base_bottom_y + base_vert_spacing), (c1x + h_d, c1y), (c1x, c1y + h_d), (c1x - h_d, c1y)]
        if bases_occupied[0]:
            draw.polygon(poly1, fill=base_color_filled)
        else:
            draw.polygon(poly1, outline=base_color_outline)

        # Draw outs (3 vertical circles)
        circle_color_filled = (255, 255, 255)
        circle_color_empty = (100, 100, 100)

        for i in range(3):
            cx = outs_column_x
            cy = outs_column_start_y + i * (out_circle_diameter + out_vertical_spacing)
            coords = [cx, cy, cx + out_circle_diameter, cy + out_circle_diameter]
            if i < outs:
                draw.ellipse(coords, fill=circle_color_filled)
            else:
                draw.ellipse(coords, outline=circle_color_empty)

        # --- Balls-strikes count (below bases) ---
        balls = game.get('balls', 0)
        strikes = game.get('strikes', 0)
        count_text = f"{balls}-{strikes}"
        count_font = self.fonts['detail']
        count_width = draw.textlength(count_text, font=count_font)
        cluster_bottom_y = overall_start_y + base_cluster_height
        count_y = cluster_bottom_y + 2
        count_x = bases_origin_x + (base_cluster_width - count_width) // 2
        self._draw_text_with_outline(draw, count_text, (int(count_x), count_y), count_font)

        # --- Team:Score at bottom corners ---
        score_font = self.fonts['score']
        away_abbr = game.get('away_abbr', '')
        home_abbr = game.get('home_abbr', '')
        away_score_str = str(game.get('away_score', '0'))
        home_score_str = str(game.get('home_score', '0'))
        away_text = f"{away_abbr}:{away_score_str}"
        home_text = f"{home_abbr}:{home_score_str}"

        try:
            font_height = score_font.getbbox("A")[3] - score_font.getbbox("A")[1]
        except AttributeError:
            font_height = 8
        score_y = matrix_height - font_height - 2

        # Away (bottom left)
        self._draw_text_with_outline(draw, away_text, (2, score_y), score_font)

        # Home (bottom right)
        try:
            home_text_width = draw.textbbox((0, 0), home_text, font=score_font)[2]
        except AttributeError:
            home_text_width = len(home_text) * 8
        self._draw_text_with_outline(draw, home_text, (matrix_width - home_text_width - 2, score_y), score_font)

        # Odds
        self._fetch_and_render_odds(draw, game, matrix_width, matrix_height)

        # Composite and display
        final_img = Image.alpha_composite(main_img, overlay)
        self.display_manager.image = final_img.convert('RGB').copy()
        self.display_manager.update_display()

    def _display_recent_game(self, game: Dict):
        """Display a recent (final) baseball game."""
        matrix_width = self.display_manager.matrix.width
        matrix_height = self.display_manager.matrix.height

        main_img = Image.new('RGBA', (matrix_width, matrix_height), (0, 0, 0, 255))
        overlay = Image.new('RGBA', (matrix_width, matrix_height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # Logos (tighter fit for recent/upcoming)
        home_logo, away_logo = self._paste_logos(main_img, game, inward_offset=2)
        if not home_logo or not away_logo:
            self._display_text_fallback(game)
            return

        # "Final" text (top center)
        status_text = "Final"
        status_font = self.fonts['time']
        status_width = draw.textlength(status_text, font=status_font)
        status_x = (matrix_width - status_width) // 2 + self._get_layout_offset('status', 'x_offset')
        status_y = 1 + self._get_layout_offset('status', 'y_offset')
        self._draw_text_with_outline(draw, status_text, (status_x, status_y), status_font)

        # Score (centered)
        away_score = str(game.get('away_score', '0'))
        home_score = str(game.get('home_score', '0'))
        score_text = f"{away_score}-{home_score}"
        score_font = self.fonts['score']
        score_width = draw.textlength(score_text, font=score_font)
        score_x = (matrix_width - score_width) // 2 + self._get_layout_offset('score', 'x_offset')
        score_y = matrix_height - 14 + self._get_layout_offset('score', 'y_offset')
        self._draw_text_with_outline(draw, score_text, (score_x, score_y), score_font, fill=(255, 200, 0))

        # Records at bottom corners
        self._draw_records(draw, game, matrix_width, matrix_height)

        # Series summary (centered, if available)
        series_summary = game.get('series_summary', '')
        if series_summary:
            series_font = self.fonts['time']
            series_width = draw.textlength(series_summary, font=series_font)
            series_bbox = draw.textbbox((0, 0), series_summary, font=series_font)
            series_height = series_bbox[3] - series_bbox[1]
            series_x = (matrix_width - series_width) // 2
            series_y = (matrix_height - series_height) // 2
            self._draw_text_with_outline(draw, series_summary, (series_x, series_y), series_font)

        # Odds
        self._fetch_and_render_odds(draw, game, matrix_width, matrix_height)

        # Composite and display
        final_img = Image.alpha_composite(main_img, overlay)
        self.display_manager.image = final_img.convert('RGB').copy()
        self.display_manager.update_display()

    def _display_upcoming_game(self, game: Dict):
        """Display an upcoming baseball game."""
        matrix_width = self.display_manager.matrix.width
        matrix_height = self.display_manager.matrix.height

        main_img = Image.new('RGBA', (matrix_width, matrix_height), (0, 0, 0, 255))
        overlay = Image.new('RGBA', (matrix_width, matrix_height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # Logos (tighter fit)
        home_logo, away_logo = self._paste_logos(main_img, game, inward_offset=2)
        if not home_logo or not away_logo:
            self._display_text_fallback(game)
            return

        # "Next Game" (top center)
        status_font = self.fonts['status'] if matrix_width <= 128 else self.fonts['time']
        status_text = "Next Game"
        status_width = draw.textlength(status_text, font=status_font)
        status_x = (matrix_width - status_width) // 2 + self._get_layout_offset('status', 'x_offset')
        status_y = 1 + self._get_layout_offset('status', 'y_offset')
        self._draw_text_with_outline(draw, status_text, (status_x, status_y), status_font)

        # Parse start time for date and time display
        center_y = matrix_height // 2
        game_date = ''
        game_time = ''
        start_time = game.get('start_time', '')
        if start_time:
            try:
                dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                local_tz = pytz.timezone(self.config.get('timezone', 'US/Eastern'))
                dt_local = dt.astimezone(local_tz)
                game_date = dt_local.strftime('%b %d')
                game_time = dt_local.strftime('%-I:%M %p')
            except (ValueError, AttributeError):
                game_date = ''
                game_time = start_time[:10] if len(start_time) > 10 else start_time

        # Date (centered)
        time_font = self.fonts['time']
        if game_date:
            date_width = draw.textlength(game_date, font=time_font)
            date_x = (matrix_width - date_width) // 2
            date_y = center_y - 7
            self._draw_text_with_outline(draw, game_date, (date_x, date_y), time_font)

        # Time (centered, below date)
        if game_time:
            time_width = draw.textlength(game_time, font=time_font)
            time_x = (matrix_width - time_width) // 2
            time_y = center_y + 2
            self._draw_text_with_outline(draw, game_time, (time_x, time_y), time_font)

        # Records at bottom corners
        self._draw_records(draw, game, matrix_width, matrix_height)

        # Odds
        self._fetch_and_render_odds(draw, game, matrix_width, matrix_height)

        # Composite and display
        final_img = Image.alpha_composite(main_img, overlay)
        self.display_manager.image = final_img.convert('RGB').copy()
        self.display_manager.update_display()

    def _display_text_fallback(self, game: Dict):
        """Text-only fallback when logos fail to load."""
        matrix_width = self.display_manager.matrix.width
        matrix_height = self.display_manager.matrix.height
        img = Image.new('RGB', (matrix_width, matrix_height), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        away_abbr = game.get('away_abbr', 'AWAY')
        home_abbr = game.get('home_abbr', 'HOME')

        draw.text((5, 5), f"{away_abbr} @ {home_abbr}", fill=(255, 255, 255))
        draw.text((5, 15), f"{game.get('away_score', 0)} - {game.get('home_score', 0)}", fill=(255, 200, 0))
        draw.text((5, 25), game.get('status_text', ''), fill=(0, 255, 0))

        self.display_manager.image = img.copy()
        self.display_manager.update_display()

    def _display_no_games(self, mode: str):
        """Display message when no games are available."""
        img = Image.new('RGB', (self.display_manager.matrix.width,
                               self.display_manager.matrix.height),
                       (0, 0, 0))
        draw = ImageDraw.Draw(img)

        message = {
            'baseball_live': "No Live Games",
            'baseball_recent': "No Recent Games",
            'baseball_upcoming': "No Upcoming Games"
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

        # Access current_games under lock for thread safety
        with self._games_lock:
            total_games = len(self.current_games)
            live_games = len([g for g in self.current_games if g.get('is_live')])
            recent_games = len([g for g in self.current_games if g.get('is_final')])
            upcoming_games = len([g for g in self.current_games if g.get('is_upcoming')])

        info.update({
            'total_games': total_games,
            'enabled_leagues': [k for k, v in self.leagues.items() if v.get('enabled', False)],
            'current_mode': self.current_display_mode,
            'last_update': self.last_update,
            'display_duration': self.display_duration,
            'show_records': self.show_records,
            'show_ranking': self.show_ranking,
            'live_games': live_games,
            'recent_games': recent_games,
            'upcoming_games': upcoming_games,
            'leagues_config': leagues_config,
            'global_config': self.global_config
        })
        return info

    # -------------------------------------------------------------------------
    # Scroll mode helper methods
    # -------------------------------------------------------------------------
    def _should_use_scroll_mode(self) -> bool:
        """
        Check if scroll mode should be used.

        Returns:
            True if scroll mode should be used, False otherwise
        """
        # Check if scroll manager is available
        if not self._scroll_manager:
            return False

        # Scroll mode is always preferred if available
        return True

    def _collect_games_for_scroll(self) -> tuple:
        """
        Collect all games for scroll mode from enabled leagues.

        Collects live, recent, and upcoming games organized by league.
        Within each league, games are sorted: live first, then recent, then upcoming.

        Returns:
            Tuple of (games_list, leagues_list)
        """
        # Make a copy of games list under lock for thread safety
        with self._games_lock:
            games_copy = list(self.current_games)

        # Group games by league first
        games_by_league = {}

        for game in games_copy:
            league = game.get('league', 'mlb')

            # Check if league is enabled
            if not self.leagues.get(league, {}).get('enabled', False):
                continue

            # Determine game type from state
            if game.get('is_live'):
                game_type = 'live'
            elif game.get('is_final'):
                game_type = 'recent'
            elif game.get('is_upcoming'):
                game_type = 'upcoming'
            else:
                continue

            # Check if this game type is enabled for this league
            display_modes = self.leagues.get(league, {}).get('display_modes', {})
            if not display_modes.get(game_type, False):
                continue

            # Add to league's games
            if league not in games_by_league:
                games_by_league[league] = []
            games_by_league[league].append(game)

        # Flatten games list, keeping leagues together
        all_games = []
        leagues = list(games_by_league.keys())

        for league in leagues:
            # Sort games within league: live first, then recent, then upcoming
            league_games = games_by_league[league]
            league_games.sort(key=lambda g: (
                0 if g.get('is_live') else 1 if g.get('is_final') else 2
            ))

            all_games.extend(league_games)

        return all_games, leagues

    # -------------------------------------------------------------------------
    # Vegas scroll mode support
    # -------------------------------------------------------------------------
    def get_vegas_content(self) -> Optional[Any]:
        """
        Get content for Vegas-style continuous scroll mode.

        Returns None to let PluginAdapter auto-detect scroll_helper.cached_image.
        Triggers scroll content generation if cache is empty to ensure Vegas
        has content to display.

        Returns:
            None - PluginAdapter will extract scroll_helper.cached_image automatically
        """
        # Ensure scroll content is generated for Vegas mode
        if hasattr(self, '_scroll_manager') and self._scroll_manager:
            # Check if any scroll display has content using public method
            if not self._scroll_manager.has_cached_content():
                self.logger.info("[Baseball Vegas] Triggering scroll content generation")
                self._ensure_scroll_content_for_vegas()

        # Return None - PluginAdapter will auto-detect scroll_helper.cached_image
        return None

    def get_vegas_content_type(self) -> str:
        """
        Indicate the type of content this plugin provides for Vegas scroll.

        Returns:
            'multi' - Plugin has multiple scrollable items (games)
        """
        return 'multi'

    def get_vegas_display_mode(self) -> 'VegasDisplayMode':
        """
        Get the display mode for Vegas scroll integration.

        Returns:
            VegasDisplayMode.SCROLL - Content scrolls continuously
        """
        if VegasDisplayMode:
            # Check for config override
            config_mode = self.config.get("vegas_mode")
            if config_mode:
                try:
                    return VegasDisplayMode(config_mode)
                except ValueError:
                    self.logger.warning(
                        f"Invalid vegas_mode '{config_mode}' in config, using SCROLL"
                    )
            return VegasDisplayMode.SCROLL
        # Fallback if VegasDisplayMode not available
        return "scroll"

    def _ensure_scroll_content_for_vegas(self) -> None:
        """
        Ensure scroll content is generated for Vegas mode.

        This method is called by get_vegas_content() when the scroll cache is empty.
        It collects all game types (live, recent, upcoming) organized by league.
        """
        if not hasattr(self, '_scroll_manager') or not self._scroll_manager:
            self.logger.debug("[Baseball Vegas] No scroll manager available")
            return

        # Collect all games (live, recent, upcoming) organized by league
        games, leagues = self._collect_games_for_scroll()

        if not games:
            self.logger.debug("[Baseball Vegas] No games available")
            return

        # Count games by type for logging
        game_type_counts = {'live': 0, 'recent': 0, 'upcoming': 0}
        for game in games:
            if game.get('is_live'):
                game_type_counts['live'] += 1
            elif game.get('is_final'):
                game_type_counts['recent'] += 1
            elif game.get('is_upcoming'):
                game_type_counts['upcoming'] += 1

        # Prepare scroll content with mixed game types
        # Note: Using 'mixed' as game_type indicator for scroll config
        rankings = self._get_rankings_cache() if self.show_ranking else None
        success = self._scroll_manager.prepare_and_display(
            games, 'mixed', leagues, rankings
        )

        if success:
            type_summary = ', '.join(
                f"{count} {gtype}" for gtype, count in game_type_counts.items() if count > 0
            )
            self.logger.info(
                f"[Baseball Vegas] Successfully generated scroll content: "
                f"{len(games)} games ({type_summary}) from {', '.join(leagues)}"
            )
        else:
            self.logger.warning("[Baseball Vegas] Failed to generate scroll content")


    def cleanup(self) -> None:
        """Cleanup resources."""
        with self._games_lock:
            self.current_games = []
        if hasattr(self, 'data_manager') and self.data_manager:
            # Background service is a global singleton, no explicit shutdown needed
            self.data_manager = None
        self.logger.info("Baseball scoreboard plugin cleaned up")
