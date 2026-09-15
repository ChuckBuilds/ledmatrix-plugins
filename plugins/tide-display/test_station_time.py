#!/usr/bin/env python3
"""Tests station-local tide times are compared with "now" in the board's timezone.

Regression under test: NOAA is asked for station-local times
(time_zone=lst_ldt) and they are parsed as naive datetimes, but they were
compared with datetime.now() -- the Pi's system zone, usually UTC. On a UTC Pi
showing a US station the next-tide highlight, past-tide dimming, direction,
current level and the chart's now-marker were 4-10 hours off. "Now" is now
naive wall time in the LEDMatrix timezone.

Also pins _DEF_ELEMENT_FONT to the schema's font_size default.

Run: <core-venv>/bin/python plugins/tide-display/test_station_time.py
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))
_core = os.environ.get("LEDMATRIX_CORE")
_candidates = [Path(_core)] if _core else []
_candidates.append(PLUGIN_DIR.parents[2] / "LEDMatrix")
for candidate in _candidates:
    if (candidate / "src" / "plugin_system" / "base_plugin.py").exists():
        sys.path.insert(0, str(candidate))
        break

try:
    from zoneinfo import ZoneInfo
    ZoneInfo("Pacific/Kiritimati")
    import manager
except Exception as exc:  # ImportError, or no tz database on this host
    print("SKIP: missing dependency (%s)" % exc)
    sys.exit(2)

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

failures = []


def check(label, ok):
    print(("  PASS  " if ok else "  FAIL  ") + label)
    if not ok:
        failures.append(label)


class _ConfigManager:
    def __init__(self, tz):
        self.tz = tz

    def get_timezone(self):
        return self.tz


class _PluginManager:
    def __init__(self, tz=None):
        if tz is not None:
            self.config_manager = _ConfigManager(tz)


def _plugin(tz):
    return manager.TidePlugin("tide-display", {"enabled": True, "station_id": "8454000"},
                              None, None, _PluginManager(tz))


# Two zones 25 hours apart: whichever zone the host is in, at least one of them
# is many hours away from the host's wall clock.
for tz in ("Pacific/Kiritimati", "Pacific/Pago_Pago"):
    print(tz)
    p = _plugin(tz)
    station_now = datetime.now(ZoneInfo(tz)).replace(tzinfo=None)
    p.hilo = [
        {"dt": (station_now - timedelta(hours=1)).isoformat(), "height": 1.0, "type": "L"},
        {"dt": (station_now + timedelta(hours=1)).isoformat(), "height": 5.0, "type": "H"},
    ]
    check("_now() is wall time in the LEDMatrix timezone",
          hasattr(p, "_now") and abs((p._now() - station_now).total_seconds()) < 5)
    nxt = p._next_tides(n=2)
    check("the tide an hour ago is not 'next'", [e["type"] for e in nxt] == ["H"])

print("fallback")
p = _plugin("Not/AZone")
check("invalid timezone falls back to system time",
      hasattr(p, "_now") and abs((p._now() - datetime.now()).total_seconds()) < 5)
p = _plugin(None)
check("no timezone configured uses system time",
      hasattr(p, "_now") and abs((p._now() - datetime.now()).total_seconds()) < 5)

print("element font default")
schema = json.loads((PLUGIN_DIR / "config_schema.json").read_text(encoding="utf-8"))
cust = schema["properties"]["customization"]["properties"]
sizes = {cust[k]["properties"]["font_size"]["default"] for k in ("tide_text", "label_text")}
check("_DEF_ELEMENT_FONT mirrors the schema font_size default",
      sizes == {manager.TidePlugin._DEF_ELEMENT_FONT[1]})

if failures:
    print("\n%d failure(s)" % len(failures))
    sys.exit(1)
print("\nall passed")
sys.exit(0)
