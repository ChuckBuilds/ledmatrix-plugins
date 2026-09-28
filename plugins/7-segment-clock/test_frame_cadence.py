#!/usr/bin/env python3
"""The clock at the core's real frame rate: once a second, a little over.

* The flashing colon read the second's parity. Sampled every ~1.03 s, a
  second is skipped now and then and the colon held for two frames, so the
  blink stuttered. It must now alternate on every frame.
* A new minute called display_manager.clear(), which blanks the lit panel as
  well as the buffer: the clock flashed black once a minute. Only mode entry
  (first frame / force_clear) may clear; later frames just repaint.

Run with the core on PYTHONPATH:
    PYTHONPATH=/path/to/LEDMatrix python test_frame_cadence.py
Exit 0 pass, 1 fail, 2 skip.
"""
import logging
import os
import sys
import time
from datetime import datetime, timedelta

import pytz

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from src.plugin_system.testing.mocks import (
        MockCacheManager, MockDisplayManager, MockPluginManager)
    import manager  # noqa: E402
except ImportError as exc:
    print("SKIP: %s" % exc)
    sys.exit(2)

failures = []


def check(label, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + label + (("  -- " + detail) if detail and not ok else ""))
    if not ok:
        failures.append(label)


class CountingDisplay(MockDisplayManager):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.clears = 0
        self.frames = []

    def clear(self):
        self.clears += 1
        super().clear()

    def update_display(self):
        self.frames.append(self.image.copy())


def run(frames, period=1.03, start="2026-08-01 15:24:40"):
    """Render ``frames`` frames ``period`` seconds apart; return the display
    and whether the colon was lit on each frame."""
    display = CountingDisplay(128, 32)
    plugin = manager.SevenSegmentClockPlugin(
        "7-segment-clock",
        {"enabled": True, "location": {"timezone": "UTC"}, "has_flashing_separator": True},
        display, MockCacheManager(), MockPluginManager())
    plugin.logger = logging.getLogger("test-7seg")
    t0 = pytz.UTC.localize(datetime.strptime(start, "%Y-%m-%d %H:%M:%S"))
    clock = [0.0]
    time.monotonic = lambda: clock[0]
    lit = []
    for i in range(frames):
        clock[0] = i * period
        plugin.update = lambda i=i: setattr(plugin, "current_time", t0 + timedelta(seconds=i * period))
        seen = []
        real = plugin._render_separator
        plugin._render_separator = lambda *a, **k: seen.append(True) or real(*a, **k)
        plugin.display(force_clear=(i == 0))
        plugin._render_separator = real
        lit.append(bool(seen))
    return display, lit


display, lit = run(60)
repeats = [i for i in range(1, len(lit)) if lit[i] == lit[i - 1]]
check("the colon alternates on every frame", not repeats,
      "held for two frames at frame(s) %s" % repeats)
check("the first frame follows the second's parity (40 s: lit)", lit[0] is True)
check("one clear() on entry, none when the minute changes", display.clears == 1,
      "%d clears over %d frames spanning a minute change" % (display.clears, len(lit)))

# The buffer is still black under the digits after a minute change: 15:28 ->
# 15:29 changes the last digit, so leftover segments would show as extra
# lit pixels compared with a clean render of the same frame.
def plain_clock(display):
    p = manager.SevenSegmentClockPlugin(
        "7-segment-clock", {"enabled": True, "location": {"timezone": "UTC"},
                            "has_flashing_separator": False},
        display, MockCacheManager(), MockPluginManager())
    p.logger = logging.getLogger("test-7seg")
    return p


def show(p, minute):
    at = pytz.UTC.localize(datetime(2026, 8, 1, 15, minute, 0))
    p.update = lambda: setattr(p, "current_time", at)
    p.display()


clean, fresh = CountingDisplay(128, 32), CountingDisplay(128, 32)
p = plain_clock(clean)
show(p, 28)
show(p, 29)
show(plain_clock(fresh), 29)
check("a new minute leaves no old segments behind",
      clean.frames[-1].tobytes() == fresh.frames[-1].tobytes())

print("%d failed" % len(failures))
sys.exit(1 if failures else 0)
