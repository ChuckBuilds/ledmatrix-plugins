"""
Olympics Plugin for LEDMatrix

Enhanced Olympics plugin with live data display including:
- Medal counts by country
- Upcoming events with timezone-accurate times
- Recent results with medal winners
- Countdown to opening/closing ceremonies

Supports both Vegas scroll mode and regular switch display mode.

Features:
- Live Event Alerts - Priority display for medal finals
- Medal Race Tracker - Compare favorite vs rival countries
- Sport Filters - Show only favorite sports

API Version: 2.0.0
"""

import hashlib
import logging
import threading
import time
from typing import Dict, Any, Optional, List
from PIL import Image

from src.plugin_system.base_plugin import BasePlugin, VegasDisplayMode

# Local imports
from data import OlympicsDataFetcher, OlympicsData
from renderers import MedalCardRenderer, EventCardRenderer, CountdownRenderer

logger = logging.getLogger(__name__)


class OlympicsPlugin(BasePlugin):
    """
    Enhanced Olympics plugin with live data and Vegas mode support.

    Configuration options:
        enabled (bool): Enable/disable plugin
        display_duration (number): Seconds to display (default: 30)
        timezone (str): Timezone for event times (default: UTC)
        top_countries_count (int): Number of top countries to show (default: 5)
        additional_countries (list): Countries to always show
        show_medals (bool): Show medal counts (default: true)
        show_schedule (bool): Show upcoming events (default: true)
        show_results (bool): Show recent results (default: true)
        live_alerts_enabled (bool): Priority alerts for live finals (default: true)
        sport_filters (list): Filter to specific sports (default: all)
    """

    # Display sections for switch mode rotation
    SECTION_MEDALS = 0
    SECTION_SCHEDULE = 1
    SECTION_RESULTS = 2
    SECTION_MEDAL_RACE = 3

    def __init__(self, plugin_id: str, config: Dict[str, Any],
                 display_manager, cache_manager, plugin_manager):
        """Initialize the Olympics plugin."""
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)

        # Configuration
        self.timezone = config.get('timezone', 'UTC')
        self.top_countries_count = config.get('top_countries_count', 5)
        self.additional_countries = config.get('additional_countries', [])
        self.rival_countries = config.get('rival_countries', [])
        self.show_medals = config.get('show_medals', True)
        self.show_schedule = config.get('show_schedule', True)
        self.show_results = config.get('show_results', True)
        self.live_alerts_enabled = config.get('live_alerts_enabled', True)
        self.medal_race_enabled = config.get('medal_race_enabled', True)
        self.sport_filters = [s.lower() for s in config.get('sport_filters', [])]
        self.upcoming_events_count = config.get('upcoming_events_count', 5)
        self.recent_results_count = config.get('recent_results_count', 5)

        # Parse text color
        text_color = config.get('text_color', [255, 255, 255])
        self.text_color = tuple(text_color) if isinstance(text_color, list) else text_color

        # Initialize data fetcher
        self.data_fetcher = OlympicsDataFetcher(config)

        # Initialize renderers with display manager fonts
        fonts = {
            'regular': getattr(display_manager, 'regular_font', None),
            'small': getattr(display_manager, 'small_font', None),
            'extra_small': getattr(display_manager, 'extra_small_font', None),
        }

        self.medal_renderer = MedalCardRenderer(
            display_manager.height,
            config,
            fonts
        )
        self.event_renderer = EventCardRenderer(
            display_manager.height,
            config,
            fonts
        )
        self.countdown_renderer = CountdownRenderer(
            display_manager,
            config
        )

        # State
        self.olympics_data: Optional[OlympicsData] = None
        self._data_lock = threading.Lock()
        self._update_lock = threading.Lock()  # Lock for _update_in_progress flag
        self._update_in_progress = False
        self.current_section = self._get_initial_section()
        self.last_section_change = time.time()
        self.section_duration = config.get('section_duration', 10)  # seconds per section
        self.last_displayed_message = None
        self.last_update_time = 0
        self.update_interval = config.get('update_interval', 300)  # 5 minutes

        # Content change detection
        self._last_content_hash: Optional[str] = None
        self._last_vegas_content_hash: Optional[str] = None

        # Medal cycling state for switch mode (individual country display)
        self._current_medal_index = 0
        self._last_medal_cycle_time = 0
        self._medal_cycle_duration = config.get('medal_cycle_duration', 3)  # seconds per country

        self.logger.info("Olympics plugin initialized with Vegas mode support")

    def _get_initial_section(self) -> int:
        """Get the first enabled section for initialization."""
        sections = self._get_enabled_sections()
        return sections[0] if sections else self.SECTION_MEDALS

    def _compute_content_hash(self, section: int) -> str:
        """
        Compute a hash of the content for change detection.

        This allows us to skip redraws when the displayed content hasn't changed.
        Thread-safe: acquires _data_lock for consistent reads.
        """
        hash_parts = [str(section)]

        with self._data_lock:
            data = self.olympics_data
            if not data:
                hash_parts.append("no_data")
            elif not data.is_active:
                # Countdown mode - hash the opening date
                hash_parts.append(f"countdown:{data.opening_date}")
            else:
                # Active Olympics - hash based on section
                if section == self.SECTION_MEDALS:
                    medals = data.get_top_countries(self.top_countries_count)
                    # Include current medal index for cycling display
                    hash_parts.append(f"medal_idx:{self._current_medal_index}")
                    for m in medals:
                        hash_parts.append(f"{m.country_code}:{m.gold}:{m.silver}:{m.bronze}")
                elif section == self.SECTION_SCHEDULE:
                    events = self._filter_events(data.upcoming_events)
                    for e in events[:self.upcoming_events_count]:
                        hash_parts.append(f"{e.sport}:{e.event_name}:{e.start_time}")
                elif section == self.SECTION_RESULTS:
                    for r in data.recent_results[:self.recent_results_count]:
                        hash_parts.append(f"{r.sport}:{r.event_name}:{r.gold_country}")
                elif section == self.SECTION_MEDAL_RACE:
                    if self.rival_countries and len(self.rival_countries) >= 2:
                        c1 = data.get_country_medals(self.rival_countries[0])
                        c2 = data.get_country_medals(self.rival_countries[1])
                        if c1:
                            hash_parts.append(f"{c1.country_code}:{c1.total}")
                        if c2:
                            hash_parts.append(f"{c2.country_code}:{c2.total}")

        return hashlib.md5("|".join(hash_parts).encode()).hexdigest()

    def update(self) -> None:
        """
        Update Olympics data from the fetcher.

        Called periodically to refresh medal counts, events, and results.
        """
        try:
            current_time = time.time()

            # Only update if enough time has passed
            if current_time - self.last_update_time < self.update_interval:
                return

            new_data = self.data_fetcher.get_olympics_data()

            # Thread-safe update of olympics_data
            with self._data_lock:
                self.olympics_data = new_data
                self.last_update_time = current_time

            if new_data:
                medal_count = len(new_data.medal_counts)
                event_count = len(new_data.upcoming_events)
                self.logger.info(
                    f"Updated Olympics data: {medal_count} countries, "
                    f"{event_count} events, active={new_data.is_active}"
                )

        except Exception as e:
            self.logger.error(f"Error updating Olympics data: {e}", exc_info=True)

    def _trigger_background_update(self) -> None:
        """Trigger a non-blocking background update if not already in progress."""
        # Thread-safe check and set of update flag
        with self._update_lock:
            if self._update_in_progress:
                return

            current_time = time.time()
            if current_time - self.last_update_time < self.update_interval:
                return

            self._update_in_progress = True

        def do_update():
            try:
                self.update()
            finally:
                with self._update_lock:
                    self._update_in_progress = False

        thread = threading.Thread(target=do_update, daemon=True)
        thread.start()

    def display(self, force_clear: bool = False) -> None:
        """
        Display Olympics content in switch mode.

        Cycles through sections: medals, schedule, results.
        Falls back to countdown if Olympics not active.
        """
        try:
            # Thread-safe snapshot of olympics_data
            with self._data_lock:
                data_snapshot = self.olympics_data

            # Ensure we have data
            if not data_snapshot:
                self.update()
                with self._data_lock:
                    data_snapshot = self.olympics_data

            if not data_snapshot:
                self._display_error("Loading data...")
                return

            # If Olympics not active, show countdown
            if not data_snapshot.is_active:
                self._display_countdown()
                return

            # Rotate through sections
            current_time = time.time()
            section_changed = False
            if current_time - self.last_section_change >= self.section_duration:
                self._advance_section()
                self.last_section_change = current_time
                section_changed = True

            # Display current section (force redraw on section change or force_clear)
            self._display_current_section(force_redraw=force_clear or section_changed)

        except Exception as e:
            self.logger.error(f"Error displaying Olympics: {e}", exc_info=True)
            self._display_error("Display Error")

    def _get_enabled_sections(self) -> List[int]:
        """Get list of enabled display sections based on config."""
        sections = []
        if self.show_medals:
            sections.append(self.SECTION_MEDALS)
        if self.show_schedule:
            sections.append(self.SECTION_SCHEDULE)
        if self.show_results:
            sections.append(self.SECTION_RESULTS)
        if self.medal_race_enabled and self.rival_countries:
            sections.append(self.SECTION_MEDAL_RACE)
        return sections if sections else [self.SECTION_MEDALS]

    def _advance_section(self) -> None:
        """Advance to next display section."""
        sections = self._get_enabled_sections()

        # If current section is not in list, start at first section
        if self.current_section not in sections:
            self.current_section = sections[0]
            return

        current_idx = sections.index(self.current_section)
        next_idx = (current_idx + 1) % len(sections)
        self.current_section = sections[next_idx]

    def _display_current_section(self, force_redraw: bool = False) -> None:
        """
        Display the current section content.

        Uses content hashing to avoid unnecessary redraws when the
        displayed content hasn't changed.
        Thread-safe: acquires _data_lock for consistent snapshot.

        Args:
            force_redraw: Force a redraw even if content hasn't changed
        """
        # Thread-safe snapshot of olympics_data
        with self._data_lock:
            data = self.olympics_data

        # Check for medal cycling time update (before computing hash)
        if self.current_section == self.SECTION_MEDALS:
            current_time = time.time()
            if current_time - self._last_medal_cycle_time >= self._medal_cycle_duration:
                medals = data.get_top_countries(self.top_countries_count) if data else []
                if medals:
                    self._current_medal_index = (self._current_medal_index + 1) % len(medals)
                    self._last_medal_cycle_time = current_time
                    force_redraw = True  # Force redraw when medal cycles

        # Compute content hash for change detection
        content_hash = self._compute_content_hash(self.current_section)

        # Skip redraw if content hasn't changed
        if not force_redraw and content_hash == self._last_content_hash:
            return

        self._last_content_hash = content_hash
        self.display_manager.clear()

        if self.current_section == self.SECTION_MEDALS:
            self._display_medals(data)
        elif self.current_section == self.SECTION_SCHEDULE:
            self._display_schedule(data)
        elif self.current_section == self.SECTION_RESULTS:
            self._display_results(data)
        elif self.current_section == self.SECTION_MEDAL_RACE:
            self._display_medal_race(data)

        self.display_manager.update_display()

    def _display_medals(self, data: Optional[OlympicsData]) -> None:
        """Display medal count - cycles through individual country cards."""
        if not data or not data.medal_counts:
            self._draw_centered_text("No medal data")
            return

        medals = data.get_top_countries(self.top_countries_count)
        if not medals:
            self._draw_centered_text("No medal data")
            return

        # Ensure index is valid (cycling handled in _display_current_section)
        self._current_medal_index = min(self._current_medal_index, len(medals) - 1)

        # Render single country card at full display width
        medal = medals[self._current_medal_index]
        card = self.medal_renderer.render_medal_card(
            medal,
            card_width=self.display_manager.width
        )
        self.display_manager.image.paste(card, (0, 0))

    def _display_schedule(self, data: Optional[OlympicsData]) -> None:
        """Display upcoming events."""
        if not data or not data.upcoming_events:
            self._draw_centered_text("No events")
            return

        events = self._filter_events(data.upcoming_events)
        summary = self.event_renderer.render_events_summary(
            events[:self.upcoming_events_count],
            self.display_manager.width,
            self.display_manager.height,
            "UPCOMING"
        )
        self.display_manager.image.paste(summary, (0, 0))

    def _display_results(self, data: Optional[OlympicsData]) -> None:
        """Display recent results."""
        if not data or not data.recent_results:
            self._draw_centered_text("No results")
            return

        summary = self.event_renderer.render_results_summary(
            data.recent_results[:self.recent_results_count],
            self.display_manager.width,
            self.display_manager.height
        )
        self.display_manager.image.paste(summary, (0, 0))

    def _display_medal_race(self, data: Optional[OlympicsData]) -> None:
        """Display medal race comparison between countries."""
        if not data or not data.medal_counts:
            self._draw_centered_text("No medal data")
            return

        if not self.rival_countries or len(self.rival_countries) < 2:
            self._draw_centered_text("Need 2 rivals")
            return

        # Get medal counts for the first two rival countries
        country1 = data.get_country_medals(self.rival_countries[0])
        country2 = data.get_country_medals(self.rival_countries[1])

        if not country1 or not country2:
            self._draw_centered_text("Rivals not found")
            return

        race_img = self.medal_renderer.render_medal_race(
            country1, country2,
            self.display_manager.width,
            self.display_manager.height
        )
        self.display_manager.image.paste(race_img, (0, 0))

    def _display_countdown(self) -> None:
        """Display countdown to Olympics opening."""
        if not self.olympics_data:
            self._draw_centered_text("Loading...")
            return

        self.countdown_renderer.display_countdown(
            self.olympics_data.opening_date,
            self.olympics_data.games_name,
            self.olympics_data.games_type,
            is_closing=False
        )

    def _filter_events(self, events: list) -> list:
        """Filter events by sport preferences."""
        if not self.sport_filters:
            return events
        return [e for e in events if e.sport.lower() in self.sport_filters]

    def _draw_centered_text(self, text: str) -> None:
        """Draw centered text on display."""
        self.display_manager.draw_text(
            text,
            x=self.display_manager.width // 2,
            y=self.display_manager.height // 2 - 4,
            color=(128, 128, 128),
            centered=True
        )

    def _display_error(self, message: str) -> None:
        """Display error message."""
        self.display_manager.clear()
        self._draw_centered_text(message)
        self.display_manager.update_display()

    # =========================================================================
    # Vegas Scroll Mode Support
    # =========================================================================

    def _compute_vegas_content_hash(self) -> str:
        """Compute a hash of Vegas mode content for change detection."""
        hash_parts = []

        with self._data_lock:
            data = self.olympics_data

        if not data:
            return "no_data"

        if not data.is_active:
            return f"countdown:{data.opening_date}"

        # Hash all displayable content
        if self.show_medals and data.medal_counts:
            medals = data.get_top_countries(self.top_countries_count)
            for m in medals:
                hash_parts.append(f"m:{m.country_code}:{m.gold}:{m.silver}:{m.bronze}")
            for country_code in self.additional_countries:
                medal = data.get_country_medals(country_code)
                if medal:
                    hash_parts.append(f"a:{medal.country_code}:{medal.total}")

        if self.show_schedule and data.upcoming_events:
            events = self._filter_events(data.upcoming_events)
            for e in events[:self.upcoming_events_count]:
                hash_parts.append(f"e:{e.sport}:{e.event_name}:{e.start_time}")

        if data.live_events:
            for e in data.live_events:
                if not self.sport_filters or e.sport.lower() in self.sport_filters:
                    hash_parts.append(f"l:{e.sport}:{e.event_name}")

        if self.show_results and data.recent_results:
            for r in data.recent_results[:self.recent_results_count]:
                hash_parts.append(f"r:{r.sport}:{r.event_name}:{r.gold_country}")

        return hashlib.md5("|".join(hash_parts).encode()).hexdigest()

    def has_vegas_content_changed(self) -> bool:
        """
        Check if Vegas content has changed since last retrieval.

        Useful for callers to decide whether to re-render.

        Returns:
            True if content has changed or never been retrieved
        """
        current_hash = self._compute_vegas_content_hash()
        changed = current_hash != self._last_vegas_content_hash
        return changed

    def get_vegas_content(self) -> Optional[List[Image.Image]]:
        """
        Get content for Vegas-style continuous scroll mode.

        Returns a list of PIL Images representing cards for:
        - Medal counts (top countries + favorites)
        - Upcoming events
        - Recent results

        Note: This method is non-blocking. If data is not available,
        it triggers a background update and returns None.

        Returns:
            List of PIL Images or None if no content
        """
        # Update content hash for change detection
        self._last_vegas_content_hash = self._compute_vegas_content_hash()

        # Get a thread-safe snapshot of the data
        with self._data_lock:
            data = self.olympics_data

        # Trigger background update if needed (non-blocking)
        self._trigger_background_update()

        if not data:
            return None

        # If Olympics not active, return countdown card
        if not data.is_active:
            countdown_card = self.countdown_renderer.render_countdown_card(
                data.opening_date,
                data.games_name,
                data.games_type,
                is_closing=False,
                width=80,
                height=self.display_manager.height
            )
            return [countdown_card]

        images = []

        # Add medal count cards
        if self.show_medals and data.medal_counts:
            medals = data.get_top_countries(self.top_countries_count)

            # Add top countries
            for medal in medals:
                card = self.medal_renderer.render_medal_card(medal)
                images.append(card)

            # Add any additional countries not in top N
            for country_code in self.additional_countries:
                medal = data.get_country_medals(country_code)
                if medal and medal.rank > self.top_countries_count:
                    card = self.medal_renderer.render_medal_card(medal)
                    images.append(card)

        # Add upcoming event cards
        if self.show_schedule and data.upcoming_events:
            events = self._filter_events(data.upcoming_events)
            for event in events[:self.upcoming_events_count]:
                card = self.event_renderer.render_upcoming_event(event)
                images.append(card)

        # Add live event cards with priority (prepend in order)
        if data.live_events:
            live_cards = []
            for event in data.live_events:
                if not self.sport_filters or event.sport.lower() in self.sport_filters:
                    card = self.event_renderer.render_live_event(event)
                    live_cards.append(card)
            # Prepend live cards while preserving their order
            images = live_cards + images

        # Add recent result cards
        if self.show_results and data.recent_results:
            for result in data.recent_results[:self.recent_results_count]:
                card = self.event_renderer.render_result_card(result)
                images.append(card)

        return images if images else None

    def get_vegas_content_type(self) -> str:
        """
        Indicate the type of content this plugin provides.

        Returns 'multi' for multiple scrollable items.
        """
        if self.olympics_data and (
            self.olympics_data.is_active or
            self.olympics_data.medal_counts or
            self.olympics_data.upcoming_events
        ):
            return 'multi'
        return 'none'

    def get_vegas_display_mode(self) -> VegasDisplayMode:
        """
        Get the display mode for Vegas scroll integration.

        Uses STATIC mode for live medal finals (pauses scroll),
        otherwise SCROLL mode for continuous scrolling.
        Thread-safe: acquires _data_lock for consistent read.
        """
        # Thread-safe snapshot for live finals check
        with self._data_lock:
            data = self.olympics_data
            has_live_finals = data.has_live_finals if data else False

        # Check for live finals that should pause the scroll
        if self.live_alerts_enabled and has_live_finals:
            return VegasDisplayMode.STATIC

        # Check config override
        config_mode = self.config.get('vegas_mode')
        if config_mode:
            # Map config string to VegasDisplayMode
            mode_map = {
                'scroll': VegasDisplayMode.SCROLL,
                'fixed': VegasDisplayMode.FIXED_SEGMENT,
                'static': VegasDisplayMode.STATIC,
            }
            if config_mode.lower() in mode_map:
                return mode_map[config_mode.lower()]

        return VegasDisplayMode.SCROLL

    def get_supported_vegas_modes(self) -> List[VegasDisplayMode]:
        """Return list of Vegas display modes this plugin supports."""
        return [VegasDisplayMode.SCROLL, VegasDisplayMode.FIXED_SEGMENT, VegasDisplayMode.STATIC]

    def has_live_content(self) -> bool:
        """
        Check if there is priority live content to display.

        Returns True if there are live medal-deciding events.
        """
        if not self.olympics_data or not self.live_alerts_enabled:
            return False
        return self.olympics_data.has_live_finals

    # =========================================================================
    # Plugin Info and Validation
    # =========================================================================

    def validate_config(self) -> bool:
        """Validate plugin configuration."""
        if not super().validate_config():
            return False

        # Validate text color
        if not isinstance(self.text_color, tuple) or len(self.text_color) != 3:
            self.logger.error("Invalid text_color: must be RGB tuple")
            return False

        try:
            color_ints = [int(c) for c in self.text_color]
            if not all(0 <= c <= 255 for c in color_ints):
                self.logger.error("Invalid text_color: values must be 0-255")
                return False
        except (ValueError, TypeError):
            self.logger.error("Invalid text_color: values must be numeric")
            return False

        # Validate country codes
        for code in self.additional_countries + self.rival_countries:
            if not isinstance(code, str) or len(code) != 3:
                self.logger.warning(f"Invalid country code: {code}")

        return True

    def get_info(self) -> Dict[str, Any]:
        """Return plugin info for web UI. Thread-safe."""
        info = super().get_info()

        # Thread-safe snapshot of olympics_data
        with self._data_lock:
            data = self.olympics_data
            olympics_active = data.is_active if data else False
            games_name = data.games_name if data else None
            medal_count = len(data.medal_counts) if data else 0
            upcoming_events = len(data.upcoming_events) if data else 0
            live_events = len(data.live_events) if data else 0
            has_live_finals = data.has_live_finals if data else False

        info.update({
            'olympics_active': olympics_active,
            'games_name': games_name,
            'medal_count': medal_count,
            'upcoming_events': upcoming_events,
            'live_events': live_events,
            'has_live_finals': has_live_finals,
            'last_fetch_error': self.data_fetcher.get_last_error(),
            'timezone': self.timezone,
            'top_countries_count': self.top_countries_count,
            'sport_filters': self.sport_filters,
        })

        return info

    def get_display_duration(self) -> float:
        """Get display duration from config."""
        return self.config.get('display_duration', 30.0)
