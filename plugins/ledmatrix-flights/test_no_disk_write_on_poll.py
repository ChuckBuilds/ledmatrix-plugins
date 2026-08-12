#!/usr/bin/env python3
"""Tests that polling SkyAware does not write to the SD card.

The last good payload only ever covers a failed poll, and the reader is the
same process seconds later -- so it belongs in memory. Persisting it through
cache_manager wrote the whole ~55KB SkyAware payload once per update_interval:
measured on a live rig at 12 rewrites/minute, some 928 MB/day, the plugin's
largest single source of card wear by a wide margin.

The fallback also has to expire. Reading it back through cache_manager took
that call's default max_age of 300s, so a receiver outage could hand back a
five-minute-old sky -- around forty miles of error for an airliner -- and the
map would draw aircraft where they plainly were not.

Run: python3 plugins/ledmatrix-flights/test_no_disk_write_on_poll.py
"""

import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))

try:
    import requests
except ImportError:
    print("SKIP: requests not installed")
    sys.exit(2)

import fetcher as ft  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s%s" % (name, (": " + detail) if detail else ""))
        failures.append(name)


class RecordingCache:
    """A cache manager that refuses to be used."""

    def __init__(self):
        self.sets = []
        self.gets = []

    def set(self, key, data, ttl=None):
        self.sets.append(key)

    def get(self, key, *a, **k):
        self.gets.append(key)
        return None


PAYLOAD = {"now": 1, "aircraft": [{"hex": "abc123", "lat": 1.0, "lon": 2.0}]}


def _fetcher(cache):
    return ft.SkyAwareFetcher("http://receiver/data.json", cache, request_timeout=5)


def _serving(payload):
    class R:
        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return payload
    return lambda *a, **k: R()


def _failing():
    def boom(*a, **k):
        raise requests.exceptions.ConnectionError("receiver down")
    return boom


def main():
    real_get, real_time = ft.requests.get, ft.time.time
    clock = {"t": 1000.0}
    ft.time.time = lambda: clock["t"]
    try:
        print("a successful poll touches neither the cache nor the disk")
        cache = RecordingCache()
        f = _fetcher(cache)
        ft.requests.get = _serving(PAYLOAD)
        for _ in range(20):                  # 20 polls, ~100s at the default
            clock["t"] += 5
            f.fetch_raw()
        check("no cache writes", not cache.sets, "wrote %r" % cache.sets)
        check("no cache reads", not cache.gets, "read %r" % cache.gets)

        print("\na failed poll is covered from memory")
        ft.requests.get = _failing()
        clock["t"] += 5
        got = f.fetch_raw()
        check("serves the last payload", got == PAYLOAD, "got %r" % got)
        check("still no cache use", not cache.sets and not cache.gets)

        print("\nbut only while it is recent enough to stand in for now")
        clock["t"] += ft.FALLBACK_MAX_AGE_SECONDS + 1
        check("drops a stale payload", f.fetch_raw() is None)
        check("and does not resurrect it later", f.fetch_raw() is None)

        print("\nthe bound is short enough to be honest about moving aircraft")
        # An airliner at ~500kt covers ~0.14 miles/s.
        miles = ft.FALLBACK_MAX_AGE_SECONDS * 0.14
        check("under ten miles of drift", miles < 10, "%.1f miles" % miles)

        print("\na cold fetcher with nothing cached shows nothing")
        cold = _fetcher(RecordingCache())
        ft.requests.get = _failing()
        check("returns None", cold.fetch_raw() is None)

        print("\nrecovery restores normal service")
        ft.requests.get = _serving(PAYLOAD)
        check("fetches again", cold.fetch_raw() == PAYLOAD)
        ft.requests.get = _failing()
        check("and covers the next failure", cold.fetch_raw() == PAYLOAD)

        print("\nthe manager's own path keeps the same contract")
        src = (PLUGIN_DIR / "manager.py").read_text(encoding="utf-8")
        check("manager no longer caches the payload",
              "cache_manager.set('flight_tracker_data'" not in src)
        check("manager no longer reads it back",
              "cache_manager.get('flight_tracker_data')" not in src)
        check("manager shares the one freshness bound",
              "FALLBACK_MAX_AGE_SECONDS" in src)
    finally:
        ft.requests.get, ft.time.time = real_get, real_time

    print("\n%s" % ("FAILED: %d" % len(failures) if failures else "All checks passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
