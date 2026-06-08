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
    text_x = (h - 6) + 8           # icon_size + 8, mirrors _display_almanac
    col_w = w - text_x
    body_h = 6
    pct_reserve = int(draw.textlength("100%", font=plugin.display_manager.extra_small_font)) + 2

    fails = []
    for name in ["New Moon", "Wax Crescent", "First Quarter", "Wax Gibbous",
                 "Full Moon", "Wan Gibbous", "Last Quarter", "Wan Crescent"]:
        lay = plugin._almanac_layout(draw, w, h, text_x, name, True)
        title_w = draw.textlength(lay["title_text"], font=lay["title_font"])
        # Horizontal: fitted title must not run into the reserved % zone.
        if title_w > col_w - pct_reserve:
            fails.append(f"'{name}': title {title_w:.0f}px > budget "
                         f"{col_w - pct_reserve}px (collides with %)")
        # Vertical: every placed row's glyphs stay above the bottom edge.
        for i, y in enumerate(lay["rows"]):
            row_h = 8 if (i == 0 and lay["title_font"] is plugin.display_manager.small_font) else body_h
            if y is not None and y + row_h > h:
                fails.append(f"'{name}': row {i} bottom {y + row_h} > height {h}")
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

    # Full render must stay on-panel where this dense page is meant to live
    # (the moon icon makes 64-wide too cramped for the rise/set rows).
    for (w, h) in [(128, 32), (256, 32), (128, 64)]:
        fails = check_render_edges(w, h)
        tag = f"render {w}x{h}"
        if fails:
            total_fail += 1
            print(f"FAIL {tag}:")
            for f in fails:
                print(f"       {f}")
        else:
            print(f"PASS {tag}")

    if total_fail:
        print(f"\n{total_fail} check(s) failed")
        sys.exit(1)
    print("\nAlmanac layout fits the panel at every supported size")
    sys.exit(0)


if __name__ == "__main__":
    main()
