"""
Cricket Scoreboard plugin.

CricketScoreboardPlugin orchestrates series discovery, data fetching, match
categorization (live / recent / upcoming), logo/flag resolution and per-mode
rotation. It mirrors the lifecycle and config surface of the other sports
scoreboard plugins (see soccer-scoreboard/manager.py) while using a cricket-
specific data model and renderer.

Display modes: cricket_live, cricket_recent, cricket_upcoming.
"""

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image

# Guarded BasePlugin import so this module also compiles / runs standalone
# (e.g. under the test harness) without the core LEDMatrix package present.
try:
    from src.plugin_system.base_plugin import BasePlugin, VegasDisplayMode
except ImportError:
    BasePlugin = None
    VegasDisplayMode = None

try:
    from src.background_data_service import get_background_service
except ImportError:
    get_background_service = None

from cricket_data_fetcher import CricketDataFetcher
from cricket_renderer import CricketRenderer

try:
    from cricket_logo_downloader import download_missing_logo
except ImportError:  # pragma: no cover
    download_missing_logo = None

logger = logging.getLogger(__name__)

_PLUGIN_DIR = Path(__file__).resolve().parent

MODE_LIVE = "cricket_live"
MODE_RECENT = "cricket_recent"
MODE_UPCOMING = "cricket_upcoming"

# ESPN competition keys that represent bundled national-team flags rather than
# auto-downloaded franchise logos.
_INTERNATIONAL_KEY = "international"


class CricketScoreboardPlugin(BasePlugin if BasePlugin else object):
    """Cricket scoreboard plugin (international + major domestic T20 leagues)."""

    def __init__(self, plugin_id, config, display_manager, cache_manager,
                 plugin_manager):
        if BasePlugin:
            super().__init__(plugin_id, config, display_manager, cache_manager,
                             plugin_manager)

        self.plugin_id = plugin_id
        self.config = config or {}
        self.display_manager = display_manager
        self.cache_manager = cache_manager
        self.plugin_manager = plugin_manager
        self.logger = logger

        self.is_enabled = self.config.get("enabled", False)

        if hasattr(display_manager, "matrix") and display_manager.matrix is not None:
            self.display_width = display_manager.matrix.width
            self.display_height = display_manager.matrix.height
        else:
            self.display_width = getattr(display_manager, "width", 128)
            self.display_height = getattr(display_manager, "height", 32)

        # Load the curated competition seed list.
        self.competitions = self._load_competitions()

        # Durations / intervals.
        self.display_duration = float(self.config.get("display_duration", 15))
        self.live_game_duration = float(self.config.get("live_game_duration", 20))
        self.non_favorite_live_game_duration = float(
            self.config.get("non_favorite_live_game_duration", 0))
        self.recent_game_duration = float(self.config.get("recent_game_duration", 15))
        self.upcoming_game_duration = float(self.config.get("upcoming_game_duration", 15))
        self.update_interval = int(self.config.get("update_interval_seconds", 3600))
        self.live_update_interval = int(self.config.get("live_update_interval", 30))
        self.recent_games_to_show = int(self.config.get("recent_games_to_show", 5))
        self.upcoming_games_to_show = int(self.config.get("upcoming_games_to_show", 5))
        self.live_priority = bool(self.config.get("live_priority", True))

        self.favorite_teams = [t.lower() for t in self.config.get("favorite_teams", [])]
        self.exclude_teams = [t.lower() for t in self.config.get("exclude_teams", [])]
        self.show_favorite_teams_only = bool(
            self.config.get("show_favorite_teams_only", False))

        display_modes = self.config.get("display_modes", {}) or {}
        self.mode_enabled = {
            MODE_LIVE: display_modes.get("live", True),
            MODE_RECENT: display_modes.get("recent", True),
            MODE_UPCOMING: display_modes.get("upcoming", True),
        }

        bg_cfg = self.config.get("background_service", {}) or {}
        req_timeout = int(bg_cfg.get("request_timeout", 30))

        self.fetcher = CricketDataFetcher(cache_manager, self.config,
                                          self.competitions, request_timeout=req_timeout)
        self.renderer = CricketRenderer(self.display_width, self.display_height,
                                        self.config)

        # Optional background service (best-effort, same pattern as soccer).
        self.background_service = None
        if get_background_service:
            try:
                self.background_service = get_background_service(cache_manager, max_workers=1)
            except Exception as e:
                self.logger.warning("Cricket background service init failed: %s", e)

        # Categorized match state.
        self._lock = threading.Lock()
        self.live_matches: List[Dict[str, Any]] = []
        self.recent_matches: List[Dict[str, Any]] = []
        self.upcoming_matches: List[Dict[str, Any]] = []

        self._last_update = 0.0

        # Per-mode rotation state.
        self._mode_index: Dict[str, int] = {MODE_LIVE: 0, MODE_RECENT: 0, MODE_UPCOMING: 0}
        self._mode_item_start: Dict[str, float] = {}

        self.logos_dir = _PLUGIN_DIR / "assets" / "logos"
        self.logos_dir.mkdir(parents=True, exist_ok=True)

        self.logger.info("Cricket scoreboard initialized (%dx%d), %d competitions seeded",
                         self.display_width, self.display_height, len(self.competitions))

    # ------------------------------------------------------------------ #
    # Setup helpers
    # ------------------------------------------------------------------ #

    def _load_competitions(self) -> List[Dict[str, Any]]:
        path = _PLUGIN_DIR / "competitions.json"
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            self.logger.error("Failed to load competitions.json: %s", e)
            return [{"key": "international", "name": "International", "search_terms": None}]

    # ------------------------------------------------------------------ #
    # Filtering
    # ------------------------------------------------------------------ #

    def _match_has_team(self, match: Dict[str, Any], names: List[str]) -> bool:
        for team in match.get("teams", []):
            hay = f"{team.get('name', '')} {team.get('abbr', '')} {team.get('short_name', '')}".lower()
            if any(n and n in hay for n in names):
                return True
        return False

    def _keep_match(self, match: Dict[str, Any]) -> bool:
        if self.exclude_teams and self._match_has_team(match, self.exclude_teams):
            return False
        # show_favorite_teams_only only constrains international matches; domestic
        # competitions are already the user's chosen favorites.
        if (self.show_favorite_teams_only and self.favorite_teams
                and match.get("competition_key") == _INTERNATIONAL_KEY):
            if not self._match_has_team(match, self.favorite_teams):
                return False
        return True

    def _match_is_favorite(self, match: Dict[str, Any]) -> bool:
        return bool(self.favorite_teams) and self._match_has_team(match, self.favorite_teams)

    # ------------------------------------------------------------------ #
    # Update
    # ------------------------------------------------------------------ #

    def update(self) -> None:
        if not self.is_enabled:
            return
        now = time.time()
        # Faster refresh when live content is present.
        has_live = bool(self.live_matches)
        interval = self.live_update_interval if has_live else self.update_interval
        if now - self._last_update < interval:
            return
        self._last_update = now

        try:
            ttl = self.live_update_interval if has_live else self.update_interval
            matches = self.fetcher.fetch_matches(ttl=ttl)
        except Exception as e:
            self.logger.warning("Cricket fetch_matches failed: %s", e)
            return

        live, recent, upcoming = [], [], []
        for m in matches:
            if not self._keep_match(m):
                continue
            state = m.get("state")
            if state == "in":
                live.append(m)
            elif state == "post":
                recent.append(m)
            else:
                upcoming.append(m)

        # Sort: favorites first for live; most-recent-first for recent; soonest
        # first for upcoming.
        live.sort(key=lambda m: (not self._match_is_favorite(m),
                                 m.get("start_time_utc") or _min_dt()))
        recent.sort(key=lambda m: m.get("start_time_utc") or _min_dt(), reverse=True)
        upcoming.sort(key=lambda m: m.get("start_time_utc") or _max_dt())

        recent = recent[: self.recent_games_to_show]
        upcoming = upcoming[: self.upcoming_games_to_show]

        # Auto-download franchise logos (national teams use bundled flags).
        for m in live + recent + upcoming:
            if m.get("competition_key") != _INTERNATIONAL_KEY:
                self._ensure_logos(m)

        with self._lock:
            self.live_matches = live
            self.recent_matches = recent
            self.upcoming_matches = upcoming

        self.logger.info("Cricket update: %d live, %d recent, %d upcoming",
                         len(live), len(recent), len(upcoming))

    def _ensure_logos(self, match: Dict[str, Any]) -> None:
        if download_missing_logo is None:
            return
        for team in match.get("teams", []):
            abbr = (team.get("abbr") or "").upper()
            abbr = "".join(c for c in abbr if c.isalnum() or c in ("&", "_"))
            url = team.get("logo_url")
            if not abbr or not url:
                continue
            path = self.logos_dir / f"{abbr}.png"
            if path.parent != self.logos_dir:
                continue
            if path.exists():
                continue
            try:
                download_missing_logo("cricket", team.get("id", ""), abbr, path, url)
            except Exception as e:
                self.logger.debug("Logo download failed for %s: %s", abbr, e)

    # ------------------------------------------------------------------ #
    # Display
    # ------------------------------------------------------------------ #

    def _matches_for_mode(self, mode: str) -> List[Dict[str, Any]]:
        with self._lock:
            if mode == MODE_LIVE:
                return list(self.live_matches)
            if mode == MODE_RECENT:
                return list(self.recent_matches)
            if mode == MODE_UPCOMING:
                return list(self.upcoming_matches)
        return []

    def _per_item_duration(self, mode: str, match: Optional[Dict[str, Any]]) -> float:
        if mode == MODE_LIVE:
            if (self.non_favorite_live_game_duration > 0 and match is not None
                    and not self._match_is_favorite(match)):
                return self.non_favorite_live_game_duration
            return self.live_game_duration
        if mode == MODE_RECENT:
            return self.recent_game_duration
        if mode == MODE_UPCOMING:
            return self.upcoming_game_duration
        return self.display_duration

    def _current_match(self, mode: str) -> Optional[Dict[str, Any]]:
        matches = self._matches_for_mode(mode)
        if not matches:
            return None
        idx = self._mode_index.get(mode, 0) % len(matches)
        match = matches[idx]

        now = time.time()
        start = self._mode_item_start.get(mode)
        if start is None:
            self._mode_item_start[mode] = now
        elif now - start >= self._per_item_duration(mode, match):
            idx = (idx + 1) % len(matches)
            self._mode_index[mode] = idx
            self._mode_item_start[mode] = now
            match = matches[idx]
        return match

    def _render_match(self, mode: str, match: Dict[str, Any]) -> Image.Image:
        if mode == MODE_LIVE:
            if match.get("is_test"):
                return self.renderer.render_live_test(match)
            return self.renderer.render_live_limited_overs(match)
        if mode == MODE_RECENT:
            return self.renderer.render_recent(match)
        return self.renderer.render_upcoming(match)

    def display(self, display_mode: str = None, force_clear: bool = False) -> bool:
        if not self.is_enabled:
            return False

        mode = display_mode or self._pick_default_mode()
        if mode not in (MODE_LIVE, MODE_RECENT, MODE_UPCOMING):
            return False
        if not self.mode_enabled.get(mode, True):
            return False

        match = self._current_match(mode)
        if match is None:
            return False

        try:
            image = self._render_match(mode, match)
        except Exception as e:
            self.logger.warning("Cricket render failed (%s): %s", mode, e)
            return False

        try:
            if force_clear and hasattr(self.display_manager, "clear"):
                self.display_manager.clear()
            self.display_manager.image.paste(image, (0, 0))
            self.display_manager.update_display()
        except Exception as e:
            self.logger.warning("Cricket display push failed: %s", e)
            return False
        return True

    def _pick_default_mode(self) -> str:
        if self.mode_enabled.get(MODE_LIVE, True) and self.live_matches:
            return MODE_LIVE
        if self.mode_enabled.get(MODE_RECENT, True) and self.recent_matches:
            return MODE_RECENT
        if self.mode_enabled.get(MODE_UPCOMING, True) and self.upcoming_matches:
            return MODE_UPCOMING
        return MODE_LIVE

    # ------------------------------------------------------------------ #
    # Duration / cycling contract
    # ------------------------------------------------------------------ #

    def get_display_duration(self, display_mode: str = None) -> float:
        return self.get_cycle_duration(display_mode) or self.display_duration

    def get_cycle_duration(self, display_mode: str = None) -> Optional[float]:
        mode = display_mode or self._pick_default_mode()
        matches = self._matches_for_mode(mode)
        if not matches:
            return self.display_duration

        # Explicit mode-level override wins.
        mode_durations = self.config.get("mode_durations", {}) or {}
        override = mode_durations.get(f"{mode.replace('cricket_', '')}_mode_duration")
        if override:
            return float(override)

        per = sum(self._per_item_duration(mode, m) for m in matches)
        dyn = self.config.get("dynamic_duration", {}) or {}
        if dyn.get("enabled", False):
            lo = float(dyn.get("min_duration_seconds", 30))
            hi = float(dyn.get("max_duration_seconds", 300))
            return max(lo, min(per, hi))
        return per

    def supports_dynamic_duration(self) -> bool:
        return bool((self.config.get("dynamic_duration", {}) or {}).get("enabled", False))

    # ------------------------------------------------------------------ #
    # Live priority contract
    # ------------------------------------------------------------------ #

    def has_live_priority(self) -> bool:
        return self.is_enabled and self.live_priority

    def has_live_content(self) -> bool:
        if not self.is_enabled or not self.mode_enabled.get(MODE_LIVE, True):
            return False
        with self._lock:
            return len(self.live_matches) > 0

    def get_live_modes(self) -> List[str]:
        return [MODE_LIVE] if self.has_live_content() else []

    # ------------------------------------------------------------------ #
    # Vegas hooks
    # ------------------------------------------------------------------ #

    def get_vegas_content_type(self) -> str:
        return "multi"

    def get_vegas_content(self) -> Optional[List[Image.Image]]:
        cards: List[Image.Image] = []
        for mode in (MODE_LIVE, MODE_RECENT, MODE_UPCOMING):
            if not self.mode_enabled.get(mode, True):
                continue
            for match in self._matches_for_mode(mode):
                try:
                    cards.append(self._render_match(mode, match))
                except Exception as e:
                    self.logger.debug("Vegas card render failed: %s", e)
        return cards or None

    def get_vegas_display_mode(self):
        if VegasDisplayMode is not None:
            return VegasDisplayMode.SCROLL
        return None

    # ------------------------------------------------------------------ #
    # Config lifecycle
    # ------------------------------------------------------------------ #

    def validate_config(self, config: Dict[str, Any] = None) -> bool:
        cfg = config if config is not None else self.config
        if not isinstance(cfg, dict):
            return False
        comps = cfg.get("favorite_competitions", [])
        if comps and not isinstance(comps, list):
            return False
        teams = cfg.get("favorite_teams", [])
        if teams and not isinstance(teams, list):
            return False
        return True

    def on_config_change(self, new_config: Dict[str, Any]) -> None:
        if BasePlugin:
            try:
                super().on_config_change(new_config)
            except Exception:
                self.logger.debug("BasePlugin on_config_change failed", exc_info=True)
        # Re-run __init__ derived state without recreating the object, but
        # preserve the lock in place -- another thread may be holding it
        # inside update()/display(), and replacing it would break mutual
        # exclusion.
        lock = self._lock
        self.__init__(self.plugin_id, new_config, self.display_manager,
                      self.cache_manager, self.plugin_manager)
        self._lock = lock
        # Force a re-discovery + refetch on next update.
        self._last_update = 0.0

    def get_info(self) -> Dict[str, Any]:
        info = {}
        if BasePlugin:
            try:
                info = super().get_info()
            except Exception:
                info = {}
        info.update({
            "name": "Cricket Scoreboard",
            "enabled": self.is_enabled,
            "live": len(self.live_matches),
            "recent": len(self.recent_matches),
            "upcoming": len(self.upcoming_matches),
            "competitions": [c.get("key") for c in self.competitions],
        })
        return info


def _min_dt():
    from datetime import datetime, timezone
    return datetime.min.replace(tzinfo=timezone.utc)


def _max_dt():
    from datetime import datetime, timezone
    return datetime.max.replace(tzinfo=timezone.utc)
