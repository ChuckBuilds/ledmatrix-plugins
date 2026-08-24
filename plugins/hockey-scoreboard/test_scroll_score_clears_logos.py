#!/usr/bin/env python3
"""The score must never be drawn on top of a logo on a scroll/Vegas card.

Ported from football-scoreboard, where this was reported against the Vegas
ticker and reproduced on a 512x64 panel: the score rendered ~80px wide inside
a 36px centre gap, so part of it sat on each team's logo.

The gap and the score were computed from unrelated inputs -- the gap from the
CARD WIDTH (width x CENTER_GAP_RATIO, clamped), the score's size from config
and the element-style resolver. Nothing compared them, so any score wider than
the clamp silently overlapped. Every harness render still passed, because
check_plugin.py exercises the regular display and not the scroll cards. Scroll
card behaviour needs its own test; the harness will not catch it.

This lineage pins the card at a flat 128px, so its logos were also frozen at
(128 - gap) / 2 = 46px however tall the panel was. The card is now sized as
two full-height logos plus the measured gap, and the redundant height cap on
the logo slot is gone.

Checks are written against the FONT-SIZE-AGNOSTIC property: whatever size the
score ends up, it fits the gap. That is what makes this robust to a config or
resolver picking a different size from the one this checkout happens to load.

Run: <core-venv>/bin/python plugins/hockey-scoreboard/test_scroll_score_clears_logos.py
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


HEIGHTS = (32, 48, 64, 96, 128)
# Deliberately a literal, not GameRenderer._SCORE_PROBE: reading the
# implementation's own constant would make this agree by construction
# and never catch a reserve that is too narrow for a real score.
WORST_SCORE = "00-00"   # this sport's widest realistic score


def main():
    os.chdir(str(CORE))
    from game_renderer import GameRenderer
    from PIL import Image, ImageDraw, ImageFont

    if not hasattr(GameRenderer, "_score_reserve_width"):
        print("  [FAIL] GameRenderer has no _score_reserve_width -- the centre "
              "gap is still derived from the card width alone, so a score "
              "wider than the clamp is drawn over the logos.")
        print("\n1 failed")
        return 1

    draw = ImageDraw.Draw(Image.new("RGB", (4, 4)))

    def card_for(h):
        # This lineage sizes the card from the height, so the width follows
        # the gap the score needs.
        probe = GameRenderer(128, h, {})
        return max(128, h * 2 + probe._center_gap_width())

    print("the score fits the gap it is centred in")
    for h in HEIGHTS:
        r = GameRenderer(card_for(h), h, {})
        score_w = draw.textlength(WORST_SCORE, font=r.fonts["score"])
        gap = r._center_gap_width()
        check("h=%-3d score %dpx fits the %dpx gap" % (h, score_w, gap),
              score_w <= gap)
        check("h=%-3d gap leaves a gutter each side" % h,
              (gap - score_w) / 2 >= GameRenderer._SCORE_LOGO_GUTTER_PX - 1)

    print("\nthe logos never reach into the gap")
    for h in HEIGHTS:
        card = card_for(h)
        r = GameRenderer(card, h, {})
        check("h=%-3d two logos + gap fit the %dpx card" % (h, card),
              r._logo_slot_width() * 2 + r._center_gap_width() <= card)

    print("\nthe logos get the full card height (no dead space)")
    for h in HEIGHTS:
        r = GameRenderer(card_for(h), h, {})
        check("h=%-3d logo slot %dpx >= height" % (h, r._logo_slot_width()),
              r._logo_slot_width() >= h)

    print("\nthe gap follows the score, not the card width")
    r = GameRenderer(card_for(64), 64, {})
    before = r._center_gap_width()
    r.fonts["score"] = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 24)
    after = r._center_gap_width()
    big = draw.textlength(WORST_SCORE, font=r.fonts["score"])
    check("a 24px score (%dpx wide) widens the gap %d -> %d" % (big, before, after),
          after > before)
    check("...and the widened gap actually holds it", big <= after)

    print("\na ratio-driven gap must be measured at the width actually used")
    # _center_gap_width() scales with display_width when center_gap_ratio
    # drives it rather than the score reserve. Sizing the card from a gap
    # measured at a 128px probe therefore underestimates the gap at the final
    # width, and the logos quietly get less than the full height the card was
    # supposed to give them. scroll_display settles the two together.
    #
    # Scope: this pins the RENDERER property that makes settling necessary.
    # The loop itself lives in ScrollDisplay._default_game_card_width, which
    # needs a display manager and is not constructed here.
    ratio_cfg = {"scroll_card": {"center_gap_ratio": 0.5,
                                 "center_gap_min": 22, "center_gap_max": 300}}
    h = 64
    naive = max(128, h * 2 + GameRenderer(128, h, ratio_cfg)._center_gap_width())
    check("a gap measured at 128px leaves the logos short (%dpx slot)"
          % GameRenderer(naive, h, ratio_cfg)._logo_slot_width(),
          GameRenderer(naive, h, ratio_cfg)._logo_slot_width() < h)
    settled = 128
    for _ in range(12):
        nxt = max(128, h * 2 + GameRenderer(settled, h, ratio_cfg)._center_gap_width())
        if nxt == settled:
            break
        settled = nxt
    check("settling on the final width restores full-height logos (%dpx)"
          % GameRenderer(settled, h, ratio_cfg)._logo_slot_width(),
          GameRenderer(settled, h, ratio_cfg)._logo_slot_width() >= h)

    failed = [c for c, ok in results if not ok]
    print("\n%d checks, %d failed" % (len(results), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
