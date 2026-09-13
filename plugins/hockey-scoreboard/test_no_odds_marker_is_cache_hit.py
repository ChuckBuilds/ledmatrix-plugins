#!/usr/bin/env python3
"""A cached "no odds" marker is a cache hit, not a miss.

When ESPN has no line for a game, get_odds caches {"no_odds": True} for the
update interval so the game is not asked about again. The read side treated
that marker as a miss and fell through to a fresh request, so every call for
a line-less game hit ESPN anyway -- the cache entry did nothing.

Exercises the bundled BaseOddsManager (the fallback for cores without
src.base_odds_manager) with a dict cache and requests.get replaced.

Run: <core-venv>/bin/python plugins/hockey-scoreboard/test_no_odds_marker_is_cache_hit.py
"""

import importlib.util
import logging
import sys
from pathlib import Path
from unittest import mock

plugin_dir = Path(__file__).parent

# Load the plugin's own copy by path: a bare `import base_odds_manager` could
# bind another copy already on sys.path.
spec = importlib.util.spec_from_file_location(
    "hockey_bundled_base_odds_manager", plugin_dir / "base_odds_manager.py")
bom = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(bom)
except ImportError as exc:
    print("SKIP: cannot import base_odds_manager.py (%s)" % exc)
    sys.exit(2)

failures = []


def check(name, ok, detail=None):
    if ok:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s%s" % (name, " -- %r" % (detail,) if detail is not None else ""))
        failures.append(name)


class _Cache:
    def __init__(self, data):
        self.data = dict(data)

    def get(self, key, *a, **k):
        return self.data.get(key)

    def set(self, key, value, *a, **k):
        self.data[key] = value


def _manager(cache):
    mgr = bom.BaseOddsManager.__new__(bom.BaseOddsManager)
    mgr.cache_manager = cache
    mgr.logger = logging.getLogger("odds_probe")
    mgr.update_interval = 3600
    mgr.request_timeout = 5
    mgr.base_url = "https://example.invalid"
    return mgr


def main():
    key = "odds_espn_hockey_nhl_401"

    print("a cached no-odds marker")
    mgr = _manager(_Cache({key: {"no_odds": True}}))
    with mock.patch.object(bom.requests, "get") as get:
        result = mgr.get_odds("hockey", "nhl", "401")
    check("returns None", result is None, result)
    check("does not request ESPN", get.call_count == 0, get.call_count)

    print("\ncached real odds")
    odds = {"spread": -1.5, "over_under": 5.5}
    mgr = _manager(_Cache({key: odds}))
    with mock.patch.object(bom.requests, "get") as get:
        result = mgr.get_odds("hockey", "nhl", "401")
    check("returns the cached odds", result == odds, result)
    check("does not request ESPN", get.call_count == 0, get.call_count)

    print("\nnothing cached")
    mgr = _manager(_Cache({}))
    response = mock.Mock()
    response.json.return_value = {"items": []}
    response.raise_for_status.return_value = None
    with mock.patch.object(bom.requests, "get", return_value=response) as get:
        mgr.get_odds("hockey", "nhl", "401")
    check("a real miss still requests ESPN once", get.call_count == 1, get.call_count)

    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
