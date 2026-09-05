"""
Event and result card renderer for Olympics plugin.

Renders upcoming events, live events, and results for display
in both Vegas scroll mode and regular switch mode.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

try:
    import pytz
except ImportError:
    pytz = None

try:
    from data.data_models import OlympicEvent, EventResult
except ImportError:
    from ..data.data_models import OlympicEvent, EventResult

from typing import Tuple

logger = logging.getLogger(__name__)

# Colors
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
GRAY = (128, 128, 128)
YELLOW = (255, 255, 0)
GREEN = (0, 255, 0)
RED = (255, 0, 0)
GOLD_COLOR = (255, 215, 0)
SILVER_COLOR = (192, 192, 192)
BRONZE_COLOR = (205, 127, 50)
CYAN = (0, 255, 255)

# Text transformations for event names
# Includes both abbreviations (to save space) and expansions (for clarity)
# Note: str.replace is called iteratively, so order matters
EVENT_TEXT_TRANSFORMS = {
    # Gender formatting (drop apostrophe)
    "Men's": "Mens",
    "Women's": "Womens",
    "men's": "Mens",
    "women's": "Womens",
    # Remove "Official" from event names (e.g., "Men's Official Training Run 5")
    "Official ": "",
    "official ": "",
    " Official": "",
    " official": "",
    # Expand ski jumping hill abbreviations
    " LH ": " Large Hill ",
    " LH-": " Large Hill-",
    " NH ": " Normal Hill ",
    " NH-": " Normal Hill-",
    # Expand alpine skiing abbreviations
    " DH ": " Downhill ",
    " SL ": " Slalom ",
    " GS ": " Giant Slalom ",
    " SG ": " Super-G ",
    " AC ": " Alpine Combined ",
    # Expand Nordic Combined abbreviations
    "Ind. Gund.": "Individual Gundersen",
    "Gund.": "Gundersen",
    "Ind.": "Individual",
    ", SJP ": ", Ski Jump ",
    # Expand team event abbreviations
    "TC ": "Team ",
}


class EventCardRenderer:
    """
    Renders event schedule and result cards.

    Creates PIL Images for upcoming events, live events,
    and completed results with medal winners.
    """

    def __init__(self, display_height: int, config: Dict[str, Any],
                 fonts: Optional[Dict[str, Any]] = None):
        """
        Initialize the event card renderer.

        Args:
            display_height: Height of display in pixels
            config: Plugin configuration
            fonts: Optional dict of fonts to use
        """
        self.display_height = display_height
        self.config = config
        self.fonts = fonts or {}
        self.timezone_str = config.get('timezone', 'UTC')
        self.flag_cache: Dict[str, Image.Image] = {}

        # Calculate card dimensions based on display height
        if display_height <= 32:
            self.card_width = 80
            self.font_size_large = 8
            self.font_size_small = 6
        elif display_height <= 64:
            self.card_width = 100
            self.font_size_large = 10
            self.font_size_small = 8
        else:
            self.card_width = 120
            self.font_size_large = 12
            self.font_size_small = 10

        self._init_fonts()

    def _init_fonts(self) -> None:
        """Initialize fonts for rendering."""
        try:
            if 'regular' in self.fonts:
                self.font_large = self.fonts['regular']
            else:
                self.font_large = ImageFont.load_default()

            if 'small' in self.fonts:
                self.font_small = self.fonts['small']
            else:
                self.font_small = self.font_large

        except Exception as e:
            logger.warning(f"Error loading fonts: {e}")
            self.font_large = ImageFont.load_default()
            self.font_small = self.font_large

    def _load_flag(self, country_code: str, size: Tuple[int, int]) -> Optional[Image.Image]:
        """Load and cache a country flag image."""
        cache_key = f"{country_code}_{size[0]}x{size[1]}"
        if cache_key in self.flag_cache:
            return self.flag_cache[cache_key]

        flag_paths = [
            Path(__file__).parent.parent / 'assets' / 'country_flags' / f"{country_code.lower()}.png",
            Path(__file__).parent.parent / 'assets' / 'country_flags' / f"{country_code.upper()}.png",
        ]

        for flag_path in flag_paths:
            if flag_path.exists():
                try:
                    with Image.open(flag_path) as img:
                        flag = img.resize(size, Image.Resampling.NEAREST)
                        flag.load()
                    self.flag_cache[cache_key] = flag
                    return flag
                except Exception as e:
                    logger.debug(f"Error loading flag {flag_path}: {e}")

        return None

    def _get_text_width(self, draw: ImageDraw.ImageDraw, text: str, font) -> int:
        """Get actual pixel width of text with given font."""
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            return bbox[2] - bbox[0]
        except AttributeError:
            # Fallback for older PIL versions
            return len(text) * 6

    def _transform_event_name(self, text: str) -> str:
        """Transform event names for display (expand abbreviations, format text)."""
        result = text
        for pattern, replacement in EVENT_TEXT_TRANSFORMS.items():
            result = result.replace(pattern, replacement)
        return result

    def _truncate_to_width(self, draw: ImageDraw.ImageDraw, text: str,
                           max_width: int, font) -> str:
        """Truncate text to fit within pixel width, using actual measurement."""
        # First abbreviate
        text = self._transform_event_name(text)

        # Check if it fits
        if self._get_text_width(draw, text, font) <= max_width:
            return text

        # Binary search for best fit
        for i in range(len(text), 0, -1):
            truncated = text[:i] + ".."
            if self._get_text_width(draw, truncated, font) <= max_width:
                return truncated

        # Fallback: try progressively smaller strings that fit
        for fallback in ["..", ".", ""]:
            if self._get_text_width(draw, fallback, font) <= max_width:
                return fallback

        return ""

    def _get_timezone(self):
        """Get timezone object for formatting."""
        if pytz and self.timezone_str:
            try:
                return pytz.timezone(self.timezone_str)
            except Exception:
                return pytz.UTC
        return None

    def _format_event_time(self, event_time: datetime) -> str:
        """
        Format event time for user's timezone with relative date.

        Returns strings like "10:30 AM TODAY" or "Feb 10 2:00 PM"
        """
        tz = self._get_timezone()

        if tz and pytz:
            # Ensure event_time is timezone-aware
            if event_time.tzinfo is None:
                event_time = pytz.UTC.localize(event_time)

            local_time = event_time.astimezone(tz)
            now = datetime.now(tz)

            # Format time
            time_str = local_time.strftime("%I:%M %p").lstrip("0")

            # Determine relative date
            if local_time.date() == now.date():
                return f"{time_str} TODAY"
            elif local_time.date() == (now + timedelta(days=1)).date():
                return f"{time_str} TMW"
            else:
                date_str = local_time.strftime("%b %d")
                return f"{date_str} {time_str}"
        else:
            # Fallback without pytz
            return event_time.strftime("%m/%d %H:%M")

    def _truncate_text(self, text: str, max_chars: int) -> str:
        """Truncate text to max characters with ellipsis (fallback method)."""
        text = self._transform_event_name(text)
        if len(text) <= max_chars:
            return text
        # Handle very small max_chars values
        if max_chars < 3:
            return "." * max_chars
        return text[:max(0, max_chars - 2)] + ".."

    def _split_text_lines(self, text: str, max_width: int, draw: ImageDraw.ImageDraw,
                           font, max_lines: int = 2) -> List[str]:
        """
        Split text into multiple lines to fit within max_width.

        Args:
            text: Text to split
            max_width: Maximum pixel width per line
            draw: ImageDraw for measuring text
            font: Font to use for measurement
            max_lines: Maximum number of lines to produce

        Returns:
            List of text lines
        """
        # If it fits on one line, return as-is
        if self._get_text_width(draw, text, font) <= max_width:
            return [text]

        words = text.split()
        lines = []
        current_line = ""

        for word in words:
            test_line = f"{current_line} {word}".strip() if current_line else word

            if self._get_text_width(draw, test_line, font) <= max_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                    if len(lines) >= max_lines:
                        # Truncate remaining words
                        remaining = " ".join(words[words.index(word):])
                        if self._get_text_width(draw, remaining, font) > max_width:
                            # Truncate last line
                            lines[-1] = self._truncate_to_width(draw, lines[-1], max_width, font)
                        break
                    current_line = word
                else:
                    # Single word too long, truncate it
                    current_line = self._truncate_to_width(draw, word, max_width, font)

        if current_line and len(lines) < max_lines:
            lines.append(current_line)

        return lines if lines else [text]

    def render_upcoming_event(self, event: OlympicEvent,
                              card_width: Optional[int] = None) -> Image.Image:
        """
        Render an upcoming event card with line breaks for long event names.

        Layout (2-block: left info, right time):
        +----------------------------------------+
        | ALPINE SKIING  FNL  |  10:30 AM TODAY  |
        | Mens Downhill       |                  |
        | Giant Slalom        |                  |
        +----------------------------------------+

        Args:
            event: OlympicEvent object
            card_width: Optional override for card width (None = auto-size for scrolling)

        Returns:
            PIL Image of event card
        """
        height = self.display_height
        margin = 2

        # Prepare text content
        sport_text = event.sport.upper()
        event_text = self._transform_event_name(event.event_name)
        time_text = self._format_event_time(event.start_time)
        fnl_text = "FNL" if event.is_final else ""

        # Calculate text measurements
        temp_img = Image.new('RGB', (1, 1), BLACK)
        temp_draw = ImageDraw.Draw(temp_img)

        sport_w = self._get_text_width(temp_draw, sport_text, self.font_small)
        fnl_w = self._get_text_width(temp_draw, fnl_text, self.font_small) + 6 if event.is_final else 0
        time_w = self._get_text_width(temp_draw, time_text, self.font_small)

        # Split event name into lines (max line width for left block)
        max_event_line_width = 80  # Reasonable width for event text
        event_lines = self._split_text_lines(event_text, max_event_line_width, temp_draw,
                                              self.font_small, max_lines=2)

        # Calculate widths for each line
        event_lines_w = max(self._get_text_width(temp_draw, line, self.font_small)
                           for line in event_lines)

        # Calculate width based on content if not specified (for Vegas scroll)
        if card_width is None:
            # Two blocks: left (sport + event lines) + gap + right (time)
            left_block_w = max(sport_w + fnl_w, event_lines_w)
            width = left_block_w + 12 + time_w + margin * 2
            width = max(width, 80)
        else:
            width = card_width
            left_block_w = max(sport_w + fnl_w, event_lines_w)

        img = Image.new('RGB', (width, height), BLACK)
        draw = ImageDraw.Draw(img)
        draw.fontmode = "1"  # Pixel fonts on an LED panel: 1-bit text so every lit pixel is fully lit (no AA fringe).

        # Recalculate event lines with actual draw context
        event_lines = self._split_text_lines(event_text, max_event_line_width, draw,
                                              self.font_small, max_lines=2)

        # Calculate vertical distribution
        line_height = 8 if height <= 32 else 10
        num_rows = 1 + len(event_lines)  # Sport row + event lines
        total_text_height = num_rows * line_height
        start_y = (height - total_text_height) // 2

        # LEFT BLOCK: Sport + Event lines (vertically centered)
        y = start_y

        # Row 1: Sport name + FNL indicator
        draw.text((margin, y), sport_text, font=self.font_small, fill=CYAN)
        if event.is_final:
            draw.text((margin + sport_w + 6, y), fnl_text, font=self.font_small, fill=GOLD_COLOR)
        y += line_height

        # Event name lines
        for line in event_lines:
            draw.text((margin, y), line, font=self.font_small, fill=WHITE)
            y += line_height

        # RIGHT BLOCK: Time (vertically centered)
        left_block_w = max(sport_w + fnl_w, event_lines_w)
        time_x = margin + left_block_w + 12
        time_y = (height - line_height) // 2
        draw.text((time_x, time_y), time_text, font=self.font_small, fill=YELLOW)

        return img

    def render_live_event(self, event: OlympicEvent,
                          card_width: Optional[int] = None) -> Image.Image:
        """
        Render a live event card with highlighted styling.

        Args:
            event: OlympicEvent object with status='live'
            card_width: Optional override for card width (None = auto-size for scrolling)

        Returns:
            PIL Image of live event card
        """
        height = self.display_height
        margin = 2

        # Prepare text content
        live_text = "LIVE"
        sport_text = event.sport.upper()
        event_text = self._transform_event_name(event.event_name)
        round_text = self._transform_event_name(event.round) if event.round else ""

        # Calculate width based on content if not specified (for Vegas scroll)
        if card_width is None:
            temp_img = Image.new('RGB', (1, 1), BLACK)
            temp_draw = ImageDraw.Draw(temp_img)

            live_w = self._get_text_width(temp_draw, live_text, self.font_small)
            sport_w = self._get_text_width(temp_draw, sport_text, self.font_small)
            row1_w = live_w + 6 + sport_w  # LIVE + gap + sport
            event_w = self._get_text_width(temp_draw, event_text, self.font_small)
            round_w = self._get_text_width(temp_draw, round_text, self.font_small) if round_text else 0

            content_width = max(row1_w, event_w, round_w)
            width = content_width + margin * 2 + 4
            width = max(width, 60)
        else:
            width = card_width

        img = Image.new('RGB', (width, height), BLACK)
        draw = ImageDraw.Draw(img)
        draw.fontmode = "1"  # Pixel fonts on an LED panel: 1-bit text so every lit pixel is fully lit (no AA fringe).

        # Calculate line height based on display size
        line_height = 8 if height <= 32 else 10
        gap = 2

        # Determine how many rows we can fit
        available_height = height - margin * 2
        num_rows = 3 if round_text else 2
        min_height_for_3_rows = line_height * 3 + gap * 2

        # Calculate vertical positions based on available space
        if num_rows == 3 and available_height < min_height_for_3_rows:
            # Not enough space for 3 rows, skip round_text
            num_rows = 2
            round_text = ""

        if num_rows == 2:
            # Two rows: LIVE+sport and event name
            total_content_height = line_height * 2 + gap
            start_y = margin + (available_height - total_content_height) // 2
            y1 = start_y
            y2 = start_y + line_height + gap
        else:
            # Three rows: evenly distributed
            total_content_height = line_height * 3 + gap * 2
            start_y = margin + (available_height - total_content_height) // 2
            y1 = start_y
            y2 = start_y + line_height + gap
            y3 = start_y + (line_height + gap) * 2

        # Row 1: "LIVE" + Sport name
        draw.text((margin, y1), live_text, font=self.font_small, fill=RED)
        live_w = self._get_text_width(draw, live_text, self.font_small)
        draw.text((margin + live_w + 6, y1), sport_text, font=self.font_small, fill=CYAN)

        # Row 2: Event name
        draw.text((margin, y2), event_text, font=self.font_small, fill=WHITE)

        # Row 3: Round info if available and space permits
        if round_text and num_rows == 3:
            draw.text((margin, y3), round_text, font=self.font_small, fill=YELLOW)

        return img

    def render_result_card(self, result: EventResult,
                           card_width: Optional[int] = None) -> Image.Image:
        """
        Render a completed event result card with two-block layout.

        Layout (scrolls horizontally, more compact with line breaks):
        +-----------------------------------------------+
        | SNOWBOARD      | [FLAG] USA  J.Smith      G  |
        | Mens Slope     | [FLAG] NOR  A.Muller     S  |
        | Style          | [FLAG] GER  K.Weber      B  |
        +-----------------------------------------------+

        Left block: Sport + Event name (stacked, with line breaks)
        Right block: Flag + Country + Athlete + Medal label (stacked)

        Args:
            result: EventResult object
            card_width: Optional override for card width (None = auto-size for scrolling)

        Returns:
            PIL Image of result card
        """
        height = self.display_height
        margin = 2

        # 1/3 height flags for medals block (larger, prominent)
        flag_height = height // 3
        flag_width = int(flag_height * 1.5)
        flag_size = (flag_width, flag_height)

        # Prepare text content
        sport_text = result.sport.upper()
        event_text = self._transform_event_name(result.event_name)

        medalists = [
            ("G", result.gold_athlete, result.gold_country, GOLD_COLOR),
            ("S", result.silver_athlete, result.silver_country, SILVER_COLOR),
            ("B", result.bronze_athlete, result.bronze_country, BRONZE_COLOR),
        ]

        # Calculate width based on content
        temp_img = Image.new('RGB', (1, 1), BLACK)
        temp_draw = ImageDraw.Draw(temp_img)

        # Left block: sport and event with line breaks
        sport_w = self._get_text_width(temp_draw, sport_text, self.font_small)
        max_event_line_width = 70  # Keep left block compact
        event_lines = self._split_text_lines(event_text, max_event_line_width, temp_draw,
                                              self.font_small, max_lines=2)
        event_lines_w = max(self._get_text_width(temp_draw, line, self.font_small)
                           for line in event_lines)
        left_block_w = max(sport_w, event_lines_w)

        # Right block: flag + country + athlete + medal label
        max_medal_w = 0
        for label, athlete, country, _ in medalists:
            label_w = self._get_text_width(temp_draw, label, self.font_small)
            athlete_w = self._get_text_width(temp_draw, athlete, self.font_small)
            country_w = self._get_text_width(temp_draw, country, self.font_small)
            # Layout: flag + country + athlete + label
            row_w = flag_size[0] + 4 + country_w + 4 + athlete_w + 4 + label_w
            max_medal_w = max(max_medal_w, row_w)

        if card_width is None:
            # Total: left block + gap + right block
            width = left_block_w + 12 + max_medal_w + margin * 2
            width = max(width, 100)
        else:
            width = card_width

        img = Image.new('RGB', (width, height), BLACK)
        draw = ImageDraw.Draw(img)
        draw.fontmode = "1"  # Pixel fonts on an LED panel: 1-bit text so every lit pixel is fully lit (no AA fringe).

        # Recalculate event lines with actual draw context
        event_lines = self._split_text_lines(event_text, max_event_line_width, draw,
                                              self.font_small, max_lines=2)

        # LEFT BLOCK: Sport on top, Event name lines below
        line_height = 8 if height <= 32 else 10
        num_rows = 1 + len(event_lines)  # Sport + event lines
        total_left_height = num_rows * line_height
        left_start_y = (height - total_left_height) // 2

        y = left_start_y
        draw.text((margin, y), sport_text, font=self.font_small, fill=CYAN)
        y += line_height

        for line in event_lines:
            draw.text((margin, y), line, font=self.font_small, fill=WHITE)
            y += line_height

        # RIGHT BLOCK: Medals stacked vertically with larger flags
        # Calculate where right block starts
        right_block_x = margin + left_block_w + 12

        # Distribute 3 medal rows across full height
        row_height = height // 3
        for i, (label, athlete, country, color) in enumerate(medalists):
            # Center the content vertically within the row
            y = i * row_height + (row_height - flag_size[1]) // 2
            x = right_block_x

            # Flag first (large, prominent)
            flag = self._load_flag(country, flag_size)
            if flag:
                img.paste(flag, (x, y))
            x += flag_size[0] + 4

            # Country code
            draw.text((x, y + 1), country, font=self.font_small, fill=color)
            x += self._get_text_width(draw, country, self.font_small) + 4

            # Athlete name
            draw.text((x, y + 1), athlete, font=self.font_small, fill=WHITE)
            x += self._get_text_width(draw, athlete, self.font_small) + 4

            # Medal label (G/S/B) at end
            draw.text((x, y + 1), label, font=self.font_small, fill=color)

        return img

    def render_events_summary(self, events: List[OlympicEvent],
                              width: int, height: int,
                              title: str = "UPCOMING") -> Image.Image:
        """
        Render a summary of multiple events on one screen.

        Useful for regular switch mode display.

        Args:
            events: List of OlympicEvent objects
            width: Full display width
            height: Full display height
            title: Title text to show

        Returns:
            PIL Image with events summary
        """
        img = Image.new('RGB', (width, height), BLACK)
        draw = ImageDraw.Draw(img)
        draw.fontmode = "1"  # Pixel fonts on an LED panel: 1-bit text so every lit pixel is fully lit (no AA fringe).

        if not events:
            draw.text((4, height // 2 - 4), "No events", font=self.font_small, fill=GRAY)
            return img

        # Title
        draw.text((2, 1), title, font=self.font_small, fill=CYAN)

        # Show events
        max_events = 2 if height <= 32 else 4
        events_to_show = events[:max_events]

        available_height = height - 10
        row_height = available_height // len(events_to_show)
        start_y = 9

        for i, event in enumerate(events_to_show):
            y = start_y + (i * row_height)

            # Time (compact)
            time_str = self._format_event_time(event.start_time)
            time_width = self._get_text_width(draw, time_str[:8], self.font_small)
            draw.text((2, y), time_str[:8], font=self.font_small, fill=YELLOW)

            # Sport/Event (use remaining width)
            sport_x = 2 + time_width + 4
            sport_width = width - sport_x - 2
            event_text = self._truncate_to_width(draw, event.sport, sport_width, self.font_small)
            draw.text((sport_x, y), event_text, font=self.font_small, fill=WHITE)

        return img

    def render_results_summary(self, results: List[EventResult],
                               width: int, height: int) -> Image.Image:
        """
        Render a summary of recent results with flags.

        Args:
            results: List of EventResult objects
            width: Full display width
            height: Full display height

        Returns:
            PIL Image with results summary
        """
        img = Image.new('RGB', (width, height), BLACK)
        draw = ImageDraw.Draw(img)
        draw.fontmode = "1"  # Pixel fonts on an LED panel: 1-bit text so every lit pixel is fully lit (no AA fringe).

        if not results:
            draw.text((4, height // 2 - 4), "No results", font=self.font_small, fill=GRAY)
            return img

        # Title
        draw.text((2, 1), "RESULTS", font=self.font_small, fill=GREEN)

        # Show results
        max_results = 2 if height <= 32 else 3
        results_to_show = results[:max_results]

        available_height = height - 10
        row_height = available_height // len(results_to_show)
        start_y = 9
        flag_size = (10, 7)

        for i, result in enumerate(results_to_show):
            y = start_y + (i * row_height)

            # Calculate space needed for G/S/B with flags and country codes
            # Format: [flag]USA [flag]NOR [flag]GER with medal colors
            countries = [
                (result.gold_country, GOLD_COLOR),
                (result.silver_country, SILVER_COLOR),
                (result.bronze_country, BRONZE_COLOR),
            ]

            # Measure total width needed for flags + countries
            country_widths = []
            spacing = 3  # pixels between country groups
            total_country_width = 0
            for country, _ in countries:
                w = self._get_text_width(draw, country, self.font_small)
                country_widths.append(w)
                # Each group: flag_width + 1px gap + country_width
                total_country_width += flag_size[0] + 1 + w
            total_country_width += spacing * 2  # spacing between 3 groups

            # Event name (with abbreviation) - leave room for flags + countries
            event_width = width - total_country_width - 6
            event_text = self._truncate_to_width(draw, result.event_name, event_width, self.font_small)
            draw.text((2, y), event_text, font=self.font_small, fill=WHITE)

            # Draw flags + country codes with medal colors (right-aligned)
            x = width - total_country_width - 2
            for idx, (country, color) in enumerate(countries):
                # Flag
                flag = self._load_flag(country, flag_size)
                if flag:
                    img.paste(flag, (x, y))
                x += flag_size[0] + 1

                # Country code
                draw.text((x, y), country, font=self.font_small, fill=color)
                x += country_widths[idx] + spacing

        return img
