#!/usr/bin/env python3
"""Regression test: the deprecated radar_zoom is honoured, as documented.

_parse_radar_config consulted radar_zoom only when radar_range_miles was
missing. The core merges schema defaults into every config (radar_range_miles
75, radar_zoom 6), so it never was, and a config saved with radar_zoom 8
(12 miles) silently showed 75 miles. The zoom now counts while the range is
still at its default and the zoom is not its own default.

Run with the core on the path (manager imports src.*):
    LEDMATRIX_CORE=/path/to/LEDMatrix python plugins/ledmatrix-weather/test_radar_zoom_back_compat.py
Exit 0 pass, 2 skip, 1 fail.
"""

import logging
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
_core = os.environ.get("LEDMATRIX_CORE")
if _core and _core not in sys.path:
    sys.path.insert(0, _core)

try:
    from manager import WeatherPlugin  # noqa: E402
except ImportError as exc:
    print(f"SKIP: weather manager does not import without the core ({exc})")
    sys.exit(2)

logging.disable(logging.CRITICAL)

failures = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ((": " + detail) if detail and not cond else ""))
    if not cond:
        failures.append(name)


def range_for(config):
    shell = WeatherPlugin.__new__(WeatherPlugin)
    return WeatherPlugin._parse_radar_config(shell, config)["range_miles"]


# As the core hands it over: schema defaults merged under the saved values.
MERGED = {"radar_range_miles": 75, "radar_zoom": 6}

cases = [
    ("defaults only -> 75", dict(MERGED), 75.0),
    ("saved radar_zoom 8, range at default -> 12", {**MERGED, "radar_zoom": 8}, 12.0),
    ("saved radar_zoom 4, range at default -> 200", {**MERGED, "radar_zoom": 4}, 200.0),
    ("radar_range_miles changed wins over radar_zoom", {**MERGED, "radar_range_miles": 40, "radar_zoom": 8}, 40.0),
    ("zoom at its default 6 leaves the new default range", {**MERGED, "radar_zoom": 6}, 75.0),
    ("unmerged config: zoom only -> its range", {"radar_zoom": 7}, 25.0),
    ("unmerged config: nothing set -> 75", {}, 75.0),
    ("unknown zoom value -> 75", {**MERGED, "radar_zoom": 12}, 75.0),
]
for name, cfg, want in cases:
    got = range_for(cfg)
    check(name, got == want, f"got {got!r}, want {want!r}")

if failures:
    print(f"\n{len(failures)} failure(s)")
    sys.exit(1)
print("\nall passed")
sys.exit(0)
