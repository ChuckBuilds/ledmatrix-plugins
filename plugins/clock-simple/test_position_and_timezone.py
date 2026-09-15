#!/usr/bin/env python3
"""
Tests position_x / position_y move the clock, and a bad timezone is not fatal.

Regressions under test:

1. position_x and position_y were read into self.pos_x / self.pos_y and never
   used, so the README's "pixel offsets applied to the whole clock" did
   nothing. The frame is now shifted by the offsets.
2. validate_config() returned False for a timezone pytz did not recognise, and
   core refuses to load a plugin whose validation fails -- a typo blanked the
   clock. It now warns and falls back to the LEDMatrix timezone, then system
   time.

Run: <core-venv>/bin/python plugins/clock-simple/test_position_and_timezone.py
"""

import os
import sys
from pathlib import Path

plugin_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(plugin_dir))
_core = os.environ.get("LEDMATRIX_CORE")
_candidates = [Path(_core)] if _core else []
_candidates.append(plugin_dir.parents[2] / "LEDMatrix")
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
    import pytz  # noqa: F401
    from PIL import ImageChops
    from src.plugin_system.testing.visual_display_manager import VisualTestDisplayManager
    import manager
except ImportError as exc:
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
    def __init__(self, tz="UTC"):
        self.config_manager = _ConfigManager(tz)


def _render(config, global_tz="UTC"):
    dm = VisualTestDisplayManager(128, 32)
    # Colours spelled out as the web UI's merged schema defaults would be:
    # without them _parse_color hands back its list default, which
    # validate_config rejects for an unrelated reason.
    cfg = {"enabled": True, "timezone": "UTC", "time_format": "24h", "show_date": True,
           "customization": {"time_text": {"text_color": [255, 255, 255]},
                             "date_text": {"text_color": [255, 128, 64]},
                             "ampm_text": {"text_color": [255, 255, 128]}}}
    cfg.update(config)
    clock = manager.SimpleClock("clock-simple", cfg, dm, None, _PluginManager(global_tz))
    clock.display()
    return clock, dm.image.copy()


os.chdir(str(CORE))  # the display manager resolves assets/fonts from cwd

print("position offsets")
_, base = _render({})
_, moved = _render({"position_x": 3, "position_y": 2})
check("base frame draws something", base.getbbox() is not None)
bb, mb = base.getbbox(), moved.getbbox()
check("offset frame differs from the default frame",
      ImageChops.difference(base.convert("RGB"), moved.convert("RGB")).getbbox() is not None)
check("content moved right by position_x and down by position_y",
      bb is not None and mb is not None and mb[0] == bb[0] + 3 and mb[1] == bb[1] + 2)
_, zero = _render({"position_x": 0, "position_y": 0})
check("zero offsets render identically to the default",
      ImageChops.difference(base.convert("RGB"), zero.convert("RGB")).getbbox() is None)

print("offset bounds")
import json  # noqa: E402
schema = json.loads((plugin_dir / "config_schema.json").read_text(encoding="utf-8"))
for key in ("position_x", "position_y"):
    spec = schema["properties"][key]
    check("%s bounded in the schema (-256..256)" % key,
          spec.get("minimum") == -256 and spec.get("maximum") == 256)
_, huge = _render({"position_x": 10 ** 6, "position_y": -(10 ** 6)})
_, edge = _render({"position_x": 128, "position_y": -32})
check("a huge stored offset renders like one clamped to the panel size",
      ImageChops.difference(huge.convert("RGB"), edge.convert("RGB")).getbbox() is None)
_, near = _render({"position_x": -3, "position_y": -2})
nb = near.getbbox()
check("negative offsets move the clock left and up",
      bb is not None and nb is not None and nb[2] == bb[2] - 3 and nb[3] == bb[3] - 2)

print("bad timezone")
clock, frame = _render({"timezone": "America/Chicagoo"}, global_tz="Europe/Berlin")
check("validate_config passes (plugin still loads)", clock.validate_config() is True)
check("falls back to the LEDMatrix timezone", str(clock.timezone) == "Europe/Berlin")
check("clock still draws", frame.getbbox() is not None)
clock, frame = _render({"timezone": "Nope/Nope"}, global_tz="Also/Bad")
check("with no usable zone at all, still validates", clock.validate_config() is True)
check("and still draws (system time)", frame.getbbox() is not None)

if failures:
    print("\n%d failure(s)" % len(failures))
    sys.exit(1)
print("\nall passed")
sys.exit(0)
