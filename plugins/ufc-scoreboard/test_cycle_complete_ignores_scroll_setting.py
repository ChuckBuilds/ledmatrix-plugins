#!/usr/bin/env python3
"""is_cycle_complete() must not wait on a scroll this plugin never runs.

The schema offers *_display_mode: "scroll", but ufc's display() always draws
the switch card (there is no display-path scroll renderer). is_cycle_complete
used to ask the scroll helper whether a scroll had finished whenever the mode
was set to "scroll"; nothing was scrolling, so it answered False forever and
the mode held the panel until the dynamic-duration cap.

Run: <core-venv>/bin/python plugins/ufc-scoreboard/test_cycle_complete_ignores_scroll_setting.py
"""

import logging
import os
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))
_core = os.environ.get("LEDMATRIX_CORE", "")
for _candidate in (_core, str(PLUGIN_DIR.parents[2] / "LEDMatrix")):
    if _candidate and (Path(_candidate) / "src" / "plugin_system").is_dir():
        sys.path.insert(0, _candidate)
        break
else:
    print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
    sys.exit(2)

from manager import UFCScoreboardPlugin  # noqa: E402

FAILURES = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILURES.append(label)


class _NeverFinishedScroll:
    calls = 0

    def is_scroll_complete(self):
        _NeverFinishedScroll.calls += 1
        return False


def build(cards_complete):
    obj = UFCScoreboardPlugin.__new__(UFCScoreboardPlugin)
    obj.logger = logging.getLogger("cycle_probe")
    obj.is_enabled = True
    obj.supports_dynamic_duration = lambda: True
    obj._current_active_display_mode = "ufc_upcoming"
    obj._should_use_scroll_mode = lambda mode_type: True   # user chose "scroll"
    obj._scroll_manager = _NeverFinishedScroll()
    obj._dynamic_cycle_complete = False

    def evaluate(display_mode=None):
        obj._dynamic_cycle_complete = cards_complete

    obj._evaluate_dynamic_cycle_completion = evaluate
    return obj


check("every card shown -> complete, despite a 'scroll' setting",
      build(True).is_cycle_complete() is True)
check("cards still to show -> not complete",
      build(False).is_cycle_complete() is False)
check("the idle scroll helper is never consulted",
      _NeverFinishedScroll.calls == 0, f"{_NeverFinishedScroll.calls} calls")

print("\n" + "=" * 60)
if FAILURES:
    print(f"{len(FAILURES)} check(s) failed: {FAILURES}")
    sys.exit(1)
print("All checks passed.")
