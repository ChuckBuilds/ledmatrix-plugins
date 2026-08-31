#!/usr/bin/env python3
"""The adaptive card honours the same text colours as the classic one.

The adaptive path draws its text through ladder-fitted faces that are not
element-owned, so the identity lookup that colours the classic card cannot
resolve them -- each adaptive draw site names its element's colour instead,
by the same rule: the colour follows the face the text is set in.

    period_text   the clock and period, a recent card's "Final",
                  an upcoming card's kickoff time (all set in the time face)
    score_text    the score, and the stacked date+time centre that stands in
                  for it (set in the score face)
    detail_text   the bottom band's date line (set in the detail face)

Records, timeouts and the semantic fills (scoring events, down & distance,
the favourite-result tint) keep their own colours, exactly as in classic.

Run: <core-venv>/bin/python plugins/football-scoreboard/test_adaptive_text_colors.py
"""

import os
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN))

CORE = None
for _c in (os.environ.get("LEDMATRIX_CORE", ""),
           str(PLUGIN.parents[2] / "LEDMatrix"),
           str(Path.home() / "projects" / "LEDMatrix"),
           str(Path.home() / "Github" / "LEDMatrix")):
    if _c and (Path(_c) / "assets" / "fonts").is_dir():
        CORE = Path(_c)
        break
if CORE is None:
    print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
    sys.exit(2)
os.chdir(str(CORE))
sys.path.insert(0, str(CORE))

from PIL import Image  # noqa: E402

import game_renderer  # noqa: E402

if not game_renderer.ADAPTIVE_AVAILABLE:
    print("SKIP: this core has no adaptive layout system")
    sys.exit(2)

PERIOD = (0, 240, 240)
SCORE = (240, 200, 0)
DETAIL = (240, 0, 240)
SENTINELS = {"period_text": PERIOD, "score_text": SCORE, "detail_text": DETAIL}

#: Solid dark squares, so no logo pixel can be mistaken for a sentinel.
LOGO = PLUGIN / "test" / "_adaptive_color_logo.png"


def game():
    return {
        "away_abbr": "KC", "home_abbr": "BUF",
        "away_logo_path": str(LOGO), "home_logo_path": str(LOGO),
        "away_score": "17", "home_score": "21",
        "period_text": "Q3", "clock": "8:44", "is_live": True,
        "game_date": "9/19", "game_time": "12:00 PM",
        "away_timeouts": 3, "home_timeouts": 3,
        "league": "nfl",
    }


def colors_in(img):
    rgb = img.convert("RGB")
    pixels = {color for _, color in rgb.getcolors(rgb.width * rgb.height)}
    return {name for name, value in SENTINELS.items() if value in pixels}


def render(config, game_type):
    cfg = {"layout_mode": "adaptive"}
    cfg.update(config)
    r = game_renderer.GameRenderer(128, 64, cfg)
    return r._render_game_card_adaptive(game(), game_type)


results = []


def check(case, passed):
    results.append((case, passed))
    print("  [%s] %s" % ("pass" if passed else "FAIL", case))


def main():
    Image.new("RGBA", (48, 48), (10, 10, 40, 255)).save(LOGO)
    try:
        colored = {"customization": {k: {"text_color": list(v)}
                                     for k, v in SENTINELS.items()}}

        seen = colors_in(render(colored, "live"))
        check("live: the clock takes period_text's colour", "period_text" in seen)
        check("live: the score takes score_text's colour", "score_text" in seen)

        seen = colors_in(render(colored, "recent"))
        check("recent: 'Final' takes period_text's colour", "period_text" in seen)
        check("recent: the date takes detail_text's colour", "detail_text" in seen)

        seen = colors_in(render(colored, "upcoming"))
        check("upcoming: the kickoff time takes period_text's colour",
              "period_text" in seen)
        check("upcoming: the date takes detail_text's colour", "detail_text" in seen)
        check("upcoming: the centre takes score_text's colour", "score_text" in seen)

        stacked = dict(colored)
        stacked["scroll_card"] = {"upcoming_center": "date_time"}
        seen = colors_in(render(stacked, "upcoming"))
        check("stacked centre stands in for the score, so score_text colours it",
              "score_text" in seen)

        for game_type in ("live", "recent", "upcoming"):
            seen = colors_in(render({}, game_type))
            check("no colours configured: %s card carries no sentinel" % game_type,
                  not seen)
    finally:
        LOGO.unlink(missing_ok=True)

    failed = [c for c, ok in results if not ok]
    if failed:
        print("FAILED: %d of %d" % (len(failed), len(results)))
        return 1
    print("All %d checks passed." % len(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
