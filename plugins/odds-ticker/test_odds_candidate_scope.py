#!/usr/bin/env python3
"""
Tests that odds are requested only for games the ticker can actually show.

Regression under test: _fetch_league_games() fetched odds inline for every
game in the future_fetch_days window, then the caller trimmed the list to
max_games_per_league (five by default). Measured on a live rig during a
college-football weekend: 1,281 ESPN requests in twenty minutes, ~600/min,
holding roughly a CPU core on a Pi -- for a ticker showing five games. The
display loop shares the interpreter, and frames stalled for up to half a
second.

The methods are exercised against a stand-in ``self`` rather than a
constructed plugin, so the test needs no display manager, no network and no
cache -- only that manager.py imports.

Run: <core-venv>/bin/python plugins/odds-ticker/test_odds_candidate_scope.py
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))
for candidate in (Path("/home/rackpi/projects/LEDMatrix"),
                  plugin_dir.parents[2] / "LEDMatrix"):
    if (candidate / "src" / "plugin_system" / "base_plugin.py").exists():
        sys.path.insert(0, str(candidate))
        break

from manager import OddsTickerPlugin  # noqa: E402

failures = []


def check(label, ok):
    print(("  PASS  " if ok else "  FAIL  ") + label)
    if not ok:
        failures.append(label)


BASE = datetime(2026, 8, 14, 12, 0, 0)


def game(index, home="HOME", away="AWAY"):
    return {
        "id": "g%d" % index,
        "home_team": home,
        "away_team": away,
        # Deliberately out of order, so anything relying on input order
        # rather than start_time shows up.
        "start_time": BASE + timedelta(hours=(index * 7) % 101),
        "odds": None,
    }


class _Ticker:
    """A stand-in ``self`` carrying only what the selection touches."""

    _ODDS_CANDIDATE_HEADROOM = OddsTickerPlugin._ODDS_CANDIDATE_HEADROOM
    _odds_candidates = OddsTickerPlugin._odds_candidates
    _select_games = OddsTickerPlugin._select_games
    _collection_limit = OddsTickerPlugin._collection_limit
    _attach_odds_to_candidates = OddsTickerPlugin._attach_odds_to_candidates
    # Re-wrap: reading a staticmethod off the class yields a plain function,
    # which would bind as an instance method on this stand-in.
    _odds_are_usable = staticmethod(OddsTickerPlugin._odds_are_usable)

    def __init__(self, favorites_only=False, odds_only=False,
                 max_games=5, per_favorite=1, fetch=True):
        self.show_favorite_teams_only = favorites_only
        self.show_odds_only = odds_only
        self.max_games_per_league = max_games
        self.games_per_favorite_team = per_favorite
        self.fetch_odds = fetch
        self._odds_pending = {}
        self.requested = []

    def _fetch_one_game_odds(self, game_id, request):
        self.requested.append(game_id)
        return {"spread": -3.5}


def with_pending(ticker, games):
    ticker._odds_pending = {
        g["id"]: {"sport": "football", "league": "college-football",
                  "update_interval_seconds": 3600, "is_live": False}
        for g in games
    }
    return games


def main():
    season = [game(i) for i in range(1281)]

    print("a full college-football window is not priced end to end")
    t = _Ticker(max_games=5)
    t._attach_odds_to_candidates(with_pending(t, season), {})
    check("5 requests, not 1281 (was %d)" % len(t.requested), len(t.requested) == 5)
    check("the pending map is drained", t._odds_pending == {})

    print("\nthe games priced are the ones that get displayed")
    t = _Ticker(max_games=5)
    soonest = [g["id"] for g in sorted(season, key=lambda g: g["start_time"])[:5]]
    t._attach_odds_to_candidates(with_pending(t, season), {})
    check("the five soonest are the five priced", t.requested == soonest)
    priced = {g["id"] for g in season if g.get("odds")}
    check("odds land on those games and no others", priced == set(soonest))

    print("\nfavourites mode prices only favourites")
    fav_games = [game(i, home="UGA" if i % 100 == 0 else "X",
                      away="BAMA" if i % 137 == 0 else "Y")
                 for i in range(1281)]
    t = _Ticker(favorites_only=True, per_favorite=2)
    cfg = {"favorite_teams": ["UGA", "BAMA"]}
    t._attach_odds_to_candidates(with_pending(t, fav_games), cfg)
    involved = {g["id"] for g in fav_games
                if g["home_team"] in ("UGA", "BAMA") or g["away_team"] in ("UGA", "BAMA")}
    check("every priced game involves a favourite",
          set(t.requested).issubset(involved))
    check("bounded by games_per_favorite_team x favourites (%d)" % len(t.requested),
          len(t.requested) <= 2 * 2)

    print("\nno favourites configured means no requests")
    t = _Ticker(favorites_only=True)
    t._attach_odds_to_candidates(with_pending(t, season), {"favorite_teams": []})
    check("nothing is fetched", t.requested == [])

    print("\nshow_odds_only widens the window rather than emptying the ticker")
    plain = _Ticker(max_games=5)
    plain._attach_odds_to_candidates(with_pending(plain, season), {})
    wide = _Ticker(max_games=5, odds_only=True)
    wide._attach_odds_to_candidates(with_pending(wide, season), {})
    check("more games priced than without the filter (%d > %d)"
          % (len(wide.requested), len(plain.requested)),
          len(wide.requested) > len(plain.requested))
    check("still bounded, not the whole season (%d)" % len(wide.requested),
          len(wide.requested) == 5 * _Ticker._ODDS_CANDIDATE_HEADROOM)

    print("\nfetch_odds=False makes no requests at all")
    t = _Ticker(fetch=False)
    t._attach_odds_to_candidates(with_pending(t, season), {})
    check("nothing is fetched", t.requested == [])
    check("the pending map is still drained", t._odds_pending == {})

    print("\ncandidate selection matches what the display will pick")
    # The two must agree. Selecting candidates by a plain count while the
    # display uses a per-team quota lets them diverge: if the earliest games
    # all involve one favourite, a count spends the whole budget there and a
    # later game for another favourite reaches the screen with no odds.
    crowded = ([game(i, home="UGA", away="X") for i in range(20)]
               + [game(500 + i, home="BAMA", away="Y") for i in range(3)])
    t = _Ticker(favorites_only=True, per_favorite=2)
    cfg = {"favorite_teams": ["UGA", "BAMA"]}
    picked = t._select_games(crowded, cfg)
    teams = {g["home_team"] for g in picked}
    check("both favourites are represented, not just the earliest one",
          teams == {"UGA", "BAMA"})
    check("each favourite is held to its quota (%d games)" % len(picked),
          len(picked) <= 2 * 2)

    t2 = _Ticker(favorites_only=True, per_favorite=2)
    t2._attach_odds_to_candidates(with_pending(t2, crowded), cfg)
    priced = {g["id"] for g in crowded if g.get("odds")}
    check("the games priced are exactly the games selected",
          priced == {g["id"] for g in picked})

    print("\nshow_odds_only keeps enough games to fall back on")
    # The headroom is only real if collection kept more than the display
    # limit. Capping collection at max_games_per_league made it inert.
    plain = _Ticker(max_games=5)
    wide = _Ticker(max_games=5, odds_only=True)
    check("collection keeps the display limit when odds are not required",
          plain._collection_limit() == 5)
    check("...and the wider window when they are (%d)" % wide._collection_limit(),
          wide._collection_limit() == 5 * _Ticker._ODDS_CANDIDATE_HEADROOM)
    # Via the real entry point, which is what applies the headroom.
    pool = [game(i) for i in range(40)]
    check("the odds fetch considers the wider window (%d)"
          % len(wide._odds_candidates(pool, {})),
          len(wide._odds_candidates(pool, {}))
          == 5 * _Ticker._ODDS_CANDIDATE_HEADROOM)
    check("...while the display limit itself is unchanged",
          len(plain._odds_candidates(pool, {})) == 5)

    print("\nunusable responses are not attached as odds")
    for label, payload in (("no_odds", {"no_odds": True}),
                           ("empty", {}),
                           ("None", None)):
        check("%s is rejected" % label, _Ticker._odds_are_usable(payload) is False)
    for label, payload in (("spread", {"spread": -3.5}),
                           ("over_under", {"over_under": 47.5}),
                           ("home spread_odds",
                            {"home_team_odds": {"spread_odds": -110}})):
        check("%s is accepted" % label, _Ticker._odds_are_usable(payload) is True)

    print("\n%s" % ("FAILED: %d" % len(failures) if failures
                    else "All checks passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
