#!/usr/bin/env python3
"""
Tests that a bad timezone string warns and falls back instead of blanking.

Regression under test: validate_config() returned False for a timezone pytz
did not recognise, and core (plugin_manager) refuses to load a plugin whose
validation fails -- so a one-letter typo in `timezone`, or in a city's
`timezone`, took the whole world clock off the rotation. _get_timezone()
already had a fallback; validation contradicted it.

Also pins the live renderer's 4x6 face to the 7px pixel grid that
render_preview.py already uses (#480).

Run: <core-venv>/bin/python plugins/geochron/test_timezone_fallback.py
"""

import os
import sys
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))
_core = os.environ.get("LEDMATRIX_CORE")
_candidates = [Path(_core)] if _core else []
_candidates.append(plugin_dir.parents[2] / "LEDMatrix")
for candidate in _candidates:
    if (candidate / "src" / "plugin_system" / "base_plugin.py").exists():
        sys.path.insert(0, str(candidate))
        break

try:
    import manager  # noqa: E402
except ImportError as exc:
    print("SKIP: cannot import geochron manager (%s); set LEDMATRIX_CORE" % exc)
    sys.exit(2)

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

failures = []


def check(label, ok):
    print(("  PASS  " if ok else "  FAIL  ") + label)
    if not ok:
        failures.append(label)


class _DisplayManager:
    width = 128
    height = 32


class _ConfigManager:
    def __init__(self, tz):
        self.tz = tz

    def get_timezone(self):
        return self.tz


class _PluginManager:
    def __init__(self, tz):
        self.config_manager = _ConfigManager(tz)


def _make(config, global_tz="UTC"):
    cfg = {"enabled": True}
    cfg.update(config)
    return manager.GeochronPlugin("geochron", cfg, _DisplayManager(), None, _PluginManager(global_tz))


print("bad plugin timezone")
p = _make({"timezone": "America/Chicagoo"}, global_tz="Europe/Berlin")
check("validate_config passes (plugin still loads)", p.validate_config() is True)
check("falls back to the LEDMatrix timezone", str(p.timezone) == "Europe/Berlin")

print("bad plugin and global timezone")
p = _make({"timezone": "Nope/Nope"}, global_tz="Also/Bad")
check("validate_config passes", p.validate_config() is True)
check("falls back to a usable system zone", p.timezone is not None)

print("bad city timezone")
p = _make({"timezone": "UTC", "cities": [
    {"name": "Typo", "lat": 10.0, "lon": 10.0, "timezone": "Mars/Olympus"}]})
check("validate_config passes", p.validate_config() is True)

print("valid timezone is untouched")
p = _make({"timezone": "Asia/Tokyo"})
check("uses the configured zone", str(p.timezone) == "Asia/Tokyo")

print("font on the pixel grid")
check("4x6 face loads at 7px, matching render_preview.py", manager.FONT_SIZE == 7)

if failures:
    print("\n%d failure(s)" % len(failures))
    sys.exit(1)
print("\nall passed")
sys.exit(0)
