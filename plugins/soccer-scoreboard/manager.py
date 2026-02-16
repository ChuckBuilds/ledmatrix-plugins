"""
Soccer Scoreboard Plugin for LEDMatrix

Displays live, recent, and upcoming soccer games across multiple leagues including
Premier League, La Liga, Bundesliga, Serie A, Ligue 1, MLS, Champions League, Europa League,
and user-defined custom leagues.

Display Modes:
- Switch Mode: Display one game at a time with timed transitions
- Scroll Mode: High-FPS horizontal scrolling of all games with league separators

Sequential Block Display Architecture:
This plugin implements a sequential block display approach where all games from
one league are shown before moving to the next league. This provides:

1. Predictable Display Order: Leagues shown in priority order (predefined first, then custom)
2. Accurate Dynamic Duration: Duration calculations include all leagues
3. Scalable Design: Easy to add more leagues via custom_leagues config
4. Granular Control: Support for enabling/disabling at league and mode levels

The sequential block flow:
- For a display mode (e.g., 'soccer_recent'), get enabled leagues in priority order
- Show all games from the first league until complete
- Then show all games from the next league until complete
- When all enabled leagues complete, the display mode cycle is complete
"""

import hashlib
import logging
import time
import threading
from typing import Dict, Any, Set, Optional, Tuple, List

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
from soccer_managers import (
    SoccerLiveManager,
    SoccerRecentManager,
    SoccerUpcomingManager,
    create_premier_league_managers,
    create_la_liga_managers,
    create_bundesliga_managers,
    create_serie_a_managers,
    create_ligue_1_managers,
    create_mls_managers,
    create_champions_league_managers,
    create_europa_league_managers,
    create_custom_league_managers,
)

logger = logging.getLogger(__name__)

# Predefined league keys and display names (priority 1-8)
# Custom leagues will be added dynamically with user-defined priorities
PREDEFINED_LEAGUE_KEYS = ['eng.1', 'esp.1', 'ger.1', 'ita.1', 'fra.1', 'usa.1', 'uefa.champions', 'uefa.europa']
PREDEFINED_LEAGUE_NAMES = {
    'eng.1': 'Premier League',
    'esp.1': 'La Liga',
    'ger.1': 'Bundesliga',
    'ita.1': 'Serie A',
    'fra.1': 'Ligue 1',
    'usa.1': 'MLS',
    'uefa.champions': 'Champions League',
    'uefa.europa': 'Europa League'
}

# Default priorities for predefined leagues (lower = higher priority, shows first)
PREDEFINED_LEAGUE_PRIORITIES = {
    'eng.1': 1,
    'esp.1': 2,
    'ger.1': 3,
    'ita.1': 4,
    'fra.1': 5,
    'usa.1': 6,
    'uefa.champions': 7,
    'uefa.europa': 8,
}

# League key -> (live_attr, recent_attr, upcoming_attr) for predefined leagues
PREDEFINED_LEAGUE_ATTR_MAP = {
    'eng.1': ('eng1_live', 'eng1_recent', 'eng1_upcoming'),
    'esp.1': ('esp1_live', 'esp1_recent', 'esp1_upcoming'),
    'ger.1': ('ger1_live', 'ger1_recent', 'ger1_upcoming'),
    'ita.1': ('ita1_live', 'ita1_recent', 'ita1_upcoming'),
    'fra.1': ('fra1_live', 'fra1_recent', 'fra1_upcoming'),
    'usa.1': ('usa1_live', 'usa1_recent', 'usa1_upcoming'),
    'uefa.champions': ('champions_live', 'champions_recent', 'champions_upcoming'),
    'uefa.europa': ('europa_live', 'europa_recent', 'europa_upcoming'),
}

# Legacy aliases for backwards compatibility. LEAGUE_NAMES is a mutable copy that
# includes predefined leagues and can be extended with custom leagues. PREDEFINED_LEAGUE_NAMES
# remains immutable for reference.
LEAGUE_KEYS = PREDEFINED_LEAGUE_KEYS
LEAGUE_NAMES = PREDEFINED_LEAGUE_NAMES.copy()


class SoccerScoreboardPlugin(BasePlugin if BasePlugin else object):
    """
    Soccer scoreboard plugin using manager classes.

    This plugin provides soccer scoreboard functionality across multiple leagues
    by delegating to proven manager classes.
    """

    def __init__(
        self,
        plugin_id: str,
        config: Dict[str, Any],
        display_manager,
        cache_manager,
        plugin_manager,
    ):
        """Initialize the soccer scoreboard plugin."""
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
        self.logger.debug(f"Soccer plugin received config keys: {list(config.keys())}")
        
        # Check which leagues are enabled
        leagues_config = config.get('leagues', {})
        self.league_enabled = {}
        for league_key in LEAGUE_KEYS:
            league_config = leagues_config.get(league_key, {})
            self.league_enabled[league_key] = league_config.get('enabled', False)
            self.logger.debug(f"{LEAGUE_NAMES[league_key]} config: {league_config}")

        enabled_leagues = [k for k, v in self.league_enabled.items() if v]
        self.logger.info(
            f"League enabled states: {', '.join([LEAGUE_NAMES[k] for k in enabled_leagues]) if enabled_leagues else 'None'}"
        )

        # Global settings
        self.display_duration = float(config.get("display_duration", 30))
        self.game_display_duration = float(config.get("game_display_duration", 15))

        # Live priority per league
        self.league_live_priority = {}
        for league_key in LEAGUE_KEYS:
            league_config = leagues_config.get(league_key, {})
            self.league_live_priority[league_key] = league_config.get("live_priority", False)

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

        # League registry: maps league IDs to their configuration and managers
        # This structure makes it easy to add more leagues (including custom leagues)
        # Format: {league_id: {'enabled': bool, 'priority': int, 'live_priority': bool, 'managers': {...}}}
        self._league_registry: Dict[str, Dict[str, Any]] = {}

        # Initialize managers for predefined leagues
        self._initialize_managers()

        # Load and initialize custom leagues from config
        self._load_custom_leagues()

        # Initialize league registry after managers are created
        # This centralizes league management and makes it easy to add more leagues
        self._initialize_league_registry()

        # Display mode settings per league and game type
        self._display_mode_settings = self._parse_display_mode_settings()
        
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
        self._scroll_active: Dict[str, bool] = {}  # {scroll_key: is_active}
        self._scroll_prepared: Dict[str, bool] = {}  # {scroll_key: is_prepared}

        # Track active update threads to prevent accumulation of stale threads
        self._active_update_threads: Dict[str, threading.Thread] = {}  # {name: thread}
        
        # Enable high-FPS mode for scroll display (allows 100+ FPS scrolling)
        # This signals to the display controller to use high-FPS loop (8ms = 125 FPS)
        self.enable_scrolling = self._scroll_manager is not None
        if self.enable_scrolling:
            self.logger.info("High-FPS scrolling enabled for soccer scoreboard")

        # Mode cycling
        self.current_mode_index = 0
        self.last_mode_switch = 0
        self.modes = self._get_available_modes()

        self.logger.info(
            f"Soccer scoreboard plugin initialized - {self.display_width}x{self.display_height}"
        )
        self.logger.info(
            f"Enabled leagues: {', '.join([LEAGUE_NAMES[k] for k in enabled_leagues]) if enabled_leagues else 'None'}"
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
        self._current_display_league: Optional[str] = None  # 'eng.1', 'esp.1', etc.
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
        # Format: {display_mode: start_time} (e.g., {'soccer_eng.1_recent': 1234567890.0})
        # Reset when mode changes or full cycle completes
        self._mode_start_time: Dict[str, float] = {}

    def _initialize_managers(self):
        """Initialize all manager instances."""
        try:
            # Initialize managers for each enabled league
            for league_key in LEAGUE_KEYS:
                if not self.league_enabled.get(league_key, False):
                    continue
                
                league_config = self._adapt_config_for_manager(league_key)
                
                # Create managers based on league
                if league_key == 'eng.1':
                    self.eng1_live, self.eng1_recent, self.eng1_upcoming = create_premier_league_managers(
                        league_config, self.display_manager, self.cache_manager
                    )
                elif league_key == 'esp.1':
                    self.esp1_live, self.esp1_recent, self.esp1_upcoming = create_la_liga_managers(
                        league_config, self.display_manager, self.cache_manager
                    )
                elif league_key == 'ger.1':
                    self.ger1_live, self.ger1_recent, self.ger1_upcoming = create_bundesliga_managers(
                        league_config, self.display_manager, self.cache_manager
                    )
                elif league_key == 'ita.1':
                    self.ita1_live, self.ita1_recent, self.ita1_upcoming = create_serie_a_managers(
                        league_config, self.display_manager, self.cache_manager
                    )
                elif league_key == 'fra.1':
                    self.fra1_live, self.fra1_recent, self.fra1_upcoming = create_ligue_1_managers(
                        league_config, self.display_manager, self.cache_manager
                    )
                elif league_key == 'usa.1':
                    self.usa1_live, self.usa1_recent, self.usa1_upcoming = create_mls_managers(
                        league_config, self.display_manager, self.cache_manager
                    )
                elif league_key == 'uefa.champions':
                    self.champions_live, self.champions_recent, self.champions_upcoming = create_champions_league_managers(
                        league_config, self.display_manager, self.cache_manager
                    )
                elif league_key == 'uefa.europa':
                    self.europa_live, self.europa_recent, self.europa_upcoming = create_europa_league_managers(
                        league_config, self.display_manager, self.cache_manager
                    )
                
                self.logger.info(f"{LEAGUE_NAMES[league_key]} managers initialized")

        except Exception as e:
            self.logger.error(f"Error initializing managers: {e}", exc_info=True)

    def _adapt_config_for_manager(self, league_key: str) -> Dict[str, Any]:
        """
        Adapt plugin config format to manager expected format.

        Plugin uses: leagues: {eng.1: {...}, esp.1: {...}, ...}
        Managers expect: soccer_eng.1_scoreboard: {...}, soccer_esp.1_scoreboard: {...}, ...
        """
        leagues_config = self.config.get('leagues', {})
        league_config = leagues_config.get(league_key, {})
        
        self.logger.debug(f"DEBUG: league_config for {league_key} = {league_config}")

        # Extract nested configurations
        display_modes_config = league_config.get("display_modes", {})
        
        manager_display_modes = {
            f"soccer_{league_key}_live": display_modes_config.get("live", True),
            f"soccer_{league_key}_recent": display_modes_config.get("recent", True),
            f"soccer_{league_key}_upcoming": display_modes_config.get("upcoming", True),
        }

        # Extract game limits from nested config if available
        game_limits = league_config.get("game_limits", {})
        filtering = league_config.get("filtering", {})

        # Create manager config with expected structure
        manager_config = {
            f"soccer_{league_key}_scoreboard": {
                "enabled": league_config.get("enabled", False),
                "favorite_teams": league_config.get("favorite_teams", []),
                "display_modes": manager_display_modes,
                "recent_games_to_show": game_limits.get("recent_games_to_show", league_config.get("recent_games_to_show", 5)),
                "upcoming_games_to_show": game_limits.get("upcoming_games_to_show", league_config.get("upcoming_games_to_show", 10)),
                "show_records": self.config.get("show_records", False),
                "show_ranking": self.config.get("show_ranking", False),
                "show_odds": self.config.get("show_odds", False),
                "update_interval_seconds": league_config.get(
                    "update_interval_seconds", 300
                ),
                "live_update_interval": league_config.get("live_update_interval", 30),
                "live_game_duration": league_config.get("live_game_duration", 20),
                "recent_game_duration": league_config.get("recent_game_duration", 15),
                "upcoming_game_duration": league_config.get("upcoming_game_duration", 15),
                "live_priority": league_config.get("live_priority", False),
                "show_favorite_teams_only": filtering.get("show_favorite_teams_only", league_config.get("show_favorite_teams_only", False)),
                "show_all_live": filtering.get("show_all_live", league_config.get("show_all_live", False)),
                "filtering": filtering if filtering else {
                    "show_favorite_teams_only": league_config.get("show_favorite_teams_only", False),
                    "show_all_live": league_config.get("show_all_live", False),
                },
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

        self.logger.debug(f"Using timezone: {timezone_str} for {league_key} managers")

        return manager_config

    def _load_custom_leagues(self) -> None:
        """
        Load and initialize custom leagues from config.

        Custom leagues are defined in config.custom_leagues as an array of objects.
        Each custom league has: name, league_code, priority, enabled, favorite_teams, etc.

        This method:
        1. Reads custom_leagues array from config
        2. Creates managers for each enabled custom league
        3. Updates league_enabled and league_live_priority dicts
        4. Updates LEAGUE_NAMES for display purposes
        """
        custom_leagues = self.config.get('custom_leagues', [])

        if not custom_leagues:
            self.logger.debug("No custom leagues configured")
            return

        self.logger.info(f"Loading {len(custom_leagues)} custom league(s)")

        # Track custom league keys for registry
        self._custom_league_keys: List[str] = []
        # Map league_code -> safe_key actually used (may differ if collision fallback applied)
        self._custom_league_safe_key: Dict[str, str] = {}

        for custom_league in custom_leagues:
            league_code = custom_league.get('league_code', '').strip()
            league_name = custom_league.get('name', '').strip()
            enabled = custom_league.get('enabled', True)
            priority = custom_league.get('priority', 50)

            if not league_code:
                self.logger.warning("Skipping custom league with empty league_code")
                continue

            # Validate against predefined leagues to prevent conflicts
            if league_code in PREDEFINED_LEAGUE_KEYS:
                self.logger.warning(
                    f"Skipping custom league with code '{league_code}' - conflicts with predefined league"
                )
                continue

            # Check for duplicate custom league codes
            if league_code in self._custom_league_keys:
                self.logger.warning(
                    f"Skipping duplicate custom league with code '{league_code}' - already registered"
                )
                continue
            
            # Also check _custom_league_priorities if it exists (may be initialized in previous iteration)
            if hasattr(self, '_custom_league_priorities') and league_code in self._custom_league_priorities:
                self.logger.warning(
                    f"Skipping duplicate custom league with code '{league_code}' - already registered"
                )
                continue

            if not league_name:
                league_name = f"Custom ({league_code})"

            self.logger.info(f"Initializing custom league: {league_name} ({league_code}) - priority {priority}")

            # Track this custom league
            self._custom_league_keys.append(league_code)

            # Update league enabled state
            self.league_enabled[league_code] = enabled

            # Update live priority
            self.league_live_priority[league_code] = custom_league.get('live_priority', False)

            # Add to LEAGUE_NAMES for display purposes
            # Note: This modifies the module-level dict, but it's intentional for consistency
            LEAGUE_NAMES[league_code] = league_name

            # Store priority for registry initialization
            if not hasattr(self, '_custom_league_priorities'):
                self._custom_league_priorities: Dict[str, int] = {}
            self._custom_league_priorities[league_code] = priority

            if not enabled:
                self.logger.debug(f"Custom league {league_name} is disabled, skipping manager initialization")
                continue

            # Create adapted config for this custom league
            custom_league_config = self._adapt_config_for_custom_league(custom_league)

            try:
                # Compute attribute names; guard against collisions (e.g. "foo.bar" vs "foo-bar"
                # both sanitize to "foo_bar") to avoid overwriting existing managers.
                safe_key = league_code.replace('.', '_').replace('-', '_')
                live_attr = f'custom_{safe_key}_live'
                recent_attr = f'custom_{safe_key}_recent'
                upcoming_attr = f'custom_{safe_key}_upcoming'
                if any(hasattr(self, a) for a in (live_attr, recent_attr, upcoming_attr)):
                    suffix = hashlib.sha256(league_code.encode()).hexdigest()[:8]
                    safe_key = f"{safe_key}_{suffix}"
                    live_attr = f'custom_{safe_key}_live'
                    recent_attr = f'custom_{safe_key}_recent'
                    upcoming_attr = f'custom_{safe_key}_upcoming'
                    self.logger.warning(
                        "Custom league_code '%s' collides with another (sanitized); using unique "
                        "suffix for attributes (custom_*_live/recent/upcoming) to avoid overwrite.",
                        league_code,
                    )
                self._custom_league_safe_key[league_code] = safe_key

                # Create managers for this custom league
                live_manager, recent_manager, upcoming_manager = create_custom_league_managers(
                    league_code=league_code,
                    league_name=league_name,
                    config=custom_league_config,
                    display_manager=self.display_manager,
                    cache_manager=self.cache_manager
                )

                setattr(self, live_attr, live_manager)
                setattr(self, recent_attr, recent_manager)
                setattr(self, upcoming_attr, upcoming_manager)

                self.logger.info(f"Custom league {league_name} managers initialized")

            except Exception as e:
                self.logger.error(f"Error initializing custom league {league_name}: {e}", exc_info=True)
                # Mark as not enabled if initialization failed
                self.league_enabled[league_code] = False

    def _adapt_config_for_custom_league(self, custom_league: Dict[str, Any]) -> Dict[str, Any]:
        """
        Adapt custom league config to manager expected format.

        Args:
            custom_league: Custom league configuration dict from config

        Returns:
            Manager config dict with expected structure
        """
        league_code = custom_league.get('league_code', '')
        league_name = custom_league.get('name', f"Custom ({league_code})")

        # Extract nested configurations
        display_modes_config = custom_league.get("display_modes", {})
        game_limits = custom_league.get("game_limits", {})
        filtering = custom_league.get("filtering", {})

        manager_display_modes = {
            f"soccer_{league_code}_live": display_modes_config.get("live", True),
            f"soccer_{league_code}_recent": display_modes_config.get("recent", True),
            f"soccer_{league_code}_upcoming": display_modes_config.get("upcoming", True),
        }

        # Create manager config with expected structure
        manager_config = {
            f"soccer_{league_code}_scoreboard": {
                "enabled": custom_league.get("enabled", True),
                "favorite_teams": custom_league.get("favorite_teams", []),
                "display_modes": manager_display_modes,
                "recent_games_to_show": game_limits.get("recent_games_to_show", 5),
                "upcoming_games_to_show": game_limits.get("upcoming_games_to_show", 10),
                "show_records": self.config.get("show_records", False),
                "show_ranking": self.config.get("show_ranking", False),
                "show_odds": self.config.get("show_odds", False),
                "update_interval_seconds": custom_league.get("update_interval_seconds", 300),
                "live_update_interval": custom_league.get("live_update_interval", 30),
                "live_game_duration": custom_league.get("live_game_duration", 20),
                "recent_game_duration": custom_league.get("recent_game_duration", 15),
                "upcoming_game_duration": custom_league.get("upcoming_game_duration", 15),
                "live_priority": custom_league.get("live_priority", False),
                "show_favorite_teams_only": filtering.get(
                    "show_favorite_teams_only",
                    custom_league.get("show_favorite_teams_only", False)
                ),
                "show_all_live": filtering.get(
                    "show_all_live",
                    custom_league.get("show_all_live", False)
                ),
                "filtering": filtering if filtering else {
                    "show_favorite_teams_only": custom_league.get("show_favorite_teams_only", False),
                    "show_all_live": custom_league.get("show_all_live", False),
                },
                "background_service": {
                    "request_timeout": 30,
                    "max_retries": 3,
                    "priority": 2,
                },
                # Custom league specific
                "league_code": league_code,
                "league_name": league_name,
            }
        }

        # Add global config
        timezone_str = self.config.get("timezone")
        if not timezone_str and hasattr(self.cache_manager, 'config_manager'):
            timezone_str = self.cache_manager.config_manager.get_timezone()
        if not timezone_str:
            timezone_str = "UTC"

        display_config = self.config.get("display", {})
        if not display_config and hasattr(self.cache_manager, 'config_manager'):
            display_config = self.cache_manager.config_manager.get_display_config()

        # Get customization config from main config (shared across all leagues)
        customization_config = self.config.get("customization", {})

        manager_config.update({
            "timezone": timezone_str,
            "display": display_config,
            "customization": customization_config,
        })

        return manager_config

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
                'is_custom': bool,         # Whether this is a custom league
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
        # Add predefined leagues to registry
        for league_key in PREDEFINED_LEAGUE_KEYS:
            attr_tuple = PREDEFINED_LEAGUE_ATTR_MAP.get(league_key)
            if not attr_tuple:
                continue
            live_attr, recent_attr, upcoming_attr = attr_tuple

            self._league_registry[league_key] = {
                'enabled': self.league_enabled.get(league_key, False),
                'priority': PREDEFINED_LEAGUE_PRIORITIES.get(league_key, 99),
                'live_priority': self.league_live_priority.get(league_key, False),
                'is_custom': False,
                'managers': {
                    'live': getattr(self, live_attr, None),
                    'recent': getattr(self, recent_attr, None),
                    'upcoming': getattr(self, upcoming_attr, None),
                }
            }

        # Add custom leagues to registry
        custom_league_keys = getattr(self, '_custom_league_keys', [])
        custom_priorities = getattr(self, '_custom_league_priorities', {})
        custom_safe_keys = getattr(self, '_custom_league_safe_key', {})

        for league_code in custom_league_keys:
            safe_key = custom_safe_keys.get(
                league_code,
                league_code.replace('.', '_').replace('-', '_'),
            )
            live_attr = f'custom_{safe_key}_live'
            recent_attr = f'custom_{safe_key}_recent'
            upcoming_attr = f'custom_{safe_key}_upcoming'

            self._league_registry[league_code] = {
                'enabled': self.league_enabled.get(league_code, False),
                'priority': custom_priorities.get(league_code, 50),
                'live_priority': self.league_live_priority.get(league_code, False),
                'is_custom': True,
                'managers': {
                    'live': getattr(self, live_attr, None),
                    'recent': getattr(self, recent_attr, None),
                    'upcoming': getattr(self, upcoming_attr, None),
                }
            }

        # Log registry state for debugging
        enabled_leagues = [lid for lid, data in self._league_registry.items() if data['enabled']]
        custom_count = len([lid for lid, data in self._league_registry.items() if data.get('is_custom', False)])
        self.logger.info(
            f"League registry initialized: {len(self._league_registry)} league(s) registered "
            f"({custom_count} custom), {len(enabled_leagues)} enabled: "
            f"{[LEAGUE_NAMES.get(lid, lid) for lid in enabled_leagues]}"
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
            Example: ['eng.1', 'esp.1'] means Premier League shows first, then La Liga

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
            if league_data.get('is_custom', False):
                # Custom league - check from custom_leagues config
                leagues_config = self.config.get('leagues', {})
                custom_leagues = leagues_config.get('custom_leagues', [])
                league_config = next(
                    (cl for cl in custom_leagues if cl.get('league_code') == league_id),
                    {}
                )
            else:
                # Predefined league
                leagues_config = self.config.get('leagues', {})
                league_config = leagues_config.get(league_id, {})

            display_modes_config = league_config.get("display_modes", {})

            # Check the appropriate flag based on mode type
            mode_enabled = True  # Default to enabled if not specified
            if mode_type == 'live':
                mode_enabled = display_modes_config.get("live", True)
            elif mode_type == 'recent':
                mode_enabled = display_modes_config.get("recent", True)
            elif mode_type == 'upcoming':
                mode_enabled = display_modes_config.get("upcoming", True)

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
            league_id: League identifier ('eng.1', 'esp.1', custom codes, etc.)
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
            return True

        # Build the manager key that matches what's used in progress tracking
        # Use "soccer_{league}_{mode}" to match _record_dynamic_progress (current_mode format)
        manager_key = self._build_manager_key(f"soccer_{league_id}_{mode_type}", manager)

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
            league_id: League identifier ('eng.1', 'esp.1', custom codes, etc.)
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

    def _set_display_context_from_manager(self, manager, mode_type: str) -> None:
        """Set the current display context based on which manager is being used."""
        # Try to determine league from manager class name or attributes
        manager_class = manager.__class__.__name__

        # Check for custom leagues first
        if hasattr(manager, 'league_code'):
            self._current_display_league = manager.league_code
        elif 'PremierLeague' in manager_class or 'Eng1' in manager_class:
            self._current_display_league = 'eng.1'
        elif 'LaLiga' in manager_class or 'Esp1' in manager_class:
            self._current_display_league = 'esp.1'
        elif 'Bundesliga' in manager_class or 'Ger1' in manager_class:
            self._current_display_league = 'ger.1'
        elif 'SerieA' in manager_class or 'Ita1' in manager_class:
            self._current_display_league = 'ita.1'
        elif 'Ligue1' in manager_class or 'Fra1' in manager_class:
            self._current_display_league = 'fra.1'
        elif 'MLS' in manager_class or 'Usa1' in manager_class:
            self._current_display_league = 'usa.1'
        elif 'ChampionsLeague' in manager_class:
            self._current_display_league = 'uefa.champions'
        elif 'EuropaLeague' in manager_class:
            self._current_display_league = 'uefa.europa'
        else:
            self._current_display_league = None

        self._current_display_mode_type = mode_type

    def _parse_display_mode_settings(self) -> Dict[str, Dict[str, str]]:
        """
        Parse display mode settings from config.

        Returns:
            Dict mapping league_key -> game_type -> display_mode ('switch' or 'scroll')
            e.g., {'eng.1': {'live': 'switch', 'recent': 'scroll', 'upcoming': 'scroll'}}
        """
        settings = {}

        leagues_config = self.config.get('leagues', {})

        # Parse predefined leagues
        for league_key in PREDEFINED_LEAGUE_KEYS:
            league_config = leagues_config.get(league_key, {})
            display_modes_config = league_config.get("display_modes", {})

            settings[league_key] = {
                'live': display_modes_config.get('live_display_mode', 'switch'),
                'recent': display_modes_config.get('recent_display_mode', 'switch'),
                'upcoming': display_modes_config.get('upcoming_display_mode', 'switch'),
            }

            self.logger.debug(f"Display mode settings for {LEAGUE_NAMES.get(league_key, league_key)}: {settings[league_key]}")

        # Parse custom leagues
        custom_leagues = leagues_config.get('custom_leagues', [])
        for custom_league in custom_leagues:
            league_code = custom_league.get('league_code', '')
            if not league_code:
                continue

            display_modes_config = custom_league.get("display_modes", {})

            settings[league_code] = {
                'live': display_modes_config.get('live_display_mode', 'switch'),
                'recent': display_modes_config.get('recent_display_mode', 'switch'),
                'upcoming': display_modes_config.get('upcoming_display_mode', 'switch'),
            }

            league_name = custom_league.get('name', league_code)
            self.logger.debug(f"Display mode settings for custom league {league_name}: {settings[league_code]}")

        return settings

    def _get_display_mode(self, league_key: str, game_type: str) -> str:
        """
        Get the display mode for a specific league and game type.

        Args:
            league_key: League key (e.g., 'eng.1', 'esp.1', or custom league code)
            game_type: 'live', 'recent', or 'upcoming'

        Returns:
            'switch' or 'scroll'
        """
        return self._display_mode_settings.get(league_key, {}).get(game_type, 'switch')

    def _should_use_scroll_mode(self, mode_type: str) -> bool:
        """
        Check if ANY enabled league should use scroll mode for this game type.

        This determines if we should collect games for scrolling or use switch mode.
        Uses the league registry to check all leagues (predefined and custom).

        Args:
            mode_type: 'live', 'recent', or 'upcoming'

        Returns:
            True if at least one enabled league uses scroll mode for this game type
        """
        # Reuse _get_enabled_leagues_for_mode to get leagues enabled for this mode
        # This avoids duplicating the per-mode enablement logic
        for league_key in self._get_enabled_leagues_for_mode(mode_type):
            if self._get_display_mode(league_key, mode_type) == 'scroll':
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

        # Build stable priority-sorted list of leagues across all mode types
        # Priority is determined by first mode_type that enables the league
        ordered_leagues = []
        for mt in mode_types:
            for league_key in self._get_enabled_leagues_for_mode(mt):
                if league_key not in ordered_leagues:
                    ordered_leagues.append(league_key)

        # Collect games by league, iterating leagues outer, mode_types inner
        # This ensures stable league ordering regardless of which mode has games
        games_by_league = {}

        for league_key in ordered_leagues:
            for mt in mode_types:
                if mode_type is not None and self._get_display_mode(league_key, mt) != 'scroll':
                    continue

                manager = self._get_league_manager_for_mode(league_key, mt)
                if manager:
                    league_games = self._get_games_from_manager(manager, mt)
                    if league_games:
                        # Add league info and ensure status field
                        for game in league_games:
                            if 'league' not in game:
                                game['league'] = league_key
                            # Normalize status to dict (handle None, non-dict, or missing)
                            if not isinstance(game.get('status'), dict):
                                game['status'] = {}
                            if 'state' not in game['status']:
                                # Infer state from mode_type
                                state_map = {'live': 'in', 'recent': 'post', 'upcoming': 'pre'}
                                game['status']['state'] = state_map.get(mt, 'pre')

                        # Group by league
                        if league_key not in games_by_league:
                            games_by_league[league_key] = []
                        games_by_league[league_key].extend(league_games)
                        self.logger.debug(f"Collected {len(league_games)} {LEAGUE_NAMES.get(league_key, league_key)} {mt} games for scroll")

        # Flatten games list in registry priority order (only leagues with games)
        # Lower priority number = higher priority, with league_key as tie-breaker
        leagues = sorted(
            [lk for lk in ordered_leagues if lk in games_by_league],
            key=lambda lk: (
                self._league_registry.get(lk, {}).get('priority', 999),
                lk  # Tie-breaker: alphabetical by league_key
            )
        )
        for league_key in leagues:
            games.extend(games_by_league[league_key])

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

        for league_data in self._league_registry.values():
            if not league_data.get('enabled', False):
                continue
            managers = league_data.get('managers', {})
            for mode_type in ('live', 'recent', 'upcoming'):
                manager = managers.get(mode_type)
                if manager:
                    manager_rankings = getattr(manager, '_team_rankings_cache', {})
                    if manager_rankings:
                        rankings.update(manager_rankings)

        return rankings
    
    def _ensure_manager_updated(self, manager) -> None:
        """Ensure a manager has been updated (call update if needed)."""
        if manager:
            try:
                manager.update()
            except Exception as e:
                self.logger.warning(f"Error updating manager: {e}")

    def _get_available_modes(self) -> list:
        """Get list of available display modes based on enabled leagues."""
        modes = []

        for league_key, league_data in self._league_registry.items():
            if not league_data.get('enabled', False):
                continue

            if league_data.get('is_custom', False):
                leagues_config = self.config.get('leagues', {})
                custom_leagues = leagues_config.get('custom_leagues', [])
                league_config = next(
                    (cl for cl in custom_leagues if cl.get('league_code') == league_key),
                    {}
                )
            else:
                leagues_config = self.config.get('leagues', {})
                league_config = leagues_config.get(league_key, {})

            display_modes = league_config.get("display_modes", {})

            prefix = f"soccer_{league_key}"
            if display_modes.get("live", True):
                modes.append(f"{prefix}_live")
            if display_modes.get("recent", True):
                modes.append(f"{prefix}_recent")
            if display_modes.get("upcoming", True):
                modes.append(f"{prefix}_upcoming")

        # Default to Premier League if no leagues enabled
        if not modes:
            modes = ["soccer_eng.1_live", "soccer_eng.1_recent", "soccer_eng.1_upcoming"]

        return modes

    def _get_current_manager(self):
        """Get the current manager based on the current mode."""
        if not self.modes:
            return None

        current_mode = self.modes[self.current_mode_index]

        # Parse mode: soccer_{league_key}_{mode_type}
        # Strip "soccer_" prefix and split from right to handle league codes with underscores
        if not current_mode.startswith('soccer_'):
            return None
        mode_without_prefix = current_mode[7:]  # len('soccer_') = 7
        parts = mode_without_prefix.rsplit('_', 1)
        if len(parts) < 2:
            return None

        league_key = parts[0]  # e.g., 'eng.1' or custom league code (may contain underscores)
        mode_type = parts[1]  # 'live', 'recent', 'upcoming'

        return self._get_league_manager_for_mode(league_key, mode_type)

    def update(self) -> None:
        """Update soccer game data using parallel manager updates."""
        if not self.is_enabled:
            return

        # Collect all manager update tasks
        update_tasks = []

        for league_key, league_data in self._league_registry.items():
            if not league_data.get('enabled', False):
                continue

            league_name = LEAGUE_NAMES.get(league_key, league_key)
            managers = league_data.get('managers', {})

            for mode_type in ('live', 'recent', 'upcoming'):
                manager = managers.get(mode_type)
                if manager:
                    update_tasks.append((f"{league_key}:{league_name} {mode_type.title()}", manager.update))
        
        if not update_tasks:
            return
        
        # Run updates in parallel with individual error handling
        def run_update_with_error_handling(name: str, update_func):
            """Run a single manager update with error handling."""
            try:
                update_func()
            except Exception as e:
                self.logger.error(f"Error updating {name} manager: {e}", exc_info=True)
        
        # Start all update threads, skipping managers with still-running threads
        threads = []
        started_threads = {}  # Track name -> thread for cleanup
        for name, update_func in update_tasks:
            # Check if a thread for this manager is still running
            existing_thread = self._active_update_threads.get(name)
            if existing_thread:
                if existing_thread.is_alive():
                    self.logger.debug(
                        f"Skipping update for {name} - previous thread still running"
                    )
                    continue
                else:
                    # Thread completed, remove stale entry
                    del self._active_update_threads[name]

            thread = threading.Thread(
                target=run_update_with_error_handling,
                args=(name, update_func),
                daemon=True,
                name=f"Update-{name}"
            )
            thread.start()
            threads.append(thread)
            self._active_update_threads[name] = thread
            started_threads[name] = thread

        # Wait for all threads to complete with a reasonable timeout
        for name, thread in started_threads.items():
            thread.join(timeout=25.0)
            if thread.is_alive():
                self.logger.warning(
                    f"Manager update thread {thread.name} did not complete within timeout"
                )
                # Keep entry in _active_update_threads so check at line 1145 prevents duplicate starts
                # The entry will be removed when the thread eventually completes
            else:
                # Thread completed successfully, remove from tracking
                if name in self._active_update_threads:
                    del self._active_update_threads[name]

    def _display_scroll_mode(self, display_mode: str, mode_type: str, force_clear: bool) -> bool:
        """Handle display for scroll mode.
        
        Args:
            display_mode: External mode name (e.g., 'soccer_live')
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
            # Use _get_enabled_leagues_for_mode to respect per-mode enablement
            enabled_league_keys = self._get_enabled_leagues_for_mode(mode_type)
            for league_key in enabled_league_keys:
                if self._get_display_mode(league_key, mode_type) != 'scroll':
                    continue
                manager = self._get_league_manager_for_mode(league_key, mode_type)
                if manager:
                    self._ensure_manager_updated(manager)

            # Check if live priority should filter to only live games
            live_priority_active = (
                mode_type == 'live'
                and any(
                    league_data.get('live_priority', False)
                    for _lk, league_data in self._league_registry.items()
                    if league_data.get('enabled', False)
                )
                and self.has_live_content()
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
                    f"[Soccer Scroll] Started scrolling {len(games)} {mode_type} games "
                    f"from {', '.join([LEAGUE_NAMES.get(l, l) for l in leagues])}"
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
                    self.logger.info(f"[Soccer Scroll] Cycle complete for {display_mode}")
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
        """Fallback to switch mode when scroll is not available."""
        managers_to_try = []

        # Use _get_enabled_leagues_for_mode to respect per-mode enablement
        enabled_league_keys = self._get_enabled_leagues_for_mode(mode_type)
        for league_key in enabled_league_keys:
            if self._get_display_mode(league_key, mode_type) != 'switch':
                continue

            manager = self._get_league_manager_for_mode(league_key, mode_type)
            if manager:
                managers_to_try.append((league_key, manager))
        
        # Try each manager until one returns True (has content)
        first_manager = True
        for league_key, current_manager in managers_to_try:
            if current_manager:
                # Track which league we're displaying for granular dynamic duration
                self._current_display_league = league_key
                self._current_display_mode_type = mode_type
                
                # Only pass force_clear to the first manager
                manager_force_clear = force_clear and first_manager
                first_manager = False
                
                result = current_manager.display(manager_force_clear)
                # If display returned True, we have content to show
                if result is True:
                    try:
                        self._record_dynamic_progress(current_manager)
                    except Exception as progress_err:
                        self.logger.debug(
                            "Dynamic progress tracking failed: %s", progress_err
                        )
                    self._evaluate_dynamic_cycle_completion()
                    return result
        
        return False

    def display(self, display_mode: str = None, force_clear: bool = False) -> bool:
        """Display soccer games with mode cycling."""
        if not self.is_enabled:
            return False

        try:
            # If display_mode is provided, use it to determine which manager to call
            if display_mode:
                self.logger.debug(f"Display called with mode: {display_mode}")
                
                # Handle registered plugin mode names (soccer_live, soccer_recent, soccer_upcoming)
                if display_mode in ["soccer_live", "soccer_recent", "soccer_upcoming"]:
                    mode_type = display_mode.replace("soccer_", "")
                    
                    # Check if any enabled league uses scroll mode for this type
                    if self._should_use_scroll_mode(mode_type):
                        return self._display_scroll_mode(display_mode, mode_type, force_clear)
                    
                    # Otherwise use switch mode
                    managers_to_try = []

                    # Use _get_enabled_leagues_for_mode to respect per-mode enablement
                    enabled_league_keys = self._get_enabled_leagues_for_mode(mode_type)
                    for league_key in enabled_league_keys:
                        league_data = self._league_registry.get(league_key, {})

                        if mode_type == 'live':
                            live_manager = self._get_league_manager_for_mode(league_key, 'live')
                            if live_manager:
                                live_games = getattr(live_manager, "live_games", [])
                                if live_games:
                                    # Include all enabled leagues with live content
                                    # Use live_priority as sort key (True first, then False)
                                    live_priority = league_data.get('live_priority', False)
                                    managers_to_try.append((live_priority, league_key, live_manager))
                        else:
                            manager = self._get_league_manager_for_mode(league_key, mode_type)
                            if manager:
                                managers_to_try.append((False, league_key, manager))

                    # Sort by live_priority (True first) for live mode, then try each manager
                    if mode_type == 'live':
                        managers_to_try.sort(key=lambda x: (not x[0], x[1]))  # True before False, then by league_key
                        managers_to_try = [(league_key, manager) for _, league_key, manager in managers_to_try]
                    else:
                        managers_to_try = [(league_key, manager) for _, league_key, manager in managers_to_try]

                    # Try each manager until one returns True (has content)
                    first_manager = True
                    for league_key, current_manager in managers_to_try:
                        if current_manager:
                            # Track which league we're displaying for granular dynamic duration
                            self._current_display_league = league_key
                            self._current_display_mode_type = mode_type
                            
                            # Only pass force_clear to the first manager
                            manager_force_clear = force_clear and first_manager
                            first_manager = False
                            
                            result = current_manager.display(manager_force_clear)
                            # If display returned True, we have content to show
                            if result is True:
                                try:
                                    self._record_dynamic_progress(current_manager)
                                except Exception as progress_err:
                                    self.logger.debug(
                                        "Dynamic progress tracking failed: %s", progress_err
                                    )
                                self._evaluate_dynamic_cycle_completion()
                                return result
                            # If result is False, try next manager
                            elif result is False:
                                continue
                            # If result is None or other, assume success
                            else:
                                return True
                    
                    # No manager returned True, return False
                    return False
                
                # Extract the mode type (live, recent, upcoming)
                mode_type = None
                if display_mode.endswith('_live'):
                    mode_type = 'live'
                elif display_mode.endswith('_recent'):
                    mode_type = 'recent'
                elif display_mode.endswith('_upcoming'):
                    mode_type = 'upcoming'
                
                if not mode_type:
                    self.logger.warning(f"Unknown display_mode: {display_mode}")
                    return False
                
                # Check if any enabled league uses scroll mode for this type
                if self._should_use_scroll_mode(mode_type):
                    return self._display_scroll_mode(display_mode, mode_type, force_clear)
                
                # Extract league from mode: soccer_{league_key}_{mode_type}
                # Use rsplit to handle custom league codes with underscores
                if not display_mode.startswith('soccer_'):
                    self.logger.warning(f"Invalid display_mode format (missing 'soccer_' prefix): {display_mode}")
                    return False
                
                mode_without_prefix = display_mode[7:]  # Remove "soccer_" prefix
                parts = mode_without_prefix.rsplit('_', 1)
                if len(parts) != 2:
                    self.logger.warning(f"Invalid display_mode format: {display_mode}")
                    return False
                
                league_key = parts[0]  # e.g., 'eng.1' or 'my_league'
                parsed_mode_type = parts[1]  # 'live', 'recent', or 'upcoming'
                
                # Validate that parsed mode_type matches the expected mode_type
                if parsed_mode_type != mode_type:
                    self.logger.warning(
                        f"Mode type mismatch: display_mode suggests '{parsed_mode_type}' "
                        f"but mode_type is '{mode_type}'"
                    )
                    return False
                
                # Get managers for this mode type across all enabled leagues (switch mode)
                # Use _get_enabled_leagues_for_mode to respect per-mode enablement
                managers_to_try = []
                enabled_league_keys = self._get_enabled_leagues_for_mode(mode_type)
                for key in enabled_league_keys:
                    manager = self._get_league_manager_for_mode(key, mode_type)
                    if manager:
                        managers_to_try.append((key, manager))
                
                # Try each manager until one returns True (has content)
                first_manager = True
                for league_key, current_manager in managers_to_try:
                    if current_manager:
                        # Track which league we're displaying for granular dynamic duration
                        self._current_display_league = league_key
                        self._current_display_mode_type = mode_type
                        
                        # Only pass force_clear to the first manager
                        manager_force_clear = force_clear and first_manager
                        first_manager = False
                        
                        result = current_manager.display(manager_force_clear)
                        # If display returned True, we have content to show
                        if result is True:
                            try:
                                self._record_dynamic_progress(current_manager)
                            except Exception as progress_err:
                                self.logger.debug(
                                    "Dynamic progress tracking failed: %s", progress_err
                                )
                            self._evaluate_dynamic_cycle_completion()
                            return result
                        # If result is False, try next manager
                        elif result is False:
                            continue
                        # If result is None or other, assume success
                        else:
                            try:
                                self._record_dynamic_progress(current_manager)
                            except Exception as progress_err:
                                self.logger.debug(
                                    "Dynamic progress tracking failed: %s", progress_err
                                )
                            self._evaluate_dynamic_cycle_completion()
                            return True
                
                # No manager had content
                if not managers_to_try:
                    self.logger.warning(
                        f"No managers available for mode: {display_mode}"
                    )
                else:
                    self.logger.info(
                        f"No content available for mode: {display_mode} after trying {len(managers_to_try)} manager(s) - returning False"
                    )
                
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

            # Get current mode and check if it uses scroll mode
            current_mode = self.modes[self.current_mode_index] if self.modes else None
            if current_mode:
                # Extract mode type from current_mode (e.g., "soccer_eng.1_live" -> "live")
                # Use rsplit to handle custom league codes with underscores
                if current_mode.startswith('soccer_'):
                    mode_without_prefix = current_mode[7:]  # Remove "soccer_" prefix
                    parts = mode_without_prefix.rsplit('_', 1)
                    if len(parts) == 2:
                        mode_type = parts[1]  # 'live', 'recent', or 'upcoming'
                        
                        # Check if scroll mode should be used
                        if self._should_use_scroll_mode(mode_type):
                            return self._display_scroll_mode(current_mode, mode_type, force_clear)
            
            # Use switch mode
            current_manager = self._get_current_manager()
            if current_manager:
                # Track which league/mode we're displaying for granular dynamic duration
                if current_mode and current_mode.startswith('soccer_'):
                    mode_without_prefix = current_mode[7:]  # Remove "soccer_" prefix
                    parts = mode_without_prefix.rsplit('_', 1)
                    if len(parts) == 2:
                        self._current_display_league = parts[0]  # league_key (handles underscores)
                        self._current_display_mode_type = parts[1]  # mode_type
                
                result = current_manager.display(force_clear)
                if result is not False:
                    try:
                        self._record_dynamic_progress(current_manager)
                    except Exception as progress_err:
                        self.logger.debug(
                            "Dynamic progress tracking failed: %s", progress_err
                        )
                self._evaluate_dynamic_cycle_completion()
                return result
            else:
                self.logger.warning("No manager available for current mode")
                return False

        except Exception as e:
            self.logger.error(f"Error in display method: {e}", exc_info=True)
            return False

    def has_live_priority(self) -> bool:
        """Check if any league has live priority enabled."""
        if not self.is_enabled:
            return False
        return any(
            league_data.get('enabled', False) and league_data.get('live_priority', False)
            for _lk, league_data in self._league_registry.items()
        )

    def has_live_content(self) -> bool:
        """Check if any league has live content."""
        if not self.is_enabled:
            return False

        for league_key, league_data in self._league_registry.items():
            if not league_data.get('enabled', False):
                continue

            live_manager = self._get_league_manager_for_mode(league_key, 'live')
            if not live_manager:
                continue
            live_games = getattr(live_manager, "live_games", [])
            if not live_games:
                continue

            # Check show_all_live first - if True, any live game counts
            show_all_live = league_data.get('show_all_live', False) or getattr(live_manager, 'show_all_live', False)
            if show_all_live:
                return True

            # Otherwise, check favorite_teams
            favorite_teams = getattr(live_manager, "favorite_teams", [])
            if favorite_teams:
                has_favorite_live = any(
                    game.get("home_abbr") in favorite_teams
                    or game.get("away_abbr") in favorite_teams
                    for game in live_games
                )
                if has_favorite_live:
                    return True

        return False

    def get_live_modes(self) -> list:
        """
        Return the registered plugin mode name(s) that have live content.
        
        This should return the mode names as registered in manifest.json, not internal
        mode names. The plugin is registered with "soccer_live", "soccer_recent", "soccer_upcoming".
        """
        if not self.is_enabled:
            return []

        # Check if any league has live content
        has_any_live = self.has_live_content()
        
        if has_any_live:
            # Return the registered plugin mode name, not internal mode names
            # The plugin is registered with "soccer_live" in manifest.json
            return ["soccer_live"]
        
        return []

    def get_info(self) -> Dict[str, Any]:
        """Get plugin information."""
        try:
            current_manager = self._get_current_manager()
            current_mode = self.modes[self.current_mode_index] if self.modes else "none"

            # Build league info from registry (includes custom leagues)
            league_info = {}
            for league_key, league_data in self._league_registry.items():
                league_info[league_key] = {
                    "enabled": league_data.get("enabled", False),
                    "live_priority": league_data.get("live_priority", False),
                }

            info = {
                "plugin_id": self.plugin_id,
                "name": "Soccer Scoreboard",
                "version": "1.3.1",
                "enabled": self.is_enabled,
                "display_size": f"{self.display_width}x{self.display_height}",
                "leagues": league_info,
                "current_mode": current_mode,
                "available_modes": self.modes,
                "display_duration": self.display_duration,
                "game_display_duration": self.game_display_duration,
                "show_records": self.config.get("show_records", False),
                "show_ranking": self.config.get("show_ranking", False),
                "show_odds": self.config.get("show_odds", False),
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
                "name": "Soccer Scoreboard",
                "error": str(e),
            }

    # ------------------------------------------------------------------
    # Dynamic duration hooks
    # ------------------------------------------------------------------
    def reset_cycle_state(self) -> None:
        """Reset dynamic cycle tracking."""
        if BasePlugin:
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
        self._evaluate_dynamic_cycle_completion()
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
        
        league_key = self._current_display_league
        mode_type = self._current_display_mode_type
        
        # Check per-league/per-mode setting first (most specific)
        leagues_config = self.config.get('leagues', {})
        league_config = leagues_config.get(league_key, {})
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
            if BasePlugin:
                return super().get_dynamic_duration_cap()
            return None
        
        league_key = self._current_display_league
        mode_type = self._current_display_mode_type
        
        # Check per-league/per-mode setting first (most specific)
        leagues_config = self.config.get('leagues', {})
        league_config = leagues_config.get(league_key, {})
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

    def _extract_mode_type(self, display_mode: str) -> Optional[str]:
        """Extract mode type (live, recent, upcoming) from display mode string.

        Args:
            display_mode: Display mode string (e.g., 'soccer_live', 'soccer_recent')

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
        2. League-specific mode duration from display_durations
        3. Default (15 seconds)

        Args:
            league: League key (e.g., 'eng.1', 'esp.1')
            mode_type: Mode type ('live', 'recent', or 'upcoming')
            manager: Optional manager instance

        Returns:
            Game duration in seconds (float)
        """
        if manager:
            manager_duration = getattr(manager, 'game_display_duration', None)
            if manager_duration is not None:
                return float(manager_duration)

        leagues_config = self.config.get('leagues', {})
        league_config = leagues_config.get(league, {})
        display_durations = league_config.get("display_durations", {})
        mode_duration = display_durations.get(mode_type)
        if mode_duration is not None:
            return float(mode_duration)

        return 15.0

    def _get_mode_duration(self, league: str, mode_type: str) -> Optional[float]:
        """Get mode duration from config for a league/mode combination.

        Checks per-league/per-mode settings first, then falls back to None.
        Returns None if not configured (uses dynamic calculation).

        Args:
            league: League key (e.g., 'eng.1', 'esp.1')
            mode_type: Mode type ('live', 'recent', or 'upcoming')

        Returns:
            Mode duration in seconds (float) or None if not configured
        """
        leagues_config = self.config.get('leagues', {})
        league_config = leagues_config.get(league, {})
        mode_durations = league_config.get("mode_durations", {})

        mode_duration_key = f"{mode_type}_mode_duration"
        if mode_duration_key in mode_durations:
            value = mode_durations[mode_duration_key]
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    pass

        return None

    def _get_effective_mode_duration(self, display_mode: str, mode_type: str) -> Optional[float]:
        """Get effective mode duration for a display mode.

        Checks per-mode duration settings first, then falls back to dynamic calculation.

        Args:
            display_mode: Display mode name (e.g., 'soccer_recent')
            mode_type: Mode type ('live', 'recent', or 'upcoming')

        Returns:
            Mode duration in seconds (float) or None to use dynamic calculation
        """
        if not self._current_display_league:
            return None

        mode_duration = self._get_mode_duration(self._current_display_league, mode_type)
        if mode_duration is not None:
            return mode_duration

        return None

    def get_cycle_duration(self, display_mode: str = None) -> Optional[float]:
        """Calculate the expected cycle duration for a display mode.

        Supports mode-level durations and dynamic calculation:
        - Mode-level duration: Fixed total time for mode (e.g., recent_mode_duration)
        - Dynamic calculation: Total duration = num_games x per_game_duration
        - Dynamic duration cap applies to both if enabled

        Args:
            display_mode: The display mode (e.g., 'soccer_live', 'soccer_recent')

        Returns:
            Total expected duration in seconds, or None if not applicable
        """
        if not self.is_enabled or not display_mode:
            return None

        mode_type = self._extract_mode_type(display_mode)
        if not mode_type:
            return None

        # Check for per-mode duration first (fixed total time for mode)
        effective_duration = self._get_effective_mode_duration(display_mode, mode_type)
        if effective_duration is not None:
            # Apply dynamic cap if configured
            if self._dynamic_feature_enabled():
                cap = self.get_dynamic_duration_cap()
                if cap is not None:
                    effective_duration = min(effective_duration, cap)
            return effective_duration

        # No mode-level duration - use dynamic calculation
        # Accumulate per-league (games * duration) to handle different durations per league
        total_duration = 0.0

        for league_key, league_data in self._league_registry.items():
            if not league_data.get('enabled', False):
                continue
            manager = league_data.get('managers', {}).get(mode_type)
            if manager:
                games = getattr(manager, 'games', [])
                if games:
                    game_duration = self._get_game_duration(league_key, mode_type, manager)
                    total_duration += len(games) * game_duration

        if total_duration == 0.0:
            return None

        # Apply dynamic cap if configured
        if self._dynamic_feature_enabled():
            cap = self.get_dynamic_duration_cap()
            if cap is not None:
                total_duration = min(total_duration, cap)

        return total_duration

    def _get_manager_for_mode(self, mode_name: str):
        """Resolve manager instance for a given display mode."""
        # Strip "soccer_" prefix and split from right to handle league codes with underscores
        if not mode_name.startswith('soccer_'):
            return None
        mode_without_prefix = mode_name[7:]  # len('soccer_') = 7
        parts = mode_without_prefix.rsplit('_', 1)
        if len(parts) < 2:
            return None

        league_key = parts[0]  # May contain underscores for custom leagues
        mode_type = parts[1]

        return self._get_league_manager_for_mode(league_key, mode_type)

    def _record_dynamic_progress(self, current_manager) -> None:
        """Track progress through managers/games for dynamic duration."""
        if not self._dynamic_feature_enabled() or not self.modes:
            self._dynamic_cycle_complete = True
            return

        current_mode = self.modes[self.current_mode_index]
        self._dynamic_cycle_seen_modes.add(current_mode)

        manager_key = self._build_manager_key(current_mode, current_manager)
        self._dynamic_mode_to_manager_key[current_mode] = manager_key

        total_games = self._get_total_games_for_manager(current_manager)
        if total_games <= 1:
            # Single (or no) game - treat as complete once visited
            self._dynamic_managers_completed.add(manager_key)
            return

        current_index = getattr(current_manager, "current_game_index", None)
        if current_index is None:
            # Fall back to zero if the manager does not expose an index
            current_index = 0
        identifier = f"index-{current_index}"

        progress_set = self._dynamic_manager_progress.setdefault(manager_key, set())
        progress_set.add(identifier)

        # Drop identifiers that no longer exist if game list shrinks
        valid_identifiers = {f"index-{idx}" for idx in range(total_games)}
        progress_set.intersection_update(valid_identifiers)

        if len(progress_set) >= total_games:
            self._dynamic_managers_completed.add(manager_key)

    def _evaluate_dynamic_cycle_completion(self) -> None:
        """Determine whether all enabled modes have completed their cycles."""
        if not self._dynamic_feature_enabled():
            self._dynamic_cycle_complete = True
            return

        if not self.modes:
            self._dynamic_cycle_complete = True
            return

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
                    self._dynamic_managers_completed.add(manager_key)
                else:
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
            self.logger.info("[Soccer Vegas] Triggering scroll content generation")
            self._ensure_scroll_content_for_vegas()
            images = self._scroll_manager.get_all_vegas_content_items()

        if images:
            total_width = sum(img.width for img in images)
            self.logger.info(
                "[Soccer Vegas] Returning %d image(s), %dpx total",
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
            self.logger.debug("[Soccer Vegas] No scroll manager available")
            return

        # Collect all games (live, recent, upcoming) organized by league
        games, leagues = self._collect_games_for_scroll(mode_type=None)

        if not games:
            self.logger.debug("[Soccer Vegas] No games available")
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
                f"[Soccer Vegas] Successfully generated scroll content: "
                f"{len(games)} games ({type_summary}) from {', '.join(leagues)}"
            )
        else:
            self.logger.warning("[Soccer Vegas] Failed to generate scroll content")

    def cleanup(self) -> None:
        """Clean up resources."""
        try:
            if hasattr(self, "background_service") and self.background_service:
                # Clean up background service if needed
                pass
            if hasattr(self, "_scroll_manager") and self._scroll_manager:
                # Clean up scroll manager if it has cleanup method
                if hasattr(self._scroll_manager, "cleanup"):
                    self._scroll_manager.cleanup()
                self._scroll_manager = None
            self.logger.info("Soccer scoreboard plugin cleanup completed")
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")
