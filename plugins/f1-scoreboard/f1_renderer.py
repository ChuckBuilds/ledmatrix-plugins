"""
F1 Renderer Module

Renders all F1 display mode cards as PIL Images for the LED matrix.
All layouts are fully dynamic - dimensions are proportional to display size.
Supports 64x32, 128x32, 96x48, 192x48, and any other matrix configuration.
"""

import logging
import math
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

import pytz
from PIL import Image, ImageDraw, ImageFont

from logo_downloader import F1LogoLoader
from team_colors import (F1_RED, PODIUM_COLORS, get_team_color)

logger = logging.getLogger(__name__)

# Accent bar width as fraction of display width
ACCENT_BAR_RATIO = 0.025  # ~3px on 128-wide display


class F1Renderer:
    """Renders F1 display cards as PIL Images."""

    def __init__(self, display_width: int, display_height: int,
                 config: Optional[Dict[str, Any]] = None,
                 logo_loader: Optional[F1LogoLoader] = None,
                 custom_logger: Optional[logging.Logger] = None):
        self.display_width = display_width
        self.display_height = display_height
        self.config = config or {}
        self.logger = custom_logger or logger

        # Logo loader
        self.logo_loader = logo_loader or F1LogoLoader()

        # Calculate dynamic sizes
        self.accent_bar_width = max(2, int(display_width * ACCENT_BAR_RATIO))
        self.logo_max_height = int(display_height * 0.8)
        self.logo_max_width = int(display_height * 0.8)

        # Load fonts
        self.fonts = self._load_fonts()

    def _load_fonts(self) -> Dict[str, Any]:
        """Load fonts with config overrides and fallbacks."""
        fonts = {}
        customization = self.config.get("customization", {})

        # Scale font sizes based on display height
        height_scale = self.display_height / 32.0

        header_cfg = customization.get("header_text", {})
        position_cfg = customization.get("position_text", {})
        detail_cfg = customization.get("detail_text", {})
        small_cfg = customization.get("small_text", {})

        fonts["header"] = self._load_font(
            header_cfg.get("font", "PressStart2P-Regular.ttf"),
            int(header_cfg.get("font_size", max(6, int(8 * height_scale)))))
        fonts["position"] = self._load_font(
            position_cfg.get("font", "PressStart2P-Regular.ttf"),
            int(position_cfg.get("font_size", max(6, int(8 * height_scale)))))
        fonts["detail"] = self._load_font(
            detail_cfg.get("font", "4x6-font.ttf"),
            int(detail_cfg.get("font_size", max(5, int(6 * height_scale)))))
        fonts["small"] = self._load_font(
            small_cfg.get("font", "4x6-font.ttf"),
            int(small_cfg.get("font_size", max(5, int(6 * height_scale)))))

        return fonts

    def _to_local_dt(self, utc_iso_str: str) -> datetime:
        """Parse a UTC ISO datetime string and convert to configured local timezone."""
        dt = datetime.fromisoformat(utc_iso_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=pytz.UTC)
        tz_str = self.config.get("timezone", "UTC")
        try:
            local_tz = pytz.timezone(tz_str)
        except pytz.exceptions.UnknownTimeZoneError:
            local_tz = pytz.UTC
        return dt.astimezone(local_tz)

    def _load_font(self, font_name: str,
                   size: int) -> Union[ImageFont.FreeTypeFont, Any]:
        """Load a font with multiple path fallbacks."""
        font_paths = [
            f"assets/fonts/{font_name}",
            str(Path(__file__).parent.parent.parent /
                "assets" / "fonts" / font_name),
        ]

        for path in font_paths:
            try:
                return ImageFont.truetype(path, size)
            except (OSError, IOError):
                continue

        self.logger.warning("Could not load font %s size %d, using default",
                          font_name, size)
        return ImageFont.load_default()

    # ─── Text Drawing Helpers ──────────────────────────────────────────

    def _draw_text_outlined(self, draw: ImageDraw.ImageDraw, xy: Tuple[int, int],
                            text: str, font, fill=(255, 255, 255),
                            outline=(0, 0, 0)):
        """Draw text with a 1px outline for readability."""
        x, y = xy
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            draw.text((x + dx, y + dy), text, font=font, fill=outline)
        draw.text((x, y), text, font=font, fill=fill)

    def _get_text_width(self, draw: ImageDraw.ImageDraw, text: str,
                        font) -> int:
        """Get the width of rendered text."""
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0]

    def _get_text_height(self, draw: ImageDraw.ImageDraw, text: str,
                         font) -> int:
        """Get the height of rendered text."""
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[3] - bbox[1]

    def _truncate_text(self, draw: ImageDraw.ImageDraw, text: str,
                       font, max_width: int) -> str:
        """Truncate text to fit within max_width pixels."""
        if self._get_text_width(draw, text, font) <= max_width:
            return text
        while len(text) > 1:
            text = text[:-1]
            if self._get_text_width(draw, text + "..", font) <= max_width:
                return text + ".."
        return text

    # ─── Accent Bar Drawing ───────────────────────────────────────────

    def _draw_accent_bar(self, draw: ImageDraw.ImageDraw,
                         constructor_id: str, x: int = 0,
                         is_favorite: bool = False):
        """Draw a team color accent bar on the left edge."""
        color = get_team_color(constructor_id)
        bar_width = self.accent_bar_width
        if is_favorite:
            bar_width = max(bar_width + 1, int(bar_width * 1.5))

        draw.rectangle(
            [x, 0, x + bar_width - 1, self.display_height - 1],
            fill=color)

    # ─── Driver Standings Card ─────────────────────────────────────────

    def render_driver_standing(self, entry: Dict) -> Image.Image:
        """
        Render a single driver standings card.

        Layout: [accent bar] [pos] [team logo] [code] [points] [W/P stats]
        """
        img = Image.new("RGBA",
                        (self.display_width, self.display_height),
                        (0, 0, 0, 255))
        draw = ImageDraw.Draw(img)

        constructor_id = entry.get("constructor_id", "")
        is_favorite = entry.get("is_favorite", False)

        # Accent bar
        self._draw_accent_bar(draw, constructor_id, is_favorite=is_favorite)

        x_offset = self.accent_bar_width + 2

        # Position number
        pos_text = f"P{entry.get('position', '?')}"
        self._draw_text_outlined(draw, (x_offset, 2), pos_text,
                                self.fonts["position"],
                                fill=(255, 255, 255))
        pos_width = self._get_text_width(draw, pos_text, self.fonts["position"])
        x_offset += pos_width + 3

        # Team logo
        logo = self.logo_loader.get_team_logo(
            constructor_id, self.logo_max_height, self.logo_max_width)
        if logo:
            logo_y = (self.display_height - logo.height) // 2
            img.paste(logo, (x_offset, logo_y), logo)
            x_offset += logo.width + 3

        # Driver code (large)
        code = entry.get("code", "???")
        self._draw_text_outlined(draw, (x_offset, 2), code,
                                self.fonts["position"],
                                fill=(255, 255, 255))

        # Full name (small, below code if space)
        name_y = 2 + self._get_text_height(draw, code, self.fonts["position"]) + 2
        if name_y + 6 < self.display_height:
            full_name = f"{entry.get('first_name', '')} {entry.get('last_name', '')}"
            self._draw_text_outlined(draw, (x_offset, name_y), full_name,
                                    self.fonts["small"],
                                    fill=(180, 180, 180))

        # Points (right-aligned)
        points = entry.get("points", 0)
        points_text = f"{int(points)}pts"
        pts_width = self._get_text_width(draw, points_text, self.fonts["detail"])
        pts_x = self.display_width - pts_width - 2
        self._draw_text_outlined(draw, (pts_x, 2), points_text,
                                self.fonts["detail"],
                                fill=(255, 255, 0))

        # Wins and poles (right-aligned, below points)
        wins = entry.get("wins", 0)
        poles = entry.get("poles", 0)
        stats_text = f"{wins}W {poles}P"
        stats_width = self._get_text_width(draw, stats_text, self.fonts["small"])
        stats_x = self.display_width - stats_width - 2
        stats_y = 2 + self._get_text_height(draw, points_text,
                                            self.fonts["detail"]) + 2
        if stats_y + 6 < self.display_height:
            self._draw_text_outlined(draw, (stats_x, stats_y), stats_text,
                                    self.fonts["small"],
                                    fill=(200, 200, 200))

        return img

    # ─── Constructor Standings Card ────────────────────────────────────

    def render_constructor_standing(self, entry: Dict) -> Image.Image:
        """
        Render a single constructor standings card.

        Layout: [accent bar] [pos] [team logo] [team name] [points] [wins]
        """
        img = Image.new("RGBA",
                        (self.display_width, self.display_height),
                        (0, 0, 0, 255))
        draw = ImageDraw.Draw(img)

        constructor_id = entry.get("constructor_id", "")
        is_favorite = entry.get("is_favorite", False)

        # Accent bar
        self._draw_accent_bar(draw, constructor_id, is_favorite=is_favorite)

        x_offset = self.accent_bar_width + 2

        # Position
        pos_text = f"P{entry.get('position', '?')}"
        self._draw_text_outlined(draw, (x_offset, 2), pos_text,
                                self.fonts["position"],
                                fill=(255, 255, 255))
        pos_width = self._get_text_width(draw, pos_text, self.fonts["position"])
        x_offset += pos_width + 3

        # Team logo
        logo = self.logo_loader.get_team_logo(
            constructor_id, self.logo_max_height, self.logo_max_width)
        if logo:
            logo_y = (self.display_height - logo.height) // 2
            img.paste(logo, (x_offset, logo_y), logo)
            x_offset += logo.width + 3

        # Team name
        team_name = entry.get("constructor", "")
        self._draw_text_outlined(draw, (x_offset, 2), team_name,
                                self.fonts["position"],
                                fill=get_team_color(constructor_id))

        # Points (right-aligned)
        points = entry.get("points", 0)
        points_text = f"{int(points)}pts"
        pts_width = self._get_text_width(draw, points_text, self.fonts["detail"])
        pts_x = self.display_width - pts_width - 2
        self._draw_text_outlined(draw, (pts_x, 2), points_text,
                                self.fonts["detail"],
                                fill=(255, 255, 0))

        # Wins (right-aligned, below points)
        wins = entry.get("wins", 0)
        wins_text = f"{wins}W"
        wins_width = self._get_text_width(draw, wins_text, self.fonts["small"])
        wins_x = self.display_width - wins_width - 2
        wins_y = 2 + self._get_text_height(draw, points_text,
                                           self.fonts["detail"]) + 2
        if wins_y + 6 < self.display_height:
            self._draw_text_outlined(draw, (wins_x, wins_y), wins_text,
                                    self.fonts["small"],
                                    fill=(200, 200, 200))

        return img

    # ─── Recent Race Results Card ──────────────────────────────────────

    def render_race_result(self, race: Dict) -> Image.Image:
        """
        Render a race result card with podium visualization.

        Layout: [GP name + winner time] [P1 P2 P3 with team colors + medals]
        """
        img = Image.new("RGBA",
                        (self.display_width, self.display_height),
                        (0, 0, 0, 255))
        draw = ImageDraw.Draw(img)

        results = race.get("results", [])
        race_name = race.get("race_name", "Grand Prix")

        # Shorten race name to fit
        short_name = race_name.replace("Grand Prix", "GP")

        # Header: GP name
        self._draw_text_outlined(draw, (2, 1), short_name,
                                self.fonts["detail"],
                                fill=F1_RED)

        # Winner time (right-aligned on header line)
        if results:
            winner_time = results[0].get("time", "")
            if winner_time:
                tw = self._get_text_width(draw, winner_time, self.fonts["small"])
                self._draw_text_outlined(
                    draw, (self.display_width - tw - 2, 1),
                    winner_time, self.fonts["small"],
                    fill=(200, 200, 200))

        # Podium section - top 3 finishers
        header_height = self._get_text_height(draw, short_name,
                                              self.fonts["detail"]) + 4
        podium_y = header_height

        # Calculate space per podium position
        top_n = min(len(results), 3)
        if top_n == 0:
            return img

        section_width = self.display_width // top_n

        for i in range(top_n):
            r = results[i]
            pos = r.get("position", i + 1)
            code = r.get("code", "???")
            constructor_id = r.get("constructor_id", "")
            team_color = get_team_color(constructor_id)
            medal_color = PODIUM_COLORS.get(pos, (200, 200, 200))

            x_base = i * section_width

            # Position with medal color
            pos_label = f"P{pos}"
            self._draw_text_outlined(draw, (x_base + 2, podium_y),
                                    pos_label, self.fonts["detail"],
                                    fill=medal_color)

            # Driver code
            code_y = podium_y + self._get_text_height(
                draw, pos_label, self.fonts["detail"]) + 1
            self._draw_text_outlined(draw, (x_base + 2, code_y),
                                    code, self.fonts["detail"],
                                    fill=(255, 255, 255))

            # Team color dot
            dot_y = code_y + self._get_text_height(
                draw, code, self.fonts["detail"]) + 1
            if dot_y + 3 < self.display_height:
                draw.rectangle(
                    [x_base + 2, dot_y,
                     x_base + 2 + self.accent_bar_width * 3, dot_y + 2],
                    fill=team_color)

            # Mini team logo
            mini_logo = self.logo_loader.get_team_logo(
                constructor_id,
                max_height=int(self.display_height * 0.3),
                max_width=int(section_width * 0.4))
            if mini_logo:
                logo_x = x_base + section_width - mini_logo.width - 1
                logo_y = podium_y
                if logo_y + mini_logo.height < self.display_height:
                    img.paste(mini_logo, (logo_x, logo_y), mini_logo)

        return img

    # ─── Shared Driver Row Helper ─────────────────────────────────────

    def _render_driver_row(self, entry: Dict, time_key: str = "",
                           gap_key: str = "",
                           show_eliminated: bool = False) -> Image.Image:
        """
        Render a common driver row card used by qualifying, practice, sprint.

        Layout: [accent bar] [pos] [code] [time] [gap] [team logo]

        Args:
            entry: Driver entry dict
            time_key: Key for the time field (e.g. "best_lap", "time")
            gap_key: Key for the gap field (e.g. "gap")
            show_eliminated: Whether to show "OUT" for eliminated entries
        """
        img = Image.new("RGBA",
                        (self.display_width, self.display_height),
                        (0, 0, 0, 255))
        draw = ImageDraw.Draw(img)

        constructor_id = entry.get("constructor_id", "")
        self._draw_accent_bar(draw, constructor_id)

        x_offset = self.accent_bar_width + 2

        # Position
        pos_text = f"P{entry.get('position', '?')}"
        self._draw_text_outlined(draw, (x_offset, 2), pos_text,
                                self.fonts["position"],
                                fill=(255, 255, 255))
        pos_width = self._get_text_width(draw, pos_text, self.fonts["position"])
        x_offset += pos_width + 4

        # Driver code
        code = entry.get("code", "???")
        self._draw_text_outlined(draw, (x_offset, 2), code,
                                self.fonts["position"],
                                fill=(255, 255, 255))
        code_width = self._get_text_width(draw, code, self.fonts["position"])
        x_offset += code_width + 4

        # Time
        time_str = entry.get(time_key, "") if time_key else ""
        time_width = 0
        if time_str:
            self._draw_text_outlined(draw, (x_offset, 2), time_str,
                                    self.fonts["detail"],
                                    fill=(200, 200, 200))
            time_width = self._get_text_width(draw, time_str,
                                             self.fonts["detail"])
            x_offset += time_width + 4
        elif show_eliminated:
            eliminated = entry.get("eliminated_in", "")
            if eliminated:
                self._draw_text_outlined(draw, (x_offset, 2), "OUT",
                                        self.fonts["detail"],
                                        fill=(255, 80, 80))

        # Gap to leader
        gap_str = entry.get(gap_key, "") if gap_key else ""
        if gap_str:
            gap_y = 2 + self._get_text_height(draw, "1:00",
                                              self.fonts["detail"]) + 2
            if gap_y + 6 < self.display_height:
                gap_x = (x_offset - time_width - 4
                         if time_str else x_offset)
                self._draw_text_outlined(draw, (gap_x, gap_y),
                                        gap_str, self.fonts["small"],
                                        fill=(255, 200, 0))

        # Team logo (right-aligned)
        logo = self.logo_loader.get_team_logo(
            constructor_id,
            max_height=int(self.display_height * 0.6),
            max_width=int(self.display_height * 0.6))
        if logo:
            logo_x = self.display_width - logo.width - 2
            logo_y = (self.display_height - logo.height) // 2
            img.paste(logo, (logo_x, logo_y), logo)

        return img

    # ─── Qualifying Results Card ───────────────────────────────────────

    def render_qualifying_entry(self, entry: Dict,
                                 session_label: str = "Q3") -> Image.Image:
        """Render a single qualifying result entry."""
        session_key = session_label.lower()
        return self._render_driver_row(
            entry,
            time_key=session_key,
            gap_key=f"{session_key}_gap",
            show_eliminated=True)

    def render_qualifying_header(self,
                                  session_label: str = "Q3",
                                  race_name: str = "") -> Image.Image:
        """Render a qualifying session header card."""
        img = Image.new("RGBA",
                        (self.display_width, self.display_height),
                        (0, 0, 0, 255))
        draw = ImageDraw.Draw(img)

        # F1 logo
        f1_logo = self.logo_loader.get_f1_logo(
            max_height=int(self.display_height * 0.4),
            max_width=int(self.display_width * 0.15))
        if f1_logo:
            img.paste(f1_logo, (2, 2), f1_logo)

        # Header text
        header_x = (f1_logo.width + 6) if f1_logo else 4
        header_text = f"QUALIFYING - {session_label}"
        self._draw_text_outlined(draw, (header_x, 2), header_text,
                                self.fonts["header"],
                                fill=F1_RED)

        # Race name below
        if race_name:
            short_name = race_name.replace("Grand Prix", "GP")
            name_y = 2 + self._get_text_height(
                draw, header_text, self.fonts["header"]) + 2
            if name_y + 6 < self.display_height:
                self._draw_text_outlined(draw, (4, name_y), short_name,
                                        self.fonts["small"],
                                        fill=(180, 180, 180))

        return img

    # ─── Practice Results Card ─────────────────────────────────────────

    def render_practice_entry(self, entry: Dict) -> Image.Image:
        """Render a practice session result entry."""
        return self._render_driver_row(
            entry, time_key="best_lap", gap_key="gap")

    def render_practice_header(self, session_name: str = "FP3",
                                circuit: str = "") -> Image.Image:
        """Render a practice session header card."""
        img = Image.new("RGBA",
                        (self.display_width, self.display_height),
                        (0, 0, 0, 255))
        draw = ImageDraw.Draw(img)

        f1_logo = self.logo_loader.get_f1_logo(
            max_height=int(self.display_height * 0.4),
            max_width=int(self.display_width * 0.15))
        if f1_logo:
            img.paste(f1_logo, (2, 2), f1_logo)

        header_x = (f1_logo.width + 6) if f1_logo else 4
        header_text = f"FREE PRACTICE {session_name[-1]}" if len(session_name) == 3 else session_name
        self._draw_text_outlined(draw, (header_x, 2), header_text,
                                self.fonts["header"],
                                fill=F1_RED)

        if circuit:
            name_y = 2 + self._get_text_height(
                draw, header_text, self.fonts["header"]) + 2
            if name_y + 6 < self.display_height:
                self._draw_text_outlined(draw, (4, name_y), circuit,
                                        self.fonts["small"],
                                        fill=(180, 180, 180))

        return img

    # ─── Sprint Results Card ───────────────────────────────────────────

    def render_sprint_entry(self, entry: Dict) -> Image.Image:
        """Render a sprint result entry."""
        return self._render_driver_row(entry, time_key="time")

    def render_sprint_header(self, race_name: str = "") -> Image.Image:
        """Render a sprint race header card."""
        img = Image.new("RGBA",
                        (self.display_width, self.display_height),
                        (0, 0, 0, 255))
        draw = ImageDraw.Draw(img)

        f1_logo = self.logo_loader.get_f1_logo(
            max_height=int(self.display_height * 0.4),
            max_width=int(self.display_width * 0.15))
        if f1_logo:
            img.paste(f1_logo, (2, 2), f1_logo)

        header_x = (f1_logo.width + 6) if f1_logo else 4
        self._draw_text_outlined(draw, (header_x, 2), "SPRINT",
                                self.fonts["header"],
                                fill=F1_RED)

        if race_name:
            short_name = race_name.replace("Grand Prix", "GP")
            name_y = 2 + self._get_text_height(
                draw, "SPRINT", self.fonts["header"]) + 2
            if name_y + 6 < self.display_height:
                self._draw_text_outlined(draw, (4, name_y), short_name,
                                        self.fonts["small"],
                                        fill=(180, 180, 180))

        return img

    # ─── Upcoming Race Card ────────────────────────────────────────────

    def render_upcoming_race(self, race: Dict) -> Image.Image:
        """
        Render the upcoming race card with countdown and circuit outline.

        Layout: [F1 logo] [GP name]      [circuit outline]
                [circuit name]            [circuit outline]
                [city, country]           [circuit outline]
                [countdown timer]
        """
        img = Image.new("RGBA",
                        (self.display_width, self.display_height),
                        (0, 0, 0, 255))
        draw = ImageDraw.Draw(img)

        # Load circuit image and calculate text area width
        circuit_img = self.logo_loader.get_circuit_image(
            circuit_name=race.get("circuit_name", ""),
            city=race.get("city", ""),
            max_height=self.display_height - 4,
            max_width=int(self.display_width * 0.35))

        if circuit_img:
            # Place circuit image on the right side, vertically centered
            circuit_x = self.display_width - circuit_img.width - 2
            circuit_y = (self.display_height - circuit_img.height) // 2
            img.paste(circuit_img, (circuit_x, circuit_y), circuit_img)
            text_max_x = circuit_x - 2
        else:
            text_max_x = self.display_width - 2

        y_pos = 1

        # F1 logo + GP name on top line
        f1_logo = self.logo_loader.get_f1_logo(
            max_height=int(self.display_height * 0.3),
            max_width=int(self.display_width * 0.12))
        if f1_logo:
            img.paste(f1_logo, (1, y_pos), f1_logo)
            name_x = f1_logo.width + 3
        else:
            name_x = 2

        # GP name
        race_name = race.get("short_name", race.get("name", ""))
        short_name = race_name.replace("Grand Prix", "GP")
        short_name = self._truncate_text(
            draw, short_name, self.fonts["header"], text_max_x - name_x)
        self._draw_text_outlined(draw, (name_x, y_pos), short_name,
                                self.fonts["header"],
                                fill=F1_RED)

        header_h = max(
            f1_logo.height if f1_logo else 0,
            self._get_text_height(draw, short_name, self.fonts["header"]))
        y_pos += header_h + 2

        # Circuit name
        circuit = race.get("circuit_name", "")
        if circuit and y_pos + 6 < self.display_height - 10:
            circuit = self._truncate_text(
                draw, circuit, self.fonts["small"], text_max_x - 2)
            self._draw_text_outlined(draw, (2, y_pos), circuit,
                                    self.fonts["small"],
                                    fill=(180, 180, 180))
            y_pos += self._get_text_height(draw, circuit,
                                          self.fonts["small"]) + 1

        # City, Country
        location_parts = []
        if race.get("city"):
            location_parts.append(race["city"])
        if race.get("country"):
            location_parts.append(race["country"])
        location = ", ".join(location_parts)

        if location and y_pos + 6 < self.display_height - 8:
            location = self._truncate_text(
                draw, location, self.fonts["small"], text_max_x - 2)
            self._draw_text_outlined(draw, (2, y_pos), location,
                                    self.fonts["small"],
                                    fill=(150, 150, 150))
            y_pos += self._get_text_height(draw, location,
                                          self.fonts["small"]) + 1

        # Countdown timer (bottom)
        countdown_seconds = race.get("countdown_seconds")
        if countdown_seconds is not None and countdown_seconds >= 0:
            countdown_y = self.display_height - self._get_text_height(
                draw, "0D", self.fonts["detail"]) - 2

            if countdown_seconds < 3600:
                # Less than 1 hour - show session type
                session_type = race.get("next_session_type", "RACE")
                label_map = {
                    "FP1": "FP1 SOON", "FP2": "FP2 SOON", "FP3": "FP3 SOON",
                    "Qual": "QUALIFYING", "Race": "RACE DAY",
                    "SS": "SPRINT QUALI", "SR": "SPRINT RACE",
                }
                label = label_map.get(session_type, "RACE DAY")
                label = self._truncate_text(
                    draw, label, self.fonts["detail"], text_max_x - 2)

                # Pulsing effect: vary brightness
                pulse = int(180 + 75 * math.sin(time.time() * 3))
                pulse = max(150, min(255, pulse))
                self._draw_text_outlined(draw, (2, countdown_y), label,
                                        self.fonts["detail"],
                                        fill=(pulse, pulse, 0))
            else:
                # Show countdown
                days = int(countdown_seconds // 86400)
                hours = int((countdown_seconds % 86400) // 3600)
                minutes = int((countdown_seconds % 3600) // 60)

                if days > 0:
                    countdown_text = f"{days}D {hours}H {minutes}M"
                else:
                    countdown_text = f"{hours}H {minutes}M"

                # Date prefix
                race_date = race.get("date", "")
                date_prefix = ""
                if race_date:
                    try:
                        dt = self._to_local_dt(race_date)
                        date_prefix = dt.strftime("%b %d").upper() + "  "
                    except (ValueError, TypeError):
                        pass

                full_text = date_prefix + countdown_text
                full_text = self._truncate_text(
                    draw, full_text, self.fonts["detail"], text_max_x - 2)
                self._draw_text_outlined(draw, (2, countdown_y), full_text,
                                        self.fonts["detail"],
                                        fill=(0, 255, 0))

        return img

    # ─── Calendar Entry Card ──────────────────────────────────────────

    def render_calendar_entry(self, entry: Dict) -> Image.Image:
        """
        Render a calendar session entry.

        Layout: [date] [day] [session type] [GP short name]
        """
        img = Image.new("RGBA",
                        (self.display_width, self.display_height),
                        (0, 0, 0, 255))
        draw = ImageDraw.Draw(img)

        # Parse date
        date_str = entry.get("date", "")
        date_display = ""
        day_display = ""
        if date_str:
            try:
                dt = self._to_local_dt(date_str)
                date_display = dt.strftime("%b %d").upper()
                day_display = dt.strftime("%a").upper()
            except (ValueError, TypeError):
                pass

        x_offset = 2

        # Date
        if date_display:
            self._draw_text_outlined(draw, (x_offset, 2), date_display,
                                    self.fonts["position"],
                                    fill=(255, 255, 255))
            date_width = self._get_text_width(draw, date_display,
                                             self.fonts["position"])
            x_offset += date_width + 4

        # Day of week
        if day_display:
            self._draw_text_outlined(draw, (x_offset, 2), day_display,
                                    self.fonts["detail"],
                                    fill=(150, 150, 150))
            day_width = self._get_text_width(draw, day_display,
                                            self.fonts["detail"])
            x_offset += day_width + 4

        # Session type with color coding
        session_type = entry.get("session_type", "")
        session_colors = {
            "Race": (255, 0, 0),
            "Qual": (255, 200, 0),
            "FP1": (100, 200, 100),
            "FP2": (100, 200, 100),
            "FP3": (100, 200, 100),
            "SS": (255, 150, 0),
            "SR": (255, 100, 0),
        }
        session_color = session_colors.get(session_type, (200, 200, 200))

        session_label = {
            "FP1": "FP1", "FP2": "FP2", "FP3": "FP3",
            "Qual": "QUALI", "Race": "RACE",
            "SS": "S.QUALI", "SR": "SPRINT",
        }.get(session_type, session_type)

        self._draw_text_outlined(draw, (x_offset, 2), session_label,
                                self.fonts["detail"],
                                fill=session_color)
        session_width = self._get_text_width(draw, session_label,
                                            self.fonts["detail"])
        x_offset += session_width + 4

        # Event name
        event_name = entry.get("event_name", "")
        short_event = event_name.replace("Grand Prix", "GP")
        max_name_width = self.display_width - x_offset - 2
        short_event = self._truncate_text(
            draw, short_event, self.fonts["small"], max_name_width)

        self._draw_text_outlined(draw, (x_offset, 2), short_event,
                                self.fonts["small"],
                                fill=(180, 180, 180))

        # Time on second line
        time_str = entry.get("status_detail", "")
        if time_str and self.display_height > 16:
            time_y = 2 + self._get_text_height(
                draw, date_display or "A", self.fonts["position"]) + 2
            if time_y + 6 < self.display_height:
                self._draw_text_outlined(draw, (2, time_y), time_str,
                                        self.fonts["small"],
                                        fill=(120, 120, 120))

        return img

    # ─── Section Separator ─────────────────────────────────────────────

    def render_f1_separator(self) -> Image.Image:
        """Render an F1 logo separator card for vegas scroll."""
        img = Image.new("RGBA",
                        (self.display_height, self.display_height),
                        (0, 0, 0, 255))

        logo = self.logo_loader.get_f1_logo(
            max_height=int(self.display_height * 0.6),
            max_width=int(self.display_height * 0.6))
        if logo:
            x = (self.display_height - logo.width) // 2
            y = (self.display_height - logo.height) // 2
            img.paste(logo, (x, y), logo)

        return img
