"""
Display rendering for Flight Tracker display modes.

Two flight detail layouts (auto-selected by canvas width):
  - ``flight_detail_wide``:      widescreen (≥ threshold), 3-zone horizontal
  - ``flight_detail_condensed``: condensed (< threshold), 2-column

Plus the area-mode card renderer for cycling through nearby aircraft.
"""

import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from units import format_altitude, format_speed, format_track, format_vrate, format_distance, null_safe
from airline_sprites import get_sprite_for_aircraft

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Font loading
# ---------------------------------------------------------------------------

_FONT_DIR_CANDIDATES = [
    os.path.join(os.path.dirname(__file__), "assets", "fonts"),
    "assets/fonts",
    "../assets/fonts",
    "../../assets/fonts",
]


def _find_font(filename: str) -> Optional[str]:
    for base in _FONT_DIR_CANDIDATES:
        p = os.path.join(base, filename)
        if os.path.exists(p):
            return p
    return None


def _ttf(filename: str, size: int) -> ImageFont.FreeTypeFont:
    p = _find_font(filename)
    if p:
        return ImageFont.truetype(p, size)
    return ImageFont.load_default()


# ---------------------------------------------------------------------------
# Airline logo loader
# ---------------------------------------------------------------------------

_LOGO_DIR_CANDIDATES = [
    os.path.join(os.path.dirname(__file__), "assets", "airline_logos"),
    "assets/airline_logos",
    "../assets/airline_logos",
    "../../assets/airline_logos",
]
_logo_cache: Dict[str, Optional[Image.Image]] = {}


def _load_airline_logo(icao: str, max_h: int) -> Optional[Image.Image]:
    """Load and scale an airline logo PNG. Returns RGBA image or None."""
    key = f"{icao}_{max_h}"
    if key in _logo_cache:
        return _logo_cache[key]

    for base in _LOGO_DIR_CANDIDATES:
        path = os.path.join(base, f"{icao.upper()}.png")
        if os.path.exists(path):
            try:
                logo = Image.open(path).convert("RGBA")
                bbox = logo.getbbox()
                if bbox:
                    logo = logo.crop(bbox)
                # Allow wider logos — cap height to max_h, scale width proportionally
                logo.thumbnail((max_h * 2, max_h), Image.Resampling.LANCZOS)
                _logo_cache[key] = logo
                logger.info(f"[Flight Tracker] Loaded airline logo: {icao} ({logo.size[0]}x{logo.size[1]})")
                return logo
            except Exception as e:
                logger.warning(f"[Flight Tracker] Failed to load logo {path}: {e}")
                break

    logger.debug(f"[Flight Tracker] No logo found for {icao}")
    _logo_cache[key] = None
    return None


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

class FlightRenderer:
    """Renders flight display modes with dynamic layout scaling."""

    # Default widescreen width threshold
    WIDE_THRESHOLD = 256

    def __init__(self, display_manager: Any, fonts: Dict[str, Any], config: Dict[str, Any]):
        self.dm = display_manager
        self._mgr_fonts = fonts

        # Unit config — granular per-metric keys with legacy fallback
        legacy = config.get("units", "imperial")
        self.alt_unit = config.get("altitude_unit", "m" if legacy == "metric" else "ft")
        self.spd_unit = config.get("speed_unit", "kmh" if legacy == "metric" else "kn")
        self.trk_fmt = config.get("track_format", "deg")
        self.vr_unit = config.get("vr_unit", "ms" if legacy == "metric" else "fpm")
        self.units_legacy = legacy  # kept for area cards / distance

        # Colors
        self.header_color = tuple(config.get("header_color", [255, 255, 255]))
        self.airport_color = tuple(config.get("airport_color", [0, 120, 255]))
        self.metric_color = tuple(config.get("metric_color", [255, 255, 255]))
        self.error_color = tuple(config.get("error_color", [255, 0, 0]))
        self.dim_color = (120, 120, 120)
        self.route_color = (150, 220, 255)

        self.show_banner = config.get("show_banner", False)
        self.show_aircraft_icon = config.get("show_aircraft_icon", False)
        self.scroll_speed = config.get("scroll_speed", 2)

        self._banner_shown = False
        self._banner_start = 0.0

        # Layout override
        self._layout_override = config.get("layout", "") or ""
        try:
            self._wide_threshold = int(config.get("widescreen_threshold", self.WIDE_THRESHOLD))
        except (TypeError, ValueError):
            self._wide_threshold = self.WIDE_THRESHOLD

        # Optional font size overrides (0 = auto)
        fonts_cfg = config.get("fonts") or {}
        def _opt_int(v):
            try:
                n = int(v)
                return n if n > 0 else None
            except (TypeError, ValueError):
                return None
        self._font_override_large = _opt_int(fonts_cfg.get("large_size"))
        self._font_override_medium = _opt_int(fonts_cfg.get("medium_size"))
        self._font_override_small = _opt_int(fonts_cfg.get("small_size"))

        # Load fonts scaled to display
        self._load_fonts()

    @property
    def width(self) -> int:
        return self.dm.matrix.width

    @property
    def height(self) -> int:
        return self.dm.matrix.height

    def _load_fonts(self) -> None:
        """Load three named font tiers scaled to display size (overridable via config.fonts).

        Tier picks consider BOTH height and width — the widescreen layout at 64px
        height on a 128-wide panel can't afford a 16pt font_large, because the
        info zone is only 50% of the width (64px, ~4 chars at 16pt).
        """
        h = self.height
        w = self.width
        if h >= 64 and w >= 192:
            large_sz, medium_sz, small_sz = 16, 10, 8
            small_face = "PressStart2P-Regular.ttf"
            self.sprite_scale = 2
        elif h >= 48:
            large_sz, medium_sz, small_sz = 10, 8, 6
            small_face = "4x6-font.ttf"
            self.sprite_scale = 1 if w < 192 else 2
        else:
            # Tiny display (64x32 or similar)
            large_sz, medium_sz, small_sz = 8, 8, 6
            small_face = "4x6-font.ttf"
            self.sprite_scale = 1

        if self._font_override_large is not None:
            large_sz = self._font_override_large
        if self._font_override_medium is not None:
            medium_sz = self._font_override_medium
        if self._font_override_small is not None:
            small_sz = self._font_override_small

        self.font_large = _ttf("PressStart2P-Regular.ttf", large_sz)
        self.font_medium = _ttf("PressStart2P-Regular.ttf", medium_sz)
        # Small tier: 4x6 below 8px, PressStart2P at 8+
        if small_sz >= 8:
            self.font_small = _ttf("PressStart2P-Regular.ttf", small_sz)
        else:
            self.font_small = _ttf(small_face, small_sz)

    # --- Row fitting helper ---

    def _row_plan(self, rows, avail_h, gap=0):
        """Given an ordered list of (key, font) tuples, return the prefix whose
        summed line heights (+ gap between rows) fits in avail_h. Rows are assumed
        to be ordered by priority (highest first). Always returns at least the
        first row so the layout is never blank.

        Returns: (selected_rows, total_height)
        """
        if not rows:
            return [], 0
        selected = []
        total = 0
        for i, (_, font) in enumerate(rows):
            lh = self._lh(font)
            candidate_total = total + lh + (gap if selected else 0)
            if candidate_total > avail_h and selected:
                break
            selected.append(rows[i])
            total = candidate_total
        return selected, total

    # --- Drawing primitives ---

    def _tw(self, draw: ImageDraw.Draw, text: str, font) -> int:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0]

    def _fh(self, font) -> int:
        try:
            a, d = font.getmetrics()
            return a + d
        except Exception:
            return 8

    def _lh(self, font) -> int:
        return self._fh(font) + 2

    def _draw(self, draw, text, pos, font, color=(255, 255, 255)):
        draw.text(pos, text, font=font, fill=color)

    def _draw_outlined(self, draw, text, pos, font, color=(255, 255, 255)):
        x, y = pos
        for dx, dy in [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]:
            draw.text((x + dx, y + dy), text, font=font, fill=(0, 0, 0))
        draw.text(pos, text, font=font, fill=color)

    def _draw_right(self, draw, text, y, font, color, margin=2):
        w = self._tw(draw, text, font)
        draw.text((self.width - w - margin, y), text, font=font, fill=color)

    def _draw_centered(self, draw, text, y, font, color, zone_x=0, zone_w=None):
        zw = zone_w or self.width
        tw = self._tw(draw, text, font)
        draw.text((zone_x + (zw - tw) // 2, y), text, font=font, fill=color)

    def _draw_sep(self, draw, y, color=(40, 40, 40)):
        draw.line([(0, y), (self.width, y)], fill=color, width=1)

    def _truncate(self, draw, text: str, font, max_w: int) -> str:
        """Truncate text with ellipsis if it exceeds max_w pixels."""
        if self._tw(draw, text, font) <= max_w:
            return text
        while len(text) > 1 and self._tw(draw, text + "..", font) > max_w:
            text = text[:-1]
        return text + ".."

    def _draw_sprite(self, draw, x, y, airline_icao="", callsign="", fallback_color=(200, 200, 200)):
        pixels = get_sprite_for_aircraft(airline_icao, "", callsign)
        if not pixels:
            return 0
        scale = self.sprite_scale
        pixel_set = set((p[0], p[1]) for p in pixels)
        for px, py, r, g, b in pixels:
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nx, ny = px + dx, py + dy
                if (nx, ny) not in pixel_set and 0 <= nx < 8 and 0 <= ny < 8:
                    for sx in range(scale):
                        for sy in range(scale):
                            draw.point((x + nx * scale + sx, y + ny * scale + sy), fill=(0, 0, 0))
        for px, py, r, g, b in pixels:
            for sx in range(scale):
                for sy in range(scale):
                    draw.point((x + px * scale + sx, y + py * scale + sy), fill=(r, g, b))
        return 8 * scale + 3

    # --- Metric formatting helpers (use per-metric units) ---

    def _fmt_alt(self, val):
        return format_altitude(val, unit=self.alt_unit)

    def _fmt_spd(self, val):
        return format_speed(val, unit=self.spd_unit)

    def _fmt_trk(self, val):
        return format_track(val, fmt=self.trk_fmt)

    def _fmt_vr(self, val, arrows=True):
        return format_vrate(val, unit=self.vr_unit, use_arrows=arrows)

    # --- Banner ---

    def render_banner(self, text="FLIGHTS"):
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
        self._draw_centered(draw, text, (self.height - self._fh(self.font_large)) // 2,
                            self.font_large, self.header_color)
        self.dm.image = img.copy()
        self.dm.update_display()
        return True

    def reset_banner(self):
        self._banner_shown = False
        self._banner_start = 0.0

    # =====================================================================
    # Flight Detail — layout auto-selection
    # =====================================================================

    def _pick_layout(self) -> str:
        if self._layout_override in ("flight_detail_wide", "flight_detail_condensed"):
            return self._layout_override
        return "flight_detail_wide" if self.width >= self._wide_threshold else "flight_detail_condensed"

    def render_flight_tracking(self, tracked_flight: Any) -> None:
        """Render a tracked flight using the appropriate layout."""
        layout = self._pick_layout()
        if layout == "flight_detail_wide":
            self._render_wide(tracked_flight)
        else:
            self._render_condensed(tracked_flight)

    # =====================================================================
    # Layout 1: Widescreen — flight_detail_wide
    # =====================================================================

    def _render_wide(self, tf) -> None:
        w, h = self.width, self.height
        img = Image.new("RGB", (w, h), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        if tf is None:
            self._draw_centered(draw, "No Flight Data", h // 2 - 4, self.font_medium, self.error_color)
            self.dm.image = img.copy()
            self.dm.update_display()
            return

        ac = tf.aircraft_state or {}
        _get = (lambda k, d=None: ac.get(k, d)) if isinstance(ac, dict) else (lambda k, d=None: getattr(ac, k, d))

        # Zone widths (20% / 50% / 30%)
        logo_w = w * 20 // 100
        info_w = w * 50 // 100
        metric_w = w - logo_w - info_w
        info_x = logo_w
        metric_x = logo_w + info_w

        # --- LOGO ZONE ---
        airline_icao = self._resolve_airline_icao(tf, _get)
        logo = _load_airline_logo(airline_icao, h - 4) if airline_icao else None
        if logo:
            lx = (logo_w - logo.width) // 2
            ly = (h - logo.height) // 2
            img.paste(logo, (max(0, lx), max(0, ly)), logo)
        elif airline_icao:
            # Fallback: render first 3 chars centered
            abbr = (airline_icao[:3] or tf.identifier[:3]).upper()
            self._draw_centered(draw, abbr, (h - self._fh(self.font_large)) // 2,
                                self.font_large, self.header_color, zone_x=0, zone_w=logo_w)
        else:
            # Draw sprite as fallback
            sx = (logo_w - 8 * self.sprite_scale) // 2
            sy = (h - 8 * self.sprite_scale) // 2
            self._draw_sprite(draw, max(0, sx), max(0, sy),
                              airline_icao=airline_icao, callsign=tf.identifier)

        # --- INFO ZONE ---
        airline_name = _get("airline_name", "") or tf.identifier
        origin = tf.origin or "---"
        dest = tf.destination or "---"
        atype = _get("aircraft_type", "") or "---"

        # Get full airport names from static data
        origin_full = ""
        dest_full = ""
        try:
            from static_data import airports
            ap = airports.by_iata(origin) or airports.by_icao(origin)
            if ap:
                origin_full = ap.get("name", "")
            ap = airports.by_iata(dest) or airports.by_icao(dest)
            if ap:
                dest_full = ap.get("name", "")
        except Exception:
            pass

        # Build priority-ordered info rows; drop lowest priority if they don't fit.
        route = f"{origin}-{dest}" if origin != "---" and dest != "---" else "---"
        name_text = self._truncate(draw, null_safe(airline_name), self.font_large, info_w - 4)
        route_text = self._truncate(draw, route, self.font_large, info_w - 4)
        type_text = self._truncate(draw, null_safe(atype, default="---"), self.font_large, info_w - 4)

        info_candidates = [
            ("name", self.font_large, name_text, self.header_color),
            ("route", self.font_large, route_text, self.header_color),
            ("atype", self.font_large, type_text, self.header_color),
        ]
        if origin_full:
            info_candidates.append(("origin_full", self.font_small,
                                    self._truncate(draw, origin_full, self.font_small, info_w - 4),
                                    self.airport_color))
        if dest_full:
            info_candidates.append(("dest_full", self.font_small,
                                    self._truncate(draw, dest_full, self.font_small, info_w - 4),
                                    self.airport_color))

        plan_input = [(key, font) for (key, font, _text, _color) in info_candidates]
        selected, rows_h = self._row_plan(plan_input, h - 2)
        selected_keys = {k for (k, _f) in selected}

        y = max(1, (h - rows_h) // 2)
        for key, font, text, color in info_candidates:
            if key not in selected_keys:
                continue
            self._draw(draw, text, (info_x + 2, y), font, color)
            y += self._lh(font)

        # --- METRICS ZONE ---
        alt_v = self._fmt_alt(_get("altitude"))
        spd_v = self._fmt_spd(_get("speed"))
        trk_v = self._fmt_trk(_get("heading"))
        vr_v = self._fmt_vr(_get("vertical_rate"), arrows=False)

        all_metrics = [
            f"Alt: {alt_v}",
            f"Spd: {spd_v}",
            f"Trk: {trk_v}",
            f"Vr: {vr_v}",
        ]
        # Fit as many metric rows as the height allows (min 1)
        metric_lh = self._lh(self.font_small)
        max_metric_rows = max(1, min(len(all_metrics), h // max(1, metric_lh)))
        metric_rows = all_metrics[:max_metric_rows]
        row_h = h // len(metric_rows)
        for i, text in enumerate(metric_rows):
            my = i * row_h + (row_h - self._fh(self.font_small)) // 2
            tw = self._tw(draw, text, self.font_small)
            mx = metric_x + metric_w - tw - 2
            self._draw(draw, text, (max(metric_x, mx), my), self.font_small, self.metric_color)

        self.dm.image = img.copy()
        self.dm.update_display()

    # =====================================================================
    # Layout 2: Condensed — flight_detail_condensed
    # =====================================================================

    def _resolve_airline_icao(self, tf, _get) -> str:
        """Try to determine airline ICAO from aircraft_state or callsign prefix."""
        icao = _get("airline_icao", "") or ""
        if icao:
            return icao
        # Try callsign prefix (first 3 chars) — many airline callsigns use ICAO prefix
        ident = tf.identifier or ""
        if len(ident) >= 3 and ident[:3].isalpha():
            return ident[:3].upper()
        return ""

    def _render_condensed(self, tf) -> None:
        w, h = self.width, self.height
        img = Image.new("RGB", (w, h), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        if tf is None:
            self._draw_centered(draw, "No Flight Data", h // 2 - 4, self.font_medium, self.error_color)
            self.dm.image = img.copy()
            self.dm.update_display()
            return

        ac = tf.aircraft_state or {}
        _get = (lambda k, d=None: ac.get(k, d)) if isinstance(ac, dict) else (lambda k, d=None: getattr(ac, k, d))

        # Column widths (40% logo / 60% text)
        logo_w = w * 40 // 100
        text_x = logo_w
        text_w = w - logo_w

        # --- LOGO COL ---
        airline_icao = self._resolve_airline_icao(tf, _get)
        logo = _load_airline_logo(airline_icao, h - 4) if airline_icao else None
        if logo:
            lx = (logo_w - logo.width) // 2
            ly = (h - logo.height) // 2
            img.paste(logo, (max(0, lx), max(0, ly)), logo)
        elif airline_icao:
            abbr = (airline_icao[:3] or tf.identifier[:3]).upper()
            self._draw_centered(draw, abbr, (h - self._fh(self.font_large)) // 2,
                                self.font_large, self.header_color, zone_x=0, zone_w=logo_w)
        else:
            sx = (logo_w - 8 * self.sprite_scale) // 2
            sy = (h - 8 * self.sprite_scale) // 2
            self._draw_sprite(draw, max(0, sx), max(0, sy),
                              airline_icao=airline_icao, callsign=tf.identifier)

        # --- TEXT COL ---
        origin = tf.origin or "---"
        dest = tf.destination or "---"
        atype = _get("aircraft_type", "") or "---"
        callsign = tf.identifier

        # Priority-ordered rows; drop lowest priority if they don't fit.
        route = f"{origin}-{dest}" if origin != "---" and dest != "---" else "---"
        atype_short = atype[:8] if atype != "---" else "---"
        alt_v = self._fmt_alt(_get("altitude"))
        spd_v = self._fmt_spd(_get("speed"))
        trk_v = self._fmt_trk(_get("heading"))
        vr_v = self._fmt_vr(_get("vertical_rate"), arrows=False)

        candidates = [
            ("callsign", self.font_medium, callsign, self.header_color),
            ("route", self.font_medium, route, self.header_color),
            ("alt_spd", self.font_small, f"Alt:{alt_v},Spd:{spd_v}", self.metric_color),
            ("atype", self.font_medium, atype_short, self.header_color),
            ("trk_vr", self.font_small, f"Trk:{trk_v},Vr:{vr_v}", self.metric_color),
        ]
        plan_input = [(k, f) for (k, f, _t, _c) in candidates]
        selected, rows_h = self._row_plan(plan_input, h)
        selected_keys = {k for (k, _f) in selected}

        y = max(0, (h - rows_h) // 2)
        for key, font, text, color in candidates:
            if key not in selected_keys:
                continue
            self._draw(draw, text, (text_x + 2, y), font, color)
            y += self._lh(font)

        self.dm.image = img.copy()
        self.dm.update_display()

    # =====================================================================
    # Area Mode — one aircraft per full display (unchanged)
    # =====================================================================

    def _render_area_card_to_image(self, aircraft, index=0, total_count=1, card_width=None):
        w = card_width or self.width
        h = self.height
        img = Image.new("RGB", (w, h), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        if not aircraft:
            self._draw_centered(draw, "No Aircraft", h // 2 - 4, self.font_medium, self.dim_color)
            return img

        callsign = aircraft.get("callsign", "---")
        alt = self._fmt_alt(aircraft.get("altitude"))
        spd = self._fmt_spd(aircraft.get("speed"))
        trk = self._fmt_trk(aircraft.get("heading"))
        dist = format_distance(aircraft.get("distance_miles"), self.units_legacy)
        origin = aircraft.get("origin", "")
        destination = aircraft.get("destination", "")
        atype = aircraft.get("aircraft_type", "")
        color = tuple(aircraft.get("color", self.header_color))
        airline_icao = aircraft.get("airline_icao", "")

        # --- Left zone: airline logo (large, vertically centered) ---
        logo_w = 2  # left margin when no logo
        logo = _load_airline_logo(airline_icao, h - 8) if airline_icao else None
        if logo:
            lx = 2
            ly = (h - logo.height) // 2
            img.paste(logo, (lx, ly), logo)
            logo_w = lx + logo.width + 4
            # Subtle separator line
            draw.line([(logo_w - 2, 1), (logo_w - 2, h - 2)], fill=(40, 40, 40))

        rx = logo_w + 1  # right zone text start

        # Adaptive top rows: callsign (P1), route/atype (P2), distance (P3). Bottom
        # metrics row is always drawn bottom-anchored and must not collide.
        top_candidates = [
            ("callsign", self.font_medium),
            ("route", self.font_medium),
            ("dist", self.font_medium),
        ]
        bottom_reserved = self._fh(self.font_small) + 3  # bottom row + margin
        top_avail = h - 2 - bottom_reserved
        selected, _ = self._row_plan(top_candidates, top_avail, gap=0)
        selected_keys = {k for (k, _f) in selected}

        y = 2
        if "callsign" in selected_keys:
            self._draw(draw, callsign, (rx, y), self.font_medium, color)
            counter = f"{index + 1}/{total_count}"
            cw = self._tw(draw, counter, self.font_small)
            self._draw(draw, counter, (w - cw - 2, y + 1), self.font_small, (80, 80, 80))
            y += self._lh(self.font_medium)

        if "route" in selected_keys:
            if origin and destination:
                route = f"{origin} > {destination}"
                self._draw(draw, route, (rx, y), self.font_medium, self.route_color)
                if atype and atype != "Unknown":
                    rw_used = self._tw(draw, route, self.font_medium) + 8
                    if rx + rw_used + self._tw(draw, atype, self.font_small) < w - 2:
                        self._draw(draw, atype, (rx + rw_used, y + 2), self.font_small, (100, 100, 100))
            elif atype and atype != "Unknown":
                self._draw(draw, atype, (rx, y), self.font_medium, (100, 100, 100))
            y += self._lh(self.font_medium)

        if "dist" in selected_keys:
            self._draw(draw, "DST", (rx, y), self.font_small, (255, 255, 255))
            self._draw(draw, dist, (rx + self._tw(draw, "DST ", self.font_small), y), self.font_medium, (220, 170, 0))

        # --- Bottom row: Labeled metrics in small font (clip to available width) ---
        y = h - self._fh(self.font_small) - 2
        label_color = (255, 255, 255)
        value_color = (180, 180, 180)
        x = rx
        for label, value in [("ALT", alt), ("SPD", spd), ("HDG", trk)]:
            needed = self._tw(draw, label, self.font_small) + 1 + self._tw(draw, value, self.font_small) + 3
            if x + needed > w:
                break  # don't clip mid-metric
            self._draw(draw, label, (x, y), self.font_small, label_color)
            x += self._tw(draw, label, self.font_small) + 1
            self._draw(draw, value, (x, y), self.font_small, value_color)
            x += self._tw(draw, value, self.font_small) + 3

        return img

    def render_area_card(self, aircraft, index=0, total_count=1):
        img = self._render_area_card_to_image(aircraft, index, total_count)
        self.dm.image = img.copy()
        self.dm.update_display()

    def render_area_card_image(self, aircraft, index=0, total_count=1):
        return self._render_area_card_to_image(aircraft, index, total_count)

    # =====================================================================
    # Stats Cards
    # =====================================================================

    def render_stat_card(self, title, title_color, aircraft, stat_label, stat_value,
                         origin="", destination="", aircraft_type="", airline_icao="",
                         record_time=""):
        """Render a stats card (CLOSEST/FASTEST/HIGHEST/records) and push to display."""
        img = self._render_stat_card_to_image(
            title, title_color, aircraft, stat_label, stat_value,
            origin, destination, aircraft_type, airline_icao, record_time)
        self.dm.image = img.copy()
        self.dm.update_display()

    def _render_stat_card_to_image(self, title, title_color, aircraft, stat_label, stat_value,
                                    origin="", destination="", aircraft_type="", airline_icao="",
                                    record_time=""):
        w, h = self.width, self.height
        img = Image.new("RGB", (w, h), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        callsign = aircraft.get("callsign", "---") if aircraft else "---"
        alt = self._fmt_alt(aircraft.get("altitude")) if aircraft else ""
        spd = self._fmt_spd(aircraft.get("speed")) if aircraft else ""
        trk = self._fmt_trk(aircraft.get("heading")) if aircraft else ""
        dist = format_distance(aircraft.get("distance_miles"), self.units_legacy) if aircraft else ""
        color = tuple(aircraft.get("color", self.header_color)) if aircraft else self.header_color

        # --- Left zone: airline logo ---
        logo_w = 2
        logo = _load_airline_logo(airline_icao, h - 8) if airline_icao else None
        if logo:
            img.paste(logo, (2, (h - logo.height) // 2), logo)
            logo_w = 2 + logo.width + 4
            draw.line([(logo_w - 2, 1), (logo_w - 2, h - 2)], fill=(40, 40, 40))

        rx = logo_w + 1

        # Adaptive top rows: title+callsign (P1), hero stat (P1), route/atype (P3).
        # Bottom metrics row is always drawn bottom-anchored.
        top_candidates = [
            ("title", self.font_medium),
            ("hero", self.font_medium),
            ("route", self.font_medium),
        ]
        bottom_reserved = self._fh(self.font_small) + 3
        top_avail = h - 2 - bottom_reserved
        selected, _ = self._row_plan(top_candidates, top_avail, gap=0)
        selected_keys = {k for (k, _f) in selected}

        y = 2
        if "title" in selected_keys:
            self._draw(draw, title, (rx, y), self.font_medium, title_color)
            cs_x = rx + self._tw(draw, title, self.font_medium) + 6
            self._draw(draw, callsign, (cs_x, y), self.font_medium, color)
            y += self._lh(self.font_medium)

        if "hero" in selected_keys:
            self._draw(draw, stat_label, (rx, y), self.font_small, (255, 255, 255))
            lbl_w = self._tw(draw, stat_label + " ", self.font_small)
            self._draw(draw, stat_value, (rx + lbl_w, y), self.font_medium, title_color)
            y += self._lh(self.font_medium)

        if "route" in selected_keys:
            if origin and destination and origin != "Unknown" and destination != "Unknown":
                self._draw(draw, f"{origin} > {destination}", (rx, y), self.font_medium, self.route_color)
                if aircraft_type and aircraft_type != "Unknown":
                    rt_w = self._tw(draw, f"{origin} > {destination}", self.font_medium) + 8
                    if rx + rt_w + self._tw(draw, aircraft_type, self.font_small) < w - 2:
                        self._draw(draw, aircraft_type, (rx + rt_w, y + 2), self.font_small, (130, 130, 130))
            elif aircraft_type and aircraft_type != "Unknown":
                self._draw(draw, aircraft_type, (rx, y), self.font_medium, (130, 130, 130))

        # --- Bottom row: Complementary metrics (exclude the hero stat) ---
        y = h - self._fh(self.font_small) - 2
        label_color = (255, 255, 255)
        value_color = (180, 180, 180)
        # Build list of metrics that aren't already shown as the hero
        parts = []
        if stat_label != "ALT" and alt:
            parts.append(("ALT", alt))
        if stat_label != "SPD" and spd:
            parts.append(("SPD", spd))
        if stat_label != "DST" and dist:
            parts.append(("DST", dist))
        if stat_label != "HDG" and trk:
            parts.append(("HDG", trk))
        if record_time:
            parts.append(("REC", record_time))
        x = rx
        for label, value in parts:
            needed = self._tw(draw, label, self.font_small) + 1 + self._tw(draw, value, self.font_small) + 3
            if x + needed > w:
                break
            self._draw(draw, label, (x, y), self.font_small, label_color)
            x += self._tw(draw, label, self.font_small) + 1
            self._draw(draw, value, (x, y), self.font_small, value_color)
            x += self._tw(draw, value, self.font_small) + 3

        return img

    # =====================================================================
    # Error / No Data
    # =====================================================================

    def render_error(self, message="NO DATA"):
        img = Image.new("RGB", (self.width, self.height), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        self._draw_centered(draw, message, (self.height - self._fh(self.font_large)) // 2,
                            self.font_large, self.error_color)
        self.dm.image = img.copy()
        self.dm.update_display()
