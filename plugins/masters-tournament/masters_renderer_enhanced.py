"""
Enhanced Masters Tournament Renderer

Extends MastersRenderer with additional visual polish:
- Texture overlay backgrounds
- Enhanced player cards with round-by-round scores
- Course overview with pagination
- Live scoring alerts
- All methods support pagination/scrolling from base class
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image, ImageDraw

from masters_helpers import (
    AUGUSTA_HOLES,
    AUGUSTA_PAR,
    MULTIPLE_WINNERS,
    PAST_CHAMPIONS,
    format_player_name,
    format_score_to_par,
    get_hole_info,
    get_score_description,
)
from masters_renderer import COLORS, MastersRenderer

logger = logging.getLogger(__name__)


class MastersRendererEnhanced(MastersRenderer):
    """Enhanced renderer with texture backgrounds, extended player cards, and more."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.backgrounds_dir = self.plugin_dir / "assets" / "masters" / "backgrounds"

    def _get_textured_bg(self) -> Image.Image:
        img = self._draw_gradient_bg(COLORS["bg"], COLORS["bg_dark_green"])
        texture_path = self.backgrounds_dir / "augusta_green_texture.png"
        if texture_path.exists() and self.tier != "tiny":
            try:
                texture = Image.open(texture_path).convert("RGBA")
                texture = texture.resize((self.width, self.height), Image.Resampling.NEAREST)
                img = Image.blend(img.convert("RGBA"), texture, 0.15).convert("RGB")
            except Exception:
                pass
        return img

    def render_leaderboard(
        self, leaderboard_data: List[Dict], show_favorites: bool = True,
        page: int = 0,
    ) -> Optional[Image.Image]:
        """Enhanced leaderboard with texture background + pagination."""
        if not leaderboard_data:
            return None

        total_pages = max(1, (len(leaderboard_data) + self.max_players - 1) // self.max_players)
        page = page % total_pages

        img = self._get_textured_bg()
        draw = ImageDraw.Draw(img)

        self._draw_header_bar(img, draw, "LEADERBOARD")

        y = self.header_height + 2
        start = page * self.max_players
        players = leaderboard_data[start : start + self.max_players]

        for i, player in enumerate(players):
            if i % 2 == 0:
                draw.rectangle(
                    [(0, y), (self.width - 1, y + self.row_height - 1)],
                    fill=COLORS["row_alt"],
                )
            self._draw_leaderboard_row(img, draw, player, y, i, show_favorites)
            y += self.row_height + self.row_gap

        self._draw_page_dots(draw, page, total_pages)
        return img

    def render_player_card(self, player: Dict) -> Optional[Image.Image]:
        """Enhanced player card with round scores and green jacket info."""
        if not player:
            return None

        img = self._draw_gradient_bg(COLORS["masters_dark"], COLORS["masters_green"])
        draw = ImageDraw.Draw(img)

        # Gold border
        draw.rectangle(
            [(0, 0), (self.width - 1, self.height - 1)],
            outline=COLORS["masters_yellow"],
        )

        x = 4
        y = 4

        # Headshot on the left
        headshot_drawn = False
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
                img.paste(
                    headshot, (x, y),
                    headshot if headshot.mode == "RGBA" else None,
                )
                headshot_drawn = True

        tx = x + self.headshot_size + 6 if headshot_drawn else x

        # Player name
        name = player.get("player", "Unknown")
        display_name = format_player_name(name, self.name_len)
        self._text_shadow(draw, (tx, y), display_name, self.font_header, COLORS["white"])
        y_text = y + self._text_height(draw, display_name, self.font_header) + 3

        # Country
        country = player.get("country", "")
        if country and self.tier != "tiny":
            flag = self._get_flag(country)
            fx = tx
            if flag:
                img.paste(flag, (fx, y_text), flag)
                fx += flag.width + 3
            draw.text((fx, y_text), country, fill=COLORS["light_gray"], font=self.font_detail)
            y_text += 10

        # Score - big
        score = player.get("score", 0)
        score_text = format_score_to_par(score)
        self._text_shadow(draw, (tx, y_text), score_text,
                          self.font_score, self._score_color(score))
        y_text += self._text_height(draw, score_text, self.font_score) + 3

        # Position and thru
        pos = player.get("position", "")
        thru = player.get("thru", "")
        status_parts = []
        if pos:
            status_parts.append(f"Pos:{pos}")
        if thru:
            status_parts.append(f"Thru:{thru}")
        if status_parts:
            draw.text((tx, y_text), "   ".join(status_parts),
                      fill=COLORS["light_gray"], font=self.font_detail)
            y_text += 10

        # Round scores (if room)
        rounds = player.get("rounds", [None, None, None, None])
        if any(r is not None for r in rounds) and self.tier == "large":
            draw.line([(tx, y_text), (self.width - 6, y_text)],
                      fill=COLORS["masters_yellow"])
            y_text += 3

            rx = tx
            for i, r in enumerate(rounds):
                if r is not None:
                    r_label = f"R{i+1}:"
                    draw.text((rx, y_text), r_label,
                              fill=COLORS["gray"], font=self.font_detail)
                    lw = self._text_width(draw, r_label, self.font_detail)
                    r_color = COLORS["under_par"] if r < AUGUSTA_PAR else COLORS["over_par"] if r > AUGUSTA_PAR else COLORS["even_par"]
                    draw.text((rx + lw + 1, y_text), str(r),
                              fill=r_color, font=self.font_detail)
                    rx += lw + self._text_width(draw, str(r), self.font_detail) + 6

        # Green jacket count at bottom
        jacket_count = MULTIPLE_WINNERS.get(player.get("player", ""), 0)
        if jacket_count > 0 and self.tier != "tiny":
            jy = self.height - 10
            jacket = self.logo_loader.get_green_jacket_icon(size=8)
            jx = 4
            if jacket:
                img.paste(jacket, (jx, jy), jacket if jacket.mode == "RGBA" else None)
                jx += 10
            draw.text((jx, jy), f"x{jacket_count} Green Jackets",
                      fill=COLORS["masters_yellow"], font=self.font_detail)

        return img

    def render_hole_card(self, hole_number: int) -> Optional[Image.Image]:
        """Enhanced hole card — left info panel, right hole image using full height."""
        hole_info = get_hole_info(hole_number)

        img = self._draw_gradient_bg((10, 70, 25), COLORS["augusta_green"])
        draw = ImageDraw.Draw(img)

        # Left panel width for text info
        left_w = 38 if self.tier == "large" else 28

        # ── Left panel: hole info ──
        draw.rectangle([(0, 0), (left_w - 1, self.height - 1)], fill=COLORS["masters_dark"])
        draw.line([(left_w - 1, 0), (left_w - 1, self.height)], fill=COLORS["masters_yellow"])

        # Hole number
        hole_text = f"#{hole_number}"
        hw = self._text_width(draw, hole_text, self.font_header)
        self._text_shadow(draw, ((left_w - hw) // 2, 2), hole_text,
                          self.font_header, COLORS["white"])

        # Hole name — width-aware wrapping
        name_text = hole_info["name"]
        name_y = 12 if self.tier == "tiny" else 14
        line_h = self._text_height(draw, "A", self.font_detail) + 1
        max_text_w = left_w - 4

        name_lines = []
        nw = self._text_width(draw, name_text, self.font_detail)
        if nw <= max_text_w:
            name_lines = [name_text]
        else:
            words = name_text.split()
            current = ""
            for word in words:
                test = f"{current} {word}".strip() if current else word
                if self._text_width(draw, test, self.font_detail) <= max_text_w:
                    current = test
                else:
                    if current:
                        name_lines.append(current)
                    current = word
            if current:
                # Truncate last line with ellipsis if too wide
                if self._text_width(draw, current, self.font_detail) > max_text_w:
                    while len(current) > 1 and self._text_width(draw, current + "..", self.font_detail) > max_text_w:
                        current = current[:-1]
                    current = current + ".."
                name_lines.append(current)

        for i, line in enumerate(name_lines):
            lw = self._text_width(draw, line, self.font_detail)
            draw.text(((left_w - lw) // 2, name_y + i * line_h), line,
                      fill=COLORS["masters_yellow"], font=self.font_detail)

        # Par and yardage — anchored to bottom, above name block
        name_block_bottom = name_y + len(name_lines) * line_h
        par_yard_h = line_h * 2 + 2  # two lines plus padding
        par_y = max(name_block_bottom + 2, self.height - par_yard_h - 2)

        par_text = f"Par {hole_info['par']}"
        pw = self._text_width(draw, par_text, self.font_detail)
        draw.text(((left_w - pw) // 2, par_y), par_text,
                  fill=COLORS["white"], font=self.font_detail)

        yard_text = f"{hole_info['yardage']}y"
        yw = self._text_width(draw, yard_text, self.font_detail)
        draw.text(((left_w - yw) // 2, par_y + line_h), yard_text,
                  fill=COLORS["light_gray"], font=self.font_detail)

        # ── Right side: hole layout image using full height ──
        img_x = left_w + 2
        img_w = self.width - img_x - 2
        img_h = self.height - 4
        hole_img = self.logo_loader.get_hole_image(
            hole_number,
            max_width=img_w,
            max_height=img_h,
        )
        if hole_img:
            hx = img_x + (img_w - hole_img.width) // 2
            hy = (self.height - hole_img.height) // 2
            img.paste(hole_img, (hx, hy), hole_img if hole_img.mode == "RGBA" else None)

        # Zone badge at bottom-right corner (over the hole image area)
        zone = hole_info.get("zone")
        if zone and self.tier != "tiny":
            badge = zone.upper()
            bw = self._text_width(draw, badge, self.font_detail) + 4
            bx = self.width - bw - 1
            by = self.height - 9
            draw.rectangle([(bx, by), (self.width - 1, self.height - 1)],
                           fill=COLORS["masters_dark"])
            draw.text((bx + 2, by + 1), badge,
                      fill=COLORS["masters_yellow"], font=self.font_detail)

        return img

    def render_live_alert(
        self, player_name: str, hole: int, score_desc: str
    ) -> Optional[Image.Image]:
        """Render a live scoring alert with generous spacing."""
        img = self._draw_gradient_bg(COLORS["bg"], COLORS["bg_dark_green"])
        draw = ImageDraw.Draw(img)

        is_great = score_desc.lower() in ("eagle", "albatross", "hole in one")
        header_color = COLORS["gold"] if is_great else COLORS["masters_green"]
        draw.rectangle([(0, 0), (self.width - 1, self.header_height - 1)], fill=header_color)
        draw.line([(0, self.header_height - 1), (self.width, self.header_height - 1)],
                  fill=COLORS["masters_yellow"])

        self._text_shadow(draw, (3, 1), "LIVE", self.font_header,
                          COLORS["white"] if not is_great else COLORS["bg"])

        y = self.header_height + 6

        # Player name with room
        name = format_player_name(player_name, self.name_len)
        self._text_shadow(draw, (4, y), name, self.font_body, COLORS["white"])
        y += self._text_height(draw, name, self.font_body) + 6

        # Score type - big and centered
        desc_upper = score_desc.upper() + "!"
        desc_color = COLORS["masters_yellow"] if is_great else COLORS["under_par"]
        dw = self._text_width(draw, desc_upper, self.font_score)
        self._text_shadow(draw, ((self.width - dw) // 2, y),
                          desc_upper, self.font_score, desc_color)
        y += self._text_height(draw, desc_upper, self.font_score) + 6

        # Hole info
        if 1 <= hole <= 18:
            hole_info = get_hole_info(hole)
            hole_text = f"Hole {hole} - {hole_info['name']}"
            htw = self._text_width(draw, hole_text, self.font_detail)
            draw.text(((self.width - htw) // 2, y), hole_text,
                      fill=COLORS["light_gray"], font=self.font_detail)

        return img

    def render_course_overview(self, page: int = 0) -> Optional[Image.Image]:
        """Render Augusta National overview - paginated across all 18 holes."""
        img = self._draw_gradient_bg(COLORS["masters_dark"], COLORS["masters_green"])
        draw = ImageDraw.Draw(img)

        font = self.font_detail

        # Calculate how many holes fit on screen
        content_top = self.header_height + 3
        content_bottom = self.height - self.footer_height - 4
        usable_h = content_bottom - content_top
        line_h = self._text_height(draw, "A", font) + 3
        max_holes = max(1, usable_h // line_h)

        # Paginate across all 18 holes
        all_holes = list(range(1, 19))
        total_pages = max(1, (len(all_holes) + max_holes - 1) // max_holes)
        page = page % total_pages

        start = page * max_holes
        holes = all_holes[start : start + max_holes]

        # Title based on which nine we're showing
        if holes[0] <= 9:
            title = "FRONT NINE" if holes[-1] <= 9 else "FRONT/BACK"
        else:
            title = "BACK NINE"

        self._draw_header_bar(img, draw, title, show_logo=True)

        if self.tier == "tiny":
            par = sum(AUGUSTA_HOLES[h]["par"] for h in holes)
            y = self.header_height + 2
            draw.text((2, y), f"Par {par}", fill=COLORS["white"], font=self.font_body)
            return img

        y = content_top
        for h in holes:
            info = AUGUSTA_HOLES[h]

            num_text = f"{h:2d}"
            draw.text((3, y), num_text, fill=COLORS["masters_yellow"], font=font)

            name = info["name"]
            if self.tier == "small":
                name = name[:10]
            draw.text((18, y), name, fill=COLORS["white"], font=font)

            par_text = f"P{info['par']} {info['yardage']}y"
            pw = self._text_width(draw, par_text, font)
            draw.text((self.width - pw - 3, y), par_text,
                      fill=COLORS["light_gray"], font=font)

            y += line_h

        self._draw_page_dots(draw, page, total_pages)

        return img
