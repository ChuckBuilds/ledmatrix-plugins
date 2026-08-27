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

Run: <core-venv>/bin/python plugins/baseball-scoreboard/test_favorites_are_prioritised.py
"""

import logging
import os
import sys
import time
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
            "home_id": 1000 + i,
            "away_id": 2000 + i,
            "broadcast": "",
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
    obj.other_rotation_interval_seconds = 0      # pinned unless a test asks
    obj._other_window_start = 0
    obj._other_window_rotated_at = 0.0
    obj.other_games_min_quality = "any"          # filters off unless a test asks
    obj.other_games_divisions = []
    obj._team_rankings_cache = {}
    obj._division_team_ids = {}
    obj.logger = logging.getLogger("prioritised_probe")
    return obj


def abbrs(games):
    return ["%s@%s" % (g["away_abbr"], g["home_abbr"]) for g in games]


def main():
    os.chdir(str(CORE))
    import sports

    games = schedule()
    # Both spellings of the same two games. Most plugins match favourites by
    # abbreviation; nrl matches by ESPN team id, because NRL abbreviations are
    # not unique ("NEW" is two different clubs). Supplying both keeps this
    # fixture honest for either matcher instead of quietly testing nothing.
    favs = ["UGA", "AUB", "2040", "1041"]

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
    many = ["T%02dA" % i for i in range(30, 42)] + [str(2000 + i) for i in range(30, 42)]
    obj = make(sports, many, 3, 1)
    names = abbrs(obj._favorites_first(games, 3, 1))
    check("favourites capped at the limit", len(names) == 4, names)

    print("\nfewer favourite games than the limit: others fill the rest")
    obj = make(sports, ["UGA", "2040"], 5, 2)
    names = abbrs(obj._favorites_first(games, 5, 2))
    fav_picked = [n for n in names if "UGA" in n]
    check("the one favourite game is shown", len(fav_picked) == 1, names)
    check("others are not inflated to cover the shortfall",
          len(names) == 3, names)

    print("\nno favourite games at all in the window: still shows other games")
    obj = make(sports, ["ZZZ", "999999"], 3, 2)
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

    print("\nthe other-games window rotates, so variety comes from turnover")
    # A bigger pool would make a lap longer -- roughly one card per visit --
    # so the board keeps a short pool and moves the window instead.
    obj = make(sports, favs, 3, 2)
    obj.other_rotation_interval_seconds = 1800
    first = abbrs(obj._favorites_first(games, 3, 2))
    others_first = [n for n in first if "UGA" not in n and "AUB" not in n]

    obj._other_window_rotated_at = time.monotonic() - 1801   # one interval on
    second = abbrs(obj._favorites_first(games, 3, 2))
    others_second = [n for n in second if "UGA" not in n and "AUB" not in n]

    check("a later window shows different other games",
          others_first != others_second, (others_first, others_second))
    check("consecutive windows do not overlap",
          not (set(others_first) & set(others_second)),
          (others_first, others_second))
    check("favourites are NOT rotated -- still the soonest",
          [n for n in first if "UGA" in n or "AUB" in n]
          == [n for n in second if "UGA" in n or "AUB" in n], (first, second))

    print("\nrotation interval 0 pins the window")
    obj = make(sports, favs, 3, 2)
    a = abbrs(obj._favorites_first(games, 3, 2))
    obj._other_window_rotated_at = time.monotonic() - 99999
    b = abbrs(obj._favorites_first(games, 3, 2))
    check("the same games come back", a == b, (a, b))

    print("\nthe window wraps rather than running off the end")
    obj = make(sports, favs, 3, 2)
    obj.other_rotation_interval_seconds = 1800
    obj._other_window_start = len(games) - 1      # near the end of the others
    wrapped = abbrs(obj._favorites_first(games, 3, 2))
    others = [n for n in wrapped if "UGA" not in n and "AUB" not in n]
    # only two favourite games exist in the fixture, so the total is 2 + 2
    check("still returns a full window of others", len(others) == 2, wrapped)
    check("the window wrapped to the start of the list",
          others == ["T01A@T01H", "T02A@T02H"], others)

    print("\nfewer other games than the limit: no rotation, show them all")
    tiny = [g for g in games if g["id"] in ("g00", "g40", "g41")]
    obj = make(sports, favs, 3, 2)
    obj.other_rotation_interval_seconds = 1800
    obj._other_window_rotated_at = time.monotonic() - 99999
    names = abbrs(obj._favorites_first(tiny, 3, 2))
    check("the single other game is still shown", len(names) == 3, names)

    print("\nquality filter: only ranked teams fill the other slots")
    # Selection is otherwise purely chronological, and on a college slate that
    # is mostly filler -- rotating harder just serves more of it.
    obj = make(sports, favs, 3, 3)
    obj.other_games_min_quality = "ranked"
    obj._team_rankings_cache = {"T05H": 4, "T09A": 12}
    names = abbrs(obj._favorites_first(games, 3, 3))
    others = [n for n in names if "UGA" not in n and "AUB" not in n]
    check("only ranked matchups fill the other slots",
          others and all("T05H" in n or "T09A" in n for n in others), others)
    check("favourites are exempt from the quality filter",
          len([n for n in names if "UGA" in n or "AUB" in n]) == 2, names)

    print("\nan empty rankings table must not empty the board")
    obj = make(sports, favs, 3, 3)
    obj.other_games_min_quality = "ranked"
    obj._team_rankings_cache = {}        # fetch failed, or rankings unavailable
    names = abbrs(obj._favorites_first(games, 3, 3))
    check("filter fails OPEN, other games still shown",
          len([n for n in names if "UGA" not in n and "AUB" not in n]) == 3, names)

    print("\ndivision filter: every participant must be in a checked division")
    obj = make(sports, favs, 3, 3)
    obj.other_games_divisions = ["fbs"]
    obj._division_team_ids = {
        "fbs": {int(g["home_id"]) for g in games[:20]},
        "fcs": {int(g["home_id"]) for g in games[20:]},
    }
    picked = obj._favorites_first(games, 3, 3)
    others = [g for g in picked if not obj._is_favorite_game(g)]
    check("a game with an unchecked-division side is dropped",
          all(int(g["home_id"]) in obj._division_team_ids["fbs"]
              and int(g["away_id"]) in obj._division_team_ids["fbs"]
              for g in others), abbrs(others))

    print("\na favourite from an unchecked division is STILL shown")
    # Someone can be genuinely into a smaller-division school; making them a
    # favourite has to keep working regardless of what the others filter says.
    obj = make(sports, favs, 3, 3)
    obj.favorite_teams = ["T45H", "1045"]                       # home_id 1045 -> the fcs set below
    obj.other_games_min_quality = "ranked"
    obj.other_games_divisions = ["fbs"]
    obj._team_rankings_cache = {"T05H": 4}
    obj._division_team_ids = {
        "fbs": {int(g["home_id"]) for g in games[:20]},
        "fcs": {int(g["home_id"]) for g in games[20:]},
    }
    picked = obj._favorites_first(games, 3, 3)
    fav = [g for g in picked if obj._is_favorite_game(g)]
    check("the small-division favourite still appears", len(fav) >= 1, abbrs(picked))

    print("\nunresolved divisions must not empty the board either")
    obj = make(sports, favs, 3, 3)
    obj.other_games_divisions = ["fbs"]
    obj._division_team_ids = {}          # lookup failed
    names = abbrs(obj._favorites_first(games, 3, 3))
    check("filter fails OPEN when divisions are unknown",
          len([n for n in names if "UGA" not in n and "AUB" not in n]) == 3, names)

    print("\nthe RECENT class must have these too, not just Upcoming")
    # SportsRecent is a SIBLING of SportsUpcoming, not a subclass. The helpers
    # first landed on Upcoming, so the recent path called a method it did not
    # have -- AttributeError, swallowed by update()'s own try/except, recent
    # games silently blank. Driving the real class is the only way to see it.
    for cls_name in ("SportsRecent", "SportsUpcoming"):
        klass = getattr(sports, cls_name)
        for attr in ("_favorites_first", "_passes_other_filters",
                     "_other_games_window", "_is_favorite_game",
                     "_game_divisions", "_is_ranked_game"):
            check(f"{cls_name} has {attr}", hasattr(klass, attr))

    recent_cls = type("RecentProbe", (sports.SportsRecent,), {
        "_fetch_data": lambda s: None,
        "_extract_game_details": lambda s, ev: None,
    })
    r = recent_cls.__new__(recent_cls)
    r.favorite_teams = favs
    r.recent_games_to_show = 3
    r.other_recent_games_to_show = 2
    r.logger = logging.getLogger("recent_probe")
    picked = r._favorites_first(games, 3, 2, newest_first=True)
    names = abbrs(picked)
    check("the recent path actually selects games", len(names) == 4, names)
    check("and its favourites are present",
          len([n for n in names if "UGA" in n or "AUB" in n]) == 2, names)

    print("\nrankings are only fetched where a poll exists")
    # NFL's rankings endpoint 404s. _fetch_team_rankings only short-circuits on
    # a NON-empty cache, so a failed fetch retries every update -- ~2,900 dead
    # requests a day per league once "ranked" became the default.
    probe = make(sports, favs, 3, 3)
    for league, expected in (("college-football", True), ("mens-college-basketball", True),
                             ("ncaa_mens", True), ("nfl", False), ("nhl", False),
                             ("mlb", False), ("", False)):
        probe.league = league
        check("%-24s rankings fetch = %s" % (league or "<unset>", expected),
              probe._league_has_rankings() is expected)

    failed = [c for c, ok in results if not ok]
    print("\n%d checks, %d failed" % (len(results), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
