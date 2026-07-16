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
from typing import Dict, Any, Set, Optional, List

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

# Import the NRL manager factory
from nrl_managers import create_nrl_managers, LEAGUE_NAMES, NRL_LEAGUE_SLUG

logger = logging.getLogger(__name__)

# NRL is a single league. Its ESPN league slug is "3" (see nrl_managers.py), but
# the plugin's display modes / config are keyed with the friendly "nrl" name.
LEAGUE_KEY = NRL_LEAGUE_SLUG  # "3" — ESPN's NRL slug, do not change to "nrl"
LEAGUE_NAME = LEAGUE_NAMES.get(NRL_LEAGUE_SLUG, "NRL")

# Registered display-mode names (must match manifest.json display_modes).
MODE_LIVE = "nrl_live"
MODE_RECENT = "nrl_recent"
MODE_UPCOMING = "nrl_upcoming"
MODE_TYPES = ("live", "recent", "upcoming")


class NrlScoreboardPlugin(BasePlugin if BasePlugin else object):
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
                self.background_service = get_background_service(
                    self.cache_manager, max_workers=1
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
                    self.display_manager, self.config, self.logger
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
        display_options = cfg.get("display_options", {})

        manager_config = {
            "nrl_scoreboard": {
                "enabled": cfg.get("enabled", False),
                "favorite_teams": cfg.get("favorite_teams", []),
                "exclude_teams": cfg.get("exclude_teams", []),
                "display_modes": manager_display_modes,
                "recent_games_to_show": game_limits.get(
                    "recent_games_to_show", cfg.get("recent_games_to_show", 5)
                ),
                "upcoming_games_to_show": game_limits.get(
                    "upcoming_games_to_show", cfg.get("upcoming_games_to_show", 10)
                ),
                "show_records": display_options.get(
                    "show_records", cfg.get("show_records", False)
                ),
                "show_ranking": display_options.get(
                    "show_ranking", cfg.get("show_ranking", False)
                ),
                "show_odds": display_options.get(
                    "show_odds", cfg.get("show_odds", False)
                ),
                "update_interval_seconds": cfg.get("update_interval_seconds", 300),
                "live_update_interval": cfg.get("live_update_interval", 30),
                "live_game_duration": cfg.get("live_game_duration", 20),
                "non_favorite_live_game_duration": cfg.get(
                    "non_favorite_live_game_duration", 0
                ),
                "recent_game_duration": cfg.get("recent_game_duration", 15),
                "upcoming_game_duration": cfg.get("upcoming_game_duration", 15),
                "live_priority": cfg.get("live_priority", True),
                "celebration_enabled": cfg.get("celebration_enabled", True),
                "celebration_duration": cfg.get("celebration_duration", 8),
                "celebrate_opponent_goals": cfg.get("celebrate_opponent_goals", False),
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

        # Global config - timezone from cache_manager's config_manager if available
        timezone_str = cfg.get("timezone")
        if not timezone_str and hasattr(self.cache_manager, 'config_manager'):
            timezone_str = self.cache_manager.config_manager.get_timezone()
        if not timezone_str:
            timezone_str = "UTC"

        display_config = cfg.get("display", {})
        if not display_config and hasattr(self.cache_manager, 'config_manager'):
            display_config = self.cache_manager.config_manager.get_display_config()

        manager_config.update({
            "timezone": timezone_str,
            "display": display_config,
            "customization": cfg.get("customization", {}),
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
    def update(self) -> None:
        """Update NRL game data using parallel manager updates."""
        if not self.is_enabled:
            return

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
    def _display_scroll_mode(self, display_mode: str, mode_type: str, force_clear: bool) -> bool:
        """Handle display for scroll mode."""
        if not self._scroll_manager:
            self.logger.warning("Scroll mode requested but scroll manager not available")
            return self._display_switch_mode(mode_type, force_clear)

        scroll_key = f"{display_mode}_{mode_type}"

        if not self._scroll_prepared.get(scroll_key, False):
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
            success = self._scroll_manager.prepare_and_display(games, mode_type, leagues, rankings)
            if success:
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

    def _display_switch_mode(self, mode_type: str, force_clear: bool) -> bool:
        """Display a single game for a mode type via the manager (switch mode)."""
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

            self._initialize_managers()
            self._display_mode_settings = self._parse_display_mode_settings()
            self.modes = self._get_available_modes()
            self.current_mode_index = 0
            self.enable_scrolling = self._has_any_scroll_mode()

        self.logger.info(f"NRL config updated at runtime - reinitialized. Modes: {self.modes}")

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

    def _dynamic_feature_enabled(self) -> bool:
        if not self.is_enabled:
            return False
        return self.supports_dynamic_duration()

    def supports_dynamic_duration(self) -> bool:
        """Check whether dynamic duration is enabled for the current context."""
        if not self.is_enabled:
            return False
        mode_type = self._current_display_mode_type
        if not mode_type:
            return False

        dynamic = self.config.get("dynamic_duration", {})
        mode_config = dynamic.get("modes", {}).get(mode_type, {})
        if "enabled" in mode_config:
            return bool(mode_config.get("enabled", False))
        if "enabled" in dynamic:
            return bool(dynamic.get("enabled", False))
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
            return effective_duration

        manager = self._get_manager(mode_type)
        total_duration = 0.0
        if manager:
            games = getattr(manager, "games", [])
            if games:
                total_duration = len(games) * self._get_game_duration(mode_type, manager)

        if total_duration == 0.0:
            return None

        if self._dynamic_feature_enabled():
            cap = self.get_dynamic_duration_cap()
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
        """Get content for Vegas-style continuous scroll mode."""
        if not getattr(self, "_scroll_manager", None):
            return None

        images = self._scroll_manager.get_all_vegas_content_items()
        if not images:
            self.logger.info("[NRL Vegas] Triggering scroll content generation")
            self._ensure_scroll_content_for_vegas()
            images = self._scroll_manager.get_all_vegas_content_items()

        if images:
            total_width = sum(img.width for img in images)
            self.logger.info("[NRL Vegas] Returning %d image(s), %dpx total", len(images), total_width)
            return images
        return None

    def get_vegas_content_type(self) -> str:
        """This plugin provides multiple scrollable items (games)."""
        return "multi"

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
        """Ensure scroll content is generated for Vegas mode."""
        if not getattr(self, "_scroll_manager", None):
            self.logger.debug("[NRL Vegas] No scroll manager available")
            return

        games, leagues = self._collect_games_for_scroll(mode_type=None)
        if not games:
            self.logger.debug("[NRL Vegas] No games available")
            return

        game_type_counts = {"live": 0, "recent": 0, "upcoming": 0}
        for game in games:
            state = game.get("status", {}).get("state", "")
            if state == "in":
                game_type_counts["live"] += 1
            elif state == "post":
                game_type_counts["recent"] += 1
            elif state == "pre":
                game_type_counts["upcoming"] += 1

        success = self._scroll_manager.prepare_and_display(games, "mixed", leagues, None)
        if success:
            type_summary = ", ".join(
                f"{count} {gtype}" for gtype, count in game_type_counts.items() if count > 0
            )
            self.logger.info(f"[NRL Vegas] Generated scroll content: {len(games)} games ({type_summary})")
        else:
            self.logger.warning("[NRL Vegas] Failed to generate scroll content")

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
