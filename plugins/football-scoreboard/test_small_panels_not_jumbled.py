#!/usr/bin/env python3
"""The scorebug must not overprint itself on a small panel.

Two independent causes, both from sizes chosen without reference to the space
available.

Logos were sized at 1.5x the panel so they bleed off the outer edge -- the
look this layout is built around, and fine when the panel is wide. On a 64x32
it made each logo 48px, placed at x=-10 and x=26, so the two logos overlapped
EACH OTHER across the middle before the score or clock were drawn at all.
They are now capped so the pair always leaves the centre clear for the score.

Text was drawn at a fixed size and centred whatever its width. "Q4 02:34" at
8px is 64px -- the entire width of a 64px panel -- so it spanned edge to edge
with its outline clipped at both ends, on the same rows as the score and the
down-and-distance. Status and down/distance now shed detail to fit, the same
trade the odds row makes: "Q4 02:34" -> "02:34" -> "Q4".

Run: <core-venv>/bin/python plugins/football-scoreboard/test_small_panels_not_jumbled.py
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
    """Enough of a renderer to exercise the sizing rules without a display."""

    _LOGO_EDGE_BLEED_PX = 10

    def __init__(self, w, h, score_font):
        self.display_width = w
        self.display_height = h
        self.fonts = {"score": score_font}

    _scorebug_centre_gap = None       # bound below from the real class
    _fit_text = None


def main():
    os.chdir(str(CORE))
    from sports import SportsCore
    from PIL import Image, ImageDraw, ImageFont

    _Fake._scorebug_centre_gap = SportsCore._scorebug_centre_gap
    _Fake._fit_text = SportsCore._fit_text
    score_font = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 8)
    draw = ImageDraw.Draw(Image.new("RGB", (4, 4)))

    SIZES = [(64, 32), (128, 32), (256, 32), (96, 48), (64, 64),
             (128, 64), (128, 96), (256, 128), (512, 64)]

    print("the two logos never reach into each other")
    for w, h in SIZES:
        r = _Fake(w, h, score_font)
        gap = r._scorebug_centre_gap()
        reach = (w - gap) // 2 + r._LOGO_EDGE_BLEED_PX
        logo_w = max(8, min(int(w * 1.5), reach))
        logo_w = min(logo_w, int(h * 1.5))
        away_right = -r._LOGO_EDGE_BLEED_PX + logo_w
        home_left = w - logo_w + r._LOGO_EDGE_BLEED_PX
        check("%3dx%-3d logos leave the centre clear" % (w, h),
              away_right <= home_left)
        # The gap is deliberately half the score's width: the score's outer
        # quarter crosses onto each logo, its middle stays on black. So the
        # check is that the clear strip is at least the reserve, not that the
        # whole score fits inside it.
        check("%3dx%-3d keeps the reserved centre strip clear" % (w, h),
              home_left - away_right >= gap - 1)
        score_w = int(draw.textlength("00-00", font=score_font))
        overlap_each_side = max(0, (score_w - (home_left - away_right)) / 2)
        check("%3dx%-3d score crosses no more than a quarter onto a logo"
              % (w, h), overlap_each_side <= score_w / 4 + 1)

    print("\nthe reserve is half the score, not all of it")
    r = _Fake(64, 32, score_font)
    check("a 64px panel gets a 22px reserve, not 44",
          18 <= r._scorebug_centre_gap() <= 24)

    print("\nthe rigs keep their large logos")
    for w, h, expect_at_least in ((128, 32, 40), (512, 64, 90)):
        r = _Fake(w, h, score_font)
        reach = (w - r._scorebug_centre_gap()) // 2 + r._LOGO_EDGE_BLEED_PX
        logo_w = min(max(8, min(int(w * 1.5), reach)), int(h * 1.5))
        check("%3dx%-3d logo is still %d+px" % (w, h, expect_at_least),
              logo_w >= expect_at_least)

    print("\nstatus text sheds detail rather than overflowing")
    time_font = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 8)
    r = _Fake(64, 32, score_font)
    picked = r._fit_text(draw, ("Q4 02:34", "02:34", "Q4"), time_font, 62)
    check("a 64px panel drops the quarter from the clock", picked == "02:34")
    check("what it picked actually fits",
          draw.textlength(picked, font=time_font) <= 62)

    wide = _Fake(512, 64, score_font)
    picked_wide = wide._fit_text(draw, ("Q4 02:34", "02:34", "Q4"), time_font, 510)
    check("a wide panel keeps the full clock", picked_wide == "Q4 02:34")

    print("\nnothing fitting still returns something")
    check("the shortest form is used as a last resort",
          r._fit_text(draw, ("aaaaaaaaaaaa", "bbbbbbbbbb"), time_font, 4) == "bbbbbbbbbb")
    check("an empty candidate list yields an empty string",
          r._fit_text(draw, (), time_font, 100) == "")

    print()
    failed = [c for c, ok in results if not ok]
    print("FAILED: %d" % len(failed) if failed else "All checks passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
