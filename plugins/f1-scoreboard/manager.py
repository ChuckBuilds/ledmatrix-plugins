"""
F1 Scoreboard Plugin

Main plugin class for the Formula 1 Scoreboard.
Displays driver standings, constructor standings, race results, qualifying,
practice, sprint results, upcoming races, and race calendar.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from PIL import Image

from src.plugin_system.base_plugin import BasePlugin, VegasDisplayMode

from f1_data import F1DataSource
from f1_renderer import F1Renderer
from logo_downloader import F1LogoLoader
from scroll_display import ScrollDisplayManager
from team_colors import normalize_constructor_id

from f1_timezone import resolve_timezone_name

logger = logging.getLogger(__name__)


class F1ScoreboardPlugin(BasePlugin):
    """
    Formula 1 Scoreboard Plugin.

    Displays F1 standings, race results, qualifying breakdowns, practice
    standings, sprint results, upcoming races, and race calendar.
    Supports favorite driver/team highlighting and Vegas scroll mode.
    """

    def __init__(self, plugin_id, config, display_manager,
                 cache_manager, plugin_manager):
        super().__init__(plugin_id, config, display_manager,
                        cache_manager, plugin_manager)

        # Display dimensions
        if hasattr(display_manager, "matrix") and display_manager.matrix:
            self.display_width = display_manager.matrix.width
            self.display_height = display_manager.matrix.height
        else:
            self.display_width = getattr(display_manager, "width", 128)
            self.display_height = getattr(display_manager, "height", 32)

        # Favorites
        self.favorite_driver = config.get("favorite_driver", "").upper()
        self.favorite_team = normalize_constructor_id(
            config.get("favorite_team", ""))

        # Display duration
        self.display_duration = config.get("display_duration", 30)

        # Scroll card width: use a fixed card width for scroll mode so cards are
        # properly sized regardless of the full chain width (multi-panel setups)
        scroll_cfg = config.get("scroll", {}) if isinstance(config.get("scroll"), dict) else {}
        self._card_width = scroll_cfg.get("game_card_width", 128)

        # Resolve timezone: plugin config → global config → UTC.
        # Re-resolved on every config change so global timezone updates take
        # effect immediately. Kept in a shallow copy (never written back into
        # `config`) so the resolved value never gets persisted as a stale
        # plugin-level override that would shadow future global changes.
        self.timezone = self._resolve_timezone(config, cache_manager, plugin_manager)
        render_config = {**config, "timezone": self.timezone}

        # Initialize components
        self.logo_loader = F1LogoLoader()
        self.data_source = F1DataSource(cache_manager, render_config)
        # Full-width renderer for static single-card display
        self.renderer = F1Renderer(
            self.display_width, self.display_height,
            render_config, self.logo_loader, self.logger)
        # Card-width renderer for scroll/Vegas mode
        self._scroll_renderer = F1Renderer(
            self._card_width, self.display_height,
            render_config, self.logo_loader, self.logger)
        self._scroll_manager = ScrollDisplayManager(
            display_manager, config, self.logger)
        self.enable_scrolling = self._scroll_manager is not None

        # Data state
        self._driver_standings: List[Dict] = []
        self._constructor_standings: List[Dict] = []
        # Pre-filter P1/P2 used for battle cards (unaffected by top_n setting)
        self._driver_battle_p1: Optional[Dict] = None
        self._driver_battle_p2: Optional[Dict] = None
        self._constructor_battle_p1: Optional[Dict] = None
        self._constructor_battle_p2: Optional[Dict] = None
        self._recent_races: List[Dict] = []
        self._upcoming_race: Optional[Dict] = None
        self._qualifying: Optional[Dict] = None
        self._practice_results: Dict[str, Dict] = {}  # FP1/FP2/FP3
        self._sprint: Optional[Dict] = None
        self._calendar: List[Dict] = []
        self._pole_positions: Dict[str, int] = {}

        # Live session state
        self._is_live: bool = False
        self._live_session: str = ""
        self._is_race_weekend: bool = False

        # Timing
        self._last_update = 0
        self._last_live_check = 0
        self._live_check_interval = 120  # check live status every 2 min
        self._update_interval = config.get("update_interval", 3600)
        self._base_update_interval = self._update_interval

        # Display state tracking (for dynamic duration)
        self._current_display_mode: Optional[str] = None

        # Build enabled modes
        self.modes = self._build_enabled_modes()

        # Preload logos
        self.logo_loader.preload_all_teams(
            self.renderer.logo_max,
            self.renderer.logo_max)

        self.logger.info("F1 Scoreboard initialized with %d modes: %s",
                        len(self.modes), ", ".join(self.modes))

    def _resolve_timezone(self, config: Dict, cache_manager, plugin_manager=None) -> str:
        """Resolve timezone: plugin config → global config → system zone → UTC.

        Consulting only ``cache_manager.config_manager`` used to fall through to
        UTC on cores that expose ``config_manager`` via the plugin manager
        instead, rendering every session start time in UTC.
        """
        return resolve_timezone_name(
            config=config,
            plugin_manager=plugin_manager if plugin_manager is not None
            else getattr(self, "plugin_manager", None),
            cache_manager=cache_manager,
            log=self.logger,
        )

    def _build_enabled_modes(self) -> List[str]:
        """Build list of enabled display modes from config."""
        modes = []
        mode_configs = {
            "f1_driver_standings": self.config.get(
                "driver_standings", {}).get("enabled", True),
            "f1_constructor_standings": self.config.get(
                "constructor_standings", {}).get("enabled", True),
            "f1_recent_races": self.config.get(
                "recent_races", {}).get("enabled", True),
            "f1_upcoming": self.config.get(
                "upcoming", {}).get("enabled", True),
            "f1_qualifying": self.config.get(
                "qualifying", {}).get("enabled", True),
            "f1_practice": self.config.get(
                "practice", {}).get("enabled", True),
            "f1_sprint": self.config.get(
                "sprint", {}).get("enabled", True),
            "f1_calendar": self.config.get(
                "calendar", {}).get("enabled", True),
        }

        for mode, enabled in mode_configs.items():
            if enabled:
                modes.append(mode)

        return modes

    # ─── Update ────────────────────────────────────────────────────────

    def update(self):
        """Fetch and update all F1 data from APIs."""
        now = time.time()

        # Check live session status more frequently than full data update
        if now - self._last_live_check >= self._live_check_interval:
            self._last_live_check = now
            try:
                self._is_live, self._live_session = (
                    self.data_source.detect_live_session())
                self._is_race_weekend = (
                    self.data_source.get_is_race_weekend())

                # Dynamic update interval: faster during race weekends
                if self._is_live:
                    self._update_interval = 300   # 5 min when live
                elif self._is_race_weekend:
                    self._update_interval = 600   # 10 min during weekend
                else:
                    self._update_interval = self._base_update_interval

                if self._is_live:
                    self.logger.info(
                        "LIVE session detected: %s", self._live_session)
            except Exception as e:
                self.logger.warning("Live check error: %s", e, exc_info=True)

        if now - self._last_update < self._update_interval:
            return

        self.logger.info("Updating F1 data (live=%s, weekend=%s)...",
                        self._is_live, self._is_race_weekend)
        self._last_update = now

        for step in (self._update_standings,
                     self._update_recent_races,
                     self._update_upcoming,
                     self._update_qualifying,
                     self._update_practice,
                     self._update_sprint,
                     self._update_calendar,
                     self._prepare_scroll_content):
            try:
                step()
            except Exception as e:
                self.logger.error("Error in %s: %s", step.__name__,
                                 e, exc_info=True)

    def _update_standings(self):
        """Update driver and constructor standings."""
        # Driver standings
        if "f1_driver_standings" in self.modes:
            standings = self.data_source.fetch_driver_standings()
            if standings:
                # Calculate poles
                self._pole_positions = (
                    self.data_source.calculate_pole_positions())

                # Shallow copy entries before adding poles/gaps to avoid
                # mutating the cached standings dicts
                standings = [dict(e) for e in standings]
                for entry in standings:
                    code = entry.get("code", "")
                    entry["poles"] = self._pole_positions.get(code, 0)

                # Annotate with championship gap data
                standings = self.data_source.get_championship_gaps(standings)

                # Save pre-filter P1/P2 for battle card (not affected by top_n)
                if len(standings) >= 1:
                    self._driver_battle_p1 = standings[0]
                if len(standings) >= 2:
                    self._driver_battle_p2 = standings[1]

                # Apply favorite filter
                top_n = self.config.get(
                    "driver_standings", {}).get("top_n", 10)
                always_show = self.config.get(
                    "driver_standings", {}).get("always_show_favorite", True)

                self._driver_standings = self.data_source.apply_favorite_filter(
                    standings, top_n,
                    favorite_driver=self.favorite_driver,
                    favorite_team=self.favorite_team,
                    always_show_favorite=always_show)

        # Constructor standings
        if "f1_constructor_standings" in self.modes:
            standings = self.data_source.fetch_constructor_standings()
            if standings:
                # Annotate with championship gap data
                standings = self.data_source.get_championship_gaps(standings)

                # Save pre-filter P1/P2 for battle card (not affected by top_n)
                if len(standings) >= 1:
                    self._constructor_battle_p1 = standings[0]
                if len(standings) >= 2:
                    self._constructor_battle_p2 = standings[1]

                top_n = self.config.get(
                    "constructor_standings", {}).get("top_n", 10)
                always_show = self.config.get(
                    "constructor_standings", {}).get(
                        "always_show_favorite", True)

                self._constructor_standings = (
                    self.data_source.apply_favorite_filter(
                        standings, top_n,
                        favorite_team=self.favorite_team,
                        always_show_favorite=always_show,
                        driver_key="constructor_id",
                        team_key="constructor_id"))

    def _update_recent_races(self):
        """Update recent race results."""
        if "f1_recent_races" not in self.modes:
            return

        count = self.config.get("recent_races", {}).get("number_of_races", 3)
        races = self.data_source.fetch_recent_races(count=count)
        if races:
            top_finishers = self.config.get(
                "recent_races", {}).get("top_finishers", 3)
            always_show = self.config.get(
                "recent_races", {}).get("always_show_favorite", True)

            # Shallow copy race dicts before mutating results to avoid
            # altering the cached objects from fetch_recent_races
            filtered_races = []
            for race in races:
                race_copy = dict(race)
                results = race.get("results", [])
                # Preserve full results for the points haul card
                race_copy["all_results"] = results
                race_copy["results"] = self.data_source.apply_favorite_filter(
                    results, top_finishers,
                    favorite_driver=self.favorite_driver,
                    always_show_favorite=always_show)
                filtered_races.append(race_copy)

            self._recent_races = filtered_races

    def _update_upcoming(self):
        """Update upcoming race data."""
        if "f1_upcoming" not in self.modes:
            return

        upcoming = self.data_source.get_upcoming_race()
        if upcoming:
            self._upcoming_race = upcoming

    def _update_qualifying(self):
        """Update qualifying results."""
        if "f1_qualifying" not in self.modes:
            return

        qualifying = self.data_source.fetch_qualifying()
        if qualifying:
            self._qualifying = qualifying

    def _update_practice(self):
        """Update free practice results."""
        if "f1_practice" not in self.modes:
            return

        sessions = self.config.get(
            "practice", {}).get("sessions_to_show", ["FP1", "FP2", "FP3"])
        top_n = self.config.get("practice", {}).get("top_n", 10)

        session_name_map = {
            "FP1": "Practice 1",
            "FP2": "Practice 2",
            "FP3": "Practice 3",
        }

        for fp_key in sessions:
            session_name = session_name_map.get(fp_key)
            if not session_name:
                continue

            result = self.data_source.fetch_practice_results(session_name)
            if result:
                # Shallow copy before slicing to avoid mutating cached dict
                result_copy = dict(result)
                if result_copy.get("results"):
                    result_copy["results"] = result_copy["results"][:top_n]
                self._practice_results[fp_key] = result_copy

    def _update_sprint(self):
        """Update sprint race results."""
        if "f1_sprint" not in self.modes:
            return

        sprint = self.data_source.fetch_sprint_results()
        if sprint:
            # Shallow copy before slicing to avoid mutating cached dict
            sprint_copy = dict(sprint)
            top_n = self.config.get("sprint", {}).get("top_finishers", 10)
            if sprint_copy.get("results"):
                sprint_copy["results"] = sprint_copy["results"][:top_n]
            self._sprint = sprint_copy

    def _update_calendar(self):
        """Update race calendar."""
        if "f1_calendar" not in self.modes:
            return

        cal_config = self.config.get("calendar", {})
        calendar = self.data_source.get_calendar(
            show_practice=cal_config.get("show_practice", False),
            show_qualifying=cal_config.get("show_qualifying", True),
            show_sprint=cal_config.get("show_sprint", True),
            max_events=cal_config.get("max_events", 5))
        if calendar:
            self._calendar = calendar

    # ─── Gap Trend Helper ──────────────────────────────────────────────

    def _compute_race_gap_trend(self, code1: str, code2: str,
                                 use_constructor: bool = False) -> int:
        """
        Return points delta (code1 - code2) from the most recent race.
        Positive = code1 extended its lead; negative = code2 is closing.
        Returns 0 if data is unavailable.
        """
        if not self._recent_races:
            return 0
        all_res = self._recent_races[0].get("all_results", [])
        if use_constructor:
            pts1 = sum(e.get("points", 0) for e in all_res
                       if e.get("constructor_id", "") == code1)
            pts2 = sum(e.get("points", 0) for e in all_res
                       if e.get("constructor_id", "") == code2)
            if pts1 == 0 and pts2 == 0:
                return 0
        else:
            pts1 = next(
                (e.get("points", 0) for e in all_res
                 if e.get("code", "").upper() == code1.upper()), None)
            pts2 = next(
                (e.get("points", 0) for e in all_res
                 if e.get("code", "").upper() == code2.upper()), None)
            if pts1 is None or pts2 is None:
                return 0
        return int(pts1 - pts2)

    # ─── Scroll Content Preparation ────────────────────────────────────

    def _prepare_scroll_content(self):
        """Pre-render all scroll mode content."""
        r = self._scroll_renderer
        separator = r.render_f1_separator()
        is_live = self._is_live
        live_sess = self._live_session

        # Round / season info (used by headers and battle card)
        season = datetime.now(timezone.utc).year
        round_num = self.data_source.get_latest_round(season)
        total_rounds = len(self._calendar) if self._calendar else 24
        remaining_races = max(0, total_rounds - round_num)

        # Championship leaders intro card (very first in Vegas scroll)
        if r.show_championship_leaders and self._driver_standings and self._constructor_standings:
            drv_leader = self._driver_standings[0] if self._driver_standings else None
            con_leader = self._constructor_standings[0] if self._constructor_standings else None
            if drv_leader and con_leader:
                leaders_card = r.render_championship_leaders(
                    drv_leader, con_leader,
                    is_live=is_live, live_session=live_sess)
                self._scroll_manager.prepare_and_display(
                    "championship_leaders", [leaders_card], separator)

        # Driver championship battle card (P1 vs P2, follows leaders)
        # Uses pre-filter standings so top_n config doesn't affect P1/P2 selection
        if r.show_championship_battle and self._driver_battle_p1 and self._driver_battle_p2:
            p1 = self._driver_battle_p1
            p2 = self._driver_battle_p2
            gap_trend = self._compute_race_gap_trend(
                p1.get("code", ""), p2.get("code", ""))
            battle_card = r.render_championship_battle_card(
                p1, p2, remaining_races=remaining_races,
                gap_trend=gap_trend,
                is_live=is_live, live_session=live_sess)
            self._scroll_manager.prepare_and_display(
                "championship_battle", [battle_card], separator)

        # Constructor championship battle card (P1 vs P2 constructor)
        if r.show_constructor_battle and self._constructor_battle_p1 and self._constructor_battle_p2:
            cp1 = self._constructor_battle_p1
            cp2 = self._constructor_battle_p2
            con_gap_trend = self._compute_race_gap_trend(
                cp1.get("constructor_id", ""), cp2.get("constructor_id", ""),
                use_constructor=True)
            con_battle = r.render_constructor_battle_card(
                cp1, cp2, remaining_races=remaining_races,
                gap_trend=con_gap_trend,
                is_live=is_live, live_session=live_sess)
            self._scroll_manager.prepare_and_display(
                "constructor_battle", [con_battle], separator)

        # Spotlight card for favorite driver (appears first in sequence)
        if self.favorite_driver and self._driver_standings:
            fav_entry = next(
                (e for e in self._driver_standings
                 if e.get("code", "").upper() == self.favorite_driver),
                None)
            if fav_entry:
                spotlight = r.render_favorite_driver_spotlight(
                    fav_entry, is_live=is_live, live_session=live_sess,
                    recent_races=self._recent_races)
                self._scroll_manager.prepare_and_display(
                    "driver_spotlight", [spotlight], separator)

        # Spotlight card for favorite team
        if self.favorite_team and self._constructor_standings:
            fav_team = next(
                (e for e in self._constructor_standings
                 if e.get("constructor_id", "") == self.favorite_team),
                None)
            if fav_team:
                # Also find team drivers in driver standings
                team_drivers = [
                    e for e in self._driver_standings
                    if e.get("constructor_id", "") == self.favorite_team
                ] if self._driver_standings else []
                spotlight = r.render_favorite_team_spotlight(
                    fav_team, driver_entries=team_drivers,
                    is_live=is_live, live_session=live_sess)
                self._scroll_manager.prepare_and_display(
                    "team_spotlight", [spotlight], separator)

        # Build last-race points lookup (driver code → points scored in most recent race)
        last_race_pts_map: Dict[str, int] = {}
        last_race_con_pts_map: Dict[str, int] = {}
        if self._recent_races:
            for res in self._recent_races[0].get("all_results", []):
                code = res.get("code", "").upper()
                cid_res = res.get("constructor_id", "")
                pts = int(res.get("points", 0))
                last_race_pts_map[code] = pts
                last_race_con_pts_map[cid_res] = (
                    last_race_con_pts_map.get(cid_res, 0) + pts)

        # Driver standings
        if self._driver_standings:
            cards = []
            if r.show_standings_header:
                cards.append(r.render_standings_header(
                    "DRIVER STANDINGS", round_num=round_num,
                    total_rounds=total_rounds, season=season))
            # Driver form guide card (recent race positions at a glance)
            if r.show_driver_form and self._recent_races:
                form_card = r.render_driver_form_card(
                    self._driver_standings[:8], self._recent_races)
                cards.append(form_card)
            for e in self._driver_standings:
                enriched = dict(e)
                enriched["last_race_pts"] = last_race_pts_map.get(
                    e.get("code", "").upper(), 0)
                cards.append(r.render_driver_standing(
                    enriched, is_live=is_live, live_session=live_sess))
            self._scroll_manager.prepare_and_display(
                "driver_standings", cards, separator)

        # Constructor standings (enriched with per-driver points)
        if self._constructor_standings:
            cards = []
            if r.show_standings_header:
                cards.append(r.render_standings_header(
                    "CONSTRUCTOR STANDINGS", round_num=round_num,
                    total_rounds=total_rounds, season=season))
            for e in self._constructor_standings:
                cid = e.get("constructor_id", "")
                team_drivers = sorted(
                    [d for d in self._driver_standings
                     if d.get("constructor_id") == cid],
                    key=lambda d: d.get("position", 99))
                entry = dict(e)
                entry["team_drivers"] = team_drivers
                entry["last_race_pts"] = last_race_con_pts_map.get(cid, 0)
                cards.append(r.render_constructor_standing(
                    entry, is_live=is_live, live_session=live_sess))
            self._scroll_manager.prepare_and_display(
                "constructor_standings", cards, separator)

        # Recent races (winners summary + podium cards + favorite highlight + points haul + gap chart)
        rr_cfg = self.config.get("recent_races", {})
        show_haul = rr_cfg.get("show_points_haul", True)
        haul_top_n = rr_cfg.get("points_haul_drivers", 5)
        show_winners = rr_cfg.get("show_winners_summary", True)
        show_gap_chart = rr_cfg.get("show_gap_chart", True)
        gap_chart_n = rr_cfg.get("gap_chart_drivers", 5)
        if self._recent_races:
            cards = []
            # Winners summary at the top (only if showing 2+ races)
            if show_winners and len(self._recent_races) > 1:
                cards.append(r.render_recent_winners_card(self._recent_races))
            for race in self._recent_races:
                cards.append(r.render_race_result(race))
                # If favorite outside podium: results[3] is the appended favorite
                results = race.get("results", [])
                if self.favorite_driver and len(results) > 3:
                    fav = results[3]
                    if fav.get("code", "").upper() == self.favorite_driver:
                        cards.append(r.render_favorite_race_card(race, fav))
                # Gap chart bar visualization (skip if no result data available)
                if show_gap_chart and race.get("all_results"):
                    cards.append(r.render_race_gap_chart(race, top_n=gap_chart_n))
                # Points haul bar chart (uses full unfiltered results)
                if show_haul:
                    cards.append(r.render_race_points_haul(race, top_n=haul_top_n))
            self._scroll_manager.prepare_and_display(
                "recent_races", cards, separator)

        # Qualifying
        if self._qualifying:
            cards = self._build_qualifying_cards()
            if cards:
                self._scroll_manager.prepare_and_display(
                    "qualifying", cards, separator)

        # Practice
        practice_cards = self._build_practice_cards()
        if practice_cards:
            self._scroll_manager.prepare_and_display(
                "practice", practice_cards, separator)

        # Sprint
        if self._sprint and self._sprint.get("results"):
            cards = [r.render_sprint_header(
                        self._sprint.get("race_name", ""))]
            for entry in self._sprint["results"]:
                cards.append(r.render_sprint_entry(entry))
            self._scroll_manager.prepare_and_display(
                "sprint", cards, separator)

        # Calendar
        if self._calendar:
            cards = [r.render_calendar_entry(e)
                    for e in self._calendar]
            self._scroll_manager.prepare_and_display(
                "calendar", cards, separator)

    def _build_qualifying_cards(self) -> List[Image.Image]:
        """Build qualifying result cards grouped by Q session."""
        if not self._qualifying:
            return []

        r = self._scroll_renderer
        cards = []
        quali_config = self.config.get("qualifying", {})
        results = self._qualifying.get("results", [])
        race_name = self._qualifying.get("race_name", "")

        # Team H2H card at the start of qualifying section
        if quali_config.get("show_team_duel", True) and results:
            cards.append(r.render_qualifying_team_duel_card(self._qualifying))

        for session_key, show_key, label in [
            ("q3", "show_q3", "Q3"),
            ("q2", "show_q2", "Q2"),
            ("q1", "show_q1", "Q1"),
        ]:
            if not quali_config.get(show_key, True):
                continue

            # Add session header
            cards.append(r.render_qualifying_header(
                label, race_name))

            # Add entries for this session
            for entry in results:
                # Only show entries that have a time for this session
                if entry.get(session_key):
                    cards.append(r.render_qualifying_entry(
                        entry, label))
                elif entry.get("eliminated_in") == label:
                    # Show eliminated driver
                    cards.append(r.render_qualifying_entry(
                        entry, label))

        return cards

    def _build_practice_cards(self) -> List[Image.Image]:
        """Build practice result cards for all configured sessions."""
        r = self._scroll_renderer
        cards = []

        for fp_key in ["FP3", "FP2", "FP1"]:  # Most recent first
            if fp_key not in self._practice_results:
                continue

            fp_data = self._practice_results[fp_key]
            cards.append(r.render_practice_header(
                fp_key, fp_data.get("circuit", "")))

            for entry in fp_data.get("results", []):
                cards.append(r.render_practice_entry(entry))

        return cards

    # ─── Display ───────────────────────────────────────────────────────

    def display(self, force_clear=False, display_mode=None) -> bool:
        """
        Display the current F1 mode.

        Args:
            force_clear: Whether to clear display first
            display_mode: Specific mode to display (from manifest display_modes)

        Returns:
            True if content was displayed, False if mode has no data
        """
        if not self.enabled:
            return False

        if display_mode is None:
            display_mode = self.modes[0] if self.modes else "f1_driver_standings"

        self._current_display_mode = display_mode

        if display_mode == "f1_upcoming":
            return self._display_upcoming(force_clear)
        elif display_mode in ("f1_driver_standings",
                               "f1_constructor_standings",
                               "f1_recent_races",
                               "f1_qualifying",
                               "f1_practice",
                               "f1_sprint",
                               "f1_calendar"):
            return self._display_scroll_mode(display_mode, force_clear)
        else:
            self.logger.warning("Unknown display mode: %s", display_mode)
            return False

    def _enrich_upcoming_with_countdown(self,
                                        race: Dict) -> Dict:
        """Return a shallow copy of race with fresh countdown_seconds set."""
        upcoming = dict(race)
        upcoming["countdown_seconds"] = None

        now = datetime.now(timezone.utc)

        for session in upcoming.get("sessions", []):
            if session.get("status_state") == "pre" and session.get("date"):
                try:
                    parsed_dt = datetime.fromisoformat(
                        session["date"].replace("Z", "+00:00"))
                    if parsed_dt > now:
                        upcoming["countdown_seconds"] = max(
                            0, (parsed_dt - now).total_seconds())
                        upcoming["next_session_type"] = session.get(
                            "type_abbr", "")
                        break
                except (ValueError, TypeError):
                    continue

        return upcoming

    def _display_upcoming(self, force_clear: bool) -> bool:
        """Display the upcoming race card (static)."""
        if not self._upcoming_race:
            return False

        if force_clear:
            self.display_manager.image.paste(
                Image.new("RGB",
                          (self.display_width, self.display_height),
                          (0, 0, 0)),
                (0, 0))

        upcoming = self._enrich_upcoming_with_countdown(self._upcoming_race)
        card = self.renderer.render_upcoming_race(upcoming)
        self.display_manager.image.paste(card, (0, 0))
        self.display_manager.update_display()
        return True

    def _display_scroll_mode(self, display_mode: str,
                              force_clear: bool) -> bool:
        """Display a scrolling mode."""
        mode_key = self._MODE_KEY_MAP.get(display_mode, display_mode)

        if not self._scroll_manager.is_mode_prepared(mode_key):
            self._prepare_scroll_content()

        if not self._scroll_manager.is_mode_prepared(mode_key):
            return False

        self._scroll_manager.display_frame(mode_key, force_clear)
        return True

    # ─── Vegas Mode ────────────────────────────────────────────────────

    def get_vegas_content(self) -> Optional[List[Image.Image]]:
        """Return rendered cards for modes that have data."""
        images = []

        # Championship leaders overview card (very first)
        if self._scroll_manager.is_mode_prepared("championship_leaders"):
            images.extend(
                self._scroll_manager.get_vegas_items_for_mode(
                    "championship_leaders"))

        # Championship battle card (P1 vs P2 title fight)
        if self._scroll_manager.is_mode_prepared("championship_battle"):
            images.extend(
                self._scroll_manager.get_vegas_items_for_mode(
                    "championship_battle"))

        # Constructor championship battle card
        if self._scroll_manager.is_mode_prepared("constructor_battle"):
            images.extend(
                self._scroll_manager.get_vegas_items_for_mode(
                    "constructor_battle"))

        # Spotlight cards go first (most important, followed driver/team)
        for spotlight_key in ("driver_spotlight", "team_spotlight"):
            if self._scroll_manager.is_mode_prepared(spotlight_key):
                images.extend(
                    self._scroll_manager.get_vegas_items_for_mode(
                        spotlight_key))

        # Upcoming race card (second — before standings)
        if self._upcoming_race:
            upcoming_card = self._scroll_renderer.render_upcoming_race(
                self._enrich_upcoming_with_countdown(self._upcoming_race))
            images.append(upcoming_card)
            # Circuit stats card (immediately after upcoming race card)
            if self._scroll_renderer.show_circuit_info:
                circuit_card = self._scroll_renderer.render_circuit_info_card(
                    self._upcoming_race)
                images.append(circuit_card)

        # Standings and results
        mode_data = {
            "driver_standings": self._driver_standings,
            "constructor_standings": self._constructor_standings,
            "recent_races": self._recent_races,
            "qualifying": self._qualifying,
            "practice": self._practice_results,
            "sprint": self._sprint,
            "calendar": self._calendar,
        }
        for mode_key, data in mode_data.items():
            if data and self._scroll_manager.is_mode_prepared(mode_key):
                images.extend(
                    self._scroll_manager.get_vegas_items_for_mode(mode_key))

        return images if images else None

    def get_vegas_content_type(self) -> str:
        """Return multi for scrolling content."""
        return "multi"

    def get_vegas_display_mode(self) -> VegasDisplayMode:
        """Return SCROLL for continuous scrolling."""
        return VegasDisplayMode.SCROLL

    # ─── Dynamic Duration ──────────────────────────────────────────────

    _SCROLL_MODES = frozenset({
        "f1_driver_standings", "f1_constructor_standings",
        "f1_recent_races", "f1_qualifying", "f1_practice",
        "f1_sprint", "f1_calendar",
    })

    _MODE_KEY_MAP = {
        "f1_driver_standings": "driver_standings",
        "f1_constructor_standings": "constructor_standings",
        "f1_recent_races": "recent_races",
        "f1_qualifying": "qualifying",
        "f1_practice": "practice",
        "f1_sprint": "sprint",
        "f1_calendar": "calendar",
    }

    def supports_dynamic_duration(self) -> bool:
        """Enable dynamic duration for scrolling modes."""
        dd = self.config.get("dynamic_duration", {})
        if not isinstance(dd, dict) or not dd.get("enabled", True):
            return False
        return (self._current_display_mode is not None
                and self._current_display_mode in self._SCROLL_MODES)

    def is_cycle_complete(self) -> bool:
        """Scroll cycle complete when ScrollHelper reports done."""
        if not self._current_display_mode:
            return True
        mode_key = self._MODE_KEY_MAP.get(self._current_display_mode)
        if not mode_key:
            return True
        return self._scroll_manager.is_scroll_complete(mode_key)

    def reset_cycle_state(self) -> None:
        """Reset scroll position for the current mode."""
        super().reset_cycle_state()
        if self._current_display_mode:
            mode_key = self._MODE_KEY_MAP.get(self._current_display_mode)
            if mode_key:
                self._scroll_manager.reset_mode(mode_key)

    # ─── Lifecycle ─────────────────────────────────────────────────────

    def get_info(self) -> Dict[str, Any]:
        """Return diagnostic info for the web UI."""
        info = super().get_info()
        info.update({
            "name": "F1 Scoreboard",
            "enabled_modes": self.modes,
            "mode_count": len(self.modes),
            "last_update": self._last_update,
            "has_driver_standings": bool(self._driver_standings),
            "has_constructor_standings": bool(self._constructor_standings),
            "has_recent_races": bool(self._recent_races),
            "has_upcoming_race": self._upcoming_race is not None,
            "has_qualifying": self._qualifying is not None,
            "has_practice": bool(self._practice_results),
            "has_sprint": self._sprint is not None,
            "has_calendar": bool(self._calendar),
            "favorite_driver": self.favorite_driver,
            "favorite_team": self.favorite_team,
            "is_live": self._is_live,
            "live_session": self._live_session,
            "is_race_weekend": self._is_race_weekend,
            "effective_update_interval": self._update_interval,
        })
        return info

    def on_config_change(self, new_config):
        """Handle config changes."""
        super().on_config_change(new_config)

        self.favorite_driver = new_config.get("favorite_driver", "").upper()
        self.favorite_team = normalize_constructor_id(
            new_config.get("favorite_team", ""))
        self._base_update_interval = new_config.get("update_interval", 3600)
        self._update_interval = self._base_update_interval
        self.display_duration = new_config.get("display_duration", 30)
        self.modes = self._build_enabled_modes()

        # Re-resolve timezone in case global config changed. Kept in a shallow
        # copy (never written back into `new_config`) so it never gets
        # persisted as a stale plugin-level override.
        self.timezone = self._resolve_timezone(new_config, self.cache_manager)
        render_config = {**new_config, "timezone": self.timezone}

        # Force re-render with new settings
        scroll_cfg = render_config.get("scroll", {}) if isinstance(render_config.get("scroll"), dict) else {}
        self._card_width = scroll_cfg.get("game_card_width", 128)
        self.renderer = F1Renderer(
            self.display_width, self.display_height,
            render_config, self.logo_loader, self.logger)
        self._scroll_renderer = F1Renderer(
            self._card_width, self.display_height,
            render_config, self.logo_loader, self.logger)
        self._scroll_manager = ScrollDisplayManager(
            self.display_manager, render_config, self.logger)
        self.enable_scrolling = self._scroll_manager is not None

        # Force data refresh
        self._last_update = 0

    def cleanup(self):
        """Clean up resources."""
        try:
            self.logo_loader.clear_cache()
            self.logger.info("F1 Scoreboard cleanup completed")
        except Exception:
            self.logger.exception("Error during F1 Scoreboard cleanup")
        super().cleanup()
