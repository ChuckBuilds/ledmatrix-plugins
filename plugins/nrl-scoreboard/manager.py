"""
NRL Scoreboard Plugin for LEDMatrix

Displays live, recent, and upcoming NRL (National Rugby League) games using
ESPN's public rugby-league scoreboard API.

Display Modes:
- Switch Mode: Display one game at a time with timed transitions
- Scroll Mode: High-FPS horizontal scrolling of all games

NRL is a single league, so this plugin is a simplified single-league fork of the
soccer-scoreboard plugin: there is exactly one set of Live/Recent/Upcoming
managers instead of a per-league registry. All the parity features (dynamic
duration, scroll vs switch display, live priority + goal/win celebration, and the
Vegas continuous-scroll hooks) are preserved.
"""

import logging
import time
import threading
from typing import Dict, Any, Set, Optional, List, Tuple

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

# Import the NRL manager factory
from nrl_managers import create_nrl_managers, LEAGUE_NAMES, NRL_LEAGUE_SLUG

from nrl_timezone import resolve_timezone_name
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


# Which ESPN endpoint backs the league, for the favorite-team diagnostic.
FAVORITE_CHECK_KEY = 'nrl'
FAVORITE_CHECK_LEAGUES = {FAVORITE_CHECK_KEY: ('NRL', 'rugby-league/3')}

logger = logging.getLogger(__name__)

_MISSING = object()


def _display_option(display_options: Dict[str, Any], root: Dict[str, Any],
                    key: str, default: Any, legacy_root: Optional[str] = None) -> Any:
    """Resolve a toggle declared both in display_options and at the root.

    Ported from afl-scoreboard. The web UI saves schema defaults into both
    blocks, so a display_options value equal to the default says nothing about
    intent, and reading it first let a saved default silently undo a root
    toggle the user had changed. Precedence: a changed display_options value,
    then a root value (or a legacy name), then the default.
    """
    value = display_options.get(key, _MISSING)
    if value is not _MISSING and value != default:
        return value
    for name in (key, legacy_root):
        if name and name in root:
            return root[name]
    return default if value is _MISSING else value


# NRL is a single league. Its ESPN league slug is "3" (see nrl_managers.py), but
# the plugin's display modes / config are keyed with the friendly "nrl" name.
#: Schema defaults of settings declared both at the root and in a nested block
#: (game_limits, filtering). The core fills both copies with these, so a
#: nested value equal to its default says nothing about what the user chose;
#: see _nested_or_root.
_NESTED_DEFAULTS = {
    "recent_games_to_show": 1,
    "upcoming_games_to_show": 1,
    "other_upcoming_games_to_show": 1,
    "other_recent_games_to_show": 1,
    "other_rotation_interval_seconds": 1800,
    "favorite_rotation_boost": 1,
    "other_games_min_quality": "ranked",
    "other_games_divisions": ["fbs"],
    "show_favorite_teams_only": True,
}


def _nested_or_root(nested: Dict[str, Any], root: Dict[str, Any], key: str,
                    fallback: Any) -> Any:
    """A setting declared in a nested block and at the root.

    The nested copy used to win whenever present, and after the core's
    default fill it always is, so the root copy -- the one the settings page
    shows first -- was saved and ignored. Now, as for display_options: a
    nested value that differs from its default wins, then the root value;
    ``fallback`` applies only when neither declares the key.
    """
    if key not in nested and key not in root:
        return fallback
    return _display_option(nested, root, key, _NESTED_DEFAULTS.get(key, fallback))


LEAGUE_KEY = NRL_LEAGUE_SLUG  # "3" — ESPN's NRL slug, do not change to "nrl"
LEAGUE_NAME = LEAGUE_NAMES.get(NRL_LEAGUE_SLUG, "NRL")

# Registered display-mode names (must match manifest.json display_modes).
MODE_LIVE = "nrl_live"
MODE_RECENT = "nrl_recent"
MODE_UPCOMING = "nrl_upcoming"
MODE_TYPES = ("live", "recent", "upcoming")
# Scroll display that holds Vegas's combined live/recent/upcoming slate.
VEGAS_SCROLL_KEY = "mixed"


class NrlScoreboardPlugin(SportsPluginHostMixin, SportsLiveScrollMixin,
                          BasePlugin if BasePlugin else object):
    """NRL scoreboard plugin using the shared sports manager classes."""

    def __init__(
        self,
        plugin_id: str,
        config: Dict[str, Any],
        display_manager,
        cache_manager,
        plugin_manager,
    ):
        """Initialize the NRL scoreboard plugin."""
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

        # Global settings
        self.display_duration = float(config.get("display_duration", 30))
        self.game_display_duration = float(config.get("game_display_duration", 15))
        self.live_priority = bool(config.get("live_priority", True))

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

        # Managers dict: {'live': manager, 'recent': manager, 'upcoming': manager}
        self._managers: Dict[str, Any] = {}

        # Lock to protect shared mutable state during config reload
        self._config_lock = threading.Lock()

        # Track active update threads to prevent accumulation of stale threads
        self._active_update_threads: Dict[str, threading.Thread] = {}

        # Initialize managers
        self._initialize_managers()

        # Parse per-mode display settings (switch vs scroll)
        self._display_mode_settings = self._parse_display_mode_settings()

        # Initialize scroll display manager if available
        self._scroll_manager: Optional[ScrollDisplayManager] = None
        if SCROLL_AVAILABLE and ScrollDisplayManager:
            try:
                self._scroll_manager = ScrollDisplayManager(
                    self.display_manager, self.config, self.logger,
                    global_config=getattr(self, 'global_config', {}) or {}
                )
                self.logger.info("Scroll display manager initialized")
            except Exception as e:
                self.logger.warning(f"Could not initialize scroll display manager: {e}")
                self._scroll_manager = None
        else:
            self.logger.debug("Scroll mode not available - ScrollDisplayManager not imported")

        # Track current scroll state
        self._scroll_active: Dict[str, bool] = {}
        self._scroll_prepared: Dict[str, bool] = {}
        # What each live strip was built from, and when, so a score change
        # rebuilds it mid-cycle instead of at the end of one.
        self._live_scroll_fingerprints = {}
        self._live_scroll_rebuilt_at = {}
        # Seconds the last strip render took, per mode; feeds the duty-cycle cap.
        self._live_scroll_rebuild_cost = {}

        # Enable high-FPS mode only when NRL actually uses scroll display mode.
        # Setting it unconditionally makes switch-mode run at 125 FPS and flash.
        self.enable_scrolling = self._has_any_scroll_mode()
        if self.enable_scrolling:
            self.logger.info("High-FPS scrolling enabled for NRL scoreboard")

        # Mode cycling
        self.current_mode_index = 0
        self.last_mode_switch = 0
        self.modes = self._get_available_modes()

        # Dynamic duration tracking
        self._dynamic_cycle_seen_modes: Set[str] = set()
        self._dynamic_mode_to_manager_key: Dict[str, str] = {}
        self._dynamic_manager_progress: Dict[str, Set[str]] = {}
        self._dynamic_managers_completed: Set[str] = set()
        self._dynamic_cycle_complete = False

        # Track current display context for granular dynamic duration
        self._current_display_mode_type: Optional[str] = None  # 'live'/'recent'/'upcoming'

        self.logger.info(
            f"NRL scoreboard plugin initialized - {self.display_width}x{self.display_height}, "
            f"modes: {self.modes}"
        )

    # ------------------------------------------------------------------
    # Initialization / config
    # ------------------------------------------------------------------
    def _initialize_managers(self) -> None:
        """Create the NRL Live/Recent/Upcoming managers."""
        try:
            manager_config = self._adapt_config_for_manager()
            live, recent, upcoming = create_nrl_managers(
                manager_config, self.display_manager, self.cache_manager
            )
            self._managers = {
                "live": live,
                "recent": recent,
                "upcoming": upcoming,
            }
            self.logger.info("NRL managers initialized")
        except Exception as e:
            self.logger.error(f"Error initializing managers: {e}", exc_info=True)
            self._managers = {}

    def _adapt_config_for_manager(self) -> Dict[str, Any]:
        """Adapt the flat plugin config into the structure the managers expect.

        The shared SportsCore reads its settings from ``config["nrl_scoreboard"]``,
        so we assemble that section from the flat top-level NRL config keys.
        """
        cfg = self.config

        display_modes_config = cfg.get("display_modes", {})
        manager_display_modes = {
            MODE_LIVE: display_modes_config.get("live", True),
            MODE_RECENT: display_modes_config.get("recent", True),
            MODE_UPCOMING: display_modes_config.get("upcoming", True),
        }

        game_limits = cfg.get("game_limits", {})
        filtering = cfg.get("filtering", {})

        def limit(key, default):
            """A limit from wherever the schema offers it.

            These keys are declared twice, at the root of the config and inside
            game_limits, and both render in the web UI. Reading one location
            meant the other was accepted, saved, and silently ignored -- the
            same class of gap as leaving the key out of this translation
            altogether. See _nested_or_root for which copy wins.
            """
            return _nested_or_root(game_limits, cfg, key, default)

        display_options = cfg.get("display_options") or {}

        manager_config = {
            "nrl_scoreboard": {
                "enabled": cfg.get("enabled", False),
                "favorite_teams": cfg.get("favorite_teams", []),
                "exclude_teams": cfg.get("exclude_teams", []),
                "display_modes": manager_display_modes,
                "recent_games_to_show": limit("recent_games_to_show", 1),
                # These ride the same source as the limits above, which is where the
                # schema declares them. Managers read a translated config, not the
                # plugin config, so a key missing here is a setting the user can
                # change in the web UI that silently never reaches the code.
                "other_upcoming_games_to_show": limit(
                    "other_upcoming_games_to_show",
                    limit("upcoming_games_to_show", 1),
                ),
                "other_recent_games_to_show": limit(
                    "other_recent_games_to_show",
                    limit("recent_games_to_show", 1),
                ),
                "other_rotation_interval_seconds": limit(
                    "other_rotation_interval_seconds", 1800
                ),
                "favorite_rotation_boost": limit("favorite_rotation_boost", 1),
                "other_games_min_quality": limit(
                    "other_games_min_quality", "ranked"
                ),
                # Passed through raw; sports.py normalises it. list() here
                # turned a hand-edited "fbs" into ['f','b','s'] -- already a
                # list, so the string branch never fired and the filter
                # rejected every non-favourite game -- and made a null raise
                # TypeError inside this translation, leaving no managers.
                "other_games_divisions": limit("other_games_divisions", ["fbs"]),
                "upcoming_games_to_show": limit("upcoming_games_to_show", 1),
                # Declared both here (display_options) and at the root, and
                # the web UI saves defaults into both, so a display_options
                # value still at its default must not override a root toggle
                # the user changed. See _display_option. Defaults mirror
                # config_schema.json.
                "show_records": _display_option(
                    display_options, cfg, "show_records", False),
                "show_ranking": _display_option(
                    display_options, cfg, "show_ranking", False),
                "show_odds": _display_option(
                    display_options, cfg, "show_odds", True),
                "update_interval_seconds": cfg.get("update_interval_seconds", 3600),
                "live_update_interval": cfg.get("live_update_interval", 30),
                "recent_update_interval": cfg.get("recent_update_interval", 3600),
                "upcoming_update_interval": cfg.get("upcoming_update_interval", 3600),
                "stale_game_timeout": cfg.get("stale_game_timeout", 300),
                # Read by sports.py _fetch_odds / _attach_odds_to_rotated_games.
                "odds_update_interval": cfg.get("odds_update_interval", 3600),
                "live_odds_update_interval": cfg.get("live_odds_update_interval", 60),
                # Drives SportsLive's simulated game; without it test_mode could
                # never be set from config (same as football/baseball).
                "test_mode": cfg.get("test_mode", False),
                "live_game_duration": cfg.get("live_game_duration", 20),
                "non_favorite_live_game_duration": cfg.get(
                    "non_favorite_live_game_duration", 0
                ),
                "recent_game_duration": cfg.get("recent_game_duration", 15),
                "upcoming_game_duration": cfg.get("upcoming_game_duration", 15),
                "live_priority": cfg.get("live_priority", True),
                "celebration_enabled": cfg.get("celebration_enabled", True),
                "celebration_duration": cfg.get("celebration_duration", 8),
                "celebration_team_colors": cfg.get(
                    "celebration_team_colors", True
                ),
                "celebration_confetti": cfg.get(
                    "celebration_confetti", True
                ),
                "celebrate_opponent_goals": cfg.get("celebrate_opponent_goals", False),
                "show_favorite_teams_only": _nested_or_root(
                    filtering, cfg, "show_favorite_teams_only", False),
                "show_all_live": filtering.get(
                    "show_all_live", cfg.get("show_all_live", False)
                ),
                "favorite_live_boost": filtering.get(
                    "favorite_live_boost", cfg.get("favorite_live_boost", 2)
                ),
                "filtering": filtering if filtering else {
                    "show_favorite_teams_only": cfg.get("show_favorite_teams_only", False),
                    "show_all_live": cfg.get("show_all_live", False),
                },
                "background_service": cfg.get("background_service", {
                    "request_timeout": 30,
                    "max_retries": 3,
                    "priority": 2,
                }),
            }
        }

        # Resolve timezone: plugin override -> global config (either manager)
        # -> host system zone -> UTC. Reading only cache_manager.config_manager
        # used to fall through to UTC on cores that expose it via the plugin
        # manager instead, rendering every start time in UTC.
        timezone_str = resolve_timezone_name(
            config=cfg,
            plugin_manager=getattr(self, "plugin_manager", None),
            cache_manager=self.cache_manager,
            log=self.logger,
        )

        display_config = cfg.get("display", {})
        if not display_config and hasattr(self.cache_manager, 'config_manager'):
            display_config = self.cache_manager.config_manager.get_display_config()

        manager_config.update({
            "timezone": timezone_str,
            "display": display_config,
            "customization": cfg.get("customization", {}),
        })

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

    def _parse_display_mode_settings(self) -> Dict[str, str]:
        """Return {mode_type: 'switch'|'scroll'} from config.display_modes."""
        display_modes_config = self.config.get("display_modes", {})
        return {
            "live": display_modes_config.get("live_display_mode", "switch"),
            "recent": display_modes_config.get("recent_display_mode", "switch"),
            "upcoming": display_modes_config.get("upcoming_display_mode", "switch"),
        }

    # ------------------------------------------------------------------
    # Small helpers
    # ------------------------------------------------------------------
    def _get_manager(self, mode_type: str):
        """Return the manager for a mode type ('live'/'recent'/'upcoming')."""
        return self._managers.get(mode_type)

    def _mode_enabled(self, mode_type: str) -> bool:
        """Whether a given mode type is enabled in config."""
        display_modes = self.config.get("display_modes", {})
        return bool(display_modes.get(mode_type, True))

    def _get_display_mode(self, mode_type: str) -> str:
        """Return 'switch' or 'scroll' for a mode type."""
        return self._display_mode_settings.get(mode_type, "switch")

    def _should_use_scroll_mode(self, mode_type: str) -> bool:
        """True if this mode is enabled and configured for scroll display."""
        if not self._scroll_manager:
            return False
        return self._mode_enabled(mode_type) and self._get_display_mode(mode_type) == "scroll"

    def _has_any_scroll_mode(self) -> bool:
        return any(self._should_use_scroll_mode(mt) for mt in MODE_TYPES)

    def _get_available_modes(self) -> list:
        """Return the enabled display mode names (e.g. ['nrl_live', 'nrl_recent'])."""
        modes = []
        if self._mode_enabled("live"):
            modes.append(MODE_LIVE)
        if self._mode_enabled("recent"):
            modes.append(MODE_RECENT)
        if self._mode_enabled("upcoming"):
            modes.append(MODE_UPCOMING)
        if not modes:
            modes = [MODE_LIVE, MODE_RECENT, MODE_UPCOMING]
        return modes

    @staticmethod
    def _mode_type_from_name(display_mode: str) -> Optional[str]:
        """Extract 'live'/'recent'/'upcoming' from a mode name like 'nrl_live'."""
        if not display_mode:
            return None
        if display_mode.endswith("_live"):
            return "live"
        if display_mode.endswith("_recent"):
            return "recent"
        if display_mode.endswith("_upcoming"):
            return "upcoming"
        return None

    def _get_current_manager(self):
        """Get the manager for the current internal-cycle mode."""
        with self._config_lock:
            modes = self.modes
            mode_index = self.current_mode_index
        if not modes:
            return None
        current_mode = modes[mode_index % len(modes)]
        mode_type = self._mode_type_from_name(current_mode)
        if not mode_type:
            return None
        return self._get_manager(mode_type)

    def _manager_has_displayable_games(self, manager, mode_type: str) -> bool:
        """True if the manager currently has games to show for this mode.

        In switch mode an empty manager must be skipped: its display() clears the
        canvas when it has no games, which would blank the panel.
        """
        if mode_type == "live":
            return bool(getattr(manager, "live_games", None))
        return bool(getattr(manager, "games_list", None))

    # ------------------------------------------------------------------
    # Scroll collection
    # ------------------------------------------------------------------
    def _get_games_from_manager(self, manager, mode_type: str) -> List[Dict]:
        """Get games list from a manager based on mode type."""
        if mode_type == "live":
            return list(getattr(manager, "live_games", []) or [])
        elif mode_type == "recent":
            games = getattr(manager, "games_list", None)
            if games is None:
                games = getattr(manager, "recent_games", [])
            return list(games or [])
        elif mode_type == "upcoming":
            games = getattr(manager, "games_list", None)
            if games is None:
                games = getattr(manager, "upcoming_games", [])
            return list(games or [])
        return []

    def _collect_games_for_scroll(self, mode_type: Optional[str] = None,
                                  live_priority_active: bool = False):
        """Collect games from the enabled managers for scroll mode.

        Returns (games list, leagues list). Since NRL is a single league the
        leagues list is at most ['3'].
        """
        games: List[Dict] = []

        if mode_type is None:
            mode_types = list(MODE_TYPES)  # Vegas: all types
        else:
            mode_types = [mode_type]

        for mt in mode_types:
            if not self._mode_enabled(mt):
                continue
            if mode_type is not None and self._get_display_mode(mt) != "scroll":
                continue
            manager = self._get_manager(mt)
            if not manager:
                continue
            league_games = self._get_games_from_manager(manager, mt)
            for game in league_games:
                if "league" not in game:
                    game["league"] = LEAGUE_KEY
                if not isinstance(game.get("status"), dict):
                    game["status"] = {}
                if "state" not in game["status"]:
                    state_map = {"live": "in", "recent": "post", "upcoming": "pre"}
                    game["status"]["state"] = state_map.get(mt, "pre")
            games.extend(league_games)

        if live_priority_active:
            games = [g for g in games if g.get("is_live", False) and not g.get("is_final", False)]

        leagues = [LEAGUE_KEY] if games else []
        return games, leagues

    def _get_rankings_cache(self) -> Dict[str, int]:
        """Combined team rankings cache from all managers."""
        rankings: Dict[str, int] = {}
        for mt in MODE_TYPES:
            manager = self._get_manager(mt)
            if manager:
                manager_rankings = getattr(manager, "_team_rankings_cache", {})
                if manager_rankings:
                    rankings.update(manager_rankings)
        return rankings

    def _ensure_manager_updated(self, manager) -> None:
        if manager:
            try:
                manager.update()
            except Exception as e:
                self.logger.warning(f"Error updating manager: {e}")

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------
    def _check_favorite_teams(self) -> None:
        """
        Say why the league is showing nothing.

        A favourite that is not a real ESPN abbreviation matches no game, and so
        does a correct one before its season starts; both look like an empty
        screen. The check runs in the background, once per process, and never
        affects what is displayed.
        """
        try:
            checker = getattr(self, "_favorite_check", None)
            if checker is None:
                checker = FavoriteTeamCheck(self.logger, FAVORITE_CHECK_LEAGUES)
                self._favorite_check = checker
            with self._config_lock:
                managers = dict(self._managers)
            for mode in ("live", "recent", "upcoming"):
                favorites = getattr(managers.get(mode), "favorite_teams", None)
                if favorites:
                    checker.schedule(FAVORITE_CHECK_KEY, favorites)
                    break
        except Exception as exc:
            self.logger.debug("Favorite team check skipped: %s", exc)

    def update(self) -> None:
        """Update NRL game data using parallel manager updates."""
        if not self.is_enabled:
            return

        self._check_favorite_teams()

        with self._config_lock:
            managers_snapshot = dict(self._managers)

        update_tasks = []
        for mode_type in MODE_TYPES:
            manager = managers_snapshot.get(mode_type)
            if manager:
                update_tasks.append((f"NRL {mode_type.title()}", manager.update))

        if not update_tasks:
            return

        def run_update_with_error_handling(name: str, update_func):
            try:
                update_func()
            except Exception as e:
                self.logger.error(f"Error updating {name} manager: {e}", exc_info=True)

        started_threads = {}
        with self._config_lock:
            for name, update_func in update_tasks:
                existing_thread = self._active_update_threads.get(name)
                if existing_thread:
                    if existing_thread.is_alive():
                        self.logger.debug(f"Skipping update for {name} - previous thread still running")
                        continue
                    else:
                        del self._active_update_threads[name]

                thread = threading.Thread(
                    target=run_update_with_error_handling,
                    args=(name, update_func),
                    daemon=True,
                    name=f"Update-{name}",
                )
                thread.start()
                self._active_update_threads[name] = thread
                started_threads[name] = thread

        for name, thread in started_threads.items():
            thread.join(timeout=25.0)
            if thread.is_alive():
                self.logger.warning(f"Manager update thread {thread.name} did not complete within timeout")
            else:
                with self._config_lock:
                    if name in self._active_update_threads:
                        del self._active_update_threads[name]

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------
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
        # nrl_managers.py:237), so it moves every second too. The numeric `period`
        # is a separate field and is still compared, so a quarter/half change
        # still rebuilds -- only the clock inside the label goes stale between
        # rebuilds, which is the same trade as excluding `clock` itself.
        # football and hockey do not do this: their period_text is "Q4"/"P2".
        "period_text",
    })

    def _display_scroll_mode(self, display_mode: str, mode_type: str, force_clear: bool) -> bool:
        """Handle display for scroll mode."""
        if not self._scroll_manager:
            self.logger.warning("Scroll mode requested but scroll manager not available")
            return self._display_switch_mode(mode_type, force_clear)

        scroll_key = f"{display_mode}_{mode_type}"

        # A live card that changed since the strip was built has to rebuild
        # it now, not when the cycle ends -- see _live_scroll_needs_rebuild().
        # Refresh before fingerprinting, not after -- the rebuild
        # decision below is computed from exactly this data.
        self._refresh_live_scroll_managers()
        rebuild_for_live = self._live_scroll_needs_rebuild(scroll_key, mode_type)
        if rebuild_for_live or not self._scroll_prepared.get(scroll_key, False):
            self._ensure_manager_updated(self._get_manager(mode_type))

            live_priority_active = (
                mode_type == "live"
                and self.live_priority
                and self.has_live_content()
            )

            games, leagues = self._collect_games_for_scroll(mode_type, live_priority_active)
            if not games:
                self.logger.debug(f"No games to scroll for {display_mode}")
                self._scroll_prepared[scroll_key] = False
                self._scroll_active[scroll_key] = False
                return False

            rankings = self._get_rankings_cache()
            # What the managers hold right now -- this is what the render
            # below draws, so it is what the strip must be recorded as showing.
            pending_live_fingerprint = self._live_scroll_fingerprint(None)
            with self._preserving_scroll_position(mode_type, rebuild_for_live, scroll_key):
                success = self._scroll_manager.prepare_and_display(games, mode_type, leagues, rankings)
            if success:
                self._note_live_scroll_built(scroll_key, mode_type, pending_live_fingerprint)
                self._scroll_prepared[scroll_key] = True
                self._scroll_active[scroll_key] = True
                self.logger.info(f"[NRL Scroll] Started scrolling {len(games)} {mode_type} games")
            else:
                self._scroll_prepared[scroll_key] = False
                self._scroll_active[scroll_key] = False
                return False

        if self._scroll_active.get(scroll_key, False):
            displayed = self._scroll_manager.display_frame(mode_type)
            if displayed:
                if self._scroll_manager.is_complete(mode_type):
                    self.logger.info(f"[NRL Scroll] Cycle complete for {display_mode}")
                    self._scroll_prepared[scroll_key] = False
                    self._scroll_active[scroll_key] = False
                    self._dynamic_cycle_complete = True
                return True
            else:
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

    def _display_switch_mode(self, mode_type: str, force_clear: bool) -> bool:
        """Display a single game for a mode type via the manager (switch mode)."""

        # Refresh before reading the managers -- a stale manager can look
        # like it has nothing to show and be skipped entirely.
        self._refresh_switch_mode_managers(mode_type)
        manager = self._get_manager(mode_type)
        if not manager or not self._manager_has_displayable_games(manager, mode_type):
            return False

        self._current_display_mode_type = mode_type
        result = manager.display(force_clear)
        if result is not False:
            try:
                self._record_dynamic_progress(manager)
            except Exception as progress_err:
                self.logger.debug("Dynamic progress tracking failed: %s", progress_err)
            self._evaluate_dynamic_cycle_completion()
            return True if result is None else result
        return False

    def display(self, display_mode: str = None, force_clear: bool = False) -> bool:
        """Display NRL games with mode cycling."""
        if not self.is_enabled:
            return False

        try:
            # A goal/win celebration takes over the screen ahead of normal
            # rendering. It only fires for live requests (or internal cycling).
            is_live_request = display_mode is None or display_mode.endswith("_live")
            if is_live_request:
                live_manager = self._get_manager("live")
                if (
                    live_manager
                    and hasattr(live_manager, "has_active_celebration")
                    and live_manager.has_active_celebration()
                ):
                    self._current_display_mode_type = "live"
                    if live_manager.display(force_clear):
                        return True

            # Host-driven display: a specific mode name was requested.
            if display_mode:
                mode_type = self._mode_type_from_name(display_mode)
                if not mode_type:
                    self.logger.warning(f"Unknown display_mode: {display_mode}")
                    return False

                if self._should_use_scroll_mode(mode_type):
                    return self._display_scroll_mode(display_mode, mode_type, force_clear)

                return self._display_switch_mode(mode_type, force_clear)

            # Internal mode cycling (no display_mode provided).
            current_time = time.time()
            with self._config_lock:
                modes = self.modes
                mode_index = self.current_mode_index
            if not modes:
                return False
            mode_index = mode_index % len(modes)

            # Stay on / switch to live when there is live content.
            should_stay_on_live = False
            if self.has_live_content():
                current_mode = modes[mode_index]
                if current_mode and current_mode.endswith("_live"):
                    should_stay_on_live = True
                else:
                    for i, mode in enumerate(modes):
                        if mode.endswith("_live"):
                            mode_index = i
                            self.current_mode_index = i
                            force_clear = True
                            self.last_mode_switch = current_time
                            self.logger.info(f"Live content detected - switching to display mode: {mode}")
                            break

            if not should_stay_on_live and current_time - self.last_mode_switch >= self.display_duration:
                mode_index = (mode_index + 1) % len(modes)
                self.current_mode_index = mode_index
                self.last_mode_switch = current_time
                force_clear = True
                self.logger.info(f"Switching to display mode: {modes[mode_index]}")

            current_mode = modes[mode_index]
            mode_type = self._mode_type_from_name(current_mode)
            if mode_type and self._should_use_scroll_mode(mode_type):
                return self._display_scroll_mode(current_mode, mode_type, force_clear)

            if mode_type:
                self._current_display_mode_type = mode_type
            current_manager = self._get_current_manager()
            if current_manager:
                result = current_manager.display(force_clear)
                if result is not False:
                    try:
                        self._record_dynamic_progress(current_manager)
                    except Exception as progress_err:
                        self.logger.debug("Dynamic progress tracking failed: %s", progress_err)
                self._evaluate_dynamic_cycle_completion()
                return result
            else:
                self.logger.warning("No manager available for current mode")
                return False

        except Exception as e:
            self.logger.error(f"Error in display method: {e}", exc_info=True)
            return False

    # ------------------------------------------------------------------
    # Live priority / content
    # ------------------------------------------------------------------
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
        """Whether live games should interrupt the normal rotation."""
        return bool(self.is_enabled and self.live_priority)

    def _has_favorite_or_all_live(self, live_manager) -> bool:
        live_games = getattr(live_manager, "live_games", [])
        if not live_games:
            return False
        if getattr(live_manager, "show_all_live", False):
            return True
        favorite_teams = getattr(live_manager, "favorite_teams", [])
        if favorite_teams:
            # live_manager is a SportsLive (SportsCore) instance - reuse its
            # canonical ID-membership check instead of re-deriving it here.
            team_in = live_manager._team_in
            return any(
                team_in(game.get("home_id"), favorite_teams)
                or team_in(game.get("away_id"), favorite_teams)
                for game in live_games
            )
        return False

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
        """Check if there is live content worth showing."""
        if not self.is_enabled:
            return False

        live_manager = self._get_manager("live")
        if not live_manager:
            return False

        # An active celebration (notably a win, whose game has already left the
        # live list) must keep the live mode on screen.
        if (
            hasattr(live_manager, "has_active_celebration")
            and live_manager.has_active_celebration()
        ):
            return True

        return self._has_favorite_or_all_live(live_manager)

    def get_live_modes(self) -> list:
        """Return ['nrl_live'] when there is live content, else []."""
        if not self.is_enabled:
            return []
        live_manager = self._get_manager("live")
        if not live_manager:
            return []
        if (
            hasattr(live_manager, "has_active_celebration")
            and live_manager.has_active_celebration()
        ):
            return [MODE_LIVE]
        if self._has_favorite_or_all_live(live_manager):
            return [MODE_LIVE]
        return []

    # ------------------------------------------------------------------
    # Config change
    # ------------------------------------------------------------------
    def on_config_change(self, new_config: Dict[str, Any]) -> None:
        """Apply config changes at runtime without restart."""
        if BasePlugin:
            super().on_config_change(new_config)
        else:
            self.config = new_config or {}

        self.is_enabled = self.config.get("enabled", True)
        self.display_duration = float(self.config.get("display_duration", 30))
        self.game_display_duration = float(self.config.get("game_display_duration", 15))
        self.live_priority = bool(self.config.get("live_priority", True))

        with self._config_lock:
            for name, thread in list(self._active_update_threads.items()):
                if thread.is_alive():
                    thread.join(timeout=10.0)
            self._active_update_threads.clear()

            self._scroll_prepared.clear()
            self._scroll_active.clear()
            # New managers: force Vegas to rebuild its slate from them.
            self._vegas_signature = None

            self._initialize_managers()
            # Rebuild the scroll display manager so it sees the new config: it
            # and its cached card renderer hold the dict they were built with,
            # which on_config_change has just replaced, so the ticker and the
            # Vegas cards kept the old settings until a restart.
            self._scroll_manager = None
            if SCROLL_AVAILABLE and ScrollDisplayManager:
                try:
                    self._scroll_manager = ScrollDisplayManager(
                        self.display_manager, self.config, self.logger,
                        global_config=getattr(self, 'global_config', {}) or {})
                except Exception as e:
                    self.logger.warning(f"Could not rebuild scroll display manager: {e}")
                    self._scroll_manager = None
            self._display_mode_settings = self._parse_display_mode_settings()
            self.modes = self._get_available_modes()
            self.current_mode_index = 0
            self.enable_scrolling = self._has_any_scroll_mode()

        self.logger.info(f"NRL config updated at runtime - reinitialized. Modes: {self.modes}")

        # Favorites may have changed, so let the diagnostic report on them again.
        checker = getattr(self, "_favorite_check", None)
        if checker is not None:
            checker.reset()

    # ------------------------------------------------------------------
    # Info
    # ------------------------------------------------------------------
    def get_info(self) -> Dict[str, Any]:
        """Get plugin information."""
        try:
            current_manager = self._get_current_manager()
            with self._config_lock:
                modes = self.modes
                mode_index = self.current_mode_index
            current_mode = modes[mode_index % len(modes)] if modes else "none"

            info = {
                "plugin_id": self.plugin_id,
                "name": "NRL Scoreboard",
                "version": "1.0.0",
                "enabled": self.is_enabled,
                "display_size": f"{self.display_width}x{self.display_height}",
                "league": LEAGUE_NAME,
                "current_mode": current_mode,
                "available_modes": modes,
                "display_duration": self.display_duration,
                "game_display_duration": self.game_display_duration,
                "show_records": self.config.get("show_records", False),
                "show_ranking": self.config.get("show_ranking", False),
                # Schema default is true; reporting false here made get_info()
                # disagree with what the manager was actually given.
                "show_odds": self.config.get("show_odds", True),
            }

            if current_manager and hasattr(current_manager, "get_info"):
                try:
                    info["current_manager_info"] = current_manager.get_info()
                except Exception as e:
                    info["current_manager_info"] = f"Error getting manager info: {e}"

            return info
        except Exception as e:
            self.logger.error(f"Error getting plugin info: {e}")
            return {"plugin_id": self.plugin_id, "name": "NRL Scoreboard", "error": str(e)}

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
        """Check whether dynamic duration is enabled for the current context."""
        if not self.is_enabled:
            return False
        mode_type = self._current_display_mode_type
        if not mode_type:
            return False

        dynamic = self.config.get("dynamic_duration", {})
        mode_config = dynamic.get("modes", {}).get(mode_type, {})
        # The league switch turns every mode on; a mode switch turns on just
        # that mode. Both default to off and the core fills every default into
        # the config, so returning the mode switch whenever it was present (as
        # this did) meant the league switch was never read.
        if mode_config.get("enabled", False) or dynamic.get("enabled", False):
            return True
        return False

    def get_dynamic_duration_cap(self) -> Optional[float]:
        """Get the dynamic duration cap for the current context."""
        if not self.is_enabled:
            return None
        mode_type = self._current_display_mode_type
        if not mode_type:
            if BasePlugin:
                return super().get_dynamic_duration_cap()
            return None

        dynamic = self.config.get("dynamic_duration", {})
        mode_config = dynamic.get("modes", {}).get(mode_type, {})
        if "max_duration_seconds" in mode_config:
            try:
                cap = float(mode_config.get("max_duration_seconds"))
                if cap > 0:
                    return cap
            except (TypeError, ValueError):
                pass
        if "max_duration_seconds" in dynamic:
            try:
                cap = float(dynamic.get("max_duration_seconds"))
                if cap > 0:
                    return cap
            except (TypeError, ValueError):
                pass
        return None

    def get_dynamic_duration_floor(self) -> Optional[float]:
        """The dynamic duration floor for the current context.

        ``dynamic_duration.min_duration_seconds`` has always been in the schema
        beside its max, and only the max was read -- a mode could run shorter
        than the minimum asked for. Same ladder as the cap.
        """
        if not self.is_enabled:
            return None
        mode_type = self._current_display_mode_type
        if not mode_type:
            return None

        dynamic = self.config.get("dynamic_duration", {})
        mode_config = dynamic.get("modes", {}).get(mode_type, {})
        for source in (mode_config, dynamic):
            if "min_duration_seconds" in source:
                try:
                    floor = float(source.get("min_duration_seconds"))
                    if floor > 0:
                        return floor
                except (TypeError, ValueError):
                    pass
        return None

    def _get_game_duration(self, mode_type: str, manager=None) -> float:
        if manager:
            manager_duration = getattr(manager, "game_display_duration", None)
            if manager_duration is not None:
                return float(manager_duration)
        return 15.0

    def _get_mode_duration(self, mode_type: str) -> Optional[float]:
        mode_durations = self.config.get("mode_durations", {})
        key = f"{mode_type}_mode_duration"
        if key in mode_durations:
            value = mode_durations[key]
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    pass
        return None

    def get_cycle_duration(self, display_mode: str = None) -> Optional[float]:
        """Calculate the expected cycle duration for a display mode."""
        if not self.is_enabled or not display_mode:
            return None
        mode_type = self._mode_type_from_name(display_mode)
        if not mode_type:
            return None

        effective_duration = self._get_mode_duration(mode_type)
        if effective_duration is not None:
            if self._dynamic_feature_enabled():
                cap = self.get_dynamic_duration_cap()
                if cap is not None:
                    effective_duration = min(effective_duration, cap)
                # Floor last, so an explicit minimum wins over a smaller cap.
                floor = self.get_dynamic_duration_floor()
                if floor is not None:
                    effective_duration = max(effective_duration, floor)
            return effective_duration

        manager = self._get_manager(mode_type)
        total_duration = 0.0
        if manager:
            # This read a `games` attribute, which no manager has: always 0,
            # so dynamic duration never sized a slot from its games. afl
            # uses the same helper.
            games = self._get_games_from_manager(manager, mode_type)
            if games:
                total_duration = len(games) * self._get_game_duration(mode_type, manager)

        if total_duration == 0.0:
            return None

        if self._dynamic_feature_enabled():
            cap = self.get_dynamic_duration_cap()
            if cap is not None:
                total_duration = min(total_duration, cap)
            floor = self.get_dynamic_duration_floor()
            if floor is not None:
                total_duration = max(total_duration, floor)
        return total_duration

    def _record_dynamic_progress(self, current_manager) -> None:
        """Track progress through games for dynamic duration."""
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
            self._dynamic_managers_completed.add(manager_key)
            return

        current_index = getattr(current_manager, "current_game_index", None)
        if current_index is None:
            current_index = 0
        identifier = f"index-{current_index}"

        progress_set = self._dynamic_manager_progress.setdefault(manager_key, set())
        progress_set.add(identifier)
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
                mode_type = self._mode_type_from_name(mode_name)
                manager = self._get_manager(mode_type) if mode_type else None
                total_games = self._get_total_games_for_manager(manager)
                if total_games <= 1:
                    self._dynamic_managers_completed.add(manager_key)
                else:
                    self._dynamic_cycle_complete = False
                    return

        self._dynamic_cycle_complete = True

    # ------------------------------------------------------------------
    # Vegas scroll mode support
    # ------------------------------------------------------------------
    def get_vegas_content(self) -> Optional[Any]:
        """Get content for Vegas-style continuous scroll mode.

        Reads the dedicated 'mixed' display, not the union of every display:
        the union only got rebuilt when it was empty, so once any standalone
        mode had rendered, Vegas froze on that mode's games and never picked
        up a score change. Content is rebuilt when the slate's fingerprint
        changes. No update() here -- fetching is the update cycle's job, and
        network I/O on this path stalls the Vegas render loop. Same as
        baseball-scoreboard.
        """
        if not getattr(self, "_scroll_manager", None):
            return None

        try:
            games, leagues = self._collect_games_for_scroll(mode_type=None)
        except Exception:
            self.logger.exception("[NRL Vegas] Failed to collect games")
            return None
        if not games:
            self.logger.debug("[NRL Vegas] No games available")
            return None

        signature = self._fingerprint_games(games)
        images = self._scroll_manager.get_vegas_content_items_for(VEGAS_SCROLL_KEY)
        if not images or signature != getattr(self, "_vegas_signature", None):
            self.logger.info(
                "[NRL Vegas] Rebuilding scroll content (%s): %d game(s)",
                "no cached content" if not images else "game data changed", len(games))
            if self._build_vegas_scroll_content(games, leagues):
                self._vegas_signature = signature
            images = self._scroll_manager.get_vegas_content_items_for(VEGAS_SCROLL_KEY)

        if not images:
            return None
        self.logger.debug("[NRL Vegas] Returning %d image(s), %dpx total",
                          len(images), sum(img.width for img in images))
        return images

    def get_vegas_elements(self) -> Optional[List[Any]]:
        """Live Vegas cards: one per game, swapped in place when its game changes.

        The slate get_vegas_content() shows, plus games that have just gone
        final, so a card on its way across the panel turns to Final instead of
        keeping its last live score. A card is drawn again only when its
        game's data changed, the live clock included (core's
        build_vegas_elements). None -- no live cards in this core, or nothing
        to show -- and the ticker uses get_vegas_content() instead.
        """
        scroll_manager = getattr(self, "_scroll_manager", None)
        if sports_vegas is None or not hasattr(scroll_manager, "get_vegas_elements_for"):
            return None
        try:
            games, leagues = self.vegas_slate()
        except Exception:
            self.logger.exception("[NRL Vegas] Failed to collect games")
            return None
        if not games:
            return None
        return scroll_manager.get_vegas_elements_for(VEGAS_SCROLL_KEY, games, leagues, self._get_rankings_cache())

    def vegas_slate(self) -> Tuple[List[Dict], List[str]]:
        """The games the live Vegas cards show, and their leagues in order."""
        games, leagues = self._collect_games_for_scroll(mode_type=None)
        # A finished game stands in for its live card, so it follows the
        # collector's gate on the live mode: with live off there was no card.
        live_managers = ([(LEAGUE_KEY, self._get_manager("live"))]
                         if self._mode_enabled("live") else [])
        return sports_vegas.with_finished_games(
            games, leagues, sports_vegas.finished_games(live_managers))

    def get_vegas_display_mode(self) -> 'VegasDisplayMode':
        """Get the display mode for Vegas scroll integration."""
        if VegasDisplayMode:
            config_mode = self.config.get("vegas_mode")
            if config_mode:
                try:
                    return VegasDisplayMode(config_mode)
                except ValueError:
                    self.logger.warning(f"Invalid vegas_mode '{config_mode}' in config, using SCROLL")
            return VegasDisplayMode.SCROLL
        return "scroll"

    def _build_vegas_scroll_content(self, games: List[Dict], leagues: List[str]) -> bool:
        """Render the combined slate into the dedicated Vegas scroll display.

        prepare_content, not prepare_and_display: the latter also makes this
        the active scroll display, hijacking the standalone rotation's scroll.
        """
        game_type_counts = {"live": 0, "recent": 0, "upcoming": 0}
        for game in games:
            state = game.get("status", {}).get("state", "")
            if state == "in":
                game_type_counts["live"] += 1
            elif state == "post":
                game_type_counts["recent"] += 1
            elif state == "pre":
                game_type_counts["upcoming"] += 1

        success = self._scroll_manager.prepare_content(
            games, VEGAS_SCROLL_KEY, leagues, self._get_rankings_cache())
        if success:
            type_summary = ", ".join(
                f"{count} {gtype}" for gtype, count in game_type_counts.items() if count > 0
            )
            self.logger.info(f"[NRL Vegas] Generated scroll content: {len(games)} games ({type_summary})")
        else:
            self.logger.warning("[NRL Vegas] Failed to generate scroll content")
        return bool(success)

    def cleanup(self) -> None:
        """Clean up resources."""
        try:
            if hasattr(self, "_scroll_manager") and self._scroll_manager:
                if hasattr(self._scroll_manager, "cleanup"):
                    self._scroll_manager.cleanup()
                self._scroll_manager = None
            self.logger.info("NRL scoreboard plugin cleanup completed")
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")
