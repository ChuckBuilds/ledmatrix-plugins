#!/usr/bin/env python3
"""
Render geochron plugin preview images without needing the full LEDMatrix system.

Outputs one PNG per target panel size at a reference UTC time, a handful of
128x32 frames at notable times of year (solstices/equinox/midnight) to verify
the terminator's shape and tilt, a hard-line vs. twilight-band comparison, and
a composite sheet of all sizes.

Usage:  python3 render_preview.py
"""

import os
from datetime import datetime, timezone

import pytz
from PIL import Image, ImageDraw, ImageFont

import geochron_renderer as gr
import solar
import worldmap

# ── Palette (must match config_schema.json defaults) ────────────────────────
OCEAN_COLOR = (10, 35, 90)
LAND_COLOR = (40, 110, 50)
COASTLINE_COLOR = (90, 160, 100)
NIGHT_TINT_COLOR = (10, 10, 40)
SUN_MARKER_COLOR = (255, 220, 0)
CITY_MARKER_COLOR = (255, 60, 60)
GRID_COLOR = (70, 70, 70)
TEXT_PRIMARY_COLOR = (255, 255, 255)
TEXT_SECONDARY_COLOR = (180, 180, 180)

NIGHT_BRIGHTNESS = 0.20
CLOCK_FORMAT = "24h"
SHOW_DATE = True
SHOW_DATE_LINE = True
DATE_LINE_LABELS = "bottom"
GRATICULE_STEP_DEG = 30

CITIES = [
    {"name": "New York", "lat": 40.71, "lon": -74.01, "timezone": "America/New_York"},
    {"name": "Los Angeles", "lat": 34.05, "lon": -118.24, "timezone": "America/Los_Angeles"},
    {"name": "Rio de Janeiro", "lat": -22.91, "lon": -43.17, "timezone": "America/Sao_Paulo"},
    {"name": "London", "lat": 51.51, "lon": -0.13, "timezone": "Europe/London"},
    {"name": "Cairo", "lat": 30.04, "lon": 31.24, "timezone": "Africa/Cairo"},
    {"name": "Moscow", "lat": 55.75, "lon": 37.62, "timezone": "Europe/Moscow"},
    {"name": "Tokyo", "lat": 35.68, "lon": 139.65, "timezone": "Asia/Tokyo"},
    {"name": "Sydney", "lat": -33.87, "lon": 151.21, "timezone": "Australia/Sydney"},
]

SIZES = [(64, 32), (128, 32), (64, 64), (128, 64), (256, 32), (128, 96), (256, 128)]

REFERENCE_DT = datetime(2025, 8, 1, 15, 25, 0, tzinfo=timezone.utc)
REFERENCE_MAP_CENTER_LON = -75.0  # roughly America/New_York in summer (UTC-4 * 15)

TIME_SAMPLES = [
    ("june_solstice_noon", datetime(2025, 6, 21, 12, 0, 0, tzinfo=timezone.utc)),
    ("dec_solstice_noon", datetime(2025, 12, 21, 12, 0, 0, tzinfo=timezone.utc)),
    ("equinox_noon", datetime(2025, 3, 20, 12, 0, 0, tzinfo=timezone.utc)),
    ("midnight_utc", datetime(2025, 8, 1, 0, 0, 0, tzinfo=timezone.utc)),
]


def _load_font():
    path = os.path.join(os.path.dirname(__file__), "assets", "fonts", "4x6-font.ttf")
    try:
        return ImageFont.truetype(path, 7)  # 4x6-font is crisp only at multiples of 7
    except OSError:
        return ImageFont.load_default()


FONT = _load_font()


SIDEBAR_W = gr.sidebar_width(FONT.getlength, CLOCK_FORMAT)


def zones_at(dt_utc, local_dt):
    cities = [{"label": gr.city_label(c), "local_dt": dt_utc.astimezone(pytz.timezone(c["timezone"])),
               "tz": c["timezone"]} for c in CITIES]
    local_name = getattr(local_dt.tzinfo, "zone", None) if local_dt is not None else None
    return gr.build_zones(local_dt, local_name, cities, CLOCK_FORMAT)


def build_readout(layout, dt_utc, local_dt):
    date_text = None
    if SHOW_DATE and layout["sidebar_w"]:
        date_text = gr.sidebar_date(local_dt or dt_utc, FONT.getlength, layout["sidebar_w"] - 4)
    return gr.build_readout(layout, dt_utc, zones_at(dt_utc, local_dt), date_text=date_text)


def render_frame(base, dw, dh, darkness, sub_lat, sub_lon, dt_utc, local_dt, featured_city,
                 map_center_lon=0.0, show_grid=True, show_sun=True, show_cities=True,
                 show_clock=True):
    layout = gr._layout(dw, dh, map_center_lon=map_center_lon, sidebar_w=SIDEBAR_W)
    map_img = gr.render_map_image(base, darkness, layout, NIGHT_BRIGHTNESS, NIGHT_TINT_COLOR)

    canvas = Image.new("RGB", (dw, dh), (0, 0, 0))
    canvas.paste(map_img, (layout["map_x"], layout["map_y"]))
    draw = ImageDraw.Draw(canvas)

    if show_grid:
        gr.draw_graticule(draw, layout, GRATICULE_STEP_DEG, GRID_COLOR)
    if show_sun:
        gr.draw_sun_marker(draw, layout, sub_lat, sub_lon, SUN_MARKER_COLOR)
    if show_cities:
        gr.draw_cities(draw, layout, CITIES, CITY_MARKER_COLOR)
    readout = build_readout(layout, dt_utc, local_dt) if show_clock else None
    if SHOW_DATE_LINE:
        avoid = gr.readout_box(draw, readout, FONT) if readout else None
        gr.draw_date_line(draw, layout, dt_utc, FONT, SUN_MARKER_COLOR, TEXT_PRIMARY_COLOR,
                          DATE_LINE_LABELS, avoid)
    if readout:
        gr.draw_readout(draw, readout, FONT, TEXT_PRIMARY_COLOR, TEXT_SECONDARY_COLOR)

    return canvas


def make_sheet(frames, sizes):
    SCALE = 2
    PAD = 6
    LABEL_H = 9

    max_w = max(dw * SCALE for dw, dh in sizes)
    sheet_h = PAD + sum(LABEL_H + dh * SCALE + PAD for dw, dh in sizes)
    sheet_w = max_w + 2 * PAD

    sheet = Image.new("RGB", (sheet_w, sheet_h), (12, 12, 20))
    sdraw = ImageDraw.Draw(sheet)

    y = PAD
    for dw, dh in sizes:
        sdraw.text((PAD, y), f"{dw}x{dh} ({frames[(dw, dh)].size[0]}x{frames[(dw, dh)].size[1]})",
                    fill=(180, 200, 240), font=FONT)
        y += LABEL_H
        big = frames[(dw, dh)].resize((dw * SCALE, dh * SCALE), Image.NEAREST)
        sheet.paste(big, (PAD, y))
        sdraw.rectangle([PAD - 1, y - 1, PAD + dw * SCALE, y + dh * SCALE], outline=(30, 40, 60))
        y += dh * SCALE + PAD

    return sheet


def main():
    out_dir = os.path.dirname(os.path.abspath(__file__))
    print("Rasterizing base map...")
    base = worldmap.render_base_map(OCEAN_COLOR, LAND_COLOR, COASTLINE_COLOR)

    ny_tz = pytz.timezone(CITIES[0]["timezone"])
    local_dt = REFERENCE_DT.astimezone(ny_tz)
    featured_city = {"name": CITIES[0]["name"], "local_dt": local_dt}

    print("Rendering size sweep at", REFERENCE_DT.isoformat())
    darkness, sub_lat, sub_lon = solar.compute_terminator(
        REFERENCE_DT, worldmap.GRID_W, worldmap.GRID_H, show_bands=True
    )
    print(f"  subsolar point: lat={sub_lat:.2f} lon={sub_lon:.2f}")

    frames = {}
    for dw, dh in SIZES:
        canvas = render_frame(
            base, dw, dh, darkness, sub_lat, sub_lon, REFERENCE_DT, local_dt, featured_city,
            map_center_lon=REFERENCE_MAP_CENTER_LON,
        )
        frames[(dw, dh)] = canvas
        big = canvas.resize((dw * 4, dh * 4), Image.NEAREST)
        path = os.path.join(out_dir, f"preview_{dw}x{dh}.png")
        big.save(path)
        print(f"  Saved: {path}")

    print("Rendering 128x32 time samples...")
    for label, dt in TIME_SAMPLES:
        d, slat, slon = solar.compute_terminator(dt, worldmap.GRID_W, worldmap.GRID_H, show_bands=True)
        print(f"  {label}: subsolar lat={slat:.2f} lon={slon:.2f}")
        canvas = render_frame(base, 128, 32, d, slat, slon, dt, None, None, map_center_lon=0.0)
        big = canvas.resize((128 * 4, 32 * 4), Image.NEAREST)
        path = os.path.join(out_dir, f"preview_128x32_{label}.png")
        big.save(path)
        print(f"  Saved: {path}")

    print("Rendering hard-line terminator comparison (128x32)...")
    d_hard, slat, slon = solar.compute_terminator(
        REFERENCE_DT, worldmap.GRID_W, worldmap.GRID_H, show_bands=False
    )
    canvas = render_frame(
        base, 128, 32, d_hard, slat, slon, REFERENCE_DT, local_dt, featured_city,
        map_center_lon=REFERENCE_MAP_CENTER_LON,
    )
    big = canvas.resize((128 * 4, 32 * 4), Image.NEAREST)
    path = os.path.join(out_dir, "preview_128x32_hardline.png")
    big.save(path)
    print(f"  Saved: {path}")

    print("Rendering composite sheet...")
    sheet = make_sheet(frames, SIZES)
    path = os.path.join(out_dir, "preview_sheet.png")
    sheet.save(path)
    print(f"  Saved: {path}  ({sheet.width}x{sheet.height})")

    print("Done.")


if __name__ == "__main__":
    main()
