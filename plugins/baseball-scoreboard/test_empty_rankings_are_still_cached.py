#!/usr/bin/env python3
"""
Tests that a league with no poll does not fetch standings at all, and that a
league that has one still caches its poll for the hour.

Two bugs, one method. The first: _fetch_team_rankings caches for an hour
(_rankings_cache_duration = 3600), but the guard read

    if (self._team_rankings_cache
            and current_time - self._rankings_cache_timestamp
            < self._rankings_cache_duration):

Professional leagues publish no poll, so `rankings` comes back {} -- and an
empty dict is falsy, so the guard never short-circuited and the standings
endpoint was hit on every single update. Measured on 2026-09-19 on an MLB-only
rig: 453 standings requests in a day against the 24 the one-hour duration
intends, at a median of 31 seconds apart, on the live update threads. The guard
now keys off when the last look happened, not off whether it found anything.

The second: that only reduced the waste to 24 requests a day, because nothing
stopped a pollless league from asking in the first place. _league_has_rankings
gated the quality-filter call site but not the two show_ranking call sites, so
ticking "Show Ranking" on MLB or MiLB kept asking endpoints that cannot answer.
The gate now lives at the top of _fetch_team_rankings, where it covers every
caller and cannot drift apart again.

The third: the gate's shared heuristic is "college" or "ncaa" in the league
name, and NCAA Baseball's other_games_min_quality defaulted to "ranked", so
that league fetched hourly by default. College baseball is the one college
league ESPN publishes no /rankings for -- measured 2026-09-24, 404 while
/scoreboard and /standings on the same slug answer 200, and out of season is
not the explanation because men's college lacrosse and hockey are equally out
of season and both answer 200 with real poll blocks. The heuristic is now
narrowed by that one measured exception, so none of this plugin's three
leagues reaches the network for a poll in any configuration.

These checks pin:

  * none of the three leagues this plugin serves ever reaches the network;
  * a league that does have a poll caches, and does not refetch inside the hour;
  * it does refetch once the hour is up;
  * the timestamp is recorded even when the poll came back empty;
  * a failure does not poison the cache.

Run: <core-venv>/bin/python plugins/baseball-scoreboard/test_empty_rankings_are_still_cached.py
"""

# A test harness: it reaches into protected members on purpose, builds a
# concrete subclass at runtime, and accepts arguments only to match the
# signatures it stands in for -- none of which pylint can see as intentional.
# pylint: disable=protected-access,abstract-class-instantiated,unused-argument
# pylint: disable=broad-exception-caught

import sys
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

import sports  # noqa: E402


class _Logger:
    def info(self, *a, **k): pass
    def debug(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def error(self, *a, **k): pass


class _Source:
    def __init__(self, payload=None, boom=False):
        self.payload = payload if payload is not None else {}
        self.boom = boom
        self.calls = 0

    def fetch_standings(self, sport, league):
        self.calls += 1
        if self.boom:
            raise RuntimeError("ESPN unavailable")
        return self.payload


# A real subclass, not an object borrowing unbound functions: the plugin's
# _league_has_rankings override calls super() to reach the shared heuristic,
# which a borrowed function cannot do. Abstract methods are stubbed from the
# class rather than named -- none is reached by the rankings fetch.
_STUBS = dict((name, lambda self, *a, **k: None)
              for name in getattr(sports.SportsCore, "__abstractmethods__", ()))
_Probe = type("RankingsProbe", (sports.SportsCore,), _STUBS)


def _Stub(source, league="college-football"):
    """A probe pinned to one league.

    The default is a league that HAS a poll, so the caching checks exercise
    the fetch path. It is deliberately not one of baseball's own: since the
    college-baseball 404 was measured, none of this plugin's three leagues
    reaches the network at all. The caching logic still matters because
    sports.py is copied across nine scoreboard lineages, several of which do
    have polls -- this is where that shared behaviour is pinned.
    """
    probe = _Probe.__new__(_Probe)
    probe.data_source = source
    probe.sport = "baseball"
    probe.league = league
    probe.logger = _Logger()
    probe._team_rankings_cache = {}
    probe._rankings_cache_timestamp = 0
    probe._rankings_cache_duration = 3600
    return probe


POLL = {"rankings": [{"ranks": [
    {"team": {"abbreviation": "UGA"}, "current": 1},
    {"team": {"abbreviation": "AUB"}, "current": 7},
]}]}

failures = []


def check(label, ok):
    print(("  PASS  " if ok else "  FAIL  ") + label)
    if not ok:
        failures.append(label)


def _at(stub, t):
    """Run _fetch_team_rankings with a pinned clock."""
    real = sports.time.time
    sports.time.time = lambda: t
    try:
        return stub._fetch_team_rankings()
    finally:
        sports.time.time = real


def main():
    print("no league THIS PLUGIN serves reaches the network")
    # All three: mlb and minor-league-baseball fail the "college" heuristic,
    # and college-baseball is the measured exception to it (its /rankings
    # answers 404 while /scoreboard and /standings on the same slug answer
    # 200). So the rankings fetch is unreachable here in every configuration.
    for league in ("mlb", "minor-league-baseball", "college-baseball"):
        src = _Source({})
        stub = _Stub(src, league)
        check("%s: the first look does not fetch" % league,
              _at(stub, 1000.0) == {} and src.calls == 0)
        # An hour of live-cadence updates, the shape that cost 453 requests a
        # day before the cache guard and 24 a day before this gate.
        for i in range(120):
            _at(stub, 1000.0 + i * 30)
        check("%s: an hour of 30s updates costs zero requests" % league,
              src.calls == 0)
        check("%s: nothing was cached to go stale" % league,
              stub._team_rankings_cache == {} and stub._rankings_cache_timestamp == 0)

    print("\na league that does have a poll still fetches, and caches for the hour")
    src = _Source(POLL)
    stub = _Stub(src)
    ranks = _at(stub, 500.0)
    check("the ranks come through", ranks == {"UGA": 1, "AUB": 7})
    check("one fetch", src.calls == 1)
    check("and it is cached", _at(stub, 530.0) == {"UGA": 1, "AUB": 7} and src.calls == 1)

    print("\nan empty poll from such a league is still a result")
    # The guard keys off when the last look happened, not off whether it found
    # anything -- an early-season board whose poll is not published yet must
    # not fall back to asking on every update. Sibling lineages depend on this;
    # sports.py is copied, not shared.
    src = _Source({})
    stub = _Stub(src)
    check("first look fetches", _at(stub, 1000.0) == {} and src.calls == 1)
    check("a second look 30s later does NOT fetch again",
          _at(stub, 1030.0) == {} and src.calls == 1)
    check("nor does one 59 minutes later",
          _at(stub, 1000.0 + 3540) == {} and src.calls == 1)
    check("the timestamp was recorded even though nothing was found",
          stub._rankings_cache_timestamp == 1000.0)
    check("past the duration it looks again",
          _at(stub, 1000.0 + 3601) == {} and src.calls == 2)

    print("\na failure does not poison the cache")
    src = _Source(boom=True)
    stub = _Stub(src)
    check("the error is swallowed and returns empty", _at(stub, 10.0) == {})
    check("and it is free to retry rather than caching the failure",
          stub._rankings_cache_timestamp == 0)

    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
