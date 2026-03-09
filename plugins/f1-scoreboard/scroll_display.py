"""
Scroll Display Handler for F1 Scoreboard Plugin

Implements horizontal scrolling of F1 standings, results, qualifying,
practice, sprint, and calendar cards using ScrollHelper.
"""

import logging
from typing import Any, Dict, List, Optional

from PIL import Image

try:
    from src.common.scroll_helper import ScrollHelper
except ImportError as _scroll_import_err:
    ScrollHelper = None
    logging.getLogger(__name__).warning(
        "ScrollHelper not available, scrolling disabled: %s",
        _scroll_import_err)

logger = logging.getLogger(__name__)


class ScrollDisplay:
    """
    Handles scroll display for a single F1 display mode.

    Pre-renders content cards, composes them into a scrolling image,
    and manages scroll state.
    """

    def __init__(self, display_manager, config: Optional[Dict[str, Any]] = None,
                 custom_logger: Optional[logging.Logger] = None):
        self.display_manager = display_manager
        self.config = config or {}
        self.logger = custom_logger or logger

        # Get display dimensions
        if hasattr(display_manager, "matrix") and display_manager.matrix:
            self.display_width = display_manager.matrix.width
            self.display_height = display_manager.matrix.height
        else:
            self.display_width = getattr(display_manager, "width", 128)
            self.display_height = getattr(display_manager, "height", 32)

        # Initialize ScrollHelper with config-driven parameters
        self.scroll_helper = None
        if ScrollHelper:
            self.scroll_helper = ScrollHelper(
                self.display_width,
                self.display_height,
                self.logger
            )
            scroll_cfg = self.config.get("scroll", {})
            if not isinstance(scroll_cfg, dict):
                scroll_cfg = {}
            self.scroll_helper.set_frame_based_scrolling(
                scroll_cfg.get("frame_based", True))
            self.scroll_helper.set_scroll_speed(
                scroll_cfg.get("scroll_speed", 1))
            self.scroll_helper.set_scroll_delay(
                scroll_cfg.get("scroll_delay", 0.03))
            self.scroll_helper.set_dynamic_duration_settings(
                enabled=True,
                min_duration=scroll_cfg.get("min_duration", 15),
                max_duration=scroll_cfg.get("max_duration", 120),
                buffer=self.display_width
            )

        # Content state
        self._content_items: List[Image.Image] = []
        self._vegas_content_items: List[Image.Image] = []
        self._is_prepared = False

    def prepare_scroll_content(self, cards: List[Image.Image],
                                separator: Image.Image = None):
        """
        Prepare scroll content from pre-rendered cards.

        Args:
            cards: List of PIL Images to scroll through
            separator: Optional separator image between cards
        """
        if not cards:
            self._content_items = []
            self._vegas_content_items = []
            self._is_prepared = False
            return

        self._content_items = list(cards)
        self._vegas_content_items = list(cards)

        if self.scroll_helper:
            # Build content items list with separators
            content_with_seps = []
            for i, card in enumerate(cards):
                content_with_seps.append(card)
                if separator and i < len(cards) - 1:
                    content_with_seps.append(separator)

            self.scroll_helper.create_scrolling_image(
                content_with_seps,
                item_gap=4,
                element_gap=2
            )

        self._is_prepared = True

    def display_scroll_frame(self, force_clear: bool = False) -> bool:
        """
        Display the next scroll frame.

        Args:
            force_clear: Whether to force clear the display first

        Returns:
            True if scroll is complete (looped), False otherwise
        """
        if not self.scroll_helper or not self._is_prepared:
            # Static fallback: show first card when scrolling unavailable
            if self._content_items:
                first = self._content_items[0]
                if isinstance(first, Image.Image):
                    self.display_manager.image.paste(first, (0, 0))
                    self.display_manager.update_display()
            return True

        if force_clear:
            self.scroll_helper.reset_scroll()

        self.scroll_helper.update_scroll_position()
        visible = self.scroll_helper.get_visible_portion()

        if visible:
            if isinstance(visible, Image.Image):
                self.display_manager.image.paste(visible, (0, 0))
            else:
                # Numpy array
                pil_image = Image.fromarray(visible)
                self.display_manager.image.paste(pil_image, (0, 0))
            self.display_manager.update_display()

        return self.scroll_helper.is_scroll_complete()

    def reset(self):
        """Reset scroll position to beginning."""
        if self.scroll_helper:
            self.scroll_helper.reset_scroll()

    def is_prepared(self) -> bool:
        """Check if content has been prepared for scrolling."""
        return self._is_prepared

    def get_content_count(self) -> int:
        """Get the number of content items."""
        return len(self._content_items)

    def is_scroll_complete(self) -> bool:
        """Check if the scroll cycle has completed."""
        if not self.scroll_helper or not self._is_prepared:
            return True
        return self.scroll_helper.is_scroll_complete()

    def get_vegas_items(self) -> List[Image.Image]:
        """Get the vegas content items for this display."""
        return self._vegas_content_items


class ScrollDisplayManager:
    """
    Manages multiple ScrollDisplay instances, one per display mode.
    """

    def __init__(self, display_manager, config: Optional[Dict[str, Any]] = None,
                 custom_logger: Optional[logging.Logger] = None):
        self.display_manager = display_manager
        self.config = config or {}
        self.logger = custom_logger or logger

        self._scroll_displays: Dict[str, ScrollDisplay] = {}

    def get_or_create(self, mode_key: str) -> ScrollDisplay:
        """Get or create a ScrollDisplay for a given mode."""
        if mode_key not in self._scroll_displays:
            self._scroll_displays[mode_key] = ScrollDisplay(
                self.display_manager,
                self.config,
                self.logger
            )
        return self._scroll_displays[mode_key]

    def prepare_and_display(self, mode_key: str, cards: List[Image.Image],
                             separator: Image.Image = None):
        """Prepare scroll content for a mode."""
        sd = self.get_or_create(mode_key)
        sd.prepare_scroll_content(cards, separator)

    def display_frame(self, mode_key: str,
                      force_clear: bool = False) -> bool:
        """Display a scroll frame for a mode. Returns True if complete."""
        if mode_key not in self._scroll_displays:
            return True
        return self._scroll_displays[mode_key].display_scroll_frame(
            force_clear)

    def reset_mode(self, mode_key: str):
        """Reset scroll position for a mode."""
        if mode_key in self._scroll_displays:
            self._scroll_displays[mode_key].reset()

    def get_all_vegas_content_items(self) -> List[Image.Image]:
        """Collect all vegas content items across all modes."""
        items = []
        for sd in self._scroll_displays.values():
            items.extend(sd.get_vegas_items())
        return items

    def is_mode_prepared(self, mode_key: str) -> bool:
        """Check if a mode has prepared content."""
        if mode_key not in self._scroll_displays:
            return False
        return self._scroll_displays[mode_key].is_prepared()

    def is_scroll_complete(self, mode_key: str) -> bool:
        """Check if a mode's scroll cycle has completed."""
        if mode_key not in self._scroll_displays:
            return True
        return self._scroll_displays[mode_key].is_scroll_complete()

    def get_vegas_items_for_mode(self, mode_key: str) -> List[Image.Image]:
        """Get vegas content items for a specific mode."""
        if mode_key not in self._scroll_displays:
            return []
        return self._scroll_displays[mode_key].get_vegas_items()
