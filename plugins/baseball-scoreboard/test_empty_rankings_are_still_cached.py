#!/usr/bin/env python3
"""
Tests that a league with no poll stops re-fetching standings every update.

_fetch_team_rankings caches for an hour (_rankings_cache_duration = 3600), but
the guard read:

    if (self._team_rankings_cache
            and current_time - self._rankings_cache_timestamp
            < self._rankings_cache_duration):

Professional leagues publish no poll, so `rankings` comes back {} -- and an
empty dict is falsy, so the guard never short-circuited and the standings
endpoint was hit on every single update. Measured on 2026-09-19 on an MLB-only
rig: 453 standings requests in a day against the 24 the one-hour duration
intends, at a median of 31 seconds apart, on the live update threads.

An empty result is a result. The guard now keys off when the last look
happened, not off whether it found anything. These checks pin:

  * an empty result is cached, and does not refetch inside the hour;
  * it does refetch once the hour is up;
  * a league that does have a poll still caches and still returns its ranks;
  * the timestamp is recorded even when nothing was found;
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


class _Stub:
    _fetch_team_rankings = sports.SportsCore._fetch_team_rankings
    _choose_poll = sports.SportsCore._choose_poll

    def __init__(self, source):
        self.data_source = source
        self.sport = "baseball"
        self.league = "mlb"
        self.logger = _Logger()
        self._team_rankings_cache = {}
        self._rankings_cache_timestamp = 0
        self._rankings_cache_duration = 3600


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
    print("a league with no poll (MLB): the empty result is cached")
    src = _Source({})                      # MLB: no "rankings" key at all
    stub = _Stub(src)
    check("first look fetches", _at(stub, 1000.0) == {} and src.calls == 1)
    check("a second look 30s later does NOT fetch again",
          _at(stub, 1030.0) == {} and src.calls == 1)
    check("nor does one 59 minutes later",
          _at(stub, 1000.0 + 3540) == {} and src.calls == 1)
    check("the timestamp was recorded even though nothing was found",
          stub._rankings_cache_timestamp == 1000.0)

    print("\n...and it does refresh once the hour is up")
    check("past the duration it looks again",
          _at(stub, 1000.0 + 3601) == {} and src.calls == 2)

    print("\na league that does have a poll is unaffected")
    src = _Source(POLL)
    stub = _Stub(src)
    ranks = _at(stub, 500.0)
    check("the ranks come through", ranks == {"UGA": 1, "AUB": 7})
    check("one fetch", src.calls == 1)
    check("and it is cached", _at(stub, 530.0) == {"UGA": 1, "AUB": 7} and src.calls == 1)

    print("\nthe old behaviour would have refetched every time")
    # 120 updates over an hour at the live cadence; the intent is one fetch.
    src = _Source({})
    stub = _Stub(src)
    for i in range(120):
        _at(stub, 2000.0 + i * 30)
    check("an hour of 30s updates costs one standings request", src.calls == 1)

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
