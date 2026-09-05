"""
Alerts renderer for Olympics plugin.

Renders special alert displays for:
- New Olympic records
- Medal celebrations for favorite countries
- Live medal event notifications
"""

import logging
from typing import Dict, Any, Optional
from PIL import Image, ImageDraw, ImageFont

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

    def render_record_alert(self, sport: str, event: str,
                           athlete: str, country: str,
                           record_type: str = "OR",
                           width: int = 128) -> Image.Image:
        """
        Render an Olympic record alert.

        Args:
            sport: Sport name
            event: Event name
            athlete: Athlete name
            country: Country code
            record_type: "OR" (Olympic Record) or "WR" (World Record)
            width: Display width

        Returns:
            PIL Image of the record alert
        """
        height = self.display_height
        img = Image.new('RGB', (width, height), BLACK)
        draw = ImageDraw.Draw(img)
        draw.fontmode = "1"  # Pixel fonts on an LED panel: 1-bit text so every lit pixel is fully lit (no AA fringe).

        # Flashing effect - alternate background
        flash_color = GOLD if record_type == "WR" else RED

        # Header: "NEW RECORD!"
        header_y = 1
        record_text = f"NEW {record_type}!"
        draw.text((2, header_y), record_text, font=self.font_large, fill=flash_color)

        # Sport + Event
        event_y = height // 3
        event_text = f"{sport}: {event}"[:30]
        draw.text((2, event_y), event_text, font=self.font_small, fill=CYAN)

        # Athlete (Country)
        athlete_y = (height * 2) // 3
        athlete_text = f"{athlete} ({country})"[:25]
        draw.text((2, athlete_y), athlete_text, font=self.font_small, fill=WHITE)

        return img

    def render_medal_celebration(self, country: str, medal_type: str,
                                 sport: str, event: str,
                                 athlete: str,
                                 width: int = 128) -> Image.Image:
        """
        Render a medal celebration for a favorite country.

        Args:
            country: Country code (e.g., "USA")
            medal_type: "gold", "silver", or "bronze"
            sport: Sport name
            event: Event name
            athlete: Athlete name
            width: Display width

        Returns:
            PIL Image of the celebration
        """
        height = self.display_height
        img = Image.new('RGB', (width, height), BLACK)
        draw = ImageDraw.Draw(img)
        draw.fontmode = "1"  # Pixel fonts on an LED panel: 1-bit text so every lit pixel is fully lit (no AA fringe).

        medal_colors = {
            "gold": GOLD,
            "silver": SILVER,
            "bronze": BRONZE,
        }
        medal_color = medal_colors.get(medal_type.lower(), GOLD)

        # Header with country and medal
        header_y = 1
        medal_char = {"gold": "G", "silver": "S", "bronze": "B"}.get(medal_type.lower(), "M")
        header_text = f"{country} WINS {medal_char}!"
        draw.text((2, header_y), header_text, font=self.font_large, fill=medal_color)

        # Sport and Event
        event_y = height // 3
        # Compose sport: event, truncate to fit
        if event and event != sport:
            event_text = f"{sport}: {event}"[:24]
        else:
            event_text = f"{sport}"[:24]
        draw.text((2, event_y), event_text, font=self.font_small, fill=WHITE)

        # Athlete
        athlete_y = (height * 2) // 3
        draw.text((2, athlete_y), athlete[:20], font=self.font_small, fill=CYAN)

        # Draw medal circle on right side
        medal_x = width - 12
        medal_y = height // 2
        medal_r = 4
        draw.ellipse(
            [(medal_x - medal_r, medal_y - medal_r),
             (medal_x + medal_r, medal_y + medal_r)],
            fill=medal_color
        )

        return img

    def render_live_final_alert(self, sport: str, event: str,
                                venue: str = "",
                                width: int = 128) -> Image.Image:
        """
        Render a live medal event alert.

        Args:
            sport: Sport name
            event: Event name
            venue: Venue name (shown on displays with enough vertical space)
            width: Display width

        Returns:
            PIL Image of the live alert
        """
        height = self.display_height
        img = Image.new('RGB', (width, height), BLACK)
        draw = ImageDraw.Draw(img)
        draw.fontmode = "1"  # Pixel fonts on an LED panel: 1-bit text so every lit pixel is fully lit (no AA fringe).

        # Pulsing "LIVE" indicator
        live_x = 2
        live_y = 1
        draw.rectangle([(live_x, live_y), (live_x + 20, live_y + 8)], fill=RED)
        draw.text((live_x + 2, live_y), "LIVE", font=self.font_small, fill=WHITE)

        # "FINAL" label
        final_x = live_x + 24
        draw.text((final_x, live_y), "FINAL", font=self.font_small, fill=GOLD)

        # Sport name
        event_y = height // 3
        event_text = f"{sport}"[:15]
        draw.text((2, event_y), event_text, font=self.font_large, fill=WHITE)

        # Event name
        name_y = height // 2 if venue and height > 32 else (height * 2) // 3
        draw.text((2, name_y), event[:25], font=self.font_small, fill=CYAN)

        # Venue (only shown if provided and display has enough space)
        if venue and height > 32:
            venue_y = (height * 3) // 4
            draw.text((2, venue_y), venue[:25], font=self.font_small, fill=GRAY)

        return img

    def render_next_event_countdown(self, sport: str, event: str,
                                    time_remaining: str,
                                    width: int = 128) -> Image.Image:
        """
        Render a countdown to the next event.

        Args:
            sport: Sport name
            event: Event name
            time_remaining: Formatted time string (e.g., "2h 15m")
            width: Display width

        Returns:
            PIL Image of the countdown
        """
        height = self.display_height
        img = Image.new('RGB', (width, height), BLACK)
        draw = ImageDraw.Draw(img)
        draw.fontmode = "1"  # Pixel fonts on an LED panel: 1-bit text so every lit pixel is fully lit (no AA fringe).

        # "NEXT" label
        draw.text((2, 1), "NEXT", font=self.font_small, fill=ORANGE)

        # Countdown time - right-align based on actual text width
        time_width = self._get_text_width(draw, time_remaining, self.font_small)
        time_x = width - time_width - 2
        draw.text((time_x, 1), time_remaining, font=self.font_small, fill=GREEN)

        # Sport
        sport_y = height // 3
        draw.text((2, sport_y), sport[:20], font=self.font_large, fill=WHITE)

        # Event
        event_y = (height * 2) // 3
        draw.text((2, event_y), event[:30], font=self.font_small, fill=CYAN)

        return img

    def render_medal_summary_flash(self, country: str, gold: int,
                                   silver: int, bronze: int,
                                   rank: int,
                                   width: int = 80) -> Image.Image:
        """
        Render a quick medal summary flash for Vegas mode.

        Args:
            country: Country code
            gold, silver, bronze: Medal counts
            rank: Current rank
            width: Card width

        Returns:
            PIL Image of the summary
        """
        height = self.display_height
        img = Image.new('RGB', (width, height), BLACK)
        draw = ImageDraw.Draw(img)
        draw.fontmode = "1"  # Pixel fonts on an LED panel: 1-bit text so every lit pixel is fully lit (no AA fringe).

        # Country + Rank
        header_y = 2
        draw.text((2, header_y), f"#{rank} {country}", font=self.font_large, fill=WHITE)

        # Medals in color
        medal_y = height // 2 + 2
        x = 2

        # Gold
        draw.text((x, medal_y), str(gold), font=self.font_small, fill=GOLD)
        x += self._get_text_width(draw, str(gold), self.font_small) + 3

        # Silver
        draw.text((x, medal_y), str(silver), font=self.font_small, fill=SILVER)
        x += self._get_text_width(draw, str(silver), self.font_small) + 3

        # Bronze
        draw.text((x, medal_y), str(bronze), font=self.font_small, fill=BRONZE)

        return img

    def _get_text_width(self, draw: ImageDraw.ImageDraw, text: str,
                        font: ImageFont.FreeTypeFont) -> int:
        """Get width of text with given font."""
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            return bbox[2] - bbox[0]
        except AttributeError:
            return len(text) * 6
