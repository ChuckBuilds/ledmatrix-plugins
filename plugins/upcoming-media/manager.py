"""
Upcoming Episodes & Movies plugin for LEDMatrix.

Shows what is coming out next: new TV episodes (from Sonarr, or from
Jellyfin's "Upcoming" list when Sonarr is not set up) and upcoming movie
releases (from Radarr). Two display modes -- ``upcoming-episodes`` and
``upcoming-movies`` -- each run as a one-card-at-a-time switch, a
continuous scroll, or as cards in the core's Vegas marquee.

Fetch in update(), draw in display(): nothing here touches the network from
the render thread.

API Version: 1.0.0
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageFont

from src.plugin_system.base_plugin import BasePlugin
from src.common.font_layout import crisp_size, load_truetype, resolve_asset_path

try:
    from src.plugin_system.base_plugin import VegasDisplayMode
except ImportError:  # older core
    VegasDisplayMode = None

try:
    from src.common.scroll_helper import ScrollHelper
except ImportError:  # pragma: no cover -- every core at the floor ships it
    ScrollHelper = None

try:
    from src.common import scroll_config as _scroll_config
except ImportError:  # pragma: no cover
    _scroll_config = None

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

from upcoming_media_sources import (
    RADARR_RELEASE_TYPES,
    ImageStore,
    JellyfinSource,
    RadarrSource,
    SonarrSource,
    SourceError,
    UpcomingItem,
    select_items,
)
from upcoming_media_renderer import RenderSettings, UpcomingRenderer

MODE_EPISODES = "upcoming-episodes"
MODE_MOVIES = "upcoming-movies"
MODES = (MODE_EPISODES, MODE_MOVIES)
KIND_FOR_MODE = {MODE_EPISODES: "episode", MODE_MOVIES: "movie"}

ERROR_COLOR = (255, 80, 80)
INFO_COLOR = (150, 150, 150)

DEFAULT_COLORS = {
    "title": (255, 255, 255),
    "episode": (120, 200, 255),
    "date": (255, 190, 60),
    "description": (170, 170, 170),
}
CUSTOM_KEYS = {
    "title": "title_text",
    "episode": "episode_text",
    "date": "date_text",
    "description": "description_text",
}


def _color(value, default) -> Tuple[int, int, int]:
    try:
        parsed = tuple(max(0, min(255, int(c))) for c in value)
        if len(parsed) == 3:
            return parsed  # type: ignore[return-value]
    except (TypeError, ValueError):
        pass
    return tuple(default)  # type: ignore[return-value]


def _bdf_pixel_size(path: str) -> Optional[int]:
    try:
        with open(path, "r", encoding="latin-1") as handle:
            for line in handle:
                if line.startswith("PIXEL_SIZE"):
                    return int(line.split()[1])
                if line.startswith("CHARS"):
                    break
    except (OSError, ValueError, IndexError):
        return None
    return None


class UpcomingMediaPlugin(BasePlugin):
    """Upcoming TV episodes and movie releases."""

    def __init__(self, plugin_id: str, config: Dict[str, Any],
                 display_manager, cache_manager, plugin_manager):
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)
        self._font_cache: Dict[Tuple[str, int], Any] = {}
        self.images = ImageStore(logger=self.logger, cache=cache_manager)
        self._items: Dict[str, List[UpcomingItem]] = {m: [] for m in MODES}
        self._errors: Dict[str, Optional[str]] = {m: None for m in MODES}
        self._fetched: Dict[str, bool] = {m: False for m in MODES}
        self._data_version = 0
        self._active_mode: Optional[str] = None
        self._load_config()

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def _load_config(self) -> None:
        """Read every setting. Called from __init__ and on_config_change, so
        a web-UI save applies without a restart."""
        c = self.config or {}
        self.enabled = c.get("enabled", True)
        self.show_episodes = bool(c.get("show_episodes", True))
        self.show_movies = bool(c.get("show_movies", True))
        self.display_mode = c.get("display_mode", "switch")
        if self.display_mode not in ("switch", "scroll"):
            self.display_mode = "switch"
        self.window = c.get("window", "upcoming_list")
        self.days_ahead = int(c.get("days_ahead", 7))
        self.max_items = int(c.get("max_items", 10))
        self.include_aired_today = bool(c.get("include_aired_today", True))
        self.include_downloaded = bool(c.get("include_downloaded", True))
        self.group_episodes = bool(c.get("group_episodes", True))
        self.switch_duration = float(c.get("switch_duration", 6))
        self.marquee_enabled = bool(c.get("marquee_enabled", True))
        self.show_empty_message = bool(c.get("show_empty_message", False))
        self.update_interval_config = max(60, int(c.get("update_interval", 900)))
        self.episode_source = c.get("episode_source", "auto")

        unmonitored = bool(c.get("include_unmonitored", False))
        self.sonarr = SonarrSource(c.get("sonarr_url", ""), c.get("sonarr_api_key", ""),
                                   include_unmonitored=unmonitored)
        release_types = c.get("movie_release_types") or list(RADARR_RELEASE_TYPES)
        if isinstance(release_types, str):
            release_types = [release_types]
        self.radarr = RadarrSource(c.get("radarr_url", ""), c.get("radarr_api_key", ""),
                                   include_unmonitored=unmonitored,
                                   release_types=[r for r in release_types if r in RADARR_RELEASE_TYPES])
        libraries = c.get("jellyfin_libraries") or []
        if isinstance(libraries, str):
            libraries = [lib for lib in libraries.split(",")]
        self.jellyfin = JellyfinSource(c.get("jellyfin_url", ""), c.get("jellyfin_api_key", ""),
                                       username=c.get("jellyfin_username", ""),
                                       libraries=libraries)

        custom = c.get("customization") or {}
        colors = {}
        overrides: Dict[str, Tuple[Optional[str], int]] = {}
        for element, key in CUSTOM_KEYS.items():
            block = custom.get(key) or {}
            colors[element] = _color(block.get("text_color"), DEFAULT_COLORS[element])
            font = block.get("font", "auto")
            size = int(block.get("font_size", 0) or 0)
            overrides[element] = (None if font in (None, "", "auto") else font, size)
        self.render_settings = RenderSettings(
            show_episode_title=bool(c.get("show_episode_title", True)),
            show_description=bool(c.get("show_description", True)),
            show_runtime=bool(c.get("show_runtime", True)),
            show_date=bool(c.get("show_date", True)),
            episode_format=c.get("episode_format", "compact"),
            image_type=c.get("image_type", "auto"),
            date_format=c.get("date_format", "relative"),
            time_format=c.get("time_format", "12h"),
            description_max_chars=int(c.get("description_max_chars", 60)),
            colors=colors,
            accent_color=_color(custom.get("accent_color"), (124, 77, 255)),
            today_color=_color(custom.get("today_color"), (90, 255, 120)),
            background_color=_color(custom.get("background_color"), (0, 0, 0)),
            highlight_today=bool(c.get("highlight_today", True)),
        )
        self.renderer = UpcomingRenderer(self.render_settings, self.images, self._load_font, overrides)

        # Scroll state, one helper per mode so each keeps its own strip.
        self.enable_scrolling = self.display_mode == "scroll"
        self._scroll: Dict[str, Any] = {}
        self._scroll_sig: Dict[str, Any] = {}
        self._scroll_settings = None
        self._switch: Dict[str, Dict[str, Any]] = {
            m: {"index": 0, "since": 0.0, "shown": 0, "frame_sig": None} for m in MODES}
        self._holds: Dict[Tuple[str, int, int, int], float] = {}
        self._data_version += 1

    def on_config_change(self, new_config: Dict[str, Any]) -> None:
        super().on_config_change(new_config)
        self._font_cache.clear()
        self._load_config()
        # Sources, window or filters may have changed: refetch on next update().
        self._fetched = {m: False for m in MODES}

    def get_update_interval(self) -> Optional[float]:
        return float(self.update_interval_config)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _dims(self) -> Tuple[int, int]:
        width = getattr(self.display_manager, "width", None)
        height = getattr(self.display_manager, "height", None)
        if not width or not height:
            width = self.display_manager.matrix.width
            height = self.display_manager.matrix.height
        return int(width), int(height)

    def _tz(self):
        name = None
        try:
            cm = getattr(self.plugin_manager, "config_manager", None)
            if cm is not None and hasattr(cm, "get_timezone"):
                name = cm.get_timezone()
        except Exception:  # noqa: BLE001
            name = None
        if not name:
            try:
                name = (self.global_config or {}).get("timezone")
            except Exception:  # noqa: BLE001
                name = None
        if name and ZoneInfo is not None:
            try:
                return ZoneInfo(str(name))
            except Exception:  # noqa: BLE001
                if getattr(self, "_warned_tz", None) != name:
                    self._warned_tz = name
                    self.logger.warning("Invalid timezone %r; using UTC", name)
        return timezone.utc

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _load_font(self, name: str, size: int):
        """A font from the core's assets/fonts. ``size`` 0 means the face's own
        size (bdf) or its crisp default (ttf)."""
        key = (name, size)
        if key in self._font_cache:
            return self._font_cache[key]
        font = None
        path = resolve_asset_path(os.path.join("assets", "fonts", name))
        if os.path.exists(path):
            native = _bdf_pixel_size(path) if name.lower().endswith(".bdf") else None
            want = native if native else crisp_size(name, size or 8) or 8
            try:
                font = load_truetype(path, want)
            except OSError:
                if native and native != want:
                    try:
                        font = load_truetype(path, native)
                    except OSError:
                        font = None
            except Exception as e:  # noqa: BLE001
                self.logger.warning("Could not load font %s: %s", name, e)
        if font is None:
            self.logger.warning("Font %s not found, using default", name)
            font = ImageFont.load_default()
        self._font_cache[key] = font
        return font

    def _episode_source(self):
        if self.episode_source == "sonarr":
            return self.sonarr
        if self.episode_source == "jellyfin":
            return self.jellyfin
        return self.sonarr if self.sonarr.configured else self.jellyfin

    def _source_for(self, mode: str):
        if mode == MODE_EPISODES:
            return self._episode_source() if self.show_episodes else None
        return self.radarr if self.show_movies else None

    def _any_configured(self) -> bool:
        return any(src is not None and src.configured for src in (self._source_for(m) for m in MODES))

    # ------------------------------------------------------------------
    # Fetch
    # ------------------------------------------------------------------

    def update(self) -> None:
        if not self.enabled:
            return
        now = self._now()
        tz = self._tz()
        changed = False
        keep_urls: List[str] = []
        for mode in MODES:
            source = self._source_for(mode)
            if source is None or not source.configured:
                if self._items[mode]:
                    changed = True
                self._items[mode] = []
                self._errors[mode] = None
                continue
            try:
                key = source.cache_key(self.days_ahead)
                raw = self.cache_manager.get(key, max_age=self.update_interval_config)
                if raw is None:
                    raw = source.fetch_raw(now, self.days_ahead)
                    self.cache_manager.set(key, raw, ttl=self.update_interval_config)
                parsed = source.parse(raw)
                items = select_items(parsed, now, tz, self.days_ahead, window=self.window,
                                     include_aired_today=self.include_aired_today,
                                     max_items=self.max_items,
                                     include_downloaded=self.include_downloaded,
                                     group_episodes=self.group_episodes)
                self._errors[mode] = None
            except SourceError as e:
                self.logger.warning("%s", e)
                self._errors[mode] = e.message
                self._fetched[mode] = True
                for item in self._items[mode]:
                    keep_urls.extend(item.images.values())
                continue  # keep the last good list on screen
            except Exception as e:  # noqa: BLE001 -- never raise into the core
                self.logger.error("Unexpected error fetching %s: %s", mode, e, exc_info=True)
                self._errors[mode] = "Error: see logs"
                self._fetched[mode] = True
                for item in self._items[mode]:
                    keep_urls.extend(item.images.values())
                continue
            if self.render_settings.image_type != "none":
                for item in items:
                    keep_urls.extend(self._prefetch_images(item))
            if [i.uid for i in items] != [i.uid for i in self._items[mode]] or not self._fetched[mode]:
                changed = True
            self._items[mode] = items
            self._fetched[mode] = True
        self.images.forget_unused(keep_urls)
        if changed:
            self._data_version += 1

    def _prefetch_images(self, item: UpcomingItem) -> List[str]:
        """Download the image(s) this panel will draw for ``item``; when the
        preferred one is missing or fails, the other slot as a fallback.
        A logo also brings its poster along: the renderer swaps to the poster
        when a logo turns out unreadable at panel size. Returns the URLs to
        keep in memory."""
        wanted = self._wanted_slots()
        kept: List[str] = []
        for slot in wanted + tuple(s for s in ("logo", "poster") if s not in wanted):
            url = item.images.get(slot)
            if url and self.images.prefetch(url, item.image_headers.get(slot)):
                kept.append(url)
                if slot == "poster":
                    break
        return kept

    def _wanted_slots(self) -> Tuple[str, ...]:
        pref = self.render_settings.image_type
        _, height = self._dims()
        if pref == "logo":
            return ("logo",)
        if pref == "poster":
            return ("poster",)
        return ("logo", "poster") if height >= 56 else ("poster",)

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def _message(self, lines: List[str], color) -> None:
        width, height = self._dims()
        img = self.renderer.render_message(width, height, lines, color)
        self.display_manager.image.paste(img, (0, 0))
        self.display_manager.update_display()

    def display(self, display_mode: Optional[str] = None, force_clear: bool = False):
        mode = display_mode if display_mode in MODES else (self._active_mode or MODES[0])
        if mode != self._active_mode:
            force_clear = True
            self._active_mode = mode
        if not self.enabled:
            return False

        source = self._source_for(mode)
        if source is None or not source.configured:
            if mode == MODE_EPISODES and not self._any_configured():
                if hasattr(self.display_manager, "set_scrolling_state"):
                    self.display_manager.set_scrolling_state(False)
                self._message(["Upcoming Media", "Add a server in settings"],
                              INFO_COLOR)
                return True
            return False

        items = self._items[mode]
        if not items:
            if not self._fetched[mode]:
                self._message(["Loading..."], INFO_COLOR)
                return True
            if self._errors[mode]:
                self._message([str(self._errors[mode])], ERROR_COLOR)
                return True
            if self.show_empty_message:
                what = "episodes" if mode == MODE_EPISODES else "movies"
                self._message([f"No upcoming {what}"], INFO_COLOR)
                return True
            return False

        if self.display_mode == "scroll" and ScrollHelper is not None:
            self._display_scroll(mode, items, force_clear)
        else:
            self._display_switch(mode, items, force_clear)
        return True

    # -- switch -----------------------------------------------------------

    def _display_switch(self, mode: str, items: List[UpcomingItem], force_clear: bool) -> None:
        if hasattr(self.display_manager, "set_scrolling_state"):
            self.display_manager.set_scrolling_state(False)
        state = self._switch[mode]
        now_t = time.time()
        if force_clear or state["since"] == 0.0:
            state.update(index=0, since=now_t, shown=1, frame_sig=None)
        elif len(items) > 1 and now_t - state["since"] >= self._hold(items[state["index"] % len(items)]):
            state["index"] = (state["index"] + 1) % len(items)
            state["since"] = now_t
            state["shown"] += 1
            state["frame_sig"] = None
        index = state["index"] % len(items)
        item = items[index]
        width, height = self._dims()
        marquee_t = (now_t - state["since"]) if self.marquee_enabled else None
        # Redraw only when something can have changed: a new card, new data,
        # or a marquee step.
        sig = (item.uid, self._data_version, width, height,
               int(marquee_t * self.renderer.MARQUEE_SPEED)
               if state.get("moving") and marquee_t is not None else None)
        if sig == state["frame_sig"] and not force_clear:
            return
        card, moving = self.renderer.render_card(item, width, height, self._now(), self._tz(),
                                                 marquee_t=marquee_t)
        state["moving"] = moving
        state["frame_sig"] = sig
        self.display_manager.image.paste(card, (0, 0))
        self.display_manager.update_display()

    # A card whose title scrolls stays up until one full pass is done, up to
    # this many times switch_duration, so a long name is never cut off midway.
    HOLD_CAP_FACTOR = 3.0

    def _hold(self, item: UpcomingItem) -> float:
        """Seconds this card stays up in switch mode."""
        base = self.switch_duration
        if not self.marquee_enabled:
            return base
        width, height = self._dims()
        key = (item.uid, self._data_version, width, height)
        cached = self._holds.get(key)
        if cached is None:
            try:
                need = self.renderer.marquee_seconds(item, width, height, self._now(), self._tz())
            except Exception:  # noqa: BLE001 -- timing must never break display
                need = 0.0
            cached = min(max(base, need + 0.5), base * self.HOLD_CAP_FACTOR) if need else base
            if len(self._holds) > 256:
                self._holds.clear()
            self._holds[key] = cached
        return cached

    def _switch_total(self, mode: str) -> float:
        items = self._items.get(mode) or []
        if not items:
            return self.switch_duration
        return float(sum(self._hold(i) for i in items))

    @property
    def needs_high_fps(self) -> bool:
        """Scrolling needs the core's fast loop; so does a switch-mode marquee
        (at the default 1 FPS a moving line would jump)."""
        return self.display_mode == "scroll" or self.marquee_enabled

    # -- scroll -----------------------------------------------------------

    def _helper(self, mode: str):
        helper = self._scroll.get(mode)
        width, height = self._dims()
        if helper is None or (helper.display_width, helper.display_height) != (width, height):
            helper = ScrollHelper(width, height, logger=self.logger)
            dd = self.config.get("dynamic_duration") or {}
            if hasattr(helper, "set_dynamic_duration_settings"):
                helper.set_dynamic_duration_settings(
                    enabled=bool(dd.get("enabled", True)),
                    min_duration=int(dd.get("min_duration_seconds", 15)),
                    max_duration=int(dd.get("max_duration_seconds", 180)),
                    buffer=0.1,
                )
            if _scroll_config is not None:
                try:
                    self._scroll_settings = _scroll_config.configure(
                        helper, plugin_config=self.config, global_config=self.global_config,
                        display_manager=self.display_manager, plugin_logger=self.logger)
                except Exception as e:  # noqa: BLE001
                    self.logger.debug("scroll_config.configure failed: %s", e)
            self._scroll[mode] = helper
            self._scroll_sig[mode] = None
        return helper

    def _frame_hold(self) -> int:
        return getattr(self._scroll_settings, "frame_hold", 1) if self._scroll_settings else 1

    def _display_scroll(self, mode: str, items: List[UpcomingItem], force_clear: bool) -> None:
        helper = self._helper(mode)
        width, height = self._dims()
        sig = (self._data_version, width, height, time.strftime("%Y%m%d%H"))
        if helper.cached_image is None or self._scroll_sig.get(mode) != sig:
            strip = self.renderer.render_strip(items, width, height, self._now(), self._tz())
            helper.set_scrolling_image(self._pad_strip(strip, width))
            self._scroll_sig[mode] = sig
            if hasattr(helper, "calculate_dynamic_duration"):
                helper.calculate_dynamic_duration()
            force_clear = True
        if force_clear:
            helper.reset_scroll()
        if hasattr(self.display_manager, "set_scrolling_state"):
            # Pass the hold every time: plugins share one display manager, so a
            # hold set once is wiped when another plugin's scroll ends.
            self.display_manager.set_scrolling_state(True, frame_hold=self._frame_hold())
        if hasattr(self.display_manager, "process_deferred_updates"):
            self.display_manager.process_deferred_updates()
        helper.update_scroll_position()
        visible = helper.get_visible_portion()
        if visible is not None:
            self.display_manager.image.paste(visible, (0, 0))
            self.display_manager.update_display()

    @staticmethod
    def _pad_strip(strip: Image.Image, width: int) -> Image.Image:
        """Lead in from off-panel (a full panel width of black before the first
        card) so a standalone scroll starts clean, as stocks/news do."""
        padded = Image.new("RGB", (strip.width + width, strip.height), (0, 0, 0))
        padded.paste(strip, (width, 0))
        return padded

    # ------------------------------------------------------------------
    # Durations / cycle
    # ------------------------------------------------------------------

    def supports_dynamic_duration(self) -> bool:
        if self.display_mode == "switch":
            return True
        dd = self.config.get("dynamic_duration") or {}
        return bool(dd.get("enabled", True))

    def get_cycle_duration(self, display_mode: Optional[str] = None) -> Optional[float]:
        mode = display_mode if display_mode in MODES else (self._active_mode or MODES[0])
        if self.display_mode == "switch":
            return self._switch_total(mode)
        helper = self._scroll.get(mode)
        if helper is not None and helper.cached_image is not None:
            duration = getattr(helper, "calculated_duration", 0) or helper.calculate_dynamic_duration()
            if duration and duration > 0:
                return float(duration)
        return None

    def get_dynamic_duration_cap(self) -> Optional[float]:
        if self.display_mode == "switch":
            mode = self._active_mode or MODES[0]
            return self._switch_total(mode)
        dd = self.config.get("dynamic_duration") or {}
        cap = dd.get("max_duration_seconds", 180)
        try:
            cap = float(cap)
        except (TypeError, ValueError):
            return None
        return cap if cap > 0 else None

    def is_cycle_complete(self) -> bool:
        mode = self._active_mode or MODES[0]
        items = self._items.get(mode) or []
        if not items:
            return True
        if self.display_mode == "switch":
            state = self._switch[mode]
            # Complete once the last card has had its full time. display()
            # rotates before the core asks, so having wrapped past the last
            # card (shown > len) also counts.
            if state["shown"] > len(items):
                return True
            return state["shown"] == len(items) and \
                time.time() - state["since"] >= self._hold(items[state["index"] % len(items)])
        helper = self._scroll.get(mode)
        return bool(helper is None or helper.is_scroll_complete())

    def reset_cycle_state(self) -> None:
        super().reset_cycle_state()
        for state in self._switch.values():
            state.update(index=0, since=0.0, shown=0, frame_sig=None)
        for helper in self._scroll.values():
            helper.reset_scroll()

    # ------------------------------------------------------------------
    # Vegas
    # ------------------------------------------------------------------

    def get_vegas_content(self):
        width, height = self._dims()
        now, tz = self._now(), self._tz()
        cards: List[Image.Image] = []
        for mode in MODES:
            for item in self._items.get(mode) or []:
                card, _ = self.renderer.render_card(item, width, height, now, tz, strip=True)
                cards.append(card)
        return cards or None

    def get_vegas_content_type(self) -> str:
        return "multi"

    def get_vegas_display_mode(self):
        if VegasDisplayMode is None:
            return "scroll"
        mode = self.config.get("vegas_mode")
        if mode:
            try:
                return VegasDisplayMode(mode)
            except ValueError:
                self.logger.warning("Invalid vegas_mode %r, using scroll", mode)
        return VegasDisplayMode.SCROLL

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def get_info(self) -> Dict[str, Any]:
        info = super().get_info()
        info.update({
            "display_mode": self.display_mode,
            "episode_source": getattr(self._episode_source(), "name", None),
            "episodes": len(self._items[MODE_EPISODES]),
            "movies": len(self._items[MODE_MOVIES]),
            "errors": {m: e for m, e in self._errors.items() if e},
        })
        return info

    def validate_config(self) -> bool:
        if not super().validate_config():
            return False
        for key in ("sonarr_url", "radarr_url", "jellyfin_url"):
            url = self.config.get(key) or ""
            if url and not str(url).startswith(("http://", "https://")):
                self.logger.error("%s must start with http:// or https://", key)
                return False
        return True

    def cleanup(self) -> None:
        self._scroll.clear()
        self.images.forget_unused(())
        super().cleanup()
