#!/usr/bin/env python3
"""Two in-memory caches must stay bounded on a board that runs for weeks.

* ``bounds_warning_cache`` rate-limits a DEBUG line with one key per
  off-screen coordinate. Aircraft move, so every poll added keys and none was
  ever removed. On a 128x32 panel most in-radius aircraft are off-screen
  vertically, so this grew fastest on the most common panel.
* ``fr24_detail_cache`` held the full FR24 clickhandler JSON for every flight
  ever enriched; its TTL was checked on read but nothing was ever evicted.

Run with the core on PYTHONPATH:
    PYTHONPATH=/path/to/LEDMatrix python <thisfile>
"""
import logging
import os
import sys
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
from manager import FlightTrackerPlugin  # noqa: E402

failures = []


def check(label, ok):
    print(("PASS " if ok else "FAIL ") + label)
    if not ok:
        failures.append(label)


def plugin():
    p = object.__new__(FlightTrackerPlugin)
    p.logger = logging.getLogger("test-flights")
    p.bounds_warning_cache = {}
    p.bounds_warning_interval = 30
    p._bounds_warning_pruned_at = 0.0
    p.fr24_detail_cache = {}
    p.fr24_detail_cache_ttl = 12 * 3600
    # display_width/height are read-only properties off the display manager.
    p._display_manager_ref = SimpleNamespace(matrix=SimpleNamespace(width=128, height=32))
    p.center_lat, p.center_lon = 27.95, -82.46
    p.map_radius_miles = 10
    p.zoom_factor = 1.0
    return p


# --- bounds_warning_cache ------------------------------------------------
p = plugin()
clock = [1_000_000.0]
with mock.patch("manager.time.time", side_effect=lambda: clock[0]):
    # 20 minutes of polls, a new off-screen position every 5 s: 240 keys
    # without pruning.
    for i in range(240):
        clock[0] += 5
        p._latlon_to_pixel(p.center_lat + 0.12, p.center_lon + i * 1e-4)
    size = len(p.bounds_warning_cache)
check("off-screen keys expire instead of piling up (%d kept)" % size, size <= 13)

p = plugin()
with mock.patch("manager.time.time", side_effect=lambda: clock[0]):
    clock[0] += 100
    p._latlon_to_pixel(p.center_lat + 0.12, p.center_lon)
    clock[0] += 1
    with mock.patch.object(p.logger, "debug") as debug:
        p._latlon_to_pixel(p.center_lat + 0.12, p.center_lon)
    check("a repeat within the interval is still rate-limited",
          not any("outside display bounds" in str(c) for c in debug.call_args_list))

# --- fr24_detail_cache ---------------------------------------------------
CAP = 500  # FlightTrackerPlugin.FR24_DETAIL_CACHE_MAX
p = plugin()
p._fr24_headers = {}
now = 2_000_000.0
p.fr24_detail_cache["old"] = {"_fetched_at": now - p.fr24_detail_cache_ttl - 1}
p.fr24_detail_cache["fresh"] = {"_fetched_at": now - 60}
response = mock.Mock()
response.json.side_effect = lambda: {"identification": {}}
response.raise_for_status.return_value = None
with mock.patch("manager.time.time", return_value=now), \
        mock.patch("manager.requests.get", return_value=response):
    p._fetch_fr24_detail("new")
check("an expired detail is evicted on the next fetch", "old" not in p.fr24_detail_cache)
check("a fresh detail is kept", "fresh" in p.fr24_detail_cache)
check("the new detail is cached", "new" in p.fr24_detail_cache)

p = plugin()
p._fr24_headers = {}
with mock.patch("manager.requests.get", return_value=response):
    for i in range(CAP + 50):
        with mock.patch("manager.time.time", return_value=now + i):
            p._fetch_fr24_detail("f%d" % i)
check("the detail cache is capped at %d" % CAP,
      len(p.fr24_detail_cache) == CAP)
check("the cap drops the oldest first",
      "f0" not in p.fr24_detail_cache and "f%d" % (CAP + 49) in p.fr24_detail_cache)

print("%d failed" % len(failures))
sys.exit(1 if failures else 0)
