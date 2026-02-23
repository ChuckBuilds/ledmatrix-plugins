"""
Odds Ticker Plugin for LEDMatrix

Displays scrolling odds and betting lines for upcoming games across multiple sports leagues.
Shows point spreads, money lines, and over/under totals with team information.

This plugin perfectly mirrors the original odds_ticker_manager.py functionality
with all the fine-tuned drawing, layout, logic, filtering, data, fonts, colors, and logos.

Features:
- Multi-sport odds display (NFL, NBA, MLB, NCAA Football, NCAA Basketball, NHL, MiLB, NCAA Baseball, NCAA Basketball)
- Scrolling ticker format with exact original layout
- Favorite team prioritization
- Broadcast channel logos with exact mapping
- Configurable scroll speed and display duration
- Background data fetching
- Live game support with sport-specific formatting
- Dynamic duration calculation
- Team rankings for NCAA football
- Base indicators for baseball
- All original fonts, colors, and spacing

API Version: 1.1.0
"""

import time
import logging
import requests
import json
import threading
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional
import os
from PIL import Image, ImageDraw, ImageFont
import pytz
from pathlib import Path
import numpy as np

# Import will be handled by the plugin system
try:
    from src.plugin_system.base_plugin import BasePlugin
except ImportError:
    # Fallback for when running outside of LEDMatrix
    class BasePlugin:
        def __init__(self, plugin_id, config, display_manager, cache_manager, plugin_manager):
            self.plugin_id = plugin_id
            self.config = config
            self.display_manager = display_manager
            self.cache_manager = cache_manager
            self.plugin_manager = plugin_manager

# Import the API counter function from web interface
try:
    from web_interface_v2 import increment_api_counter
except ImportError:
    # Fallback if web interface is not available
    def increment_api_counter(kind: str, count: int = 1):
        pass

# Import BaseOddsManager from LEDMatrix core
try:
    from src.base_odds_manager import BaseOddsManager
except ImportError:
    # Fallback - create a minimal BaseOddsManager
    class BaseOddsManager:
        def __init__(self, cache_manager, config_manager=None):
            self.cache_manager = cache_manager
            self.config_manager = config_manager
            self.logger = logging.getLogger(__name__)
            self.base_url = "https://sports.core.api.espn.com/v2/sports"
            self.base_odds_config = {}
            self.update_interval = 3600
            self.request_timeout = 30
            self.cache_ttl = 1800
        
        def get_odds(self, sport, league, event_id, update_interval_seconds=None, is_live=False):
            return None

# Import background service and dynamic resolver
try:
    from src.background_data_service import get_background_service
    from src.dynamic_team_resolver import DynamicTeamResolver
    from src.logo_downloader import download_missing_logo
    from src.common.scroll_helper import ScrollHelper
except ImportError:
    # Fallback implementations
    def get_background_service(cache_manager, max_workers=1):
        return None
    
    class DynamicTeamResolver:
        def resolve_teams(self, teams, league):
            return teams
    
    def download_missing_logo(league, team_id, team_abbr, logo_path, logo_url):
        return False
    
    class ScrollHelper:
        pass  # Will be handled by proper import

# Get logger
logger = logging.getLogger(__name__)


class OddsTickerPlugin(BasePlugin, BaseOddsManager):
    """Manager for displaying scrolling odds ticker for multiple sports leagues."""
    
    BROADCAST_LOGO_MAP = {
        "ACC Network": "accn",
        "ACCN": "accn",
        "ABC": "abc",
        "BTN": "btn",
        "CBS": "cbs",
        "CBSSN": "cbssn",
        "CBS Sports Network": "cbssn",
        "ESPN": "espn",
        "ESPN2": "espn2",
        "ESPN3": "espn3",
        "ESPNU": "espnu",
        "ESPNEWS": "espn",
        "ESPN+": "espn",
        "ESPN Plus": "espn",
        "FOX": "fox",
        "FS1": "fs1",
        "FS2": "fs2",
        "MLBN": "mlbn",
        "MLB Network": "mlbn",
        "MLB.TV": "mlbn",
        "NBC": "nbc",
        "NFLN": "nfln",
        "NFL Network": "nfln",
        "PAC12": "pac12n",
        "Pac-12 Network": "pac12n",
        "SECN": "espn-sec-us",
        "TBS": "tbs",
        "TNT": "tnt",
        "truTV": "tru",
        "Peacock": "nbc",
        "Paramount+": "cbs",
        "Hulu": "espn",
        "Disney+": "espn",
        "Apple TV+": "nbc",
        # Regional sports networks
        "MASN": "cbs",
        "MASN2": "cbs",
        "MAS+": "cbs",
        "SportsNet": "nbc",
        "FanDuel SN": "fox",
        "FanDuel SN DET": "fox",
        "FanDuel SN FL": "fox",
        "SportsNet PIT": "nbc",
        "Padres.TV": "espn",
        "CLEGuardians.TV": "espn"
    }
    
    def __init__(self, plugin_id: str, config: Dict[str, Any],
                 display_manager, cache_manager, plugin_manager):
        """Initialize the odds ticker plugin with exact original functionality."""
        # Initialize BasePlugin first
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)
        
        # Initialize BaseOddsManager with cache_manager only (no config_manager available)
        BaseOddsManager.__init__(self, cache_manager)
        
        # Resolve project root path (plugin_dir -> plugins -> project_root)
        self.project_root = Path(__file__).resolve().parent.parent.parent
        
        # Check required dependencies
        if get_background_service is None or DynamicTeamResolver is None:
            self.logger.error("Failed to import required services. Plugin will not function.")
            self.initialized = False
            return

        # Configuration - exactly like original
        # The config parameter already contains the odds-ticker configuration directly
        self.odds_ticker_config = config
        self.is_enabled = self.odds_ticker_config.get('enabled', False)

        # Debug logging
        self.logger.info(f"Full config received: {config}")
        self.logger.info(f"Odds ticker configuration: {self.odds_ticker_config}")
        self.logger.info(f"Odds ticker enabled: {self.is_enabled}")

        # Get nested config sections (support both old flat and new nested structure)
        display_options = self.odds_ticker_config.get('display_options', {})
        data_settings = self.odds_ticker_config.get('data_settings', {})
        filtering = self.odds_ticker_config.get('filtering', {})
        leagues_config = self.odds_ticker_config.get('leagues', {})

        # Use instance method for config value retrieval
        def get_config(section, key, default, old_key=None):
            return self._get_config_value(section, key, default, self.odds_ticker_config, old_key)

        # Filtering settings
        self.show_favorite_teams_only = get_config(filtering, 'show_favorite_teams_only', False)
        self.games_per_favorite_team = get_config(filtering, 'games_per_favorite_team', 1)
        self.max_games_per_league = get_config(filtering, 'max_games_per_league', 5)
        self.show_odds_only = get_config(filtering, 'show_odds_only', False)
        self.sort_order = get_config(filtering, 'sort_order', 'soonest')

        # Data settings
        self.fetch_odds = get_config(data_settings, 'fetch_odds', True)
        self.update_interval = get_config(data_settings, 'update_interval', 3600)
        self.live_game_update_interval = get_config(data_settings, 'live_game_update_interval', 60)
        self.future_fetch_days = get_config(data_settings, 'future_fetch_days', 7)
        self.request_timeout = get_config(data_settings, 'request_timeout', 30)
        self.base_update_interval = self.update_interval  # Store base interval for switching

        # Thread safety lock for concurrent access during live updates
        self._update_lock = threading.Lock()

        # Build enabled_leagues from individual league enabled flags (new structure) or from enabled_leagues array (old structure)
        if leagues_config:
            self.enabled_leagues = [
                league_key for league_key in ['nfl', 'nba', 'mlb', 'nhl', 'milb', 'ncaa_fb', 'ncaam_basketball', 'ncaa_baseball']
                if leagues_config.get(league_key, {}).get('enabled', False)
            ]
        else:
            self.enabled_leagues = self.odds_ticker_config.get('enabled_leagues', [])

        # Display options
        self.display_duration = get_config(display_options, 'display_duration', 30)
        self.target_fps = get_config(display_options, 'target_fps', 120)
        self.loop = get_config(display_options, 'loop', True)
        self.show_channel_logos = get_config(display_options, 'show_channel_logos', True)
        self.broadcast_logo_height_ratio = get_config(display_options, 'broadcast_logo_height_ratio', 0.8)
        self.broadcast_logo_max_width_ratio = get_config(display_options, 'broadcast_logo_max_width_ratio', 0.8)

        # Scroll speed configuration with backward compatibility
        # Precedence order (highest to lowest):
        #   1. display_options.scroll_speed/delay (CURRENT - recommended)
        #   2. display.scroll_speed/delay (DEPRECATED - old nested format)
        #   3. scroll_pixels_per_second (DEPRECATED - flat format)
        #   4. scroll_speed/delay at root level (LEGACY - flat format)
        display_config = self.odds_ticker_config.get('display', {})
        if display_options and ('scroll_speed' in display_options or 'scroll_delay' in display_options):
            # Priority 1: Current format - use display_options object
            self.scroll_speed = display_options.get('scroll_speed', 1.0)
            self.scroll_delay = display_options.get('scroll_delay', 0.02)
            self.scroll_pixels_per_second = display_options.get('scroll_pixels_per_second')
            self.logger.info(f"Using display_options.scroll_speed={self.scroll_speed} px/frame, display_options.scroll_delay={self.scroll_delay}s (frame-based mode)")
        elif display_config and ('scroll_speed' in display_config or 'scroll_delay' in display_config):
            # Old nested format: use display object for granular control
            self.scroll_speed = display_config.get('scroll_speed', 1.0)
            self.scroll_delay = display_config.get('scroll_delay', 0.02)
            self.scroll_pixels_per_second = None  # Not using pixels per second mode
            self.logger.info(f"Using display.scroll_speed={self.scroll_speed} px/frame, display.scroll_delay={self.scroll_delay}s (frame-based mode)")
        else:
            # Legacy flat format: use scroll_pixels_per_second (backward compatibility)
            self.scroll_pixels_per_second = self.odds_ticker_config.get('scroll_pixels_per_second')
            self.scroll_speed = self.odds_ticker_config.get('scroll_speed', 2)
            self.scroll_delay = self.odds_ticker_config.get('scroll_delay', 0.05)
            if self.scroll_pixels_per_second is not None:
                self.logger.info(f"Using scroll_pixels_per_second={self.scroll_pixels_per_second} px/s (time-based mode, backward compatibility)")
            else:
                # Calculate from legacy scroll_speed/scroll_delay
                self.logger.info(f"Using legacy scroll_speed={self.scroll_speed}, scroll_delay={self.scroll_delay} (backward compatibility)")

        # Dynamic duration settings
        self.dynamic_duration_enabled = get_config(display_options, 'dynamic_duration', True)
        self.min_duration = get_config(display_options, 'min_duration', 30)
        self.max_duration = get_config(display_options, 'max_duration', 300)
        self.duration_buffer = get_config(display_options, 'duration_buffer', 0.1)
        self.dynamic_duration = 60  # Default duration in seconds
        self.total_scroll_width = 0  # Track total width for dynamic duration calculation

        # Cache for dynamic duration to prevent race conditions during scroll
        self._cached_dynamic_duration = None
        self._duration_cache_time = 0
        
        # Initialize managers
        # BaseOddsManager is now inherited, no need for separate instance
        
        # Initialize background data service with optimized settings
        # Hardcoded for memory optimization: 1 worker, 30s timeout, 3 retries
        self.background_service = get_background_service(self.cache_manager, max_workers=1)
        self.background_fetch_requests = {}  # Track background fetch requests
        self.background_enabled = True
        logger.info("[Odds Ticker] Background service enabled with 1 worker (memory optimized)")
        
        # State variables
        self.last_update = 0
        self.games_data = []
        self.current_game_index = 0
        self.ticker_image = None # This will hold the single, wide image
        self.last_display_time = 0
        self._end_reached_logged = False  # Track if we've already logged reaching the end
        self._insufficient_time_warning_logged = False  # Track if we've already logged insufficient time warning
        self._team_rankings_cache = {}
        self._rankings_cache_timestamp = 0
        self._bases_data = None
        self._display_start_time = None

        # Independent live-game detection state (avoids cache TTL blind spot)
        self._scoreboard_last_checked = 0         # unix timestamp of last fresh scoreboard fetch
        self._live_check_interval = 300           # re-check scoreboard every 5 minutes
        self._last_scoreboard_live_status = False  # cached result of last scoreboard check

        # Get timezone from main config
        self.timezone = self._get_timezone()
        self.logger.info(f"Odds ticker using timezone: {self.timezone}")
        
        # Font setup
        self.fonts = self._load_fonts()
        
        # Initialize dynamic team resolver
        self.dynamic_resolver = DynamicTeamResolver()
        
        # Enable scrolling for high FPS mode in display controller
        # This tells the display controller to use 8ms intervals (125 FPS) instead of slower updates
        self.enable_scrolling = True
        logger.info(f"High FPS scrolling enabled: enable_scrolling={self.enable_scrolling}, target_fps={self.target_fps}")
        
        # Initialize ScrollHelper for scrolling functionality
        display_width = self.display_manager.matrix.width if hasattr(self.display_manager, 'matrix') else 128
        display_height = self.display_manager.matrix.height if hasattr(self.display_manager, 'matrix') else 32
        self.scroll_helper = ScrollHelper(display_width, display_height, logger=self.logger)
        
        # Configure ScrollHelper with plugin settings
        # Check if we should use frame-based scrolling (new format) or time-based (old format)
        use_frame_based = (self.scroll_pixels_per_second is None and 
                          display_config and 
                          ('scroll_speed' in display_config or 'scroll_delay' in display_config))
        
        if use_frame_based:
            # New format: use frame-based scrolling for finer control
            if hasattr(self.scroll_helper, 'set_frame_based_scrolling'):
                self.scroll_helper.set_frame_based_scrolling(True)
                self.logger.info(f"Frame-based scrolling enabled: {self.scroll_speed} px/frame, {self.scroll_delay}s delay")
            # In frame-based mode, scroll_speed is pixels per frame
            self.scroll_helper.set_scroll_speed(self.scroll_speed)
            self.scroll_helper.set_scroll_delay(self.scroll_delay)
            # Log effective pixels per second for reference
            pixels_per_second = self.scroll_speed / self.scroll_delay if self.scroll_delay > 0 else self.scroll_speed * 50
            self.logger.info(f"Effective scroll speed: {pixels_per_second:.1f} px/s ({self.scroll_speed} px/frame at {1.0/self.scroll_delay:.0f} FPS)")
        else:
            # Old format: use time-based scrolling (backward compatibility)
            if self.scroll_pixels_per_second is not None:
                pixels_per_second = self.scroll_pixels_per_second
                self.logger.info(f"Using scroll_pixels_per_second: {pixels_per_second} px/s (time-based mode)")
            else:
                # Convert scroll_speed from pixels per frame to pixels per second (backward compatibility)
                # scroll_speed is pixels per frame, scroll_delay is seconds per frame
                # So pixels per second = scroll_speed / scroll_delay
                pixels_per_second = self.scroll_speed / self.scroll_delay if self.scroll_delay > 0 else self.scroll_speed * 20
                self.logger.info(f"Calculated scroll speed: {pixels_per_second} px/s (from scroll_speed={self.scroll_speed}, scroll_delay={self.scroll_delay})")
            
            self.scroll_helper.set_scroll_speed(pixels_per_second)
            self.scroll_helper.set_scroll_delay(self.scroll_delay)
        
        # Set target FPS for high-performance scrolling (backward compatible)
        if hasattr(self.scroll_helper, 'set_target_fps'):
            self.scroll_helper.set_target_fps(self.target_fps)
        else:
            # Fallback for older ScrollHelper versions - set target_fps directly
            self.scroll_helper.target_fps = max(30.0, min(200.0, self.target_fps))
            self.scroll_helper.frame_time_target = 1.0 / self.scroll_helper.target_fps
            self.logger.debug(f"Target FPS set to: {self.scroll_helper.target_fps} FPS (using fallback method)")
        self.scroll_helper.set_dynamic_duration_settings(
            enabled=self.dynamic_duration_enabled,
            min_duration=self.min_duration,
            max_duration=self.max_duration,
            buffer=self.duration_buffer
        )
        
        # Get main app config for fallback to scoreboard settings
        main_config = {}
        if hasattr(plugin_manager, 'config_manager') and plugin_manager.config_manager:
            try:
                main_config = plugin_manager.config_manager.load_config() or {}
            except Exception as e:
                self.logger.warning(f"Could not load main config for league settings: {e}")

        # Plugin's own leagues config from config_schema.json
        plugin_leagues = self.odds_ticker_config.get('leagues', {})

        # Helper to get league settings - prefer plugin config, fall back to main config scoreboard
        def get_league_settings(league_key: str, scoreboard_key: str) -> tuple:
            """Get favorite_teams and enabled for a league from plugin config or main config."""
            plugin_league = plugin_leagues.get(league_key, {})
            main_scoreboard = main_config.get(scoreboard_key, {})

            # Prefer plugin config if set, otherwise use main config scoreboard settings
            # Use key presence check so explicit [] in plugin_league overrides main_scoreboard
            favorite_teams = plugin_league['favorite_teams'] if 'favorite_teams' in plugin_league else main_scoreboard.get('favorite_teams', [])
            # For enabled: plugin config takes precedence if explicitly set
            enabled = plugin_league.get('enabled', main_scoreboard.get('enabled', False))

            return favorite_teams, enabled

        # Helper to get soccer settings - includes leagues array
        def get_soccer_settings() -> dict:
            """Get leagues, favorite_teams, and enabled for soccer from plugin config or main config."""
            plugin_league = plugin_leagues.get('soccer', {})
            main_scoreboard = main_config.get('soccer_scoreboard', {})

            # Prefer plugin config if set, otherwise use main config scoreboard settings
            # Use key presence check so explicit [] in plugin_league overrides main_scoreboard
            leagues = plugin_league['leagues'] if 'leagues' in plugin_league else main_scoreboard.get('leagues', [])
            favorite_teams = plugin_league['favorite_teams'] if 'favorite_teams' in plugin_league else main_scoreboard.get('favorite_teams', [])
            # For enabled: plugin config takes precedence if explicitly set
            enabled = plugin_league.get('enabled', main_scoreboard.get('enabled', False))

            return {'leagues': leagues, 'favorite_teams': favorite_teams, 'enabled': enabled}

        # League configurations - use plugin config with fallback to main config scoreboards
        nfl_teams, nfl_enabled = get_league_settings('nfl', 'nfl_scoreboard')
        nba_teams, nba_enabled = get_league_settings('nba', 'nba_scoreboard')
        mlb_teams, mlb_enabled = get_league_settings('mlb', 'mlb_scoreboard')
        ncaa_fb_teams, ncaa_fb_enabled = get_league_settings('ncaa_fb', 'ncaa_fb_scoreboard')
        nhl_teams, nhl_enabled = get_league_settings('nhl', 'nhl_scoreboard')
        ncaam_teams, ncaam_enabled = get_league_settings('ncaam_basketball', 'ncaam_basketball_scoreboard')
        milb_teams, milb_enabled = get_league_settings('milb', 'milb_scoreboard')
        ncaa_baseball_teams, ncaa_baseball_enabled = get_league_settings('ncaa_baseball', 'ncaa_baseball_scoreboard')
        soccer_settings = get_soccer_settings()

        self.league_configs = {
            'nfl': {
                'sport': 'football',
                'league': 'nfl',
                'logo_league': 'nfl',
                'logo_dir': 'assets/sports/nfl_logos',
                'favorite_teams': nfl_teams,
                'enabled': nfl_enabled
            },
            'nba': {
                'sport': 'basketball',
                'league': 'nba',
                'logo_league': 'nba',
                'logo_dir': 'assets/sports/nba_logos',
                'favorite_teams': nba_teams,
                'enabled': nba_enabled
            },
            'mlb': {
                'sport': 'baseball',
                'league': 'mlb',
                'logo_league': 'mlb',
                'logo_dir': 'assets/sports/mlb_logos',
                'favorite_teams': mlb_teams,
                'enabled': mlb_enabled
            },
            'ncaa_fb': {
                'sport': 'football',
                'league': 'college-football',
                'logo_league': 'ncaa_fb',
                'logo_dir': 'assets/sports/ncaa_logos',
                'favorite_teams': ncaa_fb_teams,
                'enabled': ncaa_fb_enabled
            },
            'milb': {
                'sport': 'baseball',
                'league': 'milb',
                'logo_league': 'milb',
                'logo_dir': 'assets/sports/milb_logos',
                'favorite_teams': milb_teams,
                'enabled': milb_enabled
            },
            'nhl': {
                'sport': 'hockey',
                'league': 'nhl',
                'logo_league': 'nhl',
                'logo_dir': 'assets/sports/nhl_logos',
                'favorite_teams': nhl_teams,
                'enabled': nhl_enabled
            },
            'ncaam_basketball': {
                'sport': 'basketball',
                'league': 'mens-college-basketball',
                'logo_league': 'ncaam_basketball',
                'logo_dir': 'assets/sports/ncaa_logos',
                'favorite_teams': ncaam_teams,
                'enabled': ncaam_enabled
            },
            'ncaa_baseball': {
                'sport': 'baseball',
                'league': 'college-baseball',
                'logo_league': 'ncaa_baseball',
                'logo_dir': 'assets/sports/ncaa_logos',
                'favorite_teams': ncaa_baseball_teams,
                'enabled': ncaa_baseball_enabled
            },
            'soccer': {
                'sport': 'soccer',
                'leagues': soccer_settings['leagues'],
                'logo_league': None,
                'logo_dir': 'assets/sports/soccer_logos',
                'favorite_teams': soccer_settings['favorite_teams'],
                'enabled': soccer_settings['enabled']
            }
        }

        # Tournament seed display setting
        ncaam_config = plugin_leagues.get('ncaam_basketball', {})
        self.show_seeds_in_tournament = ncaam_config.get('show_seeds_in_tournament', True)

        # Resolve dynamic teams for each league
        for league_key, league_config in self.league_configs.items():
            if league_config.get('enabled', False):
                raw_favorite_teams = league_config.get('favorite_teams', [])
                if raw_favorite_teams:
                    # Resolve dynamic teams for this league
                    resolved_teams = self.dynamic_resolver.resolve_teams(raw_favorite_teams, league_key)
                    league_config['favorite_teams'] = resolved_teams

                    # Log dynamic team resolution
                    if raw_favorite_teams != resolved_teams:
                        logger.info(f"Resolved dynamic teams for {league_key}: {raw_favorite_teams} -> {resolved_teams}")
                    else:
                        logger.info(f"Favorite teams for {league_key}: {resolved_teams}")

        # Recompute enabled_leagues from resolved league_configs (includes fallback-enabled leagues)
        self.enabled_leagues = [
            league_key for league_key, league_cfg in self.league_configs.items()
            if league_cfg.get('enabled', False)
        ]

        logger.info(f"OddsTickerManager initialized with enabled leagues: {self.enabled_leagues}")
        logger.info(f"Show favorite teams only: {self.show_favorite_teams_only}")
        self.initialized = True

    def _get_config_value(self, section: Dict, key: str, default: Any,
                          config_dict: Dict[str, Any], old_key: str = None) -> Any:
        """Get config value from new nested structure or fall back to old flat structure.

        Args:
            section: The nested config section (e.g., display_options, filtering)
            key: The key to look up in the section
            default: Default value if key not found
            config_dict: The full config dict for flat structure fallback
            old_key: Optional alternative key name for backward compatibility

        Returns:
            The config value from section, config_dict, or default
        """
        if section:
            value = section.get(key, config_dict.get(key, default))
        else:
            value = config_dict.get(key, default)

        # Try old_key if value is still default and old_key is specified
        if value == default and old_key:
            value = config_dict.get(old_key, default)

        return value

    def _load_custom_font_from_element_config(self, element_config: Dict[str, Any], default_size: int = 8, default_font_name: str = 'PressStart2P-Regular.ttf') -> ImageFont.FreeTypeFont:
        """
        Load a custom font from an element configuration dictionary.
        
        Args:
            element_config: Configuration dict for a single element containing 'font' and 'font_size' keys
            default_size: Default font size if not specified in config
            default_font_name: Default font file name if not specified in config
            
        Returns:
            PIL ImageFont object
        """
        font_name = element_config.get('font', default_font_name)
        font_size = int(element_config.get('font_size', default_size))
        font_path = os.path.join('assets', 'fonts', font_name)
        
        try:
            if os.path.exists(font_path):
                if font_path.lower().endswith('.ttf'):
                    font = ImageFont.truetype(font_path, font_size)
                    self.logger.debug(f"Loaded font: {font_name} at size {font_size}")
                    return font
                elif font_path.lower().endswith('.bdf'):
                    try:
                        font = ImageFont.truetype(font_path, font_size)
                        self.logger.debug(f"Loaded BDF font: {font_name} at size {font_size}")
                        return font
                    except Exception:
                        self.logger.warning(f"Could not load BDF font {font_name} with PIL, using default")
                else:
                    self.logger.warning(f"Unknown font file type: {font_name}, using default")
            else:
                self.logger.warning(f"Font file not found: {font_path}, using default")
        except Exception as e:
            self.logger.error(f"Error loading font {font_name}: {e}, using default")
        
        # Fall back to default font
        default_font_path = os.path.join('assets', 'fonts', default_font_name)
        try:
            if os.path.exists(default_font_path):
                return ImageFont.truetype(default_font_path, font_size)
            else:
                self.logger.warning("Default font not found, using PIL default")
                return ImageFont.load_default()
        except Exception as e:
            self.logger.error(f"Error loading default font: {e}")
            return ImageFont.load_default()

    def _load_fonts(self) -> Dict[str, ImageFont.FreeTypeFont]:
        """Load fonts for the ticker display from config or use defaults."""
        customization = self.config.get('customization', {})
        
        # Load custom fonts for specific text elements
        team_config = customization.get('team_text', {})
        odds_config = customization.get('odds_text', {})
        datetime_config = customization.get('datetime_text', {})
        
        # Load fonts as instance variables
        self.team_font = self._load_custom_font_from_element_config(team_config, default_size=8)
        self.odds_font = self._load_custom_font_from_element_config(odds_config, default_size=8)
        self.datetime_font = self._load_custom_font_from_element_config(datetime_config, default_size=8)
        
        # Keep 'large' font in dict for error messages
        try:
            large_font = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 10)
        except Exception as e:
            self.logger.error(f"Error loading large font: {e}")
            large_font = ImageFont.load_default()
        
        return {
            'large': large_font
        }

    def _get_timezone(self):
        """Get timezone from main config with proper error handling."""
        try:
            timezone_str = 'UTC'
            if hasattr(self.plugin_manager, 'config_manager') and self.plugin_manager.config_manager:
                try:
                    main_config = self.plugin_manager.config_manager.load_config()
                    timezone_str = main_config.get('timezone', 'UTC')
                except Exception as e:
                    self.logger.warning(f"Could not load timezone from config: {e}, using UTC")
            
            if pytz:
                return pytz.timezone(timezone_str)
            return pytz.UTC if pytz else None
        except Exception as e:
            self.logger.warning(f"Error setting timezone: {e}, using UTC")
            return pytz.UTC if pytz else None

    def _parse_and_convert_time(self, start_time):
        """
        Parse start_time (string or datetime) and convert to local timezone.
        
        Args:
            start_time: String ISO format datetime or datetime object
            
        Returns:
            datetime object in local timezone, or None if parsing fails
        """
        try:
            # Handle string input
            if isinstance(start_time, str):
                # Parse ISO format string, handling 'Z' timezone indicator
                game_time = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
            elif isinstance(start_time, datetime):
                game_time = start_time
            else:
                self.logger.warning(f"Unexpected start_time type: {type(start_time)}")
                return None
            
            # Ensure timezone info is present (assume UTC if missing)
            if game_time.tzinfo is None:
                game_time = game_time.replace(tzinfo=pytz.UTC)
            
            # Validate timezone before conversion
            timezone = self.timezone
            if timezone is None:
                self.logger.warning("Timezone is None, using UTC as fallback")
                timezone = pytz.UTC
            
            # Convert to local timezone
            local_time = game_time.astimezone(timezone)
            return local_time
            
        except Exception as e:
            self.logger.debug(f"Error parsing start_time '{start_time}': {e}")
            return None

    def _fetch_team_record(self, team_abbr: str, league: str) -> str:
        """Fetch team record from ESPN API."""
        # This is a simplified implementation; a more robust solution would cache team data
        try:
            sport = 'baseball' if league == 'mlb' else 'football' if league in ['nfl', 'college-football'] else 'basketball'
            
            # Use a more specific endpoint for college sports
            if league == 'college-football':
                url = f"https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams/{team_abbr}"
            else:
                url = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/teams/{team_abbr}"

            response = requests.get(url, timeout=self.request_timeout)
            response.raise_for_status()
            data = response.json()
            
            # Increment API counter for sports data
            increment_api_counter('sports', 1)
            
            # Different path for college sports records
            if league == 'college-football':
                record_items = data.get('team', {}).get('record', {}).get('items', [])
                if record_items:
                    return record_items[0].get('summary', 'N/A')
                else:
                    return 'N/A'
            else:
                record = data.get('team', {}).get('record', {}).get('summary', 'N/A')
                return record

        except Exception as e:
            logger.error(f"Error fetching record for {team_abbr} in league {league}: {e}")
            return "N/A"

    def _fetch_team_rankings(self, league_key: str = 'ncaa_fb') -> Dict[str, int]:
        """Fetch current team rankings from ESPN API for NCAA football or basketball."""
        current_time = time.time()
        
        # Use separate cache keys for different leagues
        cache_key = f'_team_rankings_cache_{league_key}'
        timestamp_key = f'_rankings_cache_timestamp_{league_key}'
        
        # Check if we have cached rankings that are still valid
        if (hasattr(self, cache_key) and 
            hasattr(self, timestamp_key) and
            getattr(self, cache_key, None) and 
            current_time - getattr(self, timestamp_key, 0) < 3600):  # Cache for 1 hour
            return getattr(self, cache_key, {})
        
        try:
            # Map league keys to ESPN API paths
            rankings_urls = {
                'ncaa_fb': "https://site.api.espn.com/apis/site/v2/sports/football/college-football/rankings",
                'ncaam_basketball': "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/rankings"
            }
            
            rankings_url = rankings_urls.get(league_key)
            if not rankings_url:
                logger.warning(f"No rankings URL configured for league: {league_key}")
                return {}
            
            response = requests.get(rankings_url, timeout=self.request_timeout)
            response.raise_for_status()
            data = response.json()
            
            # Increment API counter for sports data
            increment_api_counter('sports', 1)
            
            rankings = {}
            rankings_data = data.get('rankings', [])
            
            if rankings_data:
                # Use the first ranking (usually AP Top 25)
                first_ranking = rankings_data[0]
                teams = first_ranking.get('ranks', [])
                
                for team_data in teams:
                    team_info = team_data.get('team', {})
                    team_abbr = team_info.get('abbreviation', '')
                    current_rank = team_data.get('current', 0)
                    
                    if team_abbr and current_rank > 0:
                        rankings[team_abbr] = current_rank
            
            # Cache the results
            setattr(self, cache_key, rankings)
            setattr(self, timestamp_key, current_time)
            
            logger.debug(f"Fetched rankings for {len(rankings)} teams from {league_key}")
            return rankings
            
        except Exception as e:
            logger.error(f"Error fetching team rankings for {league_key}: {e}")
            return {}

    def get_odds(self, sport: str | None, league: str | None, event_id: str,
                 update_interval_seconds: int = None, is_live: bool = False) -> Optional[Dict[str, Any]]:
        """
        Override base class method to support is_live parameter for cache key modification.
        
        For live games, appends '_live' to cache key to trigger odds_live cache strategy (2 min vs 30 min).
        
        Args:
            sport: Sport name (e.g., 'football', 'basketball')
            league: League name (e.g., 'nfl', 'nba')
            event_id: ESPN event ID
            update_interval_seconds: Override default update interval
            is_live: Whether the game is currently live (uses shorter cache TTL)

        Returns:
            Dictionary containing odds data or None if unavailable
        """
        if sport is None or league is None:
            raise ValueError("Sport and League cannot be None")

        # Use provided interval or default
        interval = update_interval_seconds or self.update_interval
        # Include 'live' in cache key for live games to trigger odds_live cache strategy (2 min vs 30 min)
        cache_key = f"odds_espn_{sport}_{league}_{event_id}_live" if is_live else f"odds_espn_{sport}_{league}_{event_id}"

        # Check cache first
        cached_data = self.cache_manager.get_with_auto_strategy(cache_key)

        if cached_data:
            self.logger.info(f"Using cached odds from ESPN for {cache_key}")
            return cached_data

        self.logger.info(f"Cache miss - fetching fresh odds from ESPN for {cache_key}")
        
        try:
            # Map league names to ESPN API format
            league_mapping = {
                'ncaa_fb': 'college-football',
                'nfl': 'nfl',
                'nba': 'nba',
                'mlb': 'mlb',
                'nhl': 'nhl'
            }
            
            espn_league = league_mapping.get(league, league)
            url = f"{self.base_url}/{sport}/leagues/{espn_league}/events/{event_id}/competitions/{event_id}/odds"
            self.logger.info(f"Requesting odds from URL: {url}")
            
            response = requests.get(url, timeout=self.request_timeout)
            response.raise_for_status()
            raw_data = response.json()
            
            # Increment API counter for odds data
            increment_api_counter('odds', 1)
            self.logger.debug(f"Received raw odds data from ESPN: {json.dumps(raw_data, indent=2)}")
            
            odds_data = self._extract_espn_data(raw_data)
            if odds_data:
                self.logger.info(f"Successfully extracted odds data: {odds_data}")
            else:
                self.logger.debug("No odds data available for this game")
            
            if odds_data:
                self.cache_manager.set(cache_key, odds_data, ttl=interval)
                self.logger.info(f"Saved odds data to cache for {cache_key} with TTL {interval}s")
            else:
                self.logger.debug(f"No odds data available for {cache_key}")
                # Cache the fact that no odds are available to avoid repeated API calls
                self.cache_manager.set(cache_key, {"no_odds": True}, ttl=interval)
            
            return odds_data

        except requests.exceptions.RequestException as e:
            self.logger.error(f"Error fetching odds from ESPN API for {cache_key}: {e}")
        except json.JSONDecodeError:
            self.logger.error(f"Error decoding JSON response from ESPN API for {cache_key}.")
        
        return self.cache_manager.get_with_auto_strategy(cache_key)

    def convert_image(self, logo_path: Path) -> Optional[Image.Image]:
        if logo_path.exists():
            logo = Image.open(logo_path)
            # Convert palette images with transparency to RGBA to avoid PIL warnings
            if logo.mode == 'P' and 'transparency' in logo.info:
                logo = logo.convert('RGBA')
            logger.debug(f"Successfully loaded logo {logo_path}")
            return logo
        return None

    def _get_team_logo(self, league: str, team_id: str, team_abbr: str, logo_dir: str) -> Optional[Image.Image]:
        """Get team logo from the configured directory, downloading if missing."""
        if not team_abbr or not logo_dir:
            logger.debug("Cannot get team logo with missing team_abbr or logo_dir")
            return None
        try:
            # Resolve logo_dir path - if relative, resolve relative to project root
            logo_dir_path = Path(logo_dir)
            if not logo_dir_path.is_absolute():
                logo_dir_path = self.project_root / logo_dir_path
            logo_path = logo_dir_path / f"{team_abbr}.png"
            logger.debug(f"Attempting to load logo from path: {logo_path}")
            if (image := self.convert_image(logo_path)):
                return image
            else:
                logger.warning(f"Logo not found at path: {logo_path}")
                
                # Try to download the missing logo if we have league information
                if league and download_missing_logo:
                    logger.info(f"Attempting to download missing logo for {team_abbr} in league {league}")
                    success = download_missing_logo(league, team_id, team_abbr, logo_path, None)
                    if success:
                        # Try to load the downloaded logo
                        if os.path.exists(logo_path):
                            logo = Image.open(logo_path)
                            # Convert palette images with transparency to RGBA to avoid PIL warnings
                            if logo.mode == 'P' and 'transparency' in logo.info:
                                logo = logo.convert('RGBA')
                            logger.info(f"Successfully downloaded and loaded logo for {team_abbr}")
                            return logo
                
                return None
        except Exception as e:
            logger.error(f"Error loading logo for {team_abbr} from {logo_dir}: {e}")
            return None

    def _fetch_upcoming_games(self) -> List[Dict[str, Any]]:
        """Fetch upcoming games with odds for all enabled leagues with user-defined granularity."""
        games_data = []
        now = datetime.now(timezone.utc)
        
        if not self.enabled_leagues:
            logger.warning("No enabled leagues configured for odds ticker")
            return games_data
        
        logger.info(f"Fetching upcoming games for {len(self.enabled_leagues)} enabled leagues: {self.enabled_leagues}")
        logger.debug(f"Show favorite teams only: {self.show_favorite_teams_only}")
        logger.debug(f"Show odds only: {self.show_odds_only}")
        
        for league_key in self.enabled_leagues:
            if league_key not in self.league_configs:
                logger.warning(f"Unknown league: {league_key}")
                continue
                
            league_config = self.league_configs[league_key]
            if not league_config.get('enabled', False):
                logger.warning(f"League {league_key} is in enabled_leagues list but has enabled=False in config, skipping")
                continue
            logger.debug(f"Processing league {league_key}: enabled={league_config['enabled']}")
            
            try:
                # Fetch all upcoming games for this league
                # Pass league_key so it can be stored as canonical lookup value in game dict
                all_games = self._fetch_league_games(league_config, now, league_key)
                logger.debug(f"Found {len(all_games)} games for {league_key}")
                league_games = []
                
                if self.show_favorite_teams_only:
                    # Collect games for favorite teams without duplication
                    # Fixes: games appearing twice when both teams are favorites,
                    # and odds filter being applied after per-team limit
                    favorite_teams = league_config.get('favorite_teams', [])
                    logger.debug(f"Favorite teams for {league_key}: {favorite_teams}")

                    if not favorite_teams:
                        logger.debug(f"No favorite teams configured for {league_key}, skipping")
                        continue

                    # Sort all games by start time first for consistent priority
                    all_games.sort(key=lambda x: x.get('start_time', datetime.max))

                    # NOTE: Odds filter moved AFTER favorite team selection to preserve favorites
                    # even when odds aren't available yet (e.g., early morning games)

                    seen_game_ids = set()
                    team_game_counts = {team: 0 for team in favorite_teams}

                    for game in all_games:
                        home_team = game.get('home_team', '')
                        away_team = game.get('away_team', '')
                        game_id = game.get('id')

                        is_home_favorite = home_team in favorite_teams
                        is_away_favorite = away_team in favorite_teams

                        # Skip if neither team is a favorite
                        if not is_home_favorite and not is_away_favorite:
                            continue

                        # Check if either favorite team still needs games
                        home_needs = is_home_favorite and team_game_counts.get(home_team, 0) < self.games_per_favorite_team
                        away_needs = is_away_favorite and team_game_counts.get(away_team, 0) < self.games_per_favorite_team

                        # Add game if at least one team needs it and we haven't seen it
                        if (home_needs or away_needs) and game_id not in seen_game_ids:
                            league_games.append(game)
                            seen_game_ids.add(game_id)
                            # Game counts for BOTH teams if both are favorites
                            if is_home_favorite:
                                team_game_counts[home_team] += 1
                            if is_away_favorite:
                                team_game_counts[away_team] += 1

                            # Check if all favorite teams are satisfied
                            if all(team_game_counts.get(t, 0) >= self.games_per_favorite_team for t in favorite_teams):
                                logger.debug(f"All favorite teams satisfied for {league_key}")
                                break

                    logger.debug(f"Favorite teams game counts: {team_game_counts}")

                    # Apply odds filter AFTER favorite team selection (with fallback)
                    # This preserves favorite team games even when odds aren't available yet
                    if self.show_odds_only and league_games:
                        games_with_odds = [g for g in league_games if g.get('odds') and not g.get('odds', {}).get('no_odds', False)]
                        if games_with_odds:
                            logger.debug(f"Odds filter on favorites: {len(league_games)} -> {len(games_with_odds)} games for {league_key}")
                            league_games = games_with_odds
                        else:
                            logger.info(f"No favorite team games have odds yet for {league_key}, showing {len(league_games)} games without odds filter")

                    # Cap at max_games_per_league as final safety limit
                    league_games = league_games[:self.max_games_per_league]
                else:
                    # Show all games, optionally only those with odds
                    league_games = all_games
                    if self.show_odds_only:
                        league_games = [g for g in league_games if g.get('odds') and not g.get('odds', {}).get('no_odds', False)]
                    # Sort by start_time
                    league_games.sort(key=lambda x: x.get('start_time', datetime.max))
                    league_games = league_games[:self.max_games_per_league]
                
                # Sorting (default is soonest)
                if self.sort_order == 'soonest':
                    league_games.sort(key=lambda x: x.get('start_time', datetime.max))
                # (Other sort options can be added here)
                
                games_data.extend(league_games)
                logger.debug(f"Added {len(league_games)} games from {league_key}")
                
            except Exception as e:
                logger.error(f"Error fetching games for {league_key}: {e}", exc_info=True)

        # Apply global sort based on sort_order setting
        if self.sort_order == 'soonest':
            # True chronological order across all leagues
            # Secondary sort by team names for deterministic ordering of same-time games
            games_data.sort(key=lambda x: (
                x.get('start_time', datetime.max),
                x.get('away_team', '').lower(),
                x.get('home_team', '').lower()
            ))
            logger.debug(f"Globally sorted {len(games_data)} games by start_time (soonest first)")
        elif self.sort_order == 'team':
            # Sort alphabetically by matchup (away @ home), then by start time
            games_data.sort(key=lambda x: (
                x.get('away_team', '').lower(),
                x.get('home_team', '').lower(),
                x.get('start_time', datetime.max)
            ))
            logger.debug(f"Globally sorted {len(games_data)} games by team name")
        # 'league' option: keep current order (games already grouped by league)

        logger.info(f"Total games found: {len(games_data)}")
        if games_data:
            logger.debug(f"Sample game data keys: {list(games_data[0].keys())}")
        elif self.enabled_leagues:
            logger.warning(f"No games found for any of the {len(self.enabled_leagues)} enabled leagues")
        return games_data

    def _fetch_league_games(self, league_config: Dict[str, Any], now: datetime, canonical_league_key: str) -> List[Dict[str, Any]]:
        """Fetch upcoming games for a specific league using day-by-day approach."""
        games = []
        yesterday = now - timedelta(days=1)
        future_window = now + timedelta(days=self.future_fetch_days)
        num_days = (future_window - yesterday).days + 1
        dates = [(yesterday + timedelta(days=i)).strftime("%Y%m%d") for i in range(num_days)]

        # Optimization: If showing favorite teams only, track games found per team
        favorite_teams = league_config.get('favorite_teams', []) if self.show_favorite_teams_only else []
        team_games_found = {team: 0 for team in favorite_teams}
        max_games = self.games_per_favorite_team if self.show_favorite_teams_only else None
        all_games = []
        
        # Optimization: Track total games found
        # max_games_per_league applies as a safety limit in all modes
        games_found = 0
        max_games_per_league = self.max_games_per_league

        sport = league_config['sport']
        leagues_to_fetch = []
        if sport == 'soccer':
            leagues_to_fetch.extend(league_config.get('leagues', []))
        else:
            if league_config.get('league'):
                leagues_to_fetch.append(league_config.get('league'))

        for league in leagues_to_fetch:
            # As requested, do not even attempt to make API calls for MiLB.
            if league == 'milb':
                logger.warning("Skipping all MiLB game requests as the API endpoint is not supported.")
                continue
                
            for date in dates:
                # Stop if we have enough games for favorite teams OR hit max games safety limit
                if self.show_favorite_teams_only and favorite_teams:
                    all_teams_satisfied = all(team_games_found.get(t, 0) >= max_games for t in favorite_teams)
                    max_reached = max_games_per_league and games_found >= max_games_per_league
                    if all_teams_satisfied or max_reached:
                        break  # All favorite teams satisfied or max limit reached
                # Stop if we have enough games for the league (when not showing favorite teams only)
                if not self.show_favorite_teams_only and max_games_per_league and games_found >= max_games_per_league:
                    break  # We have enough games for this league, stop searching
                try:
                    cache_key = f"scoreboard_data_{sport}_{league}_{date}"

                    # Dynamically set TTL for scoreboard data
                    current_date_obj = now.date()
                    request_date_obj = datetime.strptime(date, "%Y%m%d").date()

                    if request_date_obj < current_date_obj:
                        # For yesterday, use short TTL to ensure stale live games are updated
                        # For older dates, use longer TTL since games are definitely final
                        days_ago = (current_date_obj - request_date_obj).days
                        if days_ago == 1:
                            ttl = 3600  # 1 hour for yesterday (to catch games that finished late)
                        else:
                            ttl = 86400 * 30  # 30 days for older dates
                    elif request_date_obj == current_date_obj:
                        ttl = 300  # 5 minutes for today (shorter to catch live games)
                    else:
                        ttl = 43200  # 12 hours for future dates
                    
                    data = self.cache_manager.get(cache_key, max_age=ttl)

                    if data is None:
                        url = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard?dates={date}"
                        logger.debug(f"Fetching {league} games from ESPN API for date: {date}")
                        response = requests.get(url, timeout=self.request_timeout)
                        response.raise_for_status()
                        data = response.json()
                        
                        # Increment API counter for sports data
                        increment_api_counter('sports', 1)
                        
                        self.cache_manager.set(cache_key, data)
                        logger.debug(f"Cached scoreboard for {league} on {date} with a TTL of {ttl} seconds.")
                    else:
                        logger.debug(f"Using cached scoreboard data for {league} on {date}.")

                    for event in data.get('events', []):
                        # Stop if we have enough games for the league (when not showing favorite teams only)
                        if not self.show_favorite_teams_only and max_games_per_league and games_found >= max_games_per_league:
                            break
                        game_id = event['id']
                        status = event['status']['type']['name'].lower()
                        status_state = event['status']['type']['state'].lower()

                        # Explicitly exclude completed games (defense against stale cached data)
                        if status_state == 'post':
                            continue

                        # Include both scheduled and live games
                        if status in ['scheduled', 'pre-game', 'status_scheduled'] or status_state == 'in':
                            game_time = datetime.fromisoformat(event['date'].replace('Z', '+00:00'))

                            # Additional safety: exclude games claiming to be "in progress" but started >48h ago
                            # (likely stale cached data from a game that should have ended)
                            # Using 48h threshold to allow for rain delays, extra innings, etc.
                            if status_state == 'in':
                                hours_since_start = (now - game_time).total_seconds() / 3600
                                if hours_since_start > 48:
                                    logger.warning(f"Filtering out stale 'in progress' game {game_id} that started {hours_since_start:.1f}h ago")
                                    continue

                            # For live games, include them regardless of time window
                            # For scheduled games, check if they're within the future window
                            if status_state == 'in' or (now <= game_time <= future_window):
                                competitors = event['competitions'][0]['competitors']
                                home_team = next(c for c in competitors if c['homeAway'] == 'home')
                                away_team = next(c for c in competitors if c['homeAway'] == 'away')
                                home_id = home_team['team']['id']
                                away_id = away_team['team']['id']
                                home_abbr = home_team['team']['abbreviation']
                                away_abbr = away_team['team']['abbreviation']
                                home_name = home_team['team'].get('name', home_abbr)
                                away_name = away_team['team'].get('name', away_abbr)

                                # Extract tournament metadata (seeds + round) for NCAA basketball only
                                tournament_round = ""
                                home_seed = 0
                                away_seed = 0
                                if canonical_league_key in ('ncaam_basketball', 'ncaaw_basketball'):
                                    competition = event['competitions'][0]
                                    notes = competition.get('notes', [])
                                    for note in notes:
                                        headline = note.get('headline', '')
                                        if any(kw in headline for kw in ('Championship', 'Round', 'Sweet', 'Elite', 'Final Four')):
                                            tournament_round = headline
                                            break
                                    if tournament_round:
                                        try:
                                            home_seed = int(home_team.get('curatedRank', {}).get('current', 0) or 0)
                                        except (TypeError, ValueError):
                                            home_seed = 0
                                        try:
                                            away_seed = int(away_team.get('curatedRank', {}).get('current', 0) or 0)
                                        except (TypeError, ValueError):
                                            away_seed = 0
                                        if not 1 <= home_seed <= 16:
                                            home_seed = 0
                                        if not 1 <= away_seed <= 16:
                                            away_seed = 0

                                broadcast_info = []
                                broadcasts = event.get('competitions', [{}])[0].get('broadcasts', [])
                                if broadcasts:
                                    # Handle new ESPN API format where broadcast names are in 'names' array
                                    for broadcast in broadcasts:
                                        if 'names' in broadcast:
                                            # New format: broadcast names are in 'names' array
                                            broadcast_names = broadcast.get('names', [])
                                            broadcast_info.extend(broadcast_names)
                                        elif 'media' in broadcast and 'shortName' in broadcast['media']:
                                            # Old format: broadcast name is in media.shortName
                                            short_name = broadcast['media']['shortName']
                                            if short_name:
                                                broadcast_info.append(short_name)
                                    
                                    # Remove duplicates and filter out empty strings
                                    broadcast_info = list(set([name for name in broadcast_info if name]))
                                    
                                    logger.info(f"Found broadcast channels for game {game_id}: {broadcast_info}")
                                    logger.debug(f"Raw broadcasts data for game {game_id}: {broadcasts}")
                                    # Log the first broadcast structure for debugging
                                    if broadcasts:
                                        logger.debug(f"First broadcast structure: {broadcasts[0]}")
                                        if 'media' in broadcasts[0]:
                                            logger.debug(f"Media structure: {broadcasts[0]['media']}")
                                else:
                                    logger.debug(f"No broadcasts data found for game {game_id}")
                                    # Log the competitions structure to see what's available
                                    competitions = event.get('competitions', [])
                                    if competitions:
                                        logger.debug(f"Competitions structure for game {game_id}: {competitions[0].keys()}")

                                # Only process favorite teams if enabled
                                if self.show_favorite_teams_only:
                                    if not favorite_teams:
                                        continue
                                    if home_abbr not in favorite_teams and away_abbr not in favorite_teams:
                                        continue
                                # Build game dict (existing logic)
                                home_record = home_team.get('records', [{}])[0].get('summary', '') if home_team.get('records') else ''
                                away_record = away_team.get('records', [{}])[0].get('summary', '') if away_team.get('records') else ''
                                
                                # Dynamically set update interval based on game start time
                                time_until_game = game_time - now
                                if status_state == 'in':
                                    # Live games need more frequent updates
                                    update_interval_seconds = 300  # 5 minutes for live games
                                elif time_until_game > timedelta(hours=48):
                                    update_interval_seconds = 86400  # 24 hours
                                else:
                                    update_interval_seconds = 3600   # 1 hour
                                
                                logger.debug(f"Game {game_id} starts in {time_until_game}. Setting odds update interval to {update_interval_seconds}s.")
                                
                                # Fetch odds with timeout protection to prevent freezing (if enabled)
                                # Determine if game is live for cache strategy
                                is_live_game = status_state == 'in'
                                if self.fetch_odds:
                                    try:
                                        import threading
                                        import queue

                                        result_queue = queue.Queue()

                                        def fetch_odds():
                                            try:
                                                odds_result = self.get_odds(
                                                    sport=sport,
                                                    league=league,
                                                    event_id=game_id,
                                                    update_interval_seconds=update_interval_seconds,
                                                    is_live=is_live_game
                                                )
                                                result_queue.put(('success', odds_result))
                                            except Exception as e:
                                                result_queue.put(('error', e))
                                        
                                        # Start odds fetch in a separate thread
                                        odds_thread = threading.Thread(target=fetch_odds)
                                        odds_thread.daemon = True
                                        odds_thread.start()
                                        
                                        # Wait for result with 3-second timeout
                                        try:
                                            result_type, result_data = result_queue.get(timeout=3)
                                            if result_type == 'success':
                                                odds_data = result_data
                                            else:
                                                logger.warning(f"Odds fetch failed for game {game_id}: {result_data}")
                                                odds_data = None
                                        except queue.Empty:
                                            logger.warning(f"Odds fetch timed out for game {game_id}")
                                            odds_data = None
                                        
                                    except Exception as e:
                                        logger.warning(f"Odds fetch failed for game {game_id}: {e}")
                                        odds_data = None
                                else:
                                    # Odds fetching is disabled
                                    odds_data = None
                                
                                has_odds = False
                                if odds_data and not odds_data.get('no_odds'):
                                    if odds_data.get('spread') is not None:
                                        has_odds = True
                                    if odds_data.get('home_team_odds', {}).get('spread_odds') is not None:
                                        has_odds = True
                                    if odds_data.get('away_team_odds', {}).get('spread_odds') is not None:
                                        has_odds = True
                                    if odds_data.get('over_under') is not None:
                                        has_odds = True
                                
                                # Extract live game information if the game is in progress
                                live_info = None
                                if status_state == 'in':
                                    live_info = self._extract_live_game_info(event, sport)
                                
                                game = {
                                    'id': game_id,
                                    'home_id': home_id,
                                    'away_id': away_id,
                                    'home_team': home_abbr,
                                    'away_team': away_abbr,
                                    'home_team_name': home_name,
                                    'away_team_name': away_name,
                                    'start_time': game_time,
                                    'home_record': home_record,
                                    'away_record': away_record,
                                    'odds': odds_data if has_odds else None,
                                    'broadcast_info': broadcast_info,
                                    'logo_dir': league_config.get('logo_dir', f'assets/sports/{league.lower()}_logos'),
                                    'league': canonical_league_key,  # Canonical lookup key (e.g., 'nfl', 'nba', 'soccer')
                                    'logo_league': league_config.get('logo_league'),  # For logo downloads (can be None for soccer)
                                    'status': status,
                                    'status_state': status_state,
                                    'live_info': live_info,
                                    'tournament_round': tournament_round,
                                    'home_seed': home_seed,
                                    'away_seed': away_seed
                                }
                                all_games.append(game)
                                games_found += 1
                                # If favorite teams only, increment counters
                                if self.show_favorite_teams_only:
                                    for team in [home_abbr, away_abbr]:
                                        if team in team_games_found and team_games_found[team] < max_games:
                                            team_games_found[team] += 1
                    # Stop if we have enough games for the league (when not showing favorite teams only)
                    if not self.show_favorite_teams_only and max_games_per_league and games_found >= max_games_per_league:
                        break
                except requests.exceptions.HTTPError as http_err:
                    status_code = http_err.response.status_code if http_err.response else None
                    if status_code == 404:
                        logger.debug(f"No games found for {league} on {date} (404)")
                    elif status_code == 503:
                        logger.warning(f"ESPN API unavailable for {league} on {date} (503) - will retry later")
                    elif status_code == 429:
                        logger.warning(f"Rate limited by ESPN API for {league} on {date} (429) - backing off")
                    elif status_code and status_code >= 500:
                        logger.error(f"ESPN API server error for {league} on {date}: {http_err}", exc_info=True)
                    else:
                        logger.error(f"HTTP error fetching games for {league} on {date}: {http_err}")
                except requests.exceptions.Timeout:
                    logger.warning(f"Timeout fetching games for {league} on {date} - will retry later")
                except requests.exceptions.ConnectionError:
                    logger.warning(f"Connection error fetching games for {league} on {date} - network may be unavailable")
                except Exception as e:
                    logger.error(f"Unexpected error fetching games for {league_config.get('league', 'unknown')} on {date}: {e}", exc_info=True)
            if not self.show_favorite_teams_only and max_games_per_league and games_found >= max_games_per_league:
                break
        return all_games

    def _extract_live_game_info(self, event: Dict[str, Any], sport: str) -> Dict[str, Any]:
        """Extract live game information from ESPN API event data."""
        try:
            status = event['status']
            competitions = event['competitions'][0]
            competitors = competitions['competitors']
            
            # Get scores
            home_score = next(c['score'] for c in competitors if c['homeAway'] == 'home')
            away_score = next(c['score'] for c in competitors if c['homeAway'] == 'away')
            
            live_info = {
                'home_score': home_score,
                'away_score': away_score,
                'period': status.get('period', 1),
                'clock': status.get('displayClock', ''),
                'detail': status['type'].get('detail', ''),
                'short_detail': status['type'].get('shortDetail', '')
            }
            
            # Sport-specific information
            if sport == 'baseball':
                # Extract inning information
                situation = competitions.get('situation', {})
                count = situation.get('count', {})
                
                live_info.update({
                    'inning': status.get('period', 1),
                    'inning_half': 'top',  # Default
                    'balls': count.get('balls', 0),
                    'strikes': count.get('strikes', 0),
                    'outs': situation.get('outs', 0),
                    'bases_occupied': [
                        situation.get('onFirst', False),
                        situation.get('onSecond', False),
                        situation.get('onThird', False)
                    ]
                })
                
                # Determine inning half from status detail
                status_detail = status['type'].get('detail', '').lower()
                status_short = status['type'].get('shortDetail', '').lower()
                
                if 'bottom' in status_detail or 'bot' in status_detail or 'bottom' in status_short or 'bot' in status_short:
                    live_info['inning_half'] = 'bottom'
                elif 'top' in status_detail or 'mid' in status_detail or 'top' in status_short or 'mid' in status_short:
                    live_info['inning_half'] = 'top'
                    
            elif sport == 'football':
                # Extract football-specific information
                situation = competitions.get('situation', {})
                
                live_info.update({
                    'quarter': status.get('period', 1),
                    'down': situation.get('down', 0),
                    'distance': situation.get('distance', 0),
                    'yard_line': situation.get('yardLine', 0),
                    'possession': situation.get('possession', '')
                })
                
            elif sport == 'basketball':
                # Extract basketball-specific information
                situation = competitions.get('situation', {})
                
                live_info.update({
                    'quarter': status.get('period', 1),
                    'time_remaining': status.get('displayClock', ''),
                    'possession': situation.get('possession', '')
                })
                
            elif sport == 'hockey':
                # Extract hockey-specific information
                situation = competitions.get('situation', {})
                
                live_info.update({
                    'period': status.get('period', 1),
                    'time_remaining': status.get('displayClock', ''),
                    'power_play': situation.get('powerPlay', False)
                })
                
            elif sport == 'soccer':
                # Extract soccer-specific information
                live_info.update({
                    'period': status.get('period', 1),
                    'time_remaining': status.get('displayClock', ''),
                    'extra_time': status.get('displayClock', '').endswith('+')
                })
            
            return live_info
            
        except Exception as e:
            logger.error(f"Error extracting live game info: {e}")
            return None

    def _format_odds_text(self, game: Dict[str, Any]) -> str:
        """Format the odds text for display."""
        # Check if this is a live game
        is_live = game.get('status_state') == 'in'
        live_info = game.get('live_info')
        
        if is_live and live_info:
            # Format live game information
            home_score = live_info.get('home_score', 0)
            away_score = live_info.get('away_score', 0)
            
            # Determine sport for sport-specific formatting
            sport = None
            league_key = game.get('league')
            if league_key and league_key in self.league_configs:
                sport = self.league_configs[league_key].get('sport')
            
            # Get team names with rankings for NCAA football or basketball
            away_team_name = game.get('away_team_name', game['away_team'])
            home_team_name = game.get('home_team_name', game['home_team'])
            away_team_abbr = game.get('away_team', '')
            home_team_abbr = game.get('home_team', '')
            
            # Check if this is NCAA football or basketball and add rankings
            league_key = game.get('league')  # Use the league field from game dict
            if league_key in ['ncaa_fb', 'ncaam_basketball']:
                rankings = self._fetch_team_rankings(league_key)
                
                # Add ranking to away team name if ranked
                if away_team_abbr in rankings and rankings[away_team_abbr] > 0:
                    away_team_name = f"{rankings[away_team_abbr]}. {away_team_name}"
                
                # Add ranking to home team name if ranked
                if home_team_abbr in rankings and rankings[home_team_abbr] > 0:
                    home_team_name = f"{rankings[home_team_abbr]}. {home_team_name}"
            
            if sport == 'baseball':
                inning_half_indicator = "▲" if live_info.get('inning_half') == 'top' else "▼"
                inning_text = f"{inning_half_indicator}{live_info.get('inning', 1)}"
                count_text = f"{live_info.get('balls', 0)}-{live_info.get('strikes', 0)}"
                outs_count = live_info.get('outs', 0)
                outs_text = f"{outs_count} out" if outs_count == 1 else f"{outs_count} outs"
                return f"[LIVE] {away_team_name} {away_score} vs {home_team_name} {home_score} - {inning_text} {count_text} {outs_text}"
                
            elif sport == 'football':
                quarter_text = f"Q{live_info.get('quarter', 1)}"
                # Validate down and distance for odds ticker display
                down = live_info.get('down')
                distance = live_info.get('distance')
                if (down is not None and isinstance(down, int) and 1 <= down <= 4 and 
                    distance is not None and isinstance(distance, int) and distance >= 0):
                    down_text = f"{down}&{distance}"
                else:
                    down_text = ""  # Don't show invalid down/distance
                clock_text = live_info.get('clock', '')
                return f"[LIVE] {away_team_name} {away_score} vs {home_team_name} {home_score} - {quarter_text} {down_text} {clock_text}".strip()
                
            elif sport == 'basketball':
                quarter_text = f"Q{live_info.get('quarter', 1)}"
                clock_text = live_info.get('time_remaining', '')
                return f"[LIVE] {away_team_name} {away_score} vs {home_team_name} {home_score} - {quarter_text} {clock_text}"
                
            elif sport == 'hockey':
                period_text = f"P{live_info.get('period', 1)}"
                clock_text = live_info.get('time_remaining', '')
                return f"[LIVE] {away_team_name} {away_score} vs {home_team_name} {home_score} - {period_text} {clock_text}"
                
            else:
                return f"[LIVE] {away_team_name} {away_score} vs {home_team_name} {home_score}"
        
        # Original odds formatting for non-live games
        odds = game.get('odds', {})
        if not odds:
            # Show just the game info without odds
            local_time = self._parse_and_convert_time(game.get('start_time'))
            if local_time:
                time_str = local_time.strftime("%I:%M%p").lstrip('0')
            else:
                time_str = "TBD"
            
            # Get team names with rankings for NCAA football or basketball
            away_team_name = game.get('away_team_name', game['away_team'])
            home_team_name = game.get('home_team_name', game['home_team'])
            away_team_abbr = game.get('away_team', '')
            home_team_abbr = game.get('home_team', '')
            
            # Check if this is NCAA football or basketball and add rankings
            league_key = game.get('league')  # Use the league field from game dict
            if league_key in ['ncaa_fb', 'ncaam_basketball']:
                rankings = self._fetch_team_rankings(league_key)
                
                # Add ranking to away team name if ranked
                if away_team_abbr in rankings and rankings[away_team_abbr] > 0:
                    away_team_name = f"{rankings[away_team_abbr]}. {away_team_name}"
                
                # Add ranking to home team name if ranked
                if home_team_abbr in rankings and rankings[home_team_abbr] > 0:
                    home_team_name = f"{rankings[home_team_abbr]}. {home_team_name}"
            
            return f"[{time_str}] {away_team_name} vs {home_team_name} (No odds)"
        
        # Extract odds data
        home_team_odds = odds.get('home_team_odds', {})
        away_team_odds = odds.get('away_team_odds', {})
        
        home_spread = home_team_odds.get('spread_odds')
        away_spread = away_team_odds.get('spread_odds')
        home_ml = home_team_odds.get('money_line')
        away_ml = away_team_odds.get('money_line')
        over_under = odds.get('over_under')
        
        # Format time
        local_time = self._parse_and_convert_time(game.get('start_time'))
        if local_time:
            time_str = local_time.strftime("%I:%M %p").lstrip('0')
        else:
            time_str = "TBD"
        
        # Build odds string
        odds_parts = [f"[{time_str}]"]
        
        # Get team names with rankings for NCAA football or basketball
        away_team_name = game.get('away_team_name', game['away_team'])
        home_team_name = game.get('home_team_name', game['home_team'])
        away_team_abbr = game.get('away_team', '')
        home_team_abbr = game.get('home_team', '')
        
        # Check if this is NCAA football or basketball and add rankings
        league_key = game.get('league')  # Use the league field from game dict
        if league_key in ['ncaa_fb', 'ncaam_basketball']:
            rankings = self._fetch_team_rankings(league_key)
            
            # Add ranking to away team name if ranked
            if away_team_abbr in rankings and rankings[away_team_abbr] > 0:
                away_team_name = f"{rankings[away_team_abbr]}. {away_team_name}"
            
            # Add ranking to home team name if ranked
            if home_team_abbr in rankings and rankings[home_team_abbr] > 0:
                home_team_name = f"{rankings[home_team_abbr]}. {home_team_name}"
        
        # Add away team and odds
        odds_parts.append(away_team_name)
        if away_spread is not None:
            spread_str = f"{away_spread:+.1f}" if away_spread > 0 else f"{away_spread:.1f}"
            odds_parts.append(spread_str)
        if away_ml is not None:
            ml_str = f"ML {away_ml:+d}" if away_ml > 0 else f"ML {away_ml}"
            odds_parts.append(ml_str)
        
        odds_parts.append("vs")
        
        # Add home team and odds
        odds_parts.append(home_team_name)
        if home_spread is not None:
            spread_str = f"{home_spread:+.1f}" if home_spread > 0 else f"{home_spread:.1f}"
            odds_parts.append(spread_str)
        if home_ml is not None:
            ml_str = f"ML {home_ml:+d}" if home_ml > 0 else f"ML {home_ml}"
            odds_parts.append(ml_str)
        
        # Add over/under
        if over_under is not None:
            odds_parts.append(f"O/U {over_under}")
        
        return " ".join(odds_parts)

    def _draw_base_indicators(self, draw: ImageDraw.Draw, bases_occupied: List[bool], center_x: int, y: int) -> None:
        """Draw base indicators on the display similar to MLB manager."""
        base_diamond_size = 8  # Match MLB manager size
        base_horiz_spacing = 8  # Reduced from 10 to 8 for tighter spacing
        base_vert_spacing = 6  # Reduced from 8 to 6 for tighter vertical spacing
        base_cluster_width = base_diamond_size + base_horiz_spacing + base_diamond_size
        base_cluster_height = base_diamond_size + base_vert_spacing + base_diamond_size
        
        # Calculate cluster dimensions and positioning
        bases_origin_x = center_x - (base_cluster_width // 2)
        overall_start_y = y - (base_cluster_height // 2)
        
        # Draw diamond-shaped bases like MLB manager
        base_color_occupied = (255, 255, 255)
        base_color_empty = (255, 255, 255)  # Outline color
        h_d = base_diamond_size // 2
        
        # 2nd Base (Top center)
        c2x = bases_origin_x + base_cluster_width // 2
        c2y = overall_start_y + h_d
        poly2 = [(c2x, overall_start_y), (c2x + h_d, c2y), (c2x, c2y + h_d), (c2x - h_d, c2y)]
        if bases_occupied[1]:
            draw.polygon(poly2, fill=base_color_occupied)
        else:
            draw.polygon(poly2, outline=base_color_empty)
        
        base_bottom_y = c2y + h_d  # Bottom Y of 2nd base diamond
        
        # 3rd Base (Bottom left)
        c3x = bases_origin_x + h_d
        c3y = base_bottom_y + base_vert_spacing + h_d
        poly3 = [(c3x, base_bottom_y + base_vert_spacing), (c3x + h_d, c3y), (c3x, c3y + h_d), (c3x - h_d, c3y)]
        if bases_occupied[2]:
            draw.polygon(poly3, fill=base_color_occupied)
        else:
            draw.polygon(poly3, outline=base_color_empty)

        # 1st Base (Bottom right)
        c1x = bases_origin_x + base_cluster_width - h_d
        c1y = base_bottom_y + base_vert_spacing + h_d
        poly1 = [(c1x, base_bottom_y + base_vert_spacing), (c1x + h_d, c1y), (c1x, c1y + h_d), (c1x - h_d, c1y)]
        if bases_occupied[0]:
            draw.polygon(poly1, fill=base_color_occupied)
        else:
            draw.polygon(poly1, outline=base_color_empty)

    def _create_game_display(self, game: Dict[str, Any]) -> Image.Image:
        """Create a display image for a game in the new format."""
        width = self.display_manager.matrix.width
        height = self.display_manager.matrix.height
        
        # Make logos use most of the display height, with a small margin
        logo_size = int(height * 1.2)
        h_padding = 4 # Use a consistent horizontal padding

        # Fonts - use custom fonts from config
        team_font = self.team_font
        odds_font = self.odds_font
        vs_font = self.team_font  # Use same font as team names for "vs."
        datetime_font = self.datetime_font

        # Get team logos (with automatic download if missing)
        # Use logo_league for downloads, fallback to canonical league if logo_league is None
        logo_league = game.get('logo_league', game['league'])
        home_logo = self._get_team_logo(logo_league, game['home_id'], game['home_team'], game['logo_dir'])
        away_logo = self._get_team_logo(logo_league, game['away_id'], game['away_team'], game['logo_dir'])
        broadcast_logo = None
        
        # Enhanced broadcast logo debugging
        if self.show_channel_logos:
            broadcast_names = game.get('broadcast_info', [])  # This is now a list
            logger.info(f"Game {game.get('id')}: Raw broadcast info from API: {broadcast_names}")
            logger.info(f"Game {game.get('id')}: show_channel_logos setting: {self.show_channel_logos}")
            
            if broadcast_names:
                logo_name = None
                # Sort keys by length, descending, to match more specific names first (e.g., "ESPNEWS" before "ESPN")
                sorted_keys = sorted(self.BROADCAST_LOGO_MAP.keys(), key=len, reverse=True)
                logger.debug(f"Game {game.get('id')}: Available broadcast logo keys: {sorted_keys}")

                for b_name in broadcast_names:
                    logger.debug(f"Game {game.get('id')}: Checking broadcast name: '{b_name}'")
                    for key in sorted_keys:
                        if key in b_name:
                            logo_name = self.BROADCAST_LOGO_MAP[key]
                            logger.info(f"Game {game.get('id')}: Matched '{key}' to logo '{logo_name}' for broadcast '{b_name}'")
                            break  # Found the best match for this b_name
                    if logo_name:
                        break  # Found a logo, stop searching through broadcast list

                logger.info(f"Game {game.get('id')}: Final mapped logo name: '{logo_name}' from broadcast names: {broadcast_names}")
                if logo_name:
                    # Resolve path relative to project root
                    logo_path = self.project_root / "assets" / "broadcast_logos" / f"{logo_name}.png"
                    broadcast_logo = self.convert_image(logo_path)
                    if broadcast_logo:
                        logger.info(f"Game {game.get('id')}: Successfully loaded broadcast logo for '{logo_name}' - Size: {broadcast_logo.size}")
                    else:
                        logger.warning(f"Game {game.get('id')}: Failed to load broadcast logo for '{logo_name}'")
                        # Check if the file exists
                        logger.warning(f"Game {game.get('id')}: Logo file exists: {logo_path.exists()}")
                else:
                    logger.warning(f"Game {game.get('id')}: No mapping found for broadcast names {broadcast_names} in BROADCAST_LOGO_MAP")
            else:
                logger.info(f"Game {game.get('id')}: No broadcast info available.")

        if home_logo:
            home_logo = home_logo.resize((logo_size, logo_size), Image.Resampling.LANCZOS)
        if away_logo:
            away_logo = away_logo.resize((logo_size, logo_size), Image.Resampling.LANCZOS)
        
        broadcast_logo_col_width = 0
        if broadcast_logo:
            # Standardize broadcast logo size to be smaller and more consistent
            # Use configurable height ratio that's smaller than the display height
            b_logo_h = int(height * self.broadcast_logo_height_ratio)
            # Maintain aspect ratio while fitting within the height constraint
            ratio = b_logo_h / broadcast_logo.height
            b_logo_w = int(broadcast_logo.width * ratio)
            
            # Ensure the width doesn't get too wide - cap it at configurable max width ratio
            max_width = int(width * self.broadcast_logo_max_width_ratio)
            if b_logo_w > max_width:
                ratio = max_width / broadcast_logo.width
                b_logo_w = max_width
                b_logo_h = int(broadcast_logo.height * ratio)
            
            broadcast_logo = broadcast_logo.resize((b_logo_w, b_logo_h), Image.Resampling.LANCZOS)
            broadcast_logo_col_width = b_logo_w
            logger.info(f"Game {game.get('id')}: Resized broadcast logo to {broadcast_logo.size}, column width: {broadcast_logo_col_width}")

        # Format date and time into 3 parts
        local_time = self._parse_and_convert_time(game.get('start_time'))
        
        # Check if this is a live game
        is_live = game.get('status_state') == 'in'
        live_info = game.get('live_info')
        
        if is_live and live_info:
            # Show live game information instead of date/time
            sport = None
            league_key = game.get('league')
            if league_key and league_key in self.league_configs:
                sport = self.league_configs[league_key].get('sport')
            
            if sport == 'baseball':
                # For baseball, we'll use graphical base indicators instead of text
                # Don't show any text for bases - the graphical display will replace this section
                away_odds_text = ""
                home_odds_text = ""
                
                # Store bases data for later drawing
                self._bases_data = live_info.get('bases_occupied', [False, False, False])
                
                # Set datetime text for baseball live games
                inning_half_indicator = "▲" if live_info.get('inning_half') == 'top' else "▼"
                inning_text = f"{inning_half_indicator}{live_info.get('inning', 1)}"
                count_text = f"{live_info.get('balls', 0)}-{live_info.get('strikes', 0)}"
                outs_count = live_info.get('outs', 0)
                outs_text = f"{outs_count} out" if outs_count == 1 else f"{outs_count} outs"
                
                day_text = inning_text
                date_text = count_text
                time_text = outs_text
            elif sport == 'football':
                # Football: Show quarter and down/distance
                quarter_text = f"Q{live_info.get('quarter', 1)}"
                # Validate down and distance for odds ticker display
                down = live_info.get('down')
                distance = live_info.get('distance')
                if (down is not None and isinstance(down, int) and 1 <= down <= 4 and 
                    distance is not None and isinstance(distance, int) and distance >= 0):
                    down_text = f"{down}&{distance}"
                else:
                    down_text = ""  # Don't show invalid down/distance
                clock_text = live_info.get('clock', '')
                
                day_text = quarter_text
                date_text = down_text
                time_text = clock_text
                
            elif sport == 'basketball':
                # Basketball: Show quarter, time remaining, and LIVE indicator
                quarter_text = f"Q{live_info.get('quarter', 1)}"
                clock_text = live_info.get('time_remaining', '')

                day_text = quarter_text
                date_text = clock_text
                time_text = "LIVE"  # Clear indicator instead of empty possession
                
            elif sport == 'hockey':
                # Hockey: Show period and time remaining
                period_text = f"P{live_info.get('period', 1)}"
                clock_text = live_info.get('time_remaining', '')
                power_play_text = "PP" if live_info.get('power_play') else ""
                
                day_text = period_text
                date_text = clock_text
                time_text = power_play_text
                
            elif sport == 'soccer':
                # Soccer: Show period and time remaining
                period_text = f"P{live_info.get('period', 1)}"
                clock_text = live_info.get('time_remaining', '')
                extra_time_text = "+" if live_info.get('extra_time') else ""
                
                day_text = period_text
                date_text = clock_text
                time_text = extra_time_text
                
            else:
                # Fallback: Show generic live info
                day_text = "LIVE"
                date_text = f"{live_info.get('home_score', 0)}-{live_info.get('away_score', 0)}"
                time_text = live_info.get('clock', '')
        else:
            # Show regular date/time for non-live games
            if local_time:
                # Capitalize full day name, e.g., 'Tuesday'
                day_text = local_time.strftime("%A")
                date_text = local_time.strftime("%-m/%d")
                time_text = local_time.strftime("%I:%M%p").lstrip('0')
            else:
                # Fallback if time parsing failed
                day_text = "TBD"
                date_text = "TBD"
                time_text = "TBD"
        
        # Datetime column width
        temp_draw = ImageDraw.Draw(Image.new('RGB', (1, 1)))
        day_width = int(temp_draw.textlength(day_text, font=datetime_font))
        date_width = int(temp_draw.textlength(date_text, font=datetime_font))
        time_width = int(temp_draw.textlength(time_text, font=datetime_font))
        datetime_col_width = max(day_width, date_width, time_width)

        # "vs." text
        vs_text = "vs."
        vs_width = int(temp_draw.textlength(vs_text, font=vs_font))

        # Team and record text with rankings
        away_team_name = game.get('away_team_name', game.get('away_team', 'N/A'))
        home_team_name = game.get('home_team_name', game.get('home_team', 'N/A'))
        away_team_abbr = game.get('away_team', '')
        home_team_abbr = game.get('home_team', '')
        
        # Check if this is NCAA football or basketball and fetch rankings
        league_key = game.get('league')  # Use the league field from game dict
        tournament_round = game.get('tournament_round', '')

        # Tournament seeds override AP rankings display during March Madness
        # ncaaw_basketball included for forward-compatibility when women's odds are added
        if (league_key in ('ncaam_basketball', 'ncaaw_basketball') and
                self.show_seeds_in_tournament and tournament_round):
            away_seed = game.get('away_seed', 0)
            home_seed = game.get('home_seed', 0)
            if away_seed > 0:
                away_team_name = f"({away_seed}) {away_team_name}"
            if home_seed > 0:
                home_team_name = f"({home_seed}) {home_team_name}"
        elif league_key in ['ncaa_fb', 'ncaam_basketball']:
            rankings = self._fetch_team_rankings(league_key)

            # Add ranking to away team name if ranked
            if away_team_abbr in rankings and rankings[away_team_abbr] > 0:
                away_team_name = f"{rankings[away_team_abbr]}. {away_team_name}"

            # Add ranking to home team name if ranked
            if home_team_abbr in rankings and rankings[home_team_abbr] > 0:
                home_team_name = f"{rankings[home_team_abbr]}. {home_team_name}"
        
        away_team_text = f"{away_team_name} ({game.get('away_record', '') or 'N/A'})"
        home_team_text = f"{home_team_name} ({game.get('home_record', '') or 'N/A'})"
        
        # For live games, show scores instead of records
        if is_live and live_info:
            away_score = live_info.get('away_score', 0)
            home_score = live_info.get('home_score', 0)
            away_team_text = f"{away_team_name}:{away_score} "
            home_team_text = f"{home_team_name}:{home_score} "
        
        away_team_width = int(temp_draw.textlength(away_team_text, font=team_font))
        home_team_width = int(temp_draw.textlength(home_team_text, font=team_font))
        team_info_width = max(away_team_width, home_team_width)
        
        # Odds text
        odds = game.get('odds') or {}
        home_team_odds = odds.get('home_team_odds', {})
        away_team_odds = odds.get('away_team_odds', {})
        
        # Determine the favorite and get the spread
        home_spread = home_team_odds.get('spread_odds')
        away_spread = away_team_odds.get('spread_odds')
        
        # Fallback to top-level spread from odds_manager
        top_level_spread = odds.get('spread')
        if top_level_spread is not None:
            if home_spread is None or home_spread == 0.0:
                home_spread = top_level_spread
            if away_spread is None:
                away_spread = -top_level_spread

        # Check for valid spread values before comparing
        home_favored = isinstance(home_spread, (int, float)) and home_spread < 0
        away_favored = isinstance(away_spread, (int, float)) and away_spread < 0

        over_under = odds.get('over_under')
        
        away_odds_text = ""
        home_odds_text = ""
        
        # For live games, show live status instead of odds
        if is_live and live_info:
            sport = None
            league_key = game.get('league')
            if league_key and league_key in self.league_configs:
                sport = self.league_configs[league_key].get('sport')
            
            if sport == 'baseball':
                # Show bases occupied for baseball
                bases = live_info.get('bases_occupied', [False, False, False])
                bases_text = ""
                if bases[0]: bases_text += "1B"
                if bases[1]: bases_text += "2B"
                if bases[2]: bases_text += "3B"
                if not bases_text: bases_text = "Empty"
                
                away_odds_text = f"Bases: {bases_text}"
                home_odds_text = f"Count: {live_info.get('balls', 0)}-{live_info.get('strikes', 0)}"
                
            elif sport == 'football':
                # Show possession and yard line for football
                possession = live_info.get('possession', '')
                yard_line = live_info.get('yard_line', 0)
                
                away_odds_text = f"Ball: {possession}"
                home_odds_text = f"Yard: {yard_line}"
                
            elif sport == 'basketball':
                # Basketball: Show score differential or just LIVE indicator
                # Safely convert scores to int (API may return strings)
                try:
                    home_score = int(live_info.get('home_score', 0) or 0)
                except (ValueError, TypeError):
                    home_score = 0
                try:
                    away_score = int(live_info.get('away_score', 0) or 0)
                except (ValueError, TypeError):
                    away_score = 0
                diff = home_score - away_score
                if diff > 0:
                    away_odds_text = f"HOME +{diff}"
                elif diff < 0:
                    away_odds_text = f"AWAY +{abs(diff)}"
                else:
                    away_odds_text = "TIED"
                home_odds_text = "LIVE"

            elif sport == 'hockey':
                # Hockey: Show power play status and score differential
                power_play = live_info.get('power_play', False)
                # Safely convert scores to int (API may return strings)
                try:
                    home_score = int(live_info.get('home_score', 0) or 0)
                except (ValueError, TypeError):
                    home_score = 0
                try:
                    away_score = int(live_info.get('away_score', 0) or 0)
                except (ValueError, TypeError):
                    away_score = 0
                diff = home_score - away_score
                if diff > 0:
                    score_text = f"HOME +{diff}"
                elif diff < 0:
                    score_text = f"AWAY +{abs(diff)}"
                else:
                    score_text = "TIED"

                away_odds_text = "PP" if power_play else score_text
                home_odds_text = "LIVE"
                
            else:
                # Generic live status
                away_odds_text = "LIVE"
                home_odds_text = live_info.get('clock', '')
        else:
            # Show odds for non-live games
            # Simplified odds placement logic
            if home_favored:
                home_odds_text = f"{home_spread}"
                if over_under:
                    away_odds_text = f"O/U {over_under}"
            elif away_favored:
                away_odds_text = f"{away_spread}"
                if over_under:
                    home_odds_text = f"O/U {over_under}"
            elif over_under:
                home_odds_text = f"O/U {over_under}"
        
        away_odds_width = int(temp_draw.textlength(away_odds_text, font=odds_font))
        home_odds_width = int(temp_draw.textlength(home_odds_text, font=odds_font))
        odds_width = max(away_odds_width, home_odds_width)
        
        # For baseball live games, optimize width for graphical bases
        is_baseball_live = False
        if is_live and live_info and hasattr(self, '_bases_data'):
            sport = None
            league_key = game.get('league')
            if league_key and league_key in self.league_configs:
                sport = self.league_configs[league_key].get('sport')
            
            if sport == 'baseball':
                is_baseball_live = True
                # Use a more compact width for baseball games to minimize dead space
                # The bases graphic only needs about 24px width, so we can be more efficient
                min_bases_width = 24  # Reduced from 30 to minimize dead space
                odds_width = max(odds_width, min_bases_width)

        # --- Calculate total width ---
        # Start with the sum of all visible components and consistent padding
        total_width = (logo_size + h_padding + 
                       vs_width + h_padding + 
                       logo_size + h_padding +
                       team_info_width + h_padding + 
                       odds_width + h_padding + 
                       datetime_col_width + h_padding) # Always add padding at the end
        
        # Add width for the broadcast logo if it exists
        if broadcast_logo:
            total_width += broadcast_logo_col_width + h_padding  # Add padding after broadcast logo
        
        logger.info(f"Game {game.get('id')}: Total width calculation - logo_size: {logo_size}, vs_width: {vs_width}, team_info_width: {team_info_width}, odds_width: {odds_width}, datetime_col_width: {datetime_col_width}, broadcast_logo_col_width: {broadcast_logo_col_width}, total_width: {total_width}")

        # --- Create final image ---
        image = Image.new('RGB', (int(total_width), height), color=(0, 0, 0))
        draw = ImageDraw.Draw(image)

        # --- Draw elements ---
        current_x = 0

        # Away Logo
        if away_logo:
            y_pos = (height - logo_size) // 2  # Center the logo vertically
            image.paste(away_logo, (current_x, y_pos), away_logo if away_logo.mode == 'RGBA' else None)
        current_x += logo_size + h_padding

        # "vs."
        y_pos = (height - vs_font.size) // 2 if hasattr(vs_font, 'size') else (height - 8) // 2 # Added fallback for default font
        
        # Use red color for live game "vs." text to make it stand out
        vs_color = (255, 255, 255)  # White for regular games
        if is_live and live_info:
            vs_color = (255, 0, 0)  # Red for live games
        
        draw.text((current_x, y_pos), vs_text, font=vs_font, fill=vs_color)
        current_x += vs_width + h_padding

        # Home Logo
        if home_logo:
            y_pos = (height - logo_size) // 2  # Center the logo vertically
            image.paste(home_logo, (current_x, y_pos), home_logo if home_logo.mode == 'RGBA' else None)
        current_x += logo_size + h_padding

        # Team Info (stacked)
        team_font_height = team_font.size if hasattr(team_font, 'size') else 8
        away_y = 2
        home_y = height - team_font_height - 2
        
        # Use red color for live game scores to make them stand out
        team_color = (255, 255, 255)  # White for regular team info
        if is_live and live_info:
            team_color = (255, 0, 0)  # Red for live games
        
        draw.text((current_x, away_y), away_team_text, font=team_font, fill=team_color)
        draw.text((current_x, home_y), home_team_text, font=team_font, fill=team_color)
        current_x += team_info_width + h_padding

        # Odds (stacked) - Skip text for baseball live games, draw bases instead
        odds_font_height = odds_font.size if hasattr(odds_font, 'size') else 8
        odds_y_away = 2
        odds_y_home = height - odds_font_height - 2
        
        # Use a consistent color for all odds text
        odds_color = (0, 255, 0) # Green
        
        # Use red color for live game information to make it stand out
        if is_live and live_info:
            odds_color = (255, 0, 0)  # Red for live games

        # Draw odds content based on game type
        if is_baseball_live:
            # Draw graphical bases instead of text
            # Position bases closer to team names (left side of odds column) for better spacing
            bases_x = current_x + 12  # Position at left side, offset by half cluster width (24/2 = 12)
            # Shift bases down a bit more for better positioning
            bases_y = (height // 2) + 2  # Move down 2 pixels from center
            
            # Ensure the bases don't go off the edge of the image
            base_diamond_size = 8  # Total size of the diamond
            base_cluster_width = 24  # Width of the base cluster (8 + 8 + 8) with tighter spacing
            if bases_x - (base_cluster_width // 2) >= 0 and bases_x + (base_cluster_width // 2) <= image.width:
                # Draw the base indicators
                self._draw_base_indicators(draw, self._bases_data, bases_x, bases_y)
            
            # Clear the bases data after drawing
            delattr(self, '_bases_data')
        else:
            # Draw regular odds text for non-baseball games
            draw.text((current_x, odds_y_away), away_odds_text, font=odds_font, fill=odds_color)
            draw.text((current_x, odds_y_home), home_odds_text, font=odds_font, fill=odds_color)
        
        # Dynamic spacing: Use reduced padding for baseball games to minimize dead space
        if is_baseball_live:
            # Use minimal padding since bases are positioned at left of column
            current_x += odds_width + (h_padding // 3)  # Use 1/3 padding for baseball games
        else:
            current_x += odds_width + h_padding
        
        # Datetime (stacked, 3 rows) - Center justified
        datetime_font_height = datetime_font.size if hasattr(datetime_font, 'size') else 6
        
        # Calculate available height for the three text lines
        total_text_height = (3 * datetime_font_height) + 4 # 2px padding between lines
        
        # Center the block of text vertically
        dt_start_y = (height - total_text_height) // 2

        day_y = dt_start_y
        date_y = day_y + datetime_font_height + 2
        time_y = date_y + datetime_font_height + 2

        # Center justify each line of text within the datetime column
        day_text_width = int(temp_draw.textlength(day_text, font=datetime_font))
        date_text_width = int(temp_draw.textlength(date_text, font=datetime_font))
        time_text_width = int(temp_draw.textlength(time_text, font=datetime_font))

        day_x = current_x + (datetime_col_width - day_text_width) // 2
        date_x = current_x + (datetime_col_width - date_text_width) // 2
        time_x = current_x + (datetime_col_width - time_text_width) // 2

        # Use red color for live game information to make it stand out
        datetime_color = (255, 255, 255)  # White for regular date/time
        if is_live and live_info:
            datetime_color = (255, 0, 0)  # Red for live games

        draw.text((day_x, day_y), day_text, font=datetime_font, fill=datetime_color)
        draw.text((date_x, date_y), date_text, font=datetime_font, fill=datetime_color)
        draw.text((time_x, time_y), time_text, font=datetime_font, fill=datetime_color)
        current_x += datetime_col_width + h_padding # Add padding after datetime

        if broadcast_logo:
            # Position the broadcast logo in its own column
            logo_y = (height - broadcast_logo.height) // 2
            logger.info(f"Game {game.get('id')}: Pasting broadcast logo at ({int(current_x)}, {logo_y})")
            logger.info(f"Game {game.get('id')}: Broadcast logo size: {broadcast_logo.size}, image total width: {image.width}")
            image.paste(broadcast_logo, (int(current_x), logo_y), broadcast_logo if broadcast_logo.mode == 'RGBA' else None)
            logger.info(f"Game {game.get('id')}: Successfully pasted broadcast logo")
        else:
            logger.info(f"Game {game.get('id')}: No broadcast logo to paste")

        return image

    def _create_ticker_image(self):
        """Create a single wide image containing all game tickers using ScrollHelper."""
        logger.debug("Entering _create_ticker_image method")
        logger.debug(f"Number of games in games_data: {len(self.games_data) if self.games_data else 0}")
        
        if not self.games_data:
            logger.warning("No games data available, cannot create ticker image.")
            self.ticker_image = None
            self.scroll_helper.clear_cache()
            return

        logger.debug(f"Creating ticker image for {len(self.games_data)} games.")
        game_images = [self._create_game_display(game) for game in self.games_data]
        logger.debug(f"Created {len(game_images)} game images")
        
        if not game_images:
            logger.warning("Failed to create any game images.")
            self.ticker_image = None
            self.scroll_helper.clear_cache()
            return

        gap_width = 24  # Gap between games
        height = self.display_manager.matrix.height
        
        # Use ScrollHelper to create the scrolling image
        # ScrollHelper automatically adds display_width padding at the start
        self.ticker_image = self.scroll_helper.create_scrolling_image(
            content_items=game_images,
            item_gap=gap_width,
            element_gap=0  # No gap within items
        )
        
        # Add white vertical bars between games for visual separation
        # ScrollHelper places items with gaps, so we need to find where to add bars
        display_width = self.display_manager.matrix.width
        current_x = display_width  # Start after initial padding
        
        for idx, img in enumerate(game_images):
            current_x += img.width
            # Add white bar in the middle of the gap (except after last game)
            if idx < len(game_images) - 1:
                bar_x = current_x + gap_width // 2
                # Use ImageDraw for more efficient drawing
                draw = ImageDraw.Draw(self.ticker_image)
                draw.line([(bar_x, 0), (bar_x, height - 1)], fill=(255, 255, 255), width=1)
            current_x += gap_width
        
        # Update ScrollHelper's cached image and array to include the white bars
        # This ensures the bars are visible when scrolling
        self.scroll_helper.cached_image = self.ticker_image
        self.scroll_helper.cached_array = np.array(self.ticker_image)
        
        # Store reference for compatibility
        self.total_scroll_width = self.scroll_helper.total_scroll_width
        
        # Get dynamic duration from ScrollHelper
        self.dynamic_duration = self.scroll_helper.get_dynamic_duration()
        
        logger.debug(f"Odds ticker image creation:")
        logger.debug(f"  Display width: {display_width}px")
        logger.debug(f"  Content width: {self.total_scroll_width}px")
        logger.debug(f"  Total image width: {self.ticker_image.width}px")
        logger.debug(f"  Number of games: {len(game_images)}")
        logger.debug(f"  Gap width: {gap_width}px")
        logger.debug(f"  Dynamic duration: {self.dynamic_duration}s")

    def _draw_text_with_outline(self, draw: ImageDraw.Draw, text: str, position: tuple, font: ImageFont.FreeTypeFont, 
                               fill: tuple = (255, 255, 255), outline_color: tuple = (0, 0, 0)) -> None:
        """Draw text with a black outline for better readability."""
        x, y = position
        # Draw outline
        for dx, dy in [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]:
            draw.text((x + dx, y + dy), text, font=font, fill=outline_color)
        # Draw main text
        draw.text((x, y), text, font=font, fill=fill)

    # Dynamic duration calculation is now handled by ScrollHelper

    def get_dynamic_duration(self) -> int:
        """Get the calculated dynamic duration for display.

        Returns cached duration during active scrolling to prevent race conditions.
        Only fetches new data when not actively scrolling.
        """
        current_time = time.time()

        # Return cached duration if scrolling is active and cache is fresh (5 sec)
        if self._cached_dynamic_duration is not None:
            cache_age = current_time - self._duration_cache_time
            is_scrolling = hasattr(self, 'scroll_helper') and self.scroll_helper.scroll_position > 0
            if cache_age < 5.0 and is_scrolling:
                logger.debug(f"Returning cached duration: {self._cached_dynamic_duration}s (cache age: {cache_age:.1f}s)")
                return self._cached_dynamic_duration

        # If we don't have a valid dynamic duration yet (total_scroll_width is 0),
        # try to update the data first, but only if not actively scrolling
        if self.total_scroll_width == 0 and self.is_enabled:
            is_scrolling = hasattr(self, 'scroll_helper') and self.scroll_helper.scroll_position > 0
            if not is_scrolling:
                logger.debug("get_dynamic_duration called but total_scroll_width is 0, attempting update...")
                try:
                    # Use lock to prevent concurrent modifications
                    with self._update_lock:
                        # Force an update to get the data and calculate proper duration
                        self.games_data = self._fetch_upcoming_games()
                        self.scroll_helper.reset_scroll()
                        self.current_game_index = 0
                        self._create_ticker_image()
                        logger.debug(f"Force update completed, total_scroll_width: {self.total_scroll_width}px")
                except Exception as e:
                    logger.exception(f"Error updating odds ticker for dynamic duration: {e}")

        # Cache the duration
        self._cached_dynamic_duration = self.dynamic_duration
        self._duration_cache_time = current_time

        logger.debug(f"get_dynamic_duration called, returning: {self.dynamic_duration}s")
        return self.dynamic_duration

    def supports_dynamic_duration(self) -> bool:
        """Check if dynamic duration is enabled for this plugin."""
        if not self.is_enabled:
            return False
        return self.dynamic_duration_enabled

    def is_cycle_complete(self) -> bool:
        """
        Indicate whether the plugin has completed a full display cycle.

        For scrolling content, the cycle is complete when:
        - Dynamic duration is enabled AND elapsed time exceeds dynamic duration
        - OR scroll is complete (all content has been shown) when loop=False

        Returns:
            True if the cycle is complete, False otherwise
        """
        # If dynamic duration is not enabled, always return True (use fixed duration)
        if not self.supports_dynamic_duration():
            return True

        # Check if dynamic duration has been exceeded (regardless of loop setting)
        if self._display_start_time is not None and self.dynamic_duration > 0:
            elapsed_time = time.time() - self._display_start_time
            if elapsed_time >= self.dynamic_duration:
                logger.debug(f"Cycle complete: elapsed {elapsed_time:.1f}s >= dynamic duration {self.dynamic_duration}s")
                return True

        # If not looping, also check if scroll is complete
        if not self.loop:
            if hasattr(self, 'scroll_helper') and self.scroll_helper:
                if self.scroll_helper.is_scroll_complete():
                    logger.debug("Cycle complete: scroll finished (non-looping mode)")
                    return True

        return False

    def reset_cycle_state(self) -> None:
        """
        Reset any internal counters/state related to cycle tracking.
        
        Called by the display controller before beginning a new dynamic-duration
        session. Resets the scroll position and state.
        """
        super().reset_cycle_state()
        
        # Reset scroll helper state
        if hasattr(self, 'scroll_helper') and self.scroll_helper:
            self.scroll_helper.reset_scroll()
            logger.debug("Reset scroll helper state for new cycle")
        
        # Reset any plugin-specific cycle tracking
        self._end_reached_logged = False

    def on_config_change(self, new_config: Dict[str, Any]) -> None:
        """
        Handle configuration changes, particularly for dynamic duration settings.

        Args:
            new_config: The new plugin configuration dictionary
        """
        # Update the plugin's config reference
        old_config = self.config.copy() if self.config else {}
        self.config = new_config
        self.odds_ticker_config = new_config

        # Get nested config sections (support both old flat and new nested structure)
        display_options = new_config.get('display_options', {})
        old_display_options = old_config.get('display_options', {})

        # Check if dynamic duration settings changed
        old_dynamic = self._get_config_value(old_display_options, 'dynamic_duration', True, old_config)
        new_dynamic = self._get_config_value(display_options, 'dynamic_duration', True, new_config)

        if isinstance(old_dynamic, dict):
            old_enabled = old_dynamic.get('enabled', True)
        else:
            old_enabled = old_dynamic

        if isinstance(new_dynamic, dict):
            new_enabled = new_dynamic.get('enabled', True)
        else:
            new_enabled = new_dynamic

        if old_enabled != new_enabled:
            self.logger.info(
                "Dynamic duration %s for odds-ticker plugin",
                "enabled" if new_enabled else "disabled"
            )

        # Update tournament seed display setting
        plugin_leagues = new_config.get('leagues', {})
        ncaam_config = plugin_leagues.get('ncaam_basketball', {})
        self.show_seeds_in_tournament = ncaam_config.get('show_seeds_in_tournament', True)

        # Update dynamic duration settings from config (support both old and new structure)
        self.dynamic_duration_enabled = self._get_config_value(display_options, 'dynamic_duration', True, new_config)
        if isinstance(self.dynamic_duration_enabled, dict):
            self.dynamic_duration_enabled = self.dynamic_duration_enabled.get('enabled', True)

        self.min_duration = self._get_config_value(display_options, 'min_duration', 30, new_config)
        self.max_duration = self._get_config_value(display_options, 'max_duration', 300, new_config)
        self.duration_buffer = self._get_config_value(display_options, 'duration_buffer', 0.1, new_config)
        
        # Update ScrollHelper with new settings
        if hasattr(self, 'scroll_helper') and self.scroll_helper:
            self.scroll_helper.set_dynamic_duration_settings(
                enabled=self.dynamic_duration_enabled,
                min_duration=self.min_duration,
                max_duration=self.max_duration,
                buffer=self.duration_buffer
            )
            self.logger.debug(
                "Updated ScrollHelper dynamic duration settings: enabled=%s, min=%ds, max=%ds, buffer=%.1f%%",
                self.dynamic_duration_enabled,
                self.min_duration,
                self.max_duration,
                self.duration_buffer * 100
            )

        # Update scroll speed and delay settings
        display_config = new_config.get('display', {})

        # Read new scroll settings (support both old and new config structure)
        if display_options and ('scroll_speed' in display_options or 'scroll_delay' in display_options):
            new_scroll_speed = display_options.get('scroll_speed', self.scroll_speed)
            new_scroll_delay = display_options.get('scroll_delay', self.scroll_delay)
        elif display_config and ('scroll_speed' in display_config or 'scroll_delay' in display_config):
            new_scroll_speed = display_config.get('scroll_speed', self.scroll_speed)
            new_scroll_delay = display_config.get('scroll_delay', self.scroll_delay)
        else:
            new_scroll_speed = new_config.get('scroll_speed', self.scroll_speed)
            new_scroll_delay = new_config.get('scroll_delay', self.scroll_delay)

        # Update scroll speed if changed
        if new_scroll_speed != self.scroll_speed:
            self.set_scroll_speed(new_scroll_speed)

        # Update scroll delay if changed
        if new_scroll_delay != self.scroll_delay:
            self.set_scroll_delay(new_scroll_delay)

        # Update target_fps
        new_target_fps = self._get_config_value(display_options, 'target_fps', self.target_fps, new_config)
        if new_target_fps != self.target_fps:
            self.target_fps = new_target_fps
            if hasattr(self, 'scroll_helper') and self.scroll_helper and hasattr(self.scroll_helper, 'set_target_fps'):
                self.scroll_helper.set_target_fps(self.target_fps)
            self.logger.info(f"Target FPS updated to: {self.target_fps}")

        # Update loop setting
        new_loop = self._get_config_value(display_options, 'loop', self.loop, new_config)
        if new_loop != self.loop:
            self.loop = new_loop
            self.logger.info(f"Loop setting updated to: {self.loop}")

        # Update show_channel_logos
        new_show_logos = self._get_config_value(display_options, 'show_channel_logos', self.show_channel_logos, new_config)
        if new_show_logos != self.show_channel_logos:
            self.show_channel_logos = new_show_logos
            self.logger.info(f"Show channel logos updated to: {self.show_channel_logos}")

    def update(self):
        """Update odds ticker data."""
        logger.debug("Entering update method")
        if not self.is_enabled:
            logger.debug("Odds ticker is disabled, skipping update")
            return
            
        # Check if we're currently scrolling and defer the update if so
        if hasattr(self.display_manager, 'is_currently_scrolling') and self.display_manager.is_currently_scrolling():
            logger.debug("Odds ticker is currently scrolling, deferring update")
            if hasattr(self.display_manager, 'defer_update'):
                self.display_manager.defer_update(self._perform_update, priority=1)
            return
            
        self._perform_update()

    def _has_live_games(self) -> bool:
        """Check live status via games_data first, then an independently-refreshed
        scoreboard snapshot rate-limited by _live_check_interval (not cache TTL).

        Previously this method used cache_manager.get(key, max_age=300), meaning
        once the 5-minute scoreboard cache expired (between hourly _perform_update
        calls) it returned False and the update interval stayed at 3600s — causing
        up to a ~55-minute blind spot when a game went live. The new approach uses
        a plain timestamp to refresh independently of cache TTL.
        """
        # Fast path: current games_data already knows about a live game
        if self.games_data:
            if any(game.get('status_state') == 'in' for game in self.games_data):
                return True

        # Slow path: independently check scoreboard every _live_check_interval seconds.
        current_time = time.time()
        if current_time - self._scoreboard_last_checked >= self._live_check_interval:
            self._scoreboard_last_checked = current_time  # set before loop to avoid tight retry on error
            found_live = False
            try:
                now = datetime.now(timezone.utc)
                today_str = now.strftime("%Y%m%d")

                for league_key, league_cfg in self.league_configs.items():
                    if league_key not in self.enabled_leagues:
                        continue

                    sport = league_cfg.get('sport')
                    # Soccer uses 'leagues' (plural list) instead of a single 'league' string,
                    # so get('league') returns None and the guard below skips it intentionally.
                    # Soccer scoreboards use per-league cache keys that don't map to the single
                    # scoreboard_data_{sport}_{league}_{date} pattern used here.
                    league = league_cfg.get('league')
                    if not sport or not league:
                        continue

                    # No max_age restriction — freshness is managed by _scoreboard_last_checked
                    # above; we always read whatever the scoreboard plugin last stored.
                    cache_key = f"scoreboard_data_{sport}_{league}_{today_str}"
                    cached_data = self.cache_manager.get(cache_key)

                    if cached_data:
                        events = cached_data.get('events', [])
                        for event in events:
                            status = event.get('status', {})
                            status_type = status.get('type', {})
                            if status_type.get('state') == 'in':
                                found_live = True
                                break
                    if found_live:
                        break

            except Exception as e:
                logger.debug(f"Error checking scoreboard for live games: {e}")

            self._last_scoreboard_live_status = found_live
            if found_live:
                logger.info("Live game detected via independent scoreboard check")

        return self._last_scoreboard_live_status

    def _has_games_starting_soon(self) -> bool:
        """Check if any games are starting within the next 5 minutes."""
        if not self.games_data:
            return False

        now = datetime.now(timezone.utc)
        for game in self.games_data:
            start_time = game.get('start_time')
            if start_time and isinstance(start_time, datetime):
                time_until_start = (start_time - now).total_seconds()
                # Games starting in the next 5 minutes (not already started)
                if 0 <= time_until_start <= 300:
                    return True
        return False

    def _get_current_update_interval(self) -> int:
        """Get the current update interval based on game status.

        - Live games: use live_game_update_interval (default 60s)
        - Games starting soon: use 2x live interval (default 120s) capped at 5 min
        - Otherwise: use base_update_interval (default 3600s)
        """
        if self._has_live_games():
            return self.live_game_update_interval
        elif self._has_games_starting_soon():
            # Use a moderate interval for games about to start
            return min(self.live_game_update_interval * 2, 300)
        return self.base_update_interval
    
    def _perform_update(self, preserve_scroll: bool = False):
        """Internal method to perform the actual update.

        Args:
            preserve_scroll: If True, preserve current scroll position (for live game updates).
                           If False, reset scroll to beginning (for fresh display cycles).
        """
        current_time = time.time()
        # Dynamically determine update interval based on live games
        current_interval = self._get_current_update_interval()
        if current_time - self.last_update < current_interval:
            logger.debug(f"Odds ticker update interval not reached. Next update in {current_interval - (current_time - self.last_update)} seconds (interval: {current_interval}s, live games: {self._has_live_games()})")
            return

        # Use lock to prevent concurrent modifications during live updates
        with self._update_lock:
            try:
                # Reload config settings that can change at runtime (support both old and new config structure)
                filtering = self.odds_ticker_config.get('filtering', {})
                display_options = self.odds_ticker_config.get('display_options', {})
                self.show_odds_only = filtering.get('show_odds_only', self.odds_ticker_config.get('show_odds_only', False))
                self.loop = display_options.get('loop', self.odds_ticker_config.get('loop', True))

                logger.debug("Updating odds ticker data")
                logger.debug(f"Enabled leagues: {self.enabled_leagues}")
                logger.debug(f"Show favorite teams only: {self.show_favorite_teams_only}")
                logger.debug(f"Show odds only: {self.show_odds_only}")
                logger.debug(f"Loop: {self.loop}")

                # Save scroll position if preserving
                saved_scroll_position = None
                if preserve_scroll and hasattr(self, 'scroll_helper'):
                    saved_scroll_position = self.scroll_helper.scroll_position
                    logger.debug(f"Preserving scroll position: {saved_scroll_position}")

                self.games_data = self._fetch_upcoming_games()
                self.last_update = current_time

                # Only reset scroll if not preserving and (looping is enabled or scroll hasn't completed)
                if not preserve_scroll:
                    if self.loop or not (hasattr(self, 'scroll_helper') and self.scroll_helper.is_scroll_complete()):
                        self.scroll_helper.reset_scroll()
                    self.current_game_index = 0
                    # Reset logging flags when updating data
                    self._end_reached_logged = False
                    self._insufficient_time_warning_logged = False

                self._create_ticker_image()  # Create the composite image

                # Restore scroll position if we preserved it (clamp to new image width)
                if preserve_scroll and saved_scroll_position is not None and hasattr(self, 'scroll_helper'):
                    max_scroll = max(0, self.scroll_helper.total_scroll_width)
                    self.scroll_helper.scroll_position = min(saved_scroll_position, max_scroll)
                    logger.debug(f"Restored scroll position: {self.scroll_helper.scroll_position} (max: {max_scroll})")

                # Log update interval status
                next_interval = self._get_current_update_interval()
                if self.games_data:
                    live_count = sum(1 for game in self.games_data if game.get('status_state') == 'in')
                    logger.info(f"Updated odds ticker with {len(self.games_data)} games ({live_count} live). Next update in {next_interval}s")
                    for i, game in enumerate(self.games_data[:3]):  # Log first 3 games
                        status = "LIVE" if game.get('status_state') == 'in' else game.get('status', 'scheduled')
                        logger.info(f"Game {i+1}: {game['away_team']} @ {game['home_team']} - {status}")
                else:
                    logger.warning("No games found for odds ticker")

            except Exception as e:
                logger.error(f"Error updating odds ticker: {e}", exc_info=True)
                logger.warning(f"Odds ticker update failed, games_data may be empty: {e}")

    def display(self, display_mode: str = None, force_clear: bool = False):
        """Display the odds ticker."""
        logger.debug("Entering display method")
        logger.debug(f"Odds ticker enabled: {self.is_enabled}")
        logger.debug(f"Current scroll position: {self.scroll_helper.scroll_position}")
        logger.debug(f"Ticker image width: {self.ticker_image.width if self.ticker_image else 'None'}")
        logger.debug(f"Dynamic duration: {self.dynamic_duration}s")
        
        if not self.is_enabled:
            logger.debug("Odds ticker is disabled, exiting display method.")
            return

        # Check if we need to update live game data (respects update interval internally)
        # This ensures live game scores/times are refreshed during scrolling
        current_time = time.time()
        current_interval = self._get_current_update_interval()
        if current_time - self.last_update >= current_interval:
            logger.info(f"Live game update interval reached ({current_interval}s), refreshing data...")
            # Preserve scroll position during live updates so ticker doesn't jump back
            self._perform_update(preserve_scroll=True)

        # Reset display start time when force_clear is True or when starting fresh
        if force_clear or self._display_start_time is None:
            self._display_start_time = time.time()
            logger.debug(f"Reset/initialized display start time: {self._display_start_time}")
            # Also reset scroll position for clean start
            self.scroll_helper.reset_scroll()
            # Reset the end reached logging flag
            self._end_reached_logged = False
            # Reset the insufficient time warning logging flag
            self._insufficient_time_warning_logged = False
        else:
            # Check if the display start time is too old (more than 2x the dynamic duration)
            current_time = time.time()
            elapsed_time = current_time - self._display_start_time
            if elapsed_time > (self.dynamic_duration * 2):
                logger.debug(f"Display start time is too old ({elapsed_time:.1f}s), resetting")
                self._display_start_time = current_time
                self.scroll_helper.reset_scroll()
                # Reset the end reached logging flag
                self._end_reached_logged = False
                # Reset the insufficient time warning logging flag
                self._insufficient_time_warning_logged = False
        
        logger.debug(f"Number of games in data at start of display method: {len(self.games_data)}")
        if not self.games_data:
            logger.warning("Odds ticker has no games data. Attempting to update...")
            try:
                import threading
                import queue
                
                update_queue = queue.Queue()
                
                def perform_update():
                    try:
                        self.update()
                        update_queue.put(('success', None))
                    except Exception as e:
                        update_queue.put(('error', e))
                
                # Start update in a separate thread with 10-second timeout
                update_thread = threading.Thread(target=perform_update)
                update_thread.daemon = True
                update_thread.start()
                
                try:
                    result_type, result_data = update_queue.get(timeout=10)
                    if result_type == 'error':
                        logger.error(f"Update failed: {result_data}")
                except queue.Empty:
                    logger.warning("Update timed out after 10 seconds, using fallback")
                
            except Exception as e:
                logger.error(f"Error during update: {e}")
            
            if not self.games_data:
                logger.warning("Still no games data after update. Displaying fallback message.")
                self._display_fallback_message()
                return
        
        if self.ticker_image is None:
            logger.warning("Ticker image is not available. Attempting to create it.")
            try:
                import threading
                import queue
                
                image_queue = queue.Queue()
                
                def create_image():
                    try:
                        self._create_ticker_image()
                        image_queue.put(('success', None))
                    except Exception as e:
                        image_queue.put(('error', e))
                
                # Start image creation in a separate thread with 5-second timeout
                image_thread = threading.Thread(target=create_image)
                image_thread.daemon = True
                image_thread.start()
                
                try:
                    result_type, result_data = image_queue.get(timeout=5)
                    if result_type == 'error':
                        logger.error(f"Image creation failed: {result_data}")
                except queue.Empty:
                    logger.warning("Image creation timed out after 5 seconds")
                
            except Exception as e:
                logger.error(f"Error during image creation: {e}")
            
            if self.ticker_image is None:
                logger.error("Failed to create ticker image.")
                self._display_fallback_message()
                return

        try:
            # Use ScrollHelper for scrolling functionality
            # For non-looping mode, only update scroll if not complete
            if self.loop or not self.scroll_helper.is_scroll_complete():
                # Update scroll position (handles time-based scrolling automatically)
                self.scroll_helper.update_scroll_position()
            else:
                # Non-looping and scroll complete - stop scrolling
                if not self._end_reached_logged:
                    logger.info("Odds ticker reached end - scroll complete")
                    self._end_reached_logged = True
                # Signal that scrolling has stopped
                if hasattr(self.display_manager, 'set_scrolling_state'):
                    self.display_manager.set_scrolling_state(False)
            
            # Get the visible portion of the scrolling image
            visible_image = self.scroll_helper.get_visible_portion()
            
            if visible_image is None:
                logger.warning("ScrollHelper returned None for visible portion, using fallback")
                self._display_fallback_message()
                return
            
            # Signal scrolling state
            if hasattr(self.display_manager, 'set_scrolling_state'):
                if self.loop or not self.scroll_helper.is_scroll_complete():
                    self.display_manager.set_scrolling_state(True)
                else:
                    self.display_manager.set_scrolling_state(False)
            
            # Update dynamic duration from ScrollHelper
            self.dynamic_duration = self.scroll_helper.get_dynamic_duration()
            
            # Display the visible portion (use paste like leaderboard for better performance)
            if visible_image:
                # Ensure display_manager.image exists and is the right size
                matrix_width = self.display_manager.matrix.width
                matrix_height = self.display_manager.matrix.height
                if not hasattr(self.display_manager, 'image') or self.display_manager.image is None:
                    self.display_manager.image = Image.new('RGB', (matrix_width, matrix_height), (0, 0, 0))
                elif self.display_manager.image.size != (matrix_width, matrix_height):
                    # Resize if dimensions don't match
                    self.display_manager.image = Image.new('RGB', (matrix_width, matrix_height), (0, 0, 0))
                
                # Ensure visible_image matches display size (should always be true, but verify)
                if visible_image.size == (matrix_width, matrix_height):
                    self.display_manager.image.paste(visible_image, (0, 0))
                else:
                    # Resize visible_image to match display if needed (shouldn't happen, but safety check)
                    logger.warning(f"Visible image size {visible_image.size} doesn't match display size ({matrix_width}, {matrix_height}), resizing")
                    visible_image = visible_image.resize((matrix_width, matrix_height), Image.Resampling.LANCZOS)
                    self.display_manager.image.paste(visible_image, (0, 0))
                
                self.display_manager.update_display()
            
            # Log frame rate for performance monitoring (like leaderboard does)
            self.scroll_helper.log_frame_rate()
            
        except Exception as e:
            logger.error(f"Error displaying odds ticker: {e}", exc_info=True)
            self._display_fallback_message()

    def _display_fallback_message(self):
        """Display a fallback message when no games data is available."""
        try:
            width = self.display_manager.matrix.width
            height = self.display_manager.matrix.height
            
            logger.info(f"Displaying fallback message on {width}x{height} display")
            
            # Create a simple fallback image with a brighter background
            image = Image.new('RGB', (width, height), color=(50, 50, 50))  # Dark gray instead of black
            draw = ImageDraw.Draw(image)
            
            # Draw a simple message with larger font
            message = "No odds data"
            font = self.fonts['large']  # Use large font for better visibility
            text_width = draw.textlength(message, font=font)
            text_x = (width - text_width) // 2
            text_y = (height - font.size) // 2
            
            logger.info(f"Drawing fallback message: '{message}' at position ({text_x}, {text_y})")
            
            # Draw with bright white text and black outline
            self._draw_text_with_outline(draw, message, (text_x, text_y), font, fill=(255, 255, 255), outline_color=(0, 0, 0))
            
            # Display the fallback image
            self.display_manager.image = image
            self.display_manager.draw = ImageDraw.Draw(self.display_manager.image)
            self.display_manager.update_display()
            
            logger.info("Fallback message display completed")
            
        except Exception as e:
            logger.error(f"Error displaying fallback message: {e}", exc_info=True)

    def get_display_duration(self) -> float:
        """Get display duration from config."""
        return self.get_dynamic_duration()

    def set_scroll_speed(self, speed: float) -> None:
        """Set the scroll speed (pixels per frame, 0.5-5.0)."""
        # Clamp to valid range
        self.scroll_speed = max(0.5, min(5.0, speed))
        self.logger.info(f"Scroll speed set to: {self.scroll_speed} pixels/frame")
        
        # Update ScrollHelper based on current mode
        if hasattr(self.scroll_helper, 'frame_based_scrolling') and self.scroll_helper.frame_based_scrolling:
            # Frame-based mode: set pixels per frame directly
            self.scroll_helper.set_scroll_speed(self.scroll_speed)
            # Log effective pixels per second
            pixels_per_second = self.scroll_speed / self.scroll_delay if self.scroll_delay > 0 else self.scroll_speed * 50
            self.logger.info(f"Effective scroll speed: {pixels_per_second:.1f} px/s")
        else:
            # Time-based mode: convert to pixels per second
            pixels_per_second = self.scroll_speed / self.scroll_delay if self.scroll_delay > 0 else self.scroll_speed * 20
            self.scroll_helper.set_scroll_speed(pixels_per_second)
    
    def set_scroll_delay(self, delay: float) -> None:
        """Set the scroll delay (seconds between frames, 0.001-0.1)."""
        # Clamp to valid range
        self.scroll_delay = max(0.001, min(0.1, delay))
        self.logger.info(f"Scroll delay set to: {self.scroll_delay}s")
        
        # Update ScrollHelper
        self.scroll_helper.set_scroll_delay(self.scroll_delay)
        
        # Recalculate pixels per second if in time-based mode
        if hasattr(self.scroll_helper, 'frame_based_scrolling') and self.scroll_helper.frame_based_scrolling:
            # Frame-based mode: log effective pixels per second
            pixels_per_second = self.scroll_speed / self.scroll_delay if self.scroll_delay > 0 else self.scroll_speed * 50
            self.logger.info(f"Effective scroll speed: {pixels_per_second:.1f} px/s ({self.scroll_speed} px/frame at {1.0/self.scroll_delay:.0f} FPS)")
        else:
            # Time-based mode: recalculate pixels per second
            pixels_per_second = self.scroll_speed / self.scroll_delay if self.scroll_delay > 0 else self.scroll_speed * 20
            self.scroll_helper.set_scroll_speed(pixels_per_second)
    
    def get_info(self) -> Dict[str, Any]:
        """Return plugin info for web UI."""
        info = {
            'total_games': len(self.games_data),
            'enabled_leagues': self.enabled_leagues,
            'last_update': self.last_update,
            'display_duration': self.get_display_duration(),
            'scroll_speed': self.scroll_speed,
            'show_favorite_teams_only': self.show_favorite_teams_only,
            'max_games_per_league': self.max_games_per_league,
            'dynamic_duration': self.dynamic_duration,
            'total_scroll_width': self.total_scroll_width,
            'scroll_position': self.scroll_helper.scroll_position,
            'ticker_image_width': self.ticker_image.width if self.ticker_image else 0
        }
        return info

    def cleanup(self) -> None:
        """Cleanup resources."""
        self.games_data = []
        self.ticker_image = None
        self.scroll_helper.clear_cache()
        self._end_reached_logged = False
        self._insufficient_time_warning_logged = False
        logger.info("Odds ticker plugin cleaned up")
