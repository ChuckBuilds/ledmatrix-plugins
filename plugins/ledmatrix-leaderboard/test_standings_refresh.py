#!/usr/bin/env python3
"""
Regression test: standings are refetched on the configured update_interval.

Every read used the core's 'leaderboard' cache strategy, which keeps an entry
for 7 days, so while the cache was warm update_interval ("How often to fetch
new leaderboard data") never caused a fetch and NBA/NHL/MLB/NFL standings could
be a week old. The standings key also ignored level and season, so changing
either kept serving the old response.

The cache here honours max_age the way the core's does: an entry older than
the caller's max_age is a miss.

Exit codes follow scripts/run_plugin_tests.py: 0 pass, 1 fail, 2 skip.

    python plugins/ledmatrix-leaderboard/test_standings_refresh.py
"""

import logging
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

try:
    import requests  # noqa: F401  (data_fetcher imports it)
except ImportError:
    print("SKIP: requests not installed")
    sys.exit(2)

import data_fetcher as df  # noqa: E402
from league_config import LeagueConfig  # noqa: E402

failures = []


def check(cond, msg):
    print(("  PASS: " if cond else "  FAIL: ") + msg)
    if not cond:
        failures.append(msg)


class AgedCache:
    """Entries carry an age; a read older than max_age misses, as in core."""

    def __init__(self):
        self.store = {}  # key -> (data, age_seconds)

    def get(self, key, max_age=300):
        if key not in self.store:
            return None
        data, age = self.store[key]
        return data if max_age is None or age <= max_age else None

    def save_cache(self, key, data):
        self.store[key] = (data, 0)

    def get_cached_data_with_strategy(self, key, data_type="default"):
        # The strategy the plugin used: a 7-day max_age.
        return self.get(key, max_age=604800)

    def age_all(self, seconds):
        self.store = {k: (d, seconds) for k, (d, _) in self.store.items()}


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def entry(abbr, wins, losses):
    return {
        "team": {"displayName": abbr, "abbreviation": abbr, "id": abbr},
        "stats": [
            {"type": "wins", "value": wins},
            {"type": "losses", "value": losses},
            {"type": "winpercent", "value": wins / float(wins + losses)},
        ],
    }


PAYLOAD = {"standings": {"entries": [entry("TB", 90, 60), entry("NYY", 80, 70)]}}


def main():
    logger = logging.getLogger("test_standings_refresh")
    logger.addHandler(logging.NullHandler())
    logger.propagate = False

    requested = []
    df.requests.get = lambda url, params=None, **kw: (
        requested.append(dict(params or {})) or FakeResponse(PAYLOAD))

    def mlb(**overrides):
        cfg = {"enabled": True, "top_teams": 10}
        cfg.update(overrides)
        return LeagueConfig({"enabled_sports": {"mlb": cfg}}, logger).get_league_config("mlb")

    update_interval = 3600
    cache = AgedCache()
    fetcher = df.DataFetcher(cache, logger, request_timeout=5,
                             cache_max_age=update_interval // 2)

    print("[refresh follows update_interval]")
    fetcher.fetch_standings(mlb())
    check(len(requested) == 1, "a cold cache fetches")

    cache.age_all(600)
    fetcher.fetch_standings(mlb())
    check(len(requested) == 1, "a 10-minute-old response is reused")

    # The next scheduled update() comes one update_interval after the last,
    # a few seconds less after the entry was written mid-update.
    cache.age_all(update_interval - 5)
    fetcher.fetch_standings(mlb())
    check(len(requested) == 2, "the next scheduled update fetches again")

    cache.age_all(2 * 86400)
    fetcher.fetch_standings(mlb())
    check(len(requested) == 3, "a two-day-old response is never shown")

    print("[level and season are part of the key]")
    cache.age_all(0)
    fetcher.fetch_standings(mlb(season=2024))
    check(len(requested) == 4 and requested[-1].get("season") == 2024,
          "changing the season fetches that season instead of reusing the current one")
    fetcher.fetch_standings(mlb(level=2))
    check(len(requested) == 5 and requested[-1].get("level") == 2,
          "changing the level fetches that level")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # a crash is a failure, not a skip
        failures.append(repr(exc))
        print(f"  FAIL: raised {exc!r}")
    print(f"\n{len(failures)} failed")
    sys.exit(1 if failures else 0)
