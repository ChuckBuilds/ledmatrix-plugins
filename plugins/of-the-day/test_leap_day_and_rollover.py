#!/usr/bin/env python3
"""
Regression tests: the last day of a leap year has an entry, and a new day
is picked up on the first update after midnight.

1. Entries are keyed by day of year, and the bundled files run 1-365. On 31
   December of a leap year (day 366, next in 2028) nothing matched and the
   panel showed "No Data" all day. That day now takes day 365's entry when
   the file has none of its own.
2. update() had its own update_interval gate on top of the core's schedule,
   so the new day could wait up to two intervals after midnight.

Run: LEDMATRIX_CORE=/path/to/LEDMatrix python plugins/of-the-day/test_leap_day_and_rollover.py
Exit 0 pass, 1 fail, 2 skip.
"""

import logging
import os
import sys
import time
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    from manager import OfTheDayPlugin  # noqa: E402
except ImportError as exc:
    print(f"SKIP: {exc}")
    sys.exit(2)

results = []


def check(case, passed, detail=""):
    results.append((case, passed))
    print(f"  [{'pass' if passed else 'FAIL'}] {case}" + (f"  <- {detail}" if detail and not passed else ""))


def plugin(today, data):
    p = object.__new__(OfTheDayPlugin)
    p.logger = logging.getLogger("test-of-the-day")
    p.data_files = {"word_of_the_day": data}
    p.current_day, p.current_items = None, {}
    p._today = lambda: today
    return p


p = plugin(date(2028, 12, 31), {"365": {"word": "valediction"}})
p._load_todays_items()
check("31 Dec 2028 (day 366) shows day 365's entry",
      p.current_items.get("word_of_the_day", {}).get("word") == "valediction", p.current_items)
p = plugin(date(2028, 12, 31), {"365": {"word": "a"}, "366": {"word": "leap"}})
p._load_todays_items()
check("a file that has a day-366 entry still gets it",
      p.current_items["word_of_the_day"]["word"] == "leap")

p = plugin(date(2026, 9, 28), {"271": {"word": "today"}})
p.update_interval = 3600
p.last_update = time.time()          # an update() ran moments ago
p.current_day = date(2026, 9, 27)    # ...yesterday
p.update()
check("the first update after midnight loads the new day",
      p.current_day == date(2026, 9, 28) and p.current_items, p.current_day)

print()
failed = [c for c, ok in results if not ok]
print(f"{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
