"""
Alerts renderer for Olympics plugin.

Renders special alert displays for:
- New Olympic records
- Medal celebrations for favorite countries
- Live medal event notifications
"""

import logging
from typing import Dict, Any, Optional
from PIL import ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# Colors
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
GRAY = (128, 128, 128)
GOLD = (255, 215, 0)
SILVER = (192, 192, 192)
BRONZE = (205, 127, 50)
RED = (255, 50, 50)
GREEN = (0, 255, 0)
CYAN = (0, 200, 255)
YELLOW = (255, 255, 0)
ORANGE = (255, 165, 0)


class AlertsRenderer:
    """Renders special alert displays."""

    def __init__(self, display_height: int, config: Dict[str, Any],
                 fonts: Optional[Dict[str, Any]] = None):
        """
        Initialize the alerts renderer.

        Args:
            display_height: Height of display in pixels
            config: Plugin configuration
            fonts: Optional dict of fonts to use
        """
        self.display_height = display_height
        self.config = config
        self.fonts = fonts or {}

        self._init_fonts()

    def _init_fonts(self) -> None:
        """Initialize fonts for rendering."""
        try:
            self.font_large = self.fonts.get('regular') or ImageFont.load_default()
            self.font_small = self.fonts.get('small') or self.font_large
        except Exception as e:
            logger.warning(f"Error loading fonts: {e}")
            self.font_large = ImageFont.load_default()
            self.font_small = self.font_large

    def _get_text_width(self, draw: ImageDraw.ImageDraw, text: str,
                        font: ImageFont.FreeTypeFont) -> int:
        """Get width of text with given font."""
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            return bbox[2] - bbox[0]
        except AttributeError:
            return len(text) * 6
