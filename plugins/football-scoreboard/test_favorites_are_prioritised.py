#!/usr/bin/env python3
"""Favourites must appear even when "show favorite teams only" is off.

Reported as: "I want to see my favorites and other teams, not ONLY my
favorites, which is why it was off. Shouldn't we still prioritize favorites in
upcoming and recent even if 'show favorites only' is off?"

They should, and they did not. The flag was the whole story: on, and you saw
nothing but your teams; off, and your teams were ignored *entirely* -- the
selection took the next N games league-wide. On a real board that is 946
upcoming college games in the window, so a UGA fan saw UGA about as often as
chance allowed. There was no way to ask for "my teams, plus some others",
which is what almost everyone actually wants.

`_favorites_first` is that middle setting. Both limits are TOTALS here rather
than per-team budgets: in favourites-only mode `upcoming_games_to_show` is per
team, which is fine when the list is your own handful of teams, but AP_TOP_10
resolves to a dozen and three games each is 28 cards before a single other game
is added.

Run: <core-venv>/bin/python plugins/football-scoreboard/test_favorites_are_prioritised.py
"""

import os
import sys
from datetime import datetime, timedelta, timezone
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

results = []
NOW = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)


def check(case, passed, detail=""):
    results.append((case, passed))
    print("  [%s] %s%s" % ("pass" if passed else "FAIL", case,
                           "" if passed else "  <- " + str(detail)))


def schedule():
    """A college-shaped week: two favourite games buried in a pile of others.

    The favourites sit at positions 40 and 41 of 60 deliberately. Anything that
    merely takes the first N chronologically will miss them, which is the bug.
    """
    games = []
    for i in range(60):
        if i == 40:
            away, home = "UGA", "BAMA"
        elif i == 41:
            away, home = "TENN", "AUB"
        else:
            away, home = "T%02dA" % i, "T%02dH" % i
        games.append({
            "id": "g%02d" % i,
            "away_abbr": away,
            "home_abbr": home,
            "start_time_utc": NOW + timedelta(hours=i),
            "is_upcoming": True,
            "is_final": False,
            "is_live": False,
        })
    return games


def make(sports, favorites, fav_limit, other_limit):
    """A bare object with just the attributes _favorites_first reads.

    SportsUpcoming is abstract, so subclass it with the two data hooks stubbed.
    Nothing here calls them -- the selection is being tested on a fixed
    schedule, not a fetch -- but the class cannot be instantiated without them.
    """
    cls = type("Probe", (sports.SportsUpcoming,), {
        "_fetch_data": lambda s: None,
        "_extract_game_details": lambda s, ev: None,
    })
    obj = cls.__new__(cls)
    obj.favorite_teams = favorites
    obj.upcoming_games_to_show = fav_limit
    obj.other_upcoming_games_to_show = other_limit
    obj.recent_games_to_show = fav_limit
    obj.other_recent_games_to_show = other_limit
    return obj


def abbrs(games):
    return ["%s@%s" % (g["away_abbr"], g["home_abbr"]) for g in games]


def main():
    os.chdir(str(CORE))
    import sports

    games = schedule()
    favs = ["UGA", "AUB"]

    print("favourites set, only-flag off: they appear, and so do others")
    obj = make(sports, favs, 3, 2)
    picked = obj._favorites_first(games, 3, 2)
    names = abbrs(picked)
    fav_picked = [n for n in names if "UGA" in n or "AUB" in n]
    check("both favourite games are shown", len(fav_picked) == 2, names)
    check("other games are shown too", len(names) - len(fav_picked) == 2, names)
    check("total is favourites + others", len(names) == 4, names)

    print("\nthe bug: a plain chronological take misses them entirely")
    naive = abbrs(sorted(games, key=lambda g: g["start_time_utc"])[:4])
    check("naive selection contains no favourite",
          not [n for n in naive if "UGA" in n or "AUB" in n], naive)

    print("\ncard order stays chronological, not favourites-then-others")
    times = [g["start_time_utc"] for g in picked]
    check("selected games are in time order", times == sorted(times), times)

    print("\nother_limit=0 is favourites only")
    obj = make(sports, favs, 3, 0)
    names = abbrs(obj._favorites_first(games, 3, 0))
    check("only favourite games remain",
          names and all("UGA" in n or "AUB" in n for n in names), names)

    print("\nthe favourite limit is a TOTAL, not a per-team budget")
    # 12 favourite teams, as AP_TOP_10 resolves to. Per-team would be dozens.
    many = ["T%02dA" % i for i in range(30, 42)]
    obj = make(sports, many, 3, 1)
    names = abbrs(obj._favorites_first(games, 3, 1))
    check("favourites capped at the limit", len(names) == 4, names)

    print("\nfewer favourite games than the limit: others fill the rest")
    obj = make(sports, ["UGA"], 5, 2)
    names = abbrs(obj._favorites_first(games, 5, 2))
    fav_picked = [n for n in names if "UGA" in n]
    check("the one favourite game is shown", len(fav_picked) == 1, names)
    check("others are not inflated to cover the shortfall",
          len(names) == 3, names)

    print("\nno favourite games at all in the window: still shows other games")
    obj = make(sports, ["ZZZ"], 3, 2)
    names = abbrs(obj._favorites_first(games, 3, 2))
    check("the board is not left empty", len(names) == 2, names)

    print("\nrecent mode orders newest first")
    obj = make(sports, favs, 3, 2)
    picked = obj._favorites_first(games, 3, 2, newest_first=True)
    times = [g["start_time_utc"] for g in picked]
    check("selected games are newest first",
          times == sorted(times, reverse=True), times)
    check("favourites still present in recent mode",
          len([n for n in abbrs(picked) if "UGA" in n or "AUB" in n]) == 2,
          abbrs(picked))

    failed = [c for c, ok in results if not ok]
    print("\n%d checks, %d failed" % (len(results), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
