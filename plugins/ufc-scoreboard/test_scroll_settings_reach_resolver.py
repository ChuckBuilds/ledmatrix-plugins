#!/usr/bin/env python3
"""
ufc-scoreboard: ufc.scroll_settings reach the shared resolver, and the frame
hold is applied and released.

Regressions under test:

1. ScrollDisplayManager handed the whole plugin config to
   ``scroll_config.configure``, which never looks in ``ufc.scroll_settings``,
   so scroll_speed / scroll_delay were dead and every user got its 100 px/s
   default.
2. ``_scroll_frame_hold()`` was computed and never passed to
   ``display_manager.set_scrolling_state``.

Run: LEDMATRIX_CORE=/path/to/LEDMatrix python plugins/ufc-scoreboard/test_scroll_settings_reach_resolver.py
Exit: 0 pass, 1 fail, 2 skip (no core checkout).
"""

import os
import sys
from pathlib import Path

plugin_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(plugin_dir))
_core = os.environ.get("LEDMATRIX_CORE")
_candidates = [Path(_core)] if _core else []
_candidates.append(plugin_dir.parents[2] / "LEDMatrix")
for candidate in _candidates:
    if (candidate / "src" / "plugin_system" / "base_plugin.py").exists():
        sys.path.insert(0, str(candidate))
        break
else:
    print("SKIP: no LEDMatrix core checkout (set LEDMATRIX_CORE)")
    sys.exit(2)

from PIL import Image  # noqa: E402

from scroll_display import ScrollDisplayManager  # noqa: E402

failures = []


def check(label, ok):
    print(("  PASS  " if ok else "  FAIL  ") + label)
    if not ok:
        failures.append(label)


class _Logger:
    def __getattr__(self, name):
        return lambda *a, **k: None


class _DisplayManager:
    width, height = 128, 32
    matrix = None
    refresh_hz = 100.0

    def __init__(self):
        self.calls = []
        self.image = None

    def set_scrolling_state(self, is_scrolling, frame_hold=1):
        self.calls.append((is_scrolling, frame_hold))

    def update_display(self):
        pass


def _manager(scroll_settings):
    dm = _DisplayManager()
    config = {"ufc": {"scroll_settings": scroll_settings}}
    return ScrollDisplayManager(dm, config, _Logger(), global_config={}), dm


print("speed")
m, dm = _manager({"scroll_speed": 50.0, "scroll_delay": 0.01})
s = getattr(m, "_scroll_settings", None)
check("scroll_speed=50 px/s is what the resolver was asked for (not 100)",
      s is not None and abs(s.requested_pixels_per_second - 50.0) < 0.01)
m2, _ = _manager({"scroll_speed": 5.0, "scroll_delay": 0.01})
s2 = getattr(m2, "_scroll_settings", None)
check("a value under 10 is px/s like any other, as schema and README say (5, not 5 / 0.01 = 500)",
      s2 is not None and abs(s2.requested_pixels_per_second - 5.0) < 0.01
      and s2.source != "default")
m3, _ = _manager({"scroll_speed": 100.0, "scroll_delay": 0.03})
s3 = getattr(m3, "_scroll_settings", None)
check("scroll_delay does not change the speed (100 px/s with delay 0.03)",
      s3 is not None and abs(s3.requested_pixels_per_second - 100.0) < 0.01)

print("frame hold")
hold = s.frame_hold if s is not None else 1
m.scroll_helper.create_scrolling_image(
    [Image.new("RGB", (400, 32), (255, 255, 255))], item_gap=0, element_gap=0)
m.display_scroll_frame()
check(f"set_scrolling_state(True, frame_hold={hold}) while a frame is drawn (hold > 1)",
      hold > 1 and (True, hold) in dm.calls)
dm.calls.clear()
m.scroll_helper.is_scroll_complete = lambda: True
m.is_scroll_complete()
check("released when the scroll completes", bool(dm.calls) and dm.calls[-1][0] is False)

if failures:
    print(f"\n{len(failures)} failure(s)")
    sys.exit(1)
print("\nall passed")
sys.exit(0)
