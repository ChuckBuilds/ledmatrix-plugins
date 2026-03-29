"""
Display rendering for Flight Tracker display modes.

Layout is dynamic — adapts to any display size from 64×32 to 192×96+.
Font sizes, sprite scaling, and element spacing all scale with the display.
"""

import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from units import (
    format_altitude,
    format_speed,
    format_track,
    format_vrate,
    format_distance,
    null_safe,
)
from airline_sprites import get_sprite_for_aircraft

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Font loading helpers — match sports plugin patterns
# ---------------------------------------------------------------------------

_FONT_DIR_CANDIDATES = [
    "assets/fonts",
    "../assets/fonts",
    "../../assets/fonts",
]


def _find_font(filename: str) -> Optional[str]:
    """Search for a font file in standard LEDMatrix paths."""
    for base in _FONT_DIR_CANDIDATES:
        path = os.path.join(base, filename)
        if os.path.exists(path):
            return path
    return None


def _load_truetype(filename: str, size: int) -> ImageFont.FreeTypeFont:
    """Load a TrueType font, falling back to PIL default."""
    path = _find_font(filename)
    if path:
        return ImageFont.truetype(path, size)
    return ImageFont.load_default()


class FlightRenderer:
    """Renders flight display modes with dynamic layout scaling."""

    def __init__(self, display_manager: Any, fonts: Dict[str, Any], config: Dict[str, Any]):
        self.dm = display_manager
        self._manager_fonts = fonts  # keep original fonts as fallback
        self.units = config.get("units", "imperial")
        self.header_color = tuple(config.get("header_color", [255, 200, 0]))
        self.metric_color = tuple(config.get("metric_color", [255, 255, 255]))
        self.route_color = (150, 220, 255)
        self.dim_color = (120, 120, 120)
        self.error_color = tuple(config.get("error_color", [255, 0, 0]))
        self.show_banner = config.get("show_banner", False)
        self.show_aircraft_icon = config.get("show_aircraft_icon", False)
        self.scroll_speed = config.get("scroll_speed", 2)
        self._banner_shown = False
        self._banner_start = 0.0

        # Load display-size-appropriate fonts
        self._load_scaled_fonts()

    @property
    def width(self) -> int:
        return self.dm.matrix.width

    @property
    def height(self) -> int:
        return self.dm.matrix.height

    def _load_scaled_fonts(self) -> None:
        """Load fonts scaled to the actual display size.

        Follows the sports plugin pattern: PressStart2P for titles,
        4x6-font for data.  Sizes increase with display height.
        """
        h = self.height
        if h >= 64:
            # Large display (192×96+)
            self.font_title = _load_truetype("PressStart2P-Regular.ttf", 12)
            self.font_data = _load_truetype("PressStart2P-Regular.ttf", 8)
            self.font_small = _load_truetype("4x6-font.ttf", 8)
            self.sprite_scale = 2  # 16×16 sprites
        elif h >= 48:
            # Medium display (192×48, 128×48)
            # PressStart2P is a true pixel font — no anti-aliasing artifacts
            self.font_title = _load_truetype("PressStart2P-Regular.ttf", 10)
            self.font_data = _load_truetype("PressStart2P-Regular.ttf", 8)
            self.font_small = _load_truetype("PressStart2P-Regular.ttf", 6)
            self.sprite_scale = 1  # 8×8 sprites (fits within title line)
        elif h >= 32:
            # Standard display (128×32, 64×32)
            self.font_title = _load_truetype("PressStart2P-Regular.ttf", 8)
            self.font_data = _load_truetype("4x6-font.ttf", 8)
            self.font_small = _load_truetype("4x6-font.ttf", 6)
            self.sprite_scale = 1  # 8×8 sprites
        else:
            # Tiny display
            self.font_title = _load_truetype("4x6-font.ttf", 6)
            self.font_data = _load_truetype("4x6-font.ttf", 6)
            self.font_small = _load_truetype("4x6-font.ttf", 6)
            self.sprite_scale = 1

    # --- Drawing helpers ---

    def _draw(
        self,
        draw: ImageDraw.Draw,
        text: str,
        pos: Tuple[int, int],
        font: Any,
        color: Tuple[int, int, int] = (255, 255, 255),
    ) -> int:
        """Draw text and return its pixel width."""
        draw.text(pos, text, font=font, fill=color)
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0]

    def _draw_outlined(
        self,
        draw: ImageDraw.Draw,
        text: str,
        pos: Tuple[int, int],
        font: Any,
        color: Tuple[int, int, int] = (255, 255, 255),
        outline: Tuple[int, int, int] = (0, 0, 0),
    ) -> int:
        """Draw text with 1px black outline. Returns text width."""
        x, y = pos
        for dx, dy in [(-1, -1), (-1, 0), (-1, 1), (0, -1),
                        (0, 1), (1, -1), (1, 0), (1, 1)]:
            draw.text((x + dx, y + dy), text, font=font, fill=outline)
        draw.text(pos, text, font=font, fill=color)
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0]

    def _text_w(self, draw: ImageDraw.Draw, text: str, font: Any) -> int:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0]

    def _font_h(self, font: Any) -> int:
        try:
            if hasattr(font, "getmetrics"):
                a, d = font.getmetrics()
                return a + d
            if hasattr(font, "size"):
                return font.size
        except Exception:
            pass
        return 8

    def _line_h(self, font: Any) -> int:
        """Line height with padding."""
        return self._font_h(font) + 2

    def _draw_sprite(
        self,
        draw: ImageDraw.Draw,
        x: int,
        y: int,
        airline_icao: str = "",
        callsign: str = "",
        fallback_color: Tuple[int, int, int] = (200, 200, 200),
    ) -> int:
        """Draw airline sprite scaled to display size. Returns width used."""
        pixels = get_sprite_for_aircraft(airline_icao, "", callsign)
        if not pixels:
            return 0

        scale = self.sprite_scale
        size = 8 * scale  # total sprite pixel size

        # Draw scaled sprite
        pixel_set = set((p[0], p[1]) for p in pixels)

        # Black outline for visibility
        for px, py, r, g, b in pixels:
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nx, ny = px + dx, py + dy
                if (nx, ny) not in pixel_set and 0 <= nx < 8 and 0 <= ny < 8:
                    for sx in range(scale):
                        for sy in range(scale):
                            draw.point((x + nx * scale + sx, y + ny * scale + sy), fill=(0, 0, 0))

        # Colored pixels
        for px, py, r, g, b in pixels:
            for sx in range(scale):
                for sy in range(scale):
                    draw.point((x + px * scale + sx, y + py * scale + sy), fill=(r, g, b))

        return size + 3  # sprite width + gap

    def _right_text(self, draw: ImageDraw.Draw, text: str, y: int,
                    font: Any, color: Tuple[int, int, int]) -> None:
        """Draw right-aligned text."""
        w = self._text_w(draw, text, font)
        draw.text((self.width - w - 2, y), text, font=font, fill=color)

    def _center_text(self, draw: ImageDraw.Draw, text: str, y: int,
                     font: Any, color: Tuple[int, int, int]) -> None:
        """Draw horizontally centered text."""
        w = self._text_w(draw, text, font)
        draw.text(((self.width - w) // 2, y), text, font=font, fill=color)

    # --- Horizontal separator line ---

    def _draw_sep(self, draw: ImageDraw.Draw, y: int,
                  color: Tuple[int, int, int] = (40, 40, 40)) -> None:
        """Draw a subtle horizontal separator."""
        draw.line([(0, y), (self.width, y)], fill=color, width=1)

    # --- Title Banner ---

    def render_banner(self, text: str = "FLIGHTS") -> bool:
        if not self.show_banner:
            return False
        now = time.time()
        if not self._banner_shown:
            self._banner_shown = True
            self._banner_start = now
        if now - self._banner_start > 2.0:
            return False

        img = Image.new("RGB", (self.width, self.height), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        self._center_text(draw, text, (self.height - self._font_h(self.font_title)) // 2,
                          self.font_title, self.header_color)
        self.dm.image = img.copy()
        self.dm.update_display()
        return True

    def reset_banner(self) -> None:
        self._banner_shown = False
        self._banner_start = 0.0

    # =====================================================================
    # Area Mode — one aircraft per full display
    # =====================================================================

    def _render_area_card_to_image(
        self,
        aircraft: Dict,
        index: int = 0,
        total_count: int = 1,
        card_width: Optional[int] = None,
    ) -> Image.Image:
        """Render a single aircraft card. Core method used by both display and Vegas.

        Layout (192×48 example):
        ┌──────────────────────────────────────────────┐
        │ [sprite] SWA3708 Southwest            1/5    │  title font, outlined
        │ ─────────────────────────────────────────     │  separator
        │  ALB → TPA    B38M                 5.2mi     │  data font, route color
        │  Alt:4.0K  Spd:223kt  090°  ↑1200           │  data font, metric color
        └──────────────────────────────────────────────┘
        """
        w = card_width or self.width
        h = self.height
        img = Image.new("RGB", (w, h), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        if not aircraft:
            self._center_text(draw, "No Aircraft", h // 2 - 4, self.font_data, self.dim_color)
            return img

        # Extract data
        callsign = aircraft.get("callsign", "---")
        alt = format_altitude(aircraft.get("altitude"), self.units)
        spd = format_speed(aircraft.get("speed"), self.units)
        trk = format_track(aircraft.get("heading"))
        vr = format_vrate(aircraft.get("vertical_rate"), self.units)
        dist = format_distance(aircraft.get("distance_miles"), self.units)
        origin = aircraft.get("origin", "")
        destination = aircraft.get("destination", "")
        airline = aircraft.get("airline_name", "")
        atype = aircraft.get("aircraft_type", "")
        color = tuple(aircraft.get("color", self.header_color))

        # Anchor arrows
        prefix = ""
        if aircraft.get("_anchor_arrival"):
            prefix = "\u2192 "
        elif aircraft.get("_anchor_departure"):
            prefix = "\u2190 "

        title_lh = self._line_h(self.font_title)
        data_lh = self._line_h(self.font_data)

        # Calculate vertical layout: spread content across display
        # Always reserve 2 data rows (dist/route + metrics)
        content_h = title_lh + 2 + data_lh * 2
        y = max(0, (h - content_h) // 2)

        # === Row 1: [sprite] callsign + airline name ===
        text_x = 2
        if self.show_aircraft_icon:
            sprite_y = y + max(0, (title_lh - 8 * self.sprite_scale) // 2)
            sprite_w = self._draw_sprite(
                draw, 2, sprite_y,
                airline_icao=aircraft.get("airline_icao", ""),
                callsign=callsign,
                fallback_color=color,
            )
            text_x = 2 + sprite_w

        # Callsign + airline
        cs_str = f"{prefix}{callsign}"
        if airline:
            cs_str += f" {airline}"
        self._draw_outlined(draw, cs_str, (text_x, y), self.font_title, color)

        # Counter top-right
        counter = f"{index + 1}/{total_count}"
        self._right_text(draw, counter, y + (title_lh - self._font_h(self.font_small)) // 2,
                         self.font_small, self.dim_color)
        y += title_lh

        # === Separator ===
        self._draw_sep(draw, y)
        y += 2

        # === Row 2: Route (origin → dest) + aircraft type + distance ===
        if origin and destination:
            route_str = f"{origin} \u2192 {destination}"
            self._draw(draw, route_str, (2, y), self.font_data, self.route_color)

            # Aircraft type in center-ish
            if atype and atype != "Unknown":
                type_x = max(self._text_w(draw, route_str, self.font_data) + 12, w // 3)
                if type_x + self._text_w(draw, atype, self.font_small) < w - 40:
                    self._draw(draw, atype, (type_x, y + 1), self.font_small, self.dim_color)

            # Distance right-aligned
            self._right_text(draw, dist, y, self.font_data, (200, 160, 0))
            y += data_lh
        else:
            # No route — show distance + type on one line
            if atype and atype != "Unknown":
                self._draw(draw, atype, (2, y), self.font_data, self.dim_color)
            self._right_text(draw, dist, y, self.font_data, (200, 160, 0))
            y += data_lh

        # === Row 3: Metrics — compact, no labels, evenly spaced ===
        if y + data_lh <= h:
            vr_color = ((0, 255, 100) if vr.startswith("\u2191") else
                        (255, 80, 80) if vr.startswith("\u2193") else self.dim_color)
            parts = [
                (alt, self.metric_color),
                (spd, self.metric_color),
                (trk, self.dim_color),
                (vr, vr_color),
            ]
            # Calculate total width and distribute evenly
            total_tw = sum(self._text_w(draw, t, self.font_data) for t, _ in parts)
            gap = max(3, (w - 4 - total_tw) // max(1, len(parts) - 1))
            x = 2
            for text, c in parts:
                tw = self._draw(draw, text, (x, y), self.font_data, c)
                x += tw + gap

        return img

    def render_area_card(self, aircraft: Dict, index: int = 0, total_count: int = 1) -> None:
        """Render a single aircraft card to the display."""
        img = self._render_area_card_to_image(aircraft, index, total_count)
        self.dm.image = img.copy()
        self.dm.update_display()

    def render_area_card_image(self, aircraft: Dict, index: int = 0, total_count: int = 1) -> Image.Image:
        """Render a single aircraft card and return the PIL Image (for Vegas scroll)."""
        return self._render_area_card_to_image(aircraft, index, total_count)

    # =====================================================================
    # Flight Tracking Mode
    # =====================================================================

    def render_flight_tracking(self, tracked_flight: Any) -> None:
        """Render a tracked flight detail view using the full display.

        Layout (192×48 example):
        ┌──────────────────────────────────────────────┐
        │ [sprite] AA123  American Airlines            │  title, outlined
        │ ─────────────────────────────────────────     │  separator
        │  TPA → ORD          AIRBORNE       42%       │  route + status
        │  Alt:38.6K  Spd:480kt  090°  ↑1200          │  metrics
        └──────────────────────────────────────────────┘
        """
        img = Image.new("RGB", (self.width, self.height), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        if tracked_flight is None:
            self._center_text(draw, "No Flight Data", self.height // 2 - 4,
                              self.font_data, self.error_color)
            self.dm.image = img.copy()
            self.dm.update_display()
            return

        ident = tracked_flight.identifier
        status = tracked_flight.status
        origin = tracked_flight.origin or "---"
        dest = tracked_flight.destination or "---"
        dep_time = tracked_flight.departure_time or ""
        arr_time = tracked_flight.arrival_time or ""
        progress = tracked_flight.progress_pct
        city = tracked_flight.city_overfly or ""
        ac_state = tracked_flight.aircraft_state

        title_lh = self._line_h(self.font_title)
        data_lh = self._line_h(self.font_data)

        # Vertically center content
        content_h = title_lh + 1 + data_lh * 2
        y = max(1, (self.height - content_h) // 2)

        # === Row 1: [sprite] Flight ID + airline name ===
        text_x = 2
        airline_icao = ""
        if ac_state:
            airline_icao = ac_state.get("airline_icao", "") if isinstance(ac_state, dict) else getattr(ac_state, "airline_icao", "")
        airline_name = ""
        if ac_state:
            airline_name = ac_state.get("airline_name", "") if isinstance(ac_state, dict) else getattr(ac_state, "airline_name", "")

        if self.show_aircraft_icon:
            sprite_y = y + max(0, (title_lh - 8 * self.sprite_scale) // 2)
            sw = self._draw_sprite(draw, 2, sprite_y, airline_icao=airline_icao, callsign=ident)
            text_x = 2 + sw

        title_str = ident
        if airline_name:
            title_str += f"  {airline_name}"
        self._draw_outlined(draw, title_str, (text_x, y), self.font_title, self.header_color)
        y += title_lh

        # Separator
        self._draw_sep(draw, y)
        y += 2

        # === Row 2: Route + status ===
        if status == "AIRBORNE":
            if origin != "---" and dest != "---":
                self._draw(draw, f"{origin} \u2192 {dest}", (2, y), self.font_data, self.route_color)
            # Status right side
            status_text = "AIRBORNE"
            if progress is not None:
                status_text = f"{int(progress)}%"
            elif city:
                status_text = f"over {city}"
            self._right_text(draw, status_text, y, self.font_data, (0, 255, 100))
            y += data_lh

            # === Row 3: ADS-B metrics ===
            if ac_state and y + data_lh <= self.height:
                _get = (lambda k: ac_state.get(k)) if isinstance(ac_state, dict) else (lambda k: getattr(ac_state, k, None))
                alt = format_altitude(_get("altitude"), self.units)
                spd = format_speed(_get("speed"), self.units)
                trk = format_track(_get("heading"))
                vr_val = format_vrate(_get("vertical_rate"), self.units)

                x = 2
                gap = 6
                for text, c in [
                    (f"Alt:{alt}", self.metric_color),
                    (f"Spd:{spd}", self.metric_color),
                    (trk, self.metric_color),
                    (vr_val, (0, 255, 100) if vr_val.startswith("\u2191") else
                             (255, 80, 80) if vr_val.startswith("\u2193") else self.dim_color),
                ]:
                    tw = self._draw(draw, text, (x, y), self.font_data, c)
                    x += tw + gap

        elif status == "SCHEDULED":
            sched = f"SCHED  DEP {dep_time}" if dep_time else "SCHEDULED"
            if origin != "---" and dest != "---":
                self._draw(draw, f"{origin} \u2192 {dest}", (2, y), self.font_data, self.route_color)
                self._right_text(draw, sched, y, self.font_data, (255, 200, 0))
            else:
                self._center_text(draw, sched, y, self.font_data, (255, 200, 0))

        elif status == "LANDED":
            landed = f"LANDED  ARR {arr_time}" if arr_time else "LANDED"
            if origin != "---" and dest != "---":
                self._draw(draw, f"{origin} \u2192 {dest}", (2, y), self.font_data, self.route_color)
                self._right_text(draw, landed, y, self.font_data, (0, 255, 100))
            else:
                self._center_text(draw, landed, y, self.font_data, (0, 255, 100))

        else:
            self._center_text(draw, "UNKNOWN", y, self.font_data, self.dim_color)

        self.dm.image = img.copy()
        self.dm.update_display()

    # =====================================================================
    # Error / No Data
    # =====================================================================

    def render_error(self, message: str = "NO DATA") -> None:
        img = Image.new("RGB", (self.width, self.height), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        self._center_text(draw, message, (self.height - self._font_h(self.font_title)) // 2,
                          self.font_title, self.error_color)
        self.dm.image = img.copy()
        self.dm.update_display()
