"""
Masters Tournament Plugin

Main plugin class for the Masters Tournament LED display.
Displays live leaderboards, player cards, course imagery, hole maps,
fun facts, past champions, and Augusta National branding year-round.
"""

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from PIL import Image

from src.plugin_system.base_plugin import BasePlugin, VegasDisplayMode

from masters_data import MastersDataSource
from masters_renderer import MastersRenderer
from masters_renderer_enhanced import MastersRendererEnhanced
from logo_loader import MastersLogoLoader
from masters_helpers import (
    AUGUSTA_HOLES,
    _masters_thursday,
    calculate_tournament_countdown,
    filter_favorite_players,
    get_detailed_phase,
    get_score_description,
    get_tournament_phase,
    sort_leaderboard,
)

logger = logging.getLogger(__name__)


class MastersTournamentPlugin(BasePlugin):
    """
    Masters Tournament Plugin.

    Displays Masters Tournament leaderboards, player cards, course imagery,
    hole maps, fun facts, and historical data year-round with authentic
    Augusta National branding.
    """

    def __init__(self, plugin_id, config, display_manager, cache_manager, plugin_manager):
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)

        # Display dimensions
        if hasattr(display_manager, "matrix") and display_manager.matrix:
            self.display_width = display_manager.matrix.width
            self.display_height = display_manager.matrix.height
        else:
            self.display_width = getattr(display_manager, "width", 64)
            self.display_height = getattr(display_manager, "height", 32)

        # Display duration
        self.display_duration = config.get("display_duration", 20)

        # Initialize components
        self.logo_loader = MastersLogoLoader(os.path.dirname(os.path.abspath(__file__)))
        self.data_source = MastersDataSource(cache_manager, config)

        # Live tournament metadata (start/end dates, status, round).
        # Populated from ESPN on first fetch; drives countdown + phase detection.
        self._tournament_meta: Optional[Dict] = None
        try:
            self._tournament_meta = self.data_source.fetch_tournament_meta()
        except Exception as e:
            self.logger.warning(f"Initial tournament meta fetch failed: {e}")

        # Use enhanced renderer for 64x32+, base for tiny displays
        if self.display_width >= 64:
            self.renderer = MastersRendererEnhanced(
                self.display_width,
                self.display_height,
                config,
                self.logo_loader,
                self.logger,
            )
        else:
            self.renderer = MastersRenderer(
                self.display_width,
                self.display_height,
                config,
                self.logo_loader,
                self.logger,
            )

        # Data state
        self._leaderboard_data: List[Dict] = []
        self._player_data: Dict[str, Dict] = {}
        self._schedule_data: List[Dict] = []
        self._last_update = 0
        self._update_interval = config.get("update_interval", 30)

        # How many days after the final round to keep showing tournament data
        # before the countdown takes over. Default: 1 day.
        self._post_tournament_display_days = config.get("post_tournament_display_days", 1)

        # Tournament phase — date-driven from live meta when available
        meta_start, meta_end = self._meta_dates()
        self._tournament_phase = get_tournament_phase(start_date=meta_start, end_date=meta_end)
        self._detailed_phase = get_detailed_phase(
            start_date=meta_start,
            end_date=meta_end,
            post_tournament_display_days=self._post_tournament_display_days,
        )

        # Build enabled modes (phase-aware)
        self.modes = self._build_enabled_modes()

        # Current mode tracking
        self.current_mode_index = 0
        self._current_display_mode: Optional[str] = None

        # Course tour state (separate cursors so modes don't interfere)
        self._current_hole = 1
        self._featured_hole_index = 0

        # Pagination state for each mode (auto-advances each display cycle)
        self._page = {
            "leaderboard": 0,
            "champions": 0,
            "stats": 0,
            "schedule": 0,
            "course_overview": 0,
        }

        # Fun fact rotation + scroll
        self._fact_index = 0
        self._fact_scroll = 0

        # Internal timers for modes that rotate content within a display cycle
        self._last_hole_advance = {}  # per-mode hole timers
        self._hole_switch_interval = config.get("hole_display_duration", 15)
        self._last_fact_advance = 0
        self._fact_advance_interval = 3  # seconds between scroll steps
        self._last_page_advance = {}  # per-mode page timers
        self._page_interval = config.get("page_display_duration", 15)

        # Player card rotation — dwell on each card for N seconds.
        self._player_card_index = 0
        self._last_player_card_advance = 0.0
        self._player_card_interval = config.get("player_card_duration", 8)

        # Live alert detection — track score and hole state between updates
        self._previous_scores: Dict[str, int] = {}  # player_name -> score
        self._previous_thru: Dict[str, int] = {}  # player_name -> thru (holes completed)
        self._alert_queue: List[Dict] = []  # pending birdie/eagle alerts
        self._alert_index = 0
        self._last_alert_advance = 0.0
        self._alert_dwell = config.get("display_modes", {}).get(
            "live_action", {}
        ).get("duration", 10)

        # Vegas scroll mode: fixed card block width. Cards render at
        # (scroll_card_width × display_height) regardless of the panel width
        # so long chained displays (e.g. 5×64 = 320 wide) scroll smoothly
        # instead of showing one player per full-panel card.
        self._scroll_card_width = config.get("scroll_card_width", 128)

        self.logger.info(
            f"Masters Tournament plugin initialized: {self.display_width}x{self.display_height}, "
            f"{len(self.modes)} modes, phase: {self._tournament_phase}"
        )

    # ── Phase-aware mode definitions ──
    # Each phase lists modes in priority order (shown most → least)
    # The framework rotates through these, so order = screen time priority

    PHASE_MODES = {
        "off-season": [
            # masters_countdown appears 3x out of 10 entries (~30% screen time)
            # so it dominates the rotation after the post-tournament window closes.
            "masters_countdown",
            "masters_countdown",
            "masters_fun_facts",
            "masters_past_champions",
            "masters_course_tour",
            "masters_hole_by_hole",
            "masters_amen_corner",
            "masters_course_overview",
            "masters_tournament_stats",
            "masters_countdown",
        ],
        "pre-tournament": [
            "masters_countdown",
            "masters_fun_facts",
            "masters_course_tour",
            "masters_hole_by_hole",
            "masters_course_overview",
            "masters_amen_corner",
            "masters_featured_holes",
            "masters_past_champions",
            "masters_tournament_stats",
        ],
        "practice": [
            "masters_schedule",
            "masters_course_tour",
            "masters_hole_by_hole",
            "masters_fun_facts",
            "masters_course_overview",
            "masters_amen_corner",
            "masters_featured_holes",
            "masters_past_champions",
            "masters_countdown",
        ],
        "tournament-morning": [
            "masters_schedule",
            "masters_leaderboard",
            "masters_field_overview",
            "masters_hole_by_hole",
            "masters_fun_facts",
            "masters_course_overview",
            "masters_amen_corner",
        ],
        "tournament-live": [
            "masters_leaderboard",
            "masters_player_card",
            "masters_leaderboard",       # Show leaderboard twice per cycle
            "masters_field_overview",
            "masters_live_action",
            "masters_leaderboard",       # And a third time - it's the star
            "masters_featured_holes",
            "masters_amen_corner",
            "masters_schedule",
            "masters_tournament_stats",
        ],
        "tournament-evening": [
            "masters_leaderboard",
            "masters_player_card",
            "masters_past_champions",
            "masters_tournament_stats",
            "masters_hole_by_hole",
            "masters_fun_facts",
            "masters_field_overview",
            "masters_course_overview",
        ],
        "tournament-overnight": [
            "masters_leaderboard",
            "masters_fun_facts",
            "masters_past_champions",
            "masters_course_tour",
            "masters_countdown",
        ],
        "post-tournament": [
            "masters_leaderboard",
            "masters_player_card",
            "masters_past_champions",
            "masters_tournament_stats",
            "masters_fun_facts",
        ],
    }

    def _meta_dates(self):
        """Return (start_date, end_date) from cached meta, or (None, None)."""
        meta = self._tournament_meta or {}
        return meta.get("start_date"), meta.get("end_date")

    def _build_enabled_modes(self) -> List[str]:
        """Build mode list based on current tournament phase and time of day.

        The framework rotates through self.modes, so this controls what
        the user sees and in what order. Modes listed multiple times get
        proportionally more screen time.
        """
        meta_start, meta_end = self._meta_dates()
        phase = get_detailed_phase(
            start_date=meta_start,
            end_date=meta_end,
            post_tournament_display_days=self._post_tournament_display_days,
        )
        phase_modes = self.PHASE_MODES.get(phase, self.PHASE_MODES["off-season"])

        # Filter by user config (respect per-mode enabled/disabled)
        display_modes_config = self.config.get("display_modes", {})
        config_key_map = {
            "masters_leaderboard":      "leaderboard",
            "masters_player_card":      "player_cards",
            "masters_hole_by_hole":     "hole_by_hole",
            "masters_live_action":      "live_action",
            "masters_course_tour":      "course_tour",
            "masters_amen_corner":      "amen_corner",
            "masters_featured_holes":   "featured_holes",
            "masters_schedule":         "schedule",
            "masters_past_champions":   "past_champions",
            "masters_tournament_stats": "tournament_stats",
            "masters_fun_facts":        "fun_facts",
            "masters_countdown":        "countdown",
            "masters_field_overview":   "field_overview",
            "masters_course_overview":  "course_overview",
        }

        enabled = []
        for mode in phase_modes:
            config_key = config_key_map.get(mode)
            if config_key:
                mode_config = display_modes_config.get(config_key, {})
                if mode_config.get("enabled", True):
                    enabled.append(mode)

        self.logger.debug(f"Phase '{phase}' -> {len(enabled)} modes: {enabled}")
        return enabled

    def update(self):
        """Fetch and update all Masters Tournament data."""
        now = time.time()
        if now - self._last_update < self._update_interval:
            return

        self.logger.info("Updating Masters Tournament data...")
        self._last_update = now

        # Refresh tournament meta (cheap — reads cache populated by leaderboard fetch)
        try:
            self._tournament_meta = self.data_source.fetch_tournament_meta()
        except Exception as e:
            self.logger.warning(f"Tournament meta refresh failed: {e}")

        meta_start, meta_end = self._meta_dates()
        self._tournament_phase = get_tournament_phase(
            start_date=meta_start, end_date=meta_end
        )

        # Refresh modes based on current phase/time of day
        # This lets modes shift automatically (e.g., morning → live → evening)
        new_modes = self._build_enabled_modes()
        if new_modes != self.modes:
            old_phase = self._detailed_phase
            self._detailed_phase = get_detailed_phase(
                start_date=meta_start,
                end_date=meta_end,
                post_tournament_display_days=self._post_tournament_display_days,
            )
            self.modes = new_modes
            self.logger.info(
                f"Phase changed: {old_phase} -> {self._detailed_phase}, "
                f"now showing {len(self.modes)} modes"
            )

        try:
            self._update_leaderboard()
        except Exception as e:
            self.logger.error(f"Error updating leaderboard: {e}", exc_info=True)

        try:
            self._update_schedule()
        except Exception as e:
            self.logger.error(f"Error updating schedule: {e}", exc_info=True)

        try:
            self._update_favorite_players()
        except Exception as e:
            self.logger.error(f"Error updating favorite players: {e}", exc_info=True)

    def _update_leaderboard(self):
        """Update leaderboard data from API."""
        raw_leaderboard = self.data_source.fetch_leaderboard()
        if not raw_leaderboard:
            return

        sorted_board = sort_leaderboard(raw_leaderboard)

        # Detect score changes for live alerts before filtering
        self._detect_score_changes(sorted_board)

        favorites = self.config.get("favorite_players", [])
        top_n = self.config.get("display_modes", {}).get("leaderboard", {}).get("top_n", 10)
        always_show = self.config.get("display_modes", {}).get("leaderboard", {}).get(
            "show_favorites_always", True
        )

        self._leaderboard_data = filter_favorite_players(
            sorted_board, favorites, top_n=top_n, always_show_favorites=always_show
        )
        self.logger.debug(f"Updated leaderboard with {len(self._leaderboard_data)} players")

    def _detect_score_changes(self, leaderboard: List[Dict]) -> None:
        """Compare current scores against previous update to detect birdies/eagles.

        Only generates alerts when exactly one hole was completed since the last
        poll (previous_thru + 1 == current_thru). When multiple holes elapsed
        between polls the aggregate delta can't be attributed to a single hole,
        so we skip the alert and just update stored state.
        """
        new_scores: Dict[str, int] = {}
        new_thru: Dict[str, int] = {}
        new_alerts: List[Dict] = []

        for player in leaderboard:
            name = player.get("player", "")
            score = player.get("score", 0)
            hole = player.get("current_hole") or 0
            thru = player.get("thru", 0)
            if isinstance(thru, str):
                try:
                    thru = int(thru) if thru.strip() not in ("", "F", "-") else 0
                except ValueError:
                    thru = 0
            new_scores[name] = score
            new_thru[name] = thru

            if not self._previous_scores or name not in self._previous_scores:
                continue

            prev_score = self._previous_scores[name]
            prev_thru = self._previous_thru.get(name, 0)

            change = score - prev_score  # negative = improvement
            if change >= 0:
                continue

            # Only classify when exactly one hole was completed since last poll
            if thru != prev_thru + 1:
                self.logger.debug(
                    f"Skipping alert for {name}: thru jumped {prev_thru}->{thru} "
                    f"(score {prev_score}->{score})"
                )
                continue

            hole_par = AUGUSTA_HOLES.get(hole, {}).get("par", 4)
            desc = get_score_description(change, hole_par)

            if desc in ("Birdie", "Eagle", "Albatross"):
                new_alerts.append({
                    "player": name,
                    "hole": hole,
                    "score_desc": desc,
                })
                self.logger.info(f"Live alert: {name} {desc} on hole {hole}")

        self._previous_scores = new_scores
        self._previous_thru = new_thru

        if new_alerts:
            self._alert_queue = new_alerts
            self._alert_index = 0
            self._last_alert_advance = time.time()

    def _update_schedule(self):
        """Update schedule data from API."""
        self._schedule_data = self.data_source.fetch_schedule()

    def _update_favorite_players(self):
        """Fetch detailed data for favorite players."""
        favorites = self.config.get("favorite_players", [])
        if not favorites:
            return

        for player in self._leaderboard_data:
            player_name = player.get("player", "")
            if any(fav.lower() in player_name.lower() for fav in favorites):
                player_id = player.get("player_id", "")
                if player_id:
                    details = self.data_source.fetch_player_details(player_id)
                    if details:
                        self._player_data[player_id] = details

    def display(self, force_clear: bool = False, display_mode: Optional[str] = None) -> bool:
        """Render the current display mode."""
        if not self.enabled:
            return False

        if display_mode is None:
            display_mode = self.modes[0] if self.modes else None

        if display_mode is None:
            return False

        self._current_display_mode = display_mode

        if force_clear:
            self.display_manager.clear()

        dispatch = {
            "masters_leaderboard":      self._display_leaderboard,
            "masters_player_card":      self._display_player_cards,
            "masters_course_tour":      self._display_course_tour,
            "masters_amen_corner":      self._display_amen_corner,
            "masters_past_champions":   self._display_past_champions,
            "masters_hole_by_hole":     self._display_hole_by_hole,
            "masters_featured_holes":   self._display_featured_holes,
            "masters_schedule":         self._display_schedule,
            "masters_live_action":      self._display_live_action,
            "masters_tournament_stats": self._display_tournament_stats,
            "masters_fun_facts":        self._display_fun_facts,
            "masters_countdown":        self._display_countdown,
            "masters_field_overview":   self._display_field_overview,
            "masters_course_overview":  self._display_course_overview,
        }

        handler = dispatch.get(display_mode)
        if handler:
            return handler(force_clear)

        self.logger.warning(f"Unknown display mode: {display_mode}")
        return False

    def _advance_page(self, key: str) -> int:
        """Return current page for a mode, advancing only after page_interval seconds."""
        now = time.time()
        last = self._last_page_advance.get(key, 0)
        if last > 0 and now - last >= self._page_interval:
            self._page[key] = self._page.get(key, 0) + 1
            self._last_page_advance[key] = now
        elif last == 0:
            self._last_page_advance[key] = now
        return self._page.get(key, 0)

    def _show_image(self, image: Optional[Image.Image]) -> bool:
        """Helper to display an image if it exists."""
        if image:
            self.display_manager.image.paste(image, (0, 0))
            self.display_manager.update_display()
            return True
        return False

    def _display_leaderboard(self, force_clear: bool) -> bool:
        if not self._leaderboard_data:
            return False
        page = self._advance_page("leaderboard")
        return self._show_image(
            self.renderer.render_leaderboard(self._leaderboard_data, show_favorites=True, page=page)
        )

    def _display_player_cards(self, force_clear: bool) -> bool:
        if not self._leaderboard_data:
            return False
        # Rotate through top players on a dwell timer (not every frame) so
        # viewers actually get to read each card.
        now = time.time()
        if self._last_player_card_advance == 0.0:
            self._last_player_card_advance = now
        elif now - self._last_player_card_advance >= self._player_card_interval:
            self._player_card_index += 1
            self._last_player_card_advance = now
        idx = self._player_card_index % min(5, len(self._leaderboard_data))
        player = self._leaderboard_data[idx]
        return self._show_image(self.renderer.render_player_card(player))

    def _display_course_tour(self, force_clear: bool) -> bool:
        now = time.time()
        last = self._last_hole_advance.get("course_tour", 0)
        if last > 0 and now - last >= self._hole_switch_interval:
            self._current_hole = (self._current_hole % 18) + 1
            self._last_hole_advance["course_tour"] = now
        elif last == 0:
            self._last_hole_advance["course_tour"] = now
        show_divider = self.config.get("display_modes", {}).get(
            "course_tour", {}
        ).get("show_divider", True)
        return self._show_image(
            self.renderer.render_hole_card(self._current_hole, show_divider=show_divider)
        )

    def _display_amen_corner(self, force_clear: bool) -> bool:
        return self._show_image(self.renderer.render_amen_corner())

    def _display_past_champions(self, force_clear: bool) -> bool:
        page = self._advance_page("champions")
        return self._show_image(self.renderer.render_past_champions(page=page))

    def _display_hole_by_hole(self, force_clear: bool) -> bool:
        """Display hole-by-hole course tour (same as course_tour)."""
        return self._display_course_tour(force_clear)

    def _display_featured_holes(self, force_clear: bool) -> bool:
        featured = [12, 13, 15, 16]
        now = time.time()
        last = self._last_hole_advance.get("featured", 0)
        if last > 0 and now - last >= self._hole_switch_interval:
            self._featured_hole_index += 1
            self._last_hole_advance["featured"] = now
        elif last == 0:
            self._last_hole_advance["featured"] = now
        hole = featured[self._featured_hole_index % len(featured)]
        show_divider = self.config.get("display_modes", {}).get(
            "course_tour", {}
        ).get("show_divider", True)
        return self._show_image(self.renderer.render_hole_card(hole, show_divider=show_divider))

    def _display_schedule(self, force_clear: bool) -> bool:
        page = self._advance_page("schedule")
        return self._show_image(
            self.renderer.render_schedule(self._schedule_data, page=page)
        )

    def _display_live_action(self, force_clear: bool) -> bool:
        """Show live birdie/eagle alerts, falling back to the leader."""
        if not hasattr(self.renderer, "render_live_alert"):
            return self._display_leaderboard(force_clear)

        # Rotate through queued alerts on a dwell timer
        if self._alert_queue:
            now = time.time()
            if now - self._last_alert_advance >= self._alert_dwell:
                self._alert_index += 1
                self._last_alert_advance = now
            # Expire the queue once we've shown all alerts
            if self._alert_index >= len(self._alert_queue):
                self._alert_queue = []
                self._alert_index = 0
            else:
                alert = self._alert_queue[self._alert_index]
                return self._show_image(
                    self.renderer.render_live_alert(
                        alert["player"],
                        alert["hole"],
                        alert["score_desc"],
                    )
                )

        # No pending alerts — show the leader's current status
        if self._leaderboard_data:
            leader = self._leaderboard_data[0]
            return self._show_image(
                self.renderer.render_live_alert(
                    leader.get("player", ""),
                    leader.get("current_hole", 18) or 18,
                    "Leader",
                )
            )
        return self._display_leaderboard(force_clear)

    def _display_tournament_stats(self, force_clear: bool) -> bool:
        page = self._advance_page("stats")
        return self._show_image(self.renderer.render_tournament_stats(page=page))

    def _display_fun_facts(self, force_clear: bool) -> bool:
        result = self._show_image(
            self.renderer.render_fun_fact(self._fact_index, scroll_offset=self._fact_scroll)
        )
        now = time.time()
        if now - self._last_fact_advance >= self._fact_advance_interval:
            self._fact_scroll += 1
            self._last_fact_advance = now
        # Derive scroll steps from actual wrapped line count for this fact.
        total_lines, visible = self.renderer.get_fun_fact_line_count(
            self._fact_index,
        )
        max_scroll = max(1, total_lines - visible + 1)
        if self._fact_scroll >= max_scroll:
            self._fact_index += 1
            self._fact_scroll = 0
        return result

    def _display_countdown(self, force_clear: bool) -> bool:
        # Use live ESPN-derived tournament start date. Falls back to a computed
        # second-Thursday-of-April inside the data source if ESPN isn't serving
        # the Masters (off-season).
        meta = self._tournament_meta or self.data_source.fetch_tournament_meta()
        if meta and meta.get("start_date"):
            target = meta["start_date"]
        else:
            # Hard fallback — should be unreachable, but keep the screen alive.
            now = datetime.now(timezone.utc)
            year = now.year
            target = _masters_thursday(year)
            if target <= now:
                target = _masters_thursday(year + 1)
        countdown = calculate_tournament_countdown(target)
        return self._show_image(
            self.renderer.render_countdown(
                countdown["days"], countdown["hours"], countdown["minutes"]
            )
        )

    def _display_field_overview(self, force_clear: bool) -> bool:
        if not self._leaderboard_data:
            return False
        return self._show_image(self.renderer.render_field_overview(self._leaderboard_data))

    def _display_course_overview(self, force_clear: bool) -> bool:
        if hasattr(self.renderer, "render_course_overview"):
            page = self._advance_page("course_overview")
            return self._show_image(self.renderer.render_course_overview(page=page))
        return self._display_amen_corner(force_clear)

    def get_vegas_content(self) -> Optional[List[Image.Image]]:
        """Return cards for Vegas scroll mode.

        Cards are rendered at (scroll_card_width × display_height), not the
        full panel width — on a long chained display (e.g. 5×64 = 320 wide)
        this gives you a smoothly-scrolling ticker of ~128-wide blocks
        instead of one full-panel card at a time. Matches the pattern used
        by the other sports scoreboard plugins.

        Content is phase-aware:
          off-season / pre-tournament  → countdown card only
          practice / tournament / post → leaderboard + holes + fun facts
        """
        meta_start, meta_end = self._meta_dates()
        phase = get_detailed_phase(
            start_date=meta_start,
            end_date=meta_end,
            post_tournament_display_days=self._post_tournament_display_days,
        )

        cw = self._scroll_card_width
        ch = self.display_height

        # Off-season and pre-tournament: countdown card only.
        if phase in ("off-season", "pre-tournament"):
            countdown_enabled = self.config.get("display_modes", {}).get(
                "countdown", {}
            ).get("enabled", True)
            if not countdown_enabled:
                return None
            meta = self._tournament_meta or {}
            target = meta.get("start_date")
            # If the cached start_date is already in the past (stale meta from a
            # prior year), treat it as missing so we fall back to the computed date.
            if target is not None:
                t_aware = target if target.tzinfo else target.replace(tzinfo=timezone.utc)
                if t_aware <= datetime.now(timezone.utc):
                    target = None
            if target is None:
                target = self.data_source._computed_fallback_meta().get("start_date")
            if not target:
                return None
            countdown = calculate_tournament_countdown(target)
            card = self.renderer.render_countdown(
                countdown["days"], countdown["hours"], countdown["minutes"],
                card_width=cw, card_height=ch,
            )
            if not card:
                return None
            return [card]

        # Practice / tournament / post-tournament: leaderboard + holes + fun facts.
        cards = []
        for player in self._leaderboard_data[:10]:
            card = self.renderer.render_player_card(
                player, card_width=cw, card_height=ch,
            )
            if card:
                cards.append(card)

        show_divider = self.config.get("display_modes", {}).get(
            "course_tour", {}
        ).get("show_divider", True)
        for hole in range(1, 19):
            card = self.renderer.render_hole_card(
                hole, card_width=cw, card_height=ch, show_divider=show_divider,
            )
            if card:
                cards.append(card)

        fun_facts_enabled = self.config.get("display_modes", {}).get(
            "fun_facts", {}
        ).get("enabled", True)
        if fun_facts_enabled:
            for i in range(5):
                card = self.renderer.render_fun_fact_vegas(
                    i, card_height=ch,
                )
                if card:
                    cards.append(card)

        return cards if cards else None

    def get_vegas_content_type(self) -> str:
        return "multi"

    def get_vegas_display_mode(self) -> VegasDisplayMode:
        return VegasDisplayMode.SCROLL

    def get_info(self) -> Dict[str, Any]:
        """Return plugin info."""
        info = super().get_info()
        info.update({
            "name": "Masters Tournament",
            "enabled_modes": self.modes,
            "mode_count": len(self.modes),
            "last_update": self._last_update,
            "tournament_phase": self._tournament_phase,
            "has_leaderboard": bool(self._leaderboard_data),
            "player_count": len(self._leaderboard_data),
            "mock_mode": self.config.get("mock_data", False),
        })
        return info

    def on_config_change(self, new_config):
        """Handle config changes."""
        super().on_config_change(new_config)
        self._update_interval = new_config.get("update_interval", 30)
        self.display_duration = new_config.get("display_duration", 20)
        self._hole_switch_interval = new_config.get("hole_display_duration", 15)
        self._page_interval = new_config.get("page_display_duration", 15)
        self._player_card_interval = new_config.get("player_card_duration", 8)
        self._scroll_card_width = new_config.get("scroll_card_width", 128)
        self._post_tournament_display_days = new_config.get("post_tournament_display_days", 1)
        self._last_hole_advance.clear()
        self._last_page_advance.clear()
        self.modes = self._build_enabled_modes()
        self._last_update = 0

    def cleanup(self):
        """Clean up resources."""
        try:
            self.logo_loader.clear_cache()
            self.logger.info("Masters Tournament cleanup completed")
        except Exception:
            self.logger.exception("Error during Masters Tournament cleanup")
        super().cleanup()
