#!/usr/bin/env python3
"""
Regression test: code defaults mirror config_schema.json.

Seven keys fell back to a different value in code than the schema declares
(e.g. tile_provider "osm" vs "carto_dark", header_color white vs amber). A fresh
install is filled from the schema, so this surfaced only when a key was absent
from the saved config -- a hand-edited config, or a live save that dropped a
section -- and then the board silently rendered differently from what the web
UI showed as the default.

Checks both construction and on_config_change, with configs that omit the keys.

Run with the core venv, LEDMATRIX_CORE pointing at a LEDMatrix checkout:
    LEDMATRIX_CORE=/path/to/LEDMatrix .venv/bin/python \
        plugins/ledmatrix-flights/test_code_defaults_match_schema.py
"""

import json
import logging
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

_core = os.environ.get("LEDMATRIX_CORE")
if _core and _core not in sys.path:
    sys.path.insert(0, _core)

for _stale in ("manager", "data_model", "renderer"):
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


def _schema_default(*path):
    with open(os.path.join(HERE, "config_schema.json"), encoding="utf-8") as f:
        node = json.load(f)
    for key in path:
        node = node["properties"][key]
    return node["default"]


# (schema path, how to read the value the plugin actually uses)
CASES = [
    (("map_background", "tile_provider"), lambda p: p.tile_provider),
    (("map_background", "fade_intensity"), lambda p: p.fade_intensity),
    (("map_background", "custom_tile_server"), lambda p: p.custom_tile_server),
    (("show_trails",), lambda p: p.show_trails),
    (("flightaware", "max_api_calls_per_hour"), lambda p: p.max_api_calls_per_hour),
    (("header_color",), lambda p: list(p._renderer.header_color)),
    (("show_aircraft_icon",), lambda p: p._renderer.show_aircraft_icon),
    (("live_update_interval",), lambda p: p.live_update_interval),
]

# Deliberately omits every key under test (and the sections that hold them).
BARE_CONFIG = {
    "data_source": "skyaware",
    "skyaware_url": "http://127.0.0.1:1/data/aircraft.json",
    "center_latitude": 27.95,
    "center_longitude": -82.45,
}


def main():
    p = FlightTrackerPlugin(
        "ledmatrix-flights",
        dict(BARE_CONFIG),
        display_manager=_DisplayManager(),
        cache_manager=_CacheManager(tempfile.mkdtemp()),
        plugin_manager=object(),
    )
    failures = 0
    for stage in ("__init__", "on_config_change"):
        if stage == "on_config_change":
            p.on_config_change(dict(BARE_CONFIG))
        for path, read in CASES:
            want = _schema_default(*path)
            got = read(p)
            name = ".".join(path)
            if got == want:
                print(f"  PASS: [{stage}] {name} = {got!r}")
            else:
                failures += 1
                print(f"  FAIL: [{stage}] {name}: code default {got!r} != schema default {want!r}")
    print(f"\n{failures} mismatch(es)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
