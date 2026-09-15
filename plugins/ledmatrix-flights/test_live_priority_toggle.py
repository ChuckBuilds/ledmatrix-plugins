#!/usr/bin/env python3
"""
Regression test: turning on live priority takes effect without a restart.

The core reads ``plugin.modes`` exactly once, when the plugin is loaded or
enabled (``DisplayController._register_loaded_plugin``). ``flight_tracker_live``
used to be listed only while live priority was already on, so a board started
with it off registered ``["flight_tracker"]``. Switching it on in the web UI ran
``on_config_change``, which rebuilt ``self.modes`` -- but nothing re-read it, and
the core's live scan only accepts suggested modes it has registered. The
overhead preempt never fired until the display restarted.

This test snapshots the modes at construction (what the core registers), flips
live priority on through ``on_config_change``, puts a plane overhead, and asks
the core's own ``_collect_live_modes`` whether anything is live.

Run with the core venv, LEDMATRIX_CORE pointing at a LEDMatrix checkout:
    LEDMATRIX_CORE=/path/to/LEDMatrix .venv/bin/python \
        plugins/ledmatrix-flights/test_live_priority_toggle.py
"""

import logging
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

_core = os.environ.get("LEDMATRIX_CORE")
if _core and _core not in sys.path:
    sys.path.insert(0, _core)

for _stale in ("manager", "data_model"):
    sys.modules.pop(_stale, None)

try:
    from manager import FlightTrackerPlugin  # noqa: E402
except ImportError as e:
    print(f"SKIP: plugin does not import without the core on the path ({e})")
    sys.exit(2)

logging.basicConfig(level=logging.CRITICAL)


class _Matrix:
    width = 128
    height = 64


class _DisplayManager:
    matrix = _Matrix()


class _CacheManager:
    def __init__(self, cache_dir):
        self.cache_dir = cache_dir


def _collect_live_modes(registered, plugin):
    """Run the core's live scan against the modes the core registered.

    Falls back to a faithful copy of its filter (suggested modes must be
    registered) if the core controller cannot be imported here.
    """
    plugin_modes = {m: plugin for m in registered}
    try:
        from src.display_controller import DisplayController
    except Exception:
        live = []
        for _mode, inst in plugin_modes.items():
            if inst.has_live_priority() and inst.has_live_content():
                for m in inst.get_live_modes() or []:
                    if m in plugin_modes and m not in live:
                        live.append(m)
        return live

    class _Controller:
        pass

    ctrl = _Controller()
    ctrl.plugin_modes = plugin_modes
    return DisplayController._collect_live_modes(ctrl)


def main():
    config = {
        "data_source": "skyaware",
        "skyaware_url": "http://127.0.0.1:1/data/aircraft.json",
        "center_latitude": 27.95,
        "center_longitude": -82.45,
        "live_priority": False,
        "proximity_alert": {"enabled": True, "distance_miles": 0.5},
    }
    p = FlightTrackerPlugin(
        "ledmatrix-flights",
        config,
        display_manager=_DisplayManager(),
        cache_manager=_CacheManager(tempfile.mkdtemp()),
        plugin_manager=object(),
    )
    registered = list(p.modes)  # what the core reads, once, at load
    print(f"  registered at load: {registered}")

    failures = []

    # While live priority is off the slot must not produce content -- the
    # rotation should skip it rather than dwell on a blank screen.
    p.all_aircraft_data = {"abc123": {"icao": "abc123", "callsign": "TEST1",
                                      "distance_miles": 0.1}}
    p.aircraft_data = dict(p.all_aircraft_data)
    if p.has_live_content():
        failures.append("live content reported while live_priority is off")

    new_config = dict(config, live_priority=True)
    p.on_config_change(new_config)

    live = _collect_live_modes(registered, p)
    print(f"  live after enabling at runtime: {live}")
    if live != ["flight_tracker_live"]:
        failures.append(
            "turning live_priority on at runtime did not preempt: the core's live "
            f"scan found {live} against the modes registered at load {registered}")

    for f in failures:
        print(f"  FAIL: {f}")
    if failures:
        return 1
    print("  PASS: live priority enabled at runtime preempts without a restart")
    return 0


if __name__ == "__main__":
    sys.exit(main())
