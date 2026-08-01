"""
AFL Scoreboard Plugin for LEDMatrix

Displays live, recent, and upcoming AFL (Australian Football League) games with
real-time scores and game status.

Display Modes:
- Switch Mode: Display one game at a time with timed transitions
- Scroll Mode: High-FPS horizontal scrolling of all games

AFL is a single-league sport (ESPN sport ``australian-football`` / league
``afl``), so this plugin is a flattened, single-league fork of the multi-league
soccer scoreboard: the three display modes are ``afl_live``, ``afl_recent`` and
``afl_upcoming``.
"""

import logging
import time
import threading
from typing import Dict, Any, Set, Optional, List

try:
    from src.plugin_system.base_plugin import BasePlugin, VegasDisplayMode
    from src.background_data_service import get_background_service
except ImportError:
    BasePlugin = None
    VegasDisplayMode = None
    get_background_service = None

# Odds manager: prefer the core-shipped version, fall back to the bundled copy.
# Kept outside the guard above so a missing odds module can never null BasePlugin.
try:
    from src.base_odds_manager import BaseOddsManager
except ImportError:
    try:
        from base_odds_manager import BaseOddsManager
    except ImportError:
        BaseOddsManager = None

# Import scroll display components
try:
    from scroll_display import ScrollDisplayManager
    SCROLL_AVAILABLE = True
except ImportError:
    ScrollDisplayManager = None
    SCROLL_AVAILABLE = False

# Import the manager factory
from afl_managers import create_afl_managers

from afl_timezone import resolve_timezone_name

logger = logging.getLogger(__name__)

# The single AFL "league" key and its display name.
AFL_LEAGUE_KEY = "afl"
AFL_LEAGUE_NAME = "AFL"

# The three display modes exposed by this plugin (also declared in manifest.json).
MODE_TYPES = ("live", "recent", "upcoming")
DISPLAY_MODES = tuple(f"afl_{m}" for m in MODE_TYPES)  # afl_live, afl_recent, afl_upcoming


def _mode_type_of(display_mode: str) -> Optional[str]:
    """Return 'live'/'recent'/'upcoming' for an afl_* display mode, else None."""
    if not display_mode:
        return None
    if display_mode.endswith("_live"):
        return "live"
    if display_mode.endswith("_recent"):
        return "recent"
    if display_mode.endswith("_upcoming"):
        return "upcoming"
    return None


class AflScoreboardPlugin(BasePlugin if BasePlugin else object):
    """
    AFL scoreboard plugin using manager classes.

    Delegates ESPN fetch + parsing to the AFL Live/Recent/Upcoming managers and
    handles mode cycling, dynamic duration, scroll vs switch display, live
    priority/celebration, and Vegas scroll integration.
    """

    def __init__(
        self,
        plugin_id: str,
        config: Dict[str, Any],
        display_manager,
        cache_manager,
        plugin_manager,
    ):
        """Initialize the AFL scoreboard plugin."""
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

        self.logger.debug(f"AFL plugin received config keys: {list(config.keys())}")

        # Global settings
        self.display_duration = float(config.get("display_duration", 30))
        self.game_display_duration = float(config.get("game_display_duration", 15))
        self.live_priority = bool(config.get("live_priority", False))

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

        # Managers keyed by mode type: {'live': mgr, 'recent': mgr, 'upcoming': mgr}
        self._managers: Dict[str, Any] = {}
        self._initialize_managers()

        # Per-mode display method ('switch' or 'scroll')
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
        self._scroll_active: Dict[str, bool] = {}   # {scroll_key: is_active}
        self._scroll_prepared: Dict[str, bool] = {}  # {scroll_key: is_prepared}

        # Track active update threads to prevent accumulation of stale threads
        self._active_update_threads: Dict[str, threading.Thread] = {}

        # Lock to protect shared mutable state during config reload
        self._config_lock = threading.Lock()

        # Enable high-FPS mode only when a mode actually uses scroll display.
        self.enable_scrolling = self._has_any_scroll_mode()
        if self.enable_scrolling:
            self.logger.info("High-FPS scrolling enabled for AFL scoreboard")

        # Mode cycling
        self.current_mode_index = 0
        # Seed with the current time, not 0 -- otherwise the first internal-
        # cycling display() call sees a huge elapsed time (current_time - 0),
        # immediately satisfies the switch threshold, and skips mode 0.
        self.last_mode_switch = time.time()
        self.modes = self._get_available_modes()

        self.logger.info(
            f"AFL scoreboard plugin initialized - {self.display_width}x{self.display_height}, "
            f"modes: {self.modes}"
        )

        # Dynamic duration tracking
        self._dynamic_cycle_seen_modes: Set[str] = set()
        self._dynamic_mode_to_manager_key: Dict[str, str] = {}
        self._dynamic_manager_progress: Dict[str, Set[str]] = {}
        self._dynamic_managers_completed: Set[str] = set()
        self._dynamic_cycle_complete = False

        # Current display context for granular dynamic duration
        self._current_display_league: Optional[str] = AFL_LEAGUE_KEY
        self._current_display_mode_type: Optional[str] = None

    # ------------------------------------------------------------------
    # Manager initialization / config adaptation
    # ------------------------------------------------------------------
    def _initialize_managers(self) -> None:
        """Create the AFL Live/Recent/Upcoming managers."""
        try:
            manager_config = self._adapt_config_for_manager()
            live, recent, upcoming = create_afl_managers(
                manager_config, self.display_manager, self.cache_manager
            )
            self._managers = {
                "live": live,
                "recent": recent,
                "upcoming": upcoming,
            }
            self.logger.info("AFL managers initialized")
        except Exception as e:
            self.logger.error(f"Error initializing managers: {e}", exc_info=True)
            self._managers = {}

    def _adapt_config_for_manager(self) -> Dict[str, Any]:
        """
        Adapt the flat plugin config to the manager-expected structure.

        The managers read their settings from ``config['afl_scoreboard']`` (see
        ``sports.py`` / ``afl_managers.py``); this maps the flat top-level plugin
        config into that nested shape.
        """
        cfg = self.config

        display_modes_config = cfg.get("display_modes", {})
        manager_display_modes = {
            "afl_live": display_modes_config.get("live", True),
            "afl_recent": display_modes_config.get("recent", True),
            "afl_upcoming": display_modes_config.get("upcoming", True),
        }

        filtering = cfg.get("filtering", {})

        manager_config = {
            "afl_scoreboard": {
                "enabled": cfg.get("enabled", True),
                "favorite_teams": cfg.get("favorite_teams", []),
                "exclude_teams": cfg.get("exclude_teams", []),
                "display_modes": manager_display_modes,
                "recent_games_to_show": cfg.get("recent_games_to_show", 5),
                "upcoming_games_to_show": cfg.get("upcoming_games_to_show", 10),
                "show_records": cfg.get("show_records", False),
                "show_ranking": cfg.get("show_rankings", cfg.get("show_ranking", False)),
                "show_odds": cfg.get("show_odds", False),
                "update_interval_seconds": cfg.get("update_interval_seconds", 300),
                "live_update_interval": cfg.get("live_update_interval", 30),
                "live_game_duration": cfg.get("live_game_duration", 20),
                "non_favorite_live_game_duration": cfg.get("non_favorite_live_game_duration", 0),
                "recent_game_duration": cfg.get("recent_game_duration", 15),
                "upcoming_game_duration": cfg.get("upcoming_game_duration", 15),
                "live_priority": cfg.get("live_priority", False),
                "show_favorite_teams_only": filtering.get(
                    "show_favorite_teams_only",
                    cfg.get("show_favorite_teams_only", False),
                ),
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

        customization_config = cfg.get("customization", {})

        manager_config.update({
            "timezone": timezone_str,
            "display": display_config,
            "customization": customization_config,
        })

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
    # Mode / manager helpers
    # ------------------------------------------------------------------
    def _get_manager(self, mode_type: str):
        """Get the manager for a mode type ('live'/'recent'/'upcoming')."""
        return self._managers.get(mode_type)

    def _get_display_mode(self, mode_type: str) -> str:
        """Return 'switch' or 'scroll' for the given mode type."""
        return self._display_mode_settings.get(mode_type, "switch")

    def _mode_enabled(self, mode_type: str) -> bool:
        """Whether this mode type is enabled in config.display_modes."""
        return bool(self.config.get("display_modes", {}).get(mode_type, True))

    def _has_any_scroll_mode(self) -> bool:
        """Return True if any enabled mode uses scroll display."""
        if not self._scroll_manager:
            return False
        for mode_type in MODE_TYPES:
            if self._get_display_mode(mode_type) == "scroll" and self._mode_enabled(mode_type):
                return True
        return False

    def _get_available_modes(self) -> list:
        """Get the list of enabled display modes (afl_live/recent/upcoming)."""
        modes = [f"afl_{m}" for m in MODE_TYPES if self._mode_enabled(m)]
        if not modes:
            modes = list(DISPLAY_MODES)
        return modes

    def _get_current_manager(self):
        """Get the manager for the current cycling mode."""
        with self._config_lock:
            modes = self.modes
            mode_index = self.current_mode_index
        if not modes:
            return None
        current_mode = modes[mode_index % len(modes)]
        mode_type = _mode_type_of(current_mode)
        if not mode_type:
            return None
        return self._get_manager(mode_type)

    def _manager_has_displayable_games(self, manager, mode_type: str) -> bool:
        """Return True if the manager currently has games for this mode.

        In switch mode an empty manager must be skipped: its ``display()`` clears
        the shared canvas when it has no games, which would blank the panel.
        """
        if manager is None:
            return False
        if mode_type == "live":
            return bool(getattr(manager, "live_games", None))
        return bool(getattr(manager, "games_list", None))

    def _get_games_from_manager(self, manager, mode_type: str) -> List[Dict]:
        """Get the games list from a manager based on mode type."""
        if manager is None:
            return []
        if mode_type == "live":
            return list(getattr(manager, "live_games", []) or [])
        games = getattr(manager, "games_list", None)
        if games is None:
            attr = "recent_games" if mode_type == "recent" else "upcoming_games"
            games = getattr(manager, attr, [])
        return list(games or [])

    def _get_rankings_cache(self) -> Dict[str, int]:
        """Combined team rankings cache from all managers."""
        rankings: Dict[str, int] = {}
        for manager in self._managers.values():
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
        self.live_priority = bool(self.config.get("live_priority", False))

        # Snapshot in-flight update threads under the lock (a fast,
        # non-blocking dict read), then join them WITHOUT holding the lock --
        # update()'s own thread-starting path (below) also needs
        # _config_lock, and sequential thread.join(timeout=10.0) calls while
        # holding it would block display()/update() for up to 10s per thread.
        # Deliberately NOT cleared here: update() checks
        # _active_update_threads[name].is_alive() to avoid starting a
        # duplicate thread for a manager whose update is still running --
        # clearing before the join loop completes would blind that check to
        # threads we're still in the middle of draining, on a call for a
        # manager that hasn't actually finished yet. Cleared below instead,
        # after every drained thread has been joined (or timed out).
        with self._config_lock:
            threads_to_drain = list(self._active_update_threads.items())

        for name, thread in threads_to_drain:
            if thread.is_alive():
                thread.join(timeout=10.0)

        with self._config_lock:
            self._active_update_threads.clear()
            self._scroll_prepared.clear()
            self._scroll_active.clear()

            self._initialize_managers()
            self._display_mode_settings = self._parse_display_mode_settings()
            self.modes = self._get_available_modes()
            self.current_mode_index = 0
            self.enable_scrolling = self._has_any_scroll_mode()

        self.logger.info("AFL config updated at runtime - reinitialized.")

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------
    def update(self) -> None:
        """Update AFL game data using parallel manager updates."""
        if not self.is_enabled:
            return

        with self._config_lock:
            managers_snapshot = dict(self._managers)

        update_tasks = []
        for mode_type in MODE_TYPES:
            manager = managers_snapshot.get(mode_type)
            if manager:
                update_tasks.append((f"AFL {mode_type.title()}", manager.update))

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
    @staticmethod
    def _normalize_games_for_scroll(games: List[Dict], mode_type: str) -> List[Dict]:
        """Ensure each game has a league and a status dict with a state,
        in place, so the scroll manager gets a consistent shape regardless
        of which mode's manager produced it."""
        state_map = {"live": "in", "recent": "post", "upcoming": "pre"}
        for game in games:
            game.setdefault("league", AFL_LEAGUE_KEY)
            if not isinstance(game.get("status"), dict):
                game["status"] = {}
            if "state" not in game["status"]:
                game["status"]["state"] = state_map.get(mode_type, "pre")
        return games

    def _display_scroll_mode(self, display_mode: str, mode_type: str, force_clear: bool) -> bool:
        """Handle display for scroll mode."""
        if not self._scroll_manager:
            self.logger.warning("Scroll mode requested but scroll manager not available")
            return self._display_switch_mode(mode_type, force_clear)

        scroll_key = f"{display_mode}_{mode_type}"

        if not self._scroll_prepared.get(scroll_key, False):
            manager = self._get_manager(mode_type)
            self._ensure_manager_updated(manager)

            live_priority_active = (
                mode_type == "live" and self.live_priority and self.has_live_content()
            )

            games = self._normalize_games_for_scroll(
                self._get_games_from_manager(manager, mode_type), mode_type
            )

            if live_priority_active:
                games = [g for g in games if g.get("is_live", False) and not g.get("is_final", False)]

            if not games:
                self.logger.debug(f"No games to scroll for {display_mode}")
                self._scroll_prepared[scroll_key] = False
                self._scroll_active[scroll_key] = False
                return False

            rankings = self._get_rankings_cache()
            success = self._scroll_manager.prepare_and_display(
                games, mode_type, [AFL_LEAGUE_KEY], rankings
            )
            if success:
                self._scroll_prepared[scroll_key] = True
                self._scroll_active[scroll_key] = True
                self.logger.info(f"[AFL Scroll] Started scrolling {len(games)} {mode_type} games")
            else:
                self._scroll_prepared[scroll_key] = False
                self._scroll_active[scroll_key] = False
                return False

        if self._scroll_active.get(scroll_key, False):
            displayed = self._scroll_manager.display_frame(mode_type)
            if displayed:
                if self._scroll_manager.is_complete(mode_type):
                    self.logger.info(f"[AFL Scroll] Cycle complete for {display_mode}")
                    self._scroll_prepared[scroll_key] = False
                    self._scroll_active[scroll_key] = False
                    self._dynamic_cycle_complete = True
                return True
            self._scroll_active[scroll_key] = False
            return False

        return False

    def _display_switch_mode(self, mode_type: str, force_clear: bool) -> bool:
        """Handle display for switch mode."""
        manager = self._get_manager(mode_type)
        if not manager or not self._manager_has_displayable_games(manager, mode_type):
            return False

        self._current_display_league = AFL_LEAGUE_KEY
        self._current_display_mode_type = mode_type

        result = manager.display(force_clear)
        if result is not False:
            try:
                self._record_dynamic_progress(manager)
            except Exception as progress_err:
                self.logger.debug("Dynamic progress tracking failed: %s", progress_err)
            self._evaluate_dynamic_cycle_completion()
        return result if result is not None else True

    def display(self, display_mode: str = None, force_clear: bool = False) -> bool:
        """Display AFL games with mode cycling."""
        if not self.is_enabled:
            return False

        try:
            # A goal/win celebration takes over the screen for live modes.
            is_live_request = display_mode is None or display_mode.endswith("_live")
            if is_live_request:
                live_manager = self._get_manager("live")
                if (
                    live_manager
                    and hasattr(live_manager, "has_active_celebration")
                    and live_manager.has_active_celebration()
                ):
                    self._current_display_league = AFL_LEAGUE_KEY
                    self._current_display_mode_type = "live"
                    if live_manager.display(force_clear):
                        return True

            # Explicit display mode requested by the host.
            if display_mode:
                mode_type = _mode_type_of(display_mode)
                if not mode_type:
                    self.logger.warning(f"Unknown display_mode: {display_mode}")
                    return False

                if self._get_display_mode(mode_type) == "scroll":
                    return self._display_scroll_mode(display_mode, mode_type, force_clear)
                return self._display_switch_mode(mode_type, force_clear)

            # Internal mode cycling (no explicit mode).
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
            mode_type = _mode_type_of(current_mode)
            if not mode_type:
                return False

            if self._get_display_mode(mode_type) == "scroll":
                return self._display_scroll_mode(current_mode, mode_type, force_clear)
            return self._display_switch_mode(mode_type, force_clear)

        except Exception as e:
            self.logger.error(f"Error in display method: {e}", exc_info=True)
            return False

    # ------------------------------------------------------------------
    # Live priority / content
    # ------------------------------------------------------------------
    def has_live_priority(self) -> bool:
        """Whether live priority is enabled."""
        return bool(self.is_enabled and self.live_priority)

    def _live_manager_has_favorite_live(self, live_manager) -> bool:
        live_games = getattr(live_manager, "live_games", [])
        if not live_games:
            return False
        show_all_live = getattr(live_manager, "show_all_live", False)
        if show_all_live:
            return True
        favorite_teams = getattr(live_manager, "favorite_teams", [])
        if favorite_teams:
            return any(
                game.get("home_abbr") in favorite_teams or game.get("away_abbr") in favorite_teams
                for game in live_games
            )
        return False

    def has_live_content(self) -> bool:
        """Whether there is live content worth showing."""
        if not self.is_enabled:
            return False
        live_manager = self._get_manager("live")
        if not live_manager:
            return False
        if (
            hasattr(live_manager, "has_active_celebration")
            and live_manager.has_active_celebration()
        ):
            return True
        return self._live_manager_has_favorite_live(live_manager)

    def get_live_modes(self) -> list:
        """Return ['afl_live'] when there is live content, else []."""
        if not self.is_enabled:
            return []
        live_manager = self._get_manager("live")
        if not live_manager:
            return []
        if (
            hasattr(live_manager, "has_active_celebration")
            and live_manager.has_active_celebration()
        ):
            return ["afl_live"]
        if self._live_manager_has_favorite_live(live_manager):
            return ["afl_live"]
        return []

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
                "name": "AFL Scoreboard",
                "version": "1.0.0",
                "enabled": self.is_enabled,
                "display_size": f"{self.display_width}x{self.display_height}",
                "league": AFL_LEAGUE_NAME,
                "current_mode": current_mode,
                "available_modes": modes,
                "display_duration": self.display_duration,
                "live_priority": self.live_priority,
                "show_records": self.config.get("show_records", False),
                "show_odds": self.config.get("show_odds", False),
            }
            if current_manager and hasattr(current_manager, "get_info"):
                try:
                    info["current_manager_info"] = current_manager.get_info()
                except Exception as e:
                    info["current_manager_info"] = f"Error getting manager info: {e}"
            return info
        except Exception as e:
            self.logger.error(f"Error getting plugin info: {e}")
            return {"plugin_id": self.plugin_id, "name": "AFL Scoreboard", "error": str(e)}

    # ------------------------------------------------------------------
    # Dynamic duration hooks
    # ------------------------------------------------------------------
    def reset_cycle_state(self) -> None:
        if BasePlugin:
            super().reset_cycle_state()
        self._dynamic_cycle_seen_modes.clear()
        self._dynamic_mode_to_manager_key.clear()
        self._dynamic_manager_progress.clear()
        self._dynamic_managers_completed.clear()
        self._dynamic_cycle_complete = False

    def is_cycle_complete(self) -> bool:
        if not self._dynamic_feature_enabled():
            return True
        self._evaluate_dynamic_cycle_completion()
        return self._dynamic_cycle_complete

    def _dynamic_feature_enabled(self) -> bool:
        if not self.is_enabled:
            return False
        return self.supports_dynamic_duration()

    def supports_dynamic_duration(self, mode_type: Optional[str] = None) -> bool:
        """Whether dynamic duration is enabled for the given (or current) display context."""
        if mode_type is None:
            mode_type = self._current_display_mode_type
        if not self.is_enabled or not mode_type:
            return False
        dynamic = self.config.get("dynamic_duration", {})
        mode_config = dynamic.get("modes", {}).get(mode_type, {})
        if "enabled" in mode_config:
            return bool(mode_config.get("enabled", False))
        if "enabled" in dynamic:
            return bool(dynamic.get("enabled", False))
        return False

    def get_dynamic_duration_cap(self, mode_type: Optional[str] = None) -> Optional[float]:
        """Dynamic duration cap for the given (or current) display context."""
        if not self.is_enabled:
            return None
        if mode_type is None:
            mode_type = self._current_display_mode_type
        if not mode_type:
            if BasePlugin:
                return super().get_dynamic_duration_cap()
            return None
        dynamic = self.config.get("dynamic_duration", {})
        mode_config = dynamic.get("modes", {}).get(mode_type, {})
        for source in (mode_config, dynamic):
            if "max_duration_seconds" in source:
                try:
                    cap = float(source.get("max_duration_seconds"))
                    if cap > 0:
                        return cap
                except (TypeError, ValueError):
                    pass
        return None

    def _get_mode_duration(self, mode_type: str) -> Optional[float]:
        """Fixed total duration for a mode from config.mode_durations, if set."""
        mode_durations = self.config.get("mode_durations", {})
        value = mode_durations.get(f"{mode_type}_mode_duration")
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                pass
        return None

    def _get_game_duration(self, mode_type: str, manager=None) -> float:
        if manager is not None:
            manager_duration = getattr(manager, "game_display_duration", None)
            if manager_duration is not None:
                return float(manager_duration)
        return float(self.config.get(f"{mode_type}_game_duration", 15))

    def get_cycle_duration(self, display_mode: str = None) -> Optional[float]:
        """Expected cycle duration for a display mode."""
        if not self.is_enabled or not display_mode:
            return None
        mode_type = _mode_type_of(display_mode)
        if not mode_type:
            return None

        effective_duration = self._get_mode_duration(mode_type)
        if effective_duration is not None:
            if self.is_enabled and self.supports_dynamic_duration(mode_type):
                cap = self.get_dynamic_duration_cap(mode_type)
                if cap is not None:
                    effective_duration = min(effective_duration, cap)
            return effective_duration

        manager = self._get_manager(mode_type)
        games = self._get_games_from_manager(manager, mode_type)
        if not games:
            return None
        total_duration = len(games) * self._get_game_duration(mode_type, manager)

        if self.is_enabled and self.supports_dynamic_duration(mode_type):
            cap = self.get_dynamic_duration_cap(mode_type)
            if cap is not None:
                total_duration = min(total_duration, cap)
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
        progress_set = self._dynamic_manager_progress.setdefault(manager_key, set())
        progress_set.add(f"index-{current_index}")
        valid_identifiers = {f"index-{idx}" for idx in range(total_games)}
        progress_set.intersection_update(valid_identifiers)
        if len(progress_set) >= total_games:
            self._dynamic_managers_completed.add(manager_key)

    def _evaluate_dynamic_cycle_completion(self) -> None:
        if not self._dynamic_feature_enabled():
            self._dynamic_cycle_complete = True
            return
        with self._config_lock:
            modes = self.modes
        if not modes:
            self._dynamic_cycle_complete = True
            return

        for mode_name in modes:
            if mode_name not in self._dynamic_cycle_seen_modes:
                self._dynamic_cycle_complete = False
                return
            manager_key = self._dynamic_mode_to_manager_key.get(mode_name)
            if not manager_key:
                self._dynamic_cycle_complete = False
                return
            if manager_key not in self._dynamic_managers_completed:
                mode_type = _mode_type_of(mode_name)
                manager = self._get_manager(mode_type) if mode_type else None
                if self._get_total_games_for_manager(manager) <= 1:
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

    # ------------------------------------------------------------------
    # Vegas scroll mode support
    # ------------------------------------------------------------------
    def get_vegas_content(self) -> Optional[Any]:
        """Return cached scroll image(s) for Vegas continuous scroll mode."""
        if not getattr(self, "_scroll_manager", None):
            return None

        images = self._scroll_manager.get_all_vegas_content_items()
        if not images:
            self.logger.info("[AFL Vegas] Triggering scroll content generation")
            self._ensure_scroll_content_for_vegas()
            images = self._scroll_manager.get_all_vegas_content_items()

        if images:
            total_width = sum(img.width for img in images)
            self.logger.info("[AFL Vegas] Returning %d image(s), %dpx total", len(images), total_width)
            return images
        return None

    def get_vegas_content_type(self) -> str:
        """Plugin provides multiple scrollable items (games)."""
        return 'multi'

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

    def _ensure_scroll_content_for_vegas(self) -> None:
        """Generate scroll content across all mode types for Vegas mode."""
        if not getattr(self, "_scroll_manager", None):
            self.logger.debug("[AFL Vegas] No scroll manager available")
            return

        games: List[Dict] = []
        for mode_type in MODE_TYPES:
            manager = self._get_manager(mode_type)
            mode_games = self._normalize_games_for_scroll(
                self._get_games_from_manager(manager, mode_type), mode_type
            )
            games.extend(mode_games)

        if not games:
            self.logger.debug("[AFL Vegas] No games available")
            return

        success = self._scroll_manager.prepare_and_display(games, 'mixed', [AFL_LEAGUE_KEY], None)
        if success:
            self.logger.info(f"[AFL Vegas] Generated scroll content: {len(games)} games")
        else:
            self.logger.warning("[AFL Vegas] Failed to generate scroll content")

    def cleanup(self) -> None:
        """Clean up resources."""
        try:
            if hasattr(self, "_scroll_manager") and self._scroll_manager:
                if hasattr(self._scroll_manager, "cleanup"):
                    self._scroll_manager.cleanup()
                self._scroll_manager = None
            self.logger.info("AFL scoreboard plugin cleanup completed")
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")
