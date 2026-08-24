#!/usr/bin/env python3
"""In adaptive layout the score must not be drawn across the team logos.

This is a SEPARATE defect from the classic-path one in
test_vegas_score_clears_the_logos.py, and it is the one that was actually
visible on the 512x64 rig, because that rig sets layout_mode=adaptive.

_render_game_card_adaptive() does not use _center_gap_width() or
_logo_slot_width() at all -- it takes its geometry from the CORE's
src.adaptive_layout.scoreboard_regions(), which deliberately overlaps
score_area with BOTH logo slots by half the logo's width:

    128x64: away[0,44]  score[22,106]  home[84,128]  -> 22px each side
    176x64: away[0,64]  score[32,144]  home[112,176] -> 32px each side

The score is then fitted to that region, so it grows until it spans the logos
and is drawn on top of them. Widening the card does not help: the regions
scale proportionally and the overlap stays at half the logo. So the fix is to
clamp the region to the strip between the slots before fitting.

Run: <core-venv>/bin/python plugins/football-scoreboard/test_adaptive_score_clears_logos.py
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


SIZES = ((128, 32), (128, 64), (176, 64), (236, 64), (512, 64), (256, 128))


def main():
    os.chdir(str(CORE))
    from game_renderer import GameRenderer, ADAPTIVE_AVAILABLE
    if not ADAPTIVE_AVAILABLE:
        print("SKIP: this core has no src.adaptive_layout")
        return 2
    from src.adaptive_layout import Region, scoreboard_regions

    if not hasattr(GameRenderer, "_score_clear_of_logos"):
        print("  [FAIL] GameRenderer has no _score_clear_of_logos -- the "
              "adaptive score region still spans both logo slots, so the "
              "score renders on top of the logos.")
        print("\n1 failed")
        return 1

    r = GameRenderer(128, 64, {"layout_mode": "adaptive"})

    print("the clamped region never reaches into either logo")
    for w, h in SIZES:
        regs = scoreboard_regions(Region(0, 0, w, h))
        got = r._score_clear_of_logos(regs)
        away, home = regs.away_slot, regs.home_slot
        check("%3dx%-3d starts at/after the away logo ends" % (w, h),
              got.x >= away.x + away.w)
        check("%3dx%-3d ends at/before the home logo starts" % (w, h),
              got.x + got.w <= home.x)

    print("\nit actually narrows the region (the whole point)")
    # The first version of this fix silently did nothing: the constant it
    # compared against had been defined at module scope instead of on the
    # class, and the resulting AttributeError was swallowed by a try/except,
    # so the region came back unchanged with no error logged anywhere. A
    # check that only asserted "no overlap" would NOT have caught that,
    # because the unclamped region overlaps -- this one would.
    for w, h in ((128, 64), (176, 64)):
        regs = scoreboard_regions(Region(0, 0, w, h))
        before, after = regs.score_area, r._score_clear_of_logos(regs)
        check("%3dx%-3d region narrowed %d -> %d px" % (w, h, before.w, after.w),
              after.w < before.w)

    print("\nthe vertical extent and the region type are preserved")
    regs = scoreboard_regions(Region(0, 0, 128, 64))
    got = r._score_clear_of_logos(regs)
    check("y is unchanged", got.y == regs.score_area.y)
    check("height is unchanged", got.h == regs.score_area.h)
    check("still a Region", isinstance(got, type(regs.score_area)))

    print("\na card with no usable middle keeps the original region")
    class _Tight:
        score_area = Region(0, 0, 40, 20)
        away_slot = Region(0, 0, 20, 20)
        home_slot = Region(21, 0, 19, 20)      # 1px gap: unusable
    kept = r._score_clear_of_logos(_Tight())
    check("falls back rather than collapsing to a sliver",
          kept is _Tight.score_area)

    print("\nthe gap is widened only where the bigger score rung is reachable")
    # Once the card reaches 2 x height the logos are capped at the card
    # height, so extra width goes entirely into the middle and the gap
    # decides which ladder rung the score gets. But the fitter is CONTEXT
    # dependent, not purely region-driven: the identical 88x31 region takes
    # 16px on a 64-tall card and 8px on a 48-tall one. Widening the gap where
    # the rung is unreachable would buy only dead space, so the helper probes
    # the fitter and declines.
    from game_renderer import ADAPTIVE_LADDER_HEADLINE
    target = GameRenderer._ADAPTIVE_SCORE_TARGET_PX
    for h, reachable in ((32, False), (48, False), (64, True), (96, True), (128, True)):
        probe = GameRenderer(128, h, {"layout_mode": "adaptive"})
        gap = probe._adaptive_score_gap()
        check("h=%-3d %s" % (h, "widens the gap" if reachable else
                             "declines to widen (rung unreachable)"),
              (gap > 0) is reachable)
        if not reachable:
            continue
        card = max(128, h * 2 + max(probe._center_gap_width(), gap))
        r = GameRenderer(card, h, {"layout_mode": "adaptive"})
        regs = scoreboard_regions(Region(0, 0, card, h))
        fit = r._fit_element('score', "00-00",
                             r._region_for(r._score_clear_of_logos(regs), 'score'),
                             ADAPTIVE_LADDER_HEADLINE)
        got = getattr(getattr(fit, 'font', None), 'size', 0)
        check("h=%-3d card %d actually reaches the %dpx rung (got %spx)"
              % (h, card, target, got), got >= target)

    print("\nclassic layout is untouched by any of this")
    c = GameRenderer(128, 64, {"layout_mode": "classic"})
    check("classic renderer reports no adaptive gap",
          not getattr(c, "_adaptive", False) and c._adaptive_score_gap() >= 0)

    print("\nthe status band never grows to the score's size")
    # The status band spans the FULL card width while the score is confined
    # to the strip between the logos, so widening the card for the score also
    # let "Final" reach the same 16px rung on 96- and 128-tall cards -- the
    # secondary text as large as the headline above it.
    from game_renderer import ADAPTIVE_LADDER_TEXT
    for h, card in ((64, 216), (96, 280), (128, 344), (64, 256)):
        r = GameRenderer(card, h, {"layout_mode": "adaptive"})
        seen = {}
        original = r._fit_element

        def spy(key, text, region, ladder, _o=original, _s=seen):
            fit = _o(key, text, region, ladder)
            _s[key] = getattr(getattr(fit, "font", None), "size", 0)
            return fit

        r._fit_element = spy
        logos = plugin_dir / "assets" / "sports" / "nfl_logos"
        r.render_game_card({"away_abbr": "GB", "home_abbr": "KC",
                            "away_score": "34", "home_score": "13",
                            "status_text": "Final", "game_date": "Aug 22",
                            "league": "nfl",
                            "away_logo_path": str(logos / "GB.png"),
                            "home_logo_path": str(logos / "KC.png")}, "recent")
        score, status = seen.get("score", 0), seen.get("time", 0)
        # Assert the score was fitted at all. Without logos the renderer takes
        # a text-only fallback and never fits a score, and an earlier version
        # of this check quietly skipped on that -- passing while testing
        # nothing.
        check("h=%-3d card %d: the score was actually fitted" % (h, card),
              bool(score))
        check("h=%-3d card %d: status %spx stays under score %spx"
              % (h, card, status, score), 0 < status < score)

    print("\nthe ladder cap reads the right field")
    # FontStep's field is size_px, not size. Getting that wrong made the
    # filter match nothing and the fallback quietly returned a whole ladder,
    # so the cap looked applied but did nothing.
    r = GameRenderer(216, 64, {"layout_mode": "adaptive"})
    r._adaptive_score_px = 16
    capped = r._status_ladder()
    check("a 16px score caps the band below 16px",
          all(getattr(st, "size_px", 99) < 16 for st in capped))
    r._adaptive_score_px = 0
    check("no score on the card leaves the ladder alone",
          r._status_ladder() == ADAPTIVE_LADDER_TEXT)

    failed = [c for c, ok in results if not ok]
    print("\n%d checks, %d failed" % (len(results), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
