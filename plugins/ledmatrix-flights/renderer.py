"""
Display rendering for new Flight Tracker display modes.

Contains renderers for:
  - Area mode (FR-01): multi-aircraft list with FlightWall-style metrics
  - Flight tracking mode (FR-02): tracked flight detail with route + ADS-B
  - Shared drawing helpers

The existing display modes (map, overhead, stats) remain in manager.py
for backward compatibility and will be migrated here incrementally.
"""

import logging
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
from airline_sprites import get_sprite_for_aircraft, get_sprite_key, get_sprite

logger = logging.getLogger(__name__)


class FlightRenderer:
    """Renders new display modes on the LED matrix."""

    def __init__(self, display_manager: Any, fonts: Dict[str, Any], config: Dict[str, Any]):
        self.dm = display_manager
        self.fonts = fonts
        self.units = config.get("units", "imperial")
        self.header_color = tuple(config.get("header_color", [255, 200, 0]))
        self.metric_color = tuple(config.get("metric_color", [255, 255, 255]))
        self.error_color = tuple(config.get("error_color", [255, 0, 0]))
        self.show_banner = config.get("show_banner", False)
        self.show_aircraft_icon = config.get("show_aircraft_icon", False)
        self.scroll_speed = config.get("scroll_speed", 2)
        self._banner_shown = False
        self._banner_start = 0.0

    @property
    def width(self) -> int:
        return self.dm.matrix.width

    @property
    def height(self) -> int:
        return self.dm.matrix.height

    # --- Drawing helpers ---

    def _draw_text(
        self,
        draw: ImageDraw.Draw,
        text: str,
        pos: Tuple[int, int],
        font: Any,
        color: Tuple[int, int, int] = (255, 255, 255),
    ) -> None:
        """Draw text without outline (pixel-perfect for data fonts)."""
        draw.text(pos, text, font=font, fill=color)

    def _draw_text_outlined(
        self,
        draw: ImageDraw.Draw,
        text: str,
        pos: Tuple[int, int],
        font: Any,
        color: Tuple[int, int, int] = (255, 255, 255),
        outline: Tuple[int, int, int] = (0, 0, 0),
    ) -> None:
        """Draw text with a 1px black outline for readability on busy backgrounds."""
        x, y = pos
        for dx, dy in [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]:
            draw.text((x + dx, y + dy), text, font=font, fill=outline)
        draw.text(pos, text, font=font, fill=color)

    def _text_width(self, draw: ImageDraw.Draw, text: str, font: Any) -> int:
        """Get the pixel width of rendered text."""
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0]

    def _font_height(self, font: Any) -> int:
        """Get the pixel height of a font."""
        try:
            if hasattr(font, 'getmetrics'):
                ascent, descent = font.getmetrics()
                return ascent + descent
            if hasattr(font, 'size'):
                return font.size
        except Exception:
            pass
        return 8

    def _line_spacing(self, font: Any, factor: float = 1.2) -> int:
        """Calculate line spacing with padding factor."""
        return int(self._font_height(font) * factor)

    def _draw_airplane_icon(
        self,
        draw: ImageDraw.Draw,
        x: int,
        y: int,
        color: Tuple[int, int, int] = (200, 200, 200),
    ) -> None:
        """Draw a simple 5x5 airplane icon with black outline."""
        pixels = [
            (2, 0),
            (2, 1),
            (0, 2), (1, 2), (2, 2), (3, 2), (4, 2),
            (2, 3),
            (1, 4), (2, 4), (3, 4),
        ]
        pixel_set = set(pixels)
        outline = set()
        for px, py in pixels:
            for dx in [-1, 0, 1]:
                for dy in [-1, 0, 1]:
                    if dx == 0 and dy == 0:
                        continue
                    n = (px + dx, py + dy)
                    if n not in pixel_set:
                        outline.add(n)
        for px, py in outline:
            draw.point((x + px, y + py), fill=(0, 0, 0))
        for px, py in pixels:
            draw.point((x + px, y + py), fill=color)

    def _draw_airline_sprite(
        self,
        draw: ImageDraw.Draw,
        x: int,
        y: int,
        airline_icao: str = "",
        airline_iata: str = "",
        callsign: str = "",
        fallback_color: Tuple[int, int, int] = (200, 200, 200),
    ) -> int:
        """Draw an 8×8 airline logo sprite at (x, y).

        Falls back to a generic plane icon if no airline match is found.
        Returns the width of the drawn sprite (for layout positioning).
        """
        pixels = get_sprite_for_aircraft(airline_icao, airline_iata, callsign)
        if not pixels:
            # Ultimate fallback: draw simple airplane icon
            self._draw_airplane_icon(draw, x, y, fallback_color)
            return 5  # airplane icon is 5px wide

        # Draw sprite pixels (each is (px, py, r, g, b))
        pixel_set = set((p[0], p[1]) for p in pixels)

        # Optional 1px black outline for visibility on busy backgrounds
        for px, py, r, g, b in pixels:
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nx, ny = px + dx, py + dy
                if (nx, ny) not in pixel_set and 0 <= nx < 8 and 0 <= ny < 8:
                    draw.point((x + nx, y + ny), fill=(0, 0, 0))

        # Draw colored pixels on top
        for px, py, r, g, b in pixels:
            draw.point((x + px, y + py), fill=(r, g, b))

        return 8  # sprite is 8px wide

    # --- Title Banner ---

    def render_banner(self, text: str = "FLIGHTS") -> bool:
        """Show a title banner for 2 seconds. Returns True if still showing."""
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
        font = self.fonts.get("title_medium", self.fonts.get("medium"))
        tw = self._text_width(draw, text, font)
        x = max(0, (self.width - tw) // 2)
        y = max(0, (self.height - self._font_height(font)) // 2)
        self._draw_text_outlined(draw, text, (x, y), font, color=self.header_color)
        self.dm.image = img.copy()
        self.dm.update_display()
        return True

    def reset_banner(self) -> None:
        """Reset banner state for next display slot."""
        self._banner_shown = False
        self._banner_start = 0.0

    # --- Area Mode (FR-01) ---

    def render_area_card(
        self,
        aircraft: Dict,
        index: int = 0,
        total_count: int = 1,
    ) -> None:
        """Render a single aircraft using the full display — FlightWall style.

        Each aircraft gets the entire screen. The manager cycles through
        aircraft one at a time.

        Args:
            aircraft: Single aircraft dict.
            index: Current aircraft index (0-based, for counter display).
            total_count: Total aircraft in range (for N/M counter).
        """
        img = Image.new("RGB", (self.width, self.height), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        font_title = self.fonts.get("data_medium", self.fonts.get("medium"))
        font_data = self.fonts.get("data_small", self.fonts.get("small"))
        title_h = self._line_spacing(font_title, 1.2)
        data_h = self._line_spacing(font_data, 1.2)

        if not aircraft:
            self._draw_text(draw, "No Aircraft", (2, self.height // 2 - 4), font_data, (200, 200, 200))
            self.dm.image = img.copy()
            self.dm.update_display()
            return

        callsign = aircraft.get("callsign", "---")
        alt = format_altitude(aircraft.get("altitude"), self.units)
        spd = format_speed(aircraft.get("speed"), self.units)
        trk = format_track(aircraft.get("heading"))
        vr = format_vrate(aircraft.get("vertical_rate"), self.units)
        dist = format_distance(aircraft.get("distance_miles"), self.units)
        origin = aircraft.get("origin", "")
        destination = aircraft.get("destination", "")
        airline_name = aircraft.get("airline_name", "")
        aircraft_type = aircraft.get("aircraft_type", "")
        color = tuple(aircraft.get("color", self.header_color))

        # Anchor airport arrows
        prefix = ""
        if aircraft.get("_anchor_arrival"):
            prefix = "\u2192 "  # → (arrival)
        elif aircraft.get("_anchor_departure"):
            prefix = "\u2190 "  # ← (departure)

        y = 1
        text_x = 1

        # --- Line 1: [sprite] callsign + airline name ---
        if self.show_aircraft_icon:
            sprite_w = self._draw_airline_sprite(
                draw, 1, y,
                airline_icao=aircraft.get("airline_icao", ""),
                callsign=callsign,
                fallback_color=color,
            )
            text_x = 1 + sprite_w + 2

        callsign_str = f"{prefix}{callsign}"
        if airline_name:
            callsign_str += f" {airline_name}"
        self._draw_text_outlined(draw, callsign_str, (text_x, y), font_title, color)

        # Counter on the right: "3/7"
        counter = f"{index + 1}/{total_count}"
        cw = self._text_width(draw, counter, font_data)
        self._draw_text(draw, counter, (self.width - cw - 1, y), font_data, (100, 100, 100))
        y += title_h

        # --- Line 2: Route (if available) or aircraft type ---
        if origin and destination:
            route_str = f"{origin}\u2192{destination}"
            if aircraft_type and aircraft_type != "Unknown":
                route_str += f"  {aircraft_type}"
            self._draw_text(draw, route_str, (1, y), font_data, (180, 220, 255))
            y += data_h
        elif aircraft_type and aircraft_type != "Unknown":
            self._draw_text(draw, aircraft_type, (1, y), font_data, (180, 180, 180))
            y += data_h

        # --- Line 3: Metrics — Alt  Spd  Trk  Vr ---
        metrics = f"Alt:{alt}  Spd:{spd}  Trk:{trk}  Vr:{vr}"
        self._draw_text(draw, metrics, (1, y), font_data, self.metric_color)
        y += data_h

        # --- Line 4: Distance ---
        if y + data_h <= self.height:
            self._draw_text(draw, f"Dist:{dist}", (1, y), font_data, (150, 150, 150))

        self.dm.image = img.copy()
        self.dm.update_display()

    def render_area_card_image(self, aircraft: Dict, index: int = 0, total_count: int = 1) -> Image.Image:
        """Render a single aircraft card and return the PIL Image (for Vegas scroll)."""
        img = Image.new("RGB", (self.width, self.height), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        font_title = self.fonts.get("data_medium", self.fonts.get("medium"))
        font_data = self.fonts.get("data_small", self.fonts.get("small"))
        title_h = self._line_spacing(font_title, 1.2)
        data_h = self._line_spacing(font_data, 1.2)

        if not aircraft:
            self._draw_text(draw, "No Aircraft", (2, self.height // 2 - 4), font_data, (200, 200, 200))
            return img

        callsign = aircraft.get("callsign", "---")
        alt = format_altitude(aircraft.get("altitude"), self.units)
        spd = format_speed(aircraft.get("speed"), self.units)
        trk = format_track(aircraft.get("heading"))
        vr = format_vrate(aircraft.get("vertical_rate"), self.units)
        dist = format_distance(aircraft.get("distance_miles"), self.units)
        color = tuple(aircraft.get("color", self.header_color))
        origin = aircraft.get("origin", "")
        destination = aircraft.get("destination", "")
        airline_name = aircraft.get("airline_name", "")

        prefix = ""
        if aircraft.get("_anchor_arrival"):
            prefix = "\u2192 "
        elif aircraft.get("_anchor_departure"):
            prefix = "\u2190 "

        y = 1
        text_x = 1

        if self.show_aircraft_icon:
            sprite_w = self._draw_airline_sprite(
                draw, 1, y,
                airline_icao=aircraft.get("airline_icao", ""),
                callsign=callsign,
                fallback_color=color,
            )
            text_x = 1 + sprite_w + 2

        callsign_str = f"{prefix}{callsign}"
        if airline_name:
            callsign_str += f" {airline_name}"
        self._draw_text_outlined(draw, callsign_str, (text_x, y), font_title, color)

        counter = f"{index + 1}/{total_count}"
        cw = self._text_width(draw, counter, font_data)
        self._draw_text(draw, counter, (self.width - cw - 1, y), font_data, (100, 100, 100))
        y += title_h

        if origin and destination:
            self._draw_text(draw, f"{origin}\u2192{destination}", (1, y), font_data, (180, 220, 255))
            y += data_h

        metrics = f"Alt:{alt}  Spd:{spd}  Trk:{trk}  Vr:{vr}"
        self._draw_text(draw, metrics, (1, y), font_data, self.metric_color)
        y += data_h

        if y + data_h <= self.height:
            self._draw_text(draw, f"Dist:{dist}", (1, y), font_data, (150, 150, 150))

        return img

    # --- Flight Tracking Mode (FR-02) ---

    def render_flight_tracking(self, tracked_flight: Any) -> None:
        """Render a tracked flight detail view.

        Args:
            tracked_flight: A TrackedFlight dataclass instance (from data_model.py).
        """
        img = Image.new("RGB", (self.width, self.height), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        font_title = self.fonts.get("data_medium", self.fonts.get("medium"))
        font_data = self.fonts.get("data_small", self.fonts.get("small"))
        title_h = self._line_spacing(font_title, 1.1)
        data_h = self._line_spacing(font_data, 1.1)

        if tracked_flight is None:
            self._draw_text(draw, "No Flight Data", (2, self.height // 2 - 4), font_data, self.error_color)
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

        y = 1

        # Line 1: [Airline sprite] Flight ID + Route
        text_x = 1
        if self.show_aircraft_icon and ac_state:
            sprite_w = self._draw_airline_sprite(
                draw, 1, y,
                airline_icao=ac_state.get("airline_icao", "") if isinstance(ac_state, dict) else getattr(ac_state, "airline_icao", ""),
                callsign=ident,
            )
            text_x = 1 + sprite_w + 2

        route_str = f"{ident} {origin}\u2192{dest}" if origin != "---" and dest != "---" else ident
        self._draw_text_outlined(draw, route_str, (text_x, y), font_title, self.header_color)
        y += title_h

        if status == "AIRBORNE" and ac_state:
            # Line 2: Live ADS-B metrics
            alt = format_altitude(ac_state.altitude if hasattr(ac_state, 'altitude') else ac_state.get("altitude"), self.units)
            spd = format_speed(ac_state.speed if hasattr(ac_state, 'speed') else ac_state.get("speed"), self.units)
            trk = format_track(ac_state.heading if hasattr(ac_state, 'heading') else ac_state.get("heading"))
            vr = format_vrate(ac_state.vertical_rate if hasattr(ac_state, 'vertical_rate') else ac_state.get("vertical_rate"), self.units)

            metrics = f"{alt} {spd} {trk} {vr}"
            self._draw_text(draw, metrics, (1, y), font_data, self.metric_color)
            y += data_h

            # Line 3: Progress or city overfly
            if progress is not None:
                prog_text = f"{int(progress)}%"
                if city:
                    prog_text += f" over {city}"
                self._draw_text(draw, prog_text, (1, y), font_data, (150, 255, 150))
            elif city:
                self._draw_text(draw, f"Over {city}", (1, y), font_data, (150, 255, 150))

        elif status == "SCHEDULED":
            # Pre-departure
            sched_text = f"SCHED DEP {dep_time}" if dep_time else "SCHEDULED"
            self._draw_text(draw, sched_text, (1, y), font_data, (255, 200, 0))

        elif status == "LANDED":
            # Post-flight
            landed_text = f"LANDED ARR {arr_time}" if arr_time else "LANDED"
            self._draw_text(draw, landed_text, (1, y), font_data, (0, 255, 100))

        else:
            # Unknown
            self._draw_text(draw, "UNKNOWN", (1, y), font_data, (180, 180, 180))

        self.dm.image = img.copy()
        self.dm.update_display()

    # --- Error / No Data display ---

    def render_error(self, message: str = "NO DATA") -> None:
        """Render an error or no-data state."""
        img = Image.new("RGB", (self.width, self.height), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        font = self.fonts.get("data_medium", self.fonts.get("medium"))
        tw = self._text_width(draw, message, font)
        x = max(0, (self.width - tw) // 2)
        y = max(0, (self.height - self._font_height(font)) // 2)
        self._draw_text(draw, message, (x, y), font, self.error_color)
        self.dm.image = img.copy()
        self.dm.update_display()
