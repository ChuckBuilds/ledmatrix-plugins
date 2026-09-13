#!/usr/bin/env python3
"""Full-screen odds must not print through the card's top-centre text.

With no favoured side, _draw_dynamic_odds centred "O/U: x" on row 0 -- the row
holding the round clock (Live), "Final"/round (Recent) and fight class
(Upcoming). The scroll renderer already avoided this in the sibling
scoreboards; the switch cards did not. Now the O/U anchors left and steps down
one text row only when it would actually overlap.

Also: a home spread of 0.0 is a real line, not a missing one, and a non-number
top-level spread no longer raises (which silently dropped every odds line).

Run: <core-venv>/bin/python plugins/ufc-scoreboard/test_odds_top_row_collision.py
"""

import logging
import os
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))
CORE = None
_core = os.environ.get("LEDMATRIX_CORE", "")
for _candidate in (_core, str(PLUGIN_DIR.parents[2] / "LEDMatrix")):
    if _candidate and (Path(_candidate) / "src" / "plugin_system").is_dir():
        CORE = Path(_candidate)
        sys.path.insert(0, _candidate)
        break
else:
    print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
    sys.exit(2)

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from ufc_managers import UFCRecentManager as MMARecent  # noqa: E402  (concrete)

FAILURES = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILURES.append(label)


def font(name, size):
    try:
        return ImageFont.truetype(str(CORE / "assets" / "fonts" / name), size)
    except OSError:
        return ImageFont.load_default()


DETAIL = font("4x6-font.ttf", 7)
TIME = font("PressStart2P-Regular.ttf", 8)


def render(width, odds, top_text):
    mgr = MMARecent.__new__(MMARecent)
    mgr.logger = logging.getLogger("odds_probe")
    mgr.config = {}
    mgr.display_width = width
    mgr.display_height = 32
    mgr.fonts = {"detail": DETAIL, "time": TIME}
    drawn = []
    mgr._draw_text_with_outline = (
        lambda draw, text, pos, font, fill=None, outline_color=None: drawn.append((text, pos)))
    draw = ImageDraw.Draw(Image.new("RGBA", (width, 32)))
    span = mgr._top_row_span(draw, top_text, TIME) if top_text else None
    mgr._draw_dynamic_odds(draw, odds, width, 32, top_span=span)
    return drawn, span


OU_ONLY = {"over_under": 2.5, "home_team_odds": {}, "away_team_odds": {}}

drawn, span = render(64, OU_ONLY, "R3 4:12")
ou = [pos for text, pos in drawn if text.startswith("O/U")]
check("64x32: O/U is drawn", len(ou) == 1, f"drawn={drawn}")
if ou:
    check("64x32: O/U anchors left rather than centring", ou[0][0] == 0, f"pos={ou[0]}")
    check("64x32: O/U steps below the round clock it would hit", ou[0][1] > 0,
          f"pos={ou[0]} top_span={span}")

drawn, _ = render(64, OU_ONLY, "")
ou = [pos for text, pos in drawn if text.startswith("O/U")]
check("no top-row text -> O/U stays on row 0", ou and ou[0][1] == 0, f"drawn={drawn}")

drawn, span = render(256, OU_ONLY, "R3 4:12")
ou = [pos for text, pos in drawn if text.startswith("O/U")]
check("256x32: nothing to hit, O/U stays on row 0", ou and ou[0] == (0, 0),
      f"drawn={drawn} top_span={span}")

drawn, _ = render(128, {"spread": -3.5, "over_under": 2.5,
                        "home_team_odds": {"spread_odds": 0.0},
                        "away_team_odds": {}}, "")
texts = [t for t, _ in drawn]
check("a 0.0 home spread is not overwritten by the top-level spread",
      "-3.5" not in texts, f"drawn={texts}")

drawn, _ = render(128, {"spread": "PK", "over_under": 2.5,
                        "home_team_odds": {}, "away_team_odds": {}}, "")
texts = [t for t, _ in drawn]
check("a non-number top-level spread does not drop the O/U line",
      any(t.startswith("O/U") for t in texts), f"drawn={texts}")

print("\n" + "=" * 60)
if FAILURES:
    print(f"{len(FAILURES)} check(s) failed: {FAILURES}")
    sys.exit(1)
print("All checks passed.")
