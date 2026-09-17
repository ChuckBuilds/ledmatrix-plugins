#!/usr/bin/env python3
"""
march-madness: off-season drops out of rotation, and the frame hold is applied.

Regressions under test:

1. Outside the tournament window display() drew "Off-season" and returned
   None. Core skips a plugin only on a boolean False
   (display_controller.py checks isinstance(result, bool)), so the card took a
   full rotation slot eleven months a year; the README says nothing is shown.
2. ``_scroll_frame_hold()`` was computed and never passed to
   ``display_manager.set_scrolling_state``, so a snapped sub-refresh speed still
   presented a new frame every refresh, and the state was never released.
   (The parked end frame of a one-shot scroll keeps the state; it is released
   when the cycle completes. test_scroll_pacing.py covers why.)

Methods run against an instance built with ``__new__`` (no network).

Run: LEDMATRIX_CORE=/path/to/LEDMatrix python plugins/march-madness/test_offseason_and_frame_hold.py
Exit: 0 pass, 1 fail, 2 skip (no core checkout).
"""

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

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

from PIL import Image, ImageFont  # noqa: E402

import manager  # noqa: E402
from src.common.scroll_helper import ScrollHelper  # noqa: E402

Plugin = getattr(manager, json.loads((plugin_dir / "manifest.json").read_text(encoding="utf-8"))["class_name"])
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
    matrix = SimpleNamespace(width=128, height=32)

    def __init__(self):
        self.calls = []
        self.image = None
        self.frames = 0

    def set_scrolling_state(self, is_scrolling, frame_hold=1):
        self.calls.append((is_scrolling, frame_hold))

    def update_display(self):
        self.frames += 1


def _plugin():
    p = Plugin.__new__(Plugin)
    p.config = {}
    p.logger = _Logger()
    p.enabled = True
    p.display_manager = _DisplayManager()
    p.games_data = []
    p.ticker_image = None
    p.scroll_helper = ScrollHelper(128, 32)
    p._display_start_time = None
    p._end_reached_logged = False
    p.fonts = {"time": ImageFont.load_default()}
    p._march_madness_logo = None
    p.loop = True
    p.dynamic_duration = 60
    return p


print("off-season")
p = _plugin()
p._is_tournament_window = lambda: False
result = p.display()
check("display() returns False outside the tournament window", result is False)
check("nothing is drawn off-season", p.display_manager.frames == 0)

print("frame hold")
p = _plugin()
p._is_tournament_window = lambda: True
p.games_data = [{"id": "1"}]
p.scroll_helper.create_scrolling_image(
    [Image.new("RGB", (400, 32), (255, 255, 255))], item_gap=0, element_gap=0)
p.ticker_image = p.scroll_helper.cached_image
p._scroll_settings = SimpleNamespace(frame_hold=2)
result = p.display()
check("display() returns True while scrolling", result is True)
check("set_scrolling_state(True, frame_hold=2) while scrolling",
      (True, 2) in p.display_manager.calls)

p.display_manager.calls.clear()
p.loop = False
p.scroll_helper.is_scroll_complete = lambda: True
p.dynamic_duration_enabled = True
p.display()
check("the parked end frame of a one-shot scroll keeps the state and hold",
      p.display_manager.calls[-1:] == [(True, 2)])
p.display_manager.calls.clear()
p.is_cycle_complete()
check("released once the cycle completes",
      bool(p.display_manager.calls) and p.display_manager.calls[-1][0] is False)

print("in-window placeholder still shows")
p = _plugin()
p._is_tournament_window = lambda: True
check("no games during the tournament: placeholder drawn, display() True",
      p.display() is True and p.display_manager.frames == 1)

print("config save applies without a restart")
p = _plugin()
p.last_update = 1234.0
p._cached_dynamic_duration = 5.0
p.on_config_change({
    "enabled": True,
    "leagues": {"ncaam": True, "ncaaw": False},
    "favorite_teams": ["duke"],
    "display_options": {"scroll_speed": 2.0, "scroll_delay": 0.02,
                        "show_seeds": False, "max_duration": 120},
    "data_settings": {"update_interval": 600},
})
check("league toggles and favourites follow the save",
      p.show_ncaaw is False and p.favorite_teams == ["DUKE"])
check("display options and update interval follow the save",
      p.show_seeds is False and p.update_interval == 600)
s = getattr(p, "_scroll_settings", None)
check("the resolver re-ran for the saved speed (2 / 0.02 = 100 px/s)",
      s is not None and abs(s.requested_pixels_per_second - 100.0) < 0.01)
check("dynamic-duration settings reach the helper (max 120)", p.scroll_helper.max_duration == 120)
check("the next update refetches", p.last_update == 0 and p._cached_dynamic_duration is None)

if failures:
    print(f"\n{len(failures)} failure(s)")
    sys.exit(1)
print("\nall passed")
sys.exit(0)
