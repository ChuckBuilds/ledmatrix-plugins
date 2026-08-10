#!/usr/bin/env python3
"""
Regression test: _draw_text_with_outline must disable anti-aliasing.

The scoreboard renders pixel/bitmap fonts (e.g. PressStart2P) on a 1:1 LED
matrix. With anti-aliasing on (PIL's default), FreeType blends glyph edges into
dim partial-lit pixels, which on the matrix muddy the digits (a "6" can read as
a "G"). Both text-outline helpers (sports.py switch-mode renderer and
game_renderer.py scroll renderer) must set ``draw.fontmode = "1"`` so glyphs
render crisp.

This test draws a pixel-font glyph through each helper and asserts the result
has zero partial-lit (anti-aliased) pixels. It FAILS before the fontmode fix and
PASSES after.

Run with the core venv from anywhere:
    /path/to/LEDMatrix/.venv/bin/python test_score_antialiasing.py
"""

import os
import sys

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

from PIL import Image, ImageDraw, ImageFont


def _find_pixel_font():
    """Locate PressStart2P-Regular.ttf in the core assets dir.

    The plugin runs inside LEDMatrix/plugin-repos/<id>/, so the core fonts are a
    couple levels up. Search upward and a few known spots.
    """
    name = "PressStart2P-Regular.ttf"
    candidates = []
    # LEDMATRIX_CORE is the runner's contract for "the core is here", and it is
    # absolute. Walking up from the plugin only finds the fonts when the plugin
    # happens to sit inside a core checkout (LEDMatrix/plugin-repos/<id>/); from
    # a standalone plugins repo it never does, so this skipped every run even
    # when a core was supplied.
    core = os.environ.get("LEDMATRIX_CORE")
    if core:
        candidates.append(os.path.join(core, "assets", "fonts", name))
    d = PLUGIN_DIR
    for _ in range(6):
        candidates.append(os.path.join(d, "assets", "fonts", name))
        d = os.path.dirname(d)
    candidates.append(os.path.join(os.getcwd(), "assets", "fonts", name))
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def _partial_lit_pixels(font):
    """Draw a glyph via the (unbound) helper and count anti-aliased pixels.

    Returns (partials, fontmode) where partials is the number of pixels that are
    neither fully off nor fully on in the alpha channel — i.e. anti-aliasing.
    """
    from game_renderer import GameRenderer

    img = Image.new("RGBA", (24, 16), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Call the real method unbound; it uses no instance state, so self can be None.
    GameRenderer._draw_text_with_outline(None, draw, "6", (2, 1), font, fill=(255, 200, 0))
    alpha = img.split()[3].load()
    partials = sum(
        1 for y in range(img.height) for x in range(img.width) if 0 < alpha[x, y] < 255
    )
    return partials, getattr(draw, "fontmode", None)


def _partial_lit_pixels_sports(font):
    from sports import SportsCore

    img = Image.new("RGBA", (24, 16), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # SportsCore is abstract; the method uses no instance state, so call unbound.
    SportsCore._draw_text_with_outline(None, draw, "6", (2, 1), font, fill=(255, 200, 0))
    alpha = img.split()[3].load()
    partials = sum(
        1 for y in range(img.height) for x in range(img.width) if 0 < alpha[x, y] < 255
    )
    return partials, getattr(draw, "fontmode", None)


def main():
    font_path = _find_pixel_font()
    if not font_path:
        print("SKIP: could not locate PressStart2P-Regular.ttf (run from LEDMatrix tree)")
        # Skipping is not a pass; signal an error so the gap is visible.
        return 2
    # Size 10 does not land on the pixel grid -> heavy anti-aliasing if enabled.
    font = ImageFont.truetype(font_path, 10)

    failures = []
    for label, fn in (
        ("game_renderer.GameRenderer", _partial_lit_pixels),
        ("sports.SportsCore", _partial_lit_pixels_sports),
    ):
        partials, fontmode = fn(font)
        ok = partials == 0 and fontmode == "1"
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {label}: anti-aliased pixels={partials}, fontmode={fontmode!r}")
        if not ok:
            failures.append(label)

    if failures:
        print(f"\nFAILED: {', '.join(failures)} still anti-aliases pixel fonts")
        return 1
    print("\nPASS: both outline helpers disable anti-aliasing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
