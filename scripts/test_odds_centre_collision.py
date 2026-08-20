#!/usr/bin/env python3
"""Green odds labels must not overprint the time in the middle of the card.

Both odds labels are anchored to the edges of the top row, and the card centres
its time text on that same row. On a full-width panel there is room for all
three. On a Vegas game card there is not: six of these plugins pin the card to
128px regardless of panel width (`game_card_width: 128`), and at that size
"O/U: 60.5" runs from x=0 to x=54 while "8:00 PM" occupies 36..92 -- an 18px
overprint that leaves both unreadable.

Reproduced on a 512x64 rig by rendering the same upcoming game at both widths
with the rig's own config. The full-width render was clean; the 128px card was
not. Nothing was wrong with the odds themselves -- the spread value and the
favoured side were verified correct against ten live ESPN games.

Whether it bites depends on the configured font, which is why it survived: with
the default 4x6 detail font "O/U: 60.5" is 30px against a 32px budget and fits
by two pixels. The rig configures PressStart2P, which makes it 54px.

Each renderer now budgets a side against the widest time string the centre can
hold, measured in the font it will actually use, and drops the O/U -- the
longer and less useful of the two -- when it will not fit.

Run: <core-venv>/bin/python scripts/test_odds_centre_collision.py
"""

import inspect
import json
import logging
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
failures = []

# The card width these plugins pin, and a full panel for the control case.
CARD_WIDTH = 128
PANEL_WIDTH = 512

ODDS = {
    "details": "X -38.5", "over_under": 60.5, "spread": -38.5,
    "home_team_odds": {"money_line": None, "spread_odds": None},
    "away_team_odds": {"money_line": None, "spread_odds": None},
}

# A wide detail font, which is what exposes the collision. PressStart2P is what
# the rig that hit this has configured.
CFG = {"customization": {"detail_text": {"font": "PressStart2P-Regular.ttf",
                                         "font_size": 6},
                         "time": {}}}

PROBE = r'''
import json, logging, inspect, sys
from PIL import Image, ImageDraw
logging.basicConfig(level=logging.CRITICAL)
from game_renderer import GameRenderer
cfg = json.loads(sys.argv[1]); odds = json.loads(sys.argv[2])
res = {}
for w in (int(sys.argv[3]), int(sys.argv[4])):
    r = GameRenderer(w, 64, cfg, {}, logging.getLogger("q")); r.display_width = w
    img = Image.new("RGB", (w, 64)); dr = ImageDraw.Draw(img)
    # Dispatch on parameter NAMES, not count: baseball's fourth parameter is
    # `top_span`, not `height`, and passing the width into it draws nothing at
    # all -- which reads as a defect when it is only a bad call.
    params = inspect.signature(r._draw_dynamic_odds).parameters
    kwargs = {}
    if "width" in params:
        kwargs["width"] = w
    if "height" in params:
        kwargs["height"] = 64
    r._draw_dynamic_odds(dr, odds, **kwargs)
    px = img.load()
    tw = dr.textlength("12:00 PM", font=r.fonts.get("time", r.fonts["detail"]))
    c0, c1 = int((w - tw) / 2), int((w + tw) / 2)
    green = lambda xs: sum(1 for y in range(64) for x in xs
                           if px[x, y][1] > 150 and px[x, y][0] < 100 and px[x, y][2] < 100)
    res[w] = {"total": green(range(w)), "centre": green(range(c0, c1 + 1))}
print(json.dumps(res))
'''


def check(label, ok):
    print(("  PASS  " if ok else "  FAIL  ") + label)
    if not ok:
        failures.append(label)


def probe(plugin_dir):
    out = subprocess.run(
        [sys.executable, "-c", PROBE, json.dumps(CFG), json.dumps(ODDS),
         str(CARD_WIDTH), str(PANEL_WIDTH)],
        cwd=plugin_dir, capture_output=True, text=True,
        env={"PYTHONPATH": f"{_core()}:{plugin_dir}", "PATH": "/usr/bin:/bin"},
    )
    if out.returncode != 0:
        return None, (out.stderr or "").strip().splitlines()[-1:] or ["no output"]
    return json.loads(out.stdout.strip().splitlines()[-1]), None


def _core():
    for candidate in (Path("/home/rackpi/projects/LEDMatrix"), REPO.parent / "LEDMatrix"):
        if (candidate / "src" / "common" / "__init__.py").exists():
            return str(candidate)
    return ""


def main():
    if not _core():
        print("  SKIP  no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
        return 0

    print("no odds label may intrude on the centre of the row")
    renderers = sorted((REPO / "plugins").glob("*/game_renderer.py"))
    check(f"{len(renderers)} game renderers found", len(renderers) >= 6)

    for path in renderers:
        plugin = path.parent.name
        source = path.read_text(encoding="utf-8")
        if "_draw_dynamic_odds" not in source:
            continue
        if "_odds_would_hit_top_row" in source:
            # baseball-scoreboard already solves this, and better: rather than
            # dropping a label it measures the card's own top-row text and
            # steps the odds down a row when they would collide, keeping both.
            # Its answer puts the labels in the same columns but a row lower,
            # so the column test below would fail a correct implementation.
            print(f"  SKIP  {plugin}: solves this by stepping down a row, not "
                  "by dropping a label")
            continue
        res, err = probe(str(path.parent))
        if res is None:
            check(f"{plugin}: renders odds", False)
            print(f"        {err[0]}")
            continue
        card, panel = res[str(CARD_WIDTH)], res[str(PANEL_WIDTH)]
        check(f"{plugin}: nothing green in the centre of a {CARD_WIDTH}px card "
              f"({card['centre']}px there)", card["centre"] == 0)
        check(f"{plugin}: a {CARD_WIDTH}px card still shows the spread "
              f"({card['total']}px green)", card["total"] > 0)
        check(f"{plugin}: a {PANEL_WIDTH}px panel still shows both labels "
              f"({panel['total']}px green)", panel["total"] > card["total"])

    print("\n%s" % ("FAILED: %d" % len(failures) if failures else "All checks passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
