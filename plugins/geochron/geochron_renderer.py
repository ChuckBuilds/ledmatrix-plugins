"""Layout, compositing, and overlay drawing for the Geochron world clock.

This module is independent of BasePlugin/display_manager so it can be used
both by manager.py (live plugin) and render_preview.py (standalone preview
generator). Text drawing is left to the caller via a small callback so each
caller can use its own font-loading strategy.
"""

import math

import numpy as np
from PIL import Image

import worldmap

# Warm highlight blended into the twilight band, peaking at d=0.5.
TWILIGHT_GLOW_COLOR = (255, 140, 40)
TWILIGHT_GLOW_STRENGTH = 0.18

# Blend strength toward night_tint_color on the night side.
NIGHT_TINT_STRENGTH = 0.40

# Text row height in pixels (matches a 6px font + 1px line gap).
ROW_H = 7


def _layout(dw, dh, map_center_lon=0.0):
    """Compute the responsive layout for a dw x dh display.

    Returns a dict describing the map placement (in display pixels) and the
    lon/lat range of the world the map should show, plus any sidebar info.
    """
    aspect = dw / dh

    if aspect >= 3.0:
        mode = "wide_sidebar"
        sidebar_w = max(32, int(dw * 0.22))
        map_w = dw - sidebar_w
        map_h = dh
        # Asymmetric latitude band, biased toward the northern hemisphere:
        # +70 covers Moscow (55.75) plus the rest of Canada, Alaska,
        # Scandinavia, and Iceland; -50 still covers Sydney (-33.87) and Rio
        # (-22.91) with margin while cropping out the mostly-empty Southern
        # Ocean and Antarctica. The resulting 120-degree span also closely
        # matches typical wide_sidebar map aspect ratios, reducing vertical
        # stretching from the crop->resize step.
        lat_min = -50.0
        lat_max = 70.0
        lon_extent = 360.0
        lon_center = 0.0
    elif aspect >= 1.5:
        mode = "near_bleed"
        sidebar_w = 0
        map_w, map_h = dw, dh
        lat_min = -90.0
        lat_max = 90.0
        lon_extent = 360.0
        lon_center = 0.0
    else:
        mode = "square_tall"
        sidebar_w = 0
        map_w, map_h = dw, dh
        lat_min = -90.0
        lat_max = 90.0
        lon_extent = max(90.0, min(360.0, 180.0 * aspect))
        lon_center = map_center_lon

    return {
        "mode": mode,
        "dw": dw,
        "dh": dh,
        "map_x": 0,
        "map_y": 0,
        "map_w": map_w,
        "map_h": map_h,
        "sidebar_w": sidebar_w,
        "sidebar_x": map_w if sidebar_w else None,
        "lon_min": lon_center - lon_extent / 2.0,
        "lon_max": lon_center + lon_extent / 2.0,
        "lat_min": lat_min,
        "lat_max": lat_max,
    }


def lonlat_to_px(lon, lat, layout):
    """Project a (lon, lat) in degrees to a (x, y) display pixel.

    Mirrors the crop window used by render_map_image. Returns (x, y, visible)
    where visible is False if the point falls outside the cropped/shown
    region (e.g. on the far side of the world on a square/tall panel).
    """
    L = layout
    lon_span = L["lon_max"] - L["lon_min"]
    lat_span = L["lat_max"] - L["lat_min"]

    if lon_span >= 360.0:
        lon_n = ((lon + 180.0) % 360.0) - 180.0
    else:
        lon_n = ((lon - L["lon_min"]) % 360.0) + L["lon_min"]

    fx = (lon_n - L["lon_min"]) / lon_span
    fy = (L["lat_max"] - lat) / lat_span
    x = L["map_x"] + fx * L["map_w"]
    y = L["map_y"] + fy * L["map_h"]
    visible = 0.0 <= fx <= 1.0 and 0.0 <= fy <= 1.0
    return x, y, visible


def render_map_image(base_padded, darkness, layout, night_brightness, night_tint_color):
    """Composite the day/night terminator onto the base map and crop/resize
    it to the layout's map area.

    base_padded: PIL RGB image from worldmap.render_base_map().
    darkness: (GRID_H, GRID_W) float array in [0, 1] from solar.compute_terminator().
    """
    L = layout

    arr = np.asarray(base_padded, dtype=np.float32)
    d = worldmap.tile_padded(darkness).astype(np.float32)[..., None]

    tint = np.array(night_tint_color, dtype=np.float32)
    night = arr * float(night_brightness)
    night = night * (1.0 - NIGHT_TINT_STRENGTH) + tint * NIGHT_TINT_STRENGTH

    out = arr * (1.0 - d) + night * d

    glow_strength = 4.0 * d * (1.0 - d) * TWILIGHT_GLOW_STRENGTH
    glow = np.array(TWILIGHT_GLOW_COLOR, dtype=np.float32)
    out = out * (1.0 - glow_strength) + glow * glow_strength

    out = np.clip(out, 0, 255).astype(np.uint8)
    composited = Image.fromarray(out, "RGB")

    x0 = worldmap.lon_to_x(L["lon_min"])
    x1 = worldmap.lon_to_x(L["lon_max"])
    y0 = worldmap.lat_to_y(L["lat_max"])
    y1 = worldmap.lat_to_y(L["lat_min"])

    crop = composited.crop((int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1))))
    return crop.resize((L["map_w"], L["map_h"]), Image.Resampling.LANCZOS)


def draw_graticule(draw, layout, step_deg, color):
    """Draw a lat/lon grid over the map area."""
    L = layout
    lon_span = L["lon_max"] - L["lon_min"]
    lat_span = L["lat_max"] - L["lat_min"]
    x_max = L["map_x"] + L["map_w"] - 1
    y_max = L["map_y"] + L["map_h"] - 1

    lat = math.ceil(L["lat_min"] / step_deg) * step_deg
    while lat <= L["lat_max"]:
        fy = (L["lat_max"] - lat) / lat_span
        y = min(L["map_y"] + fy * L["map_h"], y_max)
        draw.line([(L["map_x"], y), (x_max, y)], fill=color)
        lat += step_deg

    lon = math.ceil(L["lon_min"] / step_deg) * step_deg
    while lon <= L["lon_max"]:
        fx = (lon - L["lon_min"]) / lon_span
        x = min(L["map_x"] + fx * L["map_w"], x_max)
        draw.line([(x, L["map_y"]), (x, y_max)], fill=color)
        lon += step_deg


def draw_sun_marker(draw, layout, subsolar_lat, subsolar_lon, color):
    """Draw a marker at the subsolar point."""
    x, y, visible = lonlat_to_px(subsolar_lon, subsolar_lat, layout)
    if not visible:
        return
    r = max(1, min(layout["map_w"], layout["map_h"]) // 48)
    draw.ellipse([x - r, y - r, x + r, y + r], fill=color)


def draw_cities(draw, layout, cities, color):
    """Draw a marker dot for each visible city."""
    r = 1 if min(layout["map_w"], layout["map_h"]) < 150 else 2
    for city in cities:
        x, y, visible = lonlat_to_px(city["lon"], city["lat"], layout)
        if not visible:
            continue
        draw.ellipse([x - r, y - r, x + r, y + r], fill=color)


def format_clock(dt, fmt="24h", show_seconds=True):
    """Format a datetime as a clock string in 12h or 24h format."""
    if fmt == "12h":
        hour = dt.hour % 12 or 12
        ampm = "AM" if dt.hour < 12 else "PM"
        if show_seconds:
            return f"{hour}:{dt.minute:02d}:{dt.second:02d}{ampm}"
        return f"{hour}:{dt.minute:02d}{ampm}"
    if show_seconds:
        return f"{dt.hour:02d}:{dt.minute:02d}:{dt.second:02d}"
    return f"{dt.hour:02d}:{dt.minute:02d}"


def build_readout(layout, dt_utc, local_dt, subsolar_lat, subsolar_lon, featured_city,
                   clock_format="24h", show_seconds=True, row_h=ROW_H):
    """Build the text rows for the digital clock / info readout.

    Returns a dict:
      - mode: "sidebar" or "corner"
      - anchor: (x, y) - top-left for sidebar, bottom-left for corner
      - row_h: pixel height per row
      - rows: list of (text, color_key) where color_key is "primary" or "secondary"

    featured_city, if given, is a dict with "name" and "local_dt" (already
    converted to that city's timezone by the caller).
    """
    L = layout

    if L["mode"] == "wide_sidebar":
        # The sidebar is narrow (~32px), so labels like "UTC"/"LCL" and full
        # ISO dates don't fit a 4px-wide pixel font. Row order conveys
        # meaning instead: UTC time, date, local time (if configured),
        # subsolar coordinates, featured city.
        rows = [
            (format_clock(dt_utc, clock_format, show_seconds), "primary"),
            (dt_utc.strftime("%m-%d"), "secondary"),
        ]
        if local_dt is not None:
            rows.append((format_clock(local_dt, clock_format, show_seconds), "primary"))
        rows.append((f"{subsolar_lat:+.0f},{subsolar_lon:+.0f}", "secondary"))
        if featured_city is not None and L["sidebar_w"] >= 50:
            name = featured_city["name"][:6]
            time_str = format_clock(featured_city["local_dt"], clock_format, False)
            rows.append((f"{name} {time_str}", "secondary"))

        max_rows = max(1, L["dh"] // row_h)
        return {
            "mode": "sidebar",
            "anchor": (L["sidebar_x"] + 2, 1),
            "row_h": row_h,
            "rows": rows[:max_rows],
        }

    rows = [(format_clock(dt_utc, clock_format, show_seconds) + " UTC", "primary")]
    if L["dh"] >= 2 * row_h + 3:
        rows.append((dt_utc.strftime("%Y-%m-%d"), "secondary"))

    return {
        "mode": "corner",
        "anchor": (2, L["dh"] - 1),
        "row_h": row_h,
        "rows": rows,
    }
