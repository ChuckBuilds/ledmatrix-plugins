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
    ascii_safe,
    format_player_name,
    format_score_to_par,
    get_hole_info,
    get_score_description,
)
from masters_renderer import COLORS, MastersRenderer, _load_bdf_font, _load_font_sized

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

        # Wide-short panels use the base class two-column layout, which
        # adapts to the horizontal space. We lose the texture background
        # in that case — an acceptable trade for fitting twice as many
        # players on screen.
        if self.is_wide_short:
            return super().render_leaderboard(
                leaderboard_data, show_favorites=show_favorites, page=page
            )

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

    def render_player_card(self, player: Dict,
                           card_width: Optional[int] = None,
                           card_height: Optional[int] = None) -> Optional[Image.Image]:
        """Enhanced player card with round scores and green jacket info.

        When card_width/card_height are passed (Vegas scroll mode), the card
        is drawn at those dimensions instead of the full panel. We delegate
        to the base class's layouts which already honor the override, since
        the enhanced round-scores block doesn't fit in a Vegas-size card anyway.
        """
        if not player:
            return None

        # Vegas scroll override → always delegate to base (handles its own
        # width/height overrides and the wide-short/standard layout split).
        if card_width is not None or card_height is not None:
            return super().render_player_card(player, card_width=card_width, card_height=card_height)

        # Wide-short panels (192x48, 256x64, etc.): delegate to the base
        # class's two-column layout. We drop the round-scores block — there's
        # no room for it on a 48-tall canvas — but the core card stays legible.
        if self.is_wide_short:
            return super().render_player_card(player)

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
        jacket_count = MULTIPLE_WINNERS.get(ascii_safe(player.get("player", "")), 0)
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

    # Vertical-resolution threshold for the compact hole card layout.
    # At less than this height, Par/Yards move to the RIGHT of Hole #/Name
    # instead of stacking underneath them; at this height or taller, the
    # current left-panel-plus-image layout is used.
    _HOLE_COMPACT_HEIGHT = 48

    def render_hole_card(self, hole_number: int,
                         card_width: Optional[int] = None,
                         card_height: Optional[int] = None,
                         show_divider: bool = True) -> Optional[Image.Image]:
        """Enhanced hole card with two layout modes, chosen by vertical resolution:

        * **ch >= 48** → existing "big" layout: a single text column on the
          left with [Hole #, Name, Par, Yards] stacked top-to-bottom,
          and the hole layout image filling the right side.

        * **ch < 48** → compact two-column text-only layout:

              ┌─────────────┬─────────────┐
              │   #12       │  Par 3      │
              │ Golden Bell │  155y       │
              │             │ (AMEN COR)  │
              └─────────────┴─────────────┘

          Par and Yards sit to the RIGHT of the Hole #/Name column
          (instead of underneath). No hole image — there isn't enough
          vertical room for a useful one below 48px.

        The decision is purely on height so Vegas scroll blocks on a
        tall parent panel still get the image layout whenever they're
        48+ tall.
        """
        cw = card_width if card_width is not None else self.width
        ch = card_height if card_height is not None else self.height

        hole_info = get_hole_info(hole_number)
        img = self._draw_gradient_bg((10, 70, 25), COLORS["augusta_green"],
                                     width=cw, height=ch)
        draw = ImageDraw.Draw(img)

        if ch >= self._HOLE_COMPACT_HEIGHT:
            return self._render_hole_card_with_image(
                img, draw, hole_number, hole_info, cw, ch, show_divider=show_divider,
            )

        return self._render_hole_card_compact(
            img, draw, hole_number, hole_info, cw, ch, show_divider=show_divider,
        )

    def _render_hole_card_with_image(self, img, draw, hole_number: int,
                                     hole_info: Dict, cw: int, ch: int,
                                     show_divider: bool = True) -> Image.Image:
        """Large-canvas layout: single text column on the left + hole image on the right.

        Text column contents (stacked top to bottom):
            [Hole #, Hole Name (wrapped), Par, Yardage]
        Zone badge is drawn as a small chip in the bottom-right over the image.
        """
        # Left panel width: wide enough to fit "Golden Bell" and par/yardage text.
        # Grows with card width so 256x64 cards get more text room than 128x48.
        # If the card is too narrow for a useful image, let text fill the width.
        left_w = max(38, min(56, cw // 3))
        img_w = cw - left_w - 4
        if img_w < 20:
            left_w = cw

        show_image = left_w < cw

        # Left panel background strip (suppressed when show_divider=False for a unified green look)
        if show_divider:
            draw.rectangle([(0, 0), (left_w - 1, ch - 1)], fill=COLORS["masters_dark"])
        if show_image and show_divider:
            draw.line([(left_w - 1, 0), (left_w - 1, ch)], fill=COLORS["masters_yellow"])

        line_h = self._text_height(draw, "A", self.font_detail) + 1
        max_text_w = left_w - 4

        # Top: hole number
        hole_text = f"#{hole_number}"
        hole_h = self._text_height(draw, hole_text, self.font_header)
        hw = self._text_width(draw, hole_text, self.font_header)
        self._text_shadow(draw, ((left_w - hw) // 2, 2), hole_text,
                          self.font_header, COLORS["white"])
        top_bound = 2 + hole_h + 2

        # Bottom: par + yardage pinned to actual canvas bottom
        par_text = f"Par {hole_info['par']}"
        yard_text = f"{hole_info['yardage']}y"
        par_block_h = line_h * 2
        par_y = ch - par_block_h - 2
        pw = self._text_width(draw, par_text, self.font_detail)
        draw.text(((left_w - pw) // 2, par_y), par_text,
                  fill=COLORS["white"], font=self.font_detail)
        yw = self._text_width(draw, yard_text, self.font_detail)
        draw.text(((left_w - yw) // 2, par_y + line_h), yard_text,
                  fill=COLORS["light_gray"], font=self.font_detail)
        bottom_bound = par_y - 2

        # Middle: hole name — fit in whatever space is left between hole# and par
        name_text = hole_info["name"]
        name_slot = bottom_bound - top_bound
        max_lines = max(1, name_slot // line_h)

        name_lines: List[str] = []
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
                name_lines.append(current)

        # Clamp to available lines; ellipsize the last surviving line if clipped.
        if len(name_lines) > max_lines:
            name_lines = name_lines[:max_lines]
            last = name_lines[-1]
            while last and self._text_width(draw, last + "..", self.font_detail) > max_text_w:
                last = last[:-1]
            name_lines[-1] = (last + "..") if last else ".."
        for idx, line in enumerate(name_lines):
            while line and self._text_width(draw, line, self.font_detail) > max_text_w:
                line = line[:-1]
            name_lines[idx] = line

        block_h = len(name_lines) * line_h
        name_y = top_bound + max(0, (name_slot - block_h) // 2)
        for i, line in enumerate(name_lines):
            lw = self._text_width(draw, line, self.font_detail)
            draw.text(((left_w - lw) // 2, name_y + i * line_h), line,
                      fill=COLORS["masters_yellow"], font=self.font_detail)

        if show_image:
            # Right side: hole layout image
            img_x = left_w + 2
            actual_img_w = cw - img_x - 2
            img_h = ch - 4
            hole_img = self.logo_loader.get_hole_image(
                hole_number,
                max_width=actual_img_w,
                max_height=img_h,
            )
            if hole_img:
                hx = img_x + (actual_img_w - hole_img.width) // 2
                hy = (ch - hole_img.height) // 2
                img.paste(hole_img, (hx, hy), hole_img if hole_img.mode == "RGBA" else None)

            # Zone badge at bottom-right corner over the hole image
            zone = hole_info.get("zone")
            if zone and self.tier != "tiny":
                badge = zone.upper()
                bw = self._text_width(draw, badge, self.font_detail) + 4
                bx = cw - bw - 1
                by = ch - 9
                draw.rectangle([(bx, by), (cw - 1, ch - 1)],
                               fill=COLORS["masters_dark"])
                draw.text((bx + 2, by + 1), badge,
                          fill=COLORS["masters_yellow"], font=self.font_detail)

        return img

    def _render_hole_card_compact(self, img, draw, hole_number: int,
                                  hole_info: Dict,
                                  cw: Optional[int] = None,
                                  ch: Optional[int] = None,
                                  show_divider: bool = True) -> Image.Image:
        """Compact hole card for vertical resolutions below 48px.

        All text stacked on the left, course image on the right.

        Layout:
            ┌──────────────┬────────────┐
            │ #12          │            │
            │ Golden Bell  │  [course]  │
            │ Par 3  155y  │  [ map  ]  │
            │ AMEN CORNER  │            │
            └──────────────┴────────────┘
        """
        if cw is None:
            cw = self.width
        if ch is None:
            ch = self.height

        text_font = _load_bdf_font("5x7.bdf") or self.font_detail
        hole_font = _load_bdf_font("5x7.bdf") or self.font_body

        # Text takes ~half, image gets the rest.
        # If the card is too narrow for both columns, skip the image.
        min_text_w = 36
        min_img_w = 20
        text_w = max(min_text_w, cw // 2)
        img_w = cw - text_w - 2
        show_image = img_w >= min_img_w
        if not show_image:
            text_w = cw
        img_x = text_w + 1
        max_text_w = text_w - 3

        line_h = self._text_height(draw, "Ag", text_font) + 1
        y = 0

        # Hole number
        hole_text = f"#{hole_number}"
        draw.text((1, y), hole_text,
                  fill=COLORS["white"], font=hole_font)
        y += line_h

        # Hole name
        name_text = hole_info["name"]
        while name_text and self._text_width(draw, name_text, text_font) > max_text_w:
            name_text = name_text[:-1]
        draw.text((1, y), name_text,
                  fill=COLORS["masters_yellow"], font=text_font)
        y += line_h

        # Par + yardage on same line
        info_text = f"Par {hole_info['par']}  {hole_info['yardage']}y"
        while info_text and self._text_width(draw, info_text, text_font) > max_text_w:
            info_text = info_text[:-1]
        draw.text((1, y), info_text,
                  fill=COLORS["white"], font=text_font)
        y += line_h

        # Zone if room
        zone = hole_info.get("zone")
        if zone and y + line_h <= ch:
            zone_text = zone.upper()
            while zone_text and self._text_width(draw, zone_text, text_font) > max_text_w:
                zone_text = zone_text[:-1]
            draw.text((1, y), zone_text,
                      fill=COLORS["masters_yellow"], font=text_font)

        if show_image:
            # Divider between text and image (suppressed when show_divider=False)
            if show_divider:
                draw.line([(text_w, 0), (text_w, ch - 1)],
                          fill=COLORS["masters_yellow"])

            # Course image on the right
            hole_img = self.logo_loader.get_hole_image(
                hole_number, max_width=img_w, max_height=ch - 2,
            )
            if hole_img:
                hx = img_x + (img_w - hole_img.width) // 2
                hy = (ch - hole_img.height) // 2
                img.paste(hole_img, (hx, hy),
                          hole_img if hole_img.mode == "RGBA" else None)

        return img

    def render_live_alert(
        self, player_name: str, hole: int, score_desc: str
    ) -> Optional[Image.Image]:
        """Render a live scoring alert.

        Wide-short panels use a horizontal layout: LIVE badge on the left,
        then player name on top / hole info beneath, with the big score
        description hugging the right edge.
        """
        img = self._draw_gradient_bg(COLORS["bg"], COLORS["bg_dark_green"])
        draw = ImageDraw.Draw(img)

        is_great = score_desc.lower() in ("eagle", "albatross", "hole in one")
        header_color = COLORS["gold"] if is_great else COLORS["masters_green"]
        draw.rectangle([(0, 0), (self.width - 1, self.header_height - 1)], fill=header_color)
        draw.line([(0, self.header_height - 1), (self.width, self.header_height - 1)],
                  fill=COLORS["masters_yellow"])

        self._text_shadow(draw, (3, 1), "LIVE", self.font_header,
                          COLORS["white"] if not is_great else COLORS["bg"])

        # Wide-short horizontal layout: everything lives below the header bar
        # in two columns so we don't stack 3 rows of large text on 48px.
        if self.is_wide_short:
            desc_upper = score_desc.upper()
            desc_color = COLORS["masters_yellow"] if is_great else COLORS["under_par"]
            desc_w = self._text_width(draw, desc_upper, self.font_score)
            desc_h = self._text_height(draw, desc_upper, self.font_score)

            # Right-hand big score block, vertically centered in the body.
            body_top = self.header_height + 2
            body_bottom = self.height - 3
            body_mid = (body_top + body_bottom) // 2
            desc_x = self.width - desc_w - 4
            desc_y = body_mid - desc_h // 2
            self._text_shadow(draw, (desc_x, desc_y),
                              desc_upper, self.font_score, desc_color)

            # Left-hand stack: name on top, hole info underneath.
            name = format_player_name(player_name, 18)
            name_h = self._text_height(draw, name, self.font_body)
            text_left = 4
            text_top = body_top + 2
            self._text_shadow(draw, (text_left, text_top),
                              name, self.font_body, COLORS["white"])

            if 1 <= hole <= 18:
                hole_info = get_hole_info(hole)
                hole_text = f"Hole {hole}: {hole_info['name']}"
                # Clip to the space before the score block.
                max_w = desc_x - text_left - 6
                while hole_text and self._text_width(draw, hole_text, self.font_detail) > max_w:
                    hole_text = hole_text[:-1]
                draw.text((text_left, text_top + name_h + 3),
                          hole_text, fill=COLORS["light_gray"],
                          font=self.font_detail)
            return img

        # Standard (taller) vertical stack layout
        y = self.header_height + 6

        name = format_player_name(player_name, self.name_len)
        self._text_shadow(draw, (4, y), name, self.font_body, COLORS["white"])
        y += self._text_height(draw, name, self.font_body) + 6

        desc_upper = score_desc.upper() + "!"
        desc_color = COLORS["masters_yellow"] if is_great else COLORS["under_par"]
        dw = self._text_width(draw, desc_upper, self.font_score)
        self._text_shadow(draw, ((self.width - dw) // 2, y),
                          desc_upper, self.font_score, desc_color)
        y += self._text_height(draw, desc_upper, self.font_score) + 6

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
