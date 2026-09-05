"""
Medal count card renderer for Olympics plugin.

Renders medal count cards for display in both Vegas scroll mode
and regular switch mode.
"""

import logging
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

try:
    from data.data_models import MedalCount
except ImportError:
    from ..data.data_models import MedalCount

logger = logging.getLogger(__name__)

# Medal colors (RGB)
GOLD_COLOR = (255, 215, 0)
SILVER_COLOR = (192, 192, 192)
BRONZE_COLOR = (205, 127, 50)
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
GRAY = (128, 128, 128)


class MedalCardRenderer:
    """
    Renders medal count cards for individual countries.

    Creates PIL Images suitable for Vegas scroll mode or
    standard display mode.
    """

    def __init__(self, display_height: int, config: Dict[str, Any],
                 fonts: Optional[Dict[str, Any]] = None):
        """
        Initialize the medal card renderer.

        Args:
            display_height: Height of display in pixels
            config: Plugin configuration
            fonts: Optional dict of fonts to use
        """
        self.display_height = display_height
        self.config = config
        self.fonts = fonts or {}
        self.flag_cache: Dict[str, Image.Image] = {}

        # Calculate card dimensions based on display height
        # Standard card width that looks good at various heights
        if display_height <= 32:
            self.card_width = 64
            self.font_size_large = 8
            self.font_size_small = 6
        elif display_height <= 64:
            self.card_width = 80
            self.font_size_large = 10
            self.font_size_small = 8
        else:
            self.card_width = 96
            self.font_size_large = 12
            self.font_size_small = 10

        # Load or create fonts
        self._init_fonts()

    def _init_fonts(self) -> None:
        """Initialize fonts for rendering."""
        try:
            # Try to use provided fonts from display_manager
            if 'regular' in self.fonts:
                self.font_large = self.fonts['regular']
            else:
                self.font_large = ImageFont.load_default()

            if 'small' in self.fonts:
                self.font_small = self.fonts['small']
            else:
                self.font_small = self.font_large

        except Exception as e:
            logger.warning(f"Error loading fonts: {e}, using defaults")
            self.font_large = ImageFont.load_default()
            self.font_small = self.font_large

    def _load_flag(self, country_code: str, size: Tuple[int, int]) -> Optional[Image.Image]:
        """
        Load and cache a country flag image.

        Args:
            country_code: ISO 3166-1 alpha-3 country code
            size: Target size (width, height)

        Returns:
            PIL Image of flag or None if not found
        """
        cache_key = f"{country_code}_{size[0]}x{size[1]}"
        if cache_key in self.flag_cache:
            return self.flag_cache[cache_key]

        # Try to load from assets directory
        flag_paths = [
            Path(__file__).parent.parent / 'assets' / 'country_flags' / f"{country_code.lower()}.png",
            Path(__file__).parent.parent / 'assets' / 'country_flags' / f"{country_code.upper()}.png",
        ]

        for flag_path in flag_paths:
            if flag_path.exists():
                try:
                    with Image.open(flag_path) as img:
                        flag = img.resize(size, Image.Resampling.NEAREST)
                        flag.load()  # Force read all pixel data into memory
                    self.flag_cache[cache_key] = flag
                    return flag
                except Exception as e:
                    logger.debug(f"Error loading flag {flag_path}: {e}")

        return None

    def _ordinal(self, n: int) -> str:
        """Convert number to ordinal (1st, 2nd, 3rd, etc.)."""
        if 11 <= (n % 100) <= 13:
            suffix = 'th'
        else:
            suffix = ['th', 'st', 'nd', 'rd', 'th'][min(n % 10, 4)]
        return f"{n}{suffix}"

    def render_medal_card(self, medal: MedalCount,
                          card_width: Optional[int] = None) -> Image.Image:
        """
        Render a single country's medal count as a leaderboard-style card.

        Layout (scrolls horizontally):
        +----------------------------------------+
        |              [      ]  NOR             |
        | 1st          [ FLAG ]  3  1  2         |
        |              [      ]                  |
        +----------------------------------------+

        Args:
            medal: MedalCount object with country data
            card_width: Optional override for card width (None = auto-size)

        Returns:
            PIL Image of the medal card
        """
        height = self.display_height
        margin = 2

        # Full-height flag (only 2px margin total - 1px top, 1px bottom)
        flag_height = height - 2
        flag_width = int(flag_height * 1.5)  # Standard flag aspect ratio
        flag_size = (flag_width, flag_height)

        # Prepare text content
        rank_text = self._ordinal(medal.rank)
        country_text = medal.country_code
        gold_text = str(medal.gold)
        silver_text = str(medal.silver)
        bronze_text = str(medal.bronze)

        # Calculate width based on content if not specified (for Vegas scroll)
        if card_width is None:
            temp_img = Image.new('RGB', (1, 1), BLACK)
            temp_draw = ImageDraw.Draw(temp_img)

            rank_w = self._get_text_width(temp_draw, rank_text, self.font_large)
            country_w = self._get_text_width(temp_draw, country_text, self.font_large)
            gold_w = self._get_text_width(temp_draw, gold_text, self.font_large)
            silver_w = self._get_text_width(temp_draw, silver_text, self.font_large)
            bronze_w = self._get_text_width(temp_draw, bronze_text, self.font_large)

            # Layout: rank | flag | country + medal counts stacked
            medal_counts_w = gold_w + 6 + silver_w + 6 + bronze_w
            content_width = rank_w + 8 + flag_size[0] + 8 + max(country_w, medal_counts_w)
            width = content_width + margin * 2 + 4
            width = max(width, 100)
        else:
            width = card_width

        img = Image.new('RGB', (width, height), BLACK)
        draw = ImageDraw.Draw(img)
        draw.fontmode = "1"  # Pixel fonts on an LED panel: 1-bit text so every lit pixel is fully lit (no AA fringe).

        # Get actual text height for proper centering
        try:
            bbox = draw.textbbox((0, 0), "Ay", font=self.font_large)
            text_height = bbox[3] - bbox[1]
        except AttributeError:
            text_height = 10  # Fallback

        # Layout: Rank | Full-height Flag | Country + Medals (vertically centered)
        rank_w = self._get_text_width(draw, rank_text, self.font_large)

        # Rank on left, vertically centered
        rank_y = (height - text_height) // 2
        draw.text((margin, rank_y), rank_text, font=self.font_large, fill=WHITE)

        # Full-height flag, centered vertically (should be nearly edge-to-edge)
        flag_x = margin + rank_w + 8
        flag_y = 1  # Just 1px from top
        flag = self._load_flag(medal.country_code, flag_size)
        if flag:
            img.paste(flag, (flag_x, flag_y))

        # Right side: Country code and medal counts vertically centered as two lines
        right_x = flag_x + flag_size[0] + 8

        # Calculate vertical centering for two lines of text
        # Use actual text height plus spacing
        line_spacing = 4  # Gap between lines
        total_text_height = text_height * 2 + line_spacing
        start_y = (height - total_text_height) // 2

        # Country code on first line
        draw.text((right_x, start_y), country_text, font=self.font_large, fill=WHITE)

        # Medal counts on second line
        medal_y = start_y + text_height + line_spacing
        x = right_x

        # Gold count in gold color
        draw.text((x, medal_y), gold_text, font=self.font_large, fill=GOLD_COLOR)
        x += self._get_text_width(draw, gold_text, self.font_large) + 6

        # Silver count in silver color
        draw.text((x, medal_y), silver_text, font=self.font_large, fill=SILVER_COLOR)
        x += self._get_text_width(draw, silver_text, self.font_large) + 6

        # Bronze count in bronze color
        draw.text((x, medal_y), bronze_text, font=self.font_large, fill=BRONZE_COLOR)

        return img

    def render_medal_card_compact(self, medal: MedalCount) -> Image.Image:
        """
        Render a compact medal card for smaller displays.

        Layout:
        +----------------+
        | USA #1         |
        | 5-3-2 (10)     |
        +----------------+

        Args:
            medal: MedalCount object

        Returns:
            PIL Image of compact medal card
        """
        width = self.card_width
        height = self.display_height

        img = Image.new('RGB', (width, height), BLACK)
        draw = ImageDraw.Draw(img)
        draw.fontmode = "1"  # Pixel fonts on an LED panel: 1-bit text so every lit pixel is fully lit (no AA fringe).

        margin = 2

        # Row 1: Country + Rank
        y1 = margin
        text1 = f"{medal.country_code} #{medal.rank}"
        draw.text((margin, y1), text1, font=self.font_large, fill=WHITE)

        # Row 2: Medal counts in G-S-B (Total) format
        y2 = height // 2 + 1
        total_text = f"({medal.total})"

        # Draw medal counts with colors
        x = margin
        # Gold count
        gold_str = str(medal.gold)
        draw.text((x, y2), gold_str, font=self.font_small, fill=GOLD_COLOR)
        x += self._get_text_width(draw, gold_str, self.font_small)
        draw.text((x, y2), "-", font=self.font_small, fill=GRAY)
        x += self._get_text_width(draw, "-", self.font_small)

        # Silver count
        silver_str = str(medal.silver)
        draw.text((x, y2), silver_str, font=self.font_small, fill=SILVER_COLOR)
        x += self._get_text_width(draw, silver_str, self.font_small)
        draw.text((x, y2), "-", font=self.font_small, fill=GRAY)
        x += self._get_text_width(draw, "-", self.font_small)

        # Bronze count
        bronze_str = str(medal.bronze)
        draw.text((x, y2), bronze_str, font=self.font_small, fill=BRONZE_COLOR)
        x += self._get_text_width(draw, bronze_str, self.font_small) + 2

        # Total
        draw.text((x, y2), total_text, font=self.font_small, fill=GRAY)

        return img

    def render_top_countries(self, medals: List[MedalCount],
                             top_n: int = 5) -> List[Image.Image]:
        """
        Render cards for top N countries by medal count.

        Args:
            medals: List of MedalCount objects (should be pre-sorted)
            top_n: Number of countries to render

        Returns:
            List of PIL Images for each country
        """
        return [self.render_medal_card(m) for m in medals[:top_n]]

    def render_medal_summary(self, medals: List[MedalCount],
                             width: int, height: int) -> Image.Image:
        """
        Render a summary view showing multiple countries on one screen.

        Useful for regular switch mode display.

        Args:
            medals: List of top medal countries
            width: Full display width
            height: Full display height

        Returns:
            PIL Image with medal summary
        """
        img = Image.new('RGB', (width, height), BLACK)
        draw = ImageDraw.Draw(img)
        draw.fontmode = "1"  # Pixel fonts on an LED panel: 1-bit text so every lit pixel is fully lit (no AA fringe).

        if not medals:
            draw.text((4, height // 2 - 4), "No medal data", font=self.font_small, fill=GRAY)
            return img

        # Title
        title_y = 1
        draw.text((2, title_y), "MEDAL COUNT", font=self.font_small, fill=WHITE)

        # Show top 3-5 countries depending on height
        max_countries = 3 if height <= 32 else 5
        countries = medals[:max_countries]

        # Calculate row height
        available_height = height - 10  # Minus title
        row_height = available_height // len(countries)
        start_y = 9

        for i, medal in enumerate(countries):
            y = start_y + (i * row_height)

            # Rank + Country
            rank_text = f"{medal.rank}."
            country_text = medal.country_code

            x = 2
            draw.text((x, y), rank_text, font=self.font_small, fill=GRAY)
            x += self._get_text_width(draw, rank_text, self.font_small) + 2
            draw.text((x, y), country_text, font=self.font_small, fill=WHITE)

            # Medal counts on right side
            medal_x = width - 40
            # Gold
            draw.text((medal_x, y), str(medal.gold), font=self.font_small, fill=GOLD_COLOR)
            medal_x += 12
            # Silver
            draw.text((medal_x, y), str(medal.silver), font=self.font_small, fill=SILVER_COLOR)
            medal_x += 12
            # Bronze
            draw.text((medal_x, y), str(medal.bronze), font=self.font_small, fill=BRONZE_COLOR)

        return img

    def render_medal_race(self, country1: MedalCount, country2: MedalCount,
                          width: int, height: int) -> Image.Image:
        """
        Render a head-to-head medal race comparison between two countries.

        Layout:
        +---------------------------+
        | MEDAL RACE                |
        | USA 5-3-2 vs CAN 4-4-3    |
        | Total: 10      Total: 11  |
        +---------------------------+

        Args:
            country1: First country's medal count
            country2: Second country's medal count
            width: Full display width
            height: Full display height

        Returns:
            PIL Image with medal race comparison
        """
        img = Image.new('RGB', (width, height), BLACK)
        draw = ImageDraw.Draw(img)
        draw.fontmode = "1"  # Pixel fonts on an LED panel: 1-bit text so every lit pixel is fully lit (no AA fringe).

        margin = 2

        # Title
        draw.text((margin, margin), "MEDAL RACE", font=self.font_small, fill=WHITE)

        # Row 2: Country codes and medal counts
        y2 = height // 3
        mid_x = width // 2

        # Country 1 (left side)
        c1_text = f"{country1.country_code} {country1.gold}-{country1.silver}-{country1.bronze}"
        draw.text((margin, y2), c1_text, font=self.font_small, fill=GOLD_COLOR)

        # VS
        draw.text((mid_x - 8, y2), "vs", font=self.font_small, fill=GRAY)

        # Country 2 (right side)
        c2_text = f"{country2.country_code} {country2.gold}-{country2.silver}-{country2.bronze}"
        draw.text((mid_x + 8, y2), c2_text, font=self.font_small, fill=GOLD_COLOR)

        # Row 3: Totals
        y3 = (height * 2) // 3
        t1_text = f"T:{country1.total}"
        t2_text = f"T:{country2.total}"

        draw.text((margin, y3), t1_text, font=self.font_small, fill=WHITE)
        draw.text((mid_x + 8, y3), t2_text, font=self.font_small, fill=WHITE)

        # Highlight winner
        if country1.total > country2.total:
            draw.text((margin + 30, y3), "+", font=self.font_small, fill=(0, 255, 0))
        elif country2.total > country1.total:
            draw.text((mid_x + 38, y3), "+", font=self.font_small, fill=(0, 255, 0))

        return img

    def _get_text_width(self, draw: ImageDraw.ImageDraw, text: str,
                        font: ImageFont.FreeTypeFont) -> int:
        """Get width of text with given font."""
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            return bbox[2] - bbox[0]
        except AttributeError:
            # Fallback for older PIL versions
            return len(text) * 6
