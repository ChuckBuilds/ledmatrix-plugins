#!/usr/bin/env python3
"""
Regression test: game times follow the board's timezone.

Game dates and tip-off times were always converted to US/Eastern, with no
"ET" on them, whatever timezone LEDMatrix was set to. They now use the
LEDMatrix timezone; US/Eastern is the fallback when none is set.

Run: LEDMATRIX_CORE=/path/to/LEDMatrix python plugins/march-madness/test_display_timezone.py
Exit 0 pass, 1 fail, 2 skip.
"""

import logging
import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    from manager import MarchMadnessPlugin  # noqa: E402
except ImportError as exc:
    print(f"SKIP: {exc}")
    sys.exit(2)

results = []


def check(case, passed, detail=""):
    results.append((case, passed))
    print(f"  [{'pass' if passed else 'FAIL'}] {case}" + (f"  <- {detail}" if detail and not passed else ""))


def plugin(tz_name):
    p = object.__new__(MarchMadnessPlugin)
    p.logger = logging.getLogger("test-mm")
    p.plugin_manager = SimpleNamespace(
        config_manager=SimpleNamespace(get_timezone=lambda: tz_name))
    return p


tip = datetime(2026, 3, 20, 2, 10, tzinfo=timezone.utc)
local = tip.astimezone(plugin("America/Los_Angeles")._display_timezone())
check("a board set to Los Angeles shows 7:10pm the evening before",
      (local.day, local.hour, local.minute) == (19, 19, 10), local)
local = tip.astimezone(plugin(None)._display_timezone())
check("with no timezone set, US/Eastern as before",
      (local.day, local.hour) == (19, 22), local)
local = tip.astimezone(plugin("Not/AZone")._display_timezone())
check("an unknown timezone falls back to US/Eastern", (local.day, local.hour) == (19, 22), local)

print()
failed = [c for c, ok in results if not ok]
print(f"{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
