#!/usr/bin/env python3
"""Default fonts must land on their face's pixel grid.

PressStart2P and 4x6-font are pixel-art faces: they rasterise cleanly only at
whole multiples of their grid (8 and 7 respectively). At any other size
FreeType anti-aliases to fake the in-between stroke widths.

On an LED matrix that is not a soft edge -- every pixel is a physical lamp, so
a half-lit edge pixel is a dim lamp, and the text reads as smeared. It showed
up worst on 64-tall panels, where _detail_font_size scaled the odds to 10px:
65% of the lit pixels were partial, and the over/under and spread came out
visibly broken.

The defaults were off-grid almost everywhere -- score 10, status 6, rank 10 --
so this was never specific to the odds; they were just the most obvious.

One deliberate exception: on a 32-tall panel the detail font stays at 6px,
off-grid. The next crisp size is 7px, and at 7px the over/under no longer fits
beside the centre text -- the collision guard drops it entirely. A missing
number is worse than a fuzzy one, so 32-tall keeps its softness.

Run: <core-venv>/bin/python plugins/football-scoreboard/test_fonts_render_crisply.py
"""

import sys
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

# The renderer resolves assets/fonts relative to a core checkout, so we need
# one. Same discovery the repo-level guards use: env var, then the usual
# sibling locations. Exit 2 when absent -- CI reads that as "skipped", not
# "failed", so this cannot go quietly green without a core to test against.
import os  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
CORE = None
for _c in (os.environ.get("LEDMATRIX_CORE", ""),
           str(REPO.parent / "LEDMatrix"),
           str(Path.home() / "projects" / "LEDMatrix")):
    if _c and (Path(_c) / "assets" / "fonts").is_dir():
        CORE = Path(_c)
        break
if CORE is None:
    print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
    sys.exit(2)
sys.path.insert(0, str(CORE))

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

results = []


def check(case, passed):
    results.append((case, passed))
    print("  [%s] %s" % ("pass" if passed else "FAIL", case))


def fuzz_pct(font, text="01/13 O45.5 17-21"):
    """Share of lit pixels that are only partly lit, i.e. anti-aliased."""
    img = Image.new("L", (600, 60), 0)
    ImageDraw.Draw(img).text((1, 1), text, font=font, fill=255)
    lit = [v for v in list(img.getdata()) if v > 8]
    if not lit:
        return 0.0
    return 100.0 * len([v for v in lit if v < 247]) / len(lit)


def main():
    os.chdir(str(CORE))                       # so assets/fonts resolves
    from game_renderer import GameRenderer

    grid_table = getattr(GameRenderer, "_FONT_PIXEL_GRID", None)
    check("GameRenderer declares a font pixel grid", bool(grid_table))
    if not grid_table:
        print("\nFAILED: no _FONT_PIXEL_GRID -- the crisp-font fix is not applied")
        sys.exit(1)

    print("\nthe grid table matches what the fonts actually do")
    for name, grid in grid_table.items():
        path = CORE / "assets" / "fonts" / name
        if not path.exists():
            check("%s present" % name, False)
            continue
        on = fuzz_pct(ImageFont.truetype(str(path), grid))
        off = fuzz_pct(ImageFont.truetype(str(path), grid + 2))
        check("%s is crisp at its grid size %d" % (name, grid), on == 0.0)
        check("%s is NOT crisp off-grid (%d)" % (name, grid + 2), off > 0.0)

    print("\nevery default font is crisp, at every panel height")
    for height in (32, 48, 64, 96, 128):
        r = GameRenderer(128, height, {})
        for key in ("score", "time", "status", "detail", "rank"):
            pct = fuzz_pct(r.fonts[key])
            if height <= 32 and key == "detail":
                continue                      # documented exception, below
            check("%3dpx panel: %s at %spx is crisp"
                  % (height, key, r.fonts[key].size), pct == 0.0)

    print("\nthe 32-tall detail exception is deliberate and still in place")
    r32 = GameRenderer(128, 32, {})
    check("32-tall detail stays 6px so the over/under survives",
          r32.fonts["detail"].size == 6)

    print("\ntall panels scale the detail font in whole grid steps")
    for height, expected in ((64, 14), (96, 21), (128, 28)):
        r = GameRenderer(128, height, {})
        check("%dpx panel: detail is %dpx" % (height, expected),
              r.fonts["detail"].size == expected)

    print()
    failed = [c for c, ok in results if not ok]
    print("FAILED: %d" % len(failed) if failed else "All checks passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
