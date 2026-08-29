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

Run: <core-venv>/bin/python plugins/soccer-scoreboard/test_favorites_are_prioritised.py
"""

import logging
import threading
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


def division_sets(games):
    """FBS and FCS rosters covering BOTH sides of every fixture game.

    Built from home_id alone, every away side landed in "other" and the filter
    dropped the whole slate: `others` came back empty and the assertion below
    ran over an empty list, which passes. It would have passed equally against
    a filter that rejected everything, which is the failure it exists to catch.

    One game straddles on purpose -- games[0] keeps its FBS home side and is
    given an FCS away side -- because the rule under test is that EVERY
    participant has to sit in a checked division, not just the home one. It is
    the FIRST game deliberately: selection is chronological, so a straddler
    further down never competes for a slot and the assertion cannot see it.
    """
    fbs = ({int(g["home_id"]) for g in games[:20]}
           | {int(g["away_id"]) for g in games[:20]})
    fcs = ({int(g["home_id"]) for g in games[20:]}
           | {int(g["away_id"]) for g in games[20:]})
    straddler = int(games[0]["away_id"])
    fbs.discard(straddler)
    fcs.add(straddler)
    return {"fbs": fbs, "fcs": fcs}


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
    # The value and its freshness stamp have to be set together: a populated
    # cache with a zero stamp reads as stale and sends the lookup back to the
    # network, which is not what a test pre-loading divisions means.
    obj._division_loaded_at = time.monotonic()
    obj.league = "college-football"
    obj.sport = "football"
    obj.cache_manager = None
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

    print("\ndivision filter: ONE side in a checked division is enough")
    # Requiring every participant read as "FBS versus FBS only": a ranked side
    # hosting an FCS school was dropped, which on a real Week 2 slate removed
    # five of the twenty ranked matchups -- games about a team the viewer had
    # explicitly checked the box for. What the setting is for is keeping
    # FCS-versus-FCS out of a board configured for FBS.
    obj = make(sports, favs, 3, 3)
    obj.other_games_divisions = ["fbs"]
    obj._division_team_ids = division_sets(games)
    obj._division_loaded_at = time.monotonic()
    picked = obj._favorites_first(games, 3, 3)
    others = [g for g in picked if not obj._is_favorite_game(g)]
    check("the other slots are still filled", len(others) == 3, abbrs(others))
    check("the game with one checked side and one unchecked side is KEPT",
          any(g["id"] == games[0]["id"] for g in others), abbrs(others))
    check("every other game has at least one checked side",
          all(int(g["home_id"]) in obj._division_team_ids["fbs"]
              or int(g["away_id"]) in obj._division_team_ids["fbs"]
              for g in others), abbrs(others))

    # Straight at the rule, so the three cases cannot hide behind whichever
    # games happen to sort first.
    fbs_id = sorted(obj._division_team_ids["fbs"])[0]
    fcs_id = sorted(obj._division_team_ids["fcs"])[0]
    def matchup(home, away):
        return {"home_id": home, "away_id": away,
                "home_abbr": "H%d" % home, "away_abbr": "A%d" % away,
                "broadcast": ""}
    check("FBS vs FBS passes with only FBS checked",
          obj._passes_other_filters(matchup(fbs_id, fbs_id)))
    check("FBS vs FCS passes too -- one checked side is the rule",
          obj._passes_other_filters(matchup(fbs_id, fcs_id)))
    check("FCS vs FCS does not",
          not obj._passes_other_filters(matchup(fcs_id, fcs_id)))
    obj.other_games_divisions = ["fbs", "fcs"]
    check("and checking FCS brings it back",
          obj._passes_other_filters(matchup(fcs_id, fcs_id)))

    print("\na favourite from an unchecked division is STILL shown")
    # Someone can be genuinely into a smaller-division school; making them a
    # favourite has to keep working regardless of what the others filter says.
    obj = make(sports, favs, 3, 3)
    obj.favorite_teams = ["T45H", "1045"]                       # home_id 1045 -> the fcs set below
    obj.other_games_min_quality = "ranked"
    obj.other_games_divisions = ["fbs"]
    obj._team_rankings_cache = {"T05H": 4}
    obj._division_team_ids = division_sets(games)
    obj._division_loaded_at = time.monotonic()
    picked = obj._favorites_first(games, 3, 3)
    fav = [g for g in picked if obj._is_favorite_game(g)]
    check("the small-division favourite still appears", len(fav) >= 1, abbrs(picked))

    print("\nunresolved divisions must not empty the board either")
    obj = make(sports, favs, 3, 3)
    obj.other_games_divisions = ["fbs"]
    obj._division_team_ids = {}          # lookup failed
    obj._division_loaded_at = time.monotonic()
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

    print("\na failed division lookup is retried, not cached forever")
    # Holding an empty result for the life of the process meant one offline
    # moment at boot disabled division filtering until someone restarted the
    # service -- on a board running for weeks, indefinitely.
    probe = make(sports, favs, 3, 3)
    probe.league = "college-football"
    probe.sport = "football"
    probe.cache_manager = None
    calls = []

    class _Boom:
        def get(self, *a, **k):
            calls.append(1)
            raise RuntimeError("network down")

    probe.session = _Boom()
    probe._division_team_ids = None
    probe._division_loaded_at = 0.0
    probe._load_division_team_ids()
    first = len(calls)
    check("a failed lookup tried the network", first > 0, calls)

    probe._load_division_team_ids()
    check("and is not retried immediately", len(calls) == first, calls)

    probe._division_loaded_at = time.monotonic() - (probe._DIVISION_RETRY_SECONDS + 1)
    probe._load_division_team_ids()
    check("but IS retried once the short clock passes", len(calls) > first, calls)

    print("\na good lookup is held for the full day")
    probe2 = make(sports, favs, 3, 3)
    probe2.league = "college-football"
    probe2.sport = "football"
    probe2.cache_manager = None
    probe2._division_team_ids = {"fbs": {1, 2}, "fcs": {3}}
    probe2._division_loaded_at = time.monotonic() - (probe2._DIVISION_RETRY_SECONDS + 1)
    hits = []

    class _Count:
        def get(self, *a, **k):
            hits.append(1)
            raise RuntimeError("should not be called")

    probe2.session = _Count()
    probe2._load_division_team_ids()
    check("a resolved lookup is not retried on the short clock", not hits, hits)
    probe2._division_loaded_at = time.monotonic() - (probe2._DIVISION_CACHE_TTL + 1)
    probe2._load_division_team_ids()
    check("but is refreshed after a day", bool(hits), hits)

    print("\nwith no favourites configured the filters still apply")
    # Every game selected in that branch is a non-favourite game, so the
    # settings that govern non-favourite games have to reach it. They did not:
    # the branch took the next N chronologically, whatever the user had asked
    # for, and nothing said so.
    probe = make(sports, [], 3, 3)
    probe.other_games_min_quality = "ranked"
    probe._team_rankings_cache = {"T05H": 4, "T09A": 12}
    kept = probe._filtered_or_all(games)
    check("only ranked games survive", bool(kept) and all(
        g["home_abbr"] in ("T05H", "T09A") or g["away_abbr"] in ("T05H", "T09A")
        for g in kept), [g["id"] for g in kept])

    probe._team_rankings_cache = {"NOT_PLAYING_TODAY": 1}
    check("a filter that matches nothing keeps the whole list rather than "
          "blanking the mode", len(probe._filtered_or_all(games)) == len(games))

    # The helper being correct is half of it; both branches have to call it.
    # That is what was missing -- the code and the settings were both there and
    # the one line joining them was not, which no behavioural check on the
    # helper itself can see.
    import inspect
    for cls_name in ("SportsUpcoming", "SportsRecent"):
        src = inspect.getsource(getattr(sports, cls_name).update)
        check("%s filters its no-favourites branch" % cls_name,
              "_filtered_or_all(processed_games)" in src)

    print("\nthe division lookup runs for the one league that has divisions")
    # FBS/FCS group rosters exist for college football and nowhere else:
    # college-baseball and college-lacrosse answer 500, college basketball and
    # college hockey answer 200 with an empty list. Asking anyway cost two
    # requests a day and a warning per league, and filtered nothing.
    for league, expected in (("college-football", True),
                             ("college-baseball", False),
                             ("mens-college-basketball", False),
                             ("nfl", False)):
        probe = make(sports, favs, 3, 3)
        probe.league = league
        probe.cache_manager = None
        probe._division_team_ids = None
        probe._division_loaded_at = 0.0
        asked = []

        class _Recorder:
            def get(self, *a, **k):
                asked.append(a[0] if a else "")
                raise RuntimeError("offline")

        probe.session = _Recorder()
        probe._load_division_team_ids()
        check("%-24s division lookup = %s" % (league, expected),
              bool(asked) is expected, asked)

    print("\nthe filters must not blank the mode when nothing survives")
    # Each check fails open on missing data, but a filter working exactly as
    # asked can match nothing -- and with no favourite game left there is
    # nothing to carry the mode. The board goes dark rather than short.
    probe = make(sports, ["NOT_PLAYING"], 3, 3)
    probe.other_games_min_quality = "ranked"
    probe._team_rankings_cache = {"NOT_PLAYING_TODAY": 1}     # loaded, matches nothing
    picked = probe._favorites_first(games, 3, 3)
    check("a filter matching nothing still fills the other slots",
          len(picked) == 3, abbrs(picked))

    probe = make(sports, ["NOT_PLAYING"], 3, 0)
    probe.other_games_min_quality = "ranked"
    probe._team_rankings_cache = {"NOT_PLAYING_TODAY": 1}
    check("but 0 others is an explicit favourites-only, and stays quiet",
          probe._favorites_first(games, 3, 0) == [])

    print("\na league with no broadcast data fails open too")
    # The scoreboard payload always carries the key, so the per-check "missing
    # means allowed" reading never fired here: picking `broadcast` in a league
    # ESPN leaves empty -- the NHL and the soccer leagues, measured -- removed
    # every non-favourite game instead of allowing them.
    probe = make(sports, favs, 3, 3)
    probe.other_games_min_quality = "broadcast"
    others = [g for g in probe._favorites_first(games, 3, 3)
              if not probe._is_favorite_game(g)]
    check("nothing televised anywhere: other games still shown",
          len(others) == 3, abbrs(others))

    televised = [dict(g) for g in games]
    televised[5]["broadcast"] = "ESPN"
    televised[6]["broadcast"] = "ABC"
    probe = make(sports, favs, 3, 3)
    probe.other_games_min_quality = "broadcast"
    others = [g for g in probe._favorites_first(televised, 3, 3)
              if not probe._is_favorite_game(g)]
    check("where the league does carry it, only televised games qualify",
          bool(others) and all(g.get("broadcast") for g in others), abbrs(others))

    print("\na poll that matches nothing says so, once")
    # The table is keyed by the abbreviation the RANKINGS endpoint returns and
    # matched against the SCOREBOARD's. If those ever stop agreeing the filter
    # removes every game with no exception and no log line -- the same shape as
    # the bug where rankings were never loading at all.
    class _Capture(logging.Handler):
        def __init__(self):
            logging.Handler.__init__(self)
            self.messages = []

        def emit(self, record):
            self.messages.append(record.getMessage())

    cap = _Capture()
    probe = make(sports, favs, 3, 3)
    probe.logger = logging.getLogger("ranking_coverage_probe")
    probe.logger.addHandler(cap)
    probe.logger.setLevel(logging.WARNING)
    probe.other_games_min_quality = "ranked"
    probe._team_rankings_cache = {"NOT_PLAYING_TODAY": 1}
    probe._ranking_coverage_logged_at = 0.0
    probe._favorites_first(games, 3, 3)
    check("the mismatch is reported",
          any("removing every non-favourite" in m for m in cap.messages),
          cap.messages)
    seen = len(cap.messages)
    probe._favorites_first(games, 3, 3)
    check("and not repeated on every update", len(cap.messages) == seen)

    # monotonic() counts from an arbitrary origin -- a few hundred seconds on a
    # freshly booted board -- so comparing it against a zero stamp treated
    # "never logged" as "logged at the epoch" and swallowed the first warning
    # for the first hour of uptime. That is exactly when a misconfigured board
    # is being watched. CI caught it; a machine with days of uptime cannot.
    booted = _Capture()
    fresh = make(sports, favs, 3, 3)
    fresh.logger = logging.getLogger("ranking_coverage_fresh_boot")
    fresh.logger.addHandler(booted)
    fresh.logger.setLevel(logging.WARNING)
    fresh.other_games_min_quality = "ranked"
    fresh._team_rankings_cache = {"NOT_PLAYING_TODAY": 1}
    fresh._ranking_coverage_logged_at = 0.0
    real_monotonic = sports.time.monotonic
    sports.time.monotonic = lambda: 120.0        # two minutes of uptime
    try:
        fresh._check_ranking_coverage(games)
    finally:
        sports.time.monotonic = real_monotonic
    check("and reported on a machine that only just booted",
          any("removing every non-favourite" in m for m in booted.messages),
          booted.messages)
    fresh.logger.removeHandler(booted)

    probe = make(sports, favs, 3, 3)
    probe.logger = logging.getLogger("ranking_coverage_quiet")
    quiet = _Capture()
    probe.logger.addHandler(quiet)
    probe.other_games_min_quality = "ranked"
    probe._team_rankings_cache = {"T05H": 4}      # a poll that DOES match
    probe._ranking_coverage_logged_at = 0.0
    probe._favorites_first(games, 3, 3)
    check("a poll that matches is not warned about", not quiet.messages, quiet.messages)

    print("\nan unusable value in config.json must not blank the mode")
    # These land in update()'s own try/except, so a string where an int belongs
    # does not surface as an error -- it surfaces as a mode that renders
    # nothing, which is indistinguishable from "no games today".
    probe = make(sports, favs, 3, 3)
    probe.logger = logging.getLogger("coercion_probe")
    probe.mode_config = {"other_upcoming_games_to_show": "not a number",
                         "other_rotation_interval_seconds": -5,
                         "other_recent_games_to_show": 999}
    check("a non-numeric count falls back to the default",
          probe._setting_int("other_upcoming_games_to_show", 3, 0, 20) == 3)
    check("a negative interval clamps to the floor",
          probe._setting_int("other_rotation_interval_seconds", 1800, 0, 86400) == 0)
    check("an oversized count clamps to the ceiling",
          probe._setting_int("other_recent_games_to_show", 3, 0, 20) == 20)
    check("a missing key uses the default",
          probe._setting_int("not_present_at_all", 7, 0, 20) == 7)

    check("a bare string division becomes one name, not three letters",
          sports.SportsCore._normalise_divisions("fbs") == ["fbs"])
    check("case and padding are normalised",
          sports.SportsCore._normalise_divisions([" FBS ", "Fcs"]) == ["fbs", "fcs"])
    check("an empty list stays empty -- that means no division filter",
          sports.SportsCore._normalise_divisions([]) == [])
    check("None is treated as empty rather than raising",
          sports.SportsCore._normalise_divisions(None) == [])

    print("\nthe slice rotates between fetches, not only during one")
    # _other_games_window only ever ran from update(), which returns early until
    # upcoming_update_interval (an hour, and not settable) has passed. So a
    # four-minute rotation did not produce fifteen slices an hour, it produced
    # one jump of fifteen windows -- the setting said one thing and the board
    # did another.
    clock = {"t": 10_000.0}
    real_monotonic = sports.time.monotonic
    sports.time.monotonic = lambda: clock["t"]
    try:
        probe = make(sports, favs, 3, 3)
        probe.other_rotation_interval_seconds = 240
        probe._games_lock = threading.RLock()
        probe.games_list = probe._favorites_first(games, 3, 3)
        probe.current_game_index = 0
        probe.current_game = probe.games_list[0]
        probe.last_game_switch = 0.0
        first = [g["id"] for g in probe.games_list]

        check("nothing rotates before the interval is up",
              not probe._rotate_other_games_on_display())
        check("and the list is untouched",
              [g["id"] for g in probe.games_list] == first)

        clock["t"] += 241
        check("once it passes, the slice is re-cut on the display path",
              probe._rotate_other_games_on_display())
        second = [g["id"] for g in probe.games_list]
        check("and the games actually changed", second != first,
              (abbrs(probe.games_list), first))

        favourite_ids = {g["id"] for g in games if probe._is_favorite_game(g)}
        check("favourites are still there after the cut",
              len(favourite_ids & set(second)) == len(favourite_ids & set(first)),
              abbrs(probe.games_list))

        clock["t"] += 241
        probe.current_game = probe.games_list[0]
        probe.current_game_index = 0
        probe._rotate_other_games_on_display()
        if probe.current_game and probe.current_game["id"] in [g["id"] for g in probe.games_list]:
            check("a surviving card keeps its place rather than jumping to the top",
                  probe.games_list[probe.current_game_index]["id"] == probe.current_game["id"])
        else:
            check("a card that did not survive the cut resets to the top",
                  probe.current_game_index == 0)

        probe.other_rotation_interval_seconds = 0
        clock["t"] += 10_000
        check("0 pins the window, on this path too",
              not probe._rotate_other_games_on_display())
    finally:
        sports.time.monotonic = real_monotonic

    print("\nthe best matchup available leads, not the earliest")
    # The filter said rank was what mattered and then selection ignored the
    # number: #1 vs #2 and #25 vs an unranked side were interchangeable, and the
    # earlier kickoff won. The pool is now ordered by the better of the two
    # sides before the window slices it.
    probe = make(sports, [], 3, 3)
    probe.other_games_min_quality = "ranked"
    # T50H plays LAST in the fixture and carries the best rank; T02H plays early
    # and is barely ranked. Chronology and importance disagree on purpose.
    probe._team_rankings_cache = {"T50H": 1, "T30A": 7, "T02H": 24}
    ordered = probe._by_importance([g for g in games if probe._passes_other_filters(g)])
    check("the top-ranked game sorts first even though it is last chronologically",
          ordered and ordered[0]["home_abbr"] == "T50H", abbrs(ordered[:3]))
    check("and the rest follow the ladder, not the clock",
          [g["home_abbr"] for g in ordered[:3]] == ["T50H", "T30H", "T02H"],
          abbrs(ordered[:3]))

    picked = probe._favorites_first(games, 3, 1)
    others = [g for g in picked if not probe._is_favorite_game(g)]
    check("so the first window holds the best game available",
          others and others[0]["home_abbr"] == "T50H", abbrs(others))

    check("ties fall back to kickoff order",
          probe._by_importance([games[5], games[3]])[0]["id"] == games[3]["id"])

    # The upcoming pool is a SEASON, not a week -- 947 games on a real board --
    # so ordering by rank alone stacked all of the #1 team's games above the #2
    # team's first one and the board walked one team's schedule: KENT@OSU,
    # ILL@OSU, OSU@IOWA, MD@OSU, measured on ledpi.
    season = []
    for week in range(4):
        season.append({**games[0], "id": "top%d" % week,
                       "home_abbr": "TOP", "away_abbr": "OPP%d" % week,
                       "start_time_utc": NOW + timedelta(days=7 * week + 1)})
        season.append({**games[1], "id": "second%d" % week,
                       "home_abbr": "SECOND", "away_abbr": "FOE%d" % week,
                       "start_time_utc": NOW + timedelta(days=7 * week + 2)})
    probe._team_rankings_cache = {"TOP": 1, "SECOND": 2}
    ordered = probe._by_importance(season)
    check("a team appears once, not once per week",
          [g["home_abbr"] for g in ordered] == ["TOP", "SECOND"],
          [g["id"] for g in ordered])
    check("and it is that team's NEXT game, not a later one",
          ordered[0]["id"] == "top0" and ordered[1]["id"] == "second0",
          [g["id"] for g in ordered])

    probe._team_rankings_cache = {}
    unchanged = probe._by_importance(list(games[:5]))
    check("a league with no poll keeps chronological order",
          [g["id"] for g in unchanged] == [g["id"] for g in games[:5]])

    print("\nfavourites are still ordered by when they play")
    # Importance ordering is for the OTHER slots. For your own teams the next
    # game is the point -- ordering those by rank would show a week-8 fixture
    # ahead of Saturday's.
    probe = make(sports, favs, 3, 3)
    probe._team_rankings_cache = {"AUB": 1, "BAMA": 25}
    picked = probe._favorites_first(games, 3, 0)
    check("the sooner favourite game still comes first",
          picked and picked[0]["id"] == games[40]["id"], abbrs(picked))

    print("\nfavourite slots are shared between your teams")
    # Taking the soonest N favourite games spends them on whoever plays most
    # often. Walked across a real season with UGA and AUB and a limit of 2, nine
    # days showed Auburn twice and Georgia not at all -- Auburn played either
    # side of a Georgia bye.
    # Each fixture team carries BOTH spellings the lineages match on -- most
    # compare abbreviations, NRL compares ESPN team ids because its
    # abbreviations are not unique -- so one fixture works in all nine.
    def fav_game(gid, team, days):
        game = dict(games[0])
        game.update({"id": gid, "start_time_utc": NOW + timedelta(days=days)})
        if team == "first":
            game.update({"home_abbr": "UGA", "home_id": 1041,
                         "away_abbr": "OPP", "away_id": 9001})
        else:
            game.update({"home_abbr": "AUB", "home_id": 2040,
                         "away_abbr": "FOE", "away_id": 9002})
        return game

    # The second team plays twice before the first plays at all -- a bye week.
    bye = [fav_game("bye0", "second", 1), fav_game("bye1", "second", 8),
           fav_game("bye2", "first", 15)]
    probe = make(sports, favs, 2, 0)
    picked = probe._favorites_first(bye, 2, 0)
    check("both teams get a slot even when one plays twice first",
          {g["id"] for g in picked} == {"bye0", "bye2"}, [g["id"] for g in picked])

    # Breadth first, but not at the cost of depth: one team with slots to spare
    # still gets its next games.
    solo = make(sports, ["AUB", "2040"], 3, 0)
    picked = solo._favorites_first(bye, 3, 0)
    check("a single favourite still fills the slots it is given",
          {g["id"] for g in picked} == {"bye0", "bye1"}, [g["id"] for g in picked])

    both = make(sports, favs, 3, 0)
    picked = both._favorites_first(bye, 3, 0)
    check("with room for three, the second game of a team comes back",
          {g["id"] for g in picked} == {"bye0", "bye1", "bye2"}, [g["id"] for g in picked])

    failed = [c for c, ok in results if not ok]
    print("\n%d checks, %d failed" % (len(results), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
