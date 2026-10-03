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
except ImportError:
    BasePlugin = None
    VegasDisplayMode = None
    get_background_service = None

# Import scroll display components
try:
    from scroll_display import ScrollDisplayManager
    SCROLL_AVAILABLE = True
except ImportError:
    ScrollDisplayManager = None
    SCROLL_AVAILABLE = False

# Import the manager classes
from soccer_managers import (
    create_premier_league_managers,
    create_la_liga_managers,
    create_bundesliga_managers,
    create_serie_a_managers,
    create_ligue_1_managers,
    create_mls_managers,
    create_champions_league_managers,
    create_europa_league_managers,
    create_liga_portugal_managers,
    create_world_cup_managers,
    create_custom_league_managers,
)

from soccer_timezone import resolve_timezone_name
from src.common.favorite_team_check import FavoriteTeamCheck
from src.common.sports_plugin_host import SportsPluginHostMixin
from src.common.sports_live_scroll import SportsLiveScrollMixin

# Live Vegas cards (LEDMatrix 3.8.0). Guarded: the manifest floor is advisory,
# and without the module the ticker simply keeps using get_vegas_content().
try:
    from src.common import sports_vegas
except ImportError:
    sports_vegas = None


_ROOT_CONFIG_KEYS = (
    "schedule_lookback_days",
    "schedule_lookahead_days",
    "no_data_interval_seconds",
    "live_idle_max_interval_seconds",
    # The matchup separator and the date/time formats, read by the full-screen
    # scorebug in sports.py as well as by the scroll and Vegas card renderer.
    # The scroll path gets the whole plugin config and so never needed this;
    # the per-league managers are handed a rebuilt dict, so without naming it
    # here the setting reaches the ticker and never the scoreboard.
    "scroll_card",
)

#: Scroll display key Vegas renders its combined live/recent/upcoming slate
#: into, kept apart from the standalone modes' own displays.
_VEGAS_SCROLL_KEY = 'mixed'


logger = logging.getLogger(__name__)

# Predefined league keys and display names (priority 1-8)
# Custom leagues will be added dynamically with user-defined priorities
PREDEFINED_LEAGUE_KEYS = ['eng.1', 'esp.1', 'ger.1', 'ita.1', 'fra.1', 'usa.1', 'por.1', 'uefa.champions', 'uefa.europa', 'fifa.world']
PREDEFINED_LEAGUE_NAMES = {
    'eng.1': 'Premier League',
    'esp.1': 'La Liga',
    'ger.1': 'Bundesliga',
    'ita.1': 'Serie A',
    'fra.1': 'Ligue 1',
    'usa.1': 'MLS',
    'por.1': 'Liga Portugal',
    'uefa.champions': 'Champions League',
    'uefa.europa': 'Europa League',
    'fifa.world': 'FIFA World Cup',
}

# Default priorities for predefined leagues (lower = higher priority, shows first)
PREDEFINED_LEAGUE_PRIORITIES = {
    'eng.1': 1,
    'esp.1': 2,
    'ger.1': 3,
    'ita.1': 4,
    'fra.1': 5,
    'usa.1': 6,
    'por.1': 7,
    'uefa.champions': 8,
    'uefa.europa': 9,
    'fifa.world': 10,
}

# League key -> (live_attr, recent_attr, upcoming_attr) for predefined leagues
PREDEFINED_LEAGUE_ATTR_MAP = {
    'eng.1': ('eng1_live', 'eng1_recent', 'eng1_upcoming'),
    'esp.1': ('esp1_live', 'esp1_recent', 'esp1_upcoming'),
    'ger.1': ('ger1_live', 'ger1_recent', 'ger1_upcoming'),
    'ita.1': ('ita1_live', 'ita1_recent', 'ita1_upcoming'),
    'fra.1': ('fra1_live', 'fra1_recent', 'fra1_upcoming'),
    'usa.1': ('usa1_live', 'usa1_recent', 'usa1_upcoming'),
    'por.1': ('por1_live', 'por1_recent', 'por1_upcoming'),
    'uefa.champions': ('champions_live', 'champions_recent', 'champions_upcoming'),
    'uefa.europa': ('europa_live', 'europa_recent', 'europa_upcoming'),
    'fifa.world': ('world_cup_live', 'world_cup_recent', 'world_cup_upcoming'),
}

# Legacy aliases for backwards compatibility. LEAGUE_NAMES is a mutable copy that
# includes predefined leagues and can be extended with custom leagues. PREDEFINED_LEAGUE_NAMES
# remains immutable for reference.
LEAGUE_KEYS = PREDEFINED_LEAGUE_KEYS
LEAGUE_NAMES = PREDEFINED_LEAGUE_NAMES.copy()

_MISSING = object()

#: Keys config_schema.json declares in every predefined league block AND at the
#: plugin root, as (league-block default, root default). They mirror the
#: schema; test_root_settings_precedence.py fails if the two drift apart.
_ROOT_DUPLICATE_DEFAULTS = {
    "show_records": (False, False),
    "show_ranking": (False, False),
    "show_odds": (True, True),
    "live_game_duration": (20, 30),
    "update_interval_seconds": (3600, 3600),
    "live_update_interval": (30, 30),
    "stale_game_timeout": (300, 300),
    "recent_update_interval": (3600, 3600),
    "upcoming_update_interval": (3600, 3600),
    "recent_games_to_show": (1, 1),
    "upcoming_games_to_show": (1, 1),
    "show_favorite_teams_only": (True, True),
    "other_upcoming_games_to_show": (1, 1),
    "other_recent_games_to_show": (1, 1),
    "other_rotation_interval_seconds": (1800, 1800),
    "favorite_rotation_boost": (1, 1),
    "other_games_min_quality": ("ranked", "ranked"),
    "other_games_divisions": (["fbs"], ["fbs"]),
}


def _league_or_root(block: Dict[str, Any], root: Dict[str, Any], key: str,
                    fallback: Any) -> Any:
    """Resolve a league setting the schema also offers at the plugin root.

    Both copies render in the web UI and the UI saves schema defaults into
    both, so a value equal to its default says nothing about what the user
    chose. The root copies used to be read only as a fallback the saved league
    value always beat (show_records/show_ranking/show_odds), or not at all (the
    rest), so changing one did nothing. Precedence, the same rule afl- and
    nrl-scoreboard use for their display_options duplicates: a league value
    changed from its default, then a root value changed from its default,
    then the league value, then ``fallback`` when the league block lacks the
    key. Comparing each copy with its OWN default matters for
    live_game_duration, whose root default (30) is not the league's (20): a
    root still at 30 must not override every league.
    """
    league_default, root_default = _ROOT_DUPLICATE_DEFAULTS[key]
    value = block.get(key, _MISSING)
    if value is not _MISSING and value != league_default:
        return value
    root_value = root.get(key, _MISSING)
    if root_value is not _MISSING and root_value != root_default:
        return root_value
    return fallback if value is _MISSING else value


def _background_settings(config: Dict[str, Any]) -> Dict[str, Any]:
    """Timeout, retries and priority for the managers' background fetches,
    from the root ``background_service`` block (schema defaults if absent)."""
    bg = config.get("background_service") or {}
    return {
        "request_timeout": bg.get("request_timeout", 30),
        "max_retries": bg.get("max_retries", 3),
        "priority": bg.get("priority", 2),
    }


class SoccerScoreboardPlugin(SportsPluginHostMixin, SportsLiveScrollMixin,
                             BasePlugin if BasePlugin else object):
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
                # background_service.max_workers is a real setting; it used to
                # be pinned at 1 here, so raising it in the web UI did nothing.
                # The service is a process-wide singleton, so the first plugin
                # to construct it decides for everyone -- which is why the
                # schema default stays at 1 rather than the factory's 3.
                self.background_service = get_background_service(
                    self.cache_manager,
                    max_workers=int(
                        (self.config.get("background_service") or {}).get("max_workers", 1)
                    ),
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
        self._build_custom_league_map()

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
                    self.logger,
                    global_config=getattr(self, 'global_config', {}) or {}
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
        # What each live strip was built from, and when, so a score change
        # rebuilds it mid-cycle instead of at the end of one.
        self._live_scroll_fingerprints = {}
        self._live_scroll_rebuilt_at = {}
        # Seconds the last strip render took, per mode; feeds the duty-cycle cap.
        self._live_scroll_rebuild_cost = {}

        # Track active update threads to prevent accumulation of stale threads
        self._active_update_threads: Dict[str, threading.Thread] = {}  # {name: thread}

        # Lock to protect shared mutable state during config reload
        self._config_lock = threading.Lock()
        
        # Enable high-FPS mode only when at least one enabled league actually
        # uses scroll display mode.  The display controller reads this flag to
        # decide between 125 FPS (scroll) and normal FPS (switch).  Setting it
        # unconditionally caused switch-mode to run at 125 FPS, re-rendering
        # full scorebug images every 8ms and producing visible flashing.
        self.enable_scrolling = self._has_any_scroll_mode()
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
        """Initialize all manager instances.

        Each league is built in its own try. One try around the whole loop
        meant a single league failing -- a bad hand-edited value raising inside
        its config translation, say -- silently skipped every league after it
        in LEAGUE_KEYS. A failed league's three attributes are set to None,
        which the registry and the update/display paths already treat as "no
        manager" (ported from hockey-scoreboard).
        """
        # Looked up at call time, so the module-level factories stay the
        # single source (and remain patchable).
        factories = {
            'eng.1': create_premier_league_managers,
            'esp.1': create_la_liga_managers,
            'ger.1': create_bundesliga_managers,
            'ita.1': create_serie_a_managers,
            'fra.1': create_ligue_1_managers,
            'usa.1': create_mls_managers,
            'por.1': create_liga_portugal_managers,
            'uefa.champions': create_champions_league_managers,
            'uefa.europa': create_europa_league_managers,
            'fifa.world': create_world_cup_managers,
        }
        for league_key in LEAGUE_KEYS:
            factory = factories.get(league_key)
            attrs = PREDEFINED_LEAGUE_ATTR_MAP.get(league_key)
            if factory is None or attrs is None:
                continue
            if not self.league_enabled.get(league_key, False):
                # Drop any managers a previous build left behind. on_config_change
                # rebuilds through here, and a league disabled at runtime kept
                # its old managers: turning off the last league fell back to the
                # default soccer_eng.1_* modes, which found the stale EPL managers
                # in the registry and kept drawing them until a restart.
                for attr in attrs:
                    setattr(self, attr, None)
                continue
            try:
                league_config = self._adapt_config_for_manager(league_key)
                live, recent, upcoming = factory(
                    league_config, self.display_manager, self.cache_manager
                )
                for attr, manager in zip(attrs, (live, recent, upcoming)):
                    setattr(self, attr, manager)
                self.logger.info(f"{LEAGUE_NAMES[league_key]} managers initialized")
            except Exception as e:
                self.logger.error(
                    f"Failed to initialize {LEAGUE_NAMES.get(league_key, league_key)} "
                    f"managers: {e}",
                    exc_info=True,
                )
                for attr in attrs:
                    setattr(self, attr, None)

    def _adapt_config_for_manager(self, league_key: str) -> Dict[str, Any]:
        """
        Adapt plugin config format to manager expected format.

        Plugin uses: leagues: {eng.1: {...}, esp.1: {...}, ...}
        Managers expect: soccer_eng.1_scoreboard: {...}, soccer_esp.1_scoreboard: {...}, ...
        """
        leagues_config = self.config.get('leagues', {})
        league_config = leagues_config.get(league_key, {})
        
        self.logger.debug(f"league_config for {league_key} = {league_config}")

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
        # Every league block declares display_options, and until now nothing
        # read it: all thirty settings rendered in the web UI, saved, and did
        # nothing, while the plugin-level key alone reached the card. That is
        # also the opposite precedence to every sibling scoreboard, where the
        # per-league copy wins. The league block is read now, and a league
        # value still at its default gives way to a plugin-level value the user
        # changed (see _league_or_root).
        display_options = league_config.get("display_options", {})
        root = self.config

        def dup(block, key, fallback):
            """A league key also declared at the plugin root; see _league_or_root."""
            return _league_or_root(block, root, key, fallback)

        # Create manager config with expected structure
        manager_config = {
            f"soccer_{league_key}_scoreboard": {
                "enabled": league_config.get("enabled", False),
                "favorite_teams": league_config.get("favorite_teams", []),
                "exclude_teams": league_config.get("exclude_teams", []),
                "display_modes": manager_display_modes,
                # Every dup() below is a key the schema declares both in this
                # league block and at the plugin root: a changed league value
                # wins, then a changed root value, then the league value. See
                # _league_or_root.
                "recent_games_to_show": dup(
                    game_limits, "recent_games_to_show",
                    league_config.get("recent_games_to_show", 5)),
                # These ride the same source as the limits above, which is where the
                # schema declares them. Managers read a translated config, not the
                # plugin config, so a key missing here is a setting the user can
                # change in the web UI that silently never reaches the code.
                "other_upcoming_games_to_show": dup(
                    game_limits, "other_upcoming_games_to_show",
                    game_limits.get("upcoming_games_to_show", 10),
                ),
                "other_recent_games_to_show": dup(
                    game_limits, "other_recent_games_to_show",
                    game_limits.get("recent_games_to_show", 5),
                ),
                "other_rotation_interval_seconds": dup(
                    game_limits, "other_rotation_interval_seconds", 1800
                ),
                "favorite_rotation_boost": dup(
                    game_limits, "favorite_rotation_boost", 1),
                "other_games_min_quality": dup(
                    game_limits, "other_games_min_quality", "ranked"
                ),
                # Passed through raw; sports.py's _normalise_divisions does the
                # coercion. list() here turned a hand-edited "fbs" into
                # ['f','b','s'] (matching nothing, so every non-favourite game
                # was rejected) and raised TypeError on a null, which the single
                # try in _initialize_managers turned into no managers at all.
                "other_games_divisions": dup(
                    game_limits, "other_games_divisions", ["fbs"]
                ),
                "upcoming_games_to_show": dup(
                    game_limits, "upcoming_games_to_show",
                    league_config.get("upcoming_games_to_show", 10)),
                "show_records": dup(display_options, "show_records", False),
                "show_ranking": dup(display_options, "show_ranking", False),
                "show_odds": dup(display_options, "show_odds", True),
                "update_interval_seconds": dup(
                    league_config, "update_interval_seconds", 3600
                ),
                "live_update_interval": dup(league_config, "live_update_interval", 30),
                "recent_update_interval": dup(league_config, "recent_update_interval", 3600),
                "upcoming_update_interval": dup(league_config, "upcoming_update_interval", 3600),
                "stale_game_timeout": dup(league_config, "stale_game_timeout", 300),
                # Read by SportsCore/SportsLive out of this translated block.
                # Every league block declares the celebration keys, and none
                # of them arrived: celebrations were always on, always 8s.
                "celebration_enabled": league_config.get("celebration_enabled", True),
                "celebration_duration": league_config.get("celebration_duration", 8),
                "celebration_team_colors": league_config.get(
                    "celebration_team_colors", True
                ),
                "celebration_confetti": league_config.get(
                    "celebration_confetti", True
                ),
                "celebrate_opponent_goals": league_config.get(
                    "celebrate_opponent_goals", False
                ),
                "odds_update_interval": league_config.get("odds_update_interval", 3600),
                "live_odds_update_interval": league_config.get(
                    "live_odds_update_interval", 60
                ),
                # Drives the simulated live game (SportsLive.test_mode); not
                # in the schema, but unreachable from config without this.
                "test_mode": league_config.get("test_mode", False),
                "live_game_duration": dup(league_config, "live_game_duration", 20),
                "non_favorite_live_game_duration": league_config.get(
                    "non_favorite_live_game_duration", 0
                ),
                "recent_game_duration": league_config.get("recent_game_duration", 15),
                "upcoming_game_duration": league_config.get("upcoming_game_duration", 15),
                "live_priority": league_config.get("live_priority", False),
                # Flattened, so it takes precedence over the filtering dict
                # below in SportsCore.
                "show_favorite_teams_only": dup(
                    filtering, "show_favorite_teams_only",
                    league_config.get("show_favorite_teams_only", False)),
                "show_all_live": filtering.get("show_all_live", league_config.get("show_all_live", False)),
                "filtering": filtering if filtering else {
                    "show_favorite_teams_only": league_config.get("show_favorite_teams_only", False),
                    "show_all_live": league_config.get("show_all_live", False),
                },
                # The root background_service settings; these were pinned
                # at their defaults here, so changing them did nothing.
                "background_service": _background_settings(self.config),
            }
        }

        # Resolve timezone: plugin override -> global config (either manager)
        # -> host system zone -> UTC. Reading only cache_manager.config_manager
        # used to fall through to UTC on cores that expose it via the plugin
        # manager instead, rendering every start time in UTC.
        timezone_str = resolve_timezone_name(
            config=self.config,
            plugin_manager=getattr(self, "plugin_manager", None),
            cache_manager=self.cache_manager,
            log=self.logger,
        )
        
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

        # Plugin-root settings that SportsCore reads from the root of the config
        # it is handed. This adapter builds its output key by key, so anything
        # not named here is dropped -- which is how the schedule window silently
        # pinned every user to the defaults, and would have done the same to the
        # idle-poll settings. Generalised to a list so the next one added to
        # SportsCore only has to be named once.
        for _root_key in _ROOT_CONFIG_KEYS:
            if _root_key in self.config:
                manager_config[_root_key] = self.config[_root_key]
        return manager_config

    def _build_custom_league_map(self) -> None:
        """Build O(1) lookup map from custom_leagues config, keyed by league_code."""
        self._custom_league_map: Dict[str, Dict] = {
            cl['league_code']: cl
            for cl in (self.config.get('custom_leagues') or [])
            if isinstance(cl, dict) and cl.get('league_code')
        }

    def _normalize_custom_leagues(self) -> None:
        """
        Clean up the custom_leagues config in place before anything reads it.

        The web UI's array-table editor keeps every non-column property in a
        hidden text input, so anything it can't represent as text comes back as
        null (empty input), and list properties come back as the comma-separated
        string the user typed. Dropping the nulls lets every downstream
        ``.get(key, default)`` fall back to its default, and splitting the
        strings restores the list shape the managers expect.
        """
        custom_leagues = self.config.get('custom_leagues') or []

        # Container properties the array-table editor keeps in a hidden input.
        # An untouched row sends them back as null, and a cleared one as an
        # empty string -- neither of which downstream .get() chains survive.
        _CONTAINER_KEYS = ('display_modes', 'game_limits', 'filtering',
                           'dynamic_duration')

        def _strip_nulls(value: Any) -> Any:
            if isinstance(value, dict):
                return {k: _strip_nulls(v) for k, v in value.items() if v is not None}
            return value

        def _drop_blank_containers(row: Dict[str, Any]) -> Dict[str, Any]:
            for key in _CONTAINER_KEYS:
                held = row.get(key)
                if held is not None and not isinstance(held, dict):
                    # A string here means "the user never opened this"; the
                    # defaults are better than a value nothing can read.
                    row.pop(key, None)
            return row

        normalized: List[Dict[str, Any]] = []
        for custom_league in custom_leagues:
            if not isinstance(custom_league, dict):
                self.logger.warning("Skipping malformed custom league entry: %r", custom_league)
                continue

            cleaned = _drop_blank_containers(_strip_nulls(custom_league))

            # "ARS, CHE" (row editor) -> ["ARS", "CHE"]
            for key in ('favorite_teams', 'exclude_teams'):
                teams = cleaned.get(key)
                if isinstance(teams, str):
                    cleaned[key] = [t.strip() for t in teams.split(',') if t.strip()]

            code = cleaned.get('league_code')
            if isinstance(code, str):
                cleaned['league_code'] = code.strip().lower()

            normalized.append(cleaned)

        self.config['custom_leagues'] = normalized

    def _get_league_config(self, league_key: str, league_data: Optional[Dict] = None) -> Dict:
        """Get the config dict for a league, handling both predefined and custom leagues."""
        if league_data is None:
            league_data = self._league_registry.get(league_key, {})

        if league_data.get('is_custom', False):
            return self._custom_league_map.get(league_key, {})
        else:
            leagues_config = self.config.get('leagues', {})
            return leagues_config.get(league_key, {})

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
        self._normalize_custom_leagues()
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
                "exclude_teams": custom_league.get("exclude_teams", []),
                "display_modes": manager_display_modes,
                "recent_games_to_show": game_limits.get("recent_games_to_show", 1),
                # These ride the same source as the limits above, which is where the
                # schema declares them. Managers read a translated config, not the
                # plugin config, so a key missing here is a setting the user can
                # change in the web UI that silently never reaches the code.
                "other_upcoming_games_to_show": game_limits.get(
                    "other_upcoming_games_to_show",
                    game_limits.get("upcoming_games_to_show", 10),
                ),
                "other_recent_games_to_show": game_limits.get(
                    "other_recent_games_to_show",
                    game_limits.get("recent_games_to_show", 1),
                ),
                "other_rotation_interval_seconds": game_limits.get(
                    "other_rotation_interval_seconds", 1800
                ),
                "favorite_rotation_boost": game_limits.get("favorite_rotation_boost", 1),
                "other_games_min_quality": game_limits.get(
                    "other_games_min_quality", "ranked"
                ),
                # Raw, as above: _normalise_divisions coerces it.
                "other_games_divisions": game_limits.get(
                    "other_games_divisions", ["fbs"]
                ),
                "upcoming_games_to_show": game_limits.get("upcoming_games_to_show", 10),
                # custom_leagues declares no display_options block, so these
                # stay plugin-level. Schema default for show_odds is true.
                "show_records": self.config.get("show_records", False),
                "show_ranking": self.config.get("show_ranking", False),
                "show_odds": self.config.get("show_odds", True),
                # 3600 to match the built-in leagues and the schema. It has
                # no effect on fetch cadence: every manager replaces it with
                # its own live/recent/upcoming interval, so the schema hides
                # it. The per-mode intervals below are the real controls.
                "update_interval_seconds": custom_league.get("update_interval_seconds", 3600),
                "live_update_interval": custom_league.get("live_update_interval", 30),
                "recent_update_interval": custom_league.get("recent_update_interval", 3600),
                "upcoming_update_interval": custom_league.get("upcoming_update_interval", 3600),
                "stale_game_timeout": custom_league.get("stale_game_timeout", 300),
                "celebration_enabled": custom_league.get("celebration_enabled", True),
                "celebration_duration": custom_league.get("celebration_duration", 8),
                "celebration_team_colors": custom_league.get(
                    "celebration_team_colors", True
                ),
                "celebration_confetti": custom_league.get(
                    "celebration_confetti", True
                ),
                "celebrate_opponent_goals": custom_league.get(
                    "celebrate_opponent_goals", False
                ),
                "odds_update_interval": custom_league.get("odds_update_interval", 3600),
                "live_odds_update_interval": custom_league.get(
                    "live_odds_update_interval", 60
                ),
                "test_mode": custom_league.get("test_mode", False),
                "live_game_duration": custom_league.get("live_game_duration", 20),
                "non_favorite_live_game_duration": custom_league.get(
                    "non_favorite_live_game_duration", 0
                ),
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
                # The root background_service settings; these were pinned
                # at their defaults here, so changing them did nothing.
                "background_service": _background_settings(self.config),
                # Custom league specific
                "league_code": league_code,
                "league_name": league_name,
            }
        }

        # Add global config
        # Resolve timezone: plugin override -> global config (either manager)
        # -> host system zone -> UTC. Reading only cache_manager.config_manager
        # used to fall through to UTC on cores that expose it via the plugin
        # manager instead, rendering every start time in UTC.
        timezone_str = resolve_timezone_name(
            config=self.config,
            plugin_manager=getattr(self, "plugin_manager", None),
            cache_manager=self.cache_manager,
            log=self.logger,
        )

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

        # Custom leagues go through their own whitelist adapter, so they need
        # the same root-key forwarding the predefined leagues get above --
        # otherwise a user's schedule-window and idle-poll settings apply to
        # every built-in league but silently not to their custom ones.
        for _root_key in _ROOT_CONFIG_KEYS:
            if _root_key in self.config:
                manager_config[_root_key] = self.config[_root_key]

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

        Built into a local and swapped in with a single assignment. The display
        thread iterates ``self._league_registry`` (via
        ``_get_enabled_leagues_for_mode``) while ``on_config_change`` rebuilds it
        on the ConfigService-Watcher thread; mutating the live dict in place let
        a frame observe it empty or half-populated, or raise "dictionary changed
        size during iteration". Rebinding the attribute is atomic, so a reader
        gets either the whole old registry or the whole new one.
        """
        registry: Dict[str, Dict[str, Any]] = {}
        # Add predefined leagues to registry
        for league_key in PREDEFINED_LEAGUE_KEYS:
            attr_tuple = PREDEFINED_LEAGUE_ATTR_MAP.get(league_key)
            if not attr_tuple:
                continue
            live_attr, recent_attr, upcoming_attr = attr_tuple

            registry[league_key] = {
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

            registry[league_code] = {
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

        # Publish the finished registry in one atomic rebind (see docstring).
        self._league_registry = registry

        # Log registry state for debugging
        enabled_leagues = [lid for lid, data in registry.items() if data['enabled']]
        custom_count = len([lid for lid, data in registry.items() if data.get('is_custom', False)])
        self.logger.info(
            f"League registry initialized: {len(registry)} league(s) registered "
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

        # One snapshot for the whole selection. _initialize_league_registry
        # publishes a replacement registry by rebinding the attribute, so
        # re-reading self._league_registry further down (the sort key, the debug
        # line) could bind a NEWER registry than the one just iterated -- and a
        # custom league collected from the old one may be absent from it, which
        # is a KeyError in the sort. Reading once makes the whole selection
        # consistent with a single registry.
        registry = self._league_registry

        # Iterate through all registered leagues
        for league_id, league_data in registry.items():
            # Check if league is enabled
            if not league_data.get('enabled', False):
                continue

            # Check if this mode type is enabled for this league
            # Get the league config to check display_modes settings
            league_config = self._get_league_config(league_id, league_data)

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
        enabled_leagues.sort(key=lambda lid: registry[lid].get('priority', 999))

        self.logger.debug(
            f"Enabled leagues for {mode_type} mode: {enabled_leagues} "
            f"(priorities: {[registry[lid].get('priority') for lid in enabled_leagues]})"
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
        # One snapshot: the membership test and the lookup must see the same
        # registry, or a rebind between them turns the check into a KeyError.
        registry = self._league_registry

        # Check if league exists in registry
        if league_id not in registry:
            self.logger.warning(f"League {league_id} not found in registry")
            return None

        # Get managers dict for this league
        managers = registry[league_id].get('managers', {})

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
        custom_leagues = self.config.get('custom_leagues', [])
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

    def _has_any_scroll_mode(self) -> bool:
        """Return True if any enabled league uses scroll for any mode type."""
        if not self._scroll_manager:
            return False
        for mode_type in ('live', 'recent', 'upcoming'):
            if self._should_use_scroll_mode(mode_type):
                return True
        return False

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

    def _manager_has_displayable_games(self, manager, mode_type: str) -> bool:
        """Return True if the manager currently has games to show for this mode.

        Live managers expose their games as ``live_games``; recent and upcoming
        managers expose ``games_list``. In switch mode an empty manager must be
        skipped: its ``display()`` clears the shared canvas when it has no games,
        which would erase content another league's manager just drew for the same
        mode and leave the panel blank for the rest of the slot.
        """
        if mode_type == 'live':
            return bool(getattr(manager, 'live_games', None))
        return bool(getattr(manager, 'games_list', None))

    def _get_available_modes(self) -> list:
        """Get list of available display modes based on enabled leagues."""
        modes = []

        for league_key, league_data in self._league_registry.items():
            if not league_data.get('enabled', False):
                continue

            league_config = self._get_league_config(league_key, league_data)

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
        with self._config_lock:
            modes = self.modes
            mode_index = self.current_mode_index
        if not modes:
            return None

        current_mode = modes[mode_index % len(modes)]

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

    def on_config_change(self, new_config: Dict[str, Any]) -> None:
        """Apply config changes at runtime without restart."""
        if BasePlugin:
            super().on_config_change(new_config)
        else:
            self.config = new_config or {}

        self.is_enabled = self.config.get("enabled", True)

        # Re-read league enabled states and live priority
        leagues_config = self.config.get('leagues', {})
        self.league_enabled = {}
        self.league_live_priority = {}
        for league_key in LEAGUE_KEYS:
            league_config = leagues_config.get(league_key, {})
            self.league_enabled[league_key] = league_config.get('enabled', False)
            self.league_live_priority[league_key] = league_config.get("live_priority", False)

        # Re-read global settings
        self.display_duration = float(self.config.get("display_duration", 30))
        self.game_display_duration = float(self.config.get("game_display_duration", 15))

        # Acquire exclusive lock so display()/update() see consistent state
        with self._config_lock:
            # Drain in-flight update threads before replacing managers
            for name, thread in list(self._active_update_threads.items()):
                if thread.is_alive():
                    thread.join(timeout=10.0)
            self._active_update_threads.clear()

            # Clear stale runtime caches before rebuilding. _league_registry is
            # deliberately NOT cleared here: _initialize_league_registry() below
            # rebuilds it into a local and swaps it in atomically, so the display
            # thread never sees it empty.
            self._scroll_prepared.clear()
            self._scroll_active.clear()
            # Force the next Vegas read to rebuild against the new config.
            self._vegas_signature = None
            # Favorites and custom leagues may have changed, so let the
            # diagnostic report again, built for the new league list.
            self._favorite_check = None

            # Reinitialize managers and modes
            self._initialize_managers()
            self._load_custom_leagues()
            self._build_custom_league_map()
            self._initialize_league_registry()
            self._display_mode_settings = self._parse_display_mode_settings()
            self.modes = self._get_available_modes()
            self.current_mode_index = 0
            self.enable_scrolling = self._has_any_scroll_mode()

        enabled_leagues = [k for k, v in self.league_enabled.items() if v]
        self.logger.info(
            f"Config updated at runtime - reinitialized. Enabled leagues: "
            f"{', '.join([LEAGUE_NAMES.get(k, k) for k in enabled_leagues]) if enabled_leagues else 'None'}"
        )

    def _check_favorite_teams(self, registry: Dict[str, Dict[str, Any]]) -> None:
        """
        Say why an enabled league is showing nothing.

        A favourite that is not a real ESPN abbreviation matches no game, and so
        does a correct one before its season starts; both look like an empty
        screen. The check runs in the background, once per league per process,
        and never affects what is displayed.
        """
        try:
            checker = getattr(self, "_favorite_check", None)
            if checker is None:
                # A league's key is its ESPN code, custom leagues included.
                checker = FavoriteTeamCheck(self.logger, {
                    key: (LEAGUE_NAMES.get(key, key), "soccer/{}".format(key))
                    for key in registry
                })
                self._favorite_check = checker
            for league_key, league_data in registry.items():
                if not league_data.get('enabled', False):
                    continue
                managers = league_data.get('managers', {})
                for mode in ("live", "recent", "upcoming"):
                    favorites = getattr(managers.get(mode), "favorite_teams", None)
                    if favorites:
                        checker.schedule(league_key, favorites)
                        break
        except Exception as exc:
            self.logger.debug("Favorite team check skipped: %s", exc)

    def update(self) -> None:
        """Update soccer game data using parallel manager updates."""
        if not self.is_enabled:
            return

        # Snapshot registry and thread state under the config lock so we don't
        # iterate a dict that on_config_change is rebuilding.
        with self._config_lock:
            registry_snapshot = dict(self._league_registry)

        self._check_favorite_teams(registry_snapshot)

        # Collect all manager update tasks from the snapshot
        update_tasks = []

        for league_key, league_data in registry_snapshot.items():
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
        with self._config_lock:
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
                with self._config_lock:
                    if name in self._active_update_threads:
                        del self._active_update_threads[name]

    #: Fields excluded when deciding whether the strip needs rebuilding.
    #: Everything *else* in the game dict is compared, so a field this set does
    #: not name cannot be silently missed -- a denylist on purpose, because the
    #: first version of this fix used an allowlist and omitted down-and-distance,
    #: possession, the red-zone colour, the timeout counts and the scoring
    #: banner, all of which the card draws.
    #:
    #: Two reasons a field belongs here:
    #:
    #: * It moves on its own. The clock ticks every second and status_text
    #:   embeds it ("0:44 - 4th"); rebuilding on either would re-render every
    #:   card once a second. Measured on a real live game dict, those are the
    #:   only two of 36 fields that move when nothing but the clock does.
    #: * The display pipeline adds it. _collect_games_for_scroll() decorates
    #:   each game with "league" and "status" *in place*, mutating the dicts the
    #:   live manager holds -- and the next update() replaces those dicts with
    #:   undecorated ones. A fingerprint that counted them therefore flipped on
    #:   every update whether or not anything had changed, which an end-to-end
    #:   simulation caught rebuilding the strip on a bare clock tick. Neither
    #:   carries information the rest of the dict lacks: games are already
    #:   identified by id, and "status" is derived from is_live/is_final.
    LIVE_VOLATILE_FIELDS = frozenset({
        "clock", "status_text", "display_clock",   # move on their own
        "league", "status",                        # added by the display pipeline
        # This sport builds period_text as "<period> <clock>" (see
        # soccer_managers.py:297), so it moves every second too. The numeric `period`
        # is a separate field and is still compared, so a quarter/half change
        # still rebuilds -- only the clock inside the label goes stale between
        # rebuilds, which is the same trade as excluding `clock` itself.
        # football and hockey do not do this: their period_text is "Q4"/"P2".
        "period_text",
    })

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
        
        # A live card that changed since the strip was built has to rebuild
        # it now, not when the cycle ends -- see _live_scroll_needs_rebuild().
        # Refresh before fingerprinting, not after -- the rebuild
        # decision below is computed from exactly this data.
        self._refresh_live_scroll_managers()
        rebuild_for_live = self._live_scroll_needs_rebuild(scroll_key, mode_type)
        if rebuild_for_live or not self._scroll_prepared.get(scroll_key, False):
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
            # What the managers hold right now -- this is what the render
            # below draws, so it is what the strip must be recorded as showing.
            pending_live_fingerprint = self._live_scroll_fingerprint(None)
            with self._preserving_scroll_position(mode_type, rebuild_for_live, scroll_key):
                success = self._scroll_manager.prepare_and_display(
                    games, mode_type, leagues, rankings
                )
            
            if success:
                self._note_live_scroll_built(scroll_key, mode_type, pending_live_fingerprint)
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
    
    def _refresh_switch_mode_managers(self, mode_type) -> None:
        """Refresh the switch-mode managers before drawing them.

        baseball, basketball, football, hockey and lacrosse call
        _ensure_manager_updated() unconditionally in _try_manager_display(), so
        their switch mode is as fresh as the manager's own interval. These three
        had no equivalent: the switch path went straight to manager.display(),
        so it only ever showed whatever the last background plugin.update() left
        behind. That is invisible at the 60s default and an hour stale for anyone
        who raises update_interval -- reachable here because, unlike
        baseball/football, these manifests declare no update_interval of their
        own, so the config value is what applies.

        This runs before the candidate managers are *read*, not just before they
        are drawn: a stale manager reads as having nothing to show, so a league
        with a live game would be dropped from the rotation entirely.

        Two shapes across the lineage, the same split _live_scroll_managers()
        handles: a per-league accessor pair, and a single _get_manager. Anything
        else refreshes nothing, which leaves this inert rather than wrong.

        The refresh itself runs off the render thread -- see
        _dispatch_switch_refresh(). A due manager.update() fetches rankings and
        the schedule synchronously, and this is called from display().
        """
        managers = []
        leagues_for_mode = getattr(self, "_get_enabled_leagues_for_mode", None)
        manager_for_league = getattr(self, "_get_league_manager_for_mode", None)
        if callable(leagues_for_mode) and callable(manager_for_league):
            try:
                # pylint: disable=not-callable
                # Lineages without these accessors infer them as None, so a
                # static checker calls them uncallable. The callable() test
                # above is the runtime guard; the branch is dead there.
                league_keys = list(leagues_for_mode(mode_type) or [])
            except (AttributeError, KeyError, TypeError, ValueError, OSError) as exc:
                self.logger.debug("Switch-mode refresh skipped: %s", exc)
                return
            for league_key in league_keys:
                try:
                    # pylint: disable=not-callable
                    manager = manager_for_league(league_key, mode_type)
                except (AttributeError, KeyError, TypeError, ValueError, OSError) as exc:
                    self.logger.debug(
                        "Switch-mode refresh skipped for %s: %s", league_key, exc)
                    continue
                if manager is not None:
                    managers.append(manager)
        else:
            getter = getattr(self, "_get_manager", None)
            if not callable(getter):
                return
            try:
                # pylint: disable=not-callable
                manager = getter(mode_type)
            except (AttributeError, KeyError, TypeError, ValueError, OSError) as exc:
                self.logger.debug("Switch-mode refresh skipped: %s", exc)
                return
            if manager is not None:
                managers.append(manager)

        for manager in managers:
            self._dispatch_switch_refresh(manager)

    def _display_switch_mode_fallback(self, display_mode: str, mode_type: str, force_clear: bool) -> bool:
        """Fallback to switch mode when scroll is not available."""
        # Refresh before reading the managers -- a stale manager can look
        # like it has nothing to show and be skipped entirely.
        self._refresh_switch_mode_managers(mode_type)
        managers_to_try = []

        # Use _get_enabled_leagues_for_mode to respect per-mode enablement
        enabled_league_keys = self._get_enabled_leagues_for_mode(mode_type)
        for league_key in enabled_league_keys:
            if self._get_display_mode(league_key, mode_type) != 'switch':
                continue

            manager = self._get_league_manager_for_mode(league_key, mode_type)
            if manager and self._manager_has_displayable_games(manager, mode_type):
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
            # A goal/win celebration takes over the screen ahead of normal
            # rendering. It only fires for live modes (or internal cycling), and
            # bypasses scroll mode + cross-league selection by rendering the
            # celebrating manager's switch-style takeover directly.
            is_live_request = display_mode is None or display_mode.endswith("_live")
            if is_live_request:
                celebrating = self._get_active_celebration_manager()
                if celebrating is not None:
                    league_key, live_manager = celebrating
                    self._current_display_league = league_key
                    self._current_display_mode_type = "live"
                    if live_manager.display(force_clear):
                        return True

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
                    # Refresh before reading the managers -- a stale manager can
                    # look like it has nothing to show and be skipped entirely.
                    self._refresh_switch_mode_managers(mode_type)
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
                            if manager and self._manager_has_displayable_games(manager, mode_type):
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
                # Refresh before reading the managers -- a stale manager can
                # look like it has nothing to show and be skipped entirely.
                self._refresh_switch_mode_managers(mode_type)
                managers_to_try = []
                enabled_league_keys = self._get_enabled_leagues_for_mode(mode_type)
                for key in enabled_league_keys:
                    manager = self._get_league_manager_for_mode(key, mode_type)
                    if manager and self._manager_has_displayable_games(manager, mode_type):
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

            # Snapshot modes under lock to avoid racing with on_config_change
            with self._config_lock:
                modes = self.modes
                mode_index = self.current_mode_index

            if not modes:
                return False

            # Clamp index in case modes list shrunk during a config reload
            mode_index = mode_index % len(modes)

            # Check if we should stay on live mode
            should_stay_on_live = False
            if self.has_live_content():
                # Get current mode name
                current_mode = modes[mode_index]
                # If we're on a live mode, stay there
                if current_mode and current_mode.endswith('_live'):
                    should_stay_on_live = True
                # If we're not on a live mode but have live content, switch to it
                elif not (current_mode and current_mode.endswith('_live')):
                    # Find the first live mode
                    for i, mode in enumerate(modes):
                        if mode.endswith('_live'):
                            mode_index = i
                            self.current_mode_index = i
                            force_clear = True
                            self.last_mode_switch = current_time
                            self.logger.info(f"Live content detected - switching to display mode: {mode}")
                            break

            # Handle mode cycling only if not staying on live
            if not should_stay_on_live and current_time - self.last_mode_switch >= self.display_duration:
                mode_index = (mode_index + 1) % len(modes)
                self.current_mode_index = mode_index
                self.last_mode_switch = current_time
                force_clear = True

                current_mode = modes[mode_index]
                self.logger.info(f"Switching to display mode: {current_mode}")

            # Get current mode and check if it uses scroll mode
            current_mode = modes[mode_index]
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

    @property
    def needs_high_fps(self) -> bool:
        """Whether the controller should drive this plugin at 125 FPS.

        Without this attribute the core falls back to `enable_scrolling`
        (LEDMatrix display_controller), which is false on a switch-mode board
        -- so the celebration's confetti and breathing score were being
        sampled once a second. The controller reads this once when it enters a
        mode, which is the moment that matters: a goal arms the takeover while
        some other plugin is on screen, live priority hands this plugin the
        panel, and the celebration is drawn smoothly from its first frame. One
        armed while this plugin is already showing still steps at 1 FPS for the
        rest of that turn, which is what the choreography is built to survive.
        """
        try:
            if self.enable_scrolling:
                return True
            return self._get_active_celebration_manager() is not None
        except Exception:  # noqa: BLE001 - the controller reads this bare
            return bool(getattr(self, "enable_scrolling", False))

    def has_live_priority(self) -> bool:
        """Check if any league has live priority enabled."""
        if not self.is_enabled:
            return False
        with self._config_lock:
            registry = dict(self._league_registry)
        return any(
            league_data.get('enabled', False) and league_data.get('live_priority', False)
            for _lk, league_data in registry.items()
        )

    def _get_active_celebration_manager(self):
        """Return the (league_key, live_manager) of an enabled league whose live
        manager currently has an active goal/win celebration, else None."""
        with self._config_lock:
            registry = dict(self._league_registry)
        for league_key, league_data in registry.items():
            if not league_data.get('enabled', False):
                continue
            live_manager = self._get_league_manager_for_mode(league_key, 'live')
            if (
                live_manager
                and hasattr(live_manager, "has_active_celebration")
                and live_manager.has_active_celebration()
            ):
                return league_key, live_manager
        return None

    def get_update_interval(self):
        """Poll at the live interval while a game is in progress, else no opinion.

        Without this hook the core scheduler calls update() at the static
        interval -- the manifest's 60s, or the config's update_interval where
        the manifest declares none (afl/nrl/soccer declare neither, so 60s;
        update_interval_seconds is never read). During a live game that is far slower than
        live_update_interval, so everything that reads update-cycle data lags:
        the Vegas cards, and any mode that is not on screen to refresh itself.
        Core 3.4.0 consults this hook on every tick (ChuckBuilds/LEDMatrix#555);
        football-scoreboard has carried it since then.

        Returning None when nothing is live keeps the idle cadence exactly where
        it was: this must not become a way to poll ESPN every 30 seconds all
        off-season.

        Cheap by construction -- the scheduler calls it on every tick, so it
        reads attributes of managers already held (the same live managers the
        scroll refresh walks) and never calls has_live_content(), which walks
        the games and applies favourite-team filtering.
        """
        if not getattr(self, "is_enabled", True):
            return None

        fastest = None
        for manager in self._live_scroll_managers(None) or []:
            # live_games rather than has_live_content(): a game in progress that
            # the favourites filter hides still needs fresh data, because the
            # filter can stop hiding it the moment a favourite's game ends.
            if not getattr(manager, "live_games", None):
                continue
            interval = getattr(manager, "update_interval", None)
            if interval is None:
                continue
            fastest = interval if fastest is None else min(fastest, interval)
        return fastest

    def has_live_content(self) -> bool:
        """Check if any league has live content."""
        if not self.is_enabled:
            return False

        # An active celebration (notably a win, whose game has already left the
        # live list) must keep the live mode on screen.
        if self._get_active_celebration_manager() is not None:
            return True

        with self._config_lock:
            registry = dict(self._league_registry)
        for league_key, league_data in registry.items():
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
        Return the registered live mode name(s) of the leagues that currently
        have live content, e.g. ``["soccer_fifa.world_live"]``.

        The host registers this plugin's modes per-league (``soccer_<league>_live``,
        built by ``_get_available_modes``), not under the generic ``soccer_live``
        manifest name. The display controller looks the returned modes up in its
        registered-mode map and only switches to one that exists; returning the
        generic ``soccer_live`` matches nothing, so it falls back to the first
        ``*_live`` mode in registration order — which may be an empty league whose
        game isn't the one that's actually live. Returning the real per-league
        mode names lets the controller switch straight to the league with the
        live game.
        """
        if not self.is_enabled:
            return []

        with self._config_lock:
            registry = dict(self._league_registry)

        live_modes = []
        for league_key, league_data in registry.items():
            if not league_data.get('enabled', False):
                continue

            live_manager = self._get_league_manager_for_mode(league_key, 'live')
            if not live_manager:
                continue

            # A celebrating league must be selectable even if its live list is
            # already empty (a win fires as the game goes final).
            if (
                hasattr(live_manager, "has_active_celebration")
                and live_manager.has_active_celebration()
            ):
                live_modes.append(f"soccer_{league_key}_live")
                continue

            live_games = getattr(live_manager, "live_games", [])
            if not live_games:
                continue

            show_all_live = league_data.get('show_all_live', False) or getattr(live_manager, 'show_all_live', False)
            if show_all_live:
                live_modes.append(f"soccer_{league_key}_live")
                continue

            favorite_teams = getattr(live_manager, "favorite_teams", [])
            if favorite_teams and any(
                game.get("home_abbr") in favorite_teams
                or game.get("away_abbr") in favorite_teams
                for game in live_games
            ):
                live_modes.append(f"soccer_{league_key}_live")

        return live_modes

    def get_info(self) -> Dict[str, Any]:
        """Get plugin information."""
        try:
            current_manager = self._get_current_manager()
            with self._config_lock:
                modes = self.modes
                mode_index = self.current_mode_index
                registry_snapshot = dict(self._league_registry)
            current_mode = modes[mode_index % len(modes)] if modes else "none"

            # Build league info from registry (includes custom leagues)
            league_info = {}
            for league_key, league_data in registry_snapshot.items():
                league_info[league_key] = {
                    "enabled": league_data.get("enabled", False),
                    "live_priority": league_data.get("live_priority", False),
                }

            info = {
                "plugin_id": self.plugin_id,
                "name": "Soccer Scoreboard",
                "version": "2.1.0",
                "enabled": self.is_enabled,
                "display_size": f"{self.display_width}x{self.display_height}",
                "leagues": league_info,
                "current_mode": current_mode,
                "available_modes": modes,
                "display_duration": self.display_duration,
                "game_display_duration": self.game_display_duration,
                "show_records": self.config.get("show_records", False),
                "show_ranking": self.config.get("show_ranking", False),
                # Schema default is true; reporting false made get_info()
                # disagree with what the managers were actually given.
                "show_odds": self.config.get("show_odds", True),
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
        league_config = self._get_league_config(league_key)
        league_dynamic = league_config.get("dynamic_duration", {})
        league_modes = league_dynamic.get("modes", {})
        mode_config = league_modes.get(mode_type, {})
        # The league switch turns every mode on; a mode switch turns on just
        # that mode. Both default to off and the core fills every default into
        # the config, so returning the mode switch whenever it was present (as
        # this did) meant the league switch was never read.
        if mode_config.get("enabled", False) or league_dynamic.get("enabled", False):
            return True

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
        league_config = self._get_league_config(league_key)
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
        """Dynamic duration floor for the current display context.

        Every league block declares ``dynamic_duration.min_duration_seconds``
        beside its max, and only the max was ever read -- a mode could run
        shorter than the minimum asked for. Same ladder as the cap.
        """
        if not self.is_enabled:
            return None
        if not self._current_display_league or not self._current_display_mode_type:
            return None

        league_config = self._get_league_config(self._current_display_league)
        league_dynamic = league_config.get("dynamic_duration", {})
        mode_config = league_dynamic.get("modes", {}).get(
            self._current_display_mode_type, {})
        for source in (mode_config, league_dynamic):
            if "min_duration_seconds" in source:
                try:
                    floor = float(source.get("min_duration_seconds"))
                    if floor > 0:
                        return floor
                except (TypeError, ValueError):
                    pass
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
                # Floor last, so an explicit minimum wins over a smaller cap.
                floor = self.get_dynamic_duration_floor()
                if floor is not None:
                    effective_duration = max(effective_duration, floor)
            return effective_duration

        # No mode-level duration: games x per-game time, for this mode's own
        # league. This read manager.games, which no soccer manager has, so it
        # was always 0 and the plugin never sized a slot from its games; it
        # also summed every enabled league although each mode is one league.
        total_duration = 0.0
        body = display_mode[len('soccer_'):] if display_mode.startswith('soccer_') else ''
        league_key = body.rsplit('_', 1)[0] if '_' in body else None
        league_data = self._league_registry.get(league_key, {}) if league_key else {}
        manager = (league_data.get('managers', {}).get(mode_type)
                   if league_data.get('enabled', False) else None)
        if manager:
            games = self._get_games_from_manager(manager, mode_type)
            if games:
                total_duration = len(games) * self._get_game_duration(league_key, mode_type, manager)

        if total_duration == 0.0:
            return None

        # Apply dynamic cap if configured
        if self._dynamic_feature_enabled():
            cap = self.get_dynamic_duration_cap()
            if cap is not None:
                total_duration = min(total_duration, cap)
            floor = self.get_dynamic_duration_floor()
            if floor is not None:
                total_duration = max(total_duration, floor)

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
        with self._config_lock:
            modes = self.modes
            mode_index = self.current_mode_index
        if not self._dynamic_feature_enabled() or not modes:
            self._dynamic_cycle_complete = True
            return

        current_mode = modes[mode_index % len(modes)]
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

        with self._config_lock:
            modes = self.modes
        if not modes:
            self._dynamic_cycle_complete = True
            return

        required_modes = [mode for mode in modes if mode]
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

    # -------------------------------------------------------------------------
    # Vegas scroll mode support
    # -------------------------------------------------------------------------
    def get_vegas_content(self) -> Optional[Any]:
        """
        Get content for Vegas-style continuous scroll mode.

        Reads the dedicated 'mixed' scroll display rather than the union of
        every display. The union meant that once a standalone scroll mode had
        rendered, Vegas inherited that mode's games, and because content was
        only built when the union was EMPTY, a score change never reached the
        ticker. Content is rebuilt when the game signature changes, so the
        common case is a cheap cache read. It never calls update(): refreshing
        data is the update cycle's job, and network I/O here would stall the
        Vegas render loop. Ported from baseball-scoreboard.

        Returns:
            List of PIL Images, one per game, or None if there is nothing to show
        """
        if not getattr(self, '_scroll_manager', None):
            return None

        try:
            games, leagues = self._collect_games_for_scroll(mode_type=None)
        except Exception:
            self.logger.exception("[Soccer Vegas] Failed to collect games")
            return None
        if not games:
            self.logger.debug("[Soccer Vegas] No games available")
            return None

        signature = self._vegas_game_signature(games)
        images = self._scroll_manager.get_vegas_content_items_for(_VEGAS_SCROLL_KEY)
        if not images or signature != getattr(self, '_vegas_signature', None):
            self.logger.info(
                "[Soccer Vegas] Rebuilding scroll content (%s): %d game(s)",
                "no cached content" if not images else "game data changed",
                len(games),
            )
            if self._ensure_scroll_content_for_vegas(games, leagues):
                self._vegas_signature = signature
            images = self._scroll_manager.get_vegas_content_items_for(_VEGAS_SCROLL_KEY)

        if not images:
            return None
        self.logger.debug(
            "[Soccer Vegas] Returning %d image(s), %dpx total",
            len(images), sum(img.width for img in images)
        )
        return images

    @staticmethod
    def _vegas_game_signature(games: List[Dict]) -> tuple:
        """Cheap fingerprint of what a viewer would notice on the Vegas cards."""
        fingerprint = []
        for game in games:
            status = game.get('status')
            state = status.get('state') if isinstance(status, dict) else status
            fingerprint.append((
                game.get('id'), game.get('league'), state,
                game.get('home_abbr'), game.get('away_abbr'),
                game.get('home_score'), game.get('away_score'),
                game.get('period_text'), game.get('clock'),
                game.get('is_final'), bool(game.get('odds')),
            ))
        return tuple(fingerprint)

    def get_vegas_elements(self) -> Optional[List[Any]]:
        """Live Vegas cards: one per game, swapped in place when its game changes.

        The slate get_vegas_content() shows, plus games that have just gone
        final, so a card on its way across the panel turns to Final instead
        of keeping its last live score. A card is drawn again only when its
        game's data changed, the running clock included (core's
        build_vegas_elements). None -- no live cards in this core, or nothing
        to show -- and the ticker uses get_vegas_content() instead.
        """
        scroll_manager = getattr(self, '_scroll_manager', None)
        if sports_vegas is None or not hasattr(scroll_manager, 'get_vegas_elements_for'):
            return None
        try:
            games, leagues = self.vegas_slate()
        except Exception:
            self.logger.exception("[Soccer Vegas] Failed to collect games")
            return None
        if not games:
            return None
        return scroll_manager.get_vegas_elements_for(_VEGAS_SCROLL_KEY, games, leagues, self._get_rankings_cache())

    def vegas_slate(self) -> Tuple[List[Dict], List[str]]:
        """The games the live Vegas cards show, and their leagues in order."""
        games, leagues = self._collect_games_for_scroll(mode_type=None)
        # Every league the collector reads a live list from, custom ones
        # included -- the same union of modes it walks, so a finished game
        # comes only from a league whose live games were on the slate.
        slate_leagues: List[str] = []
        for mode_type in ('live', 'recent', 'upcoming'):
            for league in self._get_enabled_leagues_for_mode(mode_type):
                if league not in slate_leagues:
                    slate_leagues.append(league)
        # In the collector's league order, so a league with nothing else on
        # the slate adds its finished games in priority order, not mode order.
        registry = self._league_registry
        slate_leagues.sort(key=lambda lk: (registry.get(lk, {}).get('priority', 999), lk))
        live_managers = [(league, self._get_league_manager_for_mode(league, 'live'))
                         for league in slate_leagues]
        return sports_vegas.with_finished_games(
            games, leagues, sports_vegas.finished_games(live_managers))

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

    def _ensure_scroll_content_for_vegas(self, games=None, leagues=None) -> bool:
        """
        Render the combined live/recent/upcoming slate for Vegas mode.

        Called by get_vegas_content() when its cache is empty or the games
        changed. Returns True when content was rendered.
        """
        if not hasattr(self, '_scroll_manager') or not self._scroll_manager:
            self.logger.debug("[Soccer Vegas] No scroll manager available")
            return False

        if games is None:
            games, leagues = self._collect_games_for_scroll(mode_type=None)

        if not games:
            self.logger.debug("[Soccer Vegas] No games available")
            return False

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

        # prepare_content, not prepare_and_display: the latter also makes
        # 'mixed' the active scroll display, which hijacked the standalone
        # rotation's in-progress scroll with the Vegas slate.
        try:
            success = self._scroll_manager.prepare_content(
                games, _VEGAS_SCROLL_KEY, leagues, self._get_rankings_cache()
            )
        except Exception:
            self.logger.exception("[Soccer Vegas] Error rendering scroll content")
            return False

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
        return bool(success)

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
