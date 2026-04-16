"""
Masters Tournament Renderer - Broadcast Quality

Pixel-perfect rendering for LED matrix displays with:
- BDF bitmap fonts for crisp text at all sizes
- Broadcast-style leaderboard with pagination
- Player cards with real ESPN headshots and country flags
- Accurate Augusta National hole cards
- Scrolling fun facts ticker
- Past champions with pagination
- Amen Corner spotlight
- Tournament countdown
- Schedule display with pagination
- Generous spacing for LED readability
"""

import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from masters_helpers import (
    AUGUSTA_HOLES,
    AUGUSTA_PAR,
    MULTIPLE_WINNERS,
    PAST_CHAMPIONS,
    TOURNAMENT_RECORDS,
    ascii_safe,
    format_player_name,
    format_score_to_par,
    get_fun_fact_by_index,
    get_hole_info,
    get_random_fun_fact,
    get_recent_champions,
    get_score_description,
)

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# MASTERS COLOR PALETTE - Authentic colors
# ═══════════════════════════════════════════════════════════════

COLORS = {
    "masters_green":    (0, 104, 56),
    "masters_dark":     (0, 75, 40),
    "masters_yellow":   (253, 218, 36),
    "augusta_green":    (34, 120, 34),
    "azalea_pink":      (255, 105, 180),
    "gold":             (255, 215, 0),
    "gold_dark":        (200, 170, 0),
    "white":            (255, 255, 255),
    "off_white":        (240, 240, 235),
    "yellow_bright":    (255, 255, 102),
    "red":              (220, 40, 40),
    "birdie_red":       (200, 0, 0),
    "bogey_blue":       (80, 120, 200),
    "under_par":        (100, 255, 100),
    "over_par":         (255, 130, 130),
    "even_par":         (200, 200, 200),
    "bg":               (0, 0, 0),
    "bg_dark_green":    (5, 20, 10),
    "row_alt":          (10, 35, 18),
    "header_bg":        (0, 80, 45),
    "shadow":           (0, 0, 0),
    "gray":             (120, 120, 120),
    "light_gray":       (180, 180, 180),
    "page_dot_on":      (253, 218, 36),
    "page_dot_off":     (60, 60, 60),
}


# ═══════════════════════════════════════════════════════════════
# FONT SYSTEM
# ═══════════════════════════════════════════════════════════════

FONT_SEARCH_DIRS = [
    "assets/fonts",
    "../../../assets/fonts",
    "../../assets/fonts",
    str(Path(__file__).parent.parent.parent / "assets" / "fonts"),
    str(Path.home() / "Github" / "LEDMatrix" / "assets" / "fonts"),
]

FONT_SPECS = {
    "tiny":     ("4x6-font.ttf", 6),
    "small":    ("4x6-font.ttf", 6),
    "medium":   ("PressStart2P-Regular.ttf", 8),
    "large":    ("PressStart2P-Regular.ttf", 8),
    "xl":       ("PressStart2P-Regular.ttf", 10),
    "5x7":      ("5by7.regular.ttf", 7),
}


def _find_font_path(filename: str) -> Optional[str]:
    for search_dir in FONT_SEARCH_DIRS:
        path = os.path.join(search_dir, filename)
        if os.path.exists(path):
            return path
    return None


def _load_font(name: str) -> ImageFont.ImageFont:
    if name not in FONT_SPECS:
        name = "small"
    filename, size = FONT_SPECS[name]
    path = _find_font_path(filename)
    if path:
        try:
            return ImageFont.truetype(path, size)
        except Exception as e:
            logger.warning(f"Failed to load font {path}: {e}")
    return ImageFont.load_default()


# Cache for _load_font_sized. Key: (filename, size). Value: font or None.
# Keeping None in the cache too so repeated failures don't re-hit the disk.
_FONT_SIZE_CACHE: Dict[Tuple[str, int], Optional[ImageFont.ImageFont]] = {}


def _load_font_sized(filename: str, size: int) -> Optional[ImageFont.ImageFont]:
    """Load a specific TTF at an arbitrary point size, with memoization.

    Callers like _fit_name() try ~11 (filename, size) combinations per player
    card render; without caching each call re-opens and re-parses the TTF.
    """
    cache_key = (filename, size)
    if cache_key in _FONT_SIZE_CACHE:
        return _FONT_SIZE_CACHE[cache_key]
    path = _find_font_path(filename)
    if not path:
        _FONT_SIZE_CACHE[cache_key] = None
        return None
    try:
        font = ImageFont.truetype(path, size)
    except Exception as e:
        logger.warning(f"Failed to load font {path}@{size}: {e}")
        _FONT_SIZE_CACHE[cache_key] = None
        return None
    _FONT_SIZE_CACHE[cache_key] = font
    return font


# Cache for _load_bdf_font. Key: filename. Value: font or None.
_BDF_FONT_CACHE: Dict[str, Optional[ImageFont.ImageFont]] = {}

# Persistent temp dir for converted BDF → PIL font files. BdfFontFile.save()
# writes a .pil header + .pbm bitmap pair that ImageFont.load() then reads,
# so those files need to exist on disk for the lifetime of the process.
_BDF_TEMP_DIR: Optional[str] = None


def _cleanup_bdf_temp() -> None:
    """Remove the BDF temp directory on process exit."""
    global _BDF_TEMP_DIR
    if _BDF_TEMP_DIR is None:
        return
    try:
        import shutil
        shutil.rmtree(_BDF_TEMP_DIR)
    except Exception as e:
        logger.debug("Failed to remove BDF temp dir %s: %s", _BDF_TEMP_DIR, e)
    finally:
        _BDF_TEMP_DIR = None
        _BDF_FONT_CACHE.clear()


import atexit
atexit.register(_cleanup_bdf_temp)


def _load_bdf_font(filename: str) -> Optional[ImageFont.ImageFont]:
    """Load a BDF bitmap font and return it as an ImageFont.

    PIL's ImageFont.truetype() anti-aliases TTF bitmap fonts, which ruins
    the crispness of pixel fonts like 5by7.regular.ttf at small sizes.
    BDF files are true fixed-size bitmap fonts — loading them via
    PIL.BdfFontFile gives pixel-perfect rendering with no sub-pixel
    smoothing. Converts once per process and caches the result.
    """
    if filename in _BDF_FONT_CACHE:
        return _BDF_FONT_CACHE[filename]

    bdf_path = _find_font_path(filename)
    if not bdf_path:
        _BDF_FONT_CACHE[filename] = None
        return None

    global _BDF_TEMP_DIR
    if _BDF_TEMP_DIR is None:
        _BDF_TEMP_DIR = tempfile.mkdtemp(prefix="masters_bdf_")

    try:
        from PIL import BdfFontFile  # local import — only needed here
        base = os.path.join(_BDF_TEMP_DIR, os.path.splitext(filename)[0])
        if not os.path.exists(base + ".pil"):
            with open(bdf_path, "rb") as f:
                BdfFontFile.BdfFontFile(f).save(base)
        font = ImageFont.load(base + ".pil")
    except Exception as e:
        logger.warning(f"Failed to load BDF font {bdf_path}: {e}")
        font = None

    _BDF_FONT_CACHE[filename] = font
    return font


class MastersRenderer:
    """Broadcast-quality Masters Tournament renderer with pagination & scrolling."""

    def __init__(
        self,
        display_width: int,
        display_height: int,
        config: Dict[str, Any],
        logo_loader,
        logger_inst=None,
    ):
        self.width = display_width
        self.height = display_height
        self.config = config
        self.logo_loader = logo_loader
        self.logger = logger_inst or logger

        self.plugin_dir = Path(__file__).parent
        self.flags_dir = self.plugin_dir / "assets" / "masters" / "flags"

        if self.width <= 32:
            self.tier = "tiny"
        elif self.width <= 64:
            self.tier = "small"
        else:
            self.tier = "large"

        # Wide-short panels (e.g. 192x48) have lots of horizontal room but
        # too little vertical room for the default "large" 128x64 layouts.
        # Track aspect so render methods can opt into horizontal variants.
        self.aspect = self.width / max(1, self.height)
        self.is_wide_short = self.tier == "large" and self.aspect >= 2.5

        self._configure_tier()
        self._load_fonts()

        self._flag_cache: Dict[str, Optional[Image.Image]] = {}

    def _configure_tier(self):
        """Configure display parameters by size tier with generous spacing.

        max_players is computed from the actual pixel budget (not hardcoded)
        so wide-short panels like 192x48 don't overflow the canvas.
        """
        if self.tier == "tiny":  # 32x16
            self.name_len = 8
            self.row_height = 7
            self.header_height = 7
            self.logo_size = 0
            self.show_pos_badge = False
            self.show_thru = False
            self.show_country = False
            self.show_headshot = False
            self.headshot_size = 0
            self.row_gap = 0
            self.footer_height = 0
            self.flag_size = (0, 0)
        elif self.tier == "small":  # 64x32
            self.name_len = 10
            self.row_height = 7
            self.header_height = 8
            self.logo_size = 10
            self.show_pos_badge = True
            self.show_thru = True
            self.show_country = False
            self.show_headshot = False
            self.headshot_size = 0
            self.row_gap = 1
            self.footer_height = 5
            self.flag_size = (10, 7)
        else:  # large (>64 wide)
            # Horizontal budget — wide-short panels can show a longer name
            # but less headshot detail.
            self.name_len = 14 if not self.is_wide_short else 16
            self.row_height = 9
            self.header_height = 11
            self.logo_size = 18
            self.show_pos_badge = True
            self.show_thru = True
            self.show_country = True
            self.show_headshot = True
            # Headshot fills available vertical space minus padding + border
            # + space for the name badge (~14px). On 128x64 this is ~28px;
            # on 192x48 it shrinks to ~20px.
            self.headshot_size = max(16, min(self.height - 20, 32))
            self.row_gap = 1
            self.footer_height = 6
            # Bigger flags on large tier — scale roughly to row height.
            # 14x10 on 64-tall, 12x9 on 48-tall.
            flag_h = max(8, min(self.row_height + 1, 10))
            self.flag_size = (int(flag_h * 1.4), flag_h)

        # Wide-short panels with very limited height (128x32, 256x32) need
        # compact vertical sizing — the large-tier defaults consume too much
        # of the 32px budget (header 11 + footer 6 + row 9 = 26 of 32).
        if self.is_wide_short and self.height <= 32:
            self.row_height = 7
            self.header_height = 8
            self.footer_height = 5
            self.show_headshot = False
            self.headshot_size = 0
            self.show_country = False
            flag_h = max(6, min(self.row_height, 7))
            self.flag_size = (int(flag_h * 1.4), flag_h)

        # Compute max_players from actual available vertical space.
        available_h = self.height - self.header_height - self.footer_height - 2
        slot_h = self.row_height + self.row_gap
        self.max_players = max(1, available_h // slot_h)

    def _load_fonts(self):
        if self.tier == "tiny":
            self.font_header = _load_font("tiny")
            self.font_body = _load_font("tiny")
            self.font_score = _load_font("tiny")
            self.font_detail = _load_font("tiny")
        elif self.tier == "small":
            self.font_header = _load_font("small")
            self.font_body = _load_font("small")
            self.font_score = _load_font("small")
            self.font_detail = _load_font("tiny")
        else:
            self.font_header = _load_font("medium")
            self.font_body = _load_font("small")
            self.font_score = _load_font("medium")
            self.font_detail = _load_font("small")

        # Wide-short 32px: PressStart2P at 8px is too tall for 8px header
        if self.is_wide_short and self.height <= 32:
            self.font_header = _load_font("small")
            self.font_score = _load_font("small")

    # ═══════════════════════════════════════════════════════════
    # DRAWING HELPERS
    # ═══════════════════════════════════════════════════════════

    def _text_shadow(self, draw, pos, text, font, fill, offset=(1, 1)):
        x, y = pos
        draw.text((x + offset[0], y + offset[1]), text, font=font, fill=COLORS["shadow"])
        draw.text((x, y), text, font=font, fill=fill)

    def _text_width(self, draw, text, font) -> int:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0]

    def _text_height(self, draw, text, font) -> int:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[3] - bbox[1]

    def _draw_gradient_bg(self, c1, c2, vertical=True,
                          width: Optional[int] = None,
                          height: Optional[int] = None) -> Image.Image:
        w = width if width is not None else self.width
        h = height if height is not None else self.height
        img = Image.new("RGB", (w, h))
        draw = ImageDraw.Draw(img)
        steps = h if vertical else w
        for i in range(steps):
            ratio = i / max(steps - 1, 1)
            r = int(c1[0] + (c2[0] - c1[0]) * ratio)
            g = int(c1[1] + (c2[1] - c1[1]) * ratio)
            b = int(c1[2] + (c2[2] - c1[2]) * ratio)
            if vertical:
                draw.line([(0, i), (w, i)], fill=(r, g, b))
            else:
                draw.line([(i, 0), (i, h)], fill=(r, g, b))
        return img

    def _draw_header_bar(self, img, draw, title, show_logo=True):
        h = self.header_height
        draw.rectangle([(0, 0), (self.width - 1, h - 1)], fill=COLORS["masters_green"])
        draw.line([(0, h - 1), (self.width, h - 1)], fill=COLORS["masters_yellow"])

        x_text = 2
        if show_logo and self.logo_size > 0:
            logo_img = self.logo_loader.get_masters_logo(
                max_width=self.logo_size, max_height=h - 2
            )
            if logo_img:
                img.paste(logo_img, (1, 1), logo_img if logo_img.mode == "RGBA" else None)
                x_text = self.logo_size + 3

        self._text_shadow(draw, (x_text, 1), title, self.font_header, COLORS["white"])

    def _draw_page_dots(self, draw, current_page: int, total_pages: int):
        """Draw pagination dots at bottom of display."""
        if total_pages <= 1 or self.footer_height == 0:
            return

        dot_r = 1 if self.tier == "small" else 2
        dot_spacing = dot_r * 4
        total_w = total_pages * dot_spacing
        start_x = (self.width - total_w) // 2
        dot_y = self.height - self.footer_height // 2

        for i in range(total_pages):
            x = start_x + i * dot_spacing + dot_r
            color = COLORS["page_dot_on"] if i == current_page else COLORS["page_dot_off"]
            draw.ellipse([x - dot_r, dot_y - dot_r, x + dot_r, dot_y + dot_r], fill=color)

    def _get_flag(self, country_code: str) -> Optional[Image.Image]:
        if country_code in self._flag_cache:
            return self._flag_cache[country_code]
        flag_path = self.flags_dir / f"{country_code}.png"
        fw, fh = self.flag_size
        if fw == 0 or fh == 0 or not flag_path.exists():
            return None
        try:
            flag = Image.open(flag_path).convert("RGBA")
            flag.thumbnail((fw, fh), Image.Resampling.NEAREST)
            self._flag_cache[country_code] = flag
            return flag
        except Exception as e:
            self.logger.warning(
                f"Failed to load flag {country_code} from {flag_path}: {e}",
                exc_info=True,
            )
            # Cache the failure too so we don't re-hit the broken file on every render.
            self._flag_cache[country_code] = None
            return None

    def _score_color(self, score, position=None) -> Tuple[int, int, int]:
        if position == 1:
            return COLORS["masters_yellow"]
        if score < 0:
            return COLORS["under_par"]
        elif score > 0:
            return COLORS["over_par"]
        return COLORS["even_par"]

    # ═══════════════════════════════════════════════════════════
    # LEADERBOARD - Paginated
    # ═══════════════════════════════════════════════════════════

    def render_leaderboard(
        self, leaderboard_data: List[Dict], show_favorites: bool = True,
        page: int = 0,
    ) -> Optional[Image.Image]:
        """Render paginated broadcast-style leaderboard.

        Wide-short panels (aspect >= 2.5, e.g. 192x48) render a two-column
        layout so we can show 2*max_players entries per page instead of
        wasting the horizontal real estate.
        """
        if not leaderboard_data:
            return None

        two_column = self.is_wide_short
        per_page = self.max_players * (2 if two_column else 1)
        total_pages = max(1, (len(leaderboard_data) + per_page - 1) // per_page)
        page = page % total_pages

        img = self._draw_gradient_bg(COLORS["bg"], COLORS["bg_dark_green"])
        draw = ImageDraw.Draw(img)

        self._draw_header_bar(img, draw, "LEADERBOARD")

        start = page * per_page
        players = leaderboard_data[start : start + per_page]

        if two_column:
            col_w = self.width // 2
            # Faint divider between columns
            draw.line([(col_w, self.header_height + 2),
                       (col_w, self.height - self.footer_height - 2)],
                      fill=COLORS["masters_dark"])
            for i, player in enumerate(players):
                col = i // self.max_players
                row = i % self.max_players
                y = self.header_height + 2 + row * (self.row_height + self.row_gap)
                x0 = col * col_w
                x1 = x0 + col_w - 1
                if row % 2 == 0:
                    draw.rectangle([(x0, y), (x1, y + self.row_height - 1)],
                                   fill=COLORS["row_alt"])
                self._draw_leaderboard_row(
                    img, draw, player, y, row, show_favorites,
                    x0=x0 + 1, x1=x1 - 1,
                )
        else:
            y = self.header_height + 2
            for i, player in enumerate(players):
                if i % 2 == 0:
                    draw.rectangle([(0, y), (self.width - 1, y + self.row_height - 1)],
                                   fill=COLORS["row_alt"])
                self._draw_leaderboard_row(img, draw, player, y, i, show_favorites)
                y += self.row_height + self.row_gap

        self._draw_page_dots(draw, page, total_pages)
        return img

    def _draw_leaderboard_row(
        self, img, draw, player, y, index, show_favorites,
        x0: Optional[int] = None, x1: Optional[int] = None,
    ):
        """Draw a single leaderboard row within [x0, x1] horizontally.

        When x0/x1 are None, the row spans the full canvas width.
        """
        if x0 is None:
            x0 = 1
        if x1 is None:
            x1 = self.width - 2
        col_width = x1 - x0

        pos_text = str(player.get("position", ""))
        # Narrower columns need shorter names.
        name_budget = self.name_len if col_width >= self.width - 4 else max(6, self.name_len - 4)
        name = format_player_name(player.get("player", "?"), name_budget)
        score = player.get("score", 0)
        score_text = format_score_to_par(score)
        position = player.get("position", 99)
        is_leader = (isinstance(position, int) and position == 1) or pos_text == "1"

        # Vertically center text in row
        text_y = y + (self.row_height - self._text_height(draw, "A", self.font_body)) // 2
        x = x0

        # Position badge
        if self.show_pos_badge and self.tier != "tiny":
            badge_w = 10 if self.tier == "large" else 8
            badge_color = COLORS["masters_yellow"] if is_leader else COLORS["masters_dark"]
            text_color = COLORS["bg"] if is_leader else COLORS["white"]
            draw.rectangle([(x, y), (x + badge_w, y + self.row_height - 1)], fill=badge_color)
            tw = self._text_width(draw, pos_text, self.font_body)
            draw.text((x + (badge_w - tw) // 2 + 1, text_y),
                      pos_text, fill=text_color, font=self.font_body)
            x += badge_w + 3
        else:
            draw.text((x, text_y), pos_text, fill=COLORS["masters_yellow"], font=self.font_body)
            x += max(8, self._text_width(draw, "T99", self.font_body) + 2)

        # Country flag
        if self.show_country:
            country = player.get("country", "")
            flag = self._get_flag(country)
            if flag:
                flag_y = y + (self.row_height - flag.height) // 2
                img.paste(flag, (x, flag_y), flag)
                x += flag.width + 2

        # Right-aligned score (and optional thru)
        right_x = x1

        if self.show_thru and col_width >= 60:
            thru = str(player.get("thru", ""))
            if thru:
                thru_w = self._text_width(draw, thru, self.font_detail)
                draw.text((right_x - thru_w, text_y + 1), thru,
                          fill=COLORS["white"], font=self.font_detail)
                right_x -= thru_w + 4

        score_w = self._text_width(draw, score_text, self.font_body)
        draw.text((right_x - score_w, text_y), score_text,
                  fill=self._score_color(score, position if isinstance(position, int) else 99),
                  font=self.font_body)

        # Player name — clip to whatever's left between x and (score start - pad)
        name_right = right_x - score_w - 3
        is_fav = show_favorites and self._is_favorite(player)
        if is_fav:
            name_color = COLORS["azalea_pink"]
        elif is_leader:
            name_color = COLORS["masters_yellow"]
        else:
            name_color = COLORS["white"]

        if x < name_right:
            # Clip the name text to fit the remaining width
            while name and self._text_width(draw, name, self.font_body) > name_right - x:
                name = name[:-1]
            draw.text((x, text_y), name, fill=name_color, font=self.font_body)

    # ═══════════════════════════════════════════════════════════
    # PLAYER CARD - Spacious layout
    # ═══════════════════════════════════════════════════════════

    def render_player_card(self, player: Dict,
                           card_width: Optional[int] = None,
                           card_height: Optional[int] = None) -> Optional[Image.Image]:
        """Render spacious player card with headshot and stats.

        When card_width/card_height are provided, the card is drawn at those
        dimensions instead of the full panel (self.width × self.height). Used
        by Vegas scroll mode where each player is a fixed-size block that
        scrolls across a long display, not a full-screen card.
        """
        if not player:
            return None

        w = card_width if card_width is not None else self.width
        h = card_height if card_height is not None else self.height
        # Recompute wide-short per-card so a 128x64 block on a 320x64 panel
        # gets the standard vertical-stack layout (aspect 2.0, not wide-short)
        # while the same panel's full-screen modes still use the two-column
        # wide-short layout.
        aspect = w / max(1, h)
        card_is_wide_short = (self.tier == "large") and aspect >= 2.5

        img = self._draw_gradient_bg(COLORS["masters_dark"], COLORS["masters_green"],
                                     width=w, height=h)
        draw = ImageDraw.Draw(img)

        # Gold border
        draw.rectangle([(0, 0), (w - 1, h - 1)],
                       outline=COLORS["masters_yellow"])

        raw_name = player.get("player", "Unknown")

        # Wide-short layout: maximize use of the canvas. Headshot fills the
        # full vertical minus padding; name/country/pos use fonts scaled to
        # height; big score block hugs the right edge. Works for 192x48,
        # 192x64, 256x64 and anything else aspect >= 2.5.
        if card_is_wide_short:
            return self._render_player_card_wide_short(img, draw, player, raw_name, w, h)

        x = 4
        y = 4

        # Headshot on left (sized to available vertical space)
        headshot_size = self.headshot_size
        if self.show_headshot:
            max_headshot = h - (2 * y) - 2
            headshot_size = min(headshot_size, max(16, max_headshot))
            headshot = self.logo_loader.get_player_headshot(
                player.get("player_id", ""),
                player.get("headshot_url"),
                max_size=headshot_size,
            )
            if headshot:
                draw.rectangle(
                    [x - 1, y - 1, x + headshot_size, y + headshot_size],
                    outline=COLORS["masters_yellow"],
                )
                img.paste(headshot, (x, y),
                          headshot if headshot.mode == "RGBA" else None)

        tx = x + headshot_size + 6 if self.show_headshot else x
        bottom_bound = h - 3

        if self.tier == "tiny":
            name = format_player_name(raw_name, 10)
        elif self.tier == "small":
            name = format_player_name(raw_name, 12)
        else:
            name = format_player_name(raw_name, 14)

        # Standard (tall) vertical-stack layout
        self._text_shadow(draw, (tx, y), name, self.font_header, COLORS["white"])
        y_text = y + self._text_height(draw, name, self.font_header) + 3

        # Country flag + code
        country = player.get("country", "")
        if country and self.tier != "tiny":
            flag = self._get_flag(country)
            fx = tx
            if flag:
                img.paste(flag, (fx, y_text), flag)
                fx += flag.width + 3
            draw.text((fx, y_text), country, fill=COLORS["light_gray"], font=self.font_detail)
            y_text += max(flag.height if flag else 0,
                          self._text_height(draw, country, self.font_detail)) + 2

        # Score - big and prominent with spacing
        score = player.get("score", 0)
        score_text = format_score_to_par(score)

        if self.tier == "large":
            if y_text + self._text_height(draw, score_text, self.font_score) <= bottom_bound:
                self._text_shadow(draw, (tx, y_text), score_text,
                                  self.font_score, self._score_color(score))
                y_text += self._text_height(draw, score_text, self.font_score) + 4
        else:
            draw.text((tx, y_text), score_text,
                      fill=self._score_color(score), font=self.font_body)
            y_text += 9

        # Position and thru - spread across with spacing
        pos = player.get("position", "")
        thru = player.get("thru", "")
        if pos and y_text + 9 <= bottom_bound:
            draw.text((tx, y_text), f"Pos: {pos}",
                      fill=COLORS["masters_yellow"], font=self.font_detail)
            if thru and self.tier != "tiny":
                pos_w = self._text_width(draw, f"Pos: {pos}", self.font_detail)
                draw.text((tx + pos_w + 8, y_text), f"Thru: {thru}",
                          fill=COLORS["white"], font=self.font_detail)
            y_text += 9

        # Green jacket count at bottom (only if there's still vertical room)
        jacket_count = MULTIPLE_WINNERS.get(ascii_safe(raw_name), 0)
        if jacket_count > 0 and self.tier != "tiny":
            jy = h - 10
            if jy > y_text + 2:
                jacket_icon = self.logo_loader.get_green_jacket_icon(size=8)
                jx = 4
                if jacket_icon:
                    img.paste(jacket_icon, (jx, jy),
                              jacket_icon if jacket_icon.mode == "RGBA" else None)
                    jx += 10
                draw.text((jx, jy), f"x{jacket_count} Green Jackets",
                          fill=COLORS["masters_yellow"], font=self.font_detail)

        return img

    def _fit_name(self, draw, raw_name: str, max_width: int,
                  max_height: int) -> Tuple[ImageFont.ImageFont, str, int]:
        """Pick the biggest font + display form where the full name fits.

        Tries PressStart2P (blockier, bigger) first at descending sizes, then
        the narrower 4x6-font, for each candidate display string:
            1. Full name               ("Scottie Scheffler")
            2. First initial + last    ("S. Scheffler")
            3. Last name only          ("Scheffler")
        Only falls back to mid-word truncation if literally nothing fits.
        Returns (font, display_string, rendered_height).

        Input is transliterated to ASCII so accented characters (Åberg,
        Højgaard, José María) don't render as missing-glyph boxes.
        """
        raw_name = ascii_safe(raw_name)
        parts = raw_name.split()
        full = raw_name.strip() or "?"
        last = parts[-1] if parts else full
        initial_last = f"{parts[0][0]}. {last}" if len(parts) > 1 else full
        candidates = [full, initial_last, last]

        # Try big fonts first, shrinking as needed. Cap each candidate font
        # at max_height so we don't overflow vertically.
        sizes_press = [16, 14, 12, 10, 8]
        sizes_4x6 = [14, 12, 10, 8, 7, 6]

        font_trials: List[Tuple[str, int]] = []
        for s in sizes_press:
            font_trials.append(("PressStart2P-Regular.ttf", s))
        for s in sizes_4x6:
            font_trials.append(("4x6-font.ttf", s))

        best_fallback = None
        for filename, size in font_trials:
            font = _load_font_sized(filename, size)
            if font is None:
                continue
            line_h = self._text_height(draw, "A", font)
            if line_h > max_height:
                continue
            for candidate in candidates:
                if self._text_width(draw, candidate, font) <= max_width:
                    return font, candidate, line_h
            # Remember the biggest font where even the last-name form was
            # the only option we could still truncate from.
            if best_fallback is None:
                best_fallback = (font, last, line_h)

        # Nothing fits cleanly — truncate the last name in the smallest
        # surviving font (or 4x6 size 6 as an ultimate fallback).
        if best_fallback is None:
            font = _load_font_sized("4x6-font.ttf", 6) or self.font_detail
            return font, last, self._text_height(draw, "A", font)

        font, text, h = best_fallback
        while text and self._text_width(draw, text, font) > max_width:
            text = text[:-1]
        return font, text, h

    def _render_player_card_wide_short(self, img, draw, player, raw_name,
                                       w: Optional[int] = None,
                                       h: Optional[int] = None):
        """Maximize canvas usage for wide-short player cards.

        Sizes scale from actual width/height (defaults to self.width/height
        but accepts overrides so Vegas scroll mode can pass a smaller card
        size). A full body that only references the locals w/h keeps this
        safe for per-call dimensions.
        """
        if w is None:
            w = self.width
        if h is None:
            h = self.height

        padding = max(3, h // 16)
        bottom_bound = h - padding

        # Headshot — fill the vertical budget, but also cap horizontally so
        # narrow wide-short panels (e.g. 128x48) leave enough room for the
        # name + score columns. The /4 cap ties the headshot to available
        # width, so on 128x48 it shrinks to 32px while 192x48 keeps 42px.
        headshot_size = max(16, min(h - 2 * padding, w // 4))
        hx = padding
        hy = padding
        if self.show_headshot:
            headshot = self.logo_loader.get_player_headshot(
                player.get("player_id", ""),
                player.get("headshot_url"),
                max_size=headshot_size,
            )
            if headshot:
                # Center the actual image in the reserved slot in case the
                # loader returned something smaller than max_size.
                hpx = hx + (headshot_size - headshot.width) // 2
                hpy = hy + (headshot_size - headshot.height) // 2
                draw.rectangle(
                    [hx - 1, hy - 1, hx + headshot_size, hy + headshot_size],
                    outline=COLORS["masters_yellow"],
                )
                img.paste(headshot, (hpx, hpy),
                          headshot if headshot.mode == "RGBA" else None)

        # Proportional font sizes. Score scales with BOTH height and width so
        # narrow wide-short displays (e.g. 128x48) don't let the score eat
        # the entire text column.
        score_px = max(10, min(24, int(h // 2.4), w // 8))
        detail_px = max(6, min(10, h // 7))

        score_font = _load_font_sized("PressStart2P-Regular.ttf", score_px) or self.font_score
        detail_font = _load_font_sized("4x6-font.ttf", detail_px) or self.font_detail

        # Reserve the right-hand score block width based on the actual score text.
        score = player.get("score", 0)
        score_text = format_score_to_par(score)
        score_w = self._text_width(draw, score_text, score_font)
        score_h = self._text_height(draw, score_text, score_font)
        score_block_w = score_w + padding * 2
        score_x = w - score_w - padding - 1
        score_y = (h - score_h) // 2
        self._text_shadow(draw, (score_x, score_y), score_text,
                          score_font, self._score_color(score))

        # Faint separator before the score column
        sep_x = w - score_block_w - 1
        draw.line([(sep_x, padding), (sep_x, bottom_bound)],
                  fill=COLORS["masters_dark"])

        # Text column between the headshot and the score separator
        tx = hx + headshot_size + padding + 3
        tx_right = sep_x - 3
        text_w = tx_right - tx

        # Name font: pick the biggest candidate where the full name fits.
        # PressStart2P is nearly monospace so it shows ~7 chars per 96px at
        # size 12; 4x6-font is much narrower. We try several sizes of each
        # and fall back to truncation only if nothing fits.
        name_font, name_display, name_h = self._fit_name(
            draw, raw_name, text_w, max_height=h // 3,
        )

        ty = padding
        self._text_shadow(draw, (tx, ty), name_display, name_font, COLORS["white"])
        ty += name_h + max(3, h // 16)

        # Country flag + code
        country = player.get("country", "")
        detail_h = self._text_height(draw, "A", detail_font)
        if country and ty + detail_h <= bottom_bound:
            flag = self._get_flag(country)
            fx = tx
            if flag:
                # Vertically center flag against the country label line
                flag_y = ty + max(0, (detail_h - flag.height) // 2)
                img.paste(flag, (fx, flag_y), flag)
                fx += flag.width + 3
            draw.text((fx, ty), country,
                      fill=COLORS["light_gray"], font=detail_font)
            row_h = max(flag.height if flag else 0, detail_h)
            ty += row_h + 2

        # Pos + Thru row — clip to text column so we don't bleed into score.
        pos = player.get("position", "")
        thru = player.get("thru", "")
        if pos and ty + detail_h <= bottom_bound:
            pos_text = f"POS {pos}"
            pos_w = self._text_width(draw, pos_text, detail_font)
            if tx + pos_w <= tx_right:
                draw.text((tx, ty), pos_text,
                          fill=COLORS["masters_yellow"], font=detail_font)
            if thru:
                thru_text = f"THRU {thru}"
                thru_x = tx + pos_w + 8
                if thru_x + self._text_width(draw, thru_text, detail_font) > tx_right:
                    # Try the shorter form on the next line instead of clobbering the score
                    thru_text = str(thru)
                    thru_x = tx + pos_w + 6
                if thru_x + self._text_width(draw, thru_text, detail_font) <= tx_right:
                    draw.text((thru_x, ty), thru_text,
                              fill=COLORS["white"], font=detail_font)
            ty += detail_h + 1

        # Green jacket strip along the bottom if there's room
        jacket_count = MULTIPLE_WINNERS.get(ascii_safe(raw_name), 0)
        if jacket_count > 0:
            jy = bottom_bound - detail_h
            if jy > ty + 1:
                jacket_icon = self.logo_loader.get_green_jacket_icon(
                    size=max(7, detail_h)
                )
                jx = tx
                if jacket_icon:
                    img.paste(jacket_icon, (jx, jy),
                              jacket_icon if jacket_icon.mode == "RGBA" else None)
                    jx += jacket_icon.width + 2
                jacket_text = f"x{jacket_count} GREEN JACKETS"
                # Shorter label if the long one won't fit
                if self._text_width(draw, jacket_text, detail_font) > tx_right - jx:
                    jacket_text = f"x{jacket_count}"
                draw.text((jx, jy), jacket_text,
                          fill=COLORS["masters_yellow"], font=detail_font)

        return img

    # ═══════════════════════════════════════════════════════════
    # HOLE CARD - Clean layout
    # ═══════════════════════════════════════════════════════════

    def render_hole_card(self, hole_number: int,
                         card_width: Optional[int] = None,
                         card_height: Optional[int] = None,
                         show_divider: bool = True) -> Optional[Image.Image]:
        cw = card_width if card_width is not None else self.width
        ch = card_height if card_height is not None else self.height
        hole_info = get_hole_info(hole_number)

        img = self._draw_gradient_bg((15, 80, 30), COLORS["augusta_green"],
                                     width=cw, height=ch)
        draw = ImageDraw.Draw(img)

        # Header
        header_h = self.header_height
        draw.rectangle([(0, 0), (cw - 1, header_h - 1)], fill=COLORS["masters_green"])
        draw.line([(0, header_h - 1), (cw, header_h - 1)], fill=COLORS["masters_yellow"])

        hole_text = f"HOLE {hole_number}"
        self._text_shadow(draw, (3, 1), hole_text, self.font_header, COLORS["white"])

        if self.tier != "tiny":
            name_text = hole_info["name"]
            name_w = self._text_width(draw, name_text, self.font_detail)
            draw.text((cw - name_w - 3, 2), name_text,
                      fill=COLORS["masters_yellow"], font=self.font_detail)

        # Hole layout image (clamp to min 1px for tiny displays)
        hole_img = self.logo_loader.get_hole_image(
            hole_number,
            max_width=max(1, cw - 8),
            max_height=max(1, ch - header_h - 14),
        )
        if hole_img:
            hx = (cw - hole_img.width) // 2
            hy = header_h + 2
            img.paste(hole_img, (hx, hy), hole_img if hole_img.mode == "RGBA" else None)

        # Footer
        footer_y = ch - 9
        draw.rectangle([(0, footer_y), (cw - 1, ch - 1)], fill=(0, 0, 0))
        info_text = f"Par {hole_info['par']}  {hole_info['yardage']}y"
        self._text_shadow(draw, (3, footer_y + 1), info_text,
                          self.font_detail, COLORS["white"])

        zone = hole_info.get("zone")
        if zone and self.tier != "tiny":
            badge_text = zone.upper()
            bw = self._text_width(draw, badge_text, self.font_detail) + 4
            draw.rectangle([(cw - bw - 2, footer_y),
                            (cw - 2, ch - 1)],
                           fill=COLORS["masters_dark"])
            draw.text((cw - bw, footer_y + 1), badge_text,
                      fill=COLORS["masters_yellow"], font=self.font_detail)

        return img

    # ═══════════════════════════════════════════════════════════
    # AMEN CORNER - Spacious
    # ═══════════════════════════════════════════════════════════

    def render_amen_corner(self, scoring_data: Optional[Dict] = None) -> Optional[Image.Image]:
        img = self._draw_gradient_bg((5, 50, 25), COLORS["augusta_green"])
        draw = ImageDraw.Draw(img)

        # Header
        h = self.header_height + 2
        draw.rectangle([(0, 0), (self.width - 1, h - 1)], fill=COLORS["masters_green"])
        draw.line([(0, 0), (self.width, 0)], fill=COLORS["masters_yellow"])
        draw.line([(0, h - 1), (self.width, h - 1)], fill=COLORS["masters_yellow"])

        title = "AMEN CORNER"
        tw = self._text_width(draw, title, self.font_header)
        self._text_shadow(draw, ((self.width - tw) // 2, 2), title,
                          self.font_header, COLORS["masters_yellow"])

        # Content area
        content_h = self.height - h - 4
        hole_h = content_h // 3  # Equal space for each hole

        y = h + 3
        for hole_num in [11, 12, 13]:
            info = AUGUSTA_HOLES[hole_num]
            text_y = y + (hole_h - self._text_height(draw, "A", self.font_body)) // 2

            if self.tier == "tiny":
                text = f"#{hole_num} P{info['par']} {info['yardage']}y"
                draw.text((2, text_y), text, fill=COLORS["white"], font=self.font_body)
            else:
                # Gold number circle
                cx, cy = 10, y + hole_h // 2
                r = 5
                draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=COLORS["masters_yellow"])
                num_text = str(hole_num)
                ntw = self._text_width(draw, num_text, self.font_detail)
                draw.text((cx - ntw // 2, cy - 3), num_text,
                          fill=COLORS["bg"], font=self.font_detail)

                # Name
                draw.text((20, text_y), info['name'],
                          fill=COLORS["white"], font=self.font_body)

                # Par and yardage right-aligned
                par_text = f"Par {info['par']}  {info['yardage']}y"
                ptw = self._text_width(draw, par_text, self.font_detail)
                draw.text((self.width - ptw - 4, text_y + 1), par_text,
                          fill=COLORS["light_gray"], font=self.font_detail)

            y += hole_h

        return img

    # ═══════════════════════════════════════════════════════════
    # PAST CHAMPIONS - Paginated
    # ═══════════════════════════════════════════════════════════

    def render_past_champions(self, page: int = 0) -> Optional[Image.Image]:
        img = self._draw_gradient_bg(COLORS["masters_dark"], COLORS["masters_green"])
        draw = ImageDraw.Draw(img)

        self._draw_header_bar(img, draw, "CHAMPIONS", show_logo=False)

        # Green jacket icon in header
        jacket = self.logo_loader.get_green_jacket_icon(size=self.header_height - 2)
        if jacket and self.tier != "tiny":
            jx = self.width - jacket.width - 2
            img.paste(jacket, (jx, 1), jacket if jacket.mode == "RGBA" else None)

        content_top = self.header_height + 2
        content_bottom = self.height - self.footer_height - 1
        usable_h = content_bottom - content_top

        row_h = self.row_height + self.row_gap + 1  # Extra spacing
        max_rows = max(1, usable_h // row_h)

        total_pages = max(1, (len(PAST_CHAMPIONS) + max_rows - 1) // max_rows)
        page = page % total_pages

        start = page * max_rows
        champs = PAST_CHAMPIONS[start : start + max_rows]

        y = content_top
        for i, (year, name, country, score) in enumerate(champs):
            if i % 2 == 0:
                draw.rectangle([(0, y), (self.width - 1, y + self.row_height - 1)],
                               fill=COLORS["row_alt"])

            text_y = y + (self.row_height - self._text_height(draw, "A", self.font_body)) // 2

            # Year in yellow
            draw.text((3, text_y), str(year),
                      fill=COLORS["masters_yellow"], font=self.font_body)

            # Name
            disp_name = format_player_name(name, self.name_len - 2)
            draw.text((26, text_y), disp_name, fill=COLORS["white"], font=self.font_body)

            # Score right-aligned
            score_text = format_score_to_par(score)
            sw = self._text_width(draw, score_text, self.font_body)
            draw.text((self.width - sw - 3, text_y), score_text,
                      fill=self._score_color(score), font=self.font_body)

            y += row_h

        self._draw_page_dots(draw, page, total_pages)
        return img

    # ═══════════════════════════════════════════════════════════
    # FUN FACTS - Scrolling text
    # ═══════════════════════════════════════════════════════════

    def _wrap_text(self, text: str, max_w: int,
                   font, draw) -> List[str]:
        """Word-wrap *text* to fit within *max_w* pixels using *font*.

        Words wider than *max_w* are broken at character boundaries.
        """
        words = text.split()
        lines: List[str] = []
        current_line = ""
        for word in words:
            # Break oversized words into chunks that fit.
            if self._text_width(draw, word, font) > max_w:
                if current_line:
                    lines.append(current_line)
                    current_line = ""
                for ch in word:
                    test = current_line + ch
                    if self._text_width(draw, test, font) <= max_w:
                        current_line = test
                    else:
                        if current_line:
                            lines.append(current_line)
                        current_line = ch
                continue
            test = f"{current_line} {word}".strip()
            if self._text_width(draw, test, font) <= max_w:
                current_line = test
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word
        if current_line:
            lines.append(current_line)
        return lines

    def get_fun_fact_line_count(self, fact_index: int,
                               card_width: Optional[int] = None,
                               card_height: Optional[int] = None) -> tuple:
        """Return (total_lines, visible_lines) for a fun fact at this display size."""
        cw = card_width if card_width is not None else self.width
        ch = card_height if card_height is not None else self.height

        fact = get_fun_fact_by_index(fact_index)
        tmp = Image.new("RGB", (1, 1))
        draw = ImageDraw.Draw(tmp)

        font = self.font_detail
        line_h = self._text_height(draw, "Ag", font) + 2
        content_top = self.header_height + 4

        lines = self._wrap_text(fact, cw - 10, font, draw)
        visible = max(1, (ch - content_top - 4) // line_h)
        return len(lines), visible

    def render_fun_fact(self, fact_index: int = -1, scroll_offset: int = 0,
                        card_width: Optional[int] = None,
                        card_height: Optional[int] = None) -> Optional[Image.Image]:
        """Render a fun fact with vertical scroll support for long text."""
        cw = card_width if card_width is not None else self.width
        ch = card_height if card_height is not None else self.height

        if fact_index < 0:
            fact = get_random_fun_fact()
        else:
            fact = get_fun_fact_by_index(fact_index)

        img = self._draw_gradient_bg(COLORS["bg"], COLORS["bg_dark_green"],
                                     width=cw, height=ch)
        draw = ImageDraw.Draw(img)

        # Header
        header_h = self.header_height
        draw.rectangle([(0, 0), (cw - 1, header_h - 1)], fill=COLORS["masters_green"])
        draw.line([(0, header_h - 1), (cw, header_h - 1)], fill=COLORS["masters_yellow"])

        title = "DID YOU KNOW?"
        self._text_shadow(draw, (3, 1), title, self.font_header, COLORS["masters_yellow"])

        # Word-wrap the fact text with generous padding
        content_top = header_h + 4
        font = self.font_detail
        line_h = self._text_height(draw, "Ag", font) + 2  # Extra line spacing
        max_w = cw - 10  # More horizontal padding

        lines = self._wrap_text(fact, max_w, font, draw)
        total_lines = len(lines)

        # Apply scroll offset (for long facts)
        visible_lines = max(1, (ch - content_top - 4) // line_h)
        if total_lines > visible_lines:
            start_line = scroll_offset % max(1, len(lines) - visible_lines + 1)
            lines = lines[start_line : start_line + visible_lines]

        # Draw lines centered with spacing
        y = content_top
        for line in lines:
            draw.text((5, y), line, fill=COLORS["white"], font=font)
            y += line_h

        # Scroll indicator if text is long
        if total_lines > visible_lines:
            # Small down arrow
            ax = cw - 6
            ay = ch - 6
            draw.polygon([(ax - 2, ay - 2), (ax + 2, ay - 2), (ax, ay + 1)],
                         fill=COLORS["masters_yellow"])

        return img

    def render_fun_fact_vegas(self, fact_index: int = -1,
                              card_height: int = 32) -> Optional[Image.Image]:
        """Render a fun fact as a single-line wide card for vegas horizontal scroll.

        The card is exactly as wide as needed to fit the full text on one
        line below the header, so the vegas scroller reveals it naturally.
        """
        ch = card_height

        if fact_index < 0:
            fact = get_random_fun_fact()
        else:
            fact = get_fun_fact_by_index(fact_index)

        font = self.font_detail
        # Measure the full single-line text width
        tmp = Image.new("RGB", (1, 1))
        tmp_draw = ImageDraw.Draw(tmp)
        title = "DID YOU KNOW?"
        title_w = self._text_width(tmp_draw, title, self.font_header) + 8
        text_w = self._text_width(tmp_draw, fact, font)
        text_h = self._text_height(tmp_draw, "Ag", font)

        # Card wide enough for header title or text, whichever is longer
        cw = max(title_w, text_w + 10)

        img = self._draw_gradient_bg(COLORS["bg"], COLORS["bg_dark_green"],
                                     width=cw, height=ch)
        draw = ImageDraw.Draw(img)

        # Header
        header_h = self.header_height
        draw.rectangle([(0, 0), (cw - 1, header_h - 1)], fill=COLORS["masters_green"])
        draw.line([(0, header_h - 1), (cw, header_h - 1)], fill=COLORS["masters_yellow"])
        self._text_shadow(draw, (3, 1), title, self.font_header, COLORS["masters_yellow"])

        # Single line of text, vertically centered in remaining space
        content_top = header_h + 1
        text_y = content_top + max(0, (ch - content_top - text_h) // 2)
        draw.text((5, text_y), fact, fill=COLORS["white"], font=font)

        return img

    # ═══════════════════════════════════════════════════════════
    # TOURNAMENT STATS - Paginated (2 pages)
    # ═══════════════════════════════════════════════════════════

    def render_tournament_stats(self, page: int = 0) -> Optional[Image.Image]:
        img = self._draw_gradient_bg(COLORS["bg"], COLORS["bg_dark_green"])
        draw = ImageDraw.Draw(img)

        self._draw_header_bar(img, draw, "RECORDS", show_logo=False)

        content_top = self.header_height + 3
        font = self.font_detail
        line_h = self._text_height(draw, "A", font) + 3  # Generous spacing

        all_records = [
            ("Lowest 72", f"{TOURNAMENT_RECORDS['lowest_72']['total']} - D. Johnson, 2020"),
            ("Low Round", "63 - Nick Price, 1986"),
            ("Most Wins", "6 - Jack Nicklaus"),
            ("Youngest W", "21 - Tiger Woods, 1997"),
            ("Oldest W", "46 - Jack Nicklaus, 1986"),
            ("Biggest W", "12 strokes - Tiger, '97"),
            ("First", "1934 - Horton Smith"),
        ]

        visible = max(1, (self.height - content_top - self.footer_height - 2) // line_h)
        total_pages = max(1, (len(all_records) + visible - 1) // visible)
        page = page % total_pages

        start = page * visible
        records = all_records[start : start + visible]

        y = content_top
        for label, value in records:
            # Label in yellow
            draw.text((3, y), label, fill=COLORS["masters_yellow"], font=font)
            y += line_h - 1

            # Value indented in white
            draw.text((6, y), value, fill=COLORS["white"], font=font)
            y += line_h + 1

        self._draw_page_dots(draw, page, total_pages)
        return img

    # ═══════════════════════════════════════════════════════════
    # SCHEDULE - Paginated
    # ═══════════════════════════════════════════════════════════

    def render_schedule(self, schedule_data: List[Dict], page: int = 0) -> Optional[Image.Image]:
        img = self._draw_gradient_bg(COLORS["bg"], COLORS["bg_dark_green"])
        draw = ImageDraw.Draw(img)

        self._draw_header_bar(img, draw, "TEE TIMES")

        if not schedule_data:
            y = self.header_height + 8
            draw.text((3, y), "No tee times", fill=COLORS["gray"], font=self.font_body)
            return img

        content_top = self.header_height + 2
        content_bottom = self.height - self.footer_height - 2
        avail_h = content_bottom - content_top

        two_column = self.is_wide_short
        cols = 2 if two_column else 1
        col_w = self.width // cols

        # Masters pairings are almost always threesomes; always build text
        # from the full list and let the width-clipping loop shorten it.
        name_budget = 10 if not two_column else 9

        if self.height >= 48:
            # ── Standard layout: time on one line, each player stacked below ──
            detail_h = self._text_height(draw, "Ag", self.font_detail) + 1
            # Time row + up to 3 player rows + gap
            player_rows = min(3, max(1, (avail_h - self.row_height - 1) // detail_h))
            entry_h = self.row_height + 1 + player_rows * detail_h + 2
            rows = max(1, avail_h // entry_h)
            per_page = rows * cols

            total_pages = max(1, (len(schedule_data) + per_page - 1) // per_page)
            page = page % total_pages
            entries = schedule_data[page * per_page : (page + 1) * per_page]

            if two_column:
                draw.line([(col_w, content_top), (col_w, content_bottom)],
                          fill=COLORS["masters_dark"])

            for i, entry in enumerate(entries):
                col = i // rows
                row = i % rows
                cx = col * col_w + 3
                cx_right = (col + 1) * col_w - 3
                y = content_top + row * entry_h

                time_text = entry.get("time", "")
                draw.text((cx, y), time_text,
                          fill=COLORS["masters_yellow"], font=self.font_body)
                y += self.row_height + 1

                players = entry.get("players", []) or []
                max_name_w = cx_right - cx - 3
                if len(players) <= player_rows:
                    # All players fit on their own line
                    for p in players:
                        name = format_player_name(p, name_budget)
                        while name and self._text_width(draw, name, self.font_detail) > max_name_w:
                            name = name[:-1]
                        draw.text((cx + 3, y), name,
                                  fill=COLORS["white"], font=self.font_detail)
                        y += detail_h
                else:
                    # More players than rows — show first (player_rows-1)
                    # individually, fold the rest into the last line.
                    solo = max(0, player_rows - 1)
                    for p in players[:solo]:
                        name = format_player_name(p, name_budget)
                        while name and self._text_width(draw, name, self.font_detail) > max_name_w:
                            name = name[:-1]
                        draw.text((cx + 3, y), name,
                                  fill=COLORS["white"], font=self.font_detail)
                        y += detail_h
                    # Last line: remaining players comma-separated
                    overflow = ", ".join(
                        format_player_name(p, name_budget) for p in players[solo:]
                    )
                    while overflow and self._text_width(draw, overflow, self.font_detail) > max_name_w:
                        overflow = overflow[:-1]
                    draw.text((cx + 3, y), overflow,
                              fill=COLORS["white"], font=self.font_detail)
                    y += detail_h
        else:
            # ── Compact layout (height < 48): tighter spacing ──
            # Time + comma-separated players on adjacent lines with minimal gap
            entry_h = self.row_height + self.row_gap + self.row_height
            rows = max(1, avail_h // entry_h)
            per_page = rows * cols

            total_pages = max(1, (len(schedule_data) + per_page - 1) // per_page)
            page = page % total_pages
            entries = schedule_data[page * per_page : (page + 1) * per_page]

            if two_column:
                draw.line([(col_w, content_top), (col_w, content_bottom)],
                          fill=COLORS["masters_dark"])

            for i, entry in enumerate(entries):
                col = i // rows
                row = i % rows
                cx = col * col_w + 3
                cx_right = (col + 1) * col_w - 3
                y = content_top + row * entry_h

                time_text = entry.get("time", "")
                draw.text((cx, y), time_text,
                          fill=COLORS["masters_yellow"], font=self.font_detail)
                y += self.row_height + self.row_gap

                players = entry.get("players", []) or []
                players_text = ", ".join(
                    format_player_name(p, name_budget) for p in players
                )
                while players_text and self._text_width(draw, players_text, self.font_detail) > (cx_right - cx - 3):
                    players_text = players_text[:-1]
                draw.text((cx + 3, y), players_text,
                          fill=COLORS["white"], font=self.font_detail)

        self._draw_page_dots(draw, page, total_pages)
        return img

    # ═══════════════════════════════════════════════════════════
    # COUNTDOWN - Centered and spacious
    # ═══════════════════════════════════════════════════════════

    def _draw_logo_with_glow(self, img, logo, lx, ly, glow_pad=2):
        """Paste a logo with a black glow outline for visibility."""
        if logo and logo.mode == "RGBA":
            alpha = logo.split()[3]
            shadow = Image.new("RGBA", logo.size, (0, 0, 0, 0))
            shadow.paste((0, 0, 0), mask=alpha)
            for ox in range(-glow_pad, glow_pad + 1):
                for oy in range(-glow_pad, glow_pad + 1):
                    if ox == 0 and oy == 0:
                        continue
                    img.paste(shadow, (lx + ox, ly + oy), shadow)
        if logo:
            img.paste(logo, (lx, ly), logo if logo.mode == "RGBA" else None)

    def render_countdown(self, days: int, hours: int, minutes: int) -> Optional[Image.Image]:
        img = self._draw_gradient_bg(COLORS["masters_dark"], COLORS["masters_green"])
        draw = ImageDraw.Draw(img)

        # Countdown text — show days + hours for context, hours:minutes when
        # under 1 day, minutes-only in the final hour, then "NOW".
        if days > 0:
            count_text = f"{days}d {hours}h"
            unit_text = "UNTIL THE MASTERS"
        elif hours > 0:
            count_text = f"{hours}:{minutes:02d}"
            unit_text = "HOURS TO GO"
        elif minutes > 0:
            count_text = f"{minutes}m"
            unit_text = "MINUTES TO GO"
        else:
            count_text = "NOW"
            unit_text = ""

        # Two-column layout only on large displays (width > 64)
        min_right_width = 40
        if self.tier == "large":
            logo = self.logo_loader.get_masters_logo(
                max_width=int(self.width * 0.45),
                max_height=self.height - 4,
            )
            if logo and (self.width - logo.width - 12) >= min_right_width:
                lx = 3
                ly = (self.height - logo.height) // 2
                self._draw_logo_with_glow(img, logo, lx, ly)
                right_x = lx + logo.width + 6
                right_w = self.width - right_x - 2
                right_cx = right_x + right_w // 2

                detail_h = self._text_height(draw, "A", self.font_detail)
                count_h = self._text_height(draw, count_text, self.font_score)
                # Big number on top, label underneath
                block_h = count_h + 3 + detail_h
                block_y = max(2, (self.height - block_h) // 2)

                cw = self._text_width(draw, count_text, self.font_score)
                self._text_shadow(draw, (right_cx - cw // 2, block_y),
                                  count_text, self.font_score, COLORS["masters_yellow"])

                label = unit_text
                lw = self._text_width(draw, label, self.font_detail)
                if lw > right_w:
                    label = "TO MASTERS"
                    lw = self._text_width(draw, label, self.font_detail)
                draw.text((right_cx - lw // 2, block_y + count_h + 3),
                          label, fill=COLORS["light_gray"], font=self.font_detail)
                return img

        # Compact layout: logo centered at top (larger), countdown below
        logo = self.logo_loader.get_masters_logo(
            max_width=min(self.width - 6, 56),
            max_height=min(int(self.height * 0.45), 28),
        )
        logo_bottom = 3
        if logo:
            lx = (self.width - logo.width) // 2
            self._draw_logo_with_glow(img, logo, lx, 2)
            logo_bottom = 2 + logo.height + 2

        # Position text below logo: label once, then big countdown
        remaining = self.height - logo_bottom
        detail_h = self._text_height(draw, "A", self.font_detail)
        count_h = self._text_height(draw, count_text, self.font_score)

        if self.tier == "tiny":
            label = "TO MASTERS"
        else:
            label = unit_text

        text_block_h = count_h + 2 + detail_h
        text_y = logo_bottom + max(0, (remaining - text_block_h) // 2)

        cw = self._text_width(draw, count_text, self.font_score)
        self._text_shadow(draw, ((self.width - cw) // 2, text_y),
                          count_text, self.font_score, COLORS["masters_yellow"])

        lw = self._text_width(draw, label, self.font_detail)
        draw.text(((self.width - lw) // 2, text_y + count_h + 2),
                  label, fill=COLORS["light_gray"], font=self.font_detail)

        return img

    # ═══════════════════════════════════════════════════════════
    # FIELD OVERVIEW - Spacious stats
    # ═══════════════════════════════════════════════════════════

    def render_field_overview(self, leaderboard_data: List[Dict]) -> Optional[Image.Image]:
        img = self._draw_gradient_bg(COLORS["bg"], COLORS["bg_dark_green"])
        draw = ImageDraw.Draw(img)

        self._draw_header_bar(img, draw, "THE FIELD")

        total = len(leaderboard_data)
        under = sum(1 for p in leaderboard_data if p.get("score", 0) < 0)
        over = sum(1 for p in leaderboard_data if p.get("score", 0) > 0)
        even = total - under - over

        line_h = 10 if self.tier == "large" else 8
        content_top = self.header_height + 3
        content_bottom = self.height - 2
        available = content_bottom - content_top

        leader_block_h = line_h * 2 + 6  # divider + "Leader" label + leader row

        # Wide-short layout: put par stats in two columns, leader on the right
        # column, so everything fits in a 48-tall canvas.
        if self.is_wide_short:
            col_w = self.width // 2
            # Tighter vertical rhythm for detail rows so all 4 stat rows fit.
            detail_h = self._text_height(draw, "A", self.font_detail)
            detail_step = detail_h + 1
            y_l = content_top
            draw.text((4, y_l), f"Players: {total}",
                      fill=COLORS["white"], font=self.font_body)
            y_l += self._text_height(draw, "A", self.font_body) + 2
            draw.text((4, y_l), f"Under: {under}",
                      fill=COLORS["under_par"], font=self.font_detail)
            y_l += detail_step
            draw.text((4, y_l), f"Even:  {even}",
                      fill=COLORS["even_par"], font=self.font_detail)
            y_l += detail_step
            if y_l + detail_h <= content_bottom:
                draw.text((4, y_l), f"Over:  {over}",
                          fill=COLORS["over_par"], font=self.font_detail)

            if leaderboard_data:
                draw.line([(col_w, content_top),
                           (col_w, content_bottom)],
                          fill=COLORS["masters_yellow"])
                y_r = content_top
                draw.text((col_w + 4, y_r), "LEADER",
                          fill=COLORS["masters_yellow"], font=self.font_detail)
                y_r += line_h + 1
                leader = leaderboard_data[0]
                leader_name = format_player_name(leader.get("player", ""), self.name_len)
                leader_score = format_score_to_par(leader.get("score", 0))
                self._text_shadow(draw, (col_w + 4, y_r), leader_name,
                                  self.font_body, COLORS["white"])
                y_r += line_h + 1
                draw.text((col_w + 4, y_r), leader_score,
                          fill=self._score_color(leader.get("score", 0)),
                          font=self.font_body)
            return img

        # Single-column layout — decide whether the leader block fits
        show_leader = leaderboard_data and (
            available >= line_h * 4 + 6 + leader_block_h
        )
        y = content_top

        draw.text((4, y), f"Players: {total}", fill=COLORS["white"], font=self.font_body)
        y += line_h + 2

        draw.text((4, y), f"Under par: {under}", fill=COLORS["under_par"], font=self.font_detail)
        y += line_h
        if y + self._text_height(draw, "A", self.font_detail) <= content_bottom:
            draw.text((4, y), f"Even par:  {even}", fill=COLORS["even_par"], font=self.font_detail)
            y += line_h
        if y + self._text_height(draw, "A", self.font_detail) <= content_bottom:
            draw.text((4, y), f"Over par:  {over}", fill=COLORS["over_par"], font=self.font_detail)
            y += line_h + 3

        if show_leader:
            draw.line([(3, y), (self.width - 3, y)], fill=COLORS["masters_yellow"])
            y += 4

            leader = leaderboard_data[0]
            leader_name = format_player_name(leader.get("player", ""), self.name_len)
            leader_score = format_score_to_par(leader.get("score", 0))

            draw.text((4, y), "Leader", fill=COLORS["masters_yellow"], font=self.font_detail)
            y += line_h

            self._text_shadow(draw, (4, y), f"{leader_name}  {leader_score}",
                              self.font_body, COLORS["white"])

        return img

    # ═══════════════════════════════════════════════════════════
    # UTILITIES
    # ═══════════════════════════════════════════════════════════

    def _is_favorite(self, player: Dict) -> bool:
        favorites = self.config.get("favorite_players", [])
        player_name = player.get("player", "")
        return any(fav.lower() in player_name.lower() for fav in favorites)

    def _format_score(self, score: int) -> str:
        return format_score_to_par(score)

    def _get_hole_info(self, hole_number: int) -> Dict[str, Any]:
        return get_hole_info(hole_number)
