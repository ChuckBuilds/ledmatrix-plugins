#!/usr/bin/env python3
"""
Regression tests for configurable rotation views + overhead live-priority preempt.

Covers:
  - `_get_available_modes`: legacy single slot, per-view rotation slots, the
    "none" (empty) case, invalid-view filtering, and the overhead live slot.
  - The proximity latch: an aircraft entering the radius makes the plugin "live"
    for the full proximity window, even after it leaves the radius.
  - `display()` returning False (skip) for an inactive live slot, an empty
    rotation slot, and an unknown slot name.

Run with the core venv:
    .venv/bin/python plugins/ledmatrix-flights/test/test_rotation_views_and_overhead.py
"""

import logging
import sys
import time
import types
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_DIR))

# Stub the core's BasePlugin so `manager` imports without the full LEDMatrix core
# tree on the path. We bypass __init__ in these tests, so a no-op base is enough.
if "src.plugin_system.base_plugin" not in sys.modules:
    src_mod = types.ModuleType("src")
    plugin_system_mod = types.ModuleType("src.plugin_system")
    base_plugin_mod = types.ModuleType("src.plugin_system.base_plugin")

    class _StubBasePlugin:  # pragma: no cover - trivial stub
        def __init__(self, *args, **kwargs):
            pass

    base_plugin_mod.BasePlugin = _StubBasePlugin
    src_mod.plugin_system = plugin_system_mod
    plugin_system_mod.base_plugin = base_plugin_mod
    sys.modules["src"] = src_mod
    sys.modules["src.plugin_system"] = plugin_system_mod
    sys.modules["src.plugin_system.base_plugin"] = base_plugin_mod

logging.basicConfig(level=logging.CRITICAL)

from manager import FlightTrackerPlugin  # noqa: E402


def make_plugin(config):
    """Build a FlightTrackerPlugin with only the attributes the units-under-test
    need, bypassing the heavy real __init__ (which requires display/cache managers).
    """
    p = FlightTrackerPlugin.__new__(FlightTrackerPlugin)
    p.config = config
    p.logger = logging.getLogger("flight-test")

    pc = config.get("proximity_alert", {})
    p.proximity_enabled = pc.get("enabled", True)
    p.proximity_distance_miles = pc.get("distance_miles", 0.1)
    p.proximity_duration = pc.get("duration_seconds", 30)
    p.proximity_cooldown = pc.get("cooldown_seconds", 30)
    p.live_priority_enabled = config.get("live_priority", False)
    p.update_interval = config.get("update_interval", 5)
    p.live_update_interval = config.get("live_update_interval", 2)

    p.display_mode = config.get("display_mode", "auto")
    # Overhead state machine
    p._lock_icao = None
    p._lock_start = 0.0
    p._lock_aircraft = None
    p._cooldown_until = 0.0
    p._active_overhead_aircraft = None

    p.aircraft_data = {}
    p.all_aircraft_data = {}
    p.tracked_flight_data = {}

    # Flight-records state (consulted by stats content checks)
    p.flight_records_enabled = config.get("flight_records", {}).get("enabled", True)
    p._closest_record = None
    p._farthest_record = None

    # display() preamble attrs
    p._last_displayed_time = 0.0
    p._display_idle_threshold = 30.0
    p.fr24_enrichment = False
    p.last_fr24_enrichment = 0.0

    p.modes = p._get_available_modes()
    return p


def _aircraft(distance_miles, icao="abc123", callsign="TEST123"):
    return {"icao": icao, "callsign": callsign, "distance_miles": distance_miles}


def _set(p, *aircraft):
    """Replace aircraft_data with the given aircraft (keyed by icao)."""
    p.aircraft_data = {a["icao"]: a for a in aircraft}


# ---------------------------------------------------------------------------
# _get_available_modes
# ---------------------------------------------------------------------------

def test_legacy_single_slot():
    p = make_plugin({})  # no rotation_views, live_priority off
    assert p.modes == ["flight_tracker"], p.modes


def test_legacy_with_overhead_priority():
    p = make_plugin({"live_priority": True})
    assert p.modes == ["flight_tracker", "flight_tracker_live"], p.modes


def test_rotation_views_subset_preserves_order():
    p = make_plugin({"rotation_views": ["stats", "map"]})
    assert p.modes == ["flight_tracker_stats", "flight_tracker_map"], p.modes


def test_rotation_views_filters_invalid_and_overhead():
    # 'overhead' and unknown views are not valid rotation views.
    p = make_plugin({"rotation_views": ["map", "overhead", "bogus", "area"]})
    assert p.modes == ["flight_tracker_map", "flight_tracker_area"], p.modes


def test_none_rotation_with_overhead_only():
    p = make_plugin({"rotation_views": [], "live_priority": True})
    assert p.modes == ["flight_tracker_live"], p.modes


def test_none_rotation_without_priority_is_empty():
    p = make_plugin({"rotation_views": []})
    assert p.modes == [], p.modes


def test_rotation_views_plus_overhead():
    p = make_plugin({"rotation_views": ["map", "stats"], "live_priority": True})
    assert p.modes == [
        "flight_tracker_map",
        "flight_tracker_stats",
        "flight_tracker_live",
    ], p.modes


# ---------------------------------------------------------------------------
# Overhead state machine: lock-on, hard cap, cooldown
# ---------------------------------------------------------------------------

def _cfg(**proximity):
    base = {"distance_miles": 0.5, "duration_seconds": 20, "cooldown_seconds": 30}
    base.update(proximity)
    return {"live_priority": True, "proximity_alert": base}


def test_lock_on_acquires_and_reports_live():
    p = make_plugin(_cfg())
    _set(p, _aircraft(0.3, icao="AAA", callsign="AAL1"))
    assert p.has_live_priority() is True
    assert p.has_live_content() is True
    assert p.get_live_modes() == ["flight_tracker_live"]
    assert p._lock_icao == "AAA"
    assert p._lock_aircraft["callsign"] == "AAL1"


def test_lock_on_does_not_switch_to_closer_plane():
    # Once locked, a newly-closer plane must NOT steal the screen mid-window.
    p = make_plugin(_cfg())
    _set(p, _aircraft(0.3, icao="AAA", callsign="AAL1"))
    assert p.has_live_content() is True
    assert p._lock_icao == "AAA"
    # A closer plane appears; the lock stays on AAA.
    _set(p, _aircraft(0.3, icao="AAA", callsign="AAL1"),
            _aircraft(0.05, icao="BBB", callsign="BAW2"))
    assert p.has_live_content() is True
    assert p._lock_icao == "AAA"
    assert p._lock_aircraft["callsign"] == "AAL1"


def test_hard_cap_releases_even_if_plane_lingers():
    # The flight is held only for duration_seconds, even if it stays in the radius.
    p = make_plugin(_cfg(duration_seconds=20))
    _set(p, _aircraft(0.1, icao="AAA"))
    assert p.has_live_content() is True
    # Simulate the cap elapsing while the plane is still overhead.
    p._lock_start = time.time() - 21
    assert p.has_live_content() is False          # released
    assert p._lock_icao is None
    assert p._cooldown_until > time.time()        # cooldown started


def test_window_holds_after_plane_leaves_radius():
    # A plane that flew over still shows for the full window after leaving the radius.
    p = make_plugin(_cfg(duration_seconds=20))
    _set(p, _aircraft(0.1, icao="AAA"))
    assert p.has_live_content() is True
    # Plane leaves the radius but we are still inside the window.
    _set(p, _aircraft(5.0, icao="AAA"))
    assert p.has_live_content() is True
    assert p._lock_icao == "AAA"


def test_cooldown_blocks_repreempt():
    p = make_plugin(_cfg(duration_seconds=20, cooldown_seconds=30))
    _set(p, _aircraft(0.1, icao="AAA"))
    assert p.has_live_content() is True
    p._lock_start = time.time() - 21
    assert p.has_live_content() is False          # released into cooldown
    # Another plane is overhead, but cooldown suppresses the preempt.
    _set(p, _aircraft(0.05, icao="BBB"))
    assert p.has_live_content() is False
    assert p.get_live_modes() == []
    # After cooldown, the next plane can lock on.
    p._cooldown_until = time.time() - 1
    assert p.has_live_content() is True
    assert p._lock_icao == "BBB"


def test_cooldown_zero_allows_immediate_relock():
    p = make_plugin(_cfg(duration_seconds=20, cooldown_seconds=0))
    _set(p, _aircraft(0.1, icao="AAA"))
    assert p.has_live_content() is True
    p._lock_start = time.time() - 21
    assert p.has_live_content() is False          # released, no cooldown
    _set(p, _aircraft(0.1, icao="BBB"))
    assert p.has_live_content() is True
    assert p._lock_icao == "BBB"


def test_live_priority_requires_optin():
    # Without live_priority, a close aircraft never preempts the rotation.
    p = make_plugin({"proximity_alert": {"distance_miles": 0.5}})
    _set(p, _aircraft(0.05))
    assert p.has_live_priority() is False
    assert p.has_live_content() is False
    assert p.get_live_modes() == []
    assert p._lock_icao is None


def test_proximity_disabled_has_no_live_content():
    p = make_plugin({"live_priority": True, "proximity_alert": {"enabled": False}})
    _set(p, _aircraft(0.01))
    assert p.has_live_content() is False
    assert p.has_live_priority() is False


# ---------------------------------------------------------------------------
# Dynamic fetch interval
# ---------------------------------------------------------------------------

def test_fetch_interval_speeds_up_when_locked():
    p = make_plugin(_cfg(distance_miles=0.5))
    p.update_interval = 5
    p.live_update_interval = 2
    # Idle: the effective interval is the normal one.
    assert (p.live_update_interval if p._lock_icao is not None else p.update_interval) == 5
    _set(p, _aircraft(0.1, icao="AAA"))
    p.has_live_content()  # acquire lock
    assert p._lock_icao == "AAA"
    assert (p.live_update_interval if p._lock_icao is not None else p.update_interval) == 2


def test_update_expires_stale_lock():
    # Regression: if rendering stops while a flight is locked, _evaluate_proximity()
    # never runs, so update() itself must expire a timed-out lock — otherwise the
    # stale lock pins fetching at the live cadence forever.
    p = make_plugin(_cfg(duration_seconds=20, cooldown_seconds=30))
    # Minimal attrs for update()'s no-op path (fetch branch skipped via last_fetch).
    p.data_source = "adsbfi"
    p.last_fetch = time.time()
    p.pending_fr24_details = {}
    p.tracked_flights_cfg = []
    p.metar_enabled = False     # update() reads it; make_plugin does not set it

    _set(p, _aircraft(0.1, icao="AAA"))
    p.has_live_content()  # acquire lock
    assert p._lock_icao == "AAA"

    # Simulate the lock outliving its hard cap with no render path advancing it.
    p._lock_start = time.time() - 21
    p.update()

    assert p._lock_icao is None, "update() should expire a timed-out lock"
    assert p._cooldown_until > time.time(), "expiry should start the cooldown"
    # Polling falls back to the normal interval once the lock is gone.
    assert (p.live_update_interval if p._lock_icao is not None else p.update_interval) == p.update_interval


# ---------------------------------------------------------------------------
# display() skip behavior (returns False -> framework rotates on)
# ---------------------------------------------------------------------------

def test_display_live_slot_skips_when_inactive():
    p = make_plugin({"live_priority": True})
    p.aircraft_data = {"abc123": _aircraft(5.0)}  # nothing overhead
    assert p.display(display_mode="flight_tracker_live") is False


def test_display_empty_rotation_view_skips():
    p = make_plugin({"rotation_views": ["map"]})
    p.aircraft_data = {}  # empty map -> skip
    assert p.display(display_mode="flight_tracker_map") is False


def test_display_unknown_slot_skips():
    p = make_plugin({"rotation_views": []})
    # The plugin-id fallback slot the core injects when modes is empty.
    assert p.display(display_mode="ledmatrix-flights") is False


# ---------------------------------------------------------------------------
# _view_has_content
# ---------------------------------------------------------------------------

def test_view_has_content():
    p = make_plugin({})
    # With no live aircraft and no saved records, the stats slot is empty so the
    # rotation can skip it instead of dwelling on "No Aircraft".
    assert p._view_has_content("stats") is False
    assert p._view_has_content("map") is False
    assert p._view_has_content("flight_tracking") is False

    # Live aircraft make stats (and map/area) renderable.
    p.aircraft_data = {"abc123": _aircraft(2.0)}
    assert p._view_has_content("stats") is True
    assert p._view_has_content("map") is True
    assert p._view_has_content("area") is True

    # A saved record alone is enough for stats, even with no live aircraft.
    p.aircraft_data = {}
    p._closest_record = {"callsign": "REC1", "distance_miles": 0.2}
    assert p._view_has_content("stats") is True

    # ...unless flight records are disabled.
    p.flight_records_enabled = False
    assert p._view_has_content("stats") is False


def run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:  # pragma: no cover
            failures += 1
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return failures == 0


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
