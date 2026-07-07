#!/usr/bin/env python3
"""
Regression test: ledmatrix-flights applies config edits live.

Before this fix the plugin had no on_config_change override, so the base
BasePlugin only swapped self.config and the derived settings (center, radius,
data source, units, ...) plus the config-bound fetcher/enrichment/renderer
kept their startup values until a display restart. This test fails against the
base behavior and passes once the plugin re-derives state on config change.

Run with the core venv from within a LEDMatrix tree, or set LEDMATRIX_CORE:
    LEDMATRIX_CORE=/path/to/LEDMatrix .venv/bin/python \
        plugins/ledmatrix-flights/test_config_reload.py
"""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

_core = os.environ.get("LEDMATRIX_CORE")
if _core and _core not in sys.path:
    sys.path.insert(0, _core)

from manager import FlightTrackerPlugin  # noqa: E402
from data_model import TrackedFlight  # noqa: E402

_passed = 0
_failed = 0


def check(cond, msg):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS: {msg}")
    else:
        _failed += 1
        print(f"  FAIL: {msg}")


class _Matrix:
    width = 128
    height = 64


class _DisplayManager:
    matrix = _Matrix()


class _CacheManager:
    def __init__(self, cache_dir):
        self.cache_dir = cache_dir


def _make_tracker(config):
    return FlightTrackerPlugin(
        "ledmatrix-flights",
        config,
        display_manager=_DisplayManager(),
        cache_manager=_CacheManager(tempfile.mkdtemp()),
        plugin_manager=object(),
    )


def test_on_config_change_applies_live():
    print("[ledmatrix-flights on_config_change]")
    tracker = _make_tracker(
        {
            "data_source": "skyaware",
            "center_latitude": 27.95,
            "center_longitude": -82.45,
            "map_radius_miles": 10,
            "units": "imperial",
        }
    )
    check(tracker.data_source == "skyaware", "initial data_source derived")
    check(tracker.center_lat == 27.95, "initial center derived")
    fetcher_before = tracker._fetcher
    renderer_before = tracker._renderer

    # Prime the cached map so we can confirm it is invalidated on change.
    tracker.cached_map_bg = "SENTINEL"
    tracker.last_map_center = (27.95, -82.45)

    tracker.on_config_change(
        {
            "data_source": "adsbfi",
            "center_latitude": 47.61,
            "center_longitude": -122.33,
            "map_radius_miles": 25,
            "units": "metric",
            "max_aircraft": 9,
            "live_priority": True,
        }
    )

    check(tracker.data_source == "adsbfi", "data_source updated live")
    check(tracker.center_lat == 47.61 and tracker.center_lon == -122.33, "center updated live")
    check(tracker.map_radius_miles == 25, "radius updated live")
    check(tracker.units_system == "metric", "units updated live")
    check(tracker.max_aircraft == 9, "max_aircraft updated live")
    check(tracker.live_priority_enabled is True, "live_priority updated live")
    check(tracker._fetcher is not fetcher_before, "fetcher rebuilt for new data source")
    check(tracker._renderer is not renderer_before, "renderer rebuilt with new config")
    check(tracker.cached_map_bg is None, "cached map invalidated so it re-tiles")
    check(tracker.last_map_center is None, "cached map center invalidated")


def test_stale_tracked_flight_data_pruned_on_config_change():
    print("[ledmatrix-flights tracked_flight_data pruning]")
    tracker = _make_tracker(
        {
            "data_source": "skyaware",
            "tracked_flights": ["AA123", "UAL456"],
        }
    )
    # Seed runtime tracking state as if both flights had been seen live.
    tracker.tracked_flight_data["AA123"] = TrackedFlight(identifier="AA123")
    tracker.tracked_flight_data["UAL456"] = TrackedFlight(identifier="UAL456")

    tracker.on_config_change(
        {
            "data_source": "skyaware",
            "tracked_flights": ["AA123"],  # UAL456 removed
        }
    )

    check(tracker.tracked_flights_cfg == ["AA123"], "tracked_flights_cfg updated live")
    check("AA123" in tracker.tracked_flight_data, "kept flight's runtime state is preserved")
    check(
        "UAL456" not in tracker.tracked_flight_data,
        "removed flight's stale runtime state is pruned",
    )


if __name__ == "__main__":
    test_on_config_change_applies_live()
    test_stale_tracked_flight_data_pruned_on_config_change()
    print(f"\n{_passed} passed, {_failed} failed")
    sys.exit(1 if _failed else 0)
