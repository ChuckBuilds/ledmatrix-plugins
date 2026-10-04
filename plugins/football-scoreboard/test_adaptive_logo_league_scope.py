#!/usr/bin/env python3
"""Adaptive layout: one strip, two leagues, one abbreviation, two logos.

test_logo_cache_league_scope.py covers the classic logo cache. The adaptive
path (layout_mode: "adaptive") keeps two caches of its own, and both were
keyed by abbreviation alone:

* the renderer's logo cache, keyed "MIA" (now _fitted_logo_cache, which
  holds the fitted logos; the unresized ones are no longer kept);
* the LayoutContext's fitted-image cache, keyed "logo:MIA".

One renderer draws a whole scroll strip, and a strip carries both leagues, so
whichever Miami was drawn first -- Dolphins (nfl_logos/MIA.png) or Hurricanes
(ncaa_logos/MIA.png) -- was drawn on the other's card too. Ten abbreviations
exist in both directories (CAR CIN DAL DEN HOU LAC MIA NE TB TBD).

Run: <core-venv>/bin/python plugins/football-scoreboard/test_adaptive_logo_league_scope.py
"""

import os
import sys
import tempfile
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

from PIL import Image  # noqa: E402

HURRICANES = (240, 130, 0)   # orange: ncaa_logos/MIA.png
DOLPHINS = (0, 133, 122)     # teal: nfl_logos/MIA.png

results = []


def check(case, passed, detail=""):
    results.append((case, passed))
    print("  [%s] %s%s" % ("pass" if passed else "FAIL", case,
                           ("  -- " + detail) if detail and not passed else ""))


def _count(img, colour):
    counts = img.convert("RGB").getcolors(maxcolors=img.width * img.height)
    return sum(n for n, c in counts if c == colour)


def _game(away_logo_path):
    return {
        "home_id": "1", "home_abbr": "KC", "home_logo_path": "",
        "away_id": "2", "away_abbr": "MIA", "away_logo_path": away_logo_path,
        "home_score": "21", "away_score": "17",
        "period_text": "Q3", "clock": "8:42", "is_live": True,
        "league": "nfl",
    }


def main():
    os.chdir(str(CORE))
    from game_renderer import GameRenderer, ADAPTIVE_AVAILABLE
    if not ADAPTIVE_AVAILABLE:
        print("SKIP: this core has no src.adaptive_layout")
        return 2

    tmp = Path(tempfile.mkdtemp())
    dirs = {}
    for name, colour in (("ncaa_logos", HURRICANES), ("nfl_logos", DOLPHINS)):
        d = tmp / "assets" / "sports" / name
        d.mkdir(parents=True)
        Image.new("RGBA", (60, 60), colour + (255,)).save(d / "MIA.png")
        dirs[name] = d
    # Both cards need a home logo too, or the renderer falls back to text.
    kc = tmp / "assets" / "sports" / "nfl_logos" / "KC.png"
    Image.new("RGBA", (60, 60), (200, 0, 0, 255)).save(kc)

    def game(league_dir):
        g = _game(str(dirs[league_dir] / "MIA.png"))
        g["home_logo_path"] = str(kc)
        return g

    for first, second, want, wrong in (
            ("nfl_logos", "ncaa_logos", HURRICANES, DOLPHINS),
            ("ncaa_logos", "nfl_logos", DOLPHINS, HURRICANES)):
        r = GameRenderer(128, 64, {"layout_mode": "adaptive"})
        r._render_game_card_adaptive(game(first), "live")
        card = r._render_game_card_adaptive(game(second), "live")
        check(f"after {first}, the {second} card draws its own MIA",
              _count(card, want) > 0 and _count(card, wrong) == 0,
              f"{_count(card, want)} px of its own logo, "
              f"{_count(card, wrong)} px of the other league's")

    # The same file twice is one cached fitted logo, not two.
    r = GameRenderer(128, 64, {"layout_mode": "adaptive"})
    r._render_game_card_adaptive(game("nfl_logos"), "live")
    r._render_game_card_adaptive(game("nfl_logos"), "live")
    check("the same directory and abbreviation share one fitted entry",
          sum(1 for k in r._fitted_logo_cache if k[1] == "MIA") == 1,
          str(sorted(r._fitted_logo_cache)))

    failed = [c for c, ok in results if not ok]
    print("\n%d passed, %d failed" % (len(results) - len(failed), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
