#!/usr/bin/env python3
"""
Regression tests: upcoming start times are local, and each mode is timed
by its own matches.

1. The renderer drew start_time_utc with strftime directly, i.e. in UTC, so
   an evening match in New York read as the next morning.
2. The core asks for a slot's length with get_display_duration() and no
   mode, right after display(mode). The plugin then used _pick_default_mode()
   -- live, else recent -- so Upcoming ran for the Recent total whenever
   recent matches existed, and mode_durations applied to the wrong mode.

Run: python plugins/cricket-scoreboard/test_local_times_and_mode_duration.py
Exit 0 pass, 1 fail, 2 skip.
"""

import os
import sys
import threading
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    from cricket_renderer import CricketRenderer  # noqa: E402
    import manager as m  # noqa: E402
except ImportError as exc:
    print(f"SKIP: {exc}")
    sys.exit(2)

results = []


def check(case, passed, detail=""):
    results.append((case, passed))
    print(f"  [{'pass' if passed else 'FAIL'}] {case}" + (f"  <- {detail}" if detail and not passed else ""))


start = datetime(2026, 9, 28, 1, 30, tzinfo=timezone.utc)
r = CricketRenderer(128, 32, {}, tz=ZoneInfo("America/New_York"))
check("a 01:30 UTC start reads 21:30 the evening before in New York",
      r._format_datetime(start) == "Sep 27 21:30", r._format_datetime(start))
r = CricketRenderer(128, 32, {}, tz=ZoneInfo("Asia/Kolkata"))
check("and 07:00 the same morning in Mumbai",
      r._format_datetime(start) == "Sep 28 07:00", r._format_datetime(start))

p = object.__new__(m.CricketPlugin if hasattr(m, "CricketPlugin")
                   else next(o for o in vars(m).values() if isinstance(o, type)
                             and hasattr(o, "get_cycle_duration")))
p._lock = threading.Lock()
p.config = {}
p.display_duration = 15.0
p.mode_enabled = {m.MODE_LIVE: True, m.MODE_RECENT: True, m.MODE_UPCOMING: True}
p.live_matches = []
p.recent_matches = [{"id": i} for i in range(4)]
p.upcoming_matches = [{"id": 9}]
p._per_item_duration = lambda mode, match: 10.0
p._last_display_mode = m.MODE_UPCOMING
check("after Upcoming is drawn, its slot is timed by its own matches",
      p.get_display_duration() == 10.0, p.get_display_duration())
p._last_display_mode = m.MODE_RECENT
check("and Recent by its own", p.get_display_duration() == 40.0, p.get_display_duration())
p.config = {"mode_durations": {"upcoming_mode_duration": 25}}
p._last_display_mode = m.MODE_UPCOMING
check("mode_durations applies to the mode it names", p.get_display_duration() == 25.0,
      p.get_display_duration())

print()
failed = [c for c, ok in results if not ok]
print(f"{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
