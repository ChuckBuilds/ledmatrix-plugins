#!/usr/bin/env python3
"""The adaptive upcoming card has to stack the date and time, not join them.

``switch_upcoming_center`` defaults to "date_time", which on the classic
scorebug means two rows: core sports_shared._draw_upcoming_center_switch puts
the date at center_y - 7 and the time 9px under it. The adaptive card claimed
the same thing in a comment and then did ``" ".join``, fitting "01/18 6:30PM"
as ONE string into the gap the logos leave.

A centre region is narrow by construction -- 40px on a 128x64, 20px on a
64x32 -- so the single line dropped to the bottom of the ladder trying to fit
and still did not: at 128x64 it rendered "01/18 6:" plus the face's tofu glyph,
and at the 192x48 this plugin most often runs on it ran under both logos.
Recent cards were unaffected, which is exactly how it was reported: "recent
displays the date and time perfectly, upcoming doesn't."

What this pins down:

  * date_time draws one row per line, never one joined line;
  * no row is ellipsized at any harness size -- the check that matters, and
    the one the first cut of the fix got wrong by testing ``FitResult.fits``,
    which is True on an ellipsized fit because ellipsizing is how it was made
    to fit;
  * the two rows stay together rather than at the quarter points of a tall
    gap (a 128x64's centre region is 47px, so an even split left 23px of
    black between them);
  * "vs" and "none" are untouched -- this fix is about one mode.

Asserts on what the renderer is asked to draw rather than on pixels: the
regions and strings are the layout decision, while an ink-band scan of a card
with logos on it cannot tell a second row from a logo's edge.

Run: <core-venv>/bin/python plugins/football-scoreboard/test_adaptive_upcoming_stacks.py
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


#: The eight harness sizes. The narrow ones are the point: a wide card hides
#: this bug because the joined line happens to fit.
SIZES = [(64, 32), (128, 32), (64, 64), (96, 48),
         (128, 64), (256, 32), (192, 48), (512, 64)]

DATE = "01/18"
TIME = "6:30PM"

GAME = {
    "home_abbr": "KC", "away_abbr": "PHI",
    "home_team": "KC", "away_team": "PHI",
    "home_id": "1", "away_id": "2",
    "home_score": "0", "away_score": "0",
    "home_record": "", "away_record": "",
    "league": "nfl",
    "game_date": DATE, "game_time": TIME,
    "start_time": "2026-01-18T23:30:00Z",
    "start_time_utc": "2026-01-18T23:30:00Z",
    "home_logo_url": None, "away_logo_url": None,
    "period_text": "", "clock": "", "status_text": "",
    "status": {"type": {"state": "pre"}},
    "is_live": False, "is_final": False, "is_upcoming": True,
    "is_halftime": False, "is_period_break": False, "is_tournament": False,
    "odds": None,
}


def main():
    os.chdir(str(CORE))
    from game_renderer import GameRenderer

    logos = CORE / "assets" / "sports" / "nfl_logos"
    game = dict(GAME,
                home_logo_path=logos / "KC.png",
                away_logo_path=logos / "PHI.png")
    if not (game["home_logo_path"].exists() and game["away_logo_path"].exists()):
        print("SKIP: NFL logos missing from the core checkout")
        return 2

    def draws(width, height, scroll_card, game_override=None):
        """(text, region, font size) for every fitted string the card draws."""
        config = {
            "timezone": "Etc/UTC",
            "nfl": {"enabled": True},
            "layout_mode": "adaptive",
            "scroll_card": dict(scroll_card),
            "customization": {},
            "display": {"use_short_date_format": False},
        }
        renderer = GameRenderer(width, height, config, logo_cache={},
                                switch_context=True)
        if not renderer._adaptive:
            return None
        recorded = []
        original = renderer._draw_fit_outline

        def spy(draw, fit, region, *args, **kwargs):
            recorded.append((fit.text, region, fit.size_px))
            return original(draw, fit, region, *args, **kwargs)

        renderer._draw_fit_outline = spy
        renderer.render_game_card(game_override or game, "upcoming")
        return recorded

    probe = draws(128, 64, {})
    if probe is None:
        print("SKIP: this core has no adaptive layout system")
        return 2

    # -- 1. two rows, one per line, at every size ---------------------------
    two_rows, unellipsized, together, covered = [], [], [], 0
    for width, height in SIZES:
        recorded = draws(width, height, {})
        covered += 1
        texts = [text for text, _, _ in recorded]
        two_rows.append((width, height, texts == [DATE, TIME]))
        unellipsized.append((width, height,
                             all(text in (DATE, TIME) for text in texts)))
        if len(recorded) == 2:
            (_, first, _), (_, second, _) = recorded
            gap = second.y - first.bottom
            # Adjacent: the rows may touch or sit a hair apart, never a row's
            # height apart. That is the even-split layout this replaced.
            together.append((width, height,
                             0 <= second.y - first.y and gap < first.h))
        else:
            together.append((width, height, False))

    # Assert the COUNT as well: a matrix that silently lost its sizes reports
    # no failures and reads as a pass.
    check("every harness size was rendered", covered == len(SIZES))
    check("date and time are drawn as two rows, never one joined line",
          all(ok for _, _, ok in two_rows))
    check("no row is ellipsized on any panel",
          all(ok for _, _, ok in unellipsized))
    check("the two rows sit together, not at the quarter points of the gap",
          all(ok for _, _, ok in together))

    for width, height, ok in two_rows:
        if not ok:
            print("      %dx%d drew %r" % (width, height,
                                           [t for t, _, _ in draws(width, height, {})]))

    # -- 2. the narrow-panel fallback widens instead of truncating ----------
    # 64x32 leaves about 20px between the logos, which no full row fits. The
    # classic scorebug centres these rows on the whole panel in that case;
    # drawing over a logo beats drawing "01/" and a tofu glyph.
    narrow = draws(64, 32, {})
    check("a gap too narrow for a row widens to the panel",
          len(narrow) == 2 and all(region.w > 64 // 2
                                    for _, region, _ in narrow))

    # -- 3. the other two modes are untouched ------------------------------
    vs_mode = draws(192, 48, {"switch_upcoming_center": "vs", "vs_text": "@"})
    check("vs still draws the separator and not the stacked pair",
          [text for text, _, _ in vs_mode][:1] == ["@"])
    none_mode = draws(192, 48, {"switch_upcoming_center": "none"})
    check("none still draws no centre",
          DATE not in [text for text, _, _ in none_mode])

    # -- 4. hiding one line leaves the other whole -------------------------
    date_only = draws(192, 48, {"switch_show_time": False})
    check("switch_show_time off leaves the date alone on its row",
          [text for text, _, _ in date_only] == [DATE])


    # -- 5. one size for the pair, and the same size whatever the kick-off --
    # Fitted independently the rows disagree: the ladder gives each the
    # largest rung that fits its own band, and in a 40px gap "01/18" reached
    # press_start 8 where "6:30PM" only reached 4x6-font 7 -- a two-row block
    # in two faces and two sizes. And because the rung then depends on the
    # string, an afternoon kick-off ("12:30PM", one character longer) could
    # land a rung below the evening one on the same panel, so the card would
    # change size game to game.
    KICKOFFS = [("01/18", "6:30PM"), ("01/18", "12:30PM"),
                ("12/28", "11:00AM"), ("01/18", "1:05PM")]
    one_size, stable = [], []
    for width, height in SIZES:
        seen = set()
        for date_text, time_text in KICKOFFS:
            recorded = draws(width, height, {},
                             dict(game, game_date=date_text, game_time=time_text))
            sizes = {size for _, _, size in recorded}
            one_size.append((width, height, len(sizes) == 1))
            seen |= sizes
            # Never ellipsized for any of them either.
            one_size.append((width, height,
                             [text for text, _, _ in recorded]
                             == [date_text, time_text]))
        stable.append((width, height, len(seen) == 1))
    check("both rows are set at one size on every panel",
          all(ok for _, _, ok in one_size))
    check("the size does not change with the kick-off string",
          all(ok for _, _, ok in stable))

    # -- 6. one rung on every board, not one per board ---------------------
    # The general text ladder has nothing between 16 and 8 (PressStart2P is
    # only crisp at multiples of 8), so the gap width alone decided the rung:
    # 128x64's 40px gap got 4x6-font 7, 256x64's 58px got press_start 8 and
    # 512x64's 314px got press_start 16 -- three different treatments of the
    # same sentence, on boards of the same height. The stack has its own
    # one-rung ladder now, and a gap too narrow widens the box rather than
    # shrinking the type.
    rungs = set()
    for width, height in SIZES:
        recorded = draws(width, height, {})
        rungs |= {size for _, _, size in recorded}
    check("every panel draws the pair at the same rung", len(rungs) == 1)
    if len(rungs) != 1:
        print("      rungs seen: %s" % sorted(rungs))

    # -- 7. the smaller face is a floor, not a fit step ---------------------
    # "Fri Sep 19" is 80px at that rung and a 64x32 is 64px wide, so there is
    # nowhere left to widen to. Dropping a rung beats truncating -- but only
    # here, and the same date on any wider board stays on the pinned rung.
    long_date = dict(game, game_date="Fri Sep 19")
    floor = draws(64, 32, {}, long_date)
    wider = draws(128, 32, {}, long_date)
    check("a row no panel can hold at the pinned rung drops instead of "
          "truncating",
          [text for text, _, _ in floor] == ["Fri Sep 19", TIME]
          and {size for _, _, size in floor} != rungs)
    check("the same row on a wider board stays on the pinned rung",
          [text for text, _, _ in wider] == ["Fri Sep 19", TIME]
          and {size for _, _, size in wider} == rungs)

    print()
    failed = [c for c, ok in results if not ok]
    if failed:
        print("FAILED: %d of %d" % (len(failed), len(results)))
        return 1
    print("All %d checks passed." % len(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
