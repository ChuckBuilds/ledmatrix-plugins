#!/usr/bin/env python3
"""The over/under must survive beside the centre status text.

The odds sit at the two ends of the top row and the game status sits in the
middle of it, so they share that row. The budget was:

    centre_reserve = textlength("12:00 PM")        # widest a card could hold
    side_budget    = (card_width - centre_reserve) / 2
    if ou_width > side_budget: return               # over/under dropped

Two problems compounded. The reserve was the worst case for *any* card, so a
finished card paid 24px for a kickoff time it never draws. And "O/U: 45.5" was
all-or-nothing -- no room meant no number at all, on a 128px card where the
budget came to 32px against a 35px label.

The result was that the over/under was dropped on live cards, which are the
ones anyone is actually watching.

Now the reserve measures what this card really centres, and the label sheds
its prefix before it sheds the number: "O/U: 45.5" -> "O/U 45.5" -> "O/U45.5"
-> "45.5". Position still says which number it is.

Run: <core-venv>/bin/python plugins/football-scoreboard/test_odds_survive_the_centre.py
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


def greenish(px):
    r, g, b = px[:3]
    return g > 110 and g > r + 40 and g > b + 40


def game(game_type):
    g = {"home_id": "1", "away_id": "2", "home_abbr": "TB", "away_abbr": "DAL",
         "home_score": "21", "away_score": "17", "league": "nfl",
         "home_logo_path": "assets/sports/nfl_logos/TB.png",
         "away_logo_path": "assets/sports/nfl_logos/DAL.png",
         "odds": {"spread": -3.5, "over_under": 45.5,
                  "home_team_odds": {"spread_odds": -3.5},
                  "away_team_odds": {"spread_odds": 3.5}}}
    if game_type == "live":
        g.update(period_text="Q4", clock="02:34", status_text="Q4 02:34", is_live=True)
    elif game_type == "recent":
        g.update(period_text="Final", status_text="Final", is_final=True, game_date="01/13")
    else:
        g.update(status_text="Next Game", game_date="01/18", game_time="6:30PM")
    return g


def main():
    os.chdir(str(CORE))
    from game_renderer import GameRenderer
    cfg = {"nfl": {"display_options": {"show_odds": True}}}

    print("both odds render on every card type, at both panel heights")
    for height in (32, 64):
        for game_type in ("live", "recent", "upcoming"):
            r = GameRenderer(128, height, cfg)
            img = r.render_game_card(game(game_type), game_type).convert("RGB")
            px = img.load()
            w, h = img.size
            ou = sum(1 for x in range(0, 60) for y in range(0, h // 2)
                     if greenish(px[x, y]))
            spread = sum(1 for x in range(w - 50, w) for y in range(0, h // 2)
                         if greenish(px[x, y]))
            check("%3dpx %-8s over/under drawn" % (height, game_type), ou > 0)
            check("%3dpx %-8s spread drawn" % (height, game_type), spread > 0)

    print("\nthe label sheds its prefix rather than the number")
    from PIL import Image, ImageDraw
    r = GameRenderer(128, 64, cfg)
    d = ImageDraw.Draw(Image.new("RGB", (4, 4)))
    font = r.fonts["detail"]
    widths = [d.textlength(t, font=font)
              for t in ("O/U: 45.5", "O/U 45.5", "O/U45.5", "45.5")]
    check("each fallback is narrower than the last",
          all(widths[i] > widths[i + 1] for i in range(len(widths) - 1)))
    check("the bare number is small enough to survive a wide centre",
          widths[-1] <= 32)

    print("\nthe reserve tracks the card, not the worst case")
    live = r._centre_row_text(game("live"), "live")
    recent = r._centre_row_text(game("recent"), "recent")
    check("a live card reserves for its clock", live == "Q4 02:34")
    check("a finished card reserves only for 'Final'", recent == "Final")
    check("a finished card reserves less than a live one", len(recent) < len(live))

    print()
    failed = [c for c, ok in results if not ok]
    print("FAILED: %d" % len(failed) if failed else "All checks passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
