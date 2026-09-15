#!/usr/bin/env python3
"""
nfl-draft: scroll_speed reaches the shared resolver, the frame hold is applied,
and an auto-detected draft_year follows the calendar on a long-running Pi.

Regressions under test:

1. The schema's only speed key is a root ``scroll_speed`` in pixels per second
   (default 30). The plugin handed the root config to
   ``scroll_config.configure``, whose root step needs a ``scroll_speed`` +
   ``scroll_delay`` pair, so the setting was dead and every user scrolled at
   the resolver's 100 px/s default.
2. ``_scroll_frame_hold()`` was computed and never passed to
   ``display_manager.set_scrolling_state``, so a snapped sub-refresh speed
   (30 px/s is 1px every 3rd refresh at 100Hz) still presented a new frame
   every refresh. Nor was the state ever released.
3. ``draft_year`` was resolved once, at config load. A Pi started during the
   2026 draft kept 2026 forever, so on 2027's draft day ``_is_draft_date()``
   was False and polling stayed at the daily projection interval.

Methods run against an instance built with ``__new__`` (no network, no thread).

Run: LEDMATRIX_CORE=/path/to/LEDMatrix python plugins/nfl-draft/test_scroll_pacing_and_draft_year.py
Exit: 0 pass, 1 fail, 2 skip (no core checkout).
"""

import os
import sys
import threading
import time
from datetime import datetime as _real_datetime
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

import manager  # noqa: E402
from manager import NFLDraftPlugin  # noqa: E402
from src.common.scroll_helper import ScrollHelper  # noqa: E402

failures = []


def check(label, ok):
    print(("  PASS  " if ok else "  FAIL  ") + label)
    if not ok:
        failures.append(label)


class _Logger:
    def __getattr__(self, name):
        return lambda *a, **k: None


class _DisplayManager:
    refresh_hz = 100.0

    def __init__(self):
        self.calls = []
        self.image = None

    def set_scrolling_state(self, is_scrolling, frame_hold=1):
        self.calls.append((is_scrolling, frame_hold))

    def update_display(self):
        pass

    def clear(self):
        pass


def _plugin(config):
    p = NFLDraftPlugin.__new__(NFLDraftPlugin)
    p.config = config
    p.logger = _Logger()
    p.display_manager = _DisplayManager()
    p.display_width, p.display_height = 128, 32
    p.scroll_helper = ScrollHelper(128, 32)
    return p


def _frozen(year, month, day):
    class _Frozen(_real_datetime):
        @classmethod
        def now(cls, tz=None):
            return _real_datetime(year, month, day, 12, 0, 0)
    return _Frozen


print("scroll_speed reaches the resolver")
p = _plugin({"scroll_speed": 30})
p._load_config()
s = p._scroll_settings
check("scroll_speed=30 is what the resolver was asked for (not its 100 px/s default)",
      s is not None and abs(s.requested_pixels_per_second - 30.0) < 0.01)
check("the speed did not come from the resolver's default", s is not None and s.source != "default")

print("frame hold applied while scrolling, released when done")
p._state_lock = threading.Lock()
p.draft_picks = [{"pick_number": 1}]
p.draft_status = "live"
p.scroll_helper.create_scrolling_image(
    [Image.new("RGB", (400, 32), (255, 255, 255))], item_gap=0, element_gap=0)
hold = s.frame_hold if s is not None else 1
result = p.display()
check("display() draws a frame", result is True)
check(f"set_scrolling_state(True, frame_hold={hold}) while scrolling (hold > 1 at 33.3 px/s)",
      hold > 1 and (True, hold) in p.display_manager.calls)
p.display_manager.calls.clear()
p.scroll_helper.is_scroll_complete = lambda: True
p.is_cycle_complete()
check("scrolling state released when the cycle completes",
      bool(p.display_manager.calls) and p.display_manager.calls[-1][0] is False)

print("auto draft_year rolls over on a long-running Pi")
real = manager.datetime
try:
    manager.datetime = _frozen(2026, 4, 24)
    p = _plugin({"draft_year": 0, "post_draft_days": 7})
    p._load_config()
    check("resolved as 2026 when started during the 2026 draft", p.draft_year == 2026)
    p._state_lock = threading.Lock()
    p.draft_picks, p.draft_status, p.is_draft_live, p.current_round = [], "pre", False, 1
    p.last_update_time = time.time()          # a refresh just ran
    p._fetch_draft_picks = lambda round_num=None: []
    p._create_draft_scroll_image = lambda: None

    manager.datetime = _frozen(2027, 4, 24)  # a year later, 2027 draft day
    p.update()
    check("draft_year follows to 2027", p.draft_year == 2027)
    check("2027 draft day is recognised, so polling ramps up", p._is_draft_date())

    p = _plugin({"draft_year": 2025, "post_draft_days": 7})
    p._load_config()
    p._state_lock = threading.Lock()
    p.draft_picks, p.draft_status, p.is_draft_live, p.current_round = [], "pre", False, 1
    p.last_update_time = time.time()
    p.update()
    check("a pinned draft_year is left alone", p.draft_year == 2025)
finally:
    manager.datetime = real

if failures:
    print(f"\n{len(failures)} failure(s)")
    sys.exit(1)
print("\nall passed")
sys.exit(0)
