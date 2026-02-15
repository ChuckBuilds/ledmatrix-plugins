"""
Hockey Scoreboard Plugin for LEDMatrix - Using Existing Managers

This plugin provides NHL, NCAA Men's, and NCAA Women's hockey scoreboard functionality by reusing
the proven, working manager classes from the LEDMatrix core project.
"""

import logging
import time
from typing import Dict, Any, Optional, Set, List, Tuple

try:
    from src.plugin_system.base_plugin import BasePlugin, VegasDisplayMode
except ImportError:
    BasePlugin = None
    VegasDisplayMode = None

# Import shared background service from LEDMatrix core
try:
    from src.background_data_service import get_background_service
except ImportError:
    get_background_service = None

# Import scroll display components
try:
    from scroll_display import ScrollDisplayManager
    SCROLL_AVAILABLE = True
except ImportError:
    ScrollDisplayManager = None
    SCROLL_AVAILABLE = False

# Import the copied manager classes
from nhl_managers import NHLLiveManager, NHLRecentManager, NHLUpcomingManager
from ncaam_hockey_managers import (
    NCAAMHockeyLiveManager,
    NCAAMHockeyRecentManager,
    NCAAMHockeyUpcomingManager,
)
from ncaaw_hockey_managers import (
    NCAAWHockeyLiveManager,
    NCAAWHockeyRecentManager,
    NCAAWHockeyUpcomingManager,
)

logger = logging.getLogger(__name__)


class HockeyScoreboardPlugin(BasePlugin if BasePlugin else object):
    """
    Hockey scoreboard plugin using existing manager classes.

    This plugin provides NHL, NCAA Men's, and NCAA Women's hockey scoreboard functionality by
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
        """Initialize the hockey scoreboard plugin."""
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
        self.logger.debug(f"Hockey plugin received config keys: {list(config.keys())}")
        self.logger.debug(f"NHL config: {config.get('nhl', {})}")
        
        self.nhl_enabled = config.get("nhl", {}).get("enabled", False)
        self.ncaa_mens_enabled = config.get("ncaa_mens", {}).get("enabled", False)
        self.ncaa_womens_enabled = config.get("ncaa_womens", {}).get("enabled", False)
        
        self.logger.info(f"League enabled states - NHL: {self.nhl_enabled}, NCAA Men's: {self.ncaa_mens_enabled}, NCAA Women's: {self.ncaa_womens_enabled}")

        # Live priority settings
        self.nhl_live_priority = self.config.get("nhl", {}).get("live_priority", False)
        self.ncaa_mens_live_priority = self.config.get("ncaa_mens", {}).get(
            "live_priority", False
        )
        self.ncaa_womens_live_priority = self.config.get("ncaa_womens", {}).get(
            "live_priority", False
        )

        # Global settings - read from defaults section with fallback
        defaults = config.get("defaults", {})
        self.display_duration = float(defaults.get("display_duration", config.get("display_duration", 30)))
        self.game_display_duration = float(defaults.get("display_duration", config.get("game_display_duration", 15)))

        # Additional settings - read from defaults section with fallback
        self.show_records = defaults.get("show_records", config.get("show_records", False))
        self.show_ranking = defaults.get("show_ranking", config.get("show_ranking", False))
        self.show_odds = defaults.get("show_odds", config.get("show_odds", False))

        # Initialize background service if available
        self.background_service = None
        if get_background_service:
            try:
                self.background_service = get_background_service(
                    self.cache_manager, max_workers=1
                )
            except Exception as e:
                self.logger.warning(f"Could not initialize background service: {e}")
        
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
            self.logger.info("High-FPS scrolling enabled for hockey scoreboard")

        # League registry: maps league IDs to their configuration and managers
        # This structure makes it easy to add more leagues in the future
        # Format: {league_id: {'enabled': bool, 'priority': int, 'live_priority': bool, 'managers': {...}}}
        # The registry will be populated after managers are initialized
        self._league_registry: Dict[str, Dict[str, Any]] = {}

        # Track current display context for granular dynamic duration
        self._current_display_league: Optional[str] = None  # 'nhl', 'ncaa_mens', or 'ncaa_womens'
        self._current_display_mode_type: Optional[str] = None  # 'live', 'recent', 'upcoming'

        # Initialize managers
        self._initialize_managers()
        
        # Initialize league registry after managers are created
        # This centralizes league management and makes it easy to add more leagues
        self._initialize_league_registry()

        # Mode cycling (like football plugin)
        self.current_mode_index = 0
        self.last_mode_switch = time.time()
        self.modes = self._get_available_modes()

        # Dynamic duration tracking state
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
        
        # Track last display mode to detect when we return after being away
        self._last_display_mode: Optional[str] = None  # Track previous display mode
        self._last_display_mode_time: float = 0.0  # When we last saw this mode
        self._current_active_display_mode: Optional[str] = None  # Currently active external display mode
        
        # Throttle logging for has_live_content() when returning False
        self._last_live_content_false_log: float = 0.0  # Timestamp of last False log
        self._live_content_log_interval: float = 60.0  # Log False results every 60 seconds
        
        # Track current game for transition detection
        # Format: {display_mode: {'game_id': str, 'league': str, 'last_log_time': float}}
        self._current_game_tracking: Dict[str, Dict[str, Any]] = {}
        self._game_transition_log_interval: float = 1.0  # Minimum seconds between game transition logs
        
        # Track mode start times for per-mode duration enforcement
        # Format: {display_mode: start_time} (e.g., {'nhl_recent': 1234567890.0})
        # Reset when mode changes or full cycle completes
        self._mode_start_time: Dict[str, float] = {}

        # Sticky manager tracking - ensures we complete all games from one league before switching
        self._sticky_manager_per_mode: Dict[str, Any] = {}  # {display_mode: manager_instance}
        self._sticky_manager_start_time: Dict[str, float] = {}  # {display_mode: timestamp}
        
        # Display mode settings parsing (for future scroll mode support in config schema)
        self._display_mode_settings = self._parse_display_mode_settings()

        # Initialize scroll display manager if available
        self._scroll_manager = None
        if SCROLL_AVAILABLE and ScrollDisplayManager:
            try:
                self._scroll_manager = ScrollDisplayManager(
                    self.display_manager,
                    self.config,
                    self.logger
                )
                self.logger.info("Hockey scroll display manager initialized")
            except Exception as e:
                self.logger.warning(f"Could not initialize scroll display manager: {e}")
        else:
            self.logger.info("Scroll display not available - scroll mode disabled")

        # Scroll state tracking
        self._scroll_prepared = {}  # Tracks which scroll modes are prepared
        self._scroll_active = {}  # Tracks which scroll modes are active

        self.logger.info(
            f"Hockey scoreboard plugin initialized - {self.display_width}x{self.display_height}"
        )
        self.logger.info(
            f"NHL enabled: {self.nhl_enabled}, NCAA Men's enabled: {self.ncaa_mens_enabled}, NCAA Women's enabled: {self.ncaa_womens_enabled}"
        )

    def _initialize_managers(self):
        """Initialize all manager instances."""
        try:
            # Create adapted configs for managers
            nhl_config = self._adapt_config_for_manager("nhl")
            ncaa_mens_config = self._adapt_config_for_manager("ncaa_mens")
            ncaa_womens_config = self._adapt_config_for_manager("ncaa_womens")

            # Initialize NHL managers if enabled
            if self.nhl_enabled:
                try:
                    self.nhl_live = NHLLiveManager(
                        nhl_config, self.display_manager, self.cache_manager
                    )
                    self.nhl_recent = NHLRecentManager(
                        nhl_config, self.display_manager, self.cache_manager
                    )
                    self.nhl_upcoming = NHLUpcomingManager(
                        nhl_config, self.display_manager, self.cache_manager
                    )
                    self.logger.info("NHL managers initialized")
                except Exception as e:
                    self.logger.error(f"Failed to initialize NHL managers: {e}", exc_info=True)
                    # Set to None so hasattr checks work correctly
                    if not hasattr(self, "nhl_live"):
                        self.nhl_live = None
                    if not hasattr(self, "nhl_recent"):
                        self.nhl_recent = None
                    if not hasattr(self, "nhl_upcoming"):
                        self.nhl_upcoming = None

            # Initialize NCAA Men's managers if enabled
            if self.ncaa_mens_enabled:
                try:
                    self.ncaa_mens_live = NCAAMHockeyLiveManager(
                        ncaa_mens_config, self.display_manager, self.cache_manager
                    )
                    self.ncaa_mens_recent = NCAAMHockeyRecentManager(
                        ncaa_mens_config, self.display_manager, self.cache_manager
                    )
                    self.ncaa_mens_upcoming = NCAAMHockeyUpcomingManager(
                        ncaa_mens_config, self.display_manager, self.cache_manager
                    )
                    self.logger.info("NCAA Men's Hockey managers initialized")
                except Exception as e:
                    self.logger.error(f"Failed to initialize NCAA Men's Hockey managers: {e}", exc_info=True)
                    # Set to None so hasattr checks work correctly
                    if not hasattr(self, "ncaa_mens_live"):
                        self.ncaa_mens_live = None
                    if not hasattr(self, "ncaa_mens_recent"):
                        self.ncaa_mens_recent = None
                    if not hasattr(self, "ncaa_mens_upcoming"):
                        self.ncaa_mens_upcoming = None

            # Initialize NCAA Women's managers if enabled
            if self.ncaa_womens_enabled:
                try:
                    self.ncaa_womens_live = NCAAWHockeyLiveManager(
                        ncaa_womens_config, self.display_manager, self.cache_manager
                    )
                    self.ncaa_womens_recent = NCAAWHockeyRecentManager(
                        ncaa_womens_config, self.display_manager, self.cache_manager
                    )
                    self.ncaa_womens_upcoming = NCAAWHockeyUpcomingManager(
                        ncaa_womens_config, self.display_manager, self.cache_manager
                    )
                    self.logger.info("NCAA Women's Hockey managers initialized")
                except Exception as e:
                    self.logger.error(f"Failed to initialize NCAA Women's Hockey managers: {e}", exc_info=True)
                    # Set to None so hasattr checks work correctly
                    if not hasattr(self, "ncaa_womens_live"):
                        self.ncaa_womens_live = None
                    if not hasattr(self, "ncaa_womens_recent"):
                        self.ncaa_womens_recent = None
                    if not hasattr(self, "ncaa_womens_upcoming"):
                        self.ncaa_womens_upcoming = None

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
        # NHL league entry - highest priority (1)
        self._league_registry['nhl'] = {
            'enabled': self.nhl_enabled,
            'priority': 1,  # Highest priority - shows first
            'live_priority': self.nhl_live_priority,
            'managers': {
                'live': getattr(self, 'nhl_live', None),
                'recent': getattr(self, 'nhl_recent', None),
                'upcoming': getattr(self, 'nhl_upcoming', None),
            }
        }
        
        # NCAA Men's Hockey league entry - second priority (2)
        self._league_registry['ncaa_mens'] = {
            'enabled': self.ncaa_mens_enabled,
            'priority': 2,  # Second priority - shows after NHL
            'live_priority': self.ncaa_mens_live_priority,
            'managers': {
                'live': getattr(self, 'ncaa_mens_live', None),
                'recent': getattr(self, 'ncaa_mens_recent', None),
                'upcoming': getattr(self, 'ncaa_mens_upcoming', None),
            }
        }
        
        # NCAA Women's Hockey league entry - third priority (3)
        self._league_registry['ncaa_womens'] = {
            'enabled': self.ncaa_womens_enabled,
            'priority': 3,  # Third priority - shows after NCAA Men's
            'live_priority': self.ncaa_womens_live_priority,
            'managers': {
                'live': getattr(self, 'ncaa_womens_live', None),
                'recent': getattr(self, 'ncaa_womens_recent', None),
                'upcoming': getattr(self, 'ncaa_womens_upcoming', None),
            }
        }
        
        # Log registry state for debugging
        enabled_leagues = [lid for lid, data in self._league_registry.items() if data['enabled']]
        self.logger.info(
            f"League registry initialized: {len(self._league_registry)} league(s) registered, "
            f"{len(enabled_leagues)} enabled: {enabled_leagues}"
        )

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
            Example: ['nhl', 'ncaa_mens'] means NHL shows first, then NCAA Men's
            
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
                mode_enabled = display_modes_config.get("live", display_modes_config.get("show_live", True))
            elif mode_type == 'recent':
                mode_enabled = display_modes_config.get("recent", display_modes_config.get("show_recent", True))
            elif mode_type == 'upcoming':
                mode_enabled = display_modes_config.get("upcoming", display_modes_config.get("show_upcoming", True))
            
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

    def _get_managers_for_mode_type(self, mode_type: str) -> List:
        """
        Get managers in priority order for a specific mode type.
        
        This method returns manager instances for all enabled leagues that have
        the specified mode type enabled, sorted by league priority.
        
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

    def _get_league_manager_for_mode(self, league_id: str, mode_type: str):
        """
        Get the manager instance for a specific league and mode type.
        
        This is a convenience method that looks up managers from the league registry.
        It provides a single point of access for getting managers, making the code
        more maintainable and easier to extend.
        
        Args:
            league_id: League identifier ('nhl', 'ncaa_mens', 'ncaa_womens', etc.)
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

    def _is_league_complete_for_mode(self, league_id: str, mode_type: str) -> bool:
        """
        Check if a league has completed showing all games for a specific mode type.
        
        This is used in sequential block display to determine when to move from
        one league to the next. A league is considered complete when all its games
        have been shown for their full duration (tracked via dynamic duration system).
        
        Args:
            league_id: League identifier ('nhl', 'ncaa_mens', 'ncaa_womens', etc.)
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

    def _get_default_logo_dir(self, league: str) -> str:
        """
        Get the default logo directory for a league.
        Matches the directories used in src/logo_downloader.py.
        """
        # Map leagues to their logo directories (matching logo_downloader.py)
        logo_dir_map = {
            'nhl': 'assets/sports/nhl_logos',
            'ncaa_mens': 'assets/sports/ncaa_logos',  # NCAA Men's Hockey uses ncaa_logos
            'ncaa_womens': 'assets/sports/ncaa_logos',  # NCAA Women's Hockey uses ncaa_logos
        }
        # Default to league-specific directory if not in map
        return logo_dir_map.get(league, f"assets/sports/{league}_logos")

    def _parse_display_mode_settings(self) -> Dict[str, Dict[str, str]]:
        """
        Parse display mode settings from config.
        
        Returns:
            Dict mapping league -> game_type -> display_mode ('switch' or 'scroll')
            e.g., {'nhl': {'live': 'switch', 'recent': 'switch', 'upcoming': 'switch'}}
        """
        settings = {}
        
        for league in ['nhl', 'ncaa_mens', 'ncaa_womens']:
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
            league: 'nhl', 'ncaa_mens', or 'ncaa_womens'
            game_type: 'live', 'recent', or 'upcoming'
            
        Returns:
            'switch' or 'scroll'
        """
        if league not in self._display_mode_settings:
            return 'switch'
        
        return self._display_mode_settings[league].get(game_type, 'switch')

    def _extract_mode_type(self, display_mode: str) -> Optional[str]:
        """Extract mode type (live, recent, upcoming) from display mode string.
        
        Args:
            display_mode: Display mode string (e.g., 'hockey_live', 'nhl_recent')
            
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

    def _get_game_duration(self, league: str, mode_type: str, manager=None) -> float:
        """Get game duration for a league and mode type combination.
        
        Resolves duration using the following hierarchy:
        1. Manager's game_display_duration attribute (if manager provided)
        2. League-specific mode duration (e.g., nhl.live_game_duration from display_durations.live)
        3. League-specific default (15 seconds)
        
        Args:
            league: League name ('nhl', 'ncaa_mens', or 'ncaa_womens')
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
        
        # Next, try league-specific mode duration from display_durations
        league_config = self.config.get(league, {})
        display_durations = league_config.get("display_durations", {})
        mode_duration_key = mode_type  # e.g., 'live' maps to display_durations.live
        mode_duration = display_durations.get(mode_duration_key)
        if mode_duration is not None:
            return float(mode_duration)
        
        # Fallback to league-specific default (15 seconds)
        return 15.0

    def _get_mode_duration(self, league: str, mode_type: str) -> Optional[float]:
        """
        Get mode duration from config for a league/mode combination.
        
        Checks per-league/per-mode settings first, then falls back to per-league settings.
        Returns None if not configured (uses dynamic calculation).
        
        Args:
            league: League name ('nhl', 'ncaa_mens', or 'ncaa_womens')
            mode_type: Mode type ('live', 'recent', or 'upcoming')
            
        Returns:
            Mode duration in seconds (float) or None if not configured
        """
        league_config = self.config.get(league, {})
        mode_durations = league_config.get("mode_durations", {})
        
        # Check per-mode setting (e.g., live_mode_duration, recent_mode_duration)
        mode_duration_key = f"{mode_type}_mode_duration"
        if mode_duration_key in mode_durations:
            value = mode_durations[mode_duration_key]
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    pass
        
        # No per-mode setting configured - return None to use dynamic calculation
        return None

    def _dynamic_feature_enabled(self) -> bool:
        """Return True when dynamic duration should be active."""
        if not self.is_enabled:
            return False
        return self.supports_dynamic_duration()

    def _adapt_config_for_manager(self, league: str) -> Dict[str, Any]:
        """
        Adapt plugin config format to manager expected format.

        Plugin uses: nhl: {...}, ncaa_mens: {...}, ncaa_womens: {...}
        Managers expect: nhl_scoreboard: {...}, ncaa_mens_hockey_scoreboard: {...}, etc.
        
        Supports both new nested structure and old flat structure for backward compatibility.
        """
        league_config = self.config.get(league, {})
        defaults = self.config.get("defaults", {})

        # Map league names to sport_key format expected by managers
        sport_key_map = {
            "nhl": "nhl",
            "ncaa_mens": "ncaam_hockey",
            "ncaa_womens": "ncaaw_hockey",
        }
        sport_key = sport_key_map.get(league, league)

        # Extract nested configurations (new structure) with fallback to flat structure (old)
        display_modes = league_config.get("display_modes", {})
        teams_config = league_config.get("teams", {})
        filtering_config = league_config.get("filtering", {})
        update_intervals = league_config.get("update_intervals", {})
        display_durations = league_config.get("display_durations", {})
        display_options = league_config.get("display_options", {})

        def resolve_mode_flag(*keys: str, default: bool = True) -> bool:
            for key in keys:
                if key in display_modes:
                    return bool(display_modes[key])
            return default

        live_flag = resolve_mode_flag("live", "show_live", "hockey_live")
        recent_flag = resolve_mode_flag("recent", "show_recent", "hockey_recent")
        upcoming_flag = resolve_mode_flag("upcoming", "show_upcoming", "hockey_upcoming")

        def resolve_value(nested_path: list, flat_keys: list, default):
            """Resolve value from nested structure or fallback to flat structure."""
            # Try nested structure first
            current = league_config
            for key in nested_path:
                if isinstance(current, dict) and key in current:
                    current = current[key]
                else:
                    current = None
                    break
            if current is not None:
                return current
            
            # Try flat structure (backward compatibility)
            for key in flat_keys:
                if key in league_config:
                    return league_config[key]
            
            # Try defaults
            if nested_path:
                current = defaults
                for key in nested_path:
                    if isinstance(current, dict) and key in current:
                        current = current[key]
                    else:
                        return default
                return current
            
            return default

        # Resolve team settings
        favorite_teams = resolve_value(["teams", "favorite_teams"], ["favorite_teams"], [])
        favorite_only = resolve_value(["teams", "favorite_teams_only"], ["favorite_teams_only"], False)
        show_all_live = resolve_value(["teams", "show_all_live"], ["show_all_live"], False)

        # Resolve filtering settings
        recent_games_to_show = resolve_value(["filtering", "recent_games_to_show"], ["recent_games_to_show"], 5)
        upcoming_games_to_show = resolve_value(["filtering", "upcoming_games_to_show"], ["upcoming_games_to_show"], 10)

        # Resolve update intervals
        update_interval_seconds = resolve_value(["update_intervals", "base"], ["update_interval_seconds"], 60)
        live_update_interval = resolve_value(["update_intervals", "live"], ["live_update_interval"], 15)
        recent_update_interval = resolve_value(["update_intervals", "recent"], ["recent_update_interval"], 3600)
        upcoming_update_interval = resolve_value(["update_intervals", "upcoming"], ["upcoming_update_interval"], 3600)

        # Resolve display durations
        def resolve_live_duration() -> int:
            # Try new nested structure
            if "display_durations" in league_config and "live" in league_config["display_durations"]:
                return int(league_config["display_durations"]["live"])
            # Try old flat structure
            if "live_game_duration" in league_config:
                return int(league_config["live_game_duration"])
            if "game_rotation_interval_seconds" in league_config:
                return int(league_config["game_rotation_interval_seconds"])
            if "live_display_duration" in league_config:
                return int(league_config["live_display_duration"])
            return 20

        # Resolve display options with defaults fallback
        show_records = resolve_value(["display_options", "show_records"], ["show_records"], self.show_records)
        show_ranking = resolve_value(["display_options", "show_ranking"], ["show_ranking"], self.show_ranking)
        show_odds = resolve_value(["display_options", "show_odds"], ["show_odds"], self.show_odds)
        show_shots_on_goal = resolve_value(["display_options", "show_shots_on_goal"], ["show_shots_on_goal"], False)
        show_powerplay = resolve_value(["display_options", "show_powerplay"], ["show_powerplay"], True)

        # Create manager config with expected structure
        manager_config = {
            f"{sport_key}_scoreboard": {
                "enabled": league_config.get("enabled", False),
                "favorite_teams": favorite_teams,
                "display_modes": {
                    "hockey_live": live_flag,
                    "hockey_recent": recent_flag,
                    "hockey_upcoming": upcoming_flag,
                },
                "recent_games_to_show": recent_games_to_show,
                "upcoming_games_to_show": upcoming_games_to_show,
                "show_records": show_records,
                "show_ranking": show_ranking,
                "show_odds": show_odds,
                "show_shots_on_goal": show_shots_on_goal,
                "show_powerplay": show_powerplay,
                "show_favorite_teams_only": favorite_only,
                "show_all_live": show_all_live,
                "live_priority": league_config.get("live_priority", False),
                "update_interval_seconds": update_interval_seconds,
                "live_update_interval": live_update_interval,
                "recent_update_interval": recent_update_interval,
                "upcoming_update_interval": upcoming_update_interval,
                "live_game_duration": resolve_live_duration(),
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

        return manager_config

    def _get_available_modes(self) -> list:
        """Get list of available display modes based on enabled leagues using league registry."""
        modes = []

        # Use league registry to build mode list in priority order
        # Iterate through leagues in priority order (lower priority number = higher priority)
        sorted_leagues = sorted(
            self._league_registry.items(),
            key=lambda item: item[1].get('priority', 999)
        )

        for league_id, league_data in sorted_leagues:
            # Check if league is enabled
            if not league_data.get('enabled', False):
                continue
            
            # Get league config to check display_modes settings
            league_config = self.config.get(league_id, {})
            display_modes_config = league_config.get("display_modes", {})
            
            # Check each mode type
            for mode_type in ['recent', 'upcoming', 'live']:  # Order: recent, upcoming, live
                mode_enabled = True  # Default to enabled if not specified
                if mode_type == 'live':
                    mode_enabled = display_modes_config.get("live", display_modes_config.get("show_live", True))
                elif mode_type == 'recent':
                    mode_enabled = display_modes_config.get("recent", display_modes_config.get("show_recent", True))
                elif mode_type == 'upcoming':
                    mode_enabled = display_modes_config.get("upcoming", display_modes_config.get("show_upcoming", True))
                
                if mode_enabled:
                    modes.append(f"{league_id}_{mode_type}")

        # Default to NHL if no leagues enabled
        if not modes:
            modes = ["nhl_recent", "nhl_upcoming", "nhl_live"]

        return modes

    def _get_current_manager(self):
        """Get the current manager based on the current mode (like football plugin)."""
        if not self.modes:
            return None

        current_mode = self.modes[self.current_mode_index]

        if current_mode.startswith("nhl_"):
            if not self.nhl_enabled:
                return None
            mode_type = current_mode.split("_", 1)[1]  # "live", "recent", "upcoming"
            if mode_type == "live":
                return self.nhl_live
            elif mode_type == "recent":
                return self.nhl_recent
            elif mode_type == "upcoming":
                return self.nhl_upcoming

        elif current_mode.startswith("ncaa_mens_"):
            if not self.ncaa_mens_enabled:
                return None
            mode_type = current_mode.split("_", 2)[2]  # "live", "recent", "upcoming"
            if mode_type == "live":
                return self.ncaa_mens_live
            elif mode_type == "recent":
                return self.ncaa_mens_recent
            elif mode_type == "upcoming":
                return self.ncaa_mens_upcoming

        elif current_mode.startswith("ncaa_womens_"):
            if not self.ncaa_womens_enabled:
                return None
            mode_type = current_mode.split("_", 2)[2]  # "live", "recent", "upcoming"
            if mode_type == "live":
                return self.ncaa_womens_live
            elif mode_type == "recent":
                return self.ncaa_womens_recent
            elif mode_type == "upcoming":
                return self.ncaa_womens_upcoming

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
        """Update hockey game data."""
        if not self.is_enabled:
            return

        current_time = time.time()
        # Log plugin update calls for debugging (every 5 minutes)
        if not hasattr(self, '_last_plugin_update_log') or current_time - self._last_plugin_update_log >= 300:
            self.logger.info(f"Plugin update() called at {current_time}")
            self._last_plugin_update_log = current_time

        try:
            # Update NHL managers if enabled
            if self.nhl_enabled:
                for attr in ("nhl_live", "nhl_recent", "nhl_upcoming"):
                    manager = getattr(self, attr, None)
                    if manager:
                        manager.update()

            # Update NCAA Men's managers if enabled
            if self.ncaa_mens_enabled:
                for attr in ("ncaa_mens_live", "ncaa_mens_recent", "ncaa_mens_upcoming"):
                    manager = getattr(self, attr, None)
                    if manager:
                        manager.update()

            # Update NCAA Women's managers if enabled
            if self.ncaa_womens_enabled:
                for attr in (
                    "ncaa_womens_live",
                    "ncaa_womens_recent",
                    "ncaa_womens_upcoming",
                ):
                    manager = getattr(self, attr, None)
                    if manager:
                        manager.update()

        except Exception as e:
            self.logger.error(f"Error updating managers: {e}", exc_info=True)

    def display(self, display_mode: str = None, force_clear: bool = False) -> bool:
        """Display hockey games for a specific granular mode.
        
        The plugin now uses granular modes directly (nhl_recent, nhl_upcoming, nhl_live,
        ncaa_mens_recent, ncaa_mens_upcoming, ncaa_mens_live, etc.) registered in manifest.json.
        The display controller handles rotation between these modes.
        
        Args:
            display_mode: Granular mode name (e.g., 'nhl_recent', 'ncaa_mens_upcoming', 'nhl_live')
                         Format: {league}_{mode_type}
                         If None, uses internal mode cycling (legacy support).
            force_clear: If True, clear display before rendering
        """
        if not self.is_enabled:
            return False

        try:
            # Track the current active display mode for use in is_cycle_complete()
            if display_mode:
                self._current_active_display_mode = display_mode
            
            # Route to appropriate display handler
            if display_mode:
                # Handle legacy combined modes (hockey_live, hockey_recent, hockey_upcoming)
                # These should not be called with new architecture, but handle gracefully
                # for backward compatibility during transition
                if display_mode.startswith("hockey_"):
                    # Legacy combined mode - extract mode_type and show all enabled leagues
                    mode_type_str = display_mode.replace("hockey_", "")
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
                    
                    # Try to display from first enabled league (simplified fallback)
                    # Sequential block display would show all leagues, but for legacy
                    # mode support we just try the first one
                    for league_id in enabled_leagues:
                        success = self._display_league_mode(league_id, mode_type_str, force_clear)
                        if success:
                            return True
                    
                    # No content from any league
                    return False
                
                # Parse granular mode name: {league}_{mode_type}
                # e.g., "nhl_recent" -> league="nhl", mode_type="recent"
                # e.g., "ncaa_mens_recent" -> league="ncaa_mens", mode_type="recent"
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
                        f"(expected format: {{league}}_{{mode_type}}, e.g., 'nhl_recent' or 'ncaa_mens_recent'). "
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
                    mode_enabled = display_modes_config.get("live", display_modes_config.get("show_live", True))
                elif mode_type_str == 'recent':
                    mode_enabled = display_modes_config.get("recent", display_modes_config.get("show_recent", True))
                elif mode_type_str == 'upcoming':
                    mode_enabled = display_modes_config.get("upcoming", display_modes_config.get("show_upcoming", True))
                
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
            self.logger.error(f"Error in display method: {e}", exc_info=True)
            return False

    def is_cycle_complete(self) -> bool:
        """Report whether the plugin has shown a full cycle of content."""
        if not self._dynamic_feature_enabled():
            return True
        
        # Pass the current active display mode to evaluate completion for the right mode
        self._evaluate_dynamic_cycle_completion(display_mode=self._current_active_display_mode)
        self.logger.info(f"is_cycle_complete() called: display_mode={self._current_active_display_mode}, returning {self._dynamic_cycle_complete}")
        return self._dynamic_cycle_complete

    def _set_display_context_from_manager(self, manager, mode_type: str) -> None:
        """Set current display league and mode type based on manager instance.
        
        Args:
            manager: Manager instance
            mode_type: 'live', 'recent', or 'upcoming'
        """
        self._current_display_mode_type = mode_type
        
        # Check NHL managers
        if manager in (getattr(self, 'nhl_live', None), 
                      getattr(self, 'nhl_recent', None), 
                      getattr(self, 'nhl_upcoming', None)):
            self._current_display_league = 'nhl'
        # Check NCAA Men's managers
        elif manager in (getattr(self, 'ncaa_mens_live', None), 
                        getattr(self, 'ncaa_mens_recent', None), 
                        getattr(self, 'ncaa_mens_upcoming', None)):
            self._current_display_league = 'ncaa_mens'
        # Check NCAA Women's managers
        elif manager in (getattr(self, 'ncaa_womens_live', None), 
                        getattr(self, 'ncaa_womens_recent', None), 
                        getattr(self, 'ncaa_womens_upcoming', None)):
            self._current_display_league = 'ncaa_womens'

    @staticmethod
    def _build_manager_key(mode_name: str, manager) -> str:
        """Build a unique key for tracking a manager instance.
        
        Args:
            mode_name: Display mode name (e.g., 'nhl_recent')
            manager: Manager instance
            
        Returns:
            Manager key string (e.g., 'nhl_recent:NHLLiveManager')
        """
        manager_name = manager.__class__.__name__ if manager else "None"
        return f"{mode_name}:{manager_name}"

    @staticmethod
    def _get_total_games_for_manager(manager) -> int:
        """Get total number of games for a manager.
        
        Args:
            manager: Manager instance
            
        Returns:
            Number of games (0 if no games or manager is None)
        """
        if manager is None:
            return 0
        for attr in ("live_games", "games_list", "recent_games", "upcoming_games"):
            value = getattr(manager, attr, None)
            if isinstance(value, list):
                return len(value)
        return 0
    
    @staticmethod
    def _get_all_game_ids_for_manager(manager) -> set:
        """Get all game IDs from a manager's game list.
        
        Args:
            manager: Manager instance
            
        Returns:
            Set of game ID strings
        """
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

    def _get_rankings_cache(self) -> Dict[str, int]:
        """Get combined team rankings cache from all managers.
        
        Returns:
            Dictionary mapping team abbreviations to their rankings/positions
            Format: {'TB': 1, 'BOS': 2, ...}
            Empty dict if no rankings available
        """
        rankings = {}
        
        # Try to get rankings from each manager
        for manager_attr in ['nhl_live', 'nhl_recent', 'nhl_upcoming', 
                            'ncaa_mens_live', 'ncaa_mens_recent', 'ncaa_mens_upcoming',
                            'ncaa_womens_live', 'ncaa_womens_recent', 'ncaa_womens_upcoming']:
            manager = getattr(self, manager_attr, None)
            if manager:
                manager_rankings = getattr(manager, '_team_rankings_cache', {})
                if manager_rankings:
                    rankings.update(manager_rankings)
        
        return rankings

    def _get_manager_for_league_mode(self, league: str, mode_type: str):
        """Get manager instance for a league and mode type combination.
        
        This is a convenience method that calls _get_league_manager_for_mode()
        for consistency with football-scoreboard naming.
        
        Args:
            league: 'nhl', 'ncaa_mens', or 'ncaa_womens'
            mode_type: 'live', 'recent', or 'upcoming'
            
        Returns:
            Manager instance or None if not available/enabled
        """
        return self._get_league_manager_for_mode(league, mode_type)

    def _get_games_from_manager(self, manager, mode_type: str) -> List[Dict]:
        """Get games list from a manager based on mode type.
        
        Args:
            manager: Manager instance
            mode_type: 'live', 'recent', or 'upcoming'
            
        Returns:
            List of game dictionaries
        """
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

    def _has_live_games_for_manager(self, manager) -> bool:
        """Check if a manager has valid live games (for favorite teams if configured).
        
        Args:
            manager: Manager instance to check
            
        Returns:
            True if manager has live games that should be displayed
        """
        if not manager:
            return False
        
        live_games = getattr(manager, 'live_games', [])
        if not live_games:
            return False
        
        # Filter out games that are final or appear over
        live_games = [g for g in live_games if not g.get('is_final', False)]
        if hasattr(manager, '_is_game_really_over'):
            live_games = [g for g in live_games if not manager._is_game_really_over(g)]
        
        if not live_games:
            return False
        
        # If favorite teams are configured, only return True if there are live games for favorite teams
        favorite_teams = getattr(manager, 'favorite_teams', [])
        if favorite_teams:
            has_favorite_live = any(
                game.get('home_abbr') in favorite_teams
                or game.get('away_abbr') in favorite_teams
                for game in live_games
            )
            return has_favorite_live
        
        # No favorite teams configured, any live game counts
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

    def _apply_sticky_manager_logic(self, display_mode: str, managers_to_try: list) -> list:
        """Apply sticky manager logic to filter managers list.
        
        Args:
            display_mode: External display mode name
            managers_to_try: List of managers to try
            
        Returns:
            Filtered list of managers (only sticky manager if exists and available)
        """
        sticky_manager = self._sticky_manager_per_mode.get(display_mode)
        
        self.logger.info(
            f"Sticky manager check for {display_mode}: "
            f"sticky={sticky_manager.__class__.__name__ if sticky_manager else None}, "
            f"available_managers={[m.__class__.__name__ for m in managers_to_try if m]}"
        )
        
        if sticky_manager and sticky_manager in managers_to_try:
            self.logger.info(
                f"Using sticky manager {sticky_manager.__class__.__name__} for {display_mode} - "
                "RESTRICTING to this manager only"
            )
            return [sticky_manager]
        
        # No sticky manager or not in list - clean up if needed
        if sticky_manager:
            self.logger.info(
                f"Sticky manager {sticky_manager.__class__.__name__} no longer available for {display_mode}, "
                f"selecting new one from {len(managers_to_try)} options"
            )
            self._sticky_manager_per_mode.pop(display_mode, None)
            self._sticky_manager_start_time.pop(display_mode, None)
        else:
            self.logger.info(
                f"No sticky manager yet for {display_mode}, will select from {len(managers_to_try)} available managers"
            )
        
        return managers_to_try

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
            - Mode enabled state for that league (live, recent, upcoming)
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

    def _get_manager_for_mode(self, mode_name: str):
        """Resolve manager instance for a given display mode.
        
        Args:
            mode_name: Display mode name (e.g., 'nhl_recent', 'ncaa_mens_live')
            
        Returns:
            Manager instance or None if not found/disabled
        """
        if mode_name.startswith("nhl_"):
            if not self.nhl_enabled:
                return None
            suffix = mode_name.split("_", 1)[1]
            if suffix == "live":
                return getattr(self, "nhl_live", None)
            if suffix == "recent":
                return getattr(self, "nhl_recent", None)
            if suffix == "upcoming":
                return getattr(self, "nhl_upcoming", None)
        elif mode_name.startswith("ncaa_mens_"):
            if not self.ncaa_mens_enabled:
                return None
            suffix = mode_name[len("ncaa_mens_"):]
            if suffix == "live":
                return getattr(self, "ncaa_mens_live", None)
            if suffix == "recent":
                return getattr(self, "ncaa_mens_recent", None)
            if suffix == "upcoming":
                return getattr(self, "ncaa_mens_upcoming", None)
        elif mode_name.startswith("ncaa_womens_"):
            if not self.ncaa_womens_enabled:
                return None
            suffix = mode_name[len("ncaa_womens_"):]
            if suffix == "live":
                return getattr(self, "ncaa_womens_live", None)
            if suffix == "recent":
                return getattr(self, "ncaa_womens_recent", None)
            if suffix == "upcoming":
                return getattr(self, "ncaa_womens_upcoming", None)
        return None

    def _track_single_game_progress(self, manager_key: str, manager, league: str, mode_type: str) -> None:
        """Track progress for a manager with a single game (or no games).
        
        Args:
            manager_key: Unique key identifying this manager
            manager: Manager instance
            league: League name ('nhl', 'ncaa_mens', or 'ncaa_womens')
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
            current_mode = self.modes[self.current_mode_index] if self.modes else None
            if current_mode is None:
                return
        
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
            if current_mode.startswith('nhl_'):
                league = 'nhl'
                mode_type = current_mode.split('_', 1)[1]
            elif current_mode.startswith('ncaa_mens_'):
                league = 'ncaa_mens'
                mode_type = current_mode.split('_', 2)[2]
            elif current_mode.startswith('ncaa_womens_'):
                league = 'ncaa_womens'
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
        the given display mode, ensuring all enabled leagues have completed
        before marking the cycle as complete.
        
        Args:
            display_mode: External display mode name (e.g., 'hockey_recent')
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
                                    league = 'nhl' if mode_name.startswith('nhl_') else ('ncaa_mens' if mode_name.startswith('ncaa_mens_') else ('ncaa_womens' if mode_name.startswith('ncaa_womens_') else None))
                                    mode_type_str = mode_name.split('_')[-1] if mode_name else None
                                    game_duration = self._get_game_duration(league, mode_type_str, manager) if league and mode_type_str else getattr(manager, 'game_display_duration', 15)
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
            
            if incomplete_managers:
                self._dynamic_cycle_complete = False
                self.logger.debug(f"Display mode {display_mode} cycle incomplete - {len(incomplete_managers)} manager(s) still in progress: {incomplete_managers}")
                return
            
            # All managers completed - verify they truly completed
            # Double-check that single-game managers have truly finished their duration
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
                            league = 'nhl' if mode_name.startswith('nhl_') else ('ncaa_mens' if mode_name.startswith('ncaa_mens_') else ('ncaa_womens' if mode_name.startswith('ncaa_womens_') else None))
                            mode_type_str = mode_name.split('_')[-1] if mode_name else None
                            game_duration = self._get_game_duration(league, mode_type_str, manager) if league and mode_type_str else getattr(manager, 'game_display_duration', 15)
                            elapsed = time.time() - start_time
                            if elapsed < game_duration:
                                # Not enough time has passed - not truly completed
                                all_truly_completed = False
                                self.logger.debug(f"Manager {manager_key} in completed set but still has start time with {elapsed:.2f}s < {game_duration}s")
                                break
            
            if all_truly_completed:
                self._dynamic_cycle_complete = True
                self.logger.info(f"Display mode {display_mode} cycle complete - all {len(used_manager_keys)} manager(s) completed")
            else:
                # Some managers aren't truly completed - keep cycle incomplete
                self._dynamic_cycle_complete = False
                self.logger.debug(f"Display mode {display_mode} cycle incomplete - some managers not truly completed yet")
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
                        game_duration = getattr(manager, 'game_display_duration', 15) if manager else 15
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

    def has_live_priority(self) -> bool:
        if not self.is_enabled:
            return False

        return any(
            [
                self.nhl_enabled and self.nhl_live_priority,
                self.ncaa_mens_enabled and self.ncaa_mens_live_priority,
                self.ncaa_womens_enabled and self.ncaa_womens_live_priority,
            ]
        )

    def has_live_content(self) -> bool:
        if not self.is_enabled:
            return False

        # Check NHL live content
        nhl_live = False
        if (
            self.nhl_enabled
            and self.nhl_live_priority
            and hasattr(self, "nhl_live")
        ):
            live_games = getattr(self.nhl_live, "live_games", [])
            if live_games:
                # Filter out any games that are final or appear over
                live_games = [g for g in live_games if not g.get("is_final", False)]
                # Additional validation using helper method if available
                if hasattr(self.nhl_live, "_is_game_really_over"):
                    live_games = [g for g in live_games if not self.nhl_live._is_game_really_over(g)]
                
                if live_games:
                    # If favorite teams are configured, only return True if there are live games for favorite teams
                    favorite_teams = getattr(self.nhl_live, "favorite_teams", [])
                    if favorite_teams:
                        # Check if any live game involves a favorite team
                        nhl_live = any(
                            game.get("home_abbr") in favorite_teams
                            or game.get("away_abbr") in favorite_teams
                            for game in live_games
                        )
                    else:
                        # No favorite teams configured, return True if any live games exist
                        nhl_live = True

        # Check NCAA Men's live content
        ncaa_mens_live = False
        if (
            self.ncaa_mens_enabled
            and self.ncaa_mens_live_priority
            and hasattr(self, "ncaa_mens_live")
        ):
            live_games = getattr(self.ncaa_mens_live, "live_games", [])
            if live_games:
                # Filter out any games that are final or appear over
                live_games = [g for g in live_games if not g.get("is_final", False)]
                # Additional validation using helper method if available
                if hasattr(self.ncaa_mens_live, "_is_game_really_over"):
                    live_games = [g for g in live_games if not self.ncaa_mens_live._is_game_really_over(g)]
                
                if live_games:
                    # If favorite teams are configured, only return True if there are live games for favorite teams
                    favorite_teams = getattr(self.ncaa_mens_live, "favorite_teams", [])
                    if favorite_teams:
                        # Check if any live game involves a favorite team
                        ncaa_mens_live = any(
                            game.get("home_abbr") in favorite_teams
                            or game.get("away_abbr") in favorite_teams
                            for game in live_games
                        )
                    else:
                        # No favorite teams configured, return True if any live games exist
                        ncaa_mens_live = True

        # Check NCAA Women's live content
        ncaa_womens_live = False
        if (
            self.ncaa_womens_enabled
            and self.ncaa_womens_live_priority
            and hasattr(self, "ncaa_womens_live")
        ):
            live_games = getattr(self.ncaa_womens_live, "live_games", [])
            if live_games:
                # Filter out any games that are final or appear over
                live_games = [g for g in live_games if not g.get("is_final", False)]
                # Additional validation using helper method if available
                if hasattr(self.ncaa_womens_live, "_is_game_really_over"):
                    live_games = [g for g in live_games if not self.ncaa_womens_live._is_game_really_over(g)]
                
                if live_games:
                    # If favorite teams are configured, only return True if there are live games for favorite teams
                    favorite_teams = getattr(self.ncaa_womens_live, "favorite_teams", [])
                    if favorite_teams:
                        # Check if any live game involves a favorite team
                        ncaa_womens_live = any(
                            game.get("home_abbr") in favorite_teams
                            or game.get("away_abbr") in favorite_teams
                            for game in live_games
                        )
                    else:
                        # No favorite teams configured, return True if any live games exist
                        ncaa_womens_live = True

        result = nhl_live or ncaa_mens_live or ncaa_womens_live
        
        # Throttle logging when returning False to reduce log noise
        # Always log True immediately (important), but only log False every 60 seconds
        current_time = time.time()
        should_log = result or (current_time - self._last_live_content_false_log >= self._live_content_log_interval)
        
        if should_log:
            if result:
                # Always log True results immediately
                self.logger.info(f"has_live_content() returning {result}: nhl_live={nhl_live}, ncaa_mens_live={ncaa_mens_live}, ncaa_womens_live={ncaa_womens_live}")
            else:
                # Log False results only every 60 seconds
                self.logger.info(f"has_live_content() returning {result}: nhl_live={nhl_live}, ncaa_mens_live={ncaa_mens_live}, ncaa_womens_live={ncaa_womens_live}")
                self._last_live_content_false_log = current_time
        
        return result

    def get_live_modes(self) -> list:
        """
        Return the registered plugin mode name(s) that have live content.
        
        Returns granular live modes (nhl_live, ncaa_mens_live, etc.) that have live content.
        The plugin is registered with granular modes in manifest.json.
        """
        if not self.is_enabled:
            return []

        live_modes = []
        
        # Check NHL live content
        if (
            self.nhl_enabled
            and self.nhl_live_priority
            and hasattr(self, "nhl_live")
        ):
            live_games = getattr(self.nhl_live, "live_games", [])
            if live_games:
                # Filter out any games that are final or appear over
                live_games = [g for g in live_games if not g.get("is_final", False)]
                # Additional validation using helper method if available
                if hasattr(self.nhl_live, "_is_game_really_over"):
                    live_games = [g for g in live_games if not self.nhl_live._is_game_really_over(g)]
                
                if live_games:
                    # Check if favorite teams filter applies
                    favorite_teams = getattr(self.nhl_live, "favorite_teams", [])
                    if favorite_teams:
                        # Only include if there are live games for favorite teams
                        if any(
                            game.get("home_abbr") in favorite_teams
                            or game.get("away_abbr") in favorite_teams
                            for game in live_games
                        ):
                            live_modes.append("nhl_live")
                    else:
                        # No favorite teams configured, include if any live games exist
                        live_modes.append("nhl_live")
        
        # Check NCAA Men's live content
        if (
            self.ncaa_mens_enabled
            and self.ncaa_mens_live_priority
            and hasattr(self, "ncaa_mens_live")
        ):
            live_games = getattr(self.ncaa_mens_live, "live_games", [])
            if live_games:
                # Filter out any games that are final or appear over
                live_games = [g for g in live_games if not g.get("is_final", False)]
                # Additional validation using helper method if available
                if hasattr(self.ncaa_mens_live, "_is_game_really_over"):
                    live_games = [g for g in live_games if not self.ncaa_mens_live._is_game_really_over(g)]
                
                if live_games:
                    # Check if favorite teams filter applies
                    favorite_teams = getattr(self.ncaa_mens_live, "favorite_teams", [])
                    if favorite_teams:
                        # Only include if there are live games for favorite teams
                        if any(
                            game.get("home_abbr") in favorite_teams
                            or game.get("away_abbr") in favorite_teams
                            for game in live_games
                        ):
                            live_modes.append("ncaa_mens_live")
                    else:
                        # No favorite teams configured, include if any live games exist
                        live_modes.append("ncaa_mens_live")
        
        # Check NCAA Women's live content
        if (
            self.ncaa_womens_enabled
            and self.ncaa_womens_live_priority
            and hasattr(self, "ncaa_womens_live")
        ):
            live_games = getattr(self.ncaa_womens_live, "live_games", [])
            if live_games:
                # Filter out any games that are final or appear over
                live_games = [g for g in live_games if not g.get("is_final", False)]
                # Additional validation using helper method if available
                if hasattr(self.ncaa_womens_live, "_is_game_really_over"):
                    live_games = [g for g in live_games if not self.ncaa_womens_live._is_game_really_over(g)]
                
                if live_games:
                    # Check if favorite teams filter applies
                    favorite_teams = getattr(self.ncaa_womens_live, "favorite_teams", [])
                    if favorite_teams:
                        # Only include if there are live games for favorite teams
                        if any(
                            game.get("home_abbr") in favorite_teams
                            or game.get("away_abbr") in favorite_teams
                            for game in live_games
                        ):
                            live_modes.append("ncaa_womens_live")
                    else:
                        # No favorite teams configured, include if any live games exist
                        live_modes.append("ncaa_womens_live")
        
        return live_modes

    def _should_use_scroll_mode(self, league: str, mode_type: str) -> bool:
        """
        Check if a specific league should use scroll mode for this game type.
        
        Args:
            league: League ID ('nhl', 'ncaa_mens', or 'ncaa_womens')
            mode_type: 'live', 'recent', or 'upcoming'
            
        Returns:
            True if this league uses scroll mode for this game type
        """
        return self._get_display_mode(league, mode_type) == 'scroll'

    def _display_scroll_mode(self, display_mode: str, league: str, mode_type: str, force_clear: bool) -> bool:
        """Handle display for scroll mode (single league).
        
        Args:
            display_mode: External mode name (e.g., 'nhl_recent')
            league: League ID ('nhl', 'ncaa_mens', or 'ncaa_womens')
            mode_type: Game type ('live', 'recent', 'upcoming')
            force_clear: Whether to force clear display
            
        Returns:
            True if content was displayed, False otherwise
        """
        if not self._scroll_manager:
            self.logger.warning("Scroll mode requested but scroll manager not available")
            # Fall back to switch mode
            return self._try_manager_display(
                self._get_league_manager_for_mode(league, mode_type),
                force_clear,
                display_mode,
                mode_type,
                None
            )[0]
        
        # Check if we need to prepare new scroll content
        scroll_key = f"{display_mode}_{mode_type}"
        
        if not self._scroll_prepared.get(scroll_key, False):
            # Get manager and update it
            manager = self._get_league_manager_for_mode(league, mode_type)
            if not manager:
                self.logger.debug(f"No manager available for {league} {mode_type}")
                return False
            
            self._ensure_manager_updated(manager)
            
            # Get games from this manager
            games = self._get_games_from_manager(manager, mode_type)
            
            if not games:
                self.logger.debug(f"No games to scroll for {display_mode}")
                self._scroll_prepared[scroll_key] = False
                self._scroll_active[scroll_key] = False
                return False
            
            # Add league info to each game
            for game in games:
                game['league'] = league
            
            # Get rankings cache for display
            rankings = self._get_rankings_cache()
            
            # Prepare scroll content (single league)
            success = self._scroll_manager.prepare_and_display(
                games, mode_type, [league], rankings
            )
            
            if success:
                self._scroll_prepared[scroll_key] = True
                self._scroll_active[scroll_key] = True
                self.logger.info(
                    f"[Hockey Scroll] Started scrolling {len(games)} {league} {mode_type} games"
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
                    self.logger.info(f"[Hockey Scroll] Cycle complete for {display_mode}")
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

    def _display_league_mode(self, league: str, mode_type: str, force_clear: bool) -> bool:
        """
        Display a specific league/mode combination (e.g., NHL Recent, NCAA Men's Upcoming).
        
        This method displays content from a single league and mode type, used when
        rotation_order specifies granular modes like 'nhl_recent' or 'ncaa_mens_upcoming'.
        
        Args:
            league: League ID ('nhl', 'ncaa_mens', or 'ncaa_womens')
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
        
        # Check if this league uses scroll mode
        if self._should_use_scroll_mode(league, mode_type):
            return self._display_scroll_mode(display_mode, league, mode_type, force_clear)
        
        # Set display context for dynamic duration tracking
        self._current_display_league = league
        self._current_display_mode_type = mode_type
        
        # Try to display content from this league's manager (switch mode)
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
        
        Args:
            force_clear: Whether to force clear display
            
        Returns:
            True if content was displayed, False otherwise
        """
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
        if not should_stay_on_live and current_time - self.last_mode_switch >= self.display_duration:
            self.current_mode_index = (self.current_mode_index + 1) % len(self.modes)
            self.last_mode_switch = current_time
            force_clear = True
            
            current_mode = self.modes[self.current_mode_index]
            self.logger.info(f"Switching to display mode: {current_mode}")
        
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

    def _try_manager_display(
        self, 
        manager, 
        force_clear: bool, 
        display_mode: str, 
        mode_type: str, 
        sticky_manager=None
    ) -> Tuple[bool, Optional[str]]:
        """
        Try to display content from a single manager.
        
        This method handles displaying content from a manager and tracking progress
        for dynamic duration. It uses sticky manager logic to ensure all games from
        one league are displayed before switching to another.
        
        Args:
            manager: Manager instance to try
            force_clear: Whether to force clear display
            display_mode: External display mode name (e.g., 'hockey_recent')
            mode_type: Mode type ('live', 'recent', or 'upcoming')
            sticky_manager: Deprecated parameter (kept for compatibility, ignored)
            
        Returns:
            Tuple of (success: bool, actual_mode: Optional[str])
            - success: True if manager displayed content, False otherwise
            - actual_mode: The actual mode name used for tracking (e.g., 'nhl_recent')
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
        # Example: 'nhl_recent' or 'ncaa_mens_live'
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
            # Success - track progress and set sticky manager
            manager_key = self._build_manager_key(actual_mode, manager)
            
            try:
                self._record_dynamic_progress(manager, actual_mode=actual_mode, display_mode=display_mode)
            except Exception as progress_err:  # pylint: disable=broad-except
                self.logger.debug(f"Dynamic progress tracking failed: {progress_err}")
            
            # Set as sticky manager AFTER progress tracking (which may clear it on new cycle)
            if display_mode not in self._sticky_manager_per_mode:
                self._sticky_manager_per_mode[display_mode] = manager
                self._sticky_manager_start_time[display_mode] = time.time()
                self.logger.info(f"Set sticky manager {manager_class_name} for {display_mode}")
            
            # Track which managers were used for this display mode
            if display_mode:
                self._display_mode_to_managers.setdefault(display_mode, set()).add(manager_key)
            
            self._evaluate_dynamic_cycle_completion(display_mode=display_mode)
            return True, actual_mode
        
        elif result is False and manager == sticky_manager:
            # Sticky manager returned False - check if completed
            manager_key = self._build_manager_key(actual_mode, manager)
            
            if manager_key in self._dynamic_managers_completed:
                self.logger.info(
                    f"Sticky manager {manager_class_name} completed all games, switching to next manager"
                )
                self._sticky_manager_per_mode.pop(display_mode, None)
                self._sticky_manager_start_time.pop(display_mode, None)
                # Signal to break out of loop and try next manager
                return False, None
            else:
                # Manager not done yet, just returning False temporarily (between game switches)
                self.logger.debug(
                    f"Sticky manager {manager_class_name} returned False (between games), continuing"
                )
                return False, None
        
        elif result is False:
            # Non-sticky manager returned False - try next
            return False, None
        
        else:
            # Result is None or other - assume success
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

    def _get_effective_mode_duration(self, display_mode: str, mode_type: str) -> Optional[float]:
        """
        Get effective mode duration for a display mode.
        
        Checks per-mode duration settings first, then falls back to dynamic calculation.
        
        Args:
            display_mode: Display mode name (e.g., 'nhl_recent')
            mode_type: Mode type ('live', 'recent', or 'upcoming')
            
        Returns:
            Mode duration in seconds (float) or None to use dynamic calculation
        """
        if not self._current_display_league:
            return None
        
        # Get mode duration from config
        mode_duration = self._get_mode_duration(self._current_display_league, mode_type)
        if mode_duration is not None:
            return mode_duration
        
        # No per-mode duration configured - use dynamic calculation
        return None

    def validate_config(self) -> bool:
        """Validate plugin configuration."""
        try:
            # Check that at least one league is enabled
            if not (self.nhl_enabled or self.ncaa_mens_enabled or self.ncaa_womens_enabled):
                self.logger.warning("No leagues enabled in hockey scoreboard plugin")
                return False

            return True
        except Exception as e:
            self.logger.error(f"Error validating config: {e}")
            return False

    def get_display_duration(self) -> float:
        """Get the display duration for this plugin."""
        return float(self.display_duration)

    def get_cycle_duration(self, display_mode: str = None) -> Optional[float]:
        """
        Calculate the expected cycle duration for a display mode based on the number of games.
        
        This implements dynamic duration scaling with support for mode-level durations:
        - Mode-level duration: Fixed total time for mode (recent_mode_duration, upcoming_mode_duration, live_mode_duration)
        - Dynamic calculation: Total duration = num_games × per_game_duration
        
        Priority order:
        1. Mode-level duration (if configured)
        2. Dynamic calculation (if no mode-level duration)
        3. Dynamic duration cap applies to both if enabled
        
        Args:
            display_mode: The display mode to calculate duration for (e.g., 'hockey_live', 'hockey_recent', 'nhl_live', 'ncaa_mens_recent')
        
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
        
        # Parse granular mode name if applicable (e.g., "nhl_recent", "ncaa_mens_upcoming")
        league = None
        if "_" in display_mode and not display_mode.startswith("hockey_"):
            # Granular mode: extract league
            # Handle ncaa_mens and ncaa_womens with multiple underscores
            if display_mode.startswith("ncaa_mens_"):
                league = "ncaa_mens"
            elif display_mode.startswith("ncaa_womens_"):
                league = "ncaa_womens"
            elif display_mode.startswith("nhl_"):
                league = "nhl"
            else:
                # Try standard split
                parts = display_mode.split("_", 1)
                if len(parts) == 2:
                    potential_league, potential_mode_type = parts
                    if potential_league in self._league_registry and potential_mode_type == mode_type:
                        league = potential_league
        
        # Check for mode-level duration first (priority 1)
        # Extract league if not already determined
        if not league and mode_type:
            # Try to get league from current display context or parse from display_mode
            if self._current_display_league:
                league = self._current_display_league
            else:
                # Try to parse from display_mode
                if display_mode.startswith("nhl_"):
                    league = "nhl"
                elif display_mode.startswith("ncaa_mens_"):
                    league = "ncaa_mens"
                elif display_mode.startswith("ncaa_womens_"):
                    league = "ncaa_womens"
        
        if league:
            effective_mode_duration = self._get_mode_duration(league, mode_type)
            if effective_mode_duration is not None:
                self.logger.info(
                    f"get_cycle_duration: using mode-level duration for {display_mode} = {effective_mode_duration}s"
                )
                return effective_mode_duration
        
        # Fall through to dynamic calculation based on game count (priority 2)
        
        try:
            self.logger.info(f"get_cycle_duration: extracted mode_type={mode_type}, league={league} from display_mode={display_mode}")

            total_games = 0
            total_duration = 0.0  # Accumulate duration per-league to handle different per_game_durations
            
            # Collect managers for this mode and count their games
            managers_to_check = []
            
            # If granular mode (specific league), only check that league
            if league:
                manager = self._get_league_manager_for_mode(league, mode_type)
                if manager:
                    managers_to_check.append((league, manager))
            else:
                # Combined mode - check all enabled leagues
                if mode_type == 'live':
                    if self.nhl_enabled:
                        nhl_manager = self._get_league_manager_for_mode('nhl', 'live')
                        if nhl_manager:
                            managers_to_check.append(('nhl', nhl_manager))
                    if self.ncaa_mens_enabled:
                        ncaa_mens_manager = self._get_league_manager_for_mode('ncaa_mens', 'live')
                        if ncaa_mens_manager:
                            managers_to_check.append(('ncaa_mens', ncaa_mens_manager))
                    if self.ncaa_womens_enabled:
                        ncaa_womens_manager = self._get_league_manager_for_mode('ncaa_womens', 'live')
                        if ncaa_womens_manager:
                            managers_to_check.append(('ncaa_womens', ncaa_womens_manager))
                elif mode_type == 'recent':
                    if self.nhl_enabled:
                        nhl_manager = self._get_league_manager_for_mode('nhl', 'recent')
                        if nhl_manager:
                            managers_to_check.append(('nhl', nhl_manager))
                    if self.ncaa_mens_enabled:
                        ncaa_mens_manager = self._get_league_manager_for_mode('ncaa_mens', 'recent')
                        if ncaa_mens_manager:
                            managers_to_check.append(('ncaa_mens', ncaa_mens_manager))
                    if self.ncaa_womens_enabled:
                        ncaa_womens_manager = self._get_league_manager_for_mode('ncaa_womens', 'recent')
                        if ncaa_womens_manager:
                            managers_to_check.append(('ncaa_womens', ncaa_womens_manager))
                elif mode_type == 'upcoming':
                    if self.nhl_enabled:
                        nhl_manager = self._get_league_manager_for_mode('nhl', 'upcoming')
                        if nhl_manager:
                            managers_to_check.append(('nhl', nhl_manager))
                    if self.ncaa_mens_enabled:
                        ncaa_mens_manager = self._get_league_manager_for_mode('ncaa_mens', 'upcoming')
                        if ncaa_mens_manager:
                            managers_to_check.append(('ncaa_mens', ncaa_mens_manager))
                    if self.ncaa_womens_enabled:
                        ncaa_womens_manager = self._get_league_manager_for_mode('ncaa_womens', 'upcoming')
                        if ncaa_womens_manager:
                            managers_to_check.append(('ncaa_womens', ncaa_womens_manager))
            
            # CRITICAL: Update managers BEFORE checking game counts!
            self.logger.info(f"get_cycle_duration: updating {len(managers_to_check)} manager(s) before counting games")
            for league_name, manager in managers_to_check:
                if manager:
                    self._ensure_manager_updated(manager)
            
            # Count games from all applicable managers and get duration
            for league_name, manager in managers_to_check:
                if not manager:
                    continue
                
                # Get the appropriate game list based on mode type
                if mode_type == 'live':
                    games = getattr(manager, 'live_games', [])
                elif mode_type == 'recent':
                    # Try games_list first (used by recent managers), then recent_games
                    games = getattr(manager, 'games_list', None)
                    if games is None:
                        games = getattr(manager, 'recent_games', [])
                    else:
                        games = list(games) if games else []
                elif mode_type == 'upcoming':
                    # Try games_list first (used by upcoming managers), then upcoming_games
                    games = getattr(manager, 'games_list', None)
                    if games is None:
                        games = getattr(manager, 'upcoming_games', [])
                    else:
                        games = list(games) if games else []
                else:
                    games = []
                
                # Get duration for this league/mode combination
                per_game_duration = self._get_game_duration(league_name, mode_type, manager)
                
                # Filter out invalid games
                if games:
                    # For live games, filter out final games
                    if mode_type == 'live':
                        games = [g for g in games if not g.get('is_final', False)]
                        if hasattr(manager, '_is_game_really_over'):
                            games = [g for g in games if not manager._is_game_really_over(g)]
                    
                    game_count = len(games)
                    total_games += game_count
                    # Accumulate duration per-league to correctly handle different per_game_durations
                    total_duration += game_count * per_game_duration

                    self.logger.debug(
                        f"get_cycle_duration: {league_name} {mode_type} has {game_count} games × "
                        f"{per_game_duration}s = {game_count * per_game_duration}s"
                    )
            
            self.logger.info(f"get_cycle_duration: found {total_games} total games for {display_mode}")
            
            if total_games == 0:
                # If no games found yet (managers still fetching data), return a default duration
                # This allows the display to start while data is loading
                default_duration = 45.0  # 3 games × 15s per game (reasonable default)
                self.logger.info(f"get_cycle_duration: {display_mode} has no games yet, returning default {default_duration}s")
                return default_duration

            self.logger.info(
                f"get_cycle_duration({display_mode}): {total_games} total games = {total_duration}s"
            )

            return total_duration
            
        except Exception as e:
            self.logger.error(f"Error calculating cycle duration for {display_mode}: {e}", exc_info=True)
            return None

    def get_info(self) -> Dict[str, Any]:
        """Get plugin information."""
        try:
            current_manager = self._get_current_manager()
            current_mode = self.modes[self.current_mode_index] if self.modes else "none"

            info = {
                "plugin_id": self.plugin_id,
                "name": "Hockey Scoreboard",
                "version": "1.0.0",
                "enabled": self.is_enabled,
                "display_size": f"{self.display_width}x{self.display_height}",
                "nhl_enabled": self.nhl_enabled,
                "ncaa_mens_enabled": self.ncaa_mens_enabled,
                "ncaa_womens_enabled": self.ncaa_womens_enabled,
                "current_mode": current_mode,
                "available_modes": self.modes,
                "display_duration": self.display_duration,
                "game_display_duration": self.game_display_duration,
                "show_records": getattr(self, 'show_records', False),
                "show_ranking": getattr(self, 'show_ranking', False),
                "show_odds": getattr(self, 'show_odds', False),
                "managers_initialized": {
                    "nhl_live": hasattr(self, "nhl_live"),
                    "nhl_recent": hasattr(self, "nhl_recent"),
                    "nhl_upcoming": hasattr(self, "nhl_upcoming"),
                    "ncaa_mens_live": hasattr(self, "ncaa_mens_live"),
                    "ncaa_mens_recent": hasattr(self, "ncaa_mens_recent"),
                    "ncaa_mens_upcoming": hasattr(self, "ncaa_mens_upcoming"),
                    "ncaa_womens_live": hasattr(self, "ncaa_womens_live"),
                    "ncaa_womens_recent": hasattr(self, "ncaa_womens_recent"),
                    "ncaa_womens_upcoming": hasattr(self, "ncaa_womens_upcoming"),
                },
                "live_priority": {
                    "nhl": self.nhl_enabled and self.nhl_live_priority,
                    "ncaa_mens": self.ncaa_mens_enabled
                    and self.ncaa_mens_live_priority,
                    "ncaa_womens": self.ncaa_womens_enabled
                    and self.ncaa_womens_live_priority,
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
                "name": "Hockey Scoreboard",
                "error": str(e),
            }

    # -------------------------------------------------------------------------
    # Scroll mode helper methods
    # -------------------------------------------------------------------------
    def _is_scroll_mode_available(self) -> bool:
        """
        Check if scroll mode is available (scroll manager exists).

        Returns:
            True if scroll mode is available, False otherwise
        """
        return bool(self._scroll_manager)

    def _collect_games_for_scroll(self) -> tuple:
        """
        Collect all games for scroll mode from enabled leagues.

        Collects live, recent, and upcoming games organized by league.
        Within each league, games are sorted: live first, then recent, then upcoming.

        Returns:
            Tuple of (games_list, leagues_list)
        """
        all_games = []
        leagues = []

        # Collect from NHL if enabled - all game types
        if self.nhl_enabled:
            league_games = []
            for mode_type in ['live', 'recent', 'upcoming']:
                manager = self._get_manager_for_league_mode('nhl', mode_type)
                if manager:
                    games = self._get_games_from_manager(manager, mode_type)
                    for game in games:
                        game['league'] = 'nhl'
                        # Ensure game has status for type determination
                        if 'status' not in game:
                            game['status'] = {}
                        if 'state' not in game['status']:
                            # Infer state from mode_type
                            state_map = {'live': 'in', 'recent': 'post', 'upcoming': 'pre'}
                            game['status']['state'] = state_map.get(mode_type, 'pre')
                    league_games.extend(games)

            if league_games:
                all_games.extend(league_games)
                leagues.append('nhl')

        # Collect from NCAA Men's if enabled - all game types
        if self.ncaa_mens_enabled:
            league_games = []
            for mode_type in ['live', 'recent', 'upcoming']:
                manager = self._get_manager_for_league_mode('ncaam_hockey', mode_type)
                if manager:
                    games = self._get_games_from_manager(manager, mode_type)
                    for game in games:
                        game['league'] = 'ncaam_hockey'
                        # Ensure game has status for type determination
                        if 'status' not in game:
                            game['status'] = {}
                        if 'state' not in game['status']:
                            state_map = {'live': 'in', 'recent': 'post', 'upcoming': 'pre'}
                            game['status']['state'] = state_map.get(mode_type, 'pre')
                    league_games.extend(games)

            if league_games:
                all_games.extend(league_games)
                leagues.append('ncaam_hockey')

        # Collect from NCAA Women's if enabled - all game types
        if self.ncaa_womens_enabled:
            league_games = []
            for mode_type in ['live', 'recent', 'upcoming']:
                manager = self._get_manager_for_league_mode('ncaaw_hockey', mode_type)
                if manager:
                    games = self._get_games_from_manager(manager, mode_type)
                    for game in games:
                        game['league'] = 'ncaaw_hockey'
                        # Ensure game has status for type determination
                        if 'status' not in game:
                            game['status'] = {}
                        if 'state' not in game['status']:
                            state_map = {'live': 'in', 'recent': 'post', 'upcoming': 'pre'}
                            game['status']['state'] = state_map.get(mode_type, 'pre')
                    league_games.extend(games)

            if league_games:
                all_games.extend(league_games)
                leagues.append('ncaaw_hockey')

        return all_games, leagues

    def _get_manager_for_league_mode(self, league: str, mode_type: str):
        """Get manager for a specific league and mode type."""
        if league == 'nhl':
            if mode_type == 'live':
                return self.nhl_live
            elif mode_type == 'recent':
                return self.nhl_recent
            elif mode_type == 'upcoming':
                return self.nhl_upcoming
        elif league == 'ncaam_hockey':
            if mode_type == 'live':
                return self.ncaa_mens_live
            elif mode_type == 'recent':
                return self.ncaa_mens_recent
            elif mode_type == 'upcoming':
                return self.ncaa_mens_upcoming
        elif league == 'ncaaw_hockey':
            if mode_type == 'live':
                return self.ncaa_womens_live
            elif mode_type == 'recent':
                return self.ncaa_womens_recent
            elif mode_type == 'upcoming':
                return self.ncaa_womens_upcoming
        return None

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
            # Check if any scroll display has content
            has_content = False
            for scroll_display in self._scroll_manager._scroll_displays.values():
                if hasattr(scroll_display, 'scroll_helper') and scroll_display.scroll_helper:
                    if scroll_display.scroll_helper.cached_image is not None:
                        has_content = True
                        break

            if not has_content:
                self.logger.info("[Hockey Vegas] Triggering scroll content generation")
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
            self.logger.debug("[Hockey Vegas] No scroll manager available")
            return

        # Collect all games (live, recent, upcoming) organized by league
        games, leagues = self._collect_games_for_scroll()

        if not games:
            self.logger.debug("[Hockey Vegas] No games available")
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

        # Prepare scroll content with mixed game types
        # Note: Using 'mixed' as game_type indicator for scroll config
        success = self._scroll_manager.prepare_and_display(
            games, 'mixed', leagues, None
        )

        if success:
            type_summary = ', '.join(
                f"{count} {gtype}" for gtype, count in game_type_counts.items() if count > 0
            )
            self.logger.info(
                f"[Hockey Vegas] Successfully generated scroll content: "
                f"{len(games)} games ({type_summary}) from {', '.join(leagues)}"
            )
        else:
            self.logger.warning("[Hockey Vegas] Failed to generate scroll content")

    def cleanup(self) -> None:
        """Clean up resources."""
        try:
            if hasattr(self, "background_service") and self.background_service:
                # Clean up background service if needed
                pass
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")
