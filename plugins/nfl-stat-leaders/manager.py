"""NFL Stat Leaders -- a scrolling ticker of the league's statistical leaders.

Fantasy-relevant leaderboards (passing, rushing and receiving yards and
touchdowns, plus receptions, sacks, interceptions, tackles and passer
rating) drawn as one continuous strip with club crests and colours.

Data comes from ESPN's public leaders feed, which needs no API key, so the
plugin reads no secrets and writes none.

Division of labour, per the project's rules: ``update()`` does every network
call and every cache write; ``display()`` only draws, from data already in
memory.
"""

import time
from typing import Any, Dict, List, Optional

from src.plugin_system.base_plugin import BasePlugin

try:
    # Shared scroll pacing: resolves the speed from the config, snaps it to
    # one the panel can move in whole pixels, and reports the frame hold
    # that keeps slow speeds crisp. Core docs: SCROLL_PERFORMANCE.md
    from src.common import scroll_config as _scroll_config
except ImportError:  # pragma: no cover - core predates the shared helper
    _scroll_config = None

from src.common.scroll_helper import ScrollHelper

from nfl_stat_categories import enabled_categories
from nfl_stat_fetcher import (
    SEASON_TYPE_LABELS,
    SEASON_TYPE_POSTSEASON,
    SEASON_TYPE_REGULAR,
    StatFetcher,
)
from nfl_stat_renderer import TickerRenderer


class NFLStatLeadersPlugin(BasePlugin):
    """Scrolling NFL statistical leaderboards."""

    #: How soon ``update()`` is asked for again while there is nothing to
    #: show. ``display()`` never fetches, so this is the only retry after a
    #: failed fetch; without it an ESPN outage at startup would leave the
    #: fallback up for a whole update_interval.
    NO_DATA_RETRY_SECONDS = 300

    #: The core's own cap when ``display.dynamic_duration.max_duration_seconds``
    #: is unset (DEFAULT_DYNAMIC_DURATION_CAP in src/display_controller.py).
    CORE_DEFAULT_DYNAMIC_CAP = 180.0

    def __init__(self, plugin_id: str, config: Dict[str, Any],
                 display_manager, cache_manager, plugin_manager):
        super().__init__(plugin_id, config, display_manager, cache_manager,
                         plugin_manager)

        # Read dimensions from the display manager itself: `matrix` is None
        # when hardware init failed, and these properties fall back to the
        # canvas size.
        self.display_width = display_manager.width
        self.display_height = display_manager.height

        self._load_config(config)

        self.fetcher = StatFetcher(cache_manager, self.logger, self.request_timeout)
        self.renderer = TickerRenderer(self.display_height, self.logger,
                                       self.appearance)

        self.scroll_helper = ScrollHelper(self.display_width, self.display_height,
                                          self.logger)
        self._configure_scroll()

        self.boards: List[Dict[str, Any]] = []
        self.resolved_season: Optional[int] = None
        self.last_update = 0.0
        self._cycle_complete = False
        self._last_warning = 0.0

        # Tells the core's display controller to drive this plugin at its
        # high-FPS rate; at one frame per second a scroll is a slideshow.
        self.enable_scrolling = True

        self.logger.info(
            "NFL Stat Leaders initialised: %sx%s panel, %s categories, top %s",
            self.display_width, self.display_height,
            len(self.categories), self.players_per_category,
        )
        self.update(force=True)

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def _load_config(self, config: Dict[str, Any]) -> None:
        """Read every config-derived setting.

        Called from ``__init__`` and ``on_config_change`` so a save in the
        web UI takes effect exactly the same way a restart would.
        """
        self.global_config = config.get("global", {}) or {}
        self.appearance = self.global_config.get("appearance", {}) or {}

        self.update_interval = _safe_int(
            config.get("update_interval", 3600), 3600, 900, 86400)
        self.display_duration = _safe_int(
            self.global_config.get("display_duration", 30), 30, 10, 300)
        self.request_timeout = _safe_int(
            self.global_config.get("request_timeout", 30), 30, 5, 120)

        self.categories = enabled_categories(config.get("categories"))
        self.players_per_category = _safe_int(
            config.get("players_per_category", 5), 5, 1, 10)
        self.season = _safe_int(config.get("season", 0), 0, 0, 2100)
        self.season_type_setting = str(config.get("season_type", "regular"))

        scroll_mode = self.global_config.get("scroll_mode", "one_shot")
        self.loop = scroll_mode == "continuous"

        dynamic = self.global_config.get("dynamic_duration") or {}
        self.dynamic_duration_enabled = bool(dynamic.get("enabled", True))
        self.min_duration = _safe_int(
            dynamic.get("min_duration_seconds", 45), 45, 10, 300)
        self.max_duration = _safe_int(
            dynamic.get("max_duration_seconds", 600), 600, 30, 1200)
        self.duration_buffer = _safe_float(
            dynamic.get("buffer_ratio", 0.1), 0.1, 0.01, 1.0)
        self.dynamic_duration_cap = _safe_int(
            dynamic.get("controller_cap_seconds", 600), 600, 60, 1800)

    @property
    def season_type(self) -> int:
        """ESPN's season-type code for the configured setting."""
        if self.season_type_setting == "postseason":
            return SEASON_TYPE_POSTSEASON
        return SEASON_TYPE_REGULAR

    def _configure_scroll(self) -> None:
        """Resolve scroll pacing through the core's shared resolver.

        The resolver reads ``global.display_options.scroll_speed`` (pixels
        per step) and ``scroll_delay`` (seconds per step), snaps the result
        to a speed the panel can draw in whole pixels, and applies it.
        Nothing writes the helper's speed afterwards; that would override
        the resolved pacing.
        """
        if _scroll_config is not None:
            self._scroll_settings = _scroll_config.configure(
                self.scroll_helper,
                plugin_config=self.config,
                global_config=self.global_config,
                display_manager=self.display_manager,
                plugin_logger=self.logger,
            )
        else:  # pragma: no cover - unreachable on the declared 3.4.0 floor
            self._scroll_settings = None

        self.scroll_helper.set_dynamic_duration_settings(
            enabled=self.dynamic_duration_enabled,
            min_duration=self.min_duration,
            max_duration=self.max_duration,
            buffer=self.duration_buffer,
        )

    def _scroll_frame_hold(self) -> int:
        """Refreshes to hold each frame for, from the resolved settings."""
        settings = getattr(self, "_scroll_settings", None)
        return getattr(settings, "frame_hold", 1) if settings else 1

    def on_config_change(self, new_config: Dict[str, Any]) -> None:
        """Apply a web-UI save without a restart."""
        super().on_config_change(new_config)
        self.config = new_config
        self._load_config(new_config)
        self.fetcher.request_timeout = self.request_timeout
        self.renderer = TickerRenderer(self.display_height, self.logger,
                                       self.appearance)
        self._configure_scroll()
        # Which categories and how many players are baked into the strip, so
        # it has to be rebuilt; the next display() does that.
        self.scroll_helper.clear_cache()
        self._cycle_complete = False
        self.update(force=True)

    def get_update_interval(self) -> Optional[float]:
        """Seconds between ``update()`` calls.

        The manifest's value is only a default and core prefers it over the
        config, so without this hook a user's shorter interval is ignored.
        Attribute reads only: core calls this on every scheduling tick.
        """
        interval = float(self.update_interval)
        if not self.boards:
            return min(interval, float(self.NO_DATA_RETRY_SECONDS))
        return interval

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def update(self, force: bool = False) -> None:
        """Refresh the leaderboards. The only place this plugin uses the network."""
        now = time.time()
        if (not force and self.boards
                and now - self.last_update < self.update_interval):
            return

        if not self.categories:
            self._warn_occasionally(
                "No stat categories are enabled; nothing to show")
            return

        try:
            season = self.fetcher.resolve_season(
                self.season, self.season_type, self.update_interval)
            boards = self.fetcher.fetch_boards(
                categories=self.categories,
                season=season,
                season_type=self.season_type,
                players_per_category=self.players_per_category,
                max_age=self.update_interval,
            )
        except Exception as exc:  # noqa: BLE001 - a bad payload must not take
            # the display loop down with it, and the harness fails a plugin
            # whose update() raises anything but a connectivity error.
            self.logger.error("Could not update NFL stat leaders: %s", exc,
                              exc_info=True)
            return

        self.last_update = now
        if not boards:
            self._warn_occasionally(
                "ESPN returned no leaders for the enabled categories")
            return

        self.boards = boards
        self.resolved_season = season
        # The strip is built from this data, so the cached one is now stale.
        self.scroll_helper.clear_cache()
        self._cycle_complete = False
        self.logger.info(
            "Updated NFL stat leaders: %s boards, %s players, season %s %s",
            len(boards), sum(len(b["leaders"]) for b in boards), season,
            SEASON_TYPE_LABELS.get(self.season_type, ""),
        )

    def _warn_occasionally(self, message: str) -> None:
        """Log at most once every five minutes, so a persistent problem does
        not fill the log at the update cadence."""
        now = time.time()
        if now - self._last_warning >= 300:
            self.logger.warning(message)
            self._last_warning = now

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def display(self, force_clear: bool = False) -> None:
        """Draw one frame of the scrolling ticker."""
        if not self.enabled:
            return

        if not self.boards:
            # Never fetch from here: display() runs on the render loop and a
            # request would block it. update() retries on the core's
            # schedule (get_update_interval).
            self.display_manager.set_scrolling_state(False)
            self._draw_placeholder()
            return

        if not self.scroll_helper.cached_image or force_clear:
            if not self._build_strip():
                self.display_manager.set_scrolling_state(False)
                self._draw_placeholder()
                return

        if force_clear:
            self.scroll_helper.reset_scroll()
            self._cycle_complete = False

        # A completed one-shot cycle holds its last frame. The scrolling flag
        # stays set: releasing it lets the display manager's dirty tracking
        # skip the identical frame, and with it the vsync wait that paces the
        # controller loop.
        if not self.loop and self._cycle_complete:
            self.display_manager.set_scrolling_state(
                True, frame_hold=self._scroll_frame_hold())
            return

        self.display_manager.set_scrolling_state(
            True, frame_hold=self._scroll_frame_hold())
        self.display_manager.process_deferred_updates()

        self.scroll_helper.update_scroll_position()
        if self.scroll_helper.is_scroll_complete():
            self._cycle_complete = True

        visible = self.scroll_helper.get_visible_portion()
        if visible:
            self.display_manager.image.paste(visible, (0, 0))
            self.display_manager.update_display()

        self.scroll_helper.log_frame_rate()

    def _build_strip(self) -> bool:
        """Render the ticker into the scroll helper. False if it could not be built."""
        try:
            strip = self.renderer.build_strip(self.boards, self._season_label())
        except Exception as exc:  # noqa: BLE001 - never lose the loop to a draw
            self.logger.error("Could not build the stat-leader strip: %s", exc,
                              exc_info=True)
            self.scroll_helper.clear_cache()
            return False

        if strip is None:
            self.scroll_helper.clear_cache()
            return False

        self.scroll_helper.set_scrolling_image(strip)
        self._cycle_complete = False
        self._warn_if_truncated(strip.width)
        return True

    def _season_label(self) -> str:
        season = self.resolved_season or self.season
        label = SEASON_TYPE_LABELS.get(self.season_type, "")
        return " ".join(part for part in (str(season) if season else "", label)
                        if part)

    def _warn_if_truncated(self, strip_width: int) -> None:
        """Say so when the ticker is longer than the controller will show.

        The controller stops the slot at ``min(plugin cap, global cap)``, so
        a long board can scroll off the end of its own display time. Saying
        which setting to change beats a user wondering why the last
        categories never appear.
        """
        if not self.dynamic_duration_enabled:
            return
        speed = float(getattr(self.scroll_helper, "scroll_speed", 0.0) or 0.0)
        if speed <= 0:
            return

        cap = min(float(self.dynamic_duration_cap), self._core_dynamic_cap())
        needed = (strip_width + self.display_width) / speed
        if needed > cap:
            self.logger.warning(
                "The ticker needs %.0fs at %.0f px/s but the display cap is "
                "%.0fs; lower players_per_category, enable fewer categories, "
                "or raise dynamic_duration.controller_cap_seconds",
                needed, speed, cap,
            )

    def _core_dynamic_cap(self) -> float:
        """The core's global dynamic-duration cap, which also limits the slot."""
        for owner in (self.plugin_manager, self.cache_manager):
            config_manager = getattr(owner, "config_manager", None)
            if config_manager is None:
                continue
            try:
                config = config_manager.get_config()
                value = (config.get("display", {})
                               .get("dynamic_duration", {})
                               .get("max_duration_seconds"))
            except Exception as exc:  # noqa: BLE001 - a core without this
                # block is fine; the class default below covers it.
                self.logger.debug("Could not read the core's duration cap: %s", exc)
                continue
            if value:
                return float(value)
        return self.CORE_DEFAULT_DYNAMIC_CAP

    def _draw_placeholder(self) -> None:
        """A quiet holding screen while there is nothing to scroll."""
        try:
            self.renderer.draw_placeholder(self.display_manager.image)
            self.display_manager.update_display()
        except Exception as exc:  # noqa: BLE001 - a placeholder is never fatal
            self.logger.debug("Could not draw the placeholder: %s", exc)

    # ------------------------------------------------------------------
    # Duration and cycle hooks
    # ------------------------------------------------------------------

    def supports_dynamic_duration(self) -> bool:
        return self.dynamic_duration_enabled

    def get_dynamic_duration_cap(self) -> Optional[float]:
        if not self.dynamic_duration_enabled:
            return None
        return float(self.dynamic_duration_cap)

    def get_cycle_duration(self, display_mode: str = None) -> Optional[float]:
        if self.scroll_helper.cached_image:
            return float(self.scroll_helper.get_dynamic_duration())
        return None

    def get_display_duration(self) -> float:
        if self.dynamic_duration_enabled and self.scroll_helper.cached_image:
            return float(self.scroll_helper.get_dynamic_duration())
        return float(self.display_duration)

    def is_cycle_complete(self) -> bool:
        if not self.dynamic_duration_enabled:
            return True
        if self.loop:
            return False
        return self._cycle_complete

    def reset_cycle_state(self) -> None:
        super().reset_cycle_state()
        self._cycle_complete = False
        self.scroll_helper.reset_scroll()

    def get_info(self) -> Dict[str, Any]:
        info = super().get_info()
        info.update({
            "categories": [category.key for category in self.categories],
            "players_per_category": self.players_per_category,
            "season": self.resolved_season,
            "season_type": SEASON_TYPE_LABELS.get(self.season_type, ""),
            "boards_loaded": len(self.boards),
        })
        return info

    def cleanup(self) -> None:
        self.scroll_helper.clear_cache()
        self.boards = []
        super().cleanup()


def _safe_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    """An int from config, clamped, never raising on a hand-edited value."""
    try:
        return max(minimum, min(maximum, int(value)))
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float, minimum: float,
                maximum: float) -> float:
    try:
        return max(minimum, min(maximum, float(value)))
    except (TypeError, ValueError):
        return default
