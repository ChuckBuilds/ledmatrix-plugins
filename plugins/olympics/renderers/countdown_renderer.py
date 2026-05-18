"""
Countdown display renderer for Olympics plugin.

Renders countdown cards showing days until Olympics opening/closing.
Supports both Vegas scroll mode and regular display mode.
"""

import logging
from datetime import date, datetime
from typing import Dict, Any, Optional
from pathlib import Path
from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)

# Colors
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
GRAY = (128, 128, 128)
GOLD = (255, 215, 0)


class CountdownRenderer:
    """
    Renders countdown displays for Olympics.

    Shows days remaining until opening or closing ceremony
    with Olympics logo and styled text.
    """

    def __init__(self, display_manager, config: Dict[str, Any]):
        """
        Initialize the countdown renderer.

        Args:
            display_manager: LEDMatrix display manager
            config: Plugin configuration
        """
        self.display_manager = display_manager
        self.config = config
        self.logo_image: Optional[Image.Image] = None

        # Colors from config
        text_color = config.get('text_color', [255, 255, 255])
        self.text_color = tuple(text_color) if isinstance(text_color, list) else text_color

        # Load logo
        self._load_logo_image()

    def _load_logo_image(self) -> None:
        """Load Olympics logo image from plugin directory."""
        try:
            plugin_dir = Path(__file__).parent.parent

            possible_names = [
                "olympics-logo.png",
                "olympics logo.png",
                "olympics-icon.png",
                "logo.png",
                "assets/olympics-logo.png",
            ]

            for name in possible_names:
                logo_path = plugin_dir / name
                if logo_path.exists():
                    img = Image.open(logo_path)
                    img.load()  # Force read so file handle can be closed
                    self.logo_image = img
                    logger.info(f"Loaded Olympics logo from {logo_path}")
                    return

            logger.debug("Olympics logo not found, will use programmatic drawing")

        except Exception as e:
            logger.warning(f"Error loading logo: {e}")

    def _draw_olympics_rings(self, width: int, height: int) -> Image.Image:
        """
        Draw Olympic rings programmatically.

        Args:
            width: Width of the image
            height: Height of the image

        Returns:
            PIL Image with Olympic rings
        """
        img = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        ring_colors = [
            (0, 129, 200),    # Blue
            (64, 64, 64),     # Dark gray (black ring visible on dark bg)
            (255, 20, 24),    # Red
            (255, 195, 0),    # Yellow
            (0, 158, 96)      # Green
        ]

        ring_radius = min(width, height) // 6
        center_x = width // 2
        center_y = height // 2

        # Top row (3 rings)
        top_y = center_y - ring_radius
        for i, color in enumerate(ring_colors[:3]):
            x = center_x - ring_radius + (i * int(ring_radius * 1.5))
            bbox = [x - ring_radius, top_y - ring_radius, x + ring_radius, top_y + ring_radius]
            draw.ellipse(bbox, outline=color, width=max(1, ring_radius // 8))

        # Bottom row (2 rings)
        bottom_y = center_y + ring_radius
        for i, color in enumerate(ring_colors[3:]):
            x = center_x + (i * int(ring_radius * 1.5))
            bbox = [x - ring_radius, bottom_y - ring_radius, x + ring_radius, bottom_y + ring_radius]
            draw.ellipse(bbox, outline=color, width=max(1, ring_radius // 8))

        return img

    def _get_logo_image(self, width: int, height: int) -> Image.Image:
        """
        Get Olympics logo scaled to specified dimensions.

        Args:
            width: Maximum width
            height: Maximum height

        Returns:
            PIL Image of logo
        """
        if self.logo_image:
            img_width, img_height = self.logo_image.size
            width_ratio = width / img_width
            height_ratio = height / img_height
            scale_ratio = min(width_ratio, height_ratio)

            new_width = int(img_width * scale_ratio)
            new_height = int(img_height * scale_ratio)

            try:
                resized = self.logo_image.resize((new_width, new_height), Image.Resampling.LANCZOS)
            except AttributeError:
                resized = self.logo_image.resize((new_width, new_height), Image.LANCZOS)

            return resized
        else:
            return self._draw_olympics_rings(width, height)

    def _calculate_days_until(self, target_date: datetime) -> int:
        """Calculate days until target date."""
        today = date.today()
        if isinstance(target_date, datetime):
            target = target_date.date()
        else:
            target = target_date
        return (target - today).days

    def render_countdown_card(self, target_date: datetime, _games_name: str,
                              games_type: str, is_closing: bool = False,
                              width: Optional[int] = None,
                              height: Optional[int] = None) -> Image.Image:
        """
        Render a countdown card for Vegas scroll mode.

        Args:
            target_date: Date to count down to
            _games_name: Name of the games (unused, kept for API compatibility)
            games_type: Type of games ("winter" or "summer")
            is_closing: True if counting down to closing
            width: Optional card width
            height: Optional card height

        Returns:
            PIL Image with countdown card
        """
        w = width or 80
        h = height or self.display_manager.height

        img = Image.new('RGB', (w, h), BLACK)
        draw = ImageDraw.Draw(img)

        days = self._calculate_days_until(target_date)
        margin = 2

        # Logo on left (25% of width)
        logo_width = w // 4
        logo_height = h - 4
        logo = self._get_logo_image(logo_width, logo_height)
        if logo.mode == 'RGBA':
            img.paste(logo, (margin, margin), logo)
        else:
            img.paste(logo, (margin, margin))

        # Text on right
        text_x = logo_width + 6

        # Row 1: Days count
        y1 = margin
        days_text = str(days)
        font = self.display_manager.regular_font if hasattr(self.display_manager, 'regular_font') else None
        if font:
            draw.text((text_x, y1), days_text, font=font, fill=GOLD)
        else:
            draw.text((text_x, y1), days_text, fill=GOLD)

        # Row 2: "DAYS"
        y2 = h // 3
        small_font = self.display_manager.small_font if hasattr(self.display_manager, 'small_font') else None
        if small_font:
            draw.text((text_x, y2), "DAYS", font=small_font, fill=WHITE)
        else:
            draw.text((text_x, y2), "DAYS", fill=WHITE)

        # Row 3: Target
        y3 = (h * 2) // 3
        target_text = "CLOSING" if is_closing else games_type.upper()[:6]
        if small_font:
            draw.text((text_x, y3), target_text, font=small_font, fill=self.text_color)
        else:
            draw.text((text_x, y3), target_text, fill=self.text_color)

        return img

    def display_countdown(self, target_date: datetime, _games_name: str,
                          games_type: str = "winter", is_closing: bool = False) -> None:
        """
        Display countdown on the full display (switch mode).

        Shows Olympics logo on left half, countdown text on right half.

        Args:
            target_date: Date to count down to
            _games_name: Name of the games (unused, kept for API compatibility)
            games_type: Type of games
            is_closing: True if counting down to closing
        """
        width = self.display_manager.width
        height = self.display_manager.height

        self.display_manager.clear()

        days = self._calculate_days_until(target_date)

        # Determine message lines
        if days == 0:
            if is_closing:
                lines = ["OLYMPICS", "CLOSING", "TODAY"]
            else:
                lines = ["OLYMPICS", "OPENING", "TODAY"]
        else:
            if is_closing:
                lines = [str(days), "DAYS UNTIL", "CLOSING"]
            else:
                lines = [str(days), "DAYS UNTIL", games_type.upper(), "OLYMPICS"]

        # Split display: logo on left, text on right
        left_half_width = width // 2
        right_half_width = width - left_half_width

        # Draw logo on left
        logo_margin = 2
        logo_width = left_half_width - (2 * logo_margin)
        logo_height = height - (2 * logo_margin)
        logo = self._get_logo_image(logo_width, logo_height)

        if logo.mode == 'RGBA':
            self.display_manager.image.paste(logo, (logo_margin, logo_margin), logo)
        else:
            self.display_manager.image.paste(logo, (logo_margin, logo_margin))

        # Draw text on right, centered
        line_height = height // len(lines)
        start_y = (height - (line_height * len(lines))) // 2

        for i, line in enumerate(lines):
            y = start_y + (i * line_height)
            center_x = left_half_width + (right_half_width // 2)

            # Use display_manager's draw_text for proper font handling
            self.display_manager.draw_text(
                line,
                x=center_x,
                y=y,
                color=self.text_color,
                centered=True
            )

        self.display_manager.update_display()
