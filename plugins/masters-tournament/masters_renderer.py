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
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from masters_helpers import (
    AUGUSTA_HOLES,
    AUGUSTA_PAR,
    MULTIPLE_WINNERS,
    PAST_CHAMPIONS,
    TOURNAMENT_RECORDS,
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

        self._configure_tier()
        self._load_fonts()

        self._flag_cache: Dict[str, Image.Image] = {}

    def _configure_tier(self):
        """Configure display parameters by size tier with generous spacing."""
        if self.tier == "tiny":  # 32x16
            self.max_players = 2
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
        elif self.tier == "small":  # 64x32
            self.max_players = 3       # Was 4 - breathe
            self.name_len = 10
            self.row_height = 7
            self.header_height = 8
            self.logo_size = 10
            self.show_pos_badge = True
            self.show_thru = True
            self.show_country = False
            self.show_headshot = False
            self.headshot_size = 0
            self.row_gap = 1           # 1px gap between rows
            self.footer_height = 5     # Page dots
        else:  # 128x64
            self.max_players = 5       # Was 7 - much more readable
            self.name_len = 14
            self.row_height = 9        # Was 7 - more vertical space
            self.header_height = 11
            self.logo_size = 18
            self.show_pos_badge = True
            self.show_thru = True
            self.show_country = True
            self.show_headshot = True
            self.headshot_size = 28    # Larger to fill the border box
            self.row_gap = 1           # 1px gap between rows
            self.footer_height = 6     # Page dots

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

    def _draw_gradient_bg(self, c1, c2, vertical=True) -> Image.Image:
        img = Image.new("RGB", (self.width, self.height))
        draw = ImageDraw.Draw(img)
        steps = self.height if vertical else self.width
        for i in range(steps):
            ratio = i / max(steps - 1, 1)
            r = int(c1[0] + (c2[0] - c1[0]) * ratio)
            g = int(c1[1] + (c2[1] - c1[1]) * ratio)
            b = int(c1[2] + (c2[2] - c1[2]) * ratio)
            if vertical:
                draw.line([(0, i), (self.width, i)], fill=(r, g, b))
            else:
                draw.line([(i, 0), (i, self.height)], fill=(r, g, b))
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
        if flag_path.exists():
            try:
                flag = Image.open(flag_path).convert("RGBA")
                flag.thumbnail((10, 7), Image.Resampling.NEAREST)
                self._flag_cache[country_code] = flag
                return flag
            except Exception:
                pass
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
        """Render paginated broadcast-style leaderboard."""
        if not leaderboard_data:
            return None

        total_pages = max(1, (len(leaderboard_data) + self.max_players - 1) // self.max_players)
        page = page % total_pages

        img = self._draw_gradient_bg(COLORS["bg"], COLORS["bg_dark_green"])
        draw = ImageDraw.Draw(img)

        self._draw_header_bar(img, draw, "LEADERBOARD")

        y = self.header_height + 2
        start = page * self.max_players
        players = leaderboard_data[start : start + self.max_players]

        for i, player in enumerate(players):
            if i % 2 == 0:
                draw.rectangle([(0, y), (self.width - 1, y + self.row_height - 1)],
                               fill=COLORS["row_alt"])

            self._draw_leaderboard_row(img, draw, player, y, i, show_favorites)
            y += self.row_height + self.row_gap

        # Page indicator
        self._draw_page_dots(draw, page, total_pages)

        return img

    def _draw_leaderboard_row(self, img, draw, player, y, index, show_favorites):
        pos_text = str(player.get("position", ""))
        name = format_player_name(player.get("player", "?"), self.name_len)
        score = player.get("score", 0)
        score_text = format_score_to_par(score)
        position = player.get("position", 99)
        is_leader = (isinstance(position, int) and position == 1) or pos_text == "1"

        # Vertically center text in row
        text_y = y + (self.row_height - self._text_height(draw, "A", self.font_body)) // 2
        x = 1

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

        # Player name
        is_fav = show_favorites and self._is_favorite(player)
        if is_fav:
            name_color = COLORS["azalea_pink"]
        elif is_leader:
            name_color = COLORS["masters_yellow"]
        else:
            name_color = COLORS["white"]

        draw.text((x, text_y), name, fill=name_color, font=self.font_body)

        # Score and thru (right-aligned, non-overlapping)
        right_x = self.width - 2

        if self.show_thru:
            thru = str(player.get("thru", ""))
            if thru:
                thru_w = self._text_width(draw, thru, self.font_detail)
                draw.text((right_x - thru_w, text_y + 1), thru,
                          fill=COLORS["gray"], font=self.font_detail)
                right_x -= thru_w + 4

        score_w = self._text_width(draw, score_text, self.font_body)
        draw.text((right_x - score_w, text_y), score_text,
                  fill=self._score_color(score, position if isinstance(position, int) else 99),
                  font=self.font_body)

    # ═══════════════════════════════════════════════════════════
    # PLAYER CARD - Spacious layout
    # ═══════════════════════════════════════════════════════════

    def render_player_card(self, player: Dict) -> Optional[Image.Image]:
        """Render spacious player card with headshot and stats."""
        if not player:
            return None

        img = self._draw_gradient_bg(COLORS["masters_dark"], COLORS["masters_green"])
        draw = ImageDraw.Draw(img)

        # Gold border
        draw.rectangle([(0, 0), (self.width - 1, self.height - 1)],
                       outline=COLORS["masters_yellow"])

        x = 4
        y = 4

        # Headshot on left
        if self.show_headshot:
            headshot = self.logo_loader.get_player_headshot(
                player.get("player_id", ""),
                player.get("headshot_url"),
                max_size=self.headshot_size,
            )
            if headshot:
                draw.rectangle(
                    [x - 1, y - 1, x + self.headshot_size, y + self.headshot_size],
                    outline=COLORS["masters_yellow"],
                )
                img.paste(headshot, (x, y),
                          headshot if headshot.mode == "RGBA" else None)

        # Text area to the right of headshot
        tx = x + self.headshot_size + 6 if self.show_headshot else x

        # Player name - larger, with room to breathe
        name = player.get("player", "Unknown")
        if self.tier == "tiny":
            name = format_player_name(name, 10)
        elif self.tier == "small":
            name = format_player_name(name, 12)

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
            y_text += 10

        # Score - big and prominent with spacing
        score = player.get("score", 0)
        score_text = format_score_to_par(score)

        if self.tier == "large":
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
        if pos:
            draw.text((tx, y_text), f"Pos: {pos}",
                      fill=COLORS["masters_yellow"], font=self.font_detail)
            if thru and self.tier != "tiny":
                pos_w = self._text_width(draw, f"Pos: {pos}", self.font_detail)
                draw.text((tx + pos_w + 8, y_text), f"Thru: {thru}",
                          fill=COLORS["white"], font=self.font_detail)
            y_text += 9

        # Green jacket count at bottom
        jacket_count = MULTIPLE_WINNERS.get(player.get("player", ""), 0)
        if jacket_count > 0 and self.tier != "tiny":
            jy = self.height - 10
            jacket_icon = self.logo_loader.get_green_jacket_icon(size=8)
            jx = 4
            if jacket_icon:
                img.paste(jacket_icon, (jx, jy),
                          jacket_icon if jacket_icon.mode == "RGBA" else None)
                jx += 10
            draw.text((jx, jy), f"x{jacket_count} Green Jackets",
                      fill=COLORS["masters_yellow"], font=self.font_detail)

        return img

    # ═══════════════════════════════════════════════════════════
    # HOLE CARD - Clean layout
    # ═══════════════════════════════════════════════════════════

    def render_hole_card(self, hole_number: int) -> Optional[Image.Image]:
        hole_info = get_hole_info(hole_number)

        img = self._draw_gradient_bg((15, 80, 30), COLORS["augusta_green"])
        draw = ImageDraw.Draw(img)

        # Header
        h = self.header_height
        draw.rectangle([(0, 0), (self.width - 1, h - 1)], fill=COLORS["masters_green"])
        draw.line([(0, h - 1), (self.width, h - 1)], fill=COLORS["masters_yellow"])

        hole_text = f"HOLE {hole_number}"
        self._text_shadow(draw, (3, 1), hole_text, self.font_header, COLORS["white"])

        if self.tier != "tiny":
            name_text = hole_info["name"]
            name_w = self._text_width(draw, name_text, self.font_detail)
            draw.text((self.width - name_w - 3, 2), name_text,
                      fill=COLORS["masters_yellow"], font=self.font_detail)

        # Hole layout image (clamp to min 1px for tiny displays)
        hole_img = self.logo_loader.get_hole_image(
            hole_number,
            max_width=max(1, self.width - 8),
            max_height=max(1, self.height - h - 14),
        )
        if hole_img:
            hx = (self.width - hole_img.width) // 2
            hy = h + 2
            img.paste(hole_img, (hx, hy), hole_img if hole_img.mode == "RGBA" else None)

        # Footer
        footer_y = self.height - 9
        draw.rectangle([(0, footer_y), (self.width - 1, self.height - 1)], fill=(0, 0, 0))
        info_text = f"Par {hole_info['par']}  {hole_info['yardage']}y"
        self._text_shadow(draw, (3, footer_y + 1), info_text,
                          self.font_detail, COLORS["white"])

        zone = hole_info.get("zone")
        if zone and self.tier != "tiny":
            badge_text = zone.upper()
            bw = self._text_width(draw, badge_text, self.font_detail) + 4
            draw.rectangle([(self.width - bw - 2, footer_y),
                            (self.width - 2, self.height - 1)],
                           fill=COLORS["masters_dark"])
            draw.text((self.width - bw, footer_y + 1), badge_text,
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

    def render_fun_fact(self, fact_index: int = -1, scroll_offset: int = 0) -> Optional[Image.Image]:
        """Render a fun fact with vertical scroll support for long text."""
        if fact_index < 0:
            fact = get_random_fun_fact()
        else:
            fact = get_fun_fact_by_index(fact_index)

        img = self._draw_gradient_bg(COLORS["bg"], COLORS["bg_dark_green"])
        draw = ImageDraw.Draw(img)

        # Header
        h = self.header_height
        draw.rectangle([(0, 0), (self.width - 1, h - 1)], fill=COLORS["masters_green"])
        draw.line([(0, h - 1), (self.width, h - 1)], fill=COLORS["masters_yellow"])

        title = "DID YOU KNOW?"
        self._text_shadow(draw, (3, 1), title, self.font_header, COLORS["masters_yellow"])

        # Word-wrap the fact text with generous padding
        content_top = h + 4
        font = self.font_detail
        line_h = self._text_height(draw, "Ag", font) + 2  # Extra line spacing
        max_w = self.width - 10  # More horizontal padding

        words = fact.split()
        lines = []
        current_line = ""
        for word in words:
            test = f"{current_line} {word}".strip()
            if self._text_width(draw, test, font) <= max_w:
                current_line = test
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word
        if current_line:
            lines.append(current_line)

        # Apply scroll offset (for long facts)
        visible_lines = max(1, (self.height - content_top - 4) // line_h)
        if len(lines) > visible_lines:
            start_line = scroll_offset % max(1, len(lines) - visible_lines + 1)
            lines = lines[start_line : start_line + visible_lines]

        # Draw lines centered with spacing
        y = content_top
        for line in lines:
            draw.text((5, y), line, fill=COLORS["white"], font=font)
            y += line_h

        # Scroll indicator if text is long
        if len(words) > visible_lines * 4:  # Rough heuristic
            # Small down arrow
            ax = self.width - 6
            ay = self.height - 6
            draw.polygon([(ax - 2, ay - 2), (ax + 2, ay - 2), (ax, ay + 1)],
                         fill=COLORS["masters_yellow"])

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
        # Each tee time gets 2 lines: time + players
        entry_h = (self.row_height + self.row_gap) * 2 + 2
        visible = max(1, (self.height - content_top - self.footer_height - 2) // entry_h)

        total_pages = max(1, (len(schedule_data) + visible - 1) // visible)
        page = page % total_pages

        start = page * visible
        entries = schedule_data[start : start + visible]

        y = content_top
        for i, entry in enumerate(entries):
            # Time in yellow
            time_text = entry.get("time", "")
            draw.text((3, y), time_text, fill=COLORS["masters_yellow"], font=self.font_body)
            y += self.row_height + 1

            # Players indented
            players = entry.get("players", [])
            players_text = ", ".join(format_player_name(p, 10) for p in players[:3])
            draw.text((6, y), players_text, fill=COLORS["white"], font=self.font_detail)
            y += self.row_height + 3

        self._draw_page_dots(draw, page, total_pages)
        return img

    # ═══════════════════════════════════════════════════════════
    # COUNTDOWN - Centered and spacious
    # ═══════════════════════════════════════════════════════════

    def render_countdown(self, days: int, hours: int, minutes: int) -> Optional[Image.Image]:
        img = self._draw_gradient_bg(COLORS["masters_dark"], COLORS["masters_green"])
        draw = ImageDraw.Draw(img)

        # Masters logo centered at top
        logo = self.logo_loader.get_masters_logo(
            max_width=min(self.width - 10, 48),
            max_height=min(self.height // 3, 20),
        )
        if logo:
            lx = (self.width - logo.width) // 2
            img.paste(logo, (lx, 3), logo if logo.mode == "RGBA" else None)

        # Countdown number - big and centered
        if days > 0:
            count_text = str(days)
            unit_text = "DAYS" if days > 1 else "DAY"
        elif hours > 0:
            count_text = f"{hours}:{minutes:02d}"
            unit_text = "HOURS"
        else:
            count_text = "NOW"
            unit_text = ""

        mid_y = self.height // 2

        # "UNTIL THE MASTERS" centered
        until_text = "UNTIL THE MASTERS" if self.tier != "tiny" else "TO MASTERS"
        uw = self._text_width(draw, until_text, self.font_detail)
        draw.text(((self.width - uw) // 2, mid_y - 6),
                  until_text, fill=COLORS["white"], font=self.font_detail)

        # Big countdown number
        cw = self._text_width(draw, count_text, self.font_score)
        self._text_shadow(draw, ((self.width - cw) // 2, mid_y + 4),
                          count_text, self.font_score, COLORS["masters_yellow"])

        # Unit below
        if unit_text:
            uw2 = self._text_width(draw, unit_text, self.font_detail)
            draw.text(((self.width - uw2) // 2, mid_y + 16),
                      unit_text, fill=COLORS["light_gray"], font=self.font_detail)

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

        y = self.header_height + 4
        line_h = 10 if self.tier == "large" else 8

        draw.text((4, y), f"Players: {total}", fill=COLORS["white"], font=self.font_body)
        y += line_h + 2

        draw.text((4, y), f"Under par: {under}", fill=COLORS["under_par"], font=self.font_detail)
        y += line_h
        draw.text((4, y), f"Even par:  {even}", fill=COLORS["even_par"], font=self.font_detail)
        y += line_h
        draw.text((4, y), f"Over par:  {over}", fill=COLORS["over_par"], font=self.font_detail)
        y += line_h + 3

        # Leader highlight
        if leaderboard_data:
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
