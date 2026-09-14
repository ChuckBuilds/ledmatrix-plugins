#!/usr/bin/env python3
"""A cached "no odds" marker is a cache hit, not a reason to ask ESPN again.

When ESPN has no line for a game, get_odds caches {"no_odds": True} for the
update interval so the request is not repeated. The bundled BaseOddsManager
recognised the marker and then fell through to a fresh request anyway, so a
game without odds cost an ESPN call on every odds pass until the entry
expired. The check uses the bundled copy (the fallback for cores without
src.base_odds_manager) with a stub cache and a request recorder.

Run: python plugins/basketball-scoreboard/test_no_odds_marker_is_a_cache_hit.py
"""

import sys
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

import base_odds_manager  # noqa: E402

results = []


def check(case, passed):
    results.append((case, passed))
    print("  [%s] %s" % ("pass" if passed else "FAIL", case))


class _Cache:
    def __init__(self, value):
        self.value = value

    def get(self, key, *a, **k):
        return self.value

    def set(self, *a, **k):
        pass


def main():
    requests_made = []

    def fake_get(*a, **k):
        requests_made.append(a)
        raise AssertionError("network requested")

    base_odds_manager.requests.get = fake_get

    mgr = base_odds_manager.BaseOddsManager(_Cache({"no_odds": True}))
    result = mgr.get_odds("basketball", "nba", "401", update_interval_seconds=3600)
    check("a cached no-odds marker returns None", result is None)
    check("and makes no request", requests_made == [])

    real = {"over_under": 220.5}
    mgr = base_odds_manager.BaseOddsManager(_Cache(real))
    check("cached real odds are still returned",
          mgr.get_odds("basketball", "nba", "401", update_interval_seconds=3600) == real)
    check("still without a request", requests_made == [])

    failed = [c for c, ok in results if not ok]
    print("\n%d checks, %d failed" % (len(results), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
