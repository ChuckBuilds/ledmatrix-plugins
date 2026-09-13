#!/usr/bin/env python3
"""A cached "no odds" marker must answer the call, not trigger a refetch.

get_odds caches {"no_odds": True} for a game ESPN has no line for, precisely
so the next call does not hit the API again. The read side then treated that
marker as a miss and fell through to the request, so every game without odds
was re-requested on every call for as long as the marker sat in the cache.

Run: <core-venv>/bin/python plugins/football-scoreboard/test_no_odds_marker_is_a_cache_hit.py
"""
import logging
import sys
from pathlib import Path
from unittest.mock import Mock, patch

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))
logging.disable(logging.CRITICAL)

try:
    import base_odds_manager  # noqa: E402
except ImportError as exc:
    print("SKIP: cannot import base_odds_manager.py (%s)" % exc)
    sys.exit(2)


def main():
    cache = Mock()
    cache.get = Mock(return_value={"no_odds": True})
    manager = base_odds_manager.BaseOddsManager(cache)
    failures = 0
    with patch.object(base_odds_manager.requests, "get",
                      side_effect=AssertionError("fetched")) as get:
        try:
            result = manager.get_odds("football", "nfl", "401")
        except AssertionError:
            result = "fetched"
        ok = result is None and not get.called
        failures += not ok
        print("  [%s] no-odds marker returns None without a request (got %r, "
              "requested=%s)" % ("pass" if ok else "FAIL", result, get.called))

    cache.get = Mock(return_value={"spread": -3.5})
    with patch.object(base_odds_manager.requests, "get",
                      side_effect=AssertionError("fetched")) as get:
        result = manager.get_odds("football", "nfl", "401")
        ok = result == {"spread": -3.5} and not get.called
        failures += not ok
        print("  [%s] real cached odds are still returned"
              % ("pass" if ok else "FAIL"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
