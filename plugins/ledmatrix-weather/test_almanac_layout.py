#!/usr/bin/env python3
"""Regression test for the almanac (moon) page layout.

Before the fix, the 8px PressStart2P phase name overflowed the narrow text
column on 64- and 128-wide panels: long names ("Wax Gibbous", "Last Quarter")
ran clean off the right edge and collided with the right-aligned illumination
%, and the Day-length row was drawn past the bottom of a 32px-tall panel. This
renders the real page at every supported size and asserts nothing is drawn into
the panel's edge columns/rows.

Run with the core venv from a LEDMatrix checkout so PIL + assets/fonts resolve:
    LEDMatrix/.venv/bin/python <thisfile>
"""
import os
import sys

from PIL import Image, ImageFont

sys.path.insert(0, os.path.dirname(__file__))
from manager import WeatherPlugin  # noqa: E402


def _font(name, size):
    for base in ("assets/fonts", "../assets/fonts",
                 os.path.join(os.path.dirname(__file__), "assets/fonts")):
        p = os.path.join(base, name)
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    raise FileNotFoundError(f"{name} not found; run from a LEDMatrix checkout")


class _FakeMatrix:
    def __init__(self, w, h):
        self.width, self.height = w, h


class _FakeDisplayManager:
    """Just enough surface for _display_almanac to render to an image."""

    def __init__(self, w, h):
        self.matrix = _FakeMatrix(w, h)
        self.small_font = _font("PressStart2P-Regular.ttf", 8)
        self.extra_small_font = _font("4x6-font.ttf", 6)
        self.image = None

    def update_display(self):
        pass


SIZES = [(64, 32), (128, 32), (256, 32), (128, 64)]

# One real day's worth of almanac data for every moon phase (phase 0..1).
PHASES = [0.0, 0.12, 0.25, 0.40, 0.5, 0.60, 0.75, 0.90]


def weather_for_phase(phase):
    """One day's almanac data with the moon at the given phase (0..1)."""
    return {
        "timezone_offset": -25200,
        "sun": {"sunrise": 1717500000, "sunset": 1717556400},
        "moon": {"phase": phase, "moonrise": 1717495000, "moonset": 1717545000},
    }


def _new_plugin(w, h):
    plugin = object.__new__(WeatherPlugin)
    plugin.display_manager = _FakeDisplayManager(w, h)
    plugin.COLORS = {"dim": (180, 180, 180)}
    return plugin


def check_layout_helper(w, h):
    """The pure layout helper must, at every width, fit the phase name + the
    reserved % inside the text column and keep every placed row on-panel."""
    from PIL import ImageDraw
    plugin = _new_plugin(w, h)
    draw = ImageDraw.Draw(Image.new("RGB", (w, h)))
    icon_size = min(h - 6, 32)            # mirrors _display_almanac icon cap
    gap = 4 if w < 100 else 8
    text_x = icon_size + gap
    col_w = w - text_x
    body_h = 6
    pct_reserve = int(draw.textlength("100%", font=plugin.display_manager.extra_small_font)) + 2

    fails = []
    for name in ["New Moon", "Waxing Crescent", "First Quarter", "Waxing Gibbous",
                 "Full Moon", "Waning Gibbous", "Last Quarter", "Waning Crescent"]:
        lay = plugin._almanac_layout(draw, w, h, text_x, name, True)
        title_w = draw.textlength(lay["title_text"], font=lay["title_font"])
        # Horizontal: fitted title must not run into the reserved % zone.
        if title_w > col_w - pct_reserve:
            fails.append(f"'{name}': title {title_w:.0f}px > budget "
                         f"{col_w - pct_reserve}px (collides with %)")
        # The fitted title must be a clean variant — the full name or its
        # abbreviation — unless even the abbreviation can't fit, in which case a
        # trim is the only option. Never trim mid-word when a whole word fits.
        short = plugin._PHASE_ABBREV.get(name, name)
        short_fits = draw.textlength(short, font=lay["title_font"]) <= col_w - pct_reserve
        if short_fits and lay["title_text"] not in (name, short):
            fails.append(f"'{name}': fitted title '{lay['title_text']}' is a "
                         f"mid-word trim though '{short}' fits")
        # Vertical: every placed row's glyphs stay above the bottom edge.
        for i, y in enumerate(lay["rows"]):
            row_h = 8 if (i == 0 and lay["title_font"] is plugin.display_manager.small_font) else body_h
            if y is not None and y + row_h > h:
                fails.append(f"'{name}': row {i} bottom {y + row_h} > height {h}")
    return fails


def check_full_names_restored():
    """The phase namer returns full Waxing/Waning names, and the layout shows
    them in full on a roomy panel (the point of restoring the abbreviated text)."""
    fails = []
    expected = {
        0.12: "Waxing Crescent",
        0.40: "Waxing Gibbous",
        0.60: "Waning Gibbous",
        0.90: "Waning Crescent",
    }
    plugin = _new_plugin(256, 32)
    for phase, name in expected.items():
        got = plugin._get_moon_phase_name(phase)
        if got != name:
            fails.append(f"_get_moon_phase_name({phase}) = '{got}', want '{name}'")

    # On a wide panel the full name should survive intact (not abbreviated).
    from PIL import ImageDraw
    w, h = 256, 32
    draw = ImageDraw.Draw(Image.new("RGB", (w, h)))
    text_x = min(h - 6, 32) + 8
    for name in expected.values():
        lay = plugin._almanac_layout(draw, w, h, text_x, name, True)
        if lay["title_text"] != name:
            fails.append(f"256x32: '{name}' rendered as "
                         f"'{lay['title_text']}' (full name not restored)")
    return fails


def check_render_edges(w, h):
    """End-to-end render on a realistically-sized panel: no glyph touches the
    last column or last row (the original bug bled off both)."""
    plugin = _new_plugin(w, h)
    fails = []
    for phase in PHASES:
        plugin.display_manager.image = None
        plugin.weather_data = weather_for_phase(phase)
        plugin._display_almanac()
        img = plugin.display_manager.image
        if img is None:
            raise AssertionError(f"{w}x{h} phase={phase}: no image rendered")
        px = img.load()
        if any(px[w - 1, y] != (0, 0, 0) for y in range(h)):
            fails.append(f"phase={phase:.2f}: text reaches right edge (off-panel)")
        if any(px[x, h - 1] != (0, 0, 0) for x in range(w)):
            fails.append(f"phase={phase:.2f}: text reaches bottom edge (off-panel)")
    return fails


def check_time_mode(w, h):
    """The rise/set rows must read clearly, not as cryptic 'MR/MS'. Wide short
    panels (128x32, 256x32) get the labeled 'Sun 6:42am-8:51pm' range with full
    am/pm; the cramped 64-wide panel falls back to stacked sun-only times rather
    than truncating a range into garbage."""
    from PIL import ImageDraw
    plugin = _new_plugin(w, h)
    draw = ImageDraw.Draw(Image.new("RGB", (w, h)))
    icon_size = min(h - 6, 32)
    gap = 4 if w < 100 else 8
    col_w = w - (icon_size + gap)
    data = weather_for_phase(0.5)
    s, m = data["sun"], data["moon"]
    mode, full = plugin._almanac_time_mode(
        draw, col_w, data["timezone_offset"],
        s["sunrise"], s["sunset"], m["moonrise"], m["moonset"])

    fails = []
    if w >= 128:
        if mode != "range":
            fails.append(f"expected labeled range on {w}-wide, got {mode!r}")
        if not full:
            fails.append(f"expected full am/pm on {w}-wide, got compact")
    if w == 64 and mode != "stacked":
        fails.append(f"expected stacked fallback on 64-wide, got {mode!r}")
    return fails


def check_columns(w, h):
    """In range mode the rise/set times are laid out as a grid: every formatted
    time fits inside its shared-width time column (so the two rows' rise times
    stack and set times stack), and the whole grid stays inside the text column.
    Narrow panels use the stacked fallback instead, so there's no grid to check."""
    from PIL import ImageDraw
    plugin = _new_plugin(w, h)
    font = plugin.display_manager.extra_small_font
    draw = ImageDraw.Draw(Image.new("RGB", (w, h)))
    icon_size = min(h - 6, 32)
    gap = 4 if w < 100 else 8
    col_w = w - (icon_size + gap)
    data = weather_for_phase(0.5)
    s, m = data["sun"], data["moon"]
    tz = data["timezone_offset"]
    mode, full = plugin._almanac_time_mode(
        draw, col_w, tz, s["sunrise"], s["sunset"], m["moonrise"], m["moonset"])
    if mode != "range":
        return []

    cols = plugin._almanac_columns(
        draw, font, full, tz, s["sunrise"], s["sunset"], m["moonrise"], m["moonset"])
    fails = []
    for ts in (s["sunrise"], s["sunset"], m["moonrise"], m["moonset"]):
        tw = draw.textlength(plugin._format_unix_time(ts, tz, full), font=font)
        if tw > cols["time_w"] + 0.01:
            fails.append(f"time {tw:.0f}px overflows its {cols['time_w']:.0f}px column")
    if cols["total"] > col_w - 2:
        fails.append(f"grid {cols['total']:.0f}px exceeds text column {col_w - 2}px")
    return fails


def main():
    total_fail = 0

    # Layout math holds at every supported width, including the cramped 64px.
    for (w, h) in SIZES:
        fails = check_layout_helper(w, h)
        tag = f"layout {w}x{h}"
        if fails:
            total_fail += 1
            print(f"FAIL {tag}:")
            for f in fails:
                print(f"       {f}")
        else:
            print(f"PASS {tag}")

    # Full render must stay on-panel at every supported size, including the
    # cramped 64-wide panel (the stacked fallback now keeps it on-panel where
    # the old labeled rows bled off).
    for (w, h) in SIZES:
        fails = check_render_edges(w, h)
        tag = f"render {w}x{h}"
        if fails:
            total_fail += 1
            print(f"FAIL {tag}:")
            for f in fails:
                print(f"       {f}")
        else:
            print(f"PASS {tag}")

    # Rise/set rows read clearly (labeled range + full am/pm where it fits,
    # stacked fallback where it doesn't) instead of the old cryptic MR/MS.
    for (w, h) in SIZES:
        fails = check_time_mode(w, h)
        tag = f"time-mode {w}x{h}"
        if fails:
            total_fail += 1
            print(f"FAIL {tag}:")
            for f in fails:
                print(f"       {f}")
        else:
            print(f"PASS {tag}")

    # In range mode the times line up as a grid (shared time columns) and the
    # whole label | rise | '-' | set grid stays inside the text column.
    for (w, h) in SIZES:
        fails = check_columns(w, h)
        tag = f"columns {w}x{h}"
        if fails:
            total_fail += 1
            print(f"FAIL {tag}:")
            for f in fails:
                print(f"       {f}")
        else:
            print(f"PASS {tag}")

    # The full Waxing/Waning phase names are restored and shown intact on a
    # roomy panel (degrading to the abbreviation only where the column is tight).
    fails = check_full_names_restored()
    if fails:
        total_fail += 1
        print("FAIL full-names:")
        for f in fails:
            print(f"       {f}")
    else:
        print("PASS full-names")

    if total_fail:
        print(f"\n{total_fail} check(s) failed")
        sys.exit(1)
    print("\nAlmanac layout fits the panel at every supported size")
    sys.exit(0)


if __name__ == "__main__":
    main()
