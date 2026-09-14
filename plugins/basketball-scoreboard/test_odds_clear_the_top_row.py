#!/usr/bin/env python3
"""Full-screen odds must not print through the scorebug's top-centre text.

With no favoured side, _draw_dynamic_odds centred "O/U: 220.5" on row 0 --
the row that holds "Final", the quarter and clock, and "Next Game". The scroll
cards in game_renderer.py already anchor it left and step the odds down a row
on collision; the full-screen copy never got that rule. Two smaller spread
bugs rode along: a home spread of 0.0 (a pick'em) was treated as missing and
replaced by the top-level spread, and that spread was negated without checking
it was a number, which raised and dropped the whole odds line.

Draw calls are recorded rather than rasterised: the point is where each label
goes relative to the top-row span.

Run: <core-venv>/bin/python plugins/basketball-scoreboard/test_odds_clear_the_top_row.py
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


def main():
    os.chdir(str(CORE))
    from PIL import Image, ImageDraw
    import sports

    class Bug(sports.SportsCore):
        def __init__(self, width, height):
            self.config = {}
            self.display_width = width
            self.display_height = height
            self.logger = logging.getLogger("test")
            self.fonts = sports.SportsCore._load_fonts(self)
            self.drawn = []

        def _draw_text_with_outline(self, draw, text, position, font, fill=None, **kw):
            self.drawn.append((text, position))

        def _custom_scorebug_layout(self, game, draw):  # pragma: no cover
            raise NotImplementedError

        def _extract_game_details(self, game_event):  # pragma: no cover
            raise NotImplementedError

        def _fetch_data(self):  # pragma: no cover
            raise NotImplementedError

    def draw_odds(width, odds, top_text="Final"):
        bug = Bug(width, 32)
        draw = ImageDraw.Draw(Image.new("RGB", (width, 32)))
        span = None
        if top_text:
            w = draw.textlength(top_text, font=bug.fonts["time"])
            left = (width - w) // 2
            span = (left, left + w)
        bug._draw_dynamic_odds(draw, odds, width, 32, top_span=span)
        font = bug.fonts.get("odds") or bug.fonts["detail"]
        placed = {text: (x, y, draw.textlength(text, font=font))
                  for text, (x, y) in bug.drawn}
        return placed, span

    def overlaps(label, span):
        x, y, w = label
        return y == 0 and x < span[1] + 1 and x + w > span[0] - 1

    # 64 wide: "O/U: 220.5" cannot fit beside a centred "Final".
    placed, span = draw_odds(64, {"over_under": 220.5})
    ou = placed.get("O/U: 220.5")
    check("64x32, O/U only: the O/U is drawn", ou is not None)
    check("64x32, O/U only: it no longer overprints the top-centre text",
          ou is not None and not overlaps(ou, span))
    check("64x32, O/U only: it stepped down a row rather than vanish",
          ou is not None and ou[1] > 0)

    # 192 wide: left-anchored O/U clears "Final", so it stays on row 0.
    placed, span = draw_odds(192, {"over_under": 220.5})
    ou = placed.get("O/U: 220.5")
    check("192 wide: a label that fits stays on the top row",
          ou is not None and ou[1] == 0 and not overlaps(ou, span))

    # No top-row text at all: nothing to avoid.
    placed, _ = draw_odds(64, {"over_under": 220.5}, top_text=None)
    check("no top text: odds stay on row 0", placed.get("O/U: 220.5", (0, 1))[1] == 0)

    # Home pick'em is not "missing".
    placed, _ = draw_odds(192, {"home_team_odds": {"spread_odds": 0.0},
                                "spread": -3.5, "over_under": 210})
    check("a home spread of 0.0 is not replaced by the top-level spread",
          "-3.5" not in placed)

    # A non-numeric top-level spread must not drop the whole odds line.
    placed, _ = draw_odds(192, {"spread": "EVEN", "over_under": 210})
    check("a non-numeric top-level spread still lets the O/U draw",
          "O/U: 210" in placed)

    # A favoured side still draws spread and O/U on opposite edges.
    placed, _ = draw_odds(192, {"home_team_odds": {"spread_odds": -6.5},
                                "away_team_odds": {"spread_odds": 6.5},
                                "over_under": 221.5})
    spread, ou = placed.get("-6.5"), placed.get("O/U: 221.5")
    check("home favoured: spread right, O/U left",
          spread is not None and ou is not None and spread[0] > ou[0])

    failed = [c for c, ok in results if not ok]
    print("\n%d checks, %d failed" % (len(results), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
