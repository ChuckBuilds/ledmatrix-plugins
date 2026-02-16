"""
Basketball Scoreboard Plugin for LEDMatrix - Using Existing Managers

This plugin provides NBA, WNBA, NCAA Men's, and NCAA Women's basketball scoreboard 
functionality by reusing proven, working manager classes.
"""

import logging
import time
import threading
from typing import Dict, Any, Set, Optional, List, Tuple

from PIL import ImageFont

try:
    from src.plugin_system.base_plugin import BasePlugin, VegasDisplayMode
    from src.background_data_service import get_background_service
    from base_odds_manager import BaseOddsManager
except ImportError:
    BasePlugin = None
    VegasDisplayMode = None
    get_background_service = None
    BaseOddsManager = None

# Import scroll display components
try:
    from scroll_display import ScrollDisplayManager
    SCROLL_AVAILABLE = True
except ImportError:
    ScrollDisplayManager = None
    SCROLL_AVAILABLE = False

# Import the manager classes
from nba_managers import NBALiveManager, NBARecentManager, NBAUpcomingManager
from wnba_managers import WNBALiveManager, WNBARecentManager, WNBAUpcomingManager
from ncaam_basketball_managers import (
    NCAAMBasketballLiveManager,
    NCAAMBasketballRecentManager,
    NCAAMBasketballUpcomingManager,
)
from ncaaw_basketball_managers import (
    NCAAWBasketballLiveManager,
    NCAAWBasketballRecentManager,
    NCAAWBasketballUpcomingManager,
)

logger = logging.getLogger(__name__)


class BasketballScoreboardPlugin(BasePlugin if BasePlugin else object):
    """
    Basketball scoreboard plugin using existing manager classes.

    This plugin provides NBA, WNBA, NCAA Men's, and NCAA Women's basketball 
    scoreboard functionality by delegating to proven manager classes.
    """

    def __init__(
        self,
        plugin_id: str,
        config: Dict[str, Any],
        display_manager,
        cache_manager,
        plugin_manager,
    ):
        """Initialize the basketball scoreboard plugin."""
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

        # League configurations
        self.logger.debug(f"Basketball plugin received config keys: {list(config.keys())}")
        self.logger.debug(f"NBA config: {config.get('nba', {})}")
        
        self.nba_enabled = config.get("nba", {}).get("enabled", False)
        self.wnba_enabled = config.get("wnba", {}).get("enabled", False)
        self.ncaam_enabled = config.get("ncaam", {}).get("enabled", False)
        self.ncaaw_enabled = config.get("ncaaw", {}).get("enabled", False)
        
        self.logger.info(
            f"League enabled states - NBA: {self.nba_enabled}, WNBA: {self.wnba_enabled}, "
            f"NCAA Men's: {self.ncaam_enabled}, NCAA Women's: {self.ncaaw_enabled}"
        )

        # Global settings
        self.display_duration = float(config.get("display_duration", 30))
        self.game_display_duration = float(config.get("game_display_duration", 15))

        # Live priority per league
        self.nba_live_priority = self.config.get("nba", {}).get("live_priority", False)
        self.wnba_live_priority = self.config.get("wnba", {}).get("live_priority", False)
        self.ncaam_live_priority = self.config.get("ncaam", {}).get("live_priority", False)
        self.ncaaw_live_priority = self.config.get("ncaaw", {}).get("live_priority", False)

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
        self.enable_scrolling = self._scroll_manager is not None
        if self.enable_scrolling:
            self.logger.info("High-FPS scrolling enabled for basketball scoreboard")

        # League registry: maps league IDs to their configuration and managers
        # This structure makes it easy to add more leagues in the future
        # Format: {league_id: {'enabled': bool, 'priority': int, 'live_priority': bool, 'managers': {...}}}
        # The registry will be populated after managers are initialized
        self._league_registry: Dict[str, Dict[str, Any]] = {}
        
        # Initialize managers
        self._initialize_managers()
        
        # Initialize league registry after managers are created
        # This centralizes league management and makes it easy to add more leagues
        self._initialize_league_registry()

        # Mode cycling
        self.current_mode_index = 0
        self.last_mode_switch = 0
        self.modes = self._get_available_modes()

        self.logger.info(
            f"Basketball scoreboard plugin initialized - {self.display_width}x{self.display_height}"
        )
        self.logger.info(
            f"NBA enabled: {self.nba_enabled}, WNBA enabled: {self.wnba_enabled}, "
            f"NCAA Men's enabled: {self.ncaam_enabled}, NCAA Women's enabled: {self.ncaaw_enabled}"
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
        
        # Track last display mode to detect when we return after being away
        self._last_display_mode: Optional[str] = None  # Track previous display mode
        self._last_display_mode_time: float = 0.0  # When we last saw this mode
        self._current_active_display_mode: Optional[str] = None  # Currently active external display mode
        
        # Sticky manager tracking - ensures we complete all games from one league before switching
        self._sticky_manager_per_mode: Dict[str, Any] = {}  # {display_mode: manager_instance}
        self._sticky_manager_start_time: Dict[str, float] = {}  # {display_mode: timestamp}
        
        # Throttle logging for has_live_content() when returning False
        self._last_live_content_false_log: float = 0.0  # Timestamp of last False log
        self._live_content_log_interval: float = 60.0  # Log False results every 60 seconds
        
        # Track current game for transition detection
        # Format: {display_mode: {'game_id': str, 'league': str, 'last_log_time': float}}
        self._current_game_tracking: Dict[str, Dict[str, Any]] = {}
        self._game_transition_log_interval: float = 1.0  # Minimum seconds between game transition logs
        
        # Track mode start times for per-mode duration enforcement
        # Format: {display_mode: start_time} (e.g., {'nba_recent': 1234567890.0})
        # Reset when mode changes or full cycle completes
        self._mode_start_time: Dict[str, float] = {}
        
        # Display mode settings parsing (for future scroll mode support in config schema)
        self._display_mode_settings = self._parse_display_mode_settings()
        
        # Track current display context for granular dynamic duration
        self._current_display_league: Optional[str] = None  # 'nba', 'wnba', 'ncaam', 'ncaaw'
        self._current_display_mode_type: Optional[str] = None  # 'live', 'recent', 'upcoming'

    def _initialize_managers(self):
        """Initialize all manager instances."""
        try:
            # Create adapted configs for managers
            nba_config = self._adapt_config_for_manager("nba")
            wnba_config = self._adapt_config_for_manager("wnba")
            ncaam_config = self._adapt_config_for_manager("ncaam")
            ncaaw_config = self._adapt_config_for_manager("ncaaw")

            # Initialize NBA managers if enabled
            if self.nba_enabled:
                self.nba_live = NBALiveManager(
                    nba_config, self.display_manager, self.cache_manager
                )
                self.nba_recent = NBARecentManager(
                    nba_config, self.display_manager, self.cache_manager
                )
                self.nba_upcoming = NBAUpcomingManager(
                    nba_config, self.display_manager, self.cache_manager
                )
                self.logger.info("NBA managers initialized")

            # Initialize WNBA managers if enabled
            if self.wnba_enabled:
                self.wnba_live = WNBALiveManager(
                    wnba_config, self.display_manager, self.cache_manager
                )
                self.wnba_recent = WNBARecentManager(
                    wnba_config, self.display_manager, self.cache_manager
                )
                self.wnba_upcoming = WNBAUpcomingManager(
                    wnba_config, self.display_manager, self.cache_manager
                )
                self.logger.info("WNBA managers initialized")

            # Initialize NCAA Men's managers if enabled
            if self.ncaam_enabled:
                self.ncaam_live = NCAAMBasketballLiveManager(
                    ncaam_config, self.display_manager, self.cache_manager
                )
                self.ncaam_recent = NCAAMBasketballRecentManager(
                    ncaam_config, self.display_manager, self.cache_manager
                )
                self.ncaam_upcoming = NCAAMBasketballUpcomingManager(
                    ncaam_config, self.display_manager, self.cache_manager
                )
                self.logger.info("NCAA Men's managers initialized")

            # Initialize NCAA Women's managers if enabled
            if self.ncaaw_enabled:
                self.ncaaw_live = NCAAWBasketballLiveManager(
                    ncaaw_config, self.display_manager, self.cache_manager
                )
                self.ncaaw_recent = NCAAWBasketballRecentManager(
                    ncaaw_config, self.display_manager, self.cache_manager
                )
                self.ncaaw_upcoming = NCAAWBasketballUpcomingManager(
                    ncaaw_config, self.display_manager, self.cache_manager
                )
                self.logger.info("NCAA Women's managers initialized")

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
        # NBA league entry - highest priority (1)
        self._league_registry['nba'] = {
            'enabled': self.nba_enabled,
            'priority': 1,  # Highest priority - shows first
            'live_priority': self.nba_live_priority,
            'managers': {
                'live': getattr(self, 'nba_live', None),
                'recent': getattr(self, 'nba_recent', None),
                'upcoming': getattr(self, 'nba_upcoming', None),
            }
        }
        
        # WNBA league entry - second priority (2)
        self._league_registry['wnba'] = {
            'enabled': self.wnba_enabled,
            'priority': 2,  # Second priority - shows after NBA
            'live_priority': self.wnba_live_priority,
            'managers': {
                'live': getattr(self, 'wnba_live', None),
                'recent': getattr(self, 'wnba_recent', None),
                'upcoming': getattr(self, 'wnba_upcoming', None),
            }
        }
        
        # NCAA Men's Basketball league entry - third priority (3)
        self._league_registry['ncaam'] = {
            'enabled': self.ncaam_enabled,
            'priority': 3,  # Third priority - shows after WNBA
            'live_priority': self.ncaam_live_priority,
            'managers': {
                'live': getattr(self, 'ncaam_live', None),
                'recent': getattr(self, 'ncaam_recent', None),
                'upcoming': getattr(self, 'ncaam_upcoming', None),
            }
        }
        
        # NCAA Women's Basketball league entry - fourth priority (4)
        self._league_registry['ncaaw'] = {
            'enabled': self.ncaaw_enabled,
            'priority': 4,  # Fourth priority - shows after NCAA Men's
            'live_priority': self.ncaaw_live_priority,
            'managers': {
                'live': getattr(self, 'ncaaw_live', None),
                'recent': getattr(self, 'ncaaw_recent', None),
                'upcoming': getattr(self, 'ncaaw_upcoming', None),
            }
        }
        
        # Log registry state for debugging
        enabled_leagues = [lid for lid, data in self._league_registry.items() if data.get('enabled', False)]
        disabled_leagues = [lid for lid, data in self._league_registry.items() if not data.get('enabled', False)]
        self.logger.info(
            f"League registry initialized: {len(self._league_registry)} league(s) registered, "
            f"{len(enabled_leagues)} enabled: {enabled_leagues}, "
            f"{len(disabled_leagues)} disabled: {disabled_leagues}"
        )
        # Log detailed enabled state for each league (INFO level for visibility)
        for league_id, league_data in self._league_registry.items():
            self.logger.info(
                f"League {league_id}: enabled={league_data.get('enabled', False)} (type: {type(league_data.get('enabled', False))}), "
                f"priority={league_data.get('priority', 999)}"
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
            Example: ['nba', 'wnba'] means NBA shows first, then WNBA
            
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
            league_id: League identifier ('nba', 'wnba', 'ncaam', 'ncaaw', etc.)
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
            league_id: League identifier ('nba', 'wnba', 'ncaam', 'ncaaw', etc.)
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

    def _parse_display_mode_settings(self) -> Dict[str, Dict[str, str]]:
        """
        Parse display mode settings from config.
        
        Returns:
            Dict mapping league -> game_type -> display_mode ('switch' or 'scroll')
            e.g., {'nba': {'live': 'switch', 'recent': 'switch', 'upcoming': 'switch'}}
            Currently returns 'switch' for all (scroll mode not implemented)
        """
        settings = {}
        
        for league in ['nba', 'wnba', 'ncaam', 'ncaaw']:
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
            league: 'nba', 'wnba', 'ncaam', or 'ncaaw'
            game_type: 'live', 'recent', or 'upcoming'
            
        Returns:
            'switch' or 'scroll'
        """
        if not hasattr(self, '_display_mode_settings') or league not in self._display_mode_settings:
            return 'switch'
        
        return self._display_mode_settings[league].get(game_type, 'switch')

    def _extract_mode_type(self, display_mode: str) -> Optional[str]:
        """Extract mode type (live, recent, upcoming) from display mode string.
        
        Args:
            display_mode: Display mode string (e.g., 'basketball_live', 'nba_recent')
            
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
        2. League-specific mode duration (e.g., nba.live_game_duration from display_durations.live)
        3. League-specific default (15 seconds)
        
        Args:
            league: League name ('nba', 'wnba', 'ncaam', or 'ncaaw')
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
        
        # Try live_game_duration for live mode
        if mode_type == 'live':
            live_duration = league_config.get("live_game_duration")
            if live_duration is not None:
                return float(live_duration)
        
        # Fallback to league-specific default (15 seconds)
        return 15.0

    def _get_mode_duration(self, league: str, mode_type: str) -> Optional[float]:
        """
        Get mode duration from config for a league/mode combination.
        
        Checks per-league/per-mode settings first, then falls back to per-league settings.
        Returns None if not configured (uses dynamic calculation).
        
        Args:
            league: League name ('nba', 'wnba', 'ncaam', or 'ncaaw')
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

    def _adapt_config_for_manager(self, league: str) -> Dict[str, Any]:
        """
        Adapt plugin config format to manager expected format.

        Plugin uses: nba: {...}, wnba: {...}, etc.
        Managers expect: nba_scoreboard: {...}, wnba_scoreboard: {...}, etc.
        """
        league_config = self.config.get(league, {})
        
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

        # Explicitly check if keys exist for show_favorite_teams_only
        if "show_favorite_teams_only" in filtering:
            show_favorites_only = filtering["show_favorite_teams_only"]
        elif "show_favorite_teams_only" in league_config:
            show_favorites_only = league_config["show_favorite_teams_only"]
        elif "favorite_teams_only" in league_config:
            show_favorites_only = league_config["favorite_teams_only"]
        else:
            show_favorites_only = False
        
        self.logger.debug(
            f"Config reading for {league}: "
            f"league_config.show_favorite_teams_only={league_config.get('show_favorite_teams_only', 'NOT_SET')}, "
            f"filtering.show_favorite_teams_only={filtering.get('show_favorite_teams_only', 'NOT_SET')}, "
            f"final show_favorites_only={show_favorites_only}"
        )

        # Explicitly check if key exists for show_all_live
        if "show_all_live" in filtering:
            show_all_live = filtering["show_all_live"]
        elif "show_all_live" in league_config:
            show_all_live = league_config["show_all_live"]
        else:
            show_all_live = False
        
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
            # Check if league is enabled - must be explicitly True
            league_enabled = league_data.get('enabled', False)
            self.logger.info(
                f"_get_available_modes: Checking {league_id}: enabled={league_enabled} "
                f"(type: {type(league_enabled)}, bool check: {bool(league_enabled)})"
            )
            if not league_enabled:
                self.logger.info(f"Skipping disabled league: {league_id} (enabled={league_enabled})")
                continue
            
            self.logger.info(f"Processing enabled league: {league_id}")
            
            # Get league config to check display_modes settings
            league_config = self.config.get(league_id, {})
            display_modes_config = league_config.get("display_modes", {})
            
            # Check each mode type
            for mode_type in ['recent', 'upcoming', 'live']:  # Order: recent, upcoming, live
                mode_enabled = True  # Default to enabled if not specified
                if mode_type == 'live':
                    mode_enabled = display_modes_config.get("show_live", True)
                elif mode_type == 'recent':
                    mode_enabled = display_modes_config.get("show_recent", True)
                elif mode_type == 'upcoming':
                    mode_enabled = display_modes_config.get("show_upcoming", True)
                
                if mode_enabled:
                    modes.append(f"{league_id}_{mode_type}")
                    self.logger.debug(f"Added mode: {league_id}_{mode_type}")

        # Default to NBA if no leagues enabled
        if not modes:
            modes = ["nba_recent", "nba_upcoming", "nba_live"]

        self.logger.info(
            f"Available modes generated: {len(modes)} mode(s) - {modes}. "
            f"Enabled leagues: NBA={self.nba_enabled}, WNBA={self.wnba_enabled}, "
            f"NCAA Men's={self.ncaam_enabled}, NCAA Women's={self.ncaaw_enabled}"
        )
        return modes

    def _get_current_manager(self):
        """Get the current manager based on the current mode."""
        if not self.modes:
            return None

        current_mode = self.modes[self.current_mode_index]

        if current_mode.startswith("nba_"):
            if not self.nba_enabled:
                return None
            mode_type = current_mode.split("_", 1)[1]  # "live", "recent", "upcoming"
            if mode_type == "live":
                return self.nba_live
            elif mode_type == "recent":
                return self.nba_recent
            elif mode_type == "upcoming":
                return self.nba_upcoming

        elif current_mode.startswith("wnba_"):
            if not self.wnba_enabled:
                return None
            mode_type = current_mode.split("_", 1)[1]
            if mode_type == "live":
                return self.wnba_live
            elif mode_type == "recent":
                return self.wnba_recent
            elif mode_type == "upcoming":
                return self.wnba_upcoming

        elif current_mode.startswith("ncaam_"):
            if not self.ncaam_enabled:
                return None
            mode_type = current_mode.split("_", 1)[1]
            if mode_type == "live":
                return self.ncaam_live
            elif mode_type == "recent":
                return self.ncaam_recent
            elif mode_type == "upcoming":
                return self.ncaam_upcoming

        elif current_mode.startswith("ncaaw_"):
            if not self.ncaaw_enabled:
                return None
            mode_type = current_mode.split("_", 1)[1]
            if mode_type == "live":
                return self.ncaaw_live
            elif mode_type == "recent":
                return self.ncaaw_recent
            elif mode_type == "upcoming":
                return self.ncaaw_upcoming

        return None

    def update(self) -> None:
        """Update basketball game data using parallel manager updates."""
        if not self.is_enabled:
            return

        # Collect all manager update tasks
        update_tasks = []
        
        if self.nba_enabled:
            update_tasks.extend([
                ("NBA Live", self.nba_live.update),
                ("NBA Recent", self.nba_recent.update),
                ("NBA Upcoming", self.nba_upcoming.update),
            ])
        
        if self.wnba_enabled:
            update_tasks.extend([
                ("WNBA Live", self.wnba_live.update),
                ("WNBA Recent", self.wnba_recent.update),
                ("WNBA Upcoming", self.wnba_upcoming.update),
            ])
        
        if self.ncaam_enabled:
            update_tasks.extend([
                ("NCAA Men's Live", self.ncaam_live.update),
                ("NCAA Men's Recent", self.ncaam_recent.update),
                ("NCAA Men's Upcoming", self.ncaam_upcoming.update),
            ])
        
        if self.ncaaw_enabled:
            update_tasks.extend([
                ("NCAA Women's Live", self.ncaaw_live.update),
                ("NCAA Women's Recent", self.ncaaw_recent.update),
                ("NCAA Women's Upcoming", self.ncaaw_upcoming.update),
            ])
        
        if not update_tasks:
            return
        
        # Run updates in parallel with individual error handling
        def run_update_with_error_handling(name: str, update_func):
            """Run a single manager update with error handling."""
            try:
                update_func()
            except Exception as e:
                self.logger.error(f"Error updating {name} manager: {e}", exc_info=True)
        
        # Start all update threads
        threads = []
        for name, update_func in update_tasks:
            thread = threading.Thread(
                target=run_update_with_error_handling,
                args=(name, update_func),
                daemon=True,
                name=f"Update-{name}"
            )
            thread.start()
            threads.append(thread)
        
        # Wait for all threads to complete with a reasonable timeout
        # Use 25 seconds to stay under the 30-second plugin timeout
        for thread in threads:
            thread.join(timeout=25.0)
            if thread.is_alive():
                self.logger.warning(
                    f"Manager update thread {thread.name} did not complete within timeout"
                )

    def display(self, display_mode: str = None, force_clear: bool = False) -> bool:
        """Display basketball games with mode cycling.
        
        Args:
            display_mode: Optional mode name (e.g., 'basketball_live', 'basketball_recent', 'basketball_upcoming').
                         If provided, displays that specific mode. If None, uses internal mode cycling.
            force_clear: If True, clear display before rendering
        """
        if not self.is_enabled:
            return False

        try:
            # If display_mode is provided, use it to determine which manager to call
            if display_mode:
                # Early exit: Skip if this mode is not in our available modes (disabled league)
                if display_mode not in self.modes:
                    self.logger.debug(f"Skipping disabled mode: {display_mode} (not in available modes: {self.modes})")
                    return False
                
                self.logger.debug(f"Display called with mode: {display_mode}")
                
                # Check if this is a granular mode (league-specific, e.g., ncaam_recent, nba_live)
                # Granular modes: {league}_{mode_type} format
                # Known league prefixes: nba, wnba, ncaam, ncaaw
                league = None
                mode_type = None
                
                # Try to match against league registry first (most reliable)
                mode_suffixes = ['_live', '_recent', '_upcoming']
                for league_id in self._league_registry.keys():
                    for mode_suffix in mode_suffixes:
                        expected_mode = f"{league_id}{mode_suffix}"
                        if display_mode == expected_mode:
                            league = league_id
                            mode_type = mode_suffix[1:]  # Remove leading underscore
                            break
                    if league:
                        break
                
                # Fallback: parse from the end if no registry match
                if not league:
                    if display_mode.endswith('_live'):
                        mode_type = 'live'
                        potential_league = display_mode[:-5]  # Remove '_live'
                    elif display_mode.endswith('_recent'):
                        mode_type = 'recent'
                        potential_league = display_mode[:-7]  # Remove '_recent'
                    elif display_mode.endswith('_upcoming'):
                        mode_type = 'upcoming'
                        potential_league = display_mode[:-9]  # Remove '_upcoming'
                    
                    # Validate it's a known league
                    if mode_type and potential_league in self._league_registry:
                        league = potential_league
                
                # If we have a specific league, route directly to it
                if league and mode_type:
                    self.logger.debug(f"Granular mode detected: league={league}, mode_type={mode_type}")
                    return self._display_league_mode(league, mode_type, force_clear)
                
                # Legacy combined mode handling (basketball_live, basketball_recent, basketball_upcoming)
                # Extract the mode type for legacy modes
                if not mode_type:
                    if display_mode.endswith('_live'):
                        mode_type = 'live'
                    elif display_mode.endswith('_recent'):
                        mode_type = 'recent'
                    elif display_mode.endswith('_upcoming'):
                        mode_type = 'upcoming'
                
                if not mode_type:
                    self.logger.warning(f"Unknown display_mode: {display_mode}")
                    return False
                
                self.logger.debug(
                    f"Legacy combined mode: mode_type={mode_type}, NBA enabled: {self.nba_enabled}, "
                    f"WNBA enabled: {self.wnba_enabled}, NCAA Men's enabled: {self.ncaam_enabled}, "
                    f"NCAA Women's enabled: {self.ncaaw_enabled}"
                )
                
                # Determine which manager to use based on enabled leagues
                # For live mode, prioritize leagues with live content and live_priority enabled
                managers_to_try = []
                
                if mode_type == 'live':
                    # Check NBA first (highest priority)
                    if (self.nba_enabled and self.nba_live_priority and 
                        hasattr(self, 'nba_live') and 
                        bool(getattr(self.nba_live, 'live_games', []))):
                        managers_to_try.append(self.nba_live)
                    # Check WNBA
                    if (self.wnba_enabled and self.wnba_live_priority and 
                        hasattr(self, 'wnba_live') and 
                        bool(getattr(self.wnba_live, 'live_games', []))):
                        managers_to_try.append(self.wnba_live)
                    # Check NCAA Men's
                    if (self.ncaam_enabled and self.ncaam_live_priority and 
                        hasattr(self, 'ncaam_live') and 
                        bool(getattr(self.ncaam_live, 'live_games', []))):
                        managers_to_try.append(self.ncaam_live)
                    # Check NCAA Women's
                    if (self.ncaaw_enabled and self.ncaaw_live_priority and 
                        hasattr(self, 'ncaaw_live') and 
                        bool(getattr(self.ncaaw_live, 'live_games', []))):
                        managers_to_try.append(self.ncaaw_live)
                    
                    # Fallback: if no live content, show any enabled live manager
                    if not managers_to_try:
                        if self.nba_enabled and hasattr(self, 'nba_live'):
                            managers_to_try.append(self.nba_live)
                        elif self.wnba_enabled and hasattr(self, 'wnba_live'):
                            managers_to_try.append(self.wnba_live)
                        elif self.ncaam_enabled and hasattr(self, 'ncaam_live'):
                            managers_to_try.append(self.ncaam_live)
                        elif self.ncaaw_enabled and hasattr(self, 'ncaaw_live'):
                            managers_to_try.append(self.ncaaw_live)
                else:
                    # For recent and upcoming modes, use standard priority order
                    # NBA > WNBA > NCAA Men's > NCAA Women's
                    if self.nba_enabled:
                        if mode_type == 'recent' and hasattr(self, 'nba_recent'):
                            managers_to_try.append(self.nba_recent)
                        elif mode_type == 'upcoming' and hasattr(self, 'nba_upcoming'):
                            managers_to_try.append(self.nba_upcoming)
                    
                    if self.wnba_enabled:
                        if mode_type == 'recent' and hasattr(self, 'wnba_recent'):
                            managers_to_try.append(self.wnba_recent)
                        elif mode_type == 'upcoming' and hasattr(self, 'wnba_upcoming'):
                            managers_to_try.append(self.wnba_upcoming)
                    
                    if self.ncaam_enabled:
                        if mode_type == 'recent' and hasattr(self, 'ncaam_recent'):
                            managers_to_try.append(self.ncaam_recent)
                        elif mode_type == 'upcoming' and hasattr(self, 'ncaam_upcoming'):
                            managers_to_try.append(self.ncaam_upcoming)
                    
                    if self.ncaaw_enabled:
                        if mode_type == 'recent' and hasattr(self, 'ncaaw_recent'):
                            managers_to_try.append(self.ncaaw_recent)
                        elif mode_type == 'upcoming' and hasattr(self, 'ncaaw_upcoming'):
                            managers_to_try.append(self.ncaaw_upcoming)
                
                # Try each manager until one returns True (has content)
                # Don't clear at the start - let the first successful manager clear when it displays
                # This prevents blank screens if all managers fail
                first_manager = True
                for current_manager in managers_to_try:
                    if current_manager:
                        # Track which league we're displaying for granular dynamic duration
                        if hasattr(self, 'nba_live') and (current_manager == self.nba_live or current_manager == self.nba_recent or current_manager == self.nba_upcoming):
                            self._current_display_league = 'nba'
                        elif hasattr(self, 'wnba_live') and (current_manager == self.wnba_live or current_manager == self.wnba_recent or current_manager == self.wnba_upcoming):
                            self._current_display_league = 'wnba'
                        elif hasattr(self, 'ncaam_live') and (current_manager == self.ncaam_live or current_manager == self.ncaam_recent or current_manager == self.ncaam_upcoming):
                            self._current_display_league = 'ncaam'
                        elif hasattr(self, 'ncaaw_live') and (current_manager == self.ncaaw_live or current_manager == self.ncaaw_recent or current_manager == self.ncaaw_upcoming):
                            self._current_display_league = 'ncaaw'
                        self._current_display_mode_type = mode_type
                        
                        # Only pass force_clear to the first manager
                        # Subsequent managers shouldn't clear to avoid flashing
                        manager_force_clear = force_clear and first_manager
                        first_manager = False
                        
                        # Build actual mode name for tracking
                        actual_mode = f"{self._current_display_league}_{mode_type}" if self._current_display_league and mode_type else display_mode
                        
                        result = current_manager.display(manager_force_clear)
                        # If display returned True, we have content to show
                        if result is True:
                            try:
                                self._record_dynamic_progress(current_manager, actual_mode=actual_mode, display_mode=display_mode)
                            except Exception as progress_err:
                                self.logger.debug(
                                    "Dynamic progress tracking failed: %s", progress_err
                                )
                            self._evaluate_dynamic_cycle_completion(display_mode=display_mode)
                            return result
                        # If result is False, try next manager
                        elif result is False:
                            continue
                        # If result is None or other, assume success
                        else:
                            try:
                                self._record_dynamic_progress(current_manager, actual_mode=actual_mode, display_mode=display_mode)
                            except Exception as progress_err:
                                self.logger.debug(
                                    "Dynamic progress tracking failed: %s", progress_err
                                )
                            self._evaluate_dynamic_cycle_completion(display_mode=display_mode)
                            return True
                
                # No manager had content
                if not managers_to_try:
                    self.logger.warning(
                        f"No managers available for mode: {display_mode} "
                        f"(NBA: {self.nba_enabled}, WNBA: {self.wnba_enabled}, "
                        f"NCAA Men's: {self.ncaam_enabled}, NCAA Women's: {self.ncaaw_enabled})"
                    )
                else:
                    self.logger.info(
                        f"No content available for mode: {display_mode} after trying {len(managers_to_try)} manager(s) - returning False"
                    )
                
                # Don't clear the display when returning False - let the caller handle skipping
                # Clearing here would show a blank screen before the next mode is displayed
                return False
            
            # Fall back to internal mode cycling if no display_mode provided
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
                self.current_mode_index = (self.current_mode_index + 1) % len(
                    self.modes
                )
                self.last_mode_switch = current_time
                force_clear = True

                current_mode = self.modes[self.current_mode_index]
                self.logger.info(f"Switching to display mode: {current_mode}")

            # Get current manager and display
            current_manager = self._get_current_manager()
            if current_manager:
                # Track which league/mode we're displaying for granular dynamic duration
                current_mode = self.modes[self.current_mode_index] if self.modes else None
                if current_mode:
                    if current_mode.startswith("nba_"):
                        self._current_display_league = 'nba'
                        self._current_display_mode_type = current_mode.split("_", 1)[1]
                    elif current_mode.startswith("wnba_"):
                        self._current_display_league = 'wnba'
                        self._current_display_mode_type = current_mode.split("_", 1)[1]
                    elif current_mode.startswith("ncaam_"):
                        self._current_display_league = 'ncaam'
                        self._current_display_mode_type = current_mode.split("_", 1)[1]
                    elif current_mode.startswith("ncaaw_"):
                        self._current_display_league = 'ncaaw'
                        self._current_display_mode_type = current_mode.split("_", 1)[1]
                
                result = current_manager.display(force_clear)
                if result is not False:
                    try:
                        # Build actual mode name for tracking
                        actual_mode = current_mode
                        self._record_dynamic_progress(current_manager, actual_mode=actual_mode, display_mode=actual_mode)
                    except Exception as progress_err:
                        self.logger.debug(
                            "Dynamic progress tracking failed: %s", progress_err
                        )
                else:
                    # Manager returned False (no content) - don't clear, just return False
                    # Clearing here would show a blank screen before the next mode is displayed
                    pass
                self._evaluate_dynamic_cycle_completion(display_mode=current_mode)
                return result
            else:
                self.logger.warning("No manager available for current mode")
                return False

        except Exception as e:
            self.logger.error(f"Error in display method: {e}", exc_info=True)
            return False

    def has_live_priority(self) -> bool:
        if not self.is_enabled:
            return False
        return (
            (self.nba_enabled and self.nba_live_priority)
            or (self.wnba_enabled and self.wnba_live_priority)
            or (self.ncaam_enabled and self.ncaam_live_priority)
            or (self.ncaaw_enabled and self.ncaaw_live_priority)
        )

    def has_live_content(self) -> bool:
        if not self.is_enabled:
            return False

        # Check NBA live content
        nba_live = False
        if (
            self.nba_enabled
            and self.nba_live_priority
            and hasattr(self, "nba_live")
        ):
            live_games = getattr(self.nba_live, "live_games", [])
            if live_games:
                # Filter out any games that are final or appear over
                live_games = [g for g in live_games if not g.get("is_final", False)]
                # Additional validation using helper method if available
                if hasattr(self.nba_live, "_is_game_really_over"):
                    live_games = [g for g in live_games if not self.nba_live._is_game_really_over(g)]
                
                if live_games:
                    # If favorite teams are configured, only return True if there are live games for favorite teams
                    favorite_teams = getattr(self.nba_live, "favorite_teams", [])
                    if favorite_teams:
                        # Check if any live game involves a favorite team
                        nba_live = any(
                            game.get("home_abbr") in favorite_teams
                            or game.get("away_abbr") in favorite_teams
                            for game in live_games
                        )
                    else:
                        # No favorite teams configured, return True if any live games exist
                        nba_live = True

        # Check WNBA live content
        wnba_live = False
        if (
            self.wnba_enabled
            and self.wnba_live_priority
            and hasattr(self, "wnba_live")
        ):
            live_games = getattr(self.wnba_live, "live_games", [])
            if live_games:
                # Filter out any games that are final or appear over
                live_games = [g for g in live_games if not g.get("is_final", False)]
                # Additional validation using helper method if available
                if hasattr(self.wnba_live, "_is_game_really_over"):
                    live_games = [g for g in live_games if not self.wnba_live._is_game_really_over(g)]
                
                if live_games:
                    # If favorite teams are configured, only return True if there are live games for favorite teams
                    favorite_teams = getattr(self.wnba_live, "favorite_teams", [])
                    if favorite_teams:
                        # Check if any live game involves a favorite team
                        wnba_live = any(
                            game.get("home_abbr") in favorite_teams
                            or game.get("away_abbr") in favorite_teams
                            for game in live_games
                        )
                    else:
                        # No favorite teams configured, return True if any live games exist
                        wnba_live = True

        # Check NCAA Men's live content
        ncaam_live = False
        if (
            self.ncaam_enabled
            and self.ncaam_live_priority
            and hasattr(self, "ncaam_live")
        ):
            live_games = getattr(self.ncaam_live, "live_games", [])
            if live_games:
                # Filter out any games that are final or appear over
                live_games = [g for g in live_games if not g.get("is_final", False)]
                # Additional validation using helper method if available
                if hasattr(self.ncaam_live, "_is_game_really_over"):
                    live_games = [g for g in live_games if not self.ncaam_live._is_game_really_over(g)]
                
                if live_games:
                    # If favorite teams are configured, only return True if there are live games for favorite teams
                    favorite_teams = getattr(self.ncaam_live, "favorite_teams", [])
                    if favorite_teams:
                        # Check if any live game involves a favorite team
                        ncaam_live = any(
                            game.get("home_abbr") in favorite_teams
                            or game.get("away_abbr") in favorite_teams
                            for game in live_games
                        )
                    else:
                        # No favorite teams configured, return True if any live games exist
                        ncaam_live = True

        # Check NCAA Women's live content
        ncaaw_live = False
        if (
            self.ncaaw_enabled
            and self.ncaaw_live_priority
            and hasattr(self, "ncaaw_live")
        ):
            live_games = getattr(self.ncaaw_live, "live_games", [])
            if live_games:
                # Filter out any games that are final or appear over
                live_games = [g for g in live_games if not g.get("is_final", False)]
                # Additional validation using helper method if available
                if hasattr(self.ncaaw_live, "_is_game_really_over"):
                    live_games = [g for g in live_games if not self.ncaaw_live._is_game_really_over(g)]
                
                if live_games:
                    # If favorite teams are configured, only return True if there are live games for favorite teams
                    favorite_teams = getattr(self.ncaaw_live, "favorite_teams", [])
                    if favorite_teams:
                        # Check if any live game involves a favorite team
                        ncaaw_live = any(
                            game.get("home_abbr") in favorite_teams
                            or game.get("away_abbr") in favorite_teams
                            for game in live_games
                        )
                    else:
                        # No favorite teams configured, return True if any live games exist
                        ncaaw_live = True

        result = nba_live or wnba_live or ncaam_live or ncaaw_live
        
        # Throttle logging when returning False to reduce log noise
        # Always log True immediately (important), but only log False every 60 seconds
        current_time = time.time()
        should_log = result or (current_time - self._last_live_content_false_log >= self._live_content_log_interval)
        
        if should_log:
            if result:
                # Always log True results immediately
                self.logger.info(f"has_live_content() returning {result}: nba_live={nba_live}, wnba_live={wnba_live}, ncaam_live={ncaam_live}, ncaaw_live={ncaaw_live}")
            else:
                # Log False results only every 60 seconds
                self.logger.info(f"has_live_content() returning {result}: nba_live={nba_live}, wnba_live={wnba_live}, ncaam_live={ncaam_live}, ncaaw_live={ncaaw_live}")
                self._last_live_content_false_log = current_time
        
        return result

    def get_live_modes(self) -> list:
        """
        Return the registered plugin mode name(s) that have live content.
        
        Returns granular live modes (nba_live, wnba_live, etc.) that have live content.
        The plugin is registered with granular modes in manifest.json.
        """
        if not self.is_enabled:
            return []

        live_modes = []
        
        # Check NBA live content
        if (
            self.nba_enabled
            and self.nba_live_priority
            and hasattr(self, "nba_live")
        ):
            live_games = getattr(self.nba_live, "live_games", [])
            if live_games:
                # Filter out any games that are final or appear over
                live_games = [g for g in live_games if not g.get("is_final", False)]
                # Additional validation using helper method if available
                if hasattr(self.nba_live, "_is_game_really_over"):
                    live_games = [g for g in live_games if not self.nba_live._is_game_really_over(g)]
                
                if live_games:
                    # Check if favorite teams filter applies
                    favorite_teams = getattr(self.nba_live, "favorite_teams", [])
                    if favorite_teams:
                        # Only include if there are live games for favorite teams
                        if any(
                            game.get("home_abbr") in favorite_teams
                            or game.get("away_abbr") in favorite_teams
                            for game in live_games
                        ):
                            live_modes.append("nba_live")
                    else:
                        # No favorite teams configured, include if any live games exist
                        live_modes.append("nba_live")
        
        # Check WNBA live content
        if (
            self.wnba_enabled
            and self.wnba_live_priority
            and hasattr(self, "wnba_live")
        ):
            live_games = getattr(self.wnba_live, "live_games", [])
            if live_games:
                # Filter out any games that are final or appear over
                live_games = [g for g in live_games if not g.get("is_final", False)]
                # Additional validation using helper method if available
                if hasattr(self.wnba_live, "_is_game_really_over"):
                    live_games = [g for g in live_games if not self.wnba_live._is_game_really_over(g)]
                
                if live_games:
                    # Check if favorite teams filter applies
                    favorite_teams = getattr(self.wnba_live, "favorite_teams", [])
                    if favorite_teams:
                        # Only include if there are live games for favorite teams
                        if any(
                            game.get("home_abbr") in favorite_teams
                            or game.get("away_abbr") in favorite_teams
                            for game in live_games
                        ):
                            live_modes.append("wnba_live")
                    else:
                        # No favorite teams configured, include if any live games exist
                        live_modes.append("wnba_live")
        
        # Check NCAA Men's live content
        if (
            self.ncaam_enabled
            and self.ncaam_live_priority
            and hasattr(self, "ncaam_live")
        ):
            live_games = getattr(self.ncaam_live, "live_games", [])
            if live_games:
                # Filter out any games that are final or appear over
                live_games = [g for g in live_games if not g.get("is_final", False)]
                # Additional validation using helper method if available
                if hasattr(self.ncaam_live, "_is_game_really_over"):
                    live_games = [g for g in live_games if not self.ncaam_live._is_game_really_over(g)]
                
                if live_games:
                    # Check if favorite teams filter applies
                    favorite_teams = getattr(self.ncaam_live, "favorite_teams", [])
                    if favorite_teams:
                        # Only include if there are live games for favorite teams
                        if any(
                            game.get("home_abbr") in favorite_teams
                            or game.get("away_abbr") in favorite_teams
                            for game in live_games
                        ):
                            live_modes.append("ncaam_live")
                    else:
                        # No favorite teams configured, include if any live games exist
                        live_modes.append("ncaam_live")
        
        # Check NCAA Women's live content
        if (
            self.ncaaw_enabled
            and self.ncaaw_live_priority
            and hasattr(self, "ncaaw_live")
        ):
            live_games = getattr(self.ncaaw_live, "live_games", [])
            if live_games:
                # Filter out any games that are final or appear over
                live_games = [g for g in live_games if not g.get("is_final", False)]
                # Additional validation using helper method if available
                if hasattr(self.ncaaw_live, "_is_game_really_over"):
                    live_games = [g for g in live_games if not self.ncaaw_live._is_game_really_over(g)]
                
                if live_games:
                    # Check if favorite teams filter applies
                    favorite_teams = getattr(self.ncaaw_live, "favorite_teams", [])
                    if favorite_teams:
                        # Only include if there are live games for favorite teams
                        if any(
                            game.get("home_abbr") in favorite_teams
                            or game.get("away_abbr") in favorite_teams
                            for game in live_games
                        ):
                            live_modes.append("ncaaw_live")
                    else:
                        # No favorite teams configured, include if any live games exist
                        live_modes.append("ncaaw_live")
        
        return live_modes

    def _should_use_scroll_mode(self, league: str, mode_type: str) -> bool:
        """
        Check if a specific league should use scroll mode for this game type.
        
        Args:
            league: League ID ('nba', 'wnba', 'ncaam', or 'ncaaw')
            mode_type: 'live', 'recent', or 'upcoming'
            
        Returns:
            True if this league uses scroll mode for this game type
        """
        return self._get_display_mode(league, mode_type) == 'scroll'

    def _display_scroll_mode(self, display_mode: str, league: str, mode_type: str, force_clear: bool) -> bool:
        """Handle display for scroll mode (single league).
        
        Args:
            display_mode: External mode name (e.g., 'nba_recent')
            league: League ID ('nba', 'wnba', 'ncaam', or 'ncaaw')
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
                    f"[Basketball Scroll] Started scrolling {len(games)} {league} {mode_type} games"
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
                    self.logger.info(f"[Basketball Scroll] Cycle complete for {display_mode}")
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
        Display a specific league/mode combination (e.g., NBA Recent, WNBA Upcoming).
        
        This method displays content from a single league and mode type, used when
        rotation_order specifies granular modes like 'nba_recent' or 'wnba_upcoming'.
        
        Args:
            league: League ID ('nba', 'wnba', 'ncaam', or 'ncaaw')
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

    def _set_display_context_from_manager(self, manager, mode_type: str) -> None:
        """Set current display league and mode type based on manager instance.
        
        Args:
            manager: Manager instance
            mode_type: 'live', 'recent', or 'upcoming'
        """
        self._current_display_mode_type = mode_type
        
        # Check NBA managers
        if manager in (getattr(self, 'nba_live', None), 
                      getattr(self, 'nba_recent', None), 
                      getattr(self, 'nba_upcoming', None)):
            self._current_display_league = 'nba'
        # Check WNBA managers
        elif manager in (getattr(self, 'wnba_live', None), 
                        getattr(self, 'wnba_recent', None), 
                        getattr(self, 'wnba_upcoming', None)):
            self._current_display_league = 'wnba'
        # Check NCAA Men's managers
        elif manager in (getattr(self, 'ncaam_live', None), 
                        getattr(self, 'ncaam_recent', None), 
                        getattr(self, 'ncaam_upcoming', None)):
            self._current_display_league = 'ncaam'
        # Check NCAA Women's managers
        elif manager in (getattr(self, 'ncaaw_live', None), 
                        getattr(self, 'ncaaw_recent', None), 
                        getattr(self, 'ncaaw_upcoming', None)):
            self._current_display_league = 'ncaaw'

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
            display_mode: External display mode name (e.g., 'basketball_recent')
            mode_type: Mode type ('live', 'recent', or 'upcoming')
            sticky_manager: Deprecated parameter (kept for compatibility, ignored)
            
        Returns:
            Tuple of (success: bool, actual_mode: Optional[str])
            - success: True if manager displayed content, False otherwise
            - actual_mode: The actual mode name used for tracking (e.g., 'nba_recent')
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
        # Example: 'nba_recent' or 'wnba_live'
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
            display_mode: Display mode name (e.g., 'nba_recent')
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
            display_mode: The display mode to calculate duration for (e.g., 'basketball_live', 'basketball_recent', 'nba_live', 'wnba_recent')
        
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
        
        # Parse granular mode name if applicable (e.g., "nba_recent", "wnba_upcoming")
        league = None
        if "_" in display_mode and not display_mode.startswith("basketball_"):
            # Granular mode: extract league
            # Handle ncaam and ncaaw with multiple underscores
            if display_mode.startswith("ncaam_"):
                league = "ncaam"
            elif display_mode.startswith("ncaaw_"):
                league = "ncaaw"
            elif display_mode.startswith("nba_"):
                league = "nba"
            elif display_mode.startswith("wnba_"):
                league = "wnba"
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
                if display_mode.startswith("nba_"):
                    league = "nba"
                elif display_mode.startswith("wnba_"):
                    league = "wnba"
                elif display_mode.startswith("ncaam_"):
                    league = "ncaam"
                elif display_mode.startswith("ncaaw_"):
                    league = "ncaaw"
        
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
            per_game_duration = self.game_display_duration  # Default fallback (will be overridden per league)
            
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
                    if self.nba_enabled:
                        nba_manager = self._get_league_manager_for_mode('nba', 'live')
                        if nba_manager:
                            managers_to_check.append(('nba', nba_manager))
                    if self.wnba_enabled:
                        wnba_manager = self._get_league_manager_for_mode('wnba', 'live')
                        if wnba_manager:
                            managers_to_check.append(('wnba', wnba_manager))
                    if self.ncaam_enabled:
                        ncaam_manager = self._get_league_manager_for_mode('ncaam', 'live')
                        if ncaam_manager:
                            managers_to_check.append(('ncaam', ncaam_manager))
                    if self.ncaaw_enabled:
                        ncaaw_manager = self._get_league_manager_for_mode('ncaaw', 'live')
                        if ncaaw_manager:
                            managers_to_check.append(('ncaaw', ncaaw_manager))
                elif mode_type == 'recent':
                    if self.nba_enabled:
                        nba_manager = self._get_league_manager_for_mode('nba', 'recent')
                        if nba_manager:
                            managers_to_check.append(('nba', nba_manager))
                    if self.wnba_enabled:
                        wnba_manager = self._get_league_manager_for_mode('wnba', 'recent')
                        if wnba_manager:
                            managers_to_check.append(('wnba', wnba_manager))
                    if self.ncaam_enabled:
                        ncaam_manager = self._get_league_manager_for_mode('ncaam', 'recent')
                        if ncaam_manager:
                            managers_to_check.append(('ncaam', ncaam_manager))
                    if self.ncaaw_enabled:
                        ncaaw_manager = self._get_league_manager_for_mode('ncaaw', 'recent')
                        if ncaaw_manager:
                            managers_to_check.append(('ncaaw', ncaaw_manager))
                elif mode_type == 'upcoming':
                    if self.nba_enabled:
                        nba_manager = self._get_league_manager_for_mode('nba', 'upcoming')
                        if nba_manager:
                            managers_to_check.append(('nba', nba_manager))
                    if self.wnba_enabled:
                        wnba_manager = self._get_league_manager_for_mode('wnba', 'upcoming')
                        if wnba_manager:
                            managers_to_check.append(('wnba', wnba_manager))
                    if self.ncaam_enabled:
                        ncaam_manager = self._get_league_manager_for_mode('ncaam', 'upcoming')
                        if ncaam_manager:
                            managers_to_check.append(('ncaam', ncaam_manager))
                    if self.ncaaw_enabled:
                        ncaaw_manager = self._get_league_manager_for_mode('ncaaw', 'upcoming')
                        if ncaaw_manager:
                            managers_to_check.append(('ncaaw', ncaaw_manager))
            
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
                    
                    self.logger.debug(
                        f"get_cycle_duration: {league_name} {mode_type} has {game_count} games, "
                        f"per_game_duration={per_game_duration}s"
                    )
            
            self.logger.info(f"get_cycle_duration: found {total_games} total games for {display_mode}")
            
            if total_games == 0:
                # If no games found yet (managers still fetching data), return a default duration
                # This allows the display to start while data is loading
                default_duration = 45.0  # 3 games × 15s per game (reasonable default)
                self.logger.info(f"get_cycle_duration: {display_mode} has no games yet, returning default {default_duration}s")
                return default_duration
            
            # Calculate total duration: num_games × per_game_duration
            total_duration = total_games * per_game_duration
            self.logger.info(
                f"get_cycle_duration({display_mode}): {total_games} games × {per_game_duration}s = {total_duration}s"
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
                "name": "Basketball Scoreboard",
                "version": "2.0.0",
                "enabled": self.is_enabled,
                "display_size": f"{self.display_width}x{self.display_height}",
                "nba_enabled": self.nba_enabled,
                "wnba_enabled": self.wnba_enabled,
                "ncaam_enabled": self.ncaam_enabled,
                "ncaaw_enabled": self.ncaaw_enabled,
                "current_mode": current_mode,
                "available_modes": self.modes,
                "display_duration": self.display_duration,
                "game_display_duration": self.game_display_duration,
                "live_priority": {
                    "nba": self.nba_enabled and self.nba_live_priority,
                    "wnba": self.wnba_enabled and self.wnba_live_priority,
                    "ncaam": self.ncaam_enabled and self.ncaam_live_priority,
                    "ncaaw": self.ncaaw_enabled and self.ncaaw_live_priority,
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
                    "nba_live": hasattr(self, "nba_live"),
                    "nba_recent": hasattr(self, "nba_recent"),
                    "nba_upcoming": hasattr(self, "nba_upcoming"),
                    "wnba_live": hasattr(self, "wnba_live"),
                    "wnba_recent": hasattr(self, "wnba_recent"),
                    "wnba_upcoming": hasattr(self, "wnba_upcoming"),
                    "ncaam_live": hasattr(self, "ncaam_live"),
                    "ncaam_recent": hasattr(self, "ncaam_recent"),
                    "ncaam_upcoming": hasattr(self, "ncaam_upcoming"),
                    "ncaaw_live": hasattr(self, "ncaaw_live"),
                    "ncaaw_recent": hasattr(self, "ncaaw_recent"),
                    "ncaaw_upcoming": hasattr(self, "ncaaw_upcoming"),
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
                "name": "Basketball Scoreboard",
                "error": str(e),
            }

    # ------------------------------------------------------------------
    # Dynamic duration hooks
    # ------------------------------------------------------------------
    def reset_cycle_state(self) -> None:
        """Reset dynamic cycle tracking."""
        super().reset_cycle_state()
        self._dynamic_cycle_seen_modes.clear()
        self._dynamic_mode_to_manager_key.clear()
        self._dynamic_manager_progress.clear()
        self._dynamic_managers_completed.clear()
        self._dynamic_cycle_complete = False

    def is_cycle_complete(self) -> bool:
        """Report whether the plugin has shown a full cycle of content."""
        if not self._dynamic_feature_enabled():
            return True
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
        Checks granular settings: per-league/per-mode > per-league.
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
        
        # If no current display context, check global setting
        if not self._current_display_league or not self._current_display_mode_type:
            return super().get_dynamic_duration_cap()
        
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

    def _get_manager_for_mode(self, mode_name: str):
        """Resolve manager instance for a given display mode."""
        if mode_name.startswith("nba_"):
            if not self.nba_enabled:
                return None
            suffix = mode_name.split("_", 1)[1]
            if suffix == "live":
                return getattr(self, "nba_live", None)
            if suffix == "recent":
                return getattr(self, "nba_recent", None)
            if suffix == "upcoming":
                return getattr(self, "nba_upcoming", None)
        elif mode_name.startswith("wnba_"):
            if not self.wnba_enabled:
                return None
            suffix = mode_name.split("_", 1)[1]
            if suffix == "live":
                return getattr(self, "wnba_live", None)
            if suffix == "recent":
                return getattr(self, "wnba_recent", None)
            if suffix == "upcoming":
                return getattr(self, "wnba_upcoming", None)
        elif mode_name.startswith("ncaam_"):
            if not self.ncaam_enabled:
                return None
            suffix = mode_name.split("_", 1)[1]
            if suffix == "live":
                return getattr(self, "ncaam_live", None)
            if suffix == "recent":
                return getattr(self, "ncaam_recent", None)
            if suffix == "upcoming":
                return getattr(self, "ncaam_upcoming", None)
        elif mode_name.startswith("ncaaw_"):
            if not self.ncaaw_enabled:
                return None
            suffix = mode_name.split("_", 1)[1]
            if suffix == "live":
                return getattr(self, "ncaaw_live", None)
            if suffix == "recent":
                return getattr(self, "ncaaw_recent", None)
            if suffix == "upcoming":
                return getattr(self, "ncaaw_upcoming", None)
        return None

    def _get_rankings_cache(self) -> Dict[str, int]:
        """Get combined team rankings cache from all managers.
        
        Returns:
            Dictionary mapping team abbreviations to their rankings/positions
            Format: {'LAL': 1, 'BOS': 2, ...}
            Empty dict if no rankings available
        """
        rankings = {}
        
        # Try to get rankings from each manager
        for manager_attr in ['nba_live', 'nba_recent', 'nba_upcoming', 
                            'wnba_live', 'wnba_recent', 'wnba_upcoming',
                            'ncaam_live', 'ncaam_recent', 'ncaam_upcoming',
                            'ncaaw_live', 'ncaaw_recent', 'ncaaw_upcoming']:
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
            league: 'nba', 'wnba', 'ncaam', or 'ncaaw'
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
            if current_mode.startswith('nba_'):
                league = 'nba'
                mode_type = current_mode.split('_', 1)[1]
            elif current_mode.startswith('wnba_'):
                league = 'wnba'
                mode_type = current_mode.split('_', 1)[1]
            elif current_mode.startswith('ncaam_'):
                league = 'ncaam'
                mode_type = current_mode.split('_', 1)[1]
            elif current_mode.startswith('ncaaw_'):
                league = 'ncaaw'
                mode_type = current_mode.split('_', 1)[1]
        
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
            display_mode: External display mode name (e.g., 'basketball_recent')
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
                                    league = None
                                    if mode_name.startswith('nba_'):
                                        league = 'nba'
                                    elif mode_name.startswith('wnba_'):
                                        league = 'wnba'
                                    elif mode_name.startswith('ncaam_'):
                                        league = 'ncaam'
                                    elif mode_name.startswith('ncaaw_'):
                                        league = 'ncaaw'
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
                            league = None
                            if mode_name.startswith('nba_'):
                                league = 'nba'
                            elif mode_name.startswith('wnba_'):
                                league = 'wnba'
                            elif mode_name.startswith('ncaam_'):
                                league = 'ncaam'
                            elif mode_name.startswith('ncaaw_'):
                                league = 'ncaaw'
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

    # -------------------------------------------------------------------------
    # Scroll mode helper methods
    # -------------------------------------------------------------------------
    def _collect_games_for_scroll(
        self,
        mode_type: str = None,
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

        # Collect NBA games if enabled
        if self.nba_enabled:
            league_games = []
            for mt in mode_types:
                manager = self._get_manager_for_league_mode('nba', mt)
                if manager:
                    nba_games = self._get_games_from_manager(manager, mt)
                    if nba_games:
                        # Add league info and ensure status field
                        for game in nba_games:
                            game['league'] = 'nba'
                            # Ensure game has status for type determination
                            if 'status' not in game:
                                game['status'] = {}
                            if 'state' not in game['status']:
                                # Infer state from mode_type
                                state_map = {'live': 'in', 'recent': 'post', 'upcoming': 'pre'}
                                game['status']['state'] = state_map.get(mt, 'pre')
                        league_games.extend(nba_games)
                        self.logger.debug(f"Collected {len(nba_games)} NBA {mt} games for scroll")

            if league_games:
                games.extend(league_games)
                leagues.append('nba')

        # Collect WNBA games if enabled
        if self.wnba_enabled:
            league_games = []
            for mt in mode_types:
                manager = self._get_manager_for_league_mode('wnba', mt)
                if manager:
                    wnba_games = self._get_games_from_manager(manager, mt)
                    if wnba_games:
                        # Add league info and ensure status field
                        for game in wnba_games:
                            game['league'] = 'wnba'
                            # Ensure game has status for type determination
                            if 'status' not in game:
                                game['status'] = {}
                            if 'state' not in game['status']:
                                state_map = {'live': 'in', 'recent': 'post', 'upcoming': 'pre'}
                                game['status']['state'] = state_map.get(mt, 'pre')
                        league_games.extend(wnba_games)
                        self.logger.debug(f"Collected {len(wnba_games)} WNBA {mt} games for scroll")

            if league_games:
                games.extend(league_games)
                leagues.append('wnba')

        # Collect NCAA Men's games if enabled
        if self.ncaam_enabled:
            league_games = []
            for mt in mode_types:
                manager = self._get_manager_for_league_mode('ncaam', mt)
                if manager:
                    ncaam_games = self._get_games_from_manager(manager, mt)
                    if ncaam_games:
                        # Add league info and ensure status field
                        for game in ncaam_games:
                            game['league'] = 'ncaam'
                            # Ensure game has status for type determination
                            if 'status' not in game:
                                game['status'] = {}
                            if 'state' not in game['status']:
                                state_map = {'live': 'in', 'recent': 'post', 'upcoming': 'pre'}
                                game['status']['state'] = state_map.get(mt, 'pre')
                        league_games.extend(ncaam_games)
                        self.logger.debug(f"Collected {len(ncaam_games)} NCAA Men's {mt} games for scroll")

            if league_games:
                games.extend(league_games)
                leagues.append('ncaam')

        # Collect NCAA Women's games if enabled
        if self.ncaaw_enabled:
            league_games = []
            for mt in mode_types:
                manager = self._get_manager_for_league_mode('ncaaw', mt)
                if manager:
                    ncaaw_games = self._get_games_from_manager(manager, mt)
                    if ncaaw_games:
                        # Add league info and ensure status field
                        for game in ncaaw_games:
                            game['league'] = 'ncaaw'
                            # Ensure game has status for type determination
                            if 'status' not in game:
                                game['status'] = {}
                            if 'state' not in game['status']:
                                state_map = {'live': 'in', 'recent': 'post', 'upcoming': 'pre'}
                                game['status']['state'] = state_map.get(mt, 'pre')
                        league_games.extend(ncaaw_games)
                        self.logger.debug(f"Collected {len(ncaaw_games)} NCAA Women's {mt} games for scroll")

            if league_games:
                games.extend(league_games)
                leagues.append('ncaaw')

        # If live priority is active, filter to only live games
        if live_priority_active:
            games = [g for g in games if g.get('is_live', False) and not g.get('is_final', False)]
            self.logger.debug(f"Live priority active: filtered to {len(games)} live games")

        return games, leagues

    # -------------------------------------------------------------------------
    # Vegas scroll mode support
    # -------------------------------------------------------------------------
    def get_vegas_content(self) -> Optional[Any]:
        """
        Get content for Vegas-style continuous scroll mode.

        Triggers scroll content generation if cache is empty, then returns
        the cached scroll image(s) for Vegas to compose into its scroll strip.

        Returns:
            List of PIL Images from scroll displays, or None if no content
        """
        if not hasattr(self, '_scroll_manager') or not self._scroll_manager:
            return None

        images = self._scroll_manager.get_all_vegas_content_items()

        if not images:
            self.logger.info("[Basketball Vegas] Triggering scroll content generation")
            self._ensure_scroll_content_for_vegas()
            images = self._scroll_manager.get_all_vegas_content_items()

        if images:
            total_width = sum(img.width for img in images)
            self.logger.info(
                "[Basketball Vegas] Returning %d image(s), %dpx total",
                len(images), total_width
            )
            return images

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
            self.logger.debug("[Basketball Vegas] No scroll manager available")
            return

        # Collect all games (live, recent, upcoming) organized by league
        games, leagues = self._collect_games_for_scroll(mode_type=None)

        if not games:
            self.logger.debug("[Basketball Vegas] No games available")
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
                f"[Basketball Vegas] Successfully generated scroll content: "
                f"{len(games)} games ({type_summary}) from {', '.join(leagues)}"
            )
        else:
            self.logger.warning("[Basketball Vegas] Failed to generate scroll content")

    def cleanup(self) -> None:
        """Clean up resources."""
        try:
            if hasattr(self, "background_service") and self.background_service:
                # Clean up background service if needed
                pass
            self.logger.info("Basketball scoreboard plugin cleanup completed")
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")
