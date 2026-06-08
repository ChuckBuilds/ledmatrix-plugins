"""
Election Results plugin.

Orchestrates providers -> RaceStore -> renderer. Runs a throttled update loop,
renders a scrolling ticker of races in normal rotation, and uses the core's
live-priority preemption to take over the screen with a full-screen card when a
race is newly called.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any, Dict, List, Optional

from PIL import Image

from src.plugin_system.base_plugin import BasePlugin
from src.common.scroll_helper import ScrollHelper

# Plugin-local imports (the plugin directory is on sys.path at load time, but be
# defensive in case it isn't).
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import json  # noqa: E402
from datetime import date  # noqa: E402

from data_model import Race  # noqa: E402
from providers import create_providers  # noqa: E402
from providers.nyt import NytStaticProvider  # noqa: E402
from store import RaceStore  # noqa: E402
from election_calendar import ElectionEvent, resolve_active  # noqa: E402
import renderer  # noqa: E402

_FIXTURE_DIR = os.path.join(_HERE, "test", "fixtures")


class ElectionPlugin(BasePlugin):
    """Scrolling election ticker + full-screen 'race called' interrupt."""

    def __init__(self, plugin_id, config, display_manager, cache_manager, plugin_manager):
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)

        self.display_width = getattr(display_manager, "width", 64)
        self.display_height = getattr(display_manager, "height", 32)

        # Config
        self.state = (config.get("state") or "").upper() or None
        self.only_my_state = config.get("only_my_state", True)
        self.race_types = config.get("race_types") or None
        # Local legislative races to surface, by office -> your district number.
        # The baseline carries every district; these pick out the user's own.
        self.local_districts = self._build_local_districts(config)
        self.update_interval = int(config.get("update_interval", 60))
        self.display_duration = float(config.get("display_duration", 30))
        # Hide a race from the ticker this long after it was called, so the
        # ticker drains as results settle (uncalled + fresh calls stay).
        self.hide_called_after = float(config.get("hide_called_after_seconds", 86400))
        # test_mode renders bundled fixtures offline (demo / harness goldens),
        # mirroring the sports-plugin test_mode convention.
        self.test_mode = config.get("test_mode", False)

        # Calendar / override: which election (if any) is active right now.
        self.override_cfg = config.get("override", {}) or {}
        self.calendar_events_cfg = config.get("calendar_events", []) or []
        # Resolved each update; drive the fetch state + cold-start call seeding.
        self._fetch_state = self.state
        self._election_day_ts = 0.0

        interrupt_cfg = config.get("interrupt", {}) or {}
        self.interrupt_enabled = interrupt_cfg.get("enabled", True)
        self.interrupt_duration = float(interrupt_cfg.get("duration_seconds", 12))
        self.interrupt_my_state_only = interrupt_cfg.get("my_state_only", True)
        self.interrupt_max_age = float(interrupt_cfg.get("max_age_seconds", 300))

        ca_cfg = (config.get("providers", {}) or {}).get("ca_sos", {}) or {}
        override_votes = ca_cfg.get("override_nyt_votes", True)

        # Components
        self.providers = create_providers(config, cache_manager)
        self.store = RaceStore(override_votes=override_votes, cache_manager=cache_manager)

        self.scroll_speed = float(config.get("scroll_speed", 1.0))
        self.scroll_delay = float(config.get("scroll_delay", 0.01))
        self.scroll_helper = ScrollHelper(self.display_width, self.display_height, self.logger)
        self.scroll_helper.set_frame_based_scrolling(True)
        self.scroll_helper.set_scroll_speed(self.scroll_speed)
        self.scroll_helper.set_scroll_delay(self.scroll_delay)
        self.scroll_helper.set_dynamic_duration_settings(
            enabled=True, min_duration=int(self.display_duration), max_duration=300
        )

        # State
        self.races: List[Race] = []
        self._segments: List[Image.Image] = []
        self._last_update = 0.0
        self._scroll_ready = False
        # Signals the display controller to drive this plugin at high FPS so the
        # ticker scrolls smoothly (same hook the stock/news tickers use).
        self.enable_scrolling = True

        # Interrupt queue
        self._pending_calls: List[Race] = []
        self._current_call: Optional[Race] = None
        self._current_call_start = 0.0
        # Tracks whether the last rendered frame was a called card, so the
        # display duration is the short interrupt window and not the ticker's
        # (much longer) dynamic duration.
        self._showing_called = False

        self.logger.info(
            "Elections plugin initialized: state=%s providers=%s",
            self.state, [p.name for p in self.providers],
        )

    # -- Update loop --------------------------------------------------------

    def update(self) -> None:
        now = time.time()
        if self._last_update and (now - self._last_update) < self.update_interval:
            return
        self._last_update = now

        try:
            if self.test_mode:
                # Fixtures are the CA June 2 primary; treat it as the active election.
                self._fetch_state = self.state or "CA"
                ev = ElectionEvent(state=self._fetch_state, date="2026-06-02", type="primary")
                self._election_day_ts = ev.election_day_ts()
                self.store.set_election(f"{self._fetch_state}_2026-06-02_primary")
                provider_results = self._fixture_provider_results()
            else:
                active = self._resolve_active(now)
                if active is None:
                    self._go_dormant()
                    return
                self._apply_active(active)
                provider_results = []
                for provider in self.providers:
                    try:
                        races = provider.fetch(self._fetch_state)
                        provider_results.append((provider, races))
                    except Exception as e:
                        self.logger.error("Provider %s fetch failed: %s", provider.name, e)

            merged = self.store.merge(provider_results)

            # Detect newly-called races first so called_at is stamped before the
            # visibility filter ages them out. Operates on the full merged set so
            # a race called outside the filter is still tracked. Races already
            # called at cold start are seeded at election day (see the store).
            newly = self.store.diff_newly_called(merged, now, cold_start_ts=self._election_day_ts)
            if self.interrupt_enabled:
                self._enqueue_calls(newly, now)

            filtered = self.store.filter_races(
                merged, self._fetch_state, self.only_my_state, self.race_types,
                self.local_districts,
            )
            visible = self.store.filter_visible(filtered, now, self.hide_called_after)
            self.races = self.store.sort_by_importance(visible)

            self._build_scroll_image()
            self.logger.info(
                "Elections updated: %d races shown, %d pending calls",
                len(self.races), len(self._pending_calls),
            )
        except Exception as e:
            self.logger.error("Error during update: %s", e, exc_info=True)

    # -- Active-election resolution (calendar + override) -------------------

    def _resolve_active(self, now: float) -> Optional[ElectionEvent]:
        """The election to show right now, or None when the plugin is dormant.

        A manual override wins; otherwise the built-in calendar decides whether
        today falls inside an election window for the user's state.
        """
        ev = self._override_event()
        if ev is not None:
            return ev
        today = date.fromtimestamp(now)
        return resolve_active(self.state, today, self._config_events())

    def _override_event(self) -> Optional[ElectionEvent]:
        """Build an ElectionEvent from the override config, or None if unset.

        Lets the user force "today is an election day in ZZ" (``active`` +
        optional ``state``/``election_date``) or pin an exact feed
        (``feed_url``/``feed_filename``).
        """
        o = self.override_cfg
        feed_url = (o.get("feed_url") or "").strip()
        date_str = (o.get("election_date") or "").strip()
        if not (o.get("active") or feed_url or date_str):
            return None
        state = (o.get("state") or self.state or "").upper()
        # Default the date to today so "active" alone means "election day now".
        if not date_str:
            date_str = date.today().isoformat()
        return ElectionEvent(
            state=state,
            date=date_str,
            type=(o.get("election_type") or "general"),
            trail_days=int(o.get("trail_days", 14)),
            feed_filename=(o.get("feed_filename") or None),
            feed_url=feed_url or None,
        )

    def _config_events(self) -> List[ElectionEvent]:
        """Extra scheduled elections supplied via the ``calendar_events`` config."""
        out: List[ElectionEvent] = []
        for e in self.calendar_events_cfg:
            try:
                out.append(ElectionEvent(
                    state=(e.get("state") or self.state or "").upper(),
                    date=e["date"],
                    type=e.get("type", "general"),
                    trail_days=int(e.get("trail_days", 14)),
                    feed_filename=(e.get("feed_filename") or None),
                    feed_url=(e.get("feed_url") or None),
                ))
            except Exception:
                self.logger.warning("Elections: ignoring bad calendar_events entry: %s", e)
        return out

    def _apply_active(self, ev: ElectionEvent) -> None:
        """Point the store and providers at the resolved active election."""
        self._fetch_state = ev.state or self.state
        self._election_day_ts = ev.election_day_ts()
        self.store.set_election(f"{ev.state}_{ev.date}_{ev.type}")
        for p in self.providers:
            if isinstance(p, NytStaticProvider):
                p.election_date = ev.date
                p.election_type = ev.type
                p.feed_url_override = ev.feed_url
                p.feed_filename = ev.feed_filename

    def _go_dormant(self) -> None:
        """No active election: clear content so the plugin drops out of rotation."""
        if self.races or self._scroll_ready or self._pending_calls or self._current_call:
            self.logger.info("Elections dormant: no active election for state=%s", self.state)
        self.races = []
        self._pending_calls = []
        self._current_call = None
        self._build_scroll_image()

    def _fixture_provider_results(self):
        """Parse bundled fixtures offline for test_mode (no network)."""
        results = []
        try:
            with open(os.path.join(_FIXTURE_DIR, "nyt_ca_results.json")) as f:
                nyt_data = json.load(f)
            nyt = NytStaticProvider({"election_date": "2026-06-02", "election_type": "primary"})
            results.append((nyt, nyt.parse(nyt_data)))
        except Exception as e:
            self.logger.error("test_mode: NYT fixture load failed: %s", e)

        # CA-SoS is advanced/opt-in and contributes nothing by default (NYT
        # already carries CA's statewide, House, and legislature races with an
        # accurate eevp estimate), so test_mode shows the NYT baseline only.
        return results

    def _first_called_race(self) -> Optional[Race]:
        for r in self.races:
            if r.called:
                return r
        return None

    def _enqueue_calls(self, newly: List[Race], now: float) -> None:
        for race in newly:
            if self.interrupt_my_state_only and not self._passes_state_filter(race):
                continue
            self._pending_calls.append(race)

    def _passes_state_filter(self, race: Race) -> bool:
        kept = self.store.filter_races([race], self._fetch_state, self.only_my_state,
                                       self.race_types, self.local_districts)
        return bool(kept)

    @staticmethod
    def _build_local_districts(config: dict) -> Dict[str, str]:
        """Map legislature chamber ('upper'/'lower') to the user's district number.

        Chamber-neutral keys work for any state; the CA-style ``senate_district``
        / ``assembly_district`` are accepted as aliases.
        """
        out: Dict[str, str] = {}
        sources = {
            "upper": config.get("upper_chamber_district") or config.get("senate_district"),
            "lower": config.get("lower_chamber_district") or config.get("assembly_district"),
        }
        for chamber, raw in sources.items():
            if raw is None:
                continue
            s = str(raw).strip()
            if s.isdigit():
                out[chamber] = s
        return out

    def _build_scroll_image(self) -> None:
        # Pack races into columns that fill the panel height (one race on a 32px
        # panel, more stacked as the panel gets taller), then scroll the columns.
        self._segments = renderer.render_ticker_segments(self.races, self.display_height)
        if self._segments:
            self.scroll_helper.create_scrolling_image(self._segments, item_gap=12, element_gap=6)
            self._scroll_ready = True
        else:
            self.scroll_helper.clear_cache()
            self._scroll_ready = False

    # -- Live-priority (interrupt) hooks ------------------------------------

    def has_live_priority(self) -> bool:
        return self.config.get("live_priority", True)

    def has_live_content(self) -> bool:
        if not self.interrupt_enabled:
            return False
        self._tick_interrupt()
        return self._current_call is not None or bool(self._pending_calls)

    def get_live_modes(self) -> List[str]:
        return ["election_called"]

    def _tick_interrupt(self) -> None:
        """Advance the interrupt queue: expire the current card, pop the next."""
        now = time.time()
        if self._current_call is not None:
            if now - self._current_call_start >= self.interrupt_duration:
                self._current_call = None
        if self._current_call is None and self._pending_calls:
            # Skip calls that have waited longer than max_age (stale).
            while self._pending_calls:
                candidate = self._pending_calls.pop(0)
                age = now - (candidate.called_at or now)
                if age <= self.interrupt_max_age:
                    self._current_call = candidate
                    self._current_call_start = now
                    break

    # -- Display ------------------------------------------------------------

    def display(self, force_clear: bool = False, display_mode: Optional[str] = None) -> bool:
        """Render the current frame.

        Returns False when there's nothing to show (dormant, or the ticker has
        drained to empty) so the display controller skips this mode and rotates
        on without a dead "no data" frame.
        """
        try:
            # Explicit mode (used by the core's live takeover and the test harness).
            if display_mode == "election_ticker":
                return self._display_ticker(force_clear)
            if display_mode == "election_called":
                race = self._current_call or self._first_called_race()
                if race is not None:
                    self._display_called_card(race, force_clear)
                    return True
                return self._display_ticker(force_clear)

            # Default rotation: interrupt if a call is active/pending, else ticker.
            if self.interrupt_enabled and (self._current_call or self._pending_calls):
                self._tick_interrupt()
                if self._current_call is not None:
                    self._display_called_card(self._current_call, force_clear)
                    return True
            return self._display_ticker(force_clear)
        except Exception as e:
            self.logger.error("Error during display: %s", e, exc_info=True)
            return False

    def _display_called_card(self, race: Race, force_clear: bool) -> None:
        self._showing_called = True
        img = renderer.render_called_card(race, self.display_width, self.display_height)
        self.display_manager.image = img
        self.display_manager.update_display()

    def _display_ticker(self, force_clear: bool) -> bool:
        self._showing_called = False
        if not self._scroll_ready:
            return False  # nothing to show; controller skips to the next mode

        if force_clear:
            try:
                self.scroll_helper.reset_scroll()
            except Exception as e:
                self.logger.debug("reset_scroll failed: %s", e)

        try:
            self.display_manager.set_scrolling_state(True)
        except Exception as e:
            self.logger.debug("set_scrolling_state failed: %s", e)

        self.scroll_helper.update_scroll_position()
        visible = self.scroll_helper.get_visible_portion()
        if visible is not None:
            self.display_manager.image.paste(visible, (0, 0))
            self.display_manager.update_display()
        return True

    def get_display_duration(self) -> float:
        # A called card is a brief takeover; don't let it inherit the ticker's
        # duration (which left the card on screen for minutes).
        if self._showing_called:
            return float(self.interrupt_duration)
        if self._scroll_ready:
            return self._one_pass_duration()
        return self.display_duration

    def _one_pass_duration(self) -> float:
        """Seconds for the ticker to scroll through every race exactly once.

        Sized to the real content (one loop, then rotate on) instead of padding
        up to a fixed minimum, which parked the plugin on screen long after the
        races had scrolled by.
        """
        tsw = getattr(self.scroll_helper, "total_scroll_width", 0) or 0
        pps = (self.scroll_speed / self.scroll_delay) if self.scroll_delay > 0 else self.scroll_speed * 50
        if tsw <= 0 or pps <= 0:
            return self.display_duration
        # total_scroll_width is the distance at which the scroller reports the
        # cycle complete, so this lands the rotation right as the last race clears.
        return max(6.0, tsw / pps)

    # -- Vegas hooks --------------------------------------------------------

    def get_vegas_content_type(self) -> str:
        return "multi"

    def get_vegas_content(self) -> Optional[List[Image.Image]]:
        return self._segments or None

    # -- Lifecycle ----------------------------------------------------------

    def get_info(self) -> Dict[str, Any]:
        info = super().get_info()
        info["state"] = self.state
        info["race_count"] = len(self.races)
        info["pending_calls"] = len(self._pending_calls)
        info["providers"] = [p.name for p in self.providers]
        return info

    def cleanup(self) -> None:
        self.logger.info("Cleaning up Elections plugin")
        try:
            self.scroll_helper.clear_cache()
        except Exception as e:
            self.logger.debug("clear_cache failed: %s", e)
        super().cleanup()
