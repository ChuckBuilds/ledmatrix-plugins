#!/usr/bin/env python3
"""Tests that the colour settings reach the panel and "now" uses the board timezone.

Regressions under test:

1. Every display_manager.draw_text() call passed font= but no color=, and the
   core's draw_text defaults to white. The configured colours only went to the
   font manager's registration, which never draws with them. So font_color,
   name_font_color, per-countdown style.*_color and the yellow "today"
   highlight all rendered white.
2. _calculate_time_remaining() compared the user's wall-clock target with
   datetime.now() -- the Pi's system zone, usually UTC -- rather than the
   configured LEDMatrix timezone.

Run: <core-venv>/bin/python plugins/countdown/test_countdown_colors_and_timezone.py
"""

import os
import sys
from datetime import datetime, timedelta
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
    """No font_manager: _resolve_font loads the family file directly."""

    def __init__(self, tz=None):
        self.font_manager = None
        if tz is not None:
            self.config_manager = _ConfigManager(tz)


def _plugin(countdown, tz=None, **cfg):
    config = {
        "enabled": True,
        "countdowns": [dict({"id": "t", "enabled": True, "name": "Launch"}, **countdown)],
        "font_family": "press_start", "font_size": 8,
        "name_font_size": 8, "background_color": [0, 0, 0],
    }
    config.update(cfg)
    dm = VisualTestDisplayManager(128, 32)
    return manager.CountdownPlugin("countdown", config, dm, None, _PluginManager(tz)), dm


def _colors(img):
    return {c for _, c in img.convert("RGB").getcolors(128 * 32)}


os.chdir(str(CORE))

far = (datetime.now() + timedelta(days=100)).strftime("%Y-%m-%d")

print("global colours")
p, dm = _plugin({"target_date": far}, font_color=[255, 0, 0], name_font_color=[0, 255, 0])
p.update()
p.display()
cols = _colors(dm.image)
check("value drawn in font_color (red)", (255, 0, 0) in cols)
check("name drawn in name_font_color (green)", (0, 255, 0) in cols)
check("nothing drawn in the draw_text white default", (255, 255, 255) not in cols)

print("per-countdown style overrides")
p, dm = _plugin({"target_date": far,
                 "style": {"font_color": [0, 0, 255], "name_font_color": [255, 0, 255]}},
                font_color=[255, 0, 0], name_font_color=[0, 255, 0])
p.update()
p.display()
cols = _colors(dm.image)
check("style.font_color wins (blue)", (0, 0, 255) in cols)
check("style.name_font_color wins (magenta)", (255, 0, 255) in cols)
check("global colours not used", (255, 0, 0) not in cols and (0, 255, 0) not in cols)

print("today highlight")
soon = datetime.now() + timedelta(hours=5)
p, dm = _plugin({"target_date": soon.strftime("%Y-%m-%d"), "target_time": soon.strftime("%H:%M")},
                font_color=[255, 0, 0], name_font_color=[0, 255, 0])
p.update()
p.display()
cols = _colors(dm.image)
check("value under 24h drawn yellow", (255, 255, 0) in cols)
check("and not in font_color", (255, 0, 0) not in cols)

print("timezone")
p, _ = _plugin({"target_date": far}, tz="Pacific/Kiritimati")
expected = datetime.now(ZoneInfo("Pacific/Kiritimati")).replace(tzinfo=None)
check("now is wall time in the LEDMatrix timezone (UTC+14)",
      hasattr(p, "_now") and abs((p._now() - expected).total_seconds()) < 5)
# A target 2h ahead of Kiritimati's wall clock is ~25h ahead of Pago Pago's
# (UTC-11): "2h" on one board and "Tomorrow" on the other.
target = expected + timedelta(hours=2)
kw = {"target_date": target.strftime("%Y-%m-%d"), "target_time": target.strftime("%H:%M")}
east, _ = _plugin(kw, tz="Pacific/Kiritimati")
west, _ = _plugin(kw, tz="Pacific/Pago_Pago")
e = east._calculate_time_remaining(kw["target_date"], kw["target_time"])
w = west._calculate_time_remaining(kw["target_date"], kw["target_time"])
check("same target is ~25h apart across the two zones",
      abs((w["total_seconds"] - e["total_seconds"]) - 25 * 3600) < 120)
bad, _ = _plugin({"target_date": far}, tz="Not/AZone")
check("an invalid timezone falls back to system time",
      abs((bad._calculate_time_remaining(far)["total_seconds"])
          - (datetime.strptime(far, "%Y-%m-%d") - datetime.now()).total_seconds()) < 5)

if failures:
    print("\n%d failure(s)" % len(failures))
    sys.exit(1)
print("\nall passed")
sys.exit(0)
