#!/usr/bin/env python3
"""A league's schedule window is fetched once per cache miss, not four times.

Found on a Pi running eight leagues (ledpi, 2026-10-03): every start logged
~90 NameResolutionErrors for site.api.espn.com within a minute, and over six
hours soccer made 3,812 requests. ESPN rejects date ranges, so each league's
29-day window was 29 day requests -- and _fetch_soccer_api_data, on a cache
miss, both submitted the window to the core's background service AND fetched
the same window on the spot as "partial data". The recent and upcoming
managers share the cache key but come due in the same update(), so both
missed it and both did both. Measured against live ESPN at startup: ~450
requests, ~45 in flight at once.

Now a miss fetches the window once on the calling thread
(_fetch_season_directly, which caches it), under a per-key lock, so the
league's other manager waits and reads the cache. The managers also share the
core's connection pool, so their connections (and DNS lookups) are reused.

No network: the fetch is replaced by a counting stub.

Run: <core-venv>/bin/python plugins/soccer-scoreboard/test_schedule_fetched_once.py
"""

# pylint: disable=protected-access
import logging
import os
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

plugin_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(plugin_dir))
_core = os.environ.get("LEDMATRIX_CORE")
_candidates = [Path(_core)] if _core else []
_candidates.append(plugin_dir.parents[2] / "LEDMatrix")
for candidate in _candidates:
    if (candidate / "src" / "plugin_system" / "base_plugin.py").exists():
        sys.path.insert(0, str(candidate))
        break
else:
    print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
    sys.exit(2)

import soccer_managers as sm  # noqa: E402

failures = []


def check(label, ok, detail=None):
    print(("  PASS  " if ok else "  FAIL  ") + label
          + ("" if ok or detail is None else " -- %r" % (detail,)))
    if not ok:
        failures.append(label)


class DictCache:
    def __init__(self):
        self.data = {}
        self.lock = threading.Lock()

    def get(self, key, max_age=300):
        with self.lock:
            return self.data.get(key)

    def set(self, key, value, ttl=None):
        with self.lock:
            self.data[key] = value

    def delete(self, key):
        with self.lock:
            self.data.pop(key, None)


def manager(cls, cache, fetches, league="eng.1"):
    """A manager with only what the schedule fetch reads; the constructor
    pulls in fonts, logos and an ESPN session this test has no use for."""
    obj = cls.__new__(cls)
    obj.league_key = league
    obj.league_name = sm.LEAGUE_NAMES[league]
    obj.logger = logging.getLogger("fetch_once_probe")
    obj.cache_manager = cache
    obj.schedule_lookback_days = 14
    obj.schedule_lookahead_days = 14
    obj.background_service = MagicMock()
    obj.background_enabled = True
    obj.mode_config = {}
    obj.headers = {}
    obj._background_fetches_espn_ranges = lambda: True
    obj._get_weeks_data = lambda: fetches.append("partial") or {"events": []}

    def fetch(url, datestring, cache_key, label, ttl=None):
        time.sleep(0.05)  # long enough for the other manager to arrive
        fetches.append(datestring)
        data = {"events": [{"id": "1"}]}
        cache.set(cache_key, data)
        return data

    obj._fetch_season_directly = fetch
    return obj


def main():
    print("a cache miss fetches the window once")
    cache, fetches = DictCache(), []
    recent = manager(sm.SoccerRecentManager, cache, fetches)
    data = recent._fetch_soccer_api_data(use_cache=True)
    check("one window fetch", len(fetches) == 1, fetches)
    check("no stand-in 'partial' fetch of the same window",
          "partial" not in fetches, fetches)
    check("nothing submitted to the background service as well",
          not recent.background_service.submit_fetch_request.called)
    check("the fetched schedule is returned", data == {"events": [{"id": "1"}]}, data)

    print("\na cache hit fetches nothing")
    again = recent._fetch_soccer_api_data(use_cache=True)
    check("still one fetch", len(fetches) == 1, fetches)
    check("the cached schedule is returned", again == data, again)

    print("\nthe recent and upcoming managers of a league share one fetch")
    cache, fetches = DictCache(), []
    pair = [manager(sm.SoccerRecentManager, cache, fetches),
            manager(sm.SoccerUpcomingManager, cache, fetches)]
    results = [None, None]

    def run(i):
        results[i] = pair[i]._fetch_soccer_api_data(use_cache=True)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    check("both missed together, one fetched", len(fetches) == 1, fetches)
    check("both got the schedule", results[0] == results[1] == {"events": [{"id": "1"}]},
          results)

    print("\ndifferent leagues are not serialised behind each other")
    cache, fetches = DictCache(), []
    leagues = ["eng.1", "esp.1", "ger.1", "ita.1"]
    managers = [manager(sm.SoccerRecentManager, cache, fetches, league) for league in leagues]
    started = time.monotonic()
    threads = [threading.Thread(target=m._fetch_soccer_api_data) for m in managers]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    elapsed = time.monotonic() - started
    check("one fetch per league", len(fetches) == len(leagues), fetches)
    check("they ran side by side (%.2fs for 4 x 0.05s)" % elapsed, elapsed < 0.15, elapsed)

    print("\nuse_cache=False still fetches")
    cache, fetches = DictCache(), []
    m = manager(sm.SoccerRecentManager, cache, fetches)
    m._fetch_soccer_api_data(use_cache=True)
    m._fetch_soccer_api_data(use_cache=False)
    check("two fetches", len(fetches) == 2, fetches)

    print("\nthe managers share the core's connection pool")
    try:
        from src.common.fetch_service import get_fetch_service
    except ImportError:
        print("  [skip] this core has no shared fetch service")
    else:
        check("the shared-pool helper was imported",
              getattr(sm, "share_connection_pool", None) is not None)
        import requests
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        sessions = []
        for _ in range(2):
            session = requests.Session()
            session.mount("https://", HTTPAdapter(max_retries=Retry(
                total=5, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["GET", "HEAD", "OPTIONS"])))
            sessions.append(session)

        # Run the constructor's sharing step on its own: the rest of the
        # constructor needs fonts, a display and logos.
        for session in sessions:
            sm.share_connection_pool(session, session.get_adapter("https://").max_retries)
        a, b = (s.get_adapter("https://") for s in sessions)
        check("two managers' sessions use one adapter (one pool)", a is b)
        check("...the core's shared one", a is get_fetch_service().shared_adapter(a.max_retries))
        check("...with the retry policy the manager mounted",
              a.max_retries.total == 5 and a.max_retries.backoff_factor == 1)
        src = (plugin_dir / "soccer_managers.py").read_text(encoding="utf-8")
        check("BaseSoccerManager.__init__ shares its session's pool",
              "share_connection_pool(\n                    self.session" in src)

    print("\n%s" % ("FAILED: %d" % len(failures) if failures else "All checks passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
