"""
Baseball Scoreboard Plugin for LEDMatrix - Using Existing Managers

This plugin provides MLB and NCAA Baseball scoreboard functionality by reusing
the proven, working manager classes from the LEDMatrix core project.

Display Modes:
- Switch Mode: Display one game at a time with timed transitions
- Scroll Mode: High-FPS horizontal scrolling of all games with league separators

Sequential Block Display Architecture:
This plugin implements a sequential block display approach where all games from
one league are shown before moving to the next league. This provides:

1. Predictable Display Order: MLB games show first, then NCAA Baseball games
2. Accurate Dynamic Duration: Duration calculations include all leagues
3. Scalable Design: Easy to add more leagues in the future
4. Granular Control: Support for enabling/disabling at league and mode levels

The sequential block flow:
- For a display mode (e.g., 'mlb_recent' or 'ncaa_baseball_recent'), get enabled leagues in priority order
- Show all games from the first league (MLB) until complete
- Then show all games from the next league (NCAA Baseball) until complete
- When all enabled leagues complete, the display mode cycle is complete

This replaces the previous "sticky manager" approach which prevented league rotation
and made it difficult to ensure both leagues were displayed.
"""

import logging
import time
from typing import Dict, Any, Set, Optional, Tuple, List

from PIL import ImageFont

try:
    from src.plugin_system.base_plugin import BasePlugin, VegasDisplayMode
    from src.background_data_service import get_background_service
    from src.base_odds_manager import BaseOddsManager
except ImportError:
    BasePlugin = None
    VegasDisplayMode = None
    get_background_service = None
    BaseOddsManager = None

# Import the copied manager classes
from mlb_managers import MLBLiveManager, MLBRecentManager, MLBUpcomingManager
from ncaa_baseball_managers import (
    NCAABaseballLiveManager,
    NCAABaseballRecentManager,
    NCAABaseballUpcomingManager,
)
from milb_managers import MiLBLiveManager, MiLBRecentManager, MiLBUpcomingManager

# Import scroll display components
try:
    from scroll_display import ScrollDisplayManager
    SCROLL_AVAILABLE = True
except ImportError:
    ScrollDisplayManager = None
    SCROLL_AVAILABLE = False

logger = logging.getLogger(__name__)


class BaseballScoreboardPlugin(BasePlugin if BasePlugin else object):
    """
    Baseball scoreboard plugin using existing manager classes.

    This plugin provides MLB and NCAA Baseball scoreboard functionality by
    delegating to the proven manager classes from LEDMatrix core.
    """

    def __init__(
        self,
        plugin_id: str,
        config: Dict[str, Any],
        display_manager,
        cache_manager,
        plugin_manager,
    ):
        """Initialize the baseball scoreboard plugin."""
        if BasePlugin:
            super().__init__(
                plugin_id, config, display_manager, cache_manager, plugin_manager
            )

        self.plugin_id = plugin_id
        self.config = config
        self.display_manager = display_manager
        self.cache_manager = cache_manager
        self.plugin_manager = plugin_manager

        self.logger = logger

        # Basic configuration
        self.is_enabled = config.get("enabled", True)
        # Get display dimensions from display_manager properties
        if hasattr(display_manager, 'matrix') and display_manager.matrix is not None:
            self.display_width = display_manager.matrix.width
            self.display_height = display_manager.matrix.height
        else:
            self.display_width = getattr(display_manager, "width", 128)
            self.display_height = getattr(display_manager, "height", 32)

        # League configurations (defaults come from schema via plugin_manager merge)
        # Debug: Log what config we received
        self.logger.debug(f"Baseball plugin received config keys: {list(config.keys())}")
        self.logger.debug(f"MLB config: {config.get('mlb', {})}")
        
        self.mlb_enabled = config.get("mlb", {}).get("enabled", False)
        self.milb_enabled = config.get("milb", {}).get("enabled", False)
        self.ncaa_baseball_enabled = config.get("ncaa_baseball", {}).get("enabled", False)

        self.logger.info(f"League enabled states - MLB: {self.mlb_enabled}, MiLB: {self.milb_enabled}, NCAA Baseball: {self.ncaa_baseball_enabled}")

        # League registry: maps league IDs to their configuration and managers
        # This structure makes it easy to add more leagues in the future
        # Format: {league_id: {'enabled': bool, 'priority': int, 'live_priority': bool, 'managers': {...}}}
        # The registry will be populated after managers are initialized
        self._league_registry: Dict[str, Dict[str, Any]] = {}

        # Global settings
        self.display_duration = float(config.get("display_duration", 30))
        self.game_display_duration = float(config.get("game_display_duration", 15))

        # Live priority per league
        self.mlb_live_priority = self.config.get("mlb", {}).get("live_priority", False)
        self.milb_live_priority = self.config.get("milb", {}).get("live_priority", False)
        self.ncaa_baseball_live_priority = self.config.get("ncaa_baseball", {}).get(
            "live_priority", False
        )
        
        # Display mode settings per league and game type
        self._display_mode_settings = self._parse_display_mode_settings()

        # Initialize background service if available
        self.background_service = None
        if get_background_service:
            try:
                self.background_service = get_background_service(
                    self.cache_manager, max_workers=1
                )
                self.logger.info("Background service initialized")
            except Exception as e:
                self.logger.warning(f"Could not initialize background service: {e}")

        # Initialize managers
        self._initialize_managers()
        
        # Initialize league registry after managers are created
        # This centralizes league management and makes it easy to add more leagues
        self._initialize_league_registry()
        
        # Initialize scroll display manager if available
        self._scroll_manager: Optional[ScrollDisplayManager] = None
        if SCROLL_AVAILABLE and ScrollDisplayManager:
            try:
                self._scroll_manager = ScrollDisplayManager(
                    self.display_manager,
                    self.config,
                    self.logger
                )
                self.logger.info("Scroll display manager initialized")
            except Exception as e:
                self.logger.warning(f"Could not initialize scroll display manager: {e}")
                self._scroll_manager = None
        else:
            self.logger.debug("Scroll mode not available - ScrollDisplayManager not imported")
        
        # Track current scroll state
        self._scroll_active: Dict[str, bool] = {}  # {game_type: is_active}
        self._scroll_prepared: Dict[str, bool] = {}  # {game_type: is_prepared}

        # Enable high-FPS mode for scroll display (allows 100+ FPS scrolling)
        # This signals to the display controller to use high-FPS loop (8ms = 125 FPS)
        self.enable_scrolling = self._scroll_manager is not None
        if self.enable_scrolling:
            self.logger.info("High-FPS scrolling enabled for baseball scoreboard")

        # Mode cycling
        self.current_mode_index = 0
        self.last_mode_switch = 0
        self.modes = self._get_available_modes()

        self.logger.info(
            f"Baseball scoreboard plugin initialized - {self.display_width}x{self.display_height}"
        )
        self.logger.info(
            f"MLB enabled: {self.mlb_enabled}, MiLB enabled: {self.milb_enabled}, NCAA Baseball enabled: {self.ncaa_baseball_enabled}"
        )

        # Dynamic duration tracking
        self._dynamic_cycle_seen_modes: Set[str] = set()
        self._dynamic_mode_to_manager_key: Dict[str, str] = {}
        self._dynamic_manager_progress: Dict[str, Set[str]] = {}
        self._dynamic_managers_completed: Set[str] = set()
        self._dynamic_cycle_complete = False
        # Track when single-game managers were first seen to ensure full duration
        self._single_game_manager_start_times: Dict[str, float] = {}
        # Track when each game ID was first seen to ensure full per-game duration
        # Using game IDs instead of indices prevents start time resets when game order changes
        self._game_id_start_times: Dict[str, Dict[str, float]] = {}  # {manager_key: {game_id: start_time}}
        # Track which managers were actually used for each display mode
        self._display_mode_to_managers: Dict[str, Set[str]] = {}  # {display_mode: {manager_key, ...}}
        
        # Track current display context for granular dynamic duration
        self._current_display_league: Optional[str] = None  # 'mlb' or 'ncaa_baseball'
        self._current_display_mode_type: Optional[str] = None  # 'live', 'recent', 'upcoming'
        
        # Throttle logging for has_live_content() when returning False
        self._last_live_content_false_log: float = 0.0  # Timestamp of last False log
        self._live_content_log_interval: float = 60.0  # Log False results every 60 seconds
        
        # Track last display mode to detect when we return after being away
        self._last_display_mode: Optional[str] = None  # Track previous display mode
        self._last_display_mode_time: float = 0.0  # When we last saw this mode
        self._current_active_display_mode: Optional[str] = None  # Currently active external display mode
        
        # Track current game for transition detection
        # Format: {display_mode: {'game_id': str, 'league': str, 'last_log_time': float}}
        self._current_game_tracking: Dict[str, Dict[str, Any]] = {}
        self._game_transition_log_interval: float = 1.0  # Minimum seconds between game transition logs
        
        # Track mode start times for per-mode duration enforcement
        # Format: {display_mode: start_time} (e.g., {'mlb_recent': 1234567890.0})
        # Reset when mode changes or full cycle completes
        self._mode_start_time: Dict[str, float] = {}
        
        # Note: Sticky manager tracking has been removed in favor of sequential block display
        # Sequential block display shows all games from one league before moving to the next,
        # which is simpler and more predictable than the sticky manager approach

    def _initialize_managers(self):
        """Initialize all manager instances."""
        try:
            # Create adapted configs for managers
            mlb_config = self._adapt_config_for_manager("mlb")
            milb_config = self._adapt_config_for_manager("milb")
            ncaa_baseball_config = self._adapt_config_for_manager("ncaa_baseball")

            # Initialize MLB managers if enabled
            if self.mlb_enabled:
                self.mlb_live = MLBLiveManager(
                    mlb_config, self.display_manager, self.cache_manager
                )
                self.mlb_recent = MLBRecentManager(
                    mlb_config, self.display_manager, self.cache_manager
                )
                self.mlb_upcoming = MLBUpcomingManager(
                    mlb_config, self.display_manager, self.cache_manager
                )
                self.logger.info("MLB managers initialized")

            # Initialize MiLB managers if enabled
            if self.milb_enabled:
                self.milb_live = MiLBLiveManager(
                    milb_config, self.display_manager, self.cache_manager
                )
                self.milb_recent = MiLBRecentManager(
                    milb_config, self.display_manager, self.cache_manager
                )
                self.milb_upcoming = MiLBUpcomingManager(
                    milb_config, self.display_manager, self.cache_manager
                )
                self.logger.info("MiLB managers initialized")

            # Initialize NCAA Baseball managers if enabled
            if self.ncaa_baseball_enabled:
                self.ncaa_baseball_live = NCAABaseballLiveManager(
                    ncaa_baseball_config, self.display_manager, self.cache_manager
                )
                self.ncaa_baseball_recent = NCAABaseballRecentManager(
                    ncaa_baseball_config, self.display_manager, self.cache_manager
                )
                self.ncaa_baseball_upcoming = NCAABaseballUpcomingManager(
                    ncaa_baseball_config, self.display_manager, self.cache_manager
                )
                self.logger.info("NCAA Baseball managers initialized")

        except Exception as e:
            self.logger.error(f"Error initializing managers: {e}", exc_info=True)

    def _initialize_league_registry(self) -> None:
        """
        Initialize the league registry with all available leagues.
        
        The league registry centralizes league management and makes it easy to:
        - Add new leagues in the future (just add an entry here)
        - Query enabled leagues for a mode type
        - Get managers in priority order
        - Check league completion status
        
        Registry format:
        {
            'league_id': {
                'enabled': bool,           # Whether the league is enabled
                'priority': int,           # Display priority (lower = higher priority)
                'live_priority': bool,     # Whether live priority is enabled for this league
                'managers': {
                    'live': Manager or None,
                    'recent': Manager or None,
                    'upcoming': Manager or None
                }
            }
        }
        
        This design allows the display logic to iterate through leagues in priority
        order without hardcoding league names throughout the codebase.
        """
        # MLB league entry - highest priority (1)
        # Note: We normalize league IDs to use consistent naming ('mlb', 'ncaa_baseball')
        # even though managers may use different internal identifiers
        self._league_registry['mlb'] = {
            'enabled': self.mlb_enabled,
            'priority': 1,  # Highest priority - shows first
            'live_priority': self.mlb_live_priority,
            'managers': {
                'live': getattr(self, 'mlb_live', None),
                'recent': getattr(self, 'mlb_recent', None),
                'upcoming': getattr(self, 'mlb_upcoming', None),
            }
        }
        
        # MiLB league entry - second priority (2)
        self._league_registry['milb'] = {
            'enabled': self.milb_enabled,
            'priority': 2,  # Second priority - shows after MLB
            'live_priority': self.milb_live_priority,
            'managers': {
                'live': getattr(self, 'milb_live', None),
                'recent': getattr(self, 'milb_recent', None),
                'upcoming': getattr(self, 'milb_upcoming', None),
            }
        }

        # NCAA Baseball league entry - third priority (3)
        self._league_registry['ncaa_baseball'] = {
            'enabled': self.ncaa_baseball_enabled,
            'priority': 3,  # Third priority - shows after MiLB
            'live_priority': self.ncaa_baseball_live_priority,
            'managers': {
                'live': getattr(self, 'ncaa_baseball_live', None),
                'recent': getattr(self, 'ncaa_baseball_recent', None),
                'upcoming': getattr(self, 'ncaa_baseball_upcoming', None),
            }
        }
        
        # Log registry state for debugging
        enabled_leagues = [lid for lid, data in self._league_registry.items() if data['enabled']]
        self.logger.info(
            f"League registry initialized: {len(self._league_registry)} league(s) registered, "
            f"{len(enabled_leagues)} enabled: {enabled_leagues}"
        )
        
        # Future leagues can be added here following the same pattern:
        # self._league_registry['xfl'] = {
        #     'enabled': self.config.get('xfl', {}).get('enabled', False),
        #     'priority': 3,
        #     'live_priority': self.config.get('xfl', {}).get('live_priority', False),
        #     'managers': {
        #         'live': getattr(self, 'xfl_live', None),
        #         'recent': getattr(self, 'xfl_recent', None),
        #         'upcoming': getattr(self, 'xfl_upcoming', None),
        #     }
        # }

    def _get_enabled_leagues_for_mode(self, mode_type: str) -> List[str]:
        """
        Get list of enabled leagues for a specific mode type in priority order.
        
        This method respects both league-level and mode-level disabling:
        - League must be enabled (league.enabled = True)
        - Mode must be enabled for that league (league.display_modes.show_<mode> = True)
        
        Args:
            mode_type: Mode type ('live', 'recent', or 'upcoming')
            
        Returns:
            List of league IDs in priority order (lower priority number = higher priority)
            Example: ['mlb', 'ncaa_baseball'] means MLB shows first, then NCAA Baseball
            
        This is the core method for sequential block display - it determines
        which leagues should be shown and in what order.
        """
        enabled_leagues = []
        
        # Iterate through all registered leagues
        for league_id, league_data in self._league_registry.items():
            # Check if league is enabled
            if not league_data.get('enabled', False):
                continue
            
            # Check if this mode type is enabled for this league
            # Get the league config to check display_modes settings
            league_config = self.config.get(league_id, {})
            display_modes_config = league_config.get("display_modes", {})
            
            # Check the appropriate flag based on mode type
            mode_enabled = True  # Default to enabled if not specified
            if mode_type == 'live':
                mode_enabled = display_modes_config.get("show_live", True)
            elif mode_type == 'recent':
                mode_enabled = display_modes_config.get("show_recent", True)
            elif mode_type == 'upcoming':
                mode_enabled = display_modes_config.get("show_upcoming", True)
            
            # Only include if mode is enabled for this league
            if mode_enabled:
                enabled_leagues.append(league_id)
        
        # Sort by priority (lower number = higher priority)
        enabled_leagues.sort(key=lambda lid: self._league_registry[lid].get('priority', 999))
        
        self.logger.debug(
            f"Enabled leagues for {mode_type} mode: {enabled_leagues} "
            f"(priorities: {[self._league_registry[lid].get('priority') for lid in enabled_leagues]})"
        )
        
        return enabled_leagues

    def _is_league_complete_for_mode(self, league_id: str, mode_type: str) -> bool:
        """
        Check if a league has completed showing all games for a specific mode type.
        
        This is used in sequential block display to determine when to move from
        one league to the next. A league is considered complete when all its games
        have been shown for their full duration (tracked via dynamic duration system).
        
        Args:
            league_id: League identifier ('mlb', 'ncaa_baseball', etc.)
            mode_type: Mode type ('live', 'recent', or 'upcoming')
            
        Returns:
            True if the league's manager for this mode is marked as complete,
            False otherwise
            
        The completion status is tracked in _dynamic_managers_completed set,
        using manager keys in the format: "{league_id}_{mode_type}:ManagerClass"
        """
        # Get the manager for this league and mode
        manager = self._get_league_manager_for_mode(league_id, mode_type)
        if not manager:
            # No manager means league can't be displayed, so consider it "complete"
            # (nothing to show, so we can move on)
            return True
        
        # Build the manager key that matches what's used in progress tracking
        # Format: "{league_id}_{mode_type}:ManagerClass"
        manager_key = self._build_manager_key(f"{league_id}_{mode_type}", manager)
        
        # Check if this manager is in the completed set
        is_complete = manager_key in self._dynamic_managers_completed
        
        if is_complete:
            self.logger.debug(f"League {league_id} {mode_type} is complete (manager_key: {manager_key})")
        else:
            self.logger.debug(f"League {league_id} {mode_type} is not complete (manager_key: {manager_key})")
        
        return is_complete

    def _get_league_manager_for_mode(self, league_id: str, mode_type: str):
        """
        Get the manager instance for a specific league and mode type.
        
        This is a convenience method that looks up managers from the league registry.
        It provides a single point of access for getting managers, making the code
        more maintainable and easier to extend.
        
        Args:
            league_id: League identifier ('mlb', 'ncaa_baseball', etc.)
            mode_type: Mode type ('live', 'recent', or 'upcoming')
            
        Returns:
            Manager instance if found, None otherwise
            
        The manager is retrieved from the league registry, which is populated
        during initialization. If the league or mode doesn't exist, returns None.
        """
        # Check if league exists in registry
        if league_id not in self._league_registry:
            self.logger.warning(f"League {league_id} not found in registry")
            return None
        
        # Get managers dict for this league
        managers = self._league_registry[league_id].get('managers', {})
        
        # Get the manager for this mode type
        manager = managers.get(mode_type)
        
        if manager is None:
            self.logger.debug(f"No manager found for {league_id} {mode_type}")
        
        return manager

    def _adapt_config_for_manager(self, league: str) -> Dict[str, Any]:
        """
        Adapt plugin config format to manager expected format.

        Plugin uses: mlb: {...}, milb: {...}, ncaa_baseball: {...}
        Managers expect: mlb_scoreboard: {...}, milb_scoreboard: {...}, ncaa_baseball_scoreboard: {...}
        """
        league_config = self.config.get(league, {})
        
        # Debug: Log the entire league_config to see what we're actually getting
        self.logger.debug(f"DEBUG: league_config for {league} = {league_config}")

        # Extract nested configurations
        game_limits = league_config.get("game_limits", {})
        display_options = league_config.get("display_options", {})
        filtering = league_config.get("filtering", {})
        display_modes_config = league_config.get("display_modes", {})

        manager_display_modes = {
            f"{league}_live": display_modes_config.get("show_live", True),
            f"{league}_recent": display_modes_config.get("show_recent", True),
            f"{league}_upcoming": display_modes_config.get("show_upcoming", True),
        }

        # Explicitly check if keys exist, not just if they're truthy
        # This handles False values correctly (False is a valid saved value)
        # Priority: filtering dict first (more reliable), then top-level, then default
        if "show_favorite_teams_only" in filtering:
            show_favorites_only = filtering["show_favorite_teams_only"]
        elif "show_favorite_teams_only" in league_config:
            show_favorites_only = league_config["show_favorite_teams_only"]
        elif "favorite_teams_only" in league_config:
            show_favorites_only = league_config["favorite_teams_only"]
        else:
            # Default to False if not specified (schema default is True, but we want False as default)
            show_favorites_only = False
        
        # Debug logging to diagnose config reading issues
        self.logger.debug(
            f"Config reading for {league}: "
            f"league_config.show_favorite_teams_only={league_config.get('show_favorite_teams_only', 'NOT_SET')}, "
            f"filtering.show_favorite_teams_only={filtering.get('show_favorite_teams_only', 'NOT_SET')}, "
            f"final show_favorites_only={show_favorites_only}"
        )

        # Explicitly check if key exists for show_all_live
        # Priority: filtering dict first (more reliable), then top-level, then default
        if "show_all_live" in filtering:
            show_all_live = filtering["show_all_live"]
        elif "show_all_live" in league_config:
            show_all_live = league_config["show_all_live"]
        else:
            # Default to False if not specified
            show_all_live = False
        
        # Debug logging for show_all_live
        self.logger.debug(
            f"Config reading for {league}: "
            f"league_config.show_all_live={league_config.get('show_all_live', 'NOT_SET')}, "
            f"filtering.show_all_live={filtering.get('show_all_live', 'NOT_SET')}, "
            f"final show_all_live={show_all_live}"
        )

        # Create manager config with expected structure
        manager_config = {
            f"{league}_scoreboard": {
                "enabled": league_config.get("enabled", False),
                "favorite_teams": league_config.get("favorite_teams", []),
                "display_modes": manager_display_modes,
                "recent_games_to_show": game_limits.get("recent_games_to_show", 5),
                "upcoming_games_to_show": game_limits.get("upcoming_games_to_show", 10),
                "show_records": display_options.get("show_records", False),
                "show_ranking": display_options.get("show_ranking", False),
                "show_odds": display_options.get("show_odds", False),
                "update_interval_seconds": league_config.get(
                    "update_interval_seconds", 300
                ),
                "live_update_interval": league_config.get("live_update_interval", 30),
                "live_game_duration": league_config.get("live_game_duration", 20),
                "recent_game_duration": league_config.get(
                    "recent_game_duration",
                    15  # Default per-game duration for recent games
                ),
                "upcoming_game_duration": league_config.get(
                    "upcoming_game_duration",
                    15  # Default per-game duration for upcoming games
                ),
                "live_priority": league_config.get("live_priority", False),
                "show_favorite_teams_only": show_favorites_only,
                "show_all_live": show_all_live,
                "filtering": filtering,
                "background_service": {
                    "request_timeout": 30,
                    "max_retries": 3,
                    "priority": 2,
                },
            }
        }

        # Add global config - get timezone from cache_manager's config_manager if available
        timezone_str = self.config.get("timezone")
        if not timezone_str and hasattr(self.cache_manager, 'config_manager'):
            timezone_str = self.cache_manager.config_manager.get_timezone()
        if not timezone_str:
            timezone_str = "UTC"
        
        # Get display config from main config if available
        display_config = self.config.get("display", {})
        if not display_config and hasattr(self.cache_manager, 'config_manager'):
            display_config = self.cache_manager.config_manager.get_display_config()
        
        # Get customization config from main config (shared across all leagues)
        customization_config = self.config.get("customization", {})
        
        manager_config.update(
            {
                "timezone": timezone_str,
                "display": display_config,
                "customization": customization_config,
            }
        )
        
        self.logger.debug(f"Using timezone: {timezone_str} for {league} managers")

        return manager_config
    
    def _parse_display_mode_settings(self) -> Dict[str, Dict[str, str]]:
        """
        Parse display mode settings from config.
        
        Returns:
            Dict mapping league -> game_type -> display_mode ('switch' or 'scroll')
            e.g., {'mlb': {'live': 'switch', 'recent': 'scroll', 'upcoming': 'scroll'}}
        """
        settings = {}
        
        for league in ['mlb', 'milb', 'ncaa_baseball']:
            league_config = self.config.get(league, {})
            display_modes_config = league_config.get("display_modes", {})
            
            settings[league] = {
                'live': display_modes_config.get('live_display_mode', 'switch'),
                'recent': display_modes_config.get('recent_display_mode', 'switch'),
                'upcoming': display_modes_config.get('upcoming_display_mode', 'switch'),
            }
            
            self.logger.debug(f"Display mode settings for {league}: {settings[league]}")
        
        return settings
    
    def _get_display_mode(self, league: str, game_type: str) -> str:
        """
        Get the display mode for a specific league and game type.
        
        Args:
            league: 'mlb', 'milb', or 'ncaa_baseball'
            game_type: 'live', 'recent', or 'upcoming'
            
        Returns:
            'switch' or 'scroll'
        """
        return self._display_mode_settings.get(league, {}).get(game_type, 'switch')
    
    def _should_use_scroll_mode(self, mode_type: str) -> bool:
        """
        Check if ANY enabled league should use scroll mode for this game type.
        
        This determines if we should collect games for scrolling or use switch mode.
        
        Args:
            mode_type: 'live', 'recent', or 'upcoming'
            
        Returns:
            True if at least one enabled league uses scroll mode for this game type
        """
        if self.mlb_enabled and self._get_display_mode('mlb', mode_type) == 'scroll':
            return True

        if self.milb_enabled and self._get_display_mode('milb', mode_type) == 'scroll':
            return True
        if self.ncaa_baseball_enabled and self._get_display_mode('ncaa_baseball', mode_type) == 'scroll':
            return True
        return False
    
    def _collect_games_for_scroll(
        self,
        mode_type: Optional[str] = None,
        live_priority_active: bool = False
    ) -> Tuple[List[Dict], List[str]]:
        """
        Collect all games from enabled leagues for scroll mode.

        Args:
            mode_type: Optional game type filter ('live', 'recent', 'upcoming').
                      If None, collects all game types organized by league.
            live_priority_active: If True, only include live games

        Returns:
            Tuple of (games list with league info, list of leagues included)
        """
        games = []
        leagues = []

        # Determine which mode types to collect
        if mode_type is None:
            # Collect all game types for Vegas mode
            mode_types = ['live', 'recent', 'upcoming']
        else:
            # Collect single game type for internal plugin scroll mode
            mode_types = [mode_type]

        # Collect MLB games if enabled
        if self.mlb_enabled:
            league_games = []
            for mt in mode_types:
                # Check if scroll mode is enabled for this league/mode
                if self._get_display_mode('mlb', mt) == 'scroll':
                    league_manager = self._get_manager_for_league_mode('mlb', mt)
                    if league_manager:
                        league_games_list = self._get_games_from_manager(league_manager, mt)
                        if league_games_list:
                            # Add league info and ensure status field
                            for game in league_games_list:
                                game['league'] = 'mlb'
                                # Ensure game has status dict for type determination
                                if not isinstance(game.get('status'), dict):
                                    game['status'] = {}
                                if 'state' not in game['status']:
                                    # Infer state from mode_type
                                    state_map = {'live': 'in', 'recent': 'post', 'upcoming': 'pre'}
                                    game['status']['state'] = state_map.get(mt, 'pre')
                            league_games.extend(league_games_list)
                            self.logger.debug(f"Collected {len(league_games_list)} MLB {mt} games for scroll")

            if league_games:
                games.extend(league_games)
                leagues.append('mlb')

        # Collect NCAA Baseball games if enabled

        if self.milb_enabled:
            league_games = []
            for mt in mode_types:
                # Check if scroll mode is enabled for this league/mode
                if self._get_display_mode('milb', mt) == 'scroll':
                    league_manager = self._get_manager_for_league_mode('milb', mt)
                    if league_manager:
                        league_games_list = self._get_games_from_manager(league_manager, mt)
                        if league_games_list:
                            # Add league info and ensure status field
                            for game in league_games_list:
                                game['league'] = 'milb'
                                # Ensure game has status dict for type determination
                                if not isinstance(game.get('status'), dict):
                                    game['status'] = {}
                                if 'state' not in game['status']:
                                    # Infer state from mode_type
                                    state_map = {'live': 'in', 'recent': 'post', 'upcoming': 'pre'}
                                    game['status']['state'] = state_map.get(mt, 'pre')
                            league_games.extend(league_games_list)
                            self.logger.debug(f"Collected {len(league_games_list)} MiLB {mt} games for scroll")

            if league_games:
                games.extend(league_games)
                leagues.append('milb')

        # Collect NCAA Baseball games if enabled
        if self.ncaa_baseball_enabled:
            league_games = []
            for mt in mode_types:
                # Check if scroll mode is enabled for this league/mode
                if self._get_display_mode('ncaa_baseball', mt) == 'scroll':
                    ncaa_manager = self._get_manager_for_league_mode('ncaa_baseball', mt)
                    if ncaa_manager:
                        ncaa_games = self._get_games_from_manager(ncaa_manager, mt)
                        if ncaa_games:
                            # Add league info and ensure status field
                            for game in ncaa_games:
                                game['league'] = 'ncaa_baseball'
                                # Ensure game has status dict for type determination
                                if not isinstance(game.get('status'), dict):
                                    game['status'] = {}
                                if 'state' not in game['status']:
                                    # Infer state from mode_type
                                    state_map = {'live': 'in', 'recent': 'post', 'upcoming': 'pre'}
                                    game['status']['state'] = state_map.get(mt, 'pre')
                            league_games.extend(ncaa_games)
                            self.logger.debug(f"Collected {len(ncaa_games)} NCAA Baseball {mt} games for scroll")

            if league_games:
                games.extend(league_games)
                leagues.append('ncaa_baseball')

        # If live priority is active, filter to only live games
        if live_priority_active:
            games = [g for g in games if g.get('is_live', False) and not g.get('is_final', False)]
            self.logger.debug(f"Live priority active: filtered to {len(games)} live games")

        return games, leagues
    
    def _get_games_from_manager(self, manager, mode_type: str) -> List[Dict]:
        """Get games list from a manager based on mode type."""
        if mode_type == 'live':
            return list(getattr(manager, 'live_games', []) or [])
        elif mode_type == 'recent':
            # Try games_list first (used by recent managers), then recent_games
            games = getattr(manager, 'games_list', None)
            if games is None:
                games = getattr(manager, 'recent_games', [])
            return list(games or [])
        elif mode_type == 'upcoming':
            # Try games_list first (used by upcoming managers), then upcoming_games
            games = getattr(manager, 'games_list', None)
            if games is None:
                games = getattr(manager, 'upcoming_games', [])
            return list(games or [])
        return []
    
    def _get_rankings_cache(self) -> Dict[str, int]:
        """Get combined team rankings cache from all managers."""
        rankings = {}
        
        # Try to get rankings from each manager
        for manager_attr in ['mlb_live', 'mlb_recent', 'mlb_upcoming', 
                            'ncaa_baseball_live', 'ncaa_baseball_recent', 'ncaa_baseball_upcoming']:
            manager = getattr(self, manager_attr, None)
            if manager:
                manager_rankings = getattr(manager, '_team_rankings_cache', {})
                if manager_rankings:
                    rankings.update(manager_rankings)
        
        return rankings

    def _get_available_modes(self) -> list:
        """Get list of available display modes based on enabled leagues."""
        modes = []

        def league_modes(league: str) -> Dict[str, bool]:
            league_config = self.config.get(league, {})
            display_modes = league_config.get("display_modes", {})
            return {
                "live": display_modes.get("show_live", True),
                "recent": display_modes.get("show_recent", True),
                "upcoming": display_modes.get("show_upcoming", True),
            }

        if self.mlb_enabled:
            flags = league_modes("mlb")
            prefix = "mlb"
            if flags["live"]:
                modes.append(f"{prefix}_live")
            if flags["recent"]:
                modes.append(f"{prefix}_recent")
            if flags["upcoming"]:
                modes.append(f"{prefix}_upcoming")


        if self.milb_enabled:
            flags = league_modes("milb")
            prefix = "milb"
            if flags["live"]:
                modes.append(f"{prefix}_live")
            if flags["recent"]:
                modes.append(f"{prefix}_recent")
            if flags["upcoming"]:
                modes.append(f"{prefix}_upcoming")

        if self.ncaa_baseball_enabled:
            flags = league_modes("ncaa_baseball")
            prefix = "ncaa_baseball"
            if flags["live"]:
                modes.append(f"{prefix}_live")
            if flags["recent"]:
                modes.append(f"{prefix}_recent")
            if flags["upcoming"]:
                modes.append(f"{prefix}_upcoming")

        # Default to MLB if no leagues enabled
        if not modes:
            modes = ["mlb_live", "mlb_recent", "mlb_upcoming"]

        return modes

    def _get_current_manager(self):
        """Get the current manager based on the current mode."""
        if not self.modes:
            return None

        current_mode = self.modes[self.current_mode_index]

        if current_mode.startswith("mlb_"):
            if not self.mlb_enabled:
                return None
            mode_type = current_mode.split("_", 1)[1]  # "live", "recent", "upcoming"
            if mode_type == "live":
                return self.mlb_live
            elif mode_type == "recent":
                return self.mlb_recent
            elif mode_type == "upcoming":
                return self.mlb_upcoming

        elif current_mode.startswith("milb_"):
            if not self.milb_enabled:
                return None
            mode_type = current_mode.split("_", 1)[1]  # "live", "recent", "upcoming"
            if mode_type == "live":
                return self.milb_live
            elif mode_type == "recent":
                return self.milb_recent
            elif mode_type == "upcoming":
                return self.milb_upcoming

        elif current_mode.startswith("ncaa_baseball_"):
            if not self.ncaa_baseball_enabled:
                return None
            mode_type = current_mode.split("_", 2)[2]  # "live", "recent", "upcoming"
            if mode_type == "live":
                return self.ncaa_baseball_live
            elif mode_type == "recent":
                return self.ncaa_baseball_recent
            elif mode_type == "upcoming":
                return self.ncaa_baseball_upcoming

        return None

    def _ensure_manager_updated(self, manager) -> None:
        """Trigger an update when the delegated manager is stale."""
        last_update = getattr(manager, "last_update", None)
        update_interval = getattr(manager, "update_interval", None)
        if last_update is None or update_interval is None:
            return

        interval = update_interval
        no_data_interval = getattr(manager, "no_data_interval", None)
        live_games = getattr(manager, "live_games", None)
        if no_data_interval and not live_games:
            interval = no_data_interval

        try:
            if interval and time.time() - last_update >= interval:
                manager.update()
        except Exception as exc:
            self.logger.debug(f"Auto-refresh failed for manager {manager}: {exc}")

    def update(self) -> None:
        """Update baseball game data."""
        if not self.is_enabled:
            return

        try:
            # Update MLB managers if enabled
            if self.mlb_enabled:
                self.mlb_live.update()
                self.mlb_recent.update()
                self.mlb_upcoming.update()

            # Update MiLB managers if enabled
            if self.milb_enabled:
                self.milb_live.update()
                self.milb_recent.update()
                self.milb_upcoming.update()

            # Update NCAA Baseball managers if enabled
            if self.ncaa_baseball_enabled:
                self.ncaa_baseball_live.update()
                self.ncaa_baseball_recent.update()
                self.ncaa_baseball_upcoming.update()

        except Exception as e:
            self.logger.error(f"Error updating managers: {e}")

    def _get_managers_in_priority_order(self, mode_type: str) -> list:
        """
        Get managers for a mode type in priority order based on league registry.
        
        This method replaces the old sticky manager logic with a simpler approach:
        - Returns managers in priority order (MLB first, then NCAA Baseball, etc.)
        - Sequential block display logic handles showing all games from one league
          before moving to the next
        - No sticky manager state needed - completion is tracked via dynamic duration
        
        Args:
            mode_type: Mode type ('live', 'recent', or 'upcoming')
            
        Returns:
            List of manager instances in priority order (highest priority first)
            Managers are filtered to only include enabled leagues with the mode enabled
            
        This is used by the sequential block display logic to determine which
        leagues should be shown and in what order.
        """
        managers = []
        
        # Get enabled leagues for this mode type in priority order
        enabled_leagues = self._get_enabled_leagues_for_mode(mode_type)
        
        # Get managers for each enabled league in priority order
        for league_id in enabled_leagues:
            manager = self._get_league_manager_for_mode(league_id, mode_type)
            if manager:
                managers.append(manager)
                self.logger.debug(
                    f"Added {league_id} {mode_type} manager to priority list "
                    f"(priority: {self._league_registry[league_id].get('priority', 999)})"
                )
        
        self.logger.debug(
            f"Managers in priority order for {mode_type}: "
            f"{[m.__class__.__name__ for m in managers]}"
        )
        
        return managers

    def _try_manager_display(
        self, 
        manager, 
        force_clear: bool, 
        display_mode: str, 
        mode_type: str, 
        sticky_manager=None  # Kept for compatibility but no longer used
    ) -> Tuple[bool, Optional[str]]:
        """
        Try to display content from a single manager.
        
        This method handles displaying content from a manager and tracking progress
        for dynamic duration. It no longer uses sticky manager logic - sequential
        block display handles league rotation at a higher level.
        
        Args:
            manager: Manager instance to try
            force_clear: Whether to force clear display
            display_mode: External display mode name (e.g., 'mlb_recent' or 'ncaa_baseball_recent')
            mode_type: Mode type ('live', 'recent', or 'upcoming')
            sticky_manager: Deprecated parameter (kept for compatibility, ignored)
            
        Returns:
            Tuple of (success: bool, actual_mode: Optional[str])
            - success: True if manager displayed content, False otherwise
            - actual_mode: The actual mode name used for tracking (e.g., 'mlb_recent')
        """
        if not manager:
            return False, None
        
        # Track which league we're displaying for granular dynamic duration
        # This sets _current_display_league and _current_display_mode_type
        # which are used for progress tracking and duration calculations
        self._set_display_context_from_manager(manager, mode_type)
        
        # Ensure manager is updated before displaying
        # This fetches fresh data if needed based on update intervals
        self._ensure_manager_updated(manager)
        
        # Attempt to display content from this manager
        # Manager returns True if it has content to show, False if no content
        result = manager.display(force_clear)
        
        # Build the actual mode name from league and mode_type for accurate tracking
        # This is used to track progress per league separately
        # Example: 'mlb_recent' or 'ncaa_baseball_live'
        actual_mode = (
            f"{self._current_display_league}_{mode_type}" 
            if self._current_display_league and mode_type 
            else display_mode
        )
        
        # Track game transitions for logging
        # Only log at DEBUG level for frequent calls, INFO for game transitions
        manager_class_name = manager.__class__.__name__
        has_current_game = hasattr(manager, 'current_game') and manager.current_game is not None
        current_game = getattr(manager, 'current_game', None) if has_current_game else None
        
        # Get current game ID for transition detection
        current_game_id = None
        if current_game:
            current_game_id = current_game.get('id') or current_game.get('game_id')
            if not current_game_id:
                # Fallback: create ID from team abbreviations
                away = current_game.get('away_abbr', '')
                home = current_game.get('home_abbr', '')
                if away and home:
                    current_game_id = f"{away}@{home}"
        
        # Check for game transition
        game_tracking = self._current_game_tracking.get(display_mode, {})
        last_game_id = game_tracking.get('game_id')
        last_league = game_tracking.get('league')
        last_log_time = game_tracking.get('last_log_time', 0.0)
        current_time = time.time()
        
        # Detect game transition or league change
        game_changed = (current_game_id and current_game_id != last_game_id)
        league_changed = (self._current_display_league and self._current_display_league != last_league)
        time_since_last_log = current_time - last_log_time
        
        # Log game transitions at INFO level (but throttle to avoid spam)
        if (game_changed or league_changed) and time_since_last_log >= self._game_transition_log_interval:
            if game_changed and current_game_id:
                away_abbr = current_game.get('away_abbr', '?') if current_game else '?'
                home_abbr = current_game.get('home_abbr', '?') if current_game else '?'
                self.logger.info(
                    f"Game transition in {display_mode}: "
                    f"{away_abbr} @ {home_abbr} "
                    f"({self._current_display_league or 'unknown'} {mode_type})"
                )
            elif league_changed and self._current_display_league:
                self.logger.info(
                    f"League transition in {display_mode}: "
                    f"switched to {self._current_display_league} {mode_type}"
                )
            
            # Update tracking
            self._current_game_tracking[display_mode] = {
                'game_id': current_game_id,
                'league': self._current_display_league,
                'last_log_time': current_time
            }
        else:
            # Frequent calls - only log at DEBUG level
            self.logger.debug(
                f"Manager {manager_class_name} display() returned {result}, "
                f"has_current_game={has_current_game}, game_id={current_game_id}"
            )
        
        if result is True:
            # Manager successfully displayed content
            # Track progress for dynamic duration system
            manager_key = self._build_manager_key(actual_mode, manager)
            
            try:
                # Record that we've seen this manager and track game progress
                # This updates _dynamic_manager_progress and marks games as shown
                self._record_dynamic_progress(manager, actual_mode=actual_mode, display_mode=display_mode)
            except Exception as progress_err:  # pylint: disable=broad-except
                self.logger.debug(f"Dynamic progress tracking failed: {progress_err}")
            
            # Track which managers were used for this display mode
            # This is used to determine when all leagues have completed
            if display_mode:
                self._display_mode_to_managers.setdefault(display_mode, set()).add(manager_key)
            
            # Check if this manager (league) has completed all its games
            # If all enabled leagues complete, the display mode cycle is complete
            self._evaluate_dynamic_cycle_completion(display_mode=display_mode)
            return True, actual_mode
        
        elif result is False:
            # Manager returned False - no content available or between games
            # In sequential block display, we'll try the next league if this one is complete
            # The completion check happens in _display_external_mode()
            self.logger.debug(
                f"Manager {manager_class_name} returned False - no content or between games"
            )
            return False, None
        
        else:
            # Result is None or other unexpected value - assume success
            # This handles edge cases where managers return None instead of True/False
            manager_key = self._build_manager_key(actual_mode, manager)
            
            try:
                self._record_dynamic_progress(manager, actual_mode=actual_mode, display_mode=display_mode)
            except Exception as progress_err:  # pylint: disable=broad-except
                self.logger.debug(f"Dynamic progress tracking failed: {progress_err}")
            
            # Track which managers were used for this display mode
            if display_mode:
                self._display_mode_to_managers.setdefault(display_mode, set()).add(manager_key)
            
            self._evaluate_dynamic_cycle_completion(display_mode=display_mode)
            return True, actual_mode

    def _display_external_mode(self, display_mode: str, force_clear: bool) -> bool:
        """
        Handle display for external display_mode calls (from display controller).

        Routes granular modes (mlb_live, ncaa_baseball_recent, etc.) to _display_league_mode.

        Args:
            display_mode: External mode name (e.g., 'mlb_live', 'mlb_recent', 'ncaa_baseball_upcoming')
            force_clear: Whether to force clear display

        Returns:
            True if content was displayed, False otherwise
        """
        self.logger.debug(f"Display called with mode: {display_mode}")
        
        # Extract the mode type (live, recent, upcoming)
        mode_type = self._extract_mode_type(display_mode)
        if not mode_type:
            self.logger.warning(f"Unknown display_mode: {display_mode}")
            return False
        
        # Check if this is a granular mode (league-specific)
        # Granular modes: mlb_live, ncaa_baseball_recent, etc.
        league = None
        if display_mode.startswith('mlb_'):
            league = 'mlb'
        elif display_mode.startswith('milb_'):
            league = 'milb'
        elif display_mode.startswith('ncaa_baseball_'):
            league = 'ncaa_baseball'
        # If no league prefix, it's a combined mode - keep league=None
        
        self.logger.debug(
            f"Mode: {display_mode}, League: {league}, Mode type: {mode_type}, "
            f"MLB enabled: {self.mlb_enabled}, MiLB enabled: {self.milb_enabled}, NCAA Baseball enabled: {self.ncaa_baseball_enabled}"
        )
        
        # If granular mode (league-specific), display only that league
        if league:
            return self._display_league_mode(league, mode_type, force_clear)
        
        # Combined mode - display across all enabled leagues
        
        # Check if we should use scroll mode for this game type
        if self._should_use_scroll_mode(mode_type):
            return self._display_scroll_mode(display_mode, mode_type, force_clear)
        
        # Otherwise, use switch mode (existing behavior)

        # Resolve managers to try for this mode type
        managers_to_try = self._resolve_managers_for_mode(mode_type)

        # Try each manager until one returns True (has content)
        for current_manager in managers_to_try:
            success, _ = self._try_manager_display(
                current_manager, force_clear, display_mode, mode_type, None
            )

            if success:
                self.logger.info(f"Plugin display() returning True for {display_mode}")
                return True
        
        # No manager had content - log why
        if not managers_to_try:
            self.logger.warning(
                f"_display_external_mode() called with granular mode: {display_mode}. "
                f"This should be handled by display() directly. "
                f"(mlb_has_manager={self._get_manager_for_league_mode('mlb', mode_type) is not None}, "
                f"milb_has_manager={self._get_manager_for_league_mode('milb', mode_type) is not None}, "
                f"ncaa_baseball_has_manager={self._get_manager_for_league_mode('ncaa_baseball', mode_type) is not None})"
            )
            # Try to handle it anyway by parsing and calling _display_league_mode
            parts = display_mode.split("_", 1)
            if len(parts) == 2:
                league, mode_type_str = parts
                if league in self._league_registry and mode_type_str == mode_type:
                    return self._display_league_mode(league, mode_type, force_clear)
            return False
        
        # Legacy combined mode handling (should not be reached with new architecture)
        self.logger.warning(
            f"_display_external_mode() called with combined mode: {display_mode}. "
            f"Combined modes are no longer supported. Use granular modes instead."
        )
        return False
    
    def _display_scroll_mode(self, display_mode: str, mode_type: str, force_clear: bool) -> bool:
        """Handle display for scroll mode.
        
        Args:
            display_mode: External mode name (e.g., 'mlb_live' or 'ncaa_baseball_live')
            mode_type: Game type ('live', 'recent', 'upcoming')
            force_clear: Whether to force clear display
            
        Returns:
            True if content was displayed, False otherwise
        """
        if not self._scroll_manager:
            self.logger.warning("Scroll mode requested but scroll manager not available")
            # Fall back to switch mode
            return self._display_switch_mode_fallback(display_mode, mode_type, force_clear)
        
        # Check if we need to prepare new scroll content
        scroll_key = f"{display_mode}_{mode_type}"
        
        if not self._scroll_prepared.get(scroll_key, False):
            # Update managers first to get latest game data
            if self.mlb_enabled:
                league_manager = self._get_manager_for_league_mode('mlb', mode_type)
                if league_manager:
                    self._ensure_manager_updated(league_manager)

            if self.milb_enabled:
                league_manager = self._get_manager_for_league_mode('milb', mode_type)
                if league_manager:
                    self._ensure_manager_updated(league_manager)
            if self.ncaa_baseball_enabled:
                ncaa_manager = self._get_manager_for_league_mode('ncaa_baseball', mode_type)
                if ncaa_manager:
                    self._ensure_manager_updated(ncaa_manager)
            
            # Check if live priority should filter to only live games
            live_priority_active = (
                mode_type == 'live' and
                (self.mlb_live_priority or self.milb_live_priority or self.ncaa_baseball_live_priority) and
                self.has_live_content()
            )
            
            # Collect games from all leagues using scroll mode
            games, leagues = self._collect_games_for_scroll(mode_type, live_priority_active)
            
            if not games:
                self.logger.debug(f"No games to scroll for {display_mode}")
                self._scroll_prepared[scroll_key] = False
                self._scroll_active[scroll_key] = False
                return False
            
            # Get rankings cache for display
            rankings = self._get_rankings_cache()
            
            # Prepare scroll content
            success = self._scroll_manager.prepare_and_display(
                games, mode_type, leagues, rankings
            )
            
            if success:
                self._scroll_prepared[scroll_key] = True
                self._scroll_active[scroll_key] = True
                self.logger.info(
                    f"[Baseball Scroll] Started scrolling {len(games)} {mode_type} games "
                    f"from {', '.join(leagues)}"
                )
            else:
                self._scroll_prepared[scroll_key] = False
                self._scroll_active[scroll_key] = False
                return False
        
        # Display the next scroll frame
        if self._scroll_active.get(scroll_key, False):
            displayed = self._scroll_manager.display_frame(mode_type)
            
            if displayed:
                # Check if scroll is complete
                if self._scroll_manager.is_complete(mode_type):
                    self.logger.info(f"[Baseball Scroll] Cycle complete for {display_mode}")
                    # Reset for next cycle
                    self._scroll_prepared[scroll_key] = False
                    self._scroll_active[scroll_key] = False
                    # Mark cycle as complete for dynamic duration
                    self._dynamic_cycle_complete = True
                
                return True
            else:
                # Scroll display failed
                self._scroll_active[scroll_key] = False
                return False
        
        return False
    
    def _display_switch_mode_fallback(self, display_mode: str, mode_type: str, force_clear: bool) -> bool:
        """Fallback to switch mode when scroll is not available.
        
        This is essentially the same logic as the switch mode portion of _display_external_mode.
        """
        # Resolve managers to try for this mode type (in priority order)
        managers_to_try = self._resolve_managers_for_mode(mode_type)
        
        # Try each manager until one returns True (has content)
        # Sequential block display handles league rotation at a higher level
        for current_manager in managers_to_try:
            success, _ = self._try_manager_display(
                current_manager, force_clear, display_mode, mode_type, None
            )
            
            if success:
                return True
        
        return False

    def _display_league_mode(self, league: str, mode_type: str, force_clear: bool) -> bool:
        """
        Display a specific league/mode combination (e.g., MLB Recent, NCAA Baseball Upcoming).
        
        This method displays content from a single league and mode type, used when
        rotation_order specifies granular modes like 'mlb_recent' or 'ncaa_baseball_upcoming'.
        
        Args:
            league: League ID ('mlb' or 'ncaa_baseball')
            mode_type: Mode type ('live', 'recent', or 'upcoming')
            force_clear: Whether to force clear display
            
        Returns:
            True if content was displayed, False otherwise
        """
        # Validate league
        if league not in self._league_registry:
            self.logger.warning(f"Invalid league in _display_league_mode: {league}")
            return False
        
        # Check if league is enabled
        if not self._league_registry[league].get('enabled', False):
            self.logger.debug(f"League {league} is disabled, skipping")
            return False
        
        # Get manager for this league/mode combination
        manager = self._get_league_manager_for_mode(league, mode_type)
        if not manager:
            self.logger.debug(f"No manager available for {league} {mode_type}")
            return False
        
        # Create display mode name for tracking
        display_mode = f"{league}_{mode_type}"
        
        # Set display context for dynamic duration tracking
        self._current_display_league = league
        self._current_display_mode_type = mode_type
        
        # Try to display content from this league's manager
        success, _ = self._try_manager_display(
            manager, force_clear, display_mode, mode_type, None
        )
        
        # Only track mode start time and check duration if we actually have content to display
        if success:
            # Track mode start time for per-mode duration enforcement (only when content exists)
            if display_mode not in self._mode_start_time:
                self._mode_start_time[display_mode] = time.time()
                self.logger.debug(f"Started tracking time for {display_mode}")
            
            # Check if mode-level duration has expired (only check if we have content)
            effective_mode_duration = self._get_effective_mode_duration(display_mode, mode_type)
            if effective_mode_duration is not None:
                elapsed_time = time.time() - self._mode_start_time[display_mode]
                if elapsed_time >= effective_mode_duration:
                    # Mode duration expired - time to rotate
                    self.logger.info(
                        f"Mode duration expired for {display_mode}: "
                        f"{elapsed_time:.1f}s >= {effective_mode_duration}s. "
                        f"Rotating to next mode (progress preserved for resume)."
                    )
                    # Reset mode start time for next cycle
                    self._mode_start_time[display_mode] = time.time()
                    return False
            
            self.logger.debug(
                f"Displayed content from {league} {mode_type} (mode: {display_mode})"
            )
        else:
            # No content - clear any existing start time so mode can start fresh when content becomes available
            if display_mode in self._mode_start_time:
                del self._mode_start_time[display_mode]
                self.logger.debug(f"Cleared mode start time for {display_mode} (no content available)")
            
            self.logger.debug(
                f"No content available for {league} {mode_type} (mode: {display_mode})"
            )
        
        return success

    def _display_internal_cycling(self, force_clear: bool) -> bool:
        """Handle display for internal mode cycling (when no display_mode provided).

        .. deprecated::
            This method exists for legacy/testing support. The display controller
            should always provide display_mode parameter for proper timing behavior.

        Args:
            force_clear: Whether to force clear display

        Returns:
            True if content was displayed, False otherwise
        """
        # Log deprecation warning (once per session)
        if not getattr(self, '_internal_cycling_warned', False):
            self.logger.warning(
                "Using deprecated internal mode cycling. "
                "For proper dynamic duration support, use display(display_mode=...) instead."
            )
            self._internal_cycling_warned = True

        current_time = time.time()
        
        # Check if we should stay on live mode
        should_stay_on_live = False
        if self.has_live_content():
            # Get current mode name
            current_mode = self.modes[self.current_mode_index] if self.modes else None
            # If we're on a live mode, stay there
            if current_mode and current_mode.endswith('_live'):
                should_stay_on_live = True
            # If we're not on a live mode but have live content, switch to it
            elif not (current_mode and current_mode.endswith('_live')):
                # Find the first live mode
                for i, mode in enumerate(self.modes):
                    if mode.endswith('_live'):
                        self.current_mode_index = i
                        force_clear = True
                        self.last_mode_switch = current_time
                        self.logger.info(f"Live content detected - switching to display mode: {mode}")
                        break
        
        # Handle mode cycling only if not staying on live
        # Get dynamic duration for current mode (falls back to display_duration)
        current_mode_for_duration = self.modes[self.current_mode_index] if self.modes else None
        cycle_duration = self.display_duration  # Default fallback
        if current_mode_for_duration:
            dynamic_duration = self.get_cycle_duration(current_mode_for_duration)
            if dynamic_duration is not None and dynamic_duration > 0:
                cycle_duration = dynamic_duration

        if not should_stay_on_live and current_time - self.last_mode_switch >= cycle_duration:
            self.current_mode_index = (self.current_mode_index + 1) % len(self.modes)
            self.last_mode_switch = current_time
            force_clear = True

            current_mode = self.modes[self.current_mode_index]
            self.logger.info(f"Switching to display mode: {current_mode} (after {cycle_duration:.1f}s)")
        
        # Get current manager and display
        current_manager = self._get_current_manager()
        if not current_manager:
            self.logger.warning("No manager available for current mode")
            return False
        
        # Track which league/mode we're displaying for granular dynamic duration
        current_mode = self.modes[self.current_mode_index] if self.modes else None
        if current_mode:
            # Extract mode type from mode name
            mode_type = self._extract_mode_type(current_mode)
            if mode_type:
                self._set_display_context_from_manager(current_manager, mode_type)
        
        result = current_manager.display(force_clear)
        if result is not False:
            try:
                # Build the actual mode name from league and mode_type for accurate tracking
                current_mode = self.modes[self.current_mode_index] if self.modes else None
                if current_mode:
                    manager_key = self._build_manager_key(current_mode, current_manager)
                    # Track which managers were used for internal mode cycling
                    # For internal cycling, the mode itself is the display_mode
                    self._display_mode_to_managers.setdefault(current_mode, set()).add(manager_key)
                self._record_dynamic_progress(
                    current_manager, actual_mode=current_mode, display_mode=current_mode
                )
            except Exception as progress_err:  # pylint: disable=broad-except
                self.logger.debug(f"Dynamic progress tracking failed: {progress_err}")
        else:
            # Manager returned False (no content) - ensure display is cleared
            # This is a safety measure in case the manager didn't clear it
            if force_clear:
                try:
                    self.display_manager.clear()
                    self.display_manager.update_display()
                except Exception as clear_err:
                    self.logger.debug(f"Error clearing display when manager returned False: {clear_err}")
        
        current_mode = self.modes[self.current_mode_index] if self.modes else None
        self._evaluate_dynamic_cycle_completion(display_mode=current_mode)
        return result

    def display(self, display_mode: str = None, force_clear: bool = False) -> bool:
        """Display baseball games for a specific granular mode.

        The plugin now uses granular modes directly (mlb_recent, mlb_upcoming, mlb_live,
        milb_recent, milb_upcoming, milb_live,
        ncaa_baseball_recent, ncaa_baseball_upcoming, ncaa_baseball_live) registered in manifest.json.
        The display controller handles rotation between these modes.
        
        Args:
            display_mode: Granular mode name (e.g., 'mlb_recent', 'ncaa_baseball_upcoming', 'mlb_live')
                         Format: {league}_{mode_type}
                         If None, uses internal mode cycling (legacy support).
            force_clear: If True, clear display before rendering
        """
        if not self.is_enabled:
            return False

        try:
            # Track the current active display mode for use in is_cycle_complete()
            if display_mode:
                # Early exit: Skip if this mode is not in our available modes (disabled league)
                if display_mode not in self.modes:
                    self.logger.debug(f"Skipping disabled mode: {display_mode} (not in available modes: {self.modes})")
                    return False
                self._current_active_display_mode = display_mode
            
            # Route to appropriate display handler
            if display_mode:
                # Handle granular modes (mlb_recent, ncaa_baseball_upcoming, mlb_live, etc.)
                # All modes are now league-specific granular modes
                if display_mode.startswith("baseball_"):
                    # Legacy combined mode - extract mode_type and show all enabled leagues
                    mode_type_str = display_mode.replace("baseball_", "")
                    if mode_type_str not in ['live', 'recent', 'upcoming']:
                        self.logger.warning(
                            f"Invalid legacy combined mode: {display_mode}"
                        )
                        return False
                    
                    # Show all enabled leagues for this mode type (sequential block)
                    # This maintains backward compatibility during transition
                    enabled_leagues = self._get_enabled_leagues_for_mode(mode_type_str)
                    if not enabled_leagues:
                        self.logger.debug(
                            f"No enabled leagues for legacy mode {display_mode}"
                        )
                        return False
                    
                    # Try to display from first enabled league
                    # This is a simplified fallback for legacy mode support
                    for league_id in enabled_leagues:
                        success = self._display_league_mode(league_id, mode_type_str, force_clear)
                        if success:
                            return True
                    
                    # No content from any league
                    return False
                
                # Parse granular mode name: {league}_{mode_type}
                # e.g., "mlb_recent" -> league="mlb", mode_type="recent"
                # e.g., "ncaa_baseball_recent" -> league="ncaa_baseball", mode_type="recent"
                # e.g., "uefa.champions_recent" -> league="uefa.champions", mode_type="recent" (for soccer)
                # 
                # Scalable approach: Check league registry first, then extract mode type
                # This works for any league naming convention (underscores, dots, etc.)
                mode_type_str = None
                league = None
                
                # Known mode type suffixes (standardized across all sports plugins)
                mode_suffixes = ['_live', '_recent', '_upcoming']
                
                # Try to match against league registry first (most reliable)
                # Check each league ID in registry to see if display_mode starts with it
                for league_id in self._league_registry.keys():
                    for mode_suffix in mode_suffixes:
                        expected_mode = f"{league_id}{mode_suffix}"
                        if display_mode == expected_mode:
                            league = league_id
                            mode_type_str = mode_suffix[1:]  # Remove leading underscore
                            break
                    if league:
                        break
                
                # Fallback: If no registry match, parse from the end (for backward compatibility)
                if not league:
                    for mode_suffix in mode_suffixes:
                        if display_mode.endswith(mode_suffix):
                            mode_type_str = mode_suffix[1:]  # Remove leading underscore
                            league = display_mode[:-len(mode_suffix)]  # Everything before the suffix
                            # Validate it's a known league
                            if league in self._league_registry:
                                break
                            else:
                                # Not a known league, try next suffix
                                league = None
                                mode_type_str = None
                
                if not mode_type_str or not league:
                    self.logger.warning(
                        f"Invalid granular display_mode format: {display_mode} "
                        f"(expected format: {{league}}_{{mode_type}}, e.g., 'mlb_recent' or 'ncaa_baseball_recent'). "
                        f"Valid leagues: {list(self._league_registry.keys())}"
                    )
                    return False
                
                # Validate league exists in registry (double-check)
                if league not in self._league_registry:
                    self.logger.warning(
                        f"Invalid league in display_mode: {league} (mode: {display_mode}). "
                        f"Valid leagues: {list(self._league_registry.keys())}"
                    )
                    return False
                
                # Check if league is enabled
                if not self._league_registry[league].get('enabled', False):
                    self.logger.debug(
                        f"League {league} is disabled, skipping {display_mode}"
                    )
                    return False
                
                # Check if mode is enabled for this league
                league_config = self.config.get(league, {})
                display_modes_config = league_config.get("display_modes", {})
                
                mode_enabled = True
                if mode_type_str == 'live':
                    mode_enabled = display_modes_config.get("show_live", True)
                elif mode_type_str == 'recent':
                    mode_enabled = display_modes_config.get("show_recent", True)
                elif mode_type_str == 'upcoming':
                    mode_enabled = display_modes_config.get("show_upcoming", True)
                
                if not mode_enabled:
                    self.logger.debug(
                        f"Mode {mode_type_str} is disabled for league {league}, skipping {display_mode}"
                    )
                    return False
                
                # Display this specific league/mode combination
                return self._display_league_mode(league, mode_type_str, force_clear)
            else:
                # No display_mode provided - use internal cycling (legacy support)
                return self._display_internal_cycling(force_clear)

        except Exception as e:
            self.logger.error(f"Error in display method: {e}")
            return False

    def has_live_priority(self) -> bool:
        if not self.is_enabled:
            return False
        result = (
            (self.mlb_enabled and self.mlb_live_priority)
            or (self.milb_enabled and self.milb_live_priority)
            or (self.ncaa_baseball_enabled and self.ncaa_baseball_live_priority)
        )
        # Log at DEBUG level since this is called frequently and the result rarely changes
        self.logger.debug(f"has_live_priority() called: mlb_enabled={self.mlb_enabled}, mlb_live_priority={self.mlb_live_priority}, milb_enabled={self.milb_enabled}, milb_live_priority={self.milb_live_priority}, ncaa_baseball_enabled={self.ncaa_baseball_enabled}, ncaa_baseball_live_priority={self.ncaa_baseball_live_priority}, result={result}")
        return result

    def has_live_content(self) -> bool:
        if not self.is_enabled:
            self.logger.debug("[LIVE_PRIORITY_DEBUG] has_live_content: plugin not enabled, returning False")
            return False

        # Check MLB live content
        mlb_live = False
        if (
            self.mlb_enabled
            and self.mlb_live_priority
            and hasattr(self, "mlb_live")
        ):
            raw_live_games = getattr(self.mlb_live, "live_games", [])
            self.logger.debug(f"[LIVE_PRIORITY_DEBUG] MLB raw live_games count: {len(raw_live_games)}")

            # Log each raw game for debugging
            for i, game in enumerate(raw_live_games):
                self.logger.debug(
                    f"[LIVE_PRIORITY_DEBUG] MLB raw game {i+1}: "
                    f"{game.get('away_abbr')}@{game.get('home_abbr')} "
                    f"is_final={game.get('is_final')}, is_live={game.get('is_live')}, "
                    f"clock={game.get('clock')}, period={game.get('period')}, "
                    f"period_text={game.get('period_text')}"
                )

            if raw_live_games:
                # Filter out any games that are final or appear over
                live_games = [g for g in raw_live_games if not g.get("is_final", False)]
                games_after_final_filter = len(live_games)
                self.logger.debug(f"[LIVE_PRIORITY_DEBUG] MLB after is_final filter: {games_after_final_filter} games")

                # Additional validation using helper method if available
                if hasattr(self.mlb_live, "_is_game_really_over"):
                    games_before_really_over = len(live_games)
                    for game in live_games[:]:  # Iterate over copy
                        is_really_over = self.mlb_live._is_game_really_over(game)
                        if is_really_over:
                            self.logger.debug(
                                f"[LIVE_PRIORITY_DEBUG] MLB _is_game_really_over=True for "
                                f"{game.get('away_abbr')}@{game.get('home_abbr')} "
                                f"(clock={game.get('clock')}, period={game.get('period')}, "
                                f"period_text={game.get('period_text')})"
                            )
                            live_games.remove(game)
                    self.logger.debug(
                        f"[LIVE_PRIORITY_DEBUG] MLB after _is_game_really_over filter: "
                        f"{len(live_games)} games (removed {games_before_really_over - len(live_games)})"
                    )

                if live_games:
                    # If favorite teams are configured, only return True if there are live games for favorite teams
                    favorite_teams = getattr(self.mlb_live, "favorite_teams", [])
                    self.logger.debug(f"[LIVE_PRIORITY_DEBUG] MLB favorite_teams configured: {favorite_teams}")

                    if favorite_teams:
                        # Check if any live game involves a favorite team
                        for game in live_games:
                            home = game.get("home_abbr")
                            away = game.get("away_abbr")
                            home_match = home in favorite_teams
                            away_match = away in favorite_teams
                            self.logger.debug(
                                f"[LIVE_PRIORITY_DEBUG] MLB favorite check: {away}@{home} - "
                                f"home_in_favorites={home_match}, away_in_favorites={away_match}"
                            )

                        mlb_live = any(
                            game.get("home_abbr") in favorite_teams
                            or game.get("away_abbr") in favorite_teams
                            for game in live_games
                        )
                        self.logger.debug(f"[LIVE_PRIORITY_DEBUG] MLB favorite team match result: {mlb_live}")
                    else:
                        # No favorite teams configured, return True if any live games exist
                        mlb_live = True
                        self.logger.debug("[LIVE_PRIORITY_DEBUG] MLB no favorites configured, mlb_live=True")

                    self.logger.info(f"has_live_content: MLB live_games={len(live_games)}, filtered_live_games={len(live_games)}, mlb_live={mlb_live}")
                else:
                    self.logger.debug("[LIVE_PRIORITY_DEBUG] MLB no live games after filtering")
            else:
                self.logger.debug("[LIVE_PRIORITY_DEBUG] MLB raw live_games is empty")
        else:
            self.logger.debug(
                f"[LIVE_PRIORITY_DEBUG] MLB check skipped: mlb_enabled={self.mlb_enabled}, "
                f"mlb_live_priority={self.mlb_live_priority}, has_mlb_live={hasattr(self, 'mlb_live')}"
            )

        # Check MiLB live content
        milb_live = False
        if (
            self.milb_enabled
            and self.milb_live_priority
            and hasattr(self, "milb_live")
        ):
            raw_live_games = getattr(self.milb_live, "live_games", [])
            self.logger.debug(f"[LIVE_PRIORITY_DEBUG] MiLB raw live_games count: {len(raw_live_games)}")

            # Log each raw game for debugging
            for i, game in enumerate(raw_live_games):
                self.logger.debug(
                    f"[LIVE_PRIORITY_DEBUG] MiLB raw game {i+1}: "
                    f"{game.get('away_abbr')}@{game.get('home_abbr')} "
                    f"is_final={game.get('is_final')}, is_live={game.get('is_live')}, "
                    f"clock={game.get('clock')}, period={game.get('period')}, "
                    f"period_text={game.get('period_text')}"
                )

            if raw_live_games:
                # Filter out any games that are final or appear over
                live_games = [g for g in raw_live_games if not g.get("is_final", False)]
                games_after_final_filter = len(live_games)
                self.logger.debug(f"[LIVE_PRIORITY_DEBUG] MiLB after is_final filter: {games_after_final_filter} games")

                # Additional validation using helper method if available
                if hasattr(self.milb_live, "_is_game_really_over"):
                    games_before_really_over = len(live_games)
                    for game in live_games[:]:  # Iterate over copy
                        is_really_over = self.milb_live._is_game_really_over(game)
                        if is_really_over:
                            self.logger.debug(
                                f"[LIVE_PRIORITY_DEBUG] MiLB _is_game_really_over=True for "
                                f"{game.get('away_abbr')}@{game.get('home_abbr')} "
                                f"(clock={game.get('clock')}, period={game.get('period')}, "
                                f"period_text={game.get('period_text')})"
                            )
                            live_games.remove(game)
                    self.logger.debug(
                        f"[LIVE_PRIORITY_DEBUG] MiLB after _is_game_really_over filter: "
                        f"{len(live_games)} games (removed {games_before_really_over - len(live_games)})"
                    )

                if live_games:
                    # If favorite teams are configured, only return True if there are live games for favorite teams
                    favorite_teams = getattr(self.milb_live, "favorite_teams", [])
                    self.logger.debug(f"[LIVE_PRIORITY_DEBUG] MiLB favorite_teams configured: {favorite_teams}")

                    if favorite_teams:
                        # Check if any live game involves a favorite team
                        for game in live_games:
                            home = game.get("home_abbr")
                            away = game.get("away_abbr")
                            home_match = home in favorite_teams
                            away_match = away in favorite_teams
                            self.logger.debug(
                                f"[LIVE_PRIORITY_DEBUG] MiLB favorite check: {away}@{home} - "
                                f"home_in_favorites={home_match}, away_in_favorites={away_match}"
                            )

                        milb_live = any(
                            game.get("home_abbr") in favorite_teams
                            or game.get("away_abbr") in favorite_teams
                            for game in live_games
                        )
                        self.logger.debug(f"[LIVE_PRIORITY_DEBUG] MiLB favorite team match result: {milb_live}")
                    else:
                        # No favorite teams configured, return True if any live games exist
                        milb_live = True
                        self.logger.debug("[LIVE_PRIORITY_DEBUG] MiLB no favorites configured, milb_live=True")

                    self.logger.info(f"has_live_content: MiLB live_games={len(live_games)}, filtered_live_games={len(live_games)}, milb_live={milb_live}")
                else:
                    self.logger.debug("[LIVE_PRIORITY_DEBUG] MiLB no live games after filtering")
            else:
                self.logger.debug("[LIVE_PRIORITY_DEBUG] MiLB raw live_games is empty")
        else:
            self.logger.debug(
                f"[LIVE_PRIORITY_DEBUG] MiLB check skipped: milb_enabled={self.milb_enabled}, "
                f"milb_live_priority={self.milb_live_priority}, has_milb_live={hasattr(self, 'milb_live')}"
            )

        # Check NCAA Baseball live content
        ncaa_live = False
        if (
            self.ncaa_baseball_enabled
            and self.ncaa_baseball_live_priority
            and hasattr(self, "ncaa_baseball_live")
        ):
            raw_live_games = getattr(self.ncaa_baseball_live, "live_games", [])
            self.logger.debug(f"[LIVE_PRIORITY_DEBUG] NCAA Baseball raw live_games count: {len(raw_live_games)}")

            # Log each raw game for debugging
            for i, game in enumerate(raw_live_games):
                self.logger.debug(
                    f"[LIVE_PRIORITY_DEBUG] NCAA Baseball raw game {i+1}: "
                    f"{game.get('away_abbr')}@{game.get('home_abbr')} "
                    f"is_final={game.get('is_final')}, is_live={game.get('is_live')}, "
                    f"clock={game.get('clock')}, period={game.get('period')}, "
                    f"period_text={game.get('period_text')}"
                )

            if raw_live_games:
                # Filter out any games that are final or appear over
                live_games = [g for g in raw_live_games if not g.get("is_final", False)]
                games_after_final_filter = len(live_games)
                self.logger.debug(f"[LIVE_PRIORITY_DEBUG] NCAA Baseball after is_final filter: {games_after_final_filter} games")

                # Additional validation using helper method if available
                if hasattr(self.ncaa_baseball_live, "_is_game_really_over"):
                    games_before_really_over = len(live_games)
                    for game in live_games[:]:  # Iterate over copy
                        is_really_over = self.ncaa_baseball_live._is_game_really_over(game)
                        if is_really_over:
                            self.logger.debug(
                                f"[LIVE_PRIORITY_DEBUG] NCAA Baseball _is_game_really_over=True for "
                                f"{game.get('away_abbr')}@{game.get('home_abbr')} "
                                f"(clock={game.get('clock')}, period={game.get('period')}, "
                                f"period_text={game.get('period_text')})"
                            )
                            live_games.remove(game)
                    self.logger.debug(
                        f"[LIVE_PRIORITY_DEBUG] NCAA Baseball after _is_game_really_over filter: "
                        f"{len(live_games)} games (removed {games_before_really_over - len(live_games)})"
                    )

                if live_games:
                    # If favorite teams are configured, only return True if there are live games for favorite teams
                    favorite_teams = getattr(self.ncaa_baseball_live, "favorite_teams", [])
                    self.logger.debug(f"[LIVE_PRIORITY_DEBUG] NCAA Baseball favorite_teams configured: {favorite_teams}")

                    if favorite_teams:
                        # Check if any live game involves a favorite team
                        for game in live_games:
                            home = game.get("home_abbr")
                            away = game.get("away_abbr")
                            home_match = home in favorite_teams
                            away_match = away in favorite_teams
                            self.logger.debug(
                                f"[LIVE_PRIORITY_DEBUG] NCAA Baseball favorite check: {away}@{home} - "
                                f"home_in_favorites={home_match}, away_in_favorites={away_match}"
                            )

                        ncaa_live = any(
                            game.get("home_abbr") in favorite_teams
                            or game.get("away_abbr") in favorite_teams
                            for game in live_games
                        )
                        self.logger.debug(f"[LIVE_PRIORITY_DEBUG] NCAA Baseball favorite team match result: {ncaa_live}")
                    else:
                        # No favorite teams configured, return True if any live games exist
                        ncaa_live = True
                        self.logger.debug("[LIVE_PRIORITY_DEBUG] NCAA Baseball no favorites configured, ncaa_live=True")

                    self.logger.info(f"has_live_content: NCAA Baseball live_games={len(live_games)}, filtered_live_games={len(live_games)}, ncaa_live={ncaa_live}")
                else:
                    self.logger.debug("[LIVE_PRIORITY_DEBUG] NCAA Baseball no live games after filtering")
            else:
                self.logger.debug("[LIVE_PRIORITY_DEBUG] NCAA Baseball raw live_games is empty")
        else:
            self.logger.debug(
                f"[LIVE_PRIORITY_DEBUG] NCAA Baseball check skipped: ncaa_baseball_enabled={self.ncaa_baseball_enabled}, "
                f"ncaa_baseball_live_priority={self.ncaa_baseball_live_priority}, has_ncaa_baseball_live={hasattr(self, 'ncaa_baseball_live')}"
            )

        result = mlb_live or milb_live or ncaa_live

        # Throttle logging when returning False to reduce log noise
        # Always log True immediately (important), but only log False every 60 seconds
        current_time = time.time()
        should_log = result or (current_time - self._last_live_content_false_log >= self._live_content_log_interval)

        if should_log:
            if result:
                # Always log True results immediately
                self.logger.info(f"has_live_content() returning {result}: mlb_live={mlb_live}, milb_live={milb_live}, ncaa_live={ncaa_live}")
            else:
                # Log False results only every 60 seconds
                self.logger.info(f"has_live_content() returning {result}: mlb_live={mlb_live}, milb_live={milb_live}, ncaa_live={ncaa_live}")
                self._last_live_content_false_log = current_time
        
        return result

    def get_live_modes(self) -> list:
        """
        Return the registered plugin mode name(s) that have live content.
        
        Returns granular live modes (mlb_live, ncaa_baseball_live) that actually have live content.
        The plugin is now registered with granular modes in manifest.json.
        """
        if not self.is_enabled:
            return []

        live_modes = []
        
        # Check MLB live content
        if (
            self.mlb_enabled
            and self.mlb_live_priority
            and hasattr(self, "mlb_live")
        ):
            live_games = getattr(self.mlb_live, "live_games", [])
            if live_games:
                # Filter out any games that are final or appear over
                live_games = [g for g in live_games if not g.get("is_final", False)]
                # Additional validation using helper method if available
                if hasattr(self.mlb_live, "_is_game_really_over"):
                    live_games = [g for g in live_games if not self.mlb_live._is_game_really_over(g)]
                
                if live_games:
                    # If favorite teams are configured, only return if there are live games for favorite teams
                    favorite_teams = getattr(self.mlb_live, "favorite_teams", [])
                    if favorite_teams:
                        if any(
                            game.get("home_abbr") in favorite_teams
                            or game.get("away_abbr") in favorite_teams
                            for game in live_games
                        ):
                            live_modes.append("mlb_live")
                    else:
                        # No favorite teams configured, include if any live games exist
                        live_modes.append("mlb_live")
        
        # Check MiLB live content
        if (
            self.milb_enabled
            and self.milb_live_priority
            and hasattr(self, "milb_live")
        ):
            live_games = getattr(self.milb_live, "live_games", [])
            if live_games:
                live_games = [g for g in live_games if not g.get("is_final", False)]
                if hasattr(self.milb_live, "_is_game_really_over"):
                    live_games = [g for g in live_games if not self.milb_live._is_game_really_over(g)]

                if live_games:
                    favorite_teams = getattr(self.milb_live, "favorite_teams", [])
                    if favorite_teams:
                        if any(
                            game.get("home_abbr") in favorite_teams
                            or game.get("away_abbr") in favorite_teams
                            for game in live_games
                        ):
                            live_modes.append("milb_live")
                    else:
                        live_modes.append("milb_live")

        # Check NCAA Baseball live content
        if (
            self.ncaa_baseball_enabled
            and self.ncaa_baseball_live_priority
            and hasattr(self, "ncaa_baseball_live")
        ):
            live_games = getattr(self.ncaa_baseball_live, "live_games", [])
            if live_games:
                live_games = [g for g in live_games if not g.get("is_final", False)]
                if hasattr(self.ncaa_baseball_live, "_is_game_really_over"):
                    live_games = [g for g in live_games if not self.ncaa_baseball_live._is_game_really_over(g)]

                if live_games:
                    favorite_teams = getattr(self.ncaa_baseball_live, "favorite_teams", [])
                    if favorite_teams:
                        if any(
                            game.get("home_abbr") in favorite_teams
                            or game.get("away_abbr") in favorite_teams
                            for game in live_games
                        ):
                            live_modes.append("ncaa_baseball_live")
                    else:
                        live_modes.append("ncaa_baseball_live")

        return live_modes

    def _get_game_duration(self, league: str, mode_type: str, manager=None) -> float:
        """Get game duration for a league and mode type combination.
        
        Resolves duration using the following hierarchy:
        1. Manager's game_display_duration attribute (if manager provided)
        2. League-specific mode duration (e.g., mlb.live_game_duration)
        3. League-specific default (15 seconds)
        
        Args:
            league: League name ('mlb' or 'ncaa_baseball')
            mode_type: Mode type ('live', 'recent', or 'upcoming')
            manager: Optional manager instance (if provided, checks manager's game_display_duration)
            
        Returns:
            Game duration in seconds (float)
        """
        # First, try manager's game_display_duration if available
        if manager:
            manager_duration = getattr(manager, 'game_display_duration', None)
            if manager_duration is not None:
                return float(manager_duration)
        
        # Next, try league-specific mode duration
        league_config = self.config.get(league, {})
        mode_duration_key = f"{mode_type}_game_duration"  # e.g., 'live_game_duration'
        mode_duration = league_config.get(mode_duration_key)
        if mode_duration is not None:
            return float(mode_duration)
        
        # Fallback to league-specific default (15 seconds)
        return 15.0

    def _get_mode_duration(self, mode_type: str, league: Optional[str] = None) -> Optional[float]:
        """Get mode-level duration for a specific mode type, optionally for a specific league.
        
        Resolves mode-level duration using the following hierarchy:
        1. Per-league mode duration override (if league specified, only check that league)
        2. Per-league mode duration overrides (if all enabled leagues have same value, or max if different)
        3. None (triggers dynamic calculation based on game count)
        
        Args:
            mode_type: Mode type ('live', 'recent', or 'upcoming')
            league: Optional league ID ('mlb' or 'ncaa_baseball'). If provided, only checks that league's duration.
            
        Returns:
            Mode duration in seconds (float) or None if not configured
            
        Examples:
            - _get_mode_duration('recent', 'mlb') → Returns MLB's recent_mode_duration if set
            - _get_mode_duration('recent') → Returns max of all enabled leagues or top-level
            - If recent_mode_duration=60, returns 60.0
            - If MLB has recent_mode_duration=45 and NCAA Baseball has 60, returns 60.0 (max)
            - If neither configured, returns None (use dynamic calculation)
        """
        # If specific league requested, only check that league
        if league:
            if league not in self._league_registry:
                self.logger.warning(f"Invalid league in _get_mode_duration: {league}")
                return None
            
            # Check per-league override first
            league_config = self.config.get(league, {})
            league_mode_durations = league_config.get('mode_durations', {})
            mode_duration_key = f"{mode_type}_mode_duration"  # e.g., 'recent_mode_duration'
            league_duration = league_mode_durations.get(mode_duration_key)
            if league_duration is not None:
                self.logger.debug(
                    f"_get_mode_duration({mode_type}, {league}): using per-league duration={league_duration}s"
                )
                return float(league_duration)
            
            # No mode duration configured for this league
            self.logger.debug(
                f"_get_mode_duration({mode_type}, {league}): no mode duration configured, will use dynamic calculation"
            )
            return None
        
        # No specific league - check all enabled leagues (existing logic)
        # Check for per-league overrides
        league_durations = []
        
        # Check MLB if enabled
        if self.mlb_enabled:
            mlb_config = self.config.get('mlb', {})
            mlb_mode_durations = mlb_config.get('mode_durations', {})
            mode_duration_key = f"{mode_type}_mode_duration"  # e.g., 'recent_mode_duration'
            mlb_duration = mlb_mode_durations.get(mode_duration_key)
            if mlb_duration is not None:
                league_durations.append(float(mlb_duration))

        # Check MiLB if enabled
        if self.milb_enabled:
            milb_config = self.config.get('milb', {})
            milb_mode_durations = milb_config.get('mode_durations', {})
            mode_duration_key = f"{mode_type}_mode_duration"  # e.g., 'recent_mode_duration'
            milb_duration = milb_mode_durations.get(mode_duration_key)
            if milb_duration is not None:
                league_durations.append(float(milb_duration))

        # Check NCAA Baseball if enabled
        if self.ncaa_baseball_enabled:
            ncaa_baseball_config = self.config.get('ncaa_baseball', {})
            ncaa_mode_durations = ncaa_baseball_config.get('mode_durations', {})
            mode_duration_key = f"{mode_type}_mode_duration"  # e.g., 'recent_mode_duration'
            ncaa_duration = ncaa_mode_durations.get(mode_duration_key)
            if ncaa_duration is not None:
                league_durations.append(float(ncaa_duration))
        
        # If we have per-league durations, use the maximum to ensure all leagues get their time
        if league_durations:
            max_duration = max(league_durations)
            self.logger.debug(
                f"_get_mode_duration({mode_type}): per-league durations={league_durations}, using max={max_duration}s"
            )
            return max_duration
        
        # No mode duration configured - return None to trigger dynamic calculation
        self.logger.debug(
            f"_get_mode_duration({mode_type}): no mode duration configured, will use dynamic calculation"
        )
        return None

    def _get_effective_mode_duration(self, display_mode: str, mode_type: str) -> Optional[float]:
        """Get effective mode duration integrating with dynamic duration caps.
        
        This method combines mode-level durations with dynamic duration caps to determine
        the actual duration the display controller should use for a mode.
        
        Supports granular modes (mlb_recent, ncaa_baseball_upcoming, etc.).
        
        Resolution logic:
        1. Parse display_mode to extract league from granular mode
        2. Get base mode duration from _get_mode_duration() (with league)
        3. Check if dynamic duration is enabled for this mode
        4. If both mode duration and dynamic cap are set, use minimum
        5. If only one is set, use that value
        6. If neither is set, return None (triggers dynamic calculation)
        
        Args:
            display_mode: External display mode name (e.g., 'mlb_recent', 'ncaa_baseball_upcoming', 'mlb_live')
            mode_type: Mode type ('live', 'recent', or 'upcoming')
            
        Returns:
            Effective mode duration in seconds (float) or None if not configured
            
        Examples:
            - mode_duration=60s, dynamic_cap=45s → returns 45.0
            - mode_duration=60s, no dynamic cap → returns 60.0
            - no mode_duration, dynamic_cap=45s → returns None (use dynamic calculation with cap)
            - neither set → returns None (use dynamic calculation)
        """
        # Parse display_mode to extract league if it's a granular mode
        league = None
        if "_" in display_mode and not display_mode.startswith("baseball_"):
            # Use startswith checks to correctly handle multi-underscore league IDs
            if display_mode.startswith("ncaa_baseball_"):
                league = "ncaa_baseball"
            elif display_mode.startswith("milb_"):
                league = "milb"
            elif display_mode.startswith("mlb_"):
                league = "mlb"
        
        # Get base mode duration (with league if granular mode)
        mode_duration = self._get_mode_duration(mode_type, league=league)
        
        # Check if dynamic duration is enabled and get cap
        # We need to temporarily set display context to check dynamic settings
        # Save current context
        saved_league = self._current_display_league
        saved_mode_type = self._current_display_mode_type
        
        # Set context for enabled leagues (check all enabled leagues for dynamic caps)
        dynamic_caps = []
        
        # If specific league requested (granular mode), only check that league
        if league:
            self._current_display_league = league
            self._current_display_mode_type = mode_type
            if self.supports_dynamic_duration():
                dynamic_cap = self.get_dynamic_duration_cap()
                if dynamic_cap is not None:
                    dynamic_caps.append(dynamic_cap)
        else:
            # No specific league - check all enabled leagues (combined mode)
            # Check MLB dynamic cap if enabled
            if self.mlb_enabled:
                self._current_display_league = 'mlb'
                self._current_display_mode_type = mode_type
                if self.supports_dynamic_duration():
                    dynamic_cap = self.get_dynamic_duration_cap()
                    if dynamic_cap is not None:
                        dynamic_caps.append(dynamic_cap)
            
            # Check NCAA Baseball dynamic cap if enabled

            if self.milb_enabled:
                self._current_display_league = 'milb'
                self._current_display_mode_type = mode_type
                if self.supports_dynamic_duration():
                    dynamic_cap = self.get_dynamic_duration_cap()
                    if dynamic_cap is not None:
                        dynamic_caps.append(dynamic_cap)
            
            # Check NCAA Baseball dynamic cap if enabled
            if self.ncaa_baseball_enabled:
                self._current_display_league = 'ncaa_baseball'
                self._current_display_mode_type = mode_type
                if self.supports_dynamic_duration():
                    dynamic_cap = self.get_dynamic_duration_cap()
                    if dynamic_cap is not None:
                        dynamic_caps.append(dynamic_cap)
        
        # Restore context
        self._current_display_league = saved_league
        self._current_display_mode_type = saved_mode_type
        
        # If we have dynamic caps, use the maximum (most permissive)
        effective_dynamic_cap = max(dynamic_caps) if dynamic_caps else None
        
        # Apply integration logic
        if mode_duration is not None and effective_dynamic_cap is not None:
            # Both set - use minimum
            effective_duration = min(mode_duration, effective_dynamic_cap)
            self.logger.debug(
                f"_get_effective_mode_duration({display_mode}, {mode_type}): "
                f"mode_duration={mode_duration}s, dynamic_cap={effective_dynamic_cap}s, "
                f"using min={effective_duration}s"
            )
            return effective_duration
        elif mode_duration is not None:
            # Only mode duration set
            self.logger.debug(
                f"_get_effective_mode_duration({display_mode}, {mode_type}): "
                f"using mode_duration={mode_duration}s (no dynamic cap)"
            )
            return mode_duration
        else:
            # Mode duration not set (dynamic cap might be set, but we return None
            # to trigger dynamic calculation which will apply the cap)
            self.logger.debug(
                f"_get_effective_mode_duration({display_mode}, {mode_type}): "
                f"no mode_duration (dynamic_cap={effective_dynamic_cap}), will use dynamic calculation"
            )
            return None

    def get_cycle_duration(self, display_mode: str = None) -> Optional[float]:
        """
        Calculate the expected cycle duration for a display mode based on the number of games.
        
        This implements dynamic duration scaling with support for mode-level durations:
        - Mode-level duration: Fixed total time for mode (recent_mode_duration, upcoming_mode_duration, live_mode_duration)
        - Dynamic calculation: Total duration = num_games x per_game_duration
        - For scroll mode: Duration is calculated by ScrollHelper based on content width
        
        Priority order:
        1. Mode-level duration (if configured)
        2. Dynamic calculation (if no mode-level duration)
        3. Dynamic duration cap applies to both if enabled
        
        Args:
            display_mode: The display mode to calculate duration for (e.g., 'mlb_live', 'mlb_recent', 'ncaa_baseball_upcoming')
        
        Returns:
            Total expected duration in seconds, or None if not applicable
        """
        self.logger.info(f"get_cycle_duration() called with display_mode={display_mode}, is_enabled={self.is_enabled}")
        if not self.is_enabled or not display_mode:
            self.logger.info(f"get_cycle_duration() returning None: is_enabled={self.is_enabled}, display_mode={display_mode}")
            return None
        
        # Extract mode type and league (if granular mode)
        mode_type = self._extract_mode_type(display_mode)
        if not mode_type:
            return None
        
        # Parse granular mode name if applicable (e.g., "mlb_recent", "ncaa_baseball_upcoming")
        league = None
        if "_" in display_mode and not display_mode.startswith("baseball_"):
            # Use startswith checks to correctly handle multi-underscore league IDs
            if display_mode.startswith("ncaa_baseball_"):
                league = "ncaa_baseball"
            elif display_mode.startswith("milb_"):
                league = "milb"
            elif display_mode.startswith("mlb_"):
                league = "mlb"
        
        # Check if scroll mode is active for this mode type
        if self._should_use_scroll_mode(mode_type) and self._scroll_manager:
            # Get dynamic duration from scroll manager
            scroll_duration = self._scroll_manager.get_dynamic_duration(mode_type)
            if scroll_duration > 0:
                self.logger.info(f"get_cycle_duration: scroll mode duration for {display_mode} = {scroll_duration}s")
                return float(scroll_duration)
        
        # Check for mode-level duration first (priority 1)
        effective_mode_duration = self._get_effective_mode_duration(display_mode, mode_type)
        if effective_mode_duration is not None:
            self.logger.info(
                f"get_cycle_duration: using mode-level duration for {display_mode} = {effective_mode_duration}s"
            )
            return effective_mode_duration
        
        # Fall through to dynamic calculation based on game count (priority 2)
        
        try:
            self.logger.info(f"get_cycle_duration: extracted mode_type={mode_type}, league={league} from display_mode={display_mode}")
            
            total_games = 0
            per_game_duration = self.game_display_duration  # Default fallback (will be overridden per league)
            
            # Collect managers for this mode and count their games
            managers_to_check = []
            
            # If granular mode (specific league), only check that league
            if league:
                manager = self._get_manager_for_league_mode(league, mode_type)
                if manager:
                    managers_to_check.append((league, manager))
            else:
                # Combined mode - check all enabled leagues
                if mode_type == 'live':
                    if self.mlb_enabled:
                        league_manager = self._get_manager_for_league_mode('mlb', 'live')
                        if league_manager:
                            managers_to_check.append(('mlb', league_manager))

                    if self.milb_enabled:
                        league_manager = self._get_manager_for_league_mode('milb', 'live')
                        if league_manager:
                            managers_to_check.append(('milb', league_manager))
                    if self.ncaa_baseball_enabled:
                        league_manager = self._get_manager_for_league_mode('ncaa_baseball', 'live')
                        if league_manager:
                            managers_to_check.append(('ncaa_baseball', league_manager))
                elif mode_type == 'recent':
                    if self.mlb_enabled:
                        league_manager = self._get_manager_for_league_mode('mlb', 'recent')
                        if league_manager:
                            managers_to_check.append(('mlb', league_manager))

                    if self.milb_enabled:
                        league_manager = self._get_manager_for_league_mode('milb', 'recent')
                        if league_manager:
                            managers_to_check.append(('milb', league_manager))
                    if self.ncaa_baseball_enabled:
                        league_manager = self._get_manager_for_league_mode('ncaa_baseball', 'recent')
                        if league_manager:
                            managers_to_check.append(('ncaa_baseball', league_manager))
                elif mode_type == 'upcoming':
                    if self.mlb_enabled:
                        league_manager = self._get_manager_for_league_mode('mlb', 'upcoming')
                        if league_manager:
                            managers_to_check.append(('mlb', league_manager))

                    if self.milb_enabled:
                        league_manager = self._get_manager_for_league_mode('milb', 'upcoming')
                        if league_manager:
                            managers_to_check.append(('milb', league_manager))
                    if self.ncaa_baseball_enabled:
                        league_manager = self._get_manager_for_league_mode('ncaa_baseball', 'upcoming')
                        if league_manager:
                            managers_to_check.append(('ncaa_baseball', league_manager))
            
            # CRITICAL: Update managers BEFORE checking game counts!
            self.logger.info(f"get_cycle_duration: updating {len(managers_to_check)} manager(s) before counting games")
            for league_name, manager in managers_to_check:
                if manager:
                    self._ensure_manager_updated(manager)
            
            # Count games from all applicable managers and calculate weighted duration
            # Fix: Accumulate duration per-league instead of using last league's duration
            total_duration = 0.0
            duration_breakdown = []  # For logging

            for league_name, manager in managers_to_check:
                if not manager:
                    continue

                # Get the appropriate game list based on mode type
                if mode_type == 'live':
                    games = getattr(manager, 'live_games', [])
                elif mode_type == 'recent':
                    games = getattr(manager, 'recent_games', [])
                elif mode_type == 'upcoming':
                    games = getattr(manager, 'upcoming_games', [])
                else:
                    games = []

                # Get duration for this league/mode combination
                per_game_duration = self._get_game_duration(
                    league_name, mode_type, manager
                )

                # Filter out invalid games
                if games:
                    # For live games, filter out final games
                    if mode_type == 'live':
                        games = [g for g in games if not g.get('is_final', False)]
                        if hasattr(manager, '_is_game_really_over'):
                            games = [
                                g for g in games
                                if not manager._is_game_really_over(g)
                            ]

                    game_count = len(games)
                    total_games += game_count

                    # Calculate this league's contribution to total duration
                    league_duration = game_count * per_game_duration
                    total_duration += league_duration

                    duration_breakdown.append(
                        f"{league_name}: {game_count} x {per_game_duration}s = {league_duration}s"
                    )

                    self.logger.debug(
                        f"get_cycle_duration: {league_name} {mode_type} has "
                        f"{game_count} games, per_game_duration={per_game_duration}s"
                    )

            self.logger.info(
                f"get_cycle_duration: found {total_games} total games for {display_mode}"
            )

            if total_games == 0:
                # If no games found yet, return a default duration based on config
                # Use configured game_display_duration with assumed 3 games per cycle
                default_games_per_cycle = 3
                default_duration = default_games_per_cycle * self.game_display_duration
                self.logger.info(
                    f"get_cycle_duration: {display_mode} has no games yet, "
                    f"returning default {default_duration}s ({default_games_per_cycle} x {self.game_display_duration}s)"
                )
                return default_duration

            # Apply min/max duration constraints if configured
            min_duration = self._get_duration_floor_for_mode(mode_type)
            max_duration = self._get_duration_cap_for_mode(mode_type)

            original_duration = total_duration

            if min_duration is not None and total_duration < min_duration:
                total_duration = min_duration
                self.logger.info(
                    f"get_cycle_duration: clamped {original_duration}s up to "
                    f"min_duration={min_duration}s"
                )

            if max_duration is not None and total_duration > max_duration:
                total_duration = max_duration
                self.logger.info(
                    f"get_cycle_duration: clamped {original_duration}s down to "
                    f"max_duration={max_duration}s"
                )

            # Log the breakdown for mixed leagues
            if len(duration_breakdown) > 1:
                self.logger.info(
                    f"get_cycle_duration({display_mode}): mixed leagues - "
                    f"{', '.join(duration_breakdown)} = {total_duration}s total"
                )
            else:
                self.logger.info(
                    f"get_cycle_duration: {display_mode} = {total_games} games, "
                    f"total_duration={total_duration}s"
                )

            return total_duration
            
        except Exception as e:
            self.logger.error(f"Error calculating cycle duration for {display_mode}: {e}")
            return None

    def get_info(self) -> Dict[str, Any]:
        """Get plugin information."""
        try:
            current_manager = self._get_current_manager()
            current_mode = self.modes[self.current_mode_index] if self.modes else "none"

            info = {
                "plugin_id": self.plugin_id,
                "name": "Baseball Scoreboard",
                "version": "2.0.0",
                "enabled": self.is_enabled,
                "display_size": f"{self.display_width}x{self.display_height}",
                "mlb_enabled": self.mlb_enabled,
                "milb_enabled": self.milb_enabled,
                "ncaa_baseball_enabled": self.ncaa_baseball_enabled,
                "current_mode": current_mode,
                "available_modes": self.modes,
                "display_duration": self.display_duration,
                "game_display_duration": self.game_display_duration,
                "live_priority": {
                    "mlb": self.mlb_enabled and self.mlb_live_priority,
                    "milb": self.milb_enabled and self.milb_live_priority,
                    "ncaa_baseball": self.ncaa_baseball_enabled and self.ncaa_baseball_live_priority,
                },
                "show_records": getattr(current_manager, "mode_config", {}).get(
                    "show_records"
                )
                if current_manager
                else None,
                "show_ranking": getattr(current_manager, "mode_config", {}).get(
                    "show_ranking"
                )
                if current_manager
                else None,
                "show_odds": getattr(current_manager, "mode_config", {}).get(
                    "show_odds"
                )
                if current_manager
                else None,
                "managers_initialized": {
                    "mlb_live": hasattr(self, "mlb_live"),
                    "mlb_recent": hasattr(self, "mlb_recent"),
                    "mlb_upcoming": hasattr(self, "mlb_upcoming"),
                    "milb_live": hasattr(self, "milb_live"),
                    "milb_recent": hasattr(self, "milb_recent"),
                    "milb_upcoming": hasattr(self, "milb_upcoming"),
                    "ncaa_baseball_live": hasattr(self, "ncaa_baseball_live"),
                    "ncaa_baseball_recent": hasattr(self, "ncaa_baseball_recent"),
                    "ncaa_baseball_upcoming": hasattr(self, "ncaa_baseball_upcoming"),
                },
            }

            # Add manager-specific info if available
            if current_manager and hasattr(current_manager, "get_info"):
                try:
                    manager_info = current_manager.get_info()
                    info["current_manager_info"] = manager_info
                except Exception as e:
                    info["current_manager_info"] = f"Error getting manager info: {e}"

            return info

        except Exception as e:
            self.logger.error(f"Error getting plugin info: {e}")
            return {
                "plugin_id": self.plugin_id,
                "name": "Baseball Scoreboard",
                "error": str(e),
            }

    # ------------------------------------------------------------------
    # Dynamic duration hooks
    # ------------------------------------------------------------------
    def reset_cycle_state(self) -> None:
        """Reset dynamic cycle tracking.
        
        Note: We do NOT clear start times, progress, or display_mode_to_managers
        because these need to persist across quick mode switches within the same plugin.
        The 10-second threshold in _record_dynamic_progress handles true new cycles.
        """
        super().reset_cycle_state()
        self._dynamic_cycle_seen_modes.clear()
        self._dynamic_mode_to_manager_key.clear()
        # DO NOT clear these - let the 10-second threshold in _record_dynamic_progress handle it
        # self._dynamic_manager_progress.clear()
        # self._dynamic_managers_completed.clear()
        self._dynamic_cycle_complete = False
        # DO NOT clear start times - they need to persist until full duration elapsed
        # self._single_game_manager_start_times.clear()  # Keep for duration tracking
        # self._game_id_start_times.clear()  # Keep for duration tracking
        # DO NOT clear display_mode_to_managers - the 10s threshold handles new cycles
        # self._display_mode_to_managers.clear()
        self.logger.debug("Dynamic cycle state reset - flags cleared, tracking preserved for multi-mode plugin cycle")

    def is_cycle_complete(self) -> bool:
        """Report whether the plugin has shown a full cycle of content."""
        if not self._dynamic_feature_enabled():
            return True
        
        # Check if scroll mode is active for the current display mode
        if self._current_active_display_mode:
            mode_type = self._extract_mode_type(self._current_active_display_mode)
            if mode_type and self._should_use_scroll_mode(mode_type) and self._scroll_manager:
                # For scroll mode, check ScrollHelper's completion status
                is_complete = self._scroll_manager.is_complete(mode_type)
                self.logger.info(f"is_cycle_complete() [scroll mode]: display_mode={self._current_active_display_mode}, returning {is_complete}")
                return is_complete
        
        # Pass the current active display mode to evaluate completion for the right mode
        self._evaluate_dynamic_cycle_completion(display_mode=self._current_active_display_mode)
        self.logger.info(f"is_cycle_complete() called: display_mode={self._current_active_display_mode}, returning {self._dynamic_cycle_complete}")
        return self._dynamic_cycle_complete

    def _dynamic_feature_enabled(self) -> bool:
        """Return True when dynamic duration should be active."""
        if not self.is_enabled:
            return False
        return self.supports_dynamic_duration()
    
    def supports_dynamic_duration(self) -> bool:
        """
        Check if dynamic duration is enabled for the current display context.
        Checks granular settings: per-league/per-mode > per-mode > per-league > global.
        """
        if not self.is_enabled:
            return False
        
        # If no current display context, return False (no global fallback)
        if not self._current_display_league or not self._current_display_mode_type:
            return False
        
        league = self._current_display_league
        mode_type = self._current_display_mode_type
        
        # Check per-league/per-mode setting first (most specific)
        league_config = self.config.get(league, {})
        league_dynamic = league_config.get("dynamic_duration", {})
        league_modes = league_dynamic.get("modes", {})
        mode_config = league_modes.get(mode_type, {})
        if "enabled" in mode_config:
            return bool(mode_config.get("enabled", False))
        
        # Check per-league setting
        if "enabled" in league_dynamic:
            return bool(league_dynamic.get("enabled", False))
        
        # No global fallback - return False
        return False
    
    def get_dynamic_duration_cap(self) -> Optional[float]:
        """
        Get dynamic duration cap for the current display context.
        Checks granular settings: per-league/per-mode > per-mode > per-league > global.
        """
        if not self.is_enabled:
            return None
        
        # If no current display context, return None (no global fallback)
        if not self._current_display_league or not self._current_display_mode_type:
            return None
        
        league = self._current_display_league
        mode_type = self._current_display_mode_type
        
        # Check per-league/per-mode setting first (most specific)
        league_config = self.config.get(league, {})
        league_dynamic = league_config.get("dynamic_duration", {})
        league_modes = league_dynamic.get("modes", {})
        mode_config = league_modes.get(mode_type, {})
        if "max_duration_seconds" in mode_config:
            try:
                cap = float(mode_config.get("max_duration_seconds"))
                if cap > 0:
                    return cap
            except (TypeError, ValueError):
                pass
        
        # Check per-league setting
        if "max_duration_seconds" in league_dynamic:
            try:
                cap = float(league_dynamic.get("max_duration_seconds"))
                if cap > 0:
                    return cap
            except (TypeError, ValueError):
                pass
        
        # No global fallback - return None
        return None

    def get_dynamic_duration_floor(self) -> Optional[float]:
        """
        Get dynamic duration minimum (floor) for the current display context.
        Checks granular settings: per-league/per-mode > per-league > None.

        Returns:
            Minimum duration in seconds, or None if not configured.
        """
        if not self.is_enabled:
            return None

        # If no current display context, return None
        if not self._current_display_league or not self._current_display_mode_type:
            return None

        league = self._current_display_league
        mode_type = self._current_display_mode_type

        # Check per-league/per-mode setting first (most specific)
        league_config = self.config.get(league, {})
        league_dynamic = league_config.get("dynamic_duration", {})
        league_modes = league_dynamic.get("modes", {})
        mode_config = league_modes.get(mode_type, {})
        if "min_duration_seconds" in mode_config:
            try:
                floor = float(mode_config.get("min_duration_seconds"))
                if floor > 0:
                    return floor
            except (TypeError, ValueError):
                pass

        # Check per-league setting
        if "min_duration_seconds" in league_dynamic:
            try:
                floor = float(league_dynamic.get("min_duration_seconds"))
                if floor > 0:
                    return floor
            except (TypeError, ValueError):
                pass

        # No global fallback - return None
        return None

    def _get_duration_floor_for_mode(self, mode_type: str) -> Optional[float]:
        """
        Get the minimum duration floor for a mode type across all enabled leagues.

        When both MLB and NCAA Baseball are enabled, returns the highest min_duration
        configured across the enabled leagues (most restrictive floor).

        Args:
            mode_type: Mode type ('live', 'recent', or 'upcoming')

        Returns:
            Minimum duration in seconds, or None if not configured.
        """
        floors = []

        for league in ['mlb', 'milb', 'ncaa_baseball']:
            league_config = self.config.get(league, {})
            if not league_config.get('enabled', False):
                continue

            league_dynamic = league_config.get("dynamic_duration", {})
            league_modes = league_dynamic.get("modes", {})
            mode_config = league_modes.get(mode_type, {})

            # Check per-mode setting first
            if "min_duration_seconds" in mode_config:
                try:
                    floor = float(mode_config.get("min_duration_seconds"))
                    if floor > 0:
                        floors.append(floor)
                        continue
                except (TypeError, ValueError):
                    pass

            # Check per-league setting
            if "min_duration_seconds" in league_dynamic:
                try:
                    floor = float(league_dynamic.get("min_duration_seconds"))
                    if floor > 0:
                        floors.append(floor)
                except (TypeError, ValueError):
                    pass

        # Return the highest floor (most restrictive)
        return max(floors) if floors else None

    def _get_duration_cap_for_mode(self, mode_type: str) -> Optional[float]:
        """
        Get the maximum duration cap for a mode type across all enabled leagues.

        When both MLB and NCAA Baseball are enabled, returns the lowest max_duration
        configured across the enabled leagues (most restrictive cap).

        Args:
            mode_type: Mode type ('live', 'recent', or 'upcoming')

        Returns:
            Maximum duration in seconds, or None if not configured.
        """
        caps = []

        for league in ['mlb', 'milb', 'ncaa_baseball']:
            league_config = self.config.get(league, {})
            if not league_config.get('enabled', False):
                continue

            league_dynamic = league_config.get("dynamic_duration", {})
            league_modes = league_dynamic.get("modes", {})
            mode_config = league_modes.get(mode_type, {})

            # Check per-mode setting first
            if "max_duration_seconds" in mode_config:
                try:
                    cap = float(mode_config.get("max_duration_seconds"))
                    if cap > 0:
                        caps.append(cap)
                        continue
                except (TypeError, ValueError):
                    pass

            # Check per-league setting
            if "max_duration_seconds" in league_dynamic:
                try:
                    cap = float(league_dynamic.get("max_duration_seconds"))
                    if cap > 0:
                        caps.append(cap)
                except (TypeError, ValueError):
                    pass

        # Return the lowest cap (most restrictive)
        return min(caps) if caps else None

    def _get_manager_for_mode(self, mode_name: str):
        """Resolve manager instance for a given display mode."""
        if mode_name.startswith("mlb_"):
            if not self.mlb_enabled:
                return None
            suffix = mode_name.split("_", 1)[1]
            if suffix == "live":
                return getattr(self, "mlb_live", None)
            if suffix == "recent":
                return getattr(self, "mlb_recent", None)
            if suffix == "upcoming":
                return getattr(self, "mlb_upcoming", None)
        elif mode_name.startswith("milb_"):
            if not self.milb_enabled:
                return None
            suffix = mode_name[len("milb_"):]
            if suffix == "live":
                return getattr(self, "milb_live", None)
            if suffix == "recent":
                return getattr(self, "milb_recent", None)
            if suffix == "upcoming":
                return getattr(self, "milb_upcoming", None)
        elif mode_name.startswith("ncaa_baseball_"):
            if not self.ncaa_baseball_enabled:
                return None
            suffix = mode_name[len("ncaa_baseball_"):]
            if suffix == "live":
                return getattr(self, "ncaa_baseball_live", None)
            if suffix == "recent":
                return getattr(self, "ncaa_baseball_recent", None)
            if suffix == "upcoming":
                return getattr(self, "ncaa_baseball_upcoming", None)
        return None

    def _get_manager_for_league_mode(self, league: str, mode_type: str):
        """Get manager instance for a league and mode type combination.
        
        Args:
            league: 'mlb', 'milb', or 'ncaa_baseball'
            mode_type: 'live', 'recent', or 'upcoming'
            
        Returns:
            Manager instance or None if not available/enabled
        """
        if league == 'mlb' and not self.mlb_enabled:
            return None
        if league == 'milb' and not self.milb_enabled:
            return None
        if league == 'ncaa_baseball' and not self.ncaa_baseball_enabled:
            return None
        
        attr_name = f"{league}_{mode_type}"
        return getattr(self, attr_name, None) if hasattr(self, attr_name) else None

    def _has_live_games_for_manager(self, manager) -> bool:
        """Check if a manager has valid live games (for favorite teams if configured).

        Args:
            manager: Manager instance to check

        Returns:
            True if manager has live games that should be displayed
        """
        manager_name = getattr(manager, 'sport_key', type(manager).__name__)

        if not manager:
            self.logger.debug("[LIVE_PRIORITY_DEBUG] _has_live_games_for_manager: manager is None")
            return False

        raw_live_games = getattr(manager, 'live_games', [])
        self.logger.debug(
            f"[LIVE_PRIORITY_DEBUG] _has_live_games_for_manager({manager_name}): "
            f"raw live_games count = {len(raw_live_games)}"
        )

        if not raw_live_games:
            self.logger.debug(
                f"[LIVE_PRIORITY_DEBUG] _has_live_games_for_manager({manager_name}): "
                f"returning False - no raw live games"
            )
            return False

        # Filter out games that are final or appear over
        live_games = [g for g in raw_live_games if not g.get('is_final', False)]
        games_after_final_filter = len(live_games)
        self.logger.debug(
            f"[LIVE_PRIORITY_DEBUG] _has_live_games_for_manager({manager_name}): "
            f"after is_final filter = {games_after_final_filter} games"
        )

        if hasattr(manager, '_is_game_really_over'):
            games_before = len(live_games)
            live_games = [g for g in live_games if not manager._is_game_really_over(g)]
            self.logger.debug(
                f"[LIVE_PRIORITY_DEBUG] _has_live_games_for_manager({manager_name}): "
                f"after _is_game_really_over filter = {len(live_games)} games (removed {games_before - len(live_games)})"
            )

        if not live_games:
            self.logger.debug(
                f"[LIVE_PRIORITY_DEBUG] _has_live_games_for_manager({manager_name}): "
                f"returning False - no live games after filtering"
            )
            return False

        # If favorite teams are configured, only return True if there are live games for favorite teams
        favorite_teams = getattr(manager, 'favorite_teams', [])
        self.logger.debug(
            f"[LIVE_PRIORITY_DEBUG] _has_live_games_for_manager({manager_name}): "
            f"favorite_teams = {favorite_teams}"
        )

        if favorite_teams:
            # Log each game's match status
            for game in live_games:
                home = game.get('home_abbr')
                away = game.get('away_abbr')
                home_match = home in favorite_teams
                away_match = away in favorite_teams
                self.logger.debug(
                    f"[LIVE_PRIORITY_DEBUG] _has_live_games_for_manager({manager_name}): "
                    f"checking {away}@{home} - home_in_favorites={home_match}, away_in_favorites={away_match}"
                )

            has_favorite_live = any(
                game.get('home_abbr') in favorite_teams
                or game.get('away_abbr') in favorite_teams
                for game in live_games
            )
            self.logger.debug(
                f"[LIVE_PRIORITY_DEBUG] _has_live_games_for_manager({manager_name}): "
                f"returning {has_favorite_live} - has_favorite_live check"
            )
            return has_favorite_live

        # No favorite teams configured, any live game counts
        self.logger.debug(
            f"[LIVE_PRIORITY_DEBUG] _has_live_games_for_manager({manager_name}): "
            f"returning True - no favorites configured, {len(live_games)} live games exist"
        )
        return True

    def _filter_managers_by_live_content(self, managers: list, mode_type: str) -> list:
        """Filter managers based on live content when in live mode.
        
        Args:
            managers: List of manager instances
            mode_type: 'live', 'recent', or 'upcoming'
            
        Returns:
            Filtered list of managers with live content (for live mode) or original list
        """
        if mode_type != 'live':
            return managers
        
        # For live mode, only include managers with actual live games
        filtered = []
        for manager in managers:
            if self._has_live_games_for_manager(manager):
                filtered.append(manager)
        
        return filtered

    def _resolve_managers_for_mode(self, mode_type: str) -> list:
        """
        Resolve ordered list of managers to try for a given mode type.
        
        This method uses the league registry to get managers in priority order,
        respecting both league-level and mode-level enabling/disabling.
        
        For live mode, it also respects live_priority settings and filters
        to only include managers with actual live games.
        
        Args:
            mode_type: 'live', 'recent', or 'upcoming'
            
        Returns:
            Ordered list of manager instances to try (in priority order)
            Managers are filtered based on:
            - League enabled state
            - Mode enabled state for that league (show_live, show_recent, show_upcoming)
            - For live mode: live_priority and actual live games availability
        """
        managers_to_try = []
        
        # Get enabled leagues for this mode type in priority order
        # This already respects league-level and mode-level enabling
        enabled_leagues = self._get_enabled_leagues_for_mode(mode_type)
        
        if mode_type == 'live':
            # For live mode, update managers first to get current live games
            # This ensures we have fresh data before checking for live content
            for league_id in enabled_leagues:
                manager = self._get_league_manager_for_mode(league_id, 'live')
                if manager:
                    try:
                        manager.update()
                    except Exception as e:
                        self.logger.debug(f"Error updating {league_id} live manager: {e}")
            
            # For live mode, respect live_priority settings
            # Only include managers with live_priority enabled AND actual live games
            for league_id in enabled_leagues:
                league_data = self._league_registry.get(league_id, {})
                live_priority = league_data.get('live_priority', False)
                
                manager = self._get_league_manager_for_mode(league_id, 'live')
                if not manager:
                    continue
                
                # If live_priority is enabled, only include if manager has live games
                if live_priority:
                    if self._has_live_games_for_manager(manager):
                        managers_to_try.append(manager)
                        self.logger.debug(
                            f"{league_id} has live games and live_priority - adding to list"
                        )
                else:
                    # No live_priority - include manager anyway (fallback)
                    managers_to_try.append(manager)
                    self.logger.debug(
                        f"{league_id} live manager added (no live_priority requirement)"
                    )
            
            # If no managers found with live_priority, fall back to all enabled managers
            # This ensures we always have something to show if leagues are enabled
            if not managers_to_try:
                for league_id in enabled_leagues:
                    manager = self._get_league_manager_for_mode(league_id, 'live')
                    if manager:
                        managers_to_try.append(manager)
                        self.logger.debug(
                            f"Fallback: added {league_id} live manager (no live_priority managers found)"
                        )
        else:
            # For recent and upcoming modes, use standard priority order
            # Get managers for each enabled league in priority order
            for league_id in enabled_leagues:
                manager = self._get_league_manager_for_mode(league_id, mode_type)
                if manager:
                    managers_to_try.append(manager)
                    self.logger.debug(
                        f"Added {league_id} {mode_type} manager to list "
                        f"(priority: {self._league_registry[league_id].get('priority', 999)})"
                    )
        
        self.logger.debug(
            f"Resolved {len(managers_to_try)} manager(s) for {mode_type} mode: "
            f"{[m.__class__.__name__ for m in managers_to_try]}"
        )
        
        return managers_to_try

    def _extract_mode_type(self, display_mode: str) -> Optional[str]:
        """Extract mode type (live, recent, upcoming) from display mode string.
        
        Args:
            display_mode: Display mode string (e.g., 'mlb_live', 'mlb_recent', 'ncaa_baseball_upcoming')
            
        Returns:
            Mode type string ('live', 'recent', 'upcoming') or None
        """
        if display_mode.endswith('_live'):
            return 'live'
        elif display_mode.endswith('_recent'):
            return 'recent'
        elif display_mode.endswith('_upcoming'):
            return 'upcoming'
        return None

    def _set_display_context_from_manager(self, manager, mode_type: str) -> None:
        """Set current display league and mode type based on manager instance.
        
        Args:
            manager: Manager instance
            mode_type: 'live', 'recent', or 'upcoming'
        """
        self._current_display_mode_type = mode_type
        
        if manager in (getattr(self, 'mlb_live', None),
                      getattr(self, 'mlb_recent', None),
                      getattr(self, 'mlb_upcoming', None)):
            self._current_display_league = 'mlb'
        elif manager in (getattr(self, 'milb_live', None),
                        getattr(self, 'milb_recent', None),
                        getattr(self, 'milb_upcoming', None)):
            self._current_display_league = 'milb'
        elif manager in (getattr(self, 'ncaa_baseball_live', None),
                        getattr(self, 'ncaa_baseball_recent', None),
                        getattr(self, 'ncaa_baseball_upcoming', None)):
            self._current_display_league = 'ncaa_baseball'

    def _track_single_game_progress(self, manager_key: str, manager, league: str, mode_type: str) -> None:
        """Track progress for a manager with a single game (or no games).
        
        Args:
            manager_key: Unique key identifying this manager
            manager: Manager instance
            league: League name ('mlb' or 'ncaa_baseball')
            mode_type: Mode type ('live', 'recent', or 'upcoming')
        """
        current_time = time.time()
        
        if manager_key not in self._single_game_manager_start_times:
            # First time seeing this single-game manager (in this cycle) - record start time
            self._single_game_manager_start_times[manager_key] = current_time
            game_duration = self._get_game_duration(league, mode_type, manager) if league and mode_type else getattr(manager, 'game_display_duration', 15)
            self.logger.info(f"Single-game manager {manager_key} first seen at {current_time:.2f}, will complete after {game_duration}s")
        else:
            # Check if enough time has passed
            start_time = self._single_game_manager_start_times[manager_key]
            game_duration = self._get_game_duration(league, mode_type, manager) if league and mode_type else getattr(manager, 'game_display_duration', 15)
            elapsed = current_time - start_time
            if elapsed >= game_duration:
                # Enough time has passed - mark as complete
                if manager_key not in self._dynamic_managers_completed:
                    self._dynamic_managers_completed.add(manager_key)
                    self.logger.info(f"Single-game manager {manager_key} completed after {elapsed:.2f}s (required: {game_duration}s)")
                    # Clean up start time now that manager has completed
                    if manager_key in self._single_game_manager_start_times:
                        del self._single_game_manager_start_times[manager_key]
            else:
                # Still waiting
                self.logger.debug(f"Single-game manager {manager_key} waiting: {elapsed:.2f}s/{game_duration}s (start_time={start_time:.2f}, current_time={current_time:.2f})")

    def _record_dynamic_progress(self, current_manager, actual_mode: str = None, display_mode: str = None) -> None:
        """Track progress through managers/games for dynamic duration."""
        if not self._dynamic_feature_enabled() or not self.modes:
            self._dynamic_cycle_complete = True
            return

        # Use actual_mode if provided (when display_mode is specified), otherwise use internal mode cycling
        if actual_mode:
            current_mode = actual_mode
        else:
            current_mode = self.modes[self.current_mode_index]
        
        # Track both the internal mode and the external display mode if provided
        self._dynamic_cycle_seen_modes.add(current_mode)
        if display_mode and display_mode != current_mode:
            # Also track the external display mode for proper completion checking
            self._dynamic_cycle_seen_modes.add(display_mode)

        manager_key = self._build_manager_key(current_mode, current_manager)
        self._dynamic_mode_to_manager_key[current_mode] = manager_key
        
        # Extract league and mode_type from current_mode for duration lookups
        league = None
        mode_type = None
        if current_mode:
            if current_mode.startswith('mlb_'):
                league = 'mlb'
                mode_type = current_mode.split('_', 1)[1]
            elif current_mode.startswith('milb_'):
                league = 'milb'
                mode_type = current_mode.split('_', 1)[1]
            elif current_mode.startswith('ncaa_baseball_'):
                league = 'ncaa_baseball'
                mode_type = current_mode.split('_', 2)[2]
        
        # Log for debugging
        self.logger.debug(f"_record_dynamic_progress: current_mode={current_mode}, display_mode={display_mode}, manager={current_manager.__class__.__name__}, manager_key={manager_key}, _last_display_mode={self._last_display_mode}")

        total_games = self._get_total_games_for_manager(current_manager)
        
        # Check if this is a new cycle for this display mode BEFORE adding to tracking
        # A "new cycle" means we're returning to a mode after having been away (different mode)
        # Only track external display_mode (from display controller), not internal mode cycling
        is_new_cycle = False
        current_time = time.time()
        
        # Only track mode changes for external calls (where display_mode differs from actual_mode)
        # This prevents internal mode cycling from triggering new cycle detection
        is_external_call = (display_mode and actual_mode and display_mode != actual_mode)
        
        if is_external_call:
            # External call from display controller - check for mode switches
            # Only treat as "new cycle" if we've been away for a while (> 10s)
            # This allows cycling through recent→upcoming→live→recent without clearing state
            NEW_CYCLE_THRESHOLD = 10.0  # seconds
            
            if display_mode != self._last_display_mode:
                # Switched to a different external mode
                time_since_last = current_time - self._last_display_mode_time if self._last_display_mode_time > 0 else 999
                
                # Only treat as new cycle if we've been away for a while OR this is the first time
                if time_since_last >= NEW_CYCLE_THRESHOLD:
                    is_new_cycle = True
                    self.logger.info(f"New cycle detected for {display_mode}: switched from {self._last_display_mode} (last seen {time_since_last:.1f}s ago)")
                else:
                    # Quick mode switch within same overall cycle - don't reset
                    self.logger.debug(f"Quick mode switch to {display_mode} from {self._last_display_mode} ({time_since_last:.1f}s ago) - continuing cycle")
            elif manager_key not in self._display_mode_to_managers.get(display_mode, set()):
                # Same external mode but manager not tracked yet - could be multi-league setup
                self.logger.debug(f"Manager {manager_key} not yet tracked for current mode {display_mode}")
            else:
                # Same mode and manager already tracked - continue within current cycle
                self.logger.debug(f"Continuing cycle for {display_mode}: manager {manager_key} already tracked")
            
            # Update last display mode tracking (only for external calls)
            self._last_display_mode = display_mode
            self._last_display_mode_time = current_time
            
            # ONLY reset state if this is truly a new cycle (after threshold)
            if is_new_cycle:
                # New cycle starting - reset ALL state for this manager to start completely fresh
                if manager_key in self._single_game_manager_start_times:
                    old_start = self._single_game_manager_start_times[manager_key]
                    self.logger.info(f"New cycle for {display_mode}: resetting start time for {manager_key} (old: {old_start:.2f})")
                    del self._single_game_manager_start_times[manager_key]
                # Also remove from completed set so it can be tracked fresh in this cycle
                if manager_key in self._dynamic_managers_completed:
                    self.logger.info(f"New cycle for {display_mode}: removing {manager_key} from completed set")
                    self._dynamic_managers_completed.discard(manager_key)
                # Also clear any game ID start times for this manager
                if manager_key in self._game_id_start_times:
                    self.logger.info(f"New cycle for {display_mode}: clearing game ID start times for {manager_key}")
                    del self._game_id_start_times[manager_key]
                # Clear progress tracking for this manager
                if manager_key in self._dynamic_manager_progress:
                    self.logger.info(f"New cycle for {display_mode}: clearing progress for {manager_key}")
                    self._dynamic_manager_progress[manager_key].clear()
        
        # Now add to tracking AFTER checking for new cycle
        if display_mode and display_mode != current_mode:
            # Store mapping from display_mode to manager_key for completion checking
            self._display_mode_to_managers.setdefault(display_mode, set()).add(manager_key)
        
        if total_games <= 1:
            # Single (or no) game - wait for full game display duration before marking complete
            self._track_single_game_progress(manager_key, current_manager, league, mode_type)
            return

        # Get current game to extract its ID for tracking
        current_game = getattr(current_manager, "current_game", None)
        if not current_game:
            # No current game - can't track progress, but this is valid (empty game list)
            self.logger.debug(f"No current_game in manager {manager_key}, skipping progress tracking")
            # Still mark the mode as seen even if no content
            return
        
        # Use game ID for tracking instead of index to persist across game order changes
        game_id = current_game.get('id')
        if not game_id:
            # Fallback to index if game ID not available (shouldn't happen, but safety first)
            current_index = getattr(current_manager, "current_game_index", 0)
            # Also try to get a unique identifier from game data
            away_abbr = current_game.get('away_abbr', '')
            home_abbr = current_game.get('home_abbr', '')
            if away_abbr and home_abbr:
                game_id = f"{away_abbr}@{home_abbr}-{current_index}"
            else:
                game_id = f"index-{current_index}"
            self.logger.warning(f"Game ID not found for manager {manager_key}, using fallback: {game_id}")
        
        # Ensure game_id is a string for consistent tracking
        game_id = str(game_id)
        
        progress_set = self._dynamic_manager_progress.setdefault(manager_key, set())
        
        # Track when this game ID was first seen
        game_times = self._game_id_start_times.setdefault(manager_key, {})
        if game_id not in game_times:
            # First time seeing this game - record start time
            game_times[game_id] = time.time()
            game_duration = self._get_game_duration(league, mode_type, current_manager) if league and mode_type else getattr(current_manager, 'game_display_duration', 15)
            game_display = f"{current_game.get('away_abbr', '?')}@{current_game.get('home_abbr', '?')}"
            self.logger.info(f"Game {game_display} (ID: {game_id}) in manager {manager_key} first seen, will complete after {game_duration}s")
        
        # Check if this game has been shown for full duration
        start_time = game_times[game_id]
        game_duration = self._get_game_duration(league, mode_type, current_manager) if league and mode_type else getattr(current_manager, 'game_display_duration', 15)
        elapsed = time.time() - start_time
        
        if elapsed >= game_duration:
            # This game has been shown for full duration - add to progress set
            if game_id not in progress_set:
                progress_set.add(game_id)
                game_display = f"{current_game.get('away_abbr', '?')}@{current_game.get('home_abbr', '?')}"
                self.logger.info(f"Game {game_display} (ID: {game_id}) in manager {manager_key} completed after {elapsed:.2f}s (required: {game_duration}s)")
        else:
            # Still waiting for this game to complete its duration
            self.logger.debug(f"Game ID {game_id} in manager {manager_key} waiting: {elapsed:.2f}s/{game_duration}s")

        # Get all valid game IDs from current game list to clean up stale entries
        valid_game_ids = self._get_all_game_ids_for_manager(current_manager)
        
        # Clean up progress set and start times for games that no longer exist
        if valid_game_ids:
            # Remove game IDs from progress set that are no longer in the game list
            progress_set.intersection_update(valid_game_ids)
            # Also clean up start times for games that no longer exist
            game_times = {k: v for k, v in game_times.items() if k in valid_game_ids}
            self._game_id_start_times[manager_key] = game_times
        elif total_games == 0:
            # No games in list - clear all tracking for this manager
            progress_set.clear()
            game_times.clear()
            self._game_id_start_times[manager_key] = {}

        # Only mark manager complete when all current games have been shown for their full duration
        # Use the actual current game IDs, not just the count, to handle dynamic game lists
        current_game_ids = self._get_all_game_ids_for_manager(current_manager)
        
        if current_game_ids:
            # Check if all current games have been shown for full duration
            if current_game_ids.issubset(progress_set):
                if manager_key not in self._dynamic_managers_completed:
                    self._dynamic_managers_completed.add(manager_key)
                    self.logger.info(f"Manager {manager_key} completed - all {len(current_game_ids)} games shown for full duration (progress: {len(progress_set)} game IDs)")
            else:
                missing_count = len(current_game_ids - progress_set)
                self.logger.debug(f"Manager {manager_key} incomplete - {missing_count} of {len(current_game_ids)} games not yet shown for full duration")
        elif total_games == 0:
            # Empty game list - mark as complete immediately
            if manager_key not in self._dynamic_managers_completed:
                self._dynamic_managers_completed.add(manager_key)
                self.logger.debug(f"Manager {manager_key} completed - no games to display")

    def _evaluate_dynamic_cycle_completion(self, display_mode: str = None) -> None:
        """
        Determine whether all enabled leagues have completed their cycles for a display mode.
        
        For sequential block display, a display mode cycle is complete when:
        - All enabled leagues for that mode type have completed showing all their games
        - Each league is tracked separately via manager keys
        
        This method checks completion status for all leagues that were used for
        the given display mode, ensuring both MLB and NCAA Baseball (and future leagues)
        have completed before marking the cycle as complete.
        
        Args:
            display_mode: External display mode name (e.g., 'mlb_recent' or 'ncaa_baseball_recent')
                         If None, checks internal mode cycling completion
        """
        if not self._dynamic_feature_enabled():
            self._dynamic_cycle_complete = True
            return

        if not self.modes:
            self._dynamic_cycle_complete = True
            return

        # If display_mode is provided, check all managers used for that display mode
        # This handles multi-league scenarios where we need all leagues to complete
        if display_mode and display_mode in self._display_mode_to_managers:
            used_manager_keys = self._display_mode_to_managers[display_mode]
            if not used_manager_keys:
                # No managers were used for this display mode yet - cycle not complete
                self._dynamic_cycle_complete = False
                self.logger.debug(f"Display mode {display_mode} has no managers tracked yet - cycle incomplete")
                return
            
            # Extract mode type to get enabled leagues for comparison
            mode_type = self._extract_mode_type(display_mode)
            enabled_leagues = self._get_enabled_leagues_for_mode(mode_type) if mode_type else []
            
            self.logger.info(
                f"_evaluate_dynamic_cycle_completion for {display_mode}: "
                f"checking {len(used_manager_keys)} manager(s): {used_manager_keys}, "
                f"enabled leagues: {enabled_leagues}"
            )
            
            # Check if all managers used for this display mode have completed
            incomplete_managers = []
            for manager_key in used_manager_keys:
                if manager_key not in self._dynamic_managers_completed:
                    incomplete_managers.append(manager_key)
                    # Get the manager to check its state for logging and potential completion
                    # Extract mode and manager class from manager_key (format: "mode:ManagerClass")
                    parts = manager_key.split(':', 1)
                    if len(parts) == 2:
                        mode_name, manager_class_name = parts
                        manager = self._get_manager_for_mode(mode_name)
                        if manager and manager.__class__.__name__ == manager_class_name:
                            total_games = self._get_total_games_for_manager(manager)
                            if total_games <= 1:
                                # Single-game manager - check time
                                if manager_key in self._single_game_manager_start_times:
                                    start_time = self._single_game_manager_start_times[manager_key]
                                    # Extract league and mode_type from mode_name
                                    league = 'mlb' if mode_name.startswith('mlb_') else ('milb' if mode_name.startswith('milb_') else ('ncaa_baseball' if mode_name.startswith('ncaa_baseball_') else None))
                                    mode_type = mode_name.split('_')[-1] if mode_name else None
                                    game_duration = self._get_game_duration(league, mode_type, manager) if league and mode_type else getattr(manager, 'game_display_duration', 15)
                                    current_time = time.time()
                                    elapsed = current_time - start_time
                                    if elapsed >= game_duration:
                                        self._dynamic_managers_completed.add(manager_key)
                                        incomplete_managers.remove(manager_key)
                                        self.logger.info(f"Manager {manager_key} marked complete in completion check: {elapsed:.2f}s >= {game_duration}s")
                                        # Clean up start time now that manager has completed
                                        if manager_key in self._single_game_manager_start_times:
                                            del self._single_game_manager_start_times[manager_key]
                                    else:
                                        self.logger.debug(f"Manager {manager_key} waiting in completion check: {elapsed:.2f}s/{game_duration}s (start_time={start_time:.2f}, current_time={current_time:.2f})")
                                else:
                                    # Manager not yet seen - keep it incomplete
                                    # This means _record_dynamic_progress hasn't been called yet for this manager
                                    # or the state was reset, so we can't determine completion
                                    self.logger.debug(f"Manager {manager_key} not yet seen in completion check (not in start_times) - keeping incomplete")
                                    # Don't remove from incomplete_managers - it stays incomplete
                            else:
                                # Multi-game manager - check if all current games have been shown for full duration
                                progress_set = self._dynamic_manager_progress.get(manager_key, set())
                                current_game_ids = self._get_all_game_ids_for_manager(manager)
                                
                                # Check if all current games are in the progress set (shown for full duration)
                                if current_game_ids and current_game_ids.issubset(progress_set):
                                    self._dynamic_managers_completed.add(manager_key)
                                    incomplete_managers.remove(manager_key)
                                else:
                                    missing_games = current_game_ids - progress_set
                                    self.logger.debug(f"Manager {manager_key} progress: {len(progress_set)}/{len(current_game_ids)} games completed, missing: {len(missing_games)}")
            
            self.logger.info(f"_evaluate_dynamic_cycle_completion for {display_mode}: incomplete_managers={incomplete_managers}, completed={[k for k in used_manager_keys if k in self._dynamic_managers_completed]}")
            
            if not incomplete_managers:
                # All managers have completed - but verify they actually completed in THIS cycle
                # Check that all managers either:
                # 1. Are in _dynamic_managers_completed AND have no start time (truly completed)
                # 2. Or have a start time that has elapsed (completed in this check)
                all_truly_completed = True
                for manager_key in used_manager_keys:
                    # If manager has a start time, it hasn't completed yet (or just completed)
                    if manager_key in self._single_game_manager_start_times:
                        # Still has start time - check if it should be completed
                        parts = manager_key.split(':', 1)
                        if len(parts) == 2:
                            mode_name, manager_class_name = parts
                            manager = self._get_manager_for_mode(mode_name)
                            if manager and manager.__class__.__name__ == manager_class_name:
                                start_time = self._single_game_manager_start_times[manager_key]
                                # Extract league and mode_type from mode_name
                                league = 'mlb' if mode_name.startswith('mlb_') else ('milb' if mode_name.startswith('milb_') else ('ncaa_baseball' if mode_name.startswith('ncaa_baseball_') else None))
                                mode_type = mode_name.split('_')[-1] if mode_name else None
                                game_duration = self._get_game_duration(league, mode_type, manager) if league and mode_type else getattr(manager, 'game_display_duration', 15)
                                elapsed = time.time() - start_time
                                if elapsed < game_duration:
                                    # Not enough time has passed - not truly completed
                                    all_truly_completed = False
                                    self.logger.debug(f"Manager {manager_key} in completed set but still has start time with {elapsed:.2f}s < {game_duration}s")
                                    break
                
                if all_truly_completed:
                    self._dynamic_cycle_complete = True
                    self.logger.info(f"Display mode {display_mode} cycle complete - all {len(used_manager_keys)} manager(s) completed")
                    
                    # Reset mode start time since full cycle is complete
                    # This ensures next cycle starts timing from beginning
                    if display_mode in self._mode_start_time:
                        del self._mode_start_time[display_mode]
                        self.logger.debug(f"Reset mode start time for {display_mode} (full cycle complete)")
                else:
                    # Some managers aren't truly completed - keep cycle incomplete
                    self._dynamic_cycle_complete = False
                    self.logger.debug(f"Display mode {display_mode} cycle incomplete - some managers not truly completed yet")
            else:
                self._dynamic_cycle_complete = False
                self.logger.debug(f"Display mode {display_mode} cycle incomplete - {len(incomplete_managers)} manager(s) still in progress: {incomplete_managers}")
            return

        # Standard mode checking (for internal mode cycling)
        required_modes = [mode for mode in self.modes if mode]
        if not required_modes:
            self._dynamic_cycle_complete = True
            return

        for mode_name in required_modes:
            if mode_name not in self._dynamic_cycle_seen_modes:
                self._dynamic_cycle_complete = False
                return

            manager_key = self._dynamic_mode_to_manager_key.get(mode_name)
            if not manager_key:
                self._dynamic_cycle_complete = False
                return

            if manager_key not in self._dynamic_managers_completed:
                manager = self._get_manager_for_mode(mode_name)
                total_games = self._get_total_games_for_manager(manager)
                if total_games <= 1:
                    # For single-game managers, check if enough time has passed
                    if manager_key in self._single_game_manager_start_times:
                        start_time = self._single_game_manager_start_times[manager_key]
                        # Extract league and mode_type from mode_name
                        league = 'mlb' if mode_name.startswith('mlb_') else ('milb' if mode_name.startswith('milb_') else ('ncaa_baseball' if mode_name.startswith('ncaa_baseball_') else None))
                        mode_type = mode_name.split('_')[-1] if mode_name else None
                        game_duration = self._get_game_duration(league, mode_type, manager) if (league and mode_type and manager) else (getattr(manager, 'game_display_duration', 15) if manager else 15)
                        elapsed = time.time() - start_time
                        if elapsed >= game_duration:
                            self._dynamic_managers_completed.add(manager_key)
                        else:
                            # Not enough time yet
                            self._dynamic_cycle_complete = False
                            return
                    else:
                        # Haven't seen this manager yet in _record_dynamic_progress
                        self._dynamic_cycle_complete = False
                        return
                else:
                    # Multi-game manager - check if all current games have been shown for full duration
                    progress_set = self._dynamic_manager_progress.get(manager_key, set())
                    current_game_ids = self._get_all_game_ids_for_manager(manager)
                    
                    # Check if all current games are in the progress set (shown for full duration)
                    if current_game_ids and current_game_ids.issubset(progress_set):
                        self._dynamic_managers_completed.add(manager_key)
                        # Continue to check other modes
                    else:
                        missing_games = current_game_ids - progress_set if current_game_ids else set()
                        self.logger.debug(f"Manager {manager_key} progress: {len(progress_set)}/{len(current_game_ids)} games completed, missing: {len(missing_games)}")
                        self._dynamic_cycle_complete = False
                        return

        self._dynamic_cycle_complete = True

    @staticmethod
    def _build_manager_key(mode_name: str, manager) -> str:
        manager_name = manager.__class__.__name__ if manager else "None"
        return f"{mode_name}:{manager_name}"

    @staticmethod
    def _get_total_games_for_manager(manager) -> int:
        if manager is None:
            return 0
        for attr in ("live_games", "games_list", "recent_games", "upcoming_games"):
            value = getattr(manager, attr, None)
            if isinstance(value, list):
                return len(value)
        return 0
    
    @staticmethod
    def _get_all_game_ids_for_manager(manager) -> set:
        """Get all game IDs from a manager's game list."""
        if manager is None:
            return set()
        game_ids = set()
        for attr in ("live_games", "games_list", "recent_games", "upcoming_games"):
            game_list = getattr(manager, attr, None)
            if isinstance(game_list, list) and game_list:
                for i, game in enumerate(game_list):
                    game_id = game.get('id')
                    if game_id:
                        game_ids.add(str(game_id))
                    else:
                        # Fallback to index-based identifier if ID missing
                        away_abbr = game.get('away_abbr', '')
                        home_abbr = game.get('home_abbr', '')
                        if away_abbr and home_abbr:
                            game_ids.add(f"{away_abbr}@{home_abbr}-{i}")
                        else:
                            game_ids.add(f"index-{i}")
                break
        return game_ids

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

        # Refresh internal managers/cache so Vegas has up-to-date content
        try:
            if hasattr(self, 'update') and callable(self.update):
                self.update()
                self.logger.debug("[Baseball Vegas] Refreshed managers via update()")
            elif hasattr(self, 'refresh_managers') and callable(self.refresh_managers):
                self.refresh_managers()
                self.logger.debug("[Baseball Vegas] Refreshed managers via refresh_managers()")
            elif hasattr(self, '_update') and callable(self._update):
                self._update()
                self.logger.debug("[Baseball Vegas] Refreshed managers via _update()")
        except Exception as e:
            self.logger.debug(f"[Baseball Vegas] Manager refresh failed (non-fatal): {e}")

        # Collect all games (live, recent, upcoming) organized by league
        games, leagues = self._collect_games_for_scroll(live_priority_active=False)

        if not games:
            self.logger.debug("[Baseball Vegas] No games available")
            return

        # Count games by type for logging
        game_type_counts = {'live': 0, 'recent': 0, 'upcoming': 0}
        for game in games:
            state = game.get('status', {}).get('state', '')
            if state == 'in':
                game_type_counts['live'] += 1
            elif state == 'post':
                game_type_counts['recent'] += 1
            elif state == 'pre':
                game_type_counts['upcoming'] += 1

        # Get rankings cache if available
        rankings_cache = self._get_rankings_cache() if hasattr(self, '_get_rankings_cache') else None

        # Prepare scroll content with mixed game types
        # Note: Using 'mixed' as game_type indicator for scroll config
        success = self._scroll_manager.prepare_and_display(
            games, 'mixed', leagues, rankings_cache
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
        """Clean up resources."""
        try:
            if hasattr(self, "background_service") and self.background_service:
                # Clean up background service if needed
                pass
            self.logger.info("Baseball scoreboard plugin cleanup completed")
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")
