"""
Masters Tournament Plugin

Main plugin class for the Masters Tournament LED display.
Displays live leaderboards, player cards, course imagery, hole maps,
fun facts, past champions, and Augusta National branding year-round.
"""

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from PIL import Image

from src.plugin_system.base_plugin import BasePlugin, VegasDisplayMode

from masters_data import MastersDataSource
from masters_renderer import MastersRenderer
from masters_renderer_enhanced import MastersRendererEnhanced
from logo_loader import MastersLogoLoader
from masters_helpers import (
    calculate_tournament_countdown,
    filter_favorite_players,
    get_detailed_phase,
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
        self.logo_loader = MastersLogoLoader(self.plugin_dir)
        self.data_source = MastersDataSource(cache_manager, config)

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

        # Tournament phase
        self._tournament_phase = get_tournament_phase()
        self._detailed_phase = get_detailed_phase()

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

        # Player card rotation
        self._player_card_index = 0

        self.logger.info(
            f"Masters Tournament plugin initialized: {self.display_width}x{self.display_height}, "
            f"{len(self.modes)} modes, phase: {self._tournament_phase}"
        )

    # ── Phase-aware mode definitions ──
    # Each phase lists modes in priority order (shown most → least)
    # The framework rotates through these, so order = screen time priority

    PHASE_MODES = {
        "off-season": [
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

    def _build_enabled_modes(self) -> List[str]:
        """Build mode list based on current tournament phase and time of day.

        The framework rotates through self.modes, so this controls what
        the user sees and in what order. Modes listed multiple times get
        proportionally more screen time.
        """
        phase = get_detailed_phase()
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
        self._tournament_phase = get_tournament_phase()

        # Refresh modes based on current phase/time of day
        # This lets modes shift automatically (e.g., morning → live → evening)
        new_modes = self._build_enabled_modes()
        if new_modes != self.modes:
            old_phase = self._detailed_phase
            self._detailed_phase = get_detailed_phase()
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

        favorites = self.config.get("favorite_players", [])
        top_n = self.config.get("display_modes", {}).get("leaderboard", {}).get("top_n", 10)
        always_show = self.config.get("display_modes", {}).get("leaderboard", {}).get(
            "show_favorites_always", True
        )

        self._leaderboard_data = filter_favorite_players(
            sorted_board, favorites, top_n=top_n, always_show_favorites=always_show
        )
        self.logger.debug(f"Updated leaderboard with {len(self._leaderboard_data)} players")

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

    def _show_image(self, image: Optional[Image.Image]) -> bool:
        """Helper to display an image if it exists."""
        if image:
            self.display_manager.draw_image(image, 0, 0)
            self.display_manager.update_display()
            return True
        return False

    def _display_leaderboard(self, force_clear: bool) -> bool:
        if not self._leaderboard_data:
            return False
        page = self._page["leaderboard"]
        result = self._show_image(
            self.renderer.render_leaderboard(self._leaderboard_data, show_favorites=True, page=page)
        )
        self._page["leaderboard"] = page + 1
        return result

    def _display_player_cards(self, force_clear: bool) -> bool:
        if not self._leaderboard_data:
            return False
        # Rotate through top players
        idx = self._player_card_index % min(5, len(self._leaderboard_data))
        player = self._leaderboard_data[idx]
        self._player_card_index += 1
        return self._show_image(self.renderer.render_player_card(player))

    def _display_course_tour(self, force_clear: bool) -> bool:
        result = self._show_image(self.renderer.render_hole_card(self._current_hole))
        self._current_hole = (self._current_hole % 18) + 1
        return result

    def _display_amen_corner(self, force_clear: bool) -> bool:
        return self._show_image(self.renderer.render_amen_corner())

    def _display_past_champions(self, force_clear: bool) -> bool:
        page = self._page["champions"]
        result = self._show_image(self.renderer.render_past_champions(page=page))
        self._page["champions"] = page + 1
        return result

    def _display_hole_by_hole(self, force_clear: bool) -> bool:
        """Display hole-by-hole course tour (same as course_tour)."""
        return self._display_course_tour(force_clear)

    def _display_featured_holes(self, force_clear: bool) -> bool:
        featured = [12, 13, 15, 16]
        hole = featured[self._featured_hole_index % len(featured)]
        self._featured_hole_index += 1
        return self._show_image(self.renderer.render_hole_card(hole))

    def _display_schedule(self, force_clear: bool) -> bool:
        page = self._page["schedule"]
        result = self._show_image(
            self.renderer.render_schedule(self._schedule_data, page=page)
        )
        self._page["schedule"] = page + 1
        return result

    def _display_live_action(self, force_clear: bool) -> bool:
        """Show live alert if enhanced renderer available, else leaderboard."""
        if hasattr(self.renderer, "render_live_alert") and self._leaderboard_data:
            # Show the leader's current status as a live alert
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
        page = self._page["stats"]
        result = self._show_image(self.renderer.render_tournament_stats(page=page))
        self._page["stats"] = page + 1
        return result

    def _display_fun_facts(self, force_clear: bool) -> bool:
        result = self._show_image(
            self.renderer.render_fun_fact(self._fact_index, scroll_offset=self._fact_scroll)
        )
        self._fact_scroll += 1
        # Move to next fact after scrolling through
        if self._fact_scroll > 5:
            self._fact_index += 1
            self._fact_scroll = 0
        return result

    def _display_countdown(self, force_clear: bool) -> bool:
        # Compute next Masters Thursday dynamically (approx second Thursday of April)
        now = datetime.utcnow()
        year = now.year
        target = datetime(year, 4, 10, 12, 0, 0)
        if now > target:
            target = datetime(year + 1, 4, 10, 12, 0, 0)
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
            page = self._page["course_overview"]
            result = self._show_image(self.renderer.render_course_overview(page=page))
            self._page["course_overview"] = page + 1
            return result
        return self._display_amen_corner(force_clear)

    def get_vegas_content(self) -> Optional[List[Image.Image]]:
        """Return cards for Vegas scroll mode."""
        cards = []

        for player in self._leaderboard_data[:10]:
            card = self.renderer.render_player_card(player)
            if card:
                cards.append(card)

        for hole in range(1, 19):
            card = self.renderer.render_hole_card(hole)
            if card:
                cards.append(card)

        # Fun facts
        for i in range(5):
            card = self.renderer.render_fun_fact(i)
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
