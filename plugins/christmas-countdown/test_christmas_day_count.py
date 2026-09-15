#!/usr/bin/env python3
"""Tests the day count is right on every frame, not only after update().

Regressions under test:

1. days_until_christmas is initialised to 0 and display()'s "ensure update()
   has been called" guard tested hasattr(), which is always true. A display()
   before the first update() therefore drew "MERRY CHRISTMAS" -- in any month.
2. The count was recomputed only on update_interval (default 3600 s), so after
   midnight it lagged by up to an hour, including "1 DAYS" on 25 December.
3. The date came from date.today(), the Pi's system zone, not the LEDMatrix
   timezone setting.

Run: <core-venv>/bin/python plugins/christmas-countdown/test_christmas_day_count.py
"""

import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))
_core = os.environ.get("LEDMATRIX_CORE")
_candidates = [Path(_core)] if _core else []
_candidates.append(PLUGIN_DIR.parents[2] / "LEDMatrix")
CORE = None
for candidate in _candidates:
    if (candidate / "src" / "plugin_system" / "base_plugin.py").exists():
        CORE = candidate
        sys.path.insert(0, str(candidate))
        break
if CORE is None:
    print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
    sys.exit(2)

try:
    from zoneinfo import ZoneInfo
    ZoneInfo("Pacific/Kiritimati")
    from src.plugin_system.testing.visual_display_manager import VisualTestDisplayManager
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


def _plugin(tz=None):
    dm = VisualTestDisplayManager(128, 32)
    p = manager.ChristmasCountdownPlugin("christmas-countdown", {"enabled": True}, dm, None, _PluginManager(tz))
    return p, dm


def _expected_days(today):
    xmas = date(today.year, 12, 25)
    if today > xmas:
        xmas = date(today.year + 1, 12, 25)
    return (xmas - today).days


os.chdir(str(CORE))

today = date.today()
print("display() before the first update()")
p, _ = _plugin()
p.display(force_clear=True)
if (today.month, today.day) != (12, 25):
    check("does not draw MERRY CHRISTMAS on a non-Christmas day",
          p.last_displayed_message and "MERRY" not in p.last_displayed_message)
check("shows today's count without update()", p.days_until_christmas == _expected_days(today))

print("stale count is refreshed by display()")
p, _ = _plugin()
p.update()
p.days_until_christmas, p.is_christmas = 99999, False  # as if computed long ago
p.display(force_clear=True)
check("display() recomputes instead of trusting the last update()",
      p.days_until_christmas == _expected_days(today))

print("timezone")
east_today = datetime.now(ZoneInfo("Pacific/Kiritimati")).date()
west_today = datetime.now(ZoneInfo("Pacific/Pago_Pago")).date()
east, _ = _plugin("Pacific/Kiritimati")
west, _ = _plugin("Pacific/Pago_Pago")
east.display(force_clear=True)
west.display(force_clear=True)
check("count follows the LEDMatrix timezone (UTC+14)",
      east.days_until_christmas == _expected_days(east_today))
check("count follows the LEDMatrix timezone (UTC-11)",
      west.days_until_christmas == _expected_days(west_today))
bad, _ = _plugin("Not/AZone")
bad.display(force_clear=True)
check("an invalid timezone falls back to system time",
      bad.days_until_christmas == _expected_days(date.today()))

if failures:
    print("\n%d failure(s)" % len(failures))
    sys.exit(1)
print("\nall passed")
sys.exit(0)
