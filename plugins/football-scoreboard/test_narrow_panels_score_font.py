#!/usr/bin/env python3
"""The score must not swamp a narrow panel.

sports.py loaded the score at PressStart2P 10px on every panel. That face is
fixed-width and wide: "17-21" comes out 50px. On a 128-wide panel that is 39%
of the width and fine -- it is what both of the maintained rigs run. On a
64-wide panel it is 78%, and the score, the clock and two logos were all
contending for the same strip, so the logos were reduced to slivers behind
the digits.

PressStart2P has no smaller crisp size -- its pixel grid is 8, and 10 was
already off-grid and anti-aliased. So the way down is a narrower FACE, not a
smaller size: 4x6-font is crisp at multiples of 7 and about half as wide,
putting the same score at 24px / 38%.

The swap is conditional on the score actually overflowing, so it must not
touch any panel where the old face already fitted -- in particular the 128x32
and 512x64 builds, which must render byte-identically.

Run: <core-venv>/bin/python plugins/football-scoreboard/test_narrow_panels_score_font.py
"""

import os
import sys
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

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

results = []


def check(case, passed):
    results.append((case, passed))
    print("  [%s] %s" % ("pass" if passed else "FAIL", case))


class _Fake:
    """Enough of a renderer to exercise the font rule without a display."""

    def __init__(self, w, h):
        self.display_width = w
        self.display_height = h
        self.logger = logging.getLogger("test")


def main():
    os.chdir(str(CORE))
    from sports import SportsCore
    from PIL import Image, ImageDraw, ImageFont

    for attr in ("_SCORE_WIDTH_BUDGET", "_NARROW_SCORE_RUNGS", "_fit_score_font"):
        if not hasattr(SportsCore, attr):
            print("  [FAIL] SportsCore has no %s -- the score font is still "
                  "fixed at PressStart2P 10px on every panel, so a 64-wide "
                  "panel renders the score at 78%% of its width." % attr)
            print("\n1 failed")
            return 1
        setattr(_Fake, attr, getattr(SportsCore, attr))

    draw = ImageDraw.Draw(Image.new("RGB", (4, 4)))
    baseline = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 10)

    def fonts_for(w, h):
        r = _Fake(w, h)
        return r._fit_score_font({"score": baseline, "time": baseline})

    print("a narrow panel gets a score it has room for")
    for w, h in ((64, 32), (64, 64)):
        f = fonts_for(w, h)
        width = draw.textlength("00-00", font=f["score"])
        check("%3dx%-3d score fits the budget (%dpx, %d%% of panel)"
              % (w, h, width, round(100 * width / w)),
              width <= w * SportsCore._SCORE_WIDTH_BUDGET)
        check("%3dx%-3d actually changed face" % (w, h), f["score"] is not baseline)
        check("%3dx%-3d clock moved with the score" % (w, h),
              f["time"] is f["score"])
        # The whole point: enough width left over for two logos and a gap.
        check("%3dx%-3d leaves 60%%+ of the width for the logos" % (w, h),
              w - width >= w * 0.6)

    print("\npanels that already fitted are left alone")
    for w, h in ((96, 48), (128, 32), (128, 64), (256, 32),
                 (128, 96), (256, 128), (512, 64)):
        f = fonts_for(w, h)
        check("%3dx%-3d keeps the face it had" % (w, h), f["score"] is baseline)
        check("%3dx%-3d keeps the clock it had" % (w, h), f["time"] is baseline)

    print("\nthe narrower face is on its own pixel grid (no anti-aliasing)")
    for name, size in SportsCore._NARROW_SCORE_RUNGS:
        check("%s@%d is a multiple of 7" % (name, size), size % 7 == 0)

    print("\nthe rungs step down, widest first")
    widths = [draw.textlength("00-00",
                              font=ImageFont.truetype("assets/fonts/" + n, s))
              for n, s in SportsCore._NARROW_SCORE_RUNGS]
    check("rungs are ordered widest to narrowest",
          widths == sorted(widths, reverse=True))

    print("\nthe narrow face buys back the quarter on the clock")
    f = fonts_for(64, 32)
    check("'Q4 02:34' now fits a 64px panel",
          draw.textlength("Q4 02:34", font=f["time"]) <= 62)
    check("...where PressStart2P@8 did not",
          draw.textlength("Q4 02:34",
                          font=ImageFont.truetype(
                              "assets/fonts/PressStart2P-Regular.ttf", 8)) > 62)

    failed = [c for c, ok in results if not ok]
    print("\n%d checks, %d failed" % (len(results), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
