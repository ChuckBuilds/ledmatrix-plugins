#!/usr/bin/env python3
"""Tests that odds still draw when a game has a total but no spread.

The layout offsets used to be read inside `if favored_spread is not None`,
while the over/under block below uses them unconditionally. A game priced
with a total and no spread -- ordinary enough -- therefore raised
UnboundLocalError, and the bare `except` around the whole method swallowed
it, so the card drew no odds at all rather than drawing the total.

Run: <core-venv>/bin/python plugins/afl-scoreboard/test_odds_without_spread.py
"""

import os
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))

# This renderer imports src.logo_downloader at module scope, so the core tree
# has to be importable. LEDMATRIX_CORE points at a checkout.
_core = os.environ.get('LEDMATRIX_CORE', '')
for _candidate in (_core, str(PLUGIN_DIR.parents[2] / 'LEDMatrix')):
    if _candidate and (Path(_candidate) / 'src').is_dir():
        sys.path.insert(0, _candidate)
        break
else:
    print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
    sys.exit(2)

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("SKIP: Pillow not installed")
    sys.exit(2)

import game_renderer as gr  # noqa: E402  # pylint: disable=wrong-import-position

failures = []


def check(name, cond, detail=""):
    if cond:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s%s" % (name, (": " + detail) if detail else ""))
        failures.append(name)


def _renderer(drawn):
    r = gr.GameRenderer.__new__(gr.GameRenderer)
    r.display_width, r.display_height = 128, 64
    r.config = {}
    r.logger = type("L", (), {m: (lambda *a, **k: None)
                             for m in ("exception", "error", "warning", "debug", "info")})()
    font = ImageFont.load_default()
    r.fonts = {"detail": font, "time": font, "score": font, "team": font}
    r._layout_offset = lambda e, a, default=0: 0
    r._draw_text_with_outline = (
        lambda draw, t, xy, font, fill=None: drawn.append(t))
    return r


def main():
    draw = ImageDraw.Draw(Image.new("RGB", (128, 64)))

    print("a total with no spread still draws")
    drawn = []
    _renderer(drawn)._draw_dynamic_odds(draw, {"over_under": 47.5})
    check("the over/under reached the panel", any("47.5" in t for t in drawn),
          "drew %r" % drawn)

    print("\nand the ordinary case is unchanged")
    drawn = []
    _renderer(drawn)._draw_dynamic_odds(draw, {
        "spread": -3.5, "over_under": 47.5,
        "home_team_odds": {"spread_odds": -3.5},
        "away_team_odds": {"spread_odds": 3.5},
    })
    check("both spread and total drew", len(drawn) >= 2, "drew %r" % drawn)

    print("\na spread with no total still draws")
    drawn = []
    _renderer(drawn)._draw_dynamic_odds(draw, {
        "spread": -3.5,
        "home_team_odds": {"spread_odds": -3.5},
        "away_team_odds": {"spread_odds": 3.5},
    })
    check("the spread reached the panel", any("3.5" in t for t in drawn),
          "drew %r" % drawn)

    print("\nempty odds draw nothing")
    drawn = []
    _renderer(drawn)._draw_dynamic_odds(draw, {})
    check("nothing drawn", not drawn, "drew %r" % drawn)

    print("\n%s" % ("FAILED: %d" % len(failures) if failures
                    else "All checks passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
