#!/usr/bin/env python3
"""Switch mode refreshes its managers without blocking the render thread.

_try_manager_display() ran _ensure_manager_updated(manager) inline before
drawing. When the manager's interval was due that is a network round trip --
rankings and the schedule, with 10-30s timeouts -- on the thread that draws the
panel, so during live games the display froze for the length of each ESPN
request roughly once per live interval. afl, nrl and soccer moved their switch
refresh to a worker in #483; this plugin kept the inline call.

The refresh is now handed to _dispatch_switch_refresh() -- the same function
afl/nrl/soccer carry: at most one refresh per manager at a time, dispatches for
a manager at least _SWITCH_REFRESH_MIN_GAP_SECONDS apart, and the manager's own
interval still decides whether anything is fetched.

Run: <core-venv>/bin/python plugins/football-scoreboard/test_switch_refresh_off_render_thread.py
"""

import ast
import os
import sys
import time
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))
_core = os.environ.get("LEDMATRIX_CORE", "")
for _candidate in (_core, str(PLUGIN_DIR.parents[2] / "LEDMatrix")):
    if _candidate and (Path(_candidate) / "src" / "plugin_system").is_dir():
        sys.path.insert(0, _candidate)
        break

try:
    from manager import FootballScoreboardPlugin as Plugin  # noqa: E402
except ImportError as exc:
    print(f"SKIP: cannot import the plugin without a LEDMatrix core ({exc})")
    sys.exit(2)

FAILURES = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILURES.append(label)


class _Manager:
    pass


class _Stub:
    _dispatch_switch_refresh = Plugin._dispatch_switch_refresh
    _SWITCH_REFRESH_MIN_GAP_SECONDS = Plugin._SWITCH_REFRESH_MIN_GAP_SECONDS

    def __init__(self, delay=0.0):
        self.delay = delay
        self.refreshed = []

    def _ensure_manager_updated(self, manager):
        if self.delay:
            time.sleep(self.delay)
        self.refreshed.append(manager)

    def _settle(self):
        for thread in list(getattr(self, "_switch_refresh_threads", {}).values()):
            thread.join(timeout=5)


print("the refresh runs on a worker, not the render thread")
s = _Stub(delay=0.5)
m = _Manager()
_started = time.monotonic()
s._dispatch_switch_refresh(m)
_elapsed = time.monotonic() - _started
check("returns before a slow update finishes", _elapsed < 0.2, f"{_elapsed:.3f}s")
check("the update is still running in the background", not s.refreshed)
s._SWITCH_REFRESH_MIN_GAP_SECONDS = 0
s._dispatch_switch_refresh(m)
s._settle()
check("a manager already refreshing is not started twice", len(s.refreshed) == 1,
      f"{len(s.refreshed)}")

s = _Stub()
s._dispatch_switch_refresh(m)
s._settle()
s._dispatch_switch_refresh(m)
s._settle()
check("dispatches inside the gap are skipped", len(s.refreshed) == 1, f"{len(s.refreshed)}")
s._switch_refresh_at = {k: v - 60 for k, v in s._switch_refresh_at.items()}
s._dispatch_switch_refresh(m)
s._settle()
check("the next dispatch after the gap refreshes again", len(s.refreshed) == 2,
      f"{len(s.refreshed)}")
other = _Manager()
s._dispatch_switch_refresh(other)
s._settle()
check("the gap is per manager", s.refreshed[-1] is other, f"{len(s.refreshed)}")

print("\nthe switch path is wired to the dispatch")
# Behaviour alone cannot catch this: put the inline call back and every check
# above still passes while the panel freezes on each due fetch.
with open(PLUGIN_DIR / "manager.py", encoding="utf-8") as _fh:
    _tree = ast.parse(_fh.read())

_SWITCH_PATHS = ("_try_manager_display", "_display_internal_cycling")
_seen, _dispatching, _inline = [], [], []
for _node in ast.walk(_tree):
    if not isinstance(_node, ast.FunctionDef) or _node.name not in _SWITCH_PATHS:
        continue
    _seen.append(_node.name)
    _calls = [c.func.attr for c in ast.walk(_node)
              if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)]
    if "_dispatch_switch_refresh" in _calls:
        _dispatching.append(_node.name)
    _inline += [f"{_node.name}: {a}" for a in _calls
                if a in ("_ensure_manager_updated", "update")]

check("the switch path exists", "_try_manager_display" in _seen, f"{_seen}")
check("_try_manager_display() dispatches the refresh",
      "_try_manager_display" in _dispatching, f"dispatching: {_dispatching}")
check("no switch path updates a manager inline", not _inline,
      f"inline calls: {_inline}" if _inline else "")

print("\n" + "=" * 62)
if FAILURES:
    print(f"{len(FAILURES)} check(s) failed: {FAILURES}")
    sys.exit(1)
print("All checks passed.")
