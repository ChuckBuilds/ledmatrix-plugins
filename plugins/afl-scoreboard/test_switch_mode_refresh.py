"""Switch mode refreshes its managers before it draws them.

baseball, basketball, football, hockey and lacrosse call
_ensure_manager_updated() unconditionally in _try_manager_display(). afl, nrl
and soccer had no equivalent -- their switch path went straight to
manager.display(), so it showed whatever the last background plugin.update()
left behind. Measured before the fix: with no background update at all, afl's
switch mode made zero draw-time refreshes and the panel stayed frozen for ten
simulated minutes, while baseball's picked the score up in thirty seconds.

It is invisible at the 60s default and an hour stale for anyone who raises
update_interval -- and unlike baseball/football, these three declare no
update_interval in their manifest, so the config value is what applies.

Run: PYTHONPATH=<core> <core-venv>/bin/python plugins/afl-scoreboard/test_switch_mode_refresh.py
"""

import ast
import os
import sys
import time

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

from manager import AflScoreboardPlugin as Plugin

FAILURES = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILURES.append(label)


_MISSING = object()


class _Manager:
    def __init__(self, name="m"):
        self.name = name


class _Base:
    _refresh_switch_mode_managers = Plugin._refresh_switch_mode_managers
    _dispatch_switch_refresh = Plugin._dispatch_switch_refresh
    _SWITCH_REFRESH_MIN_GAP_SECONDS = Plugin._SWITCH_REFRESH_MIN_GAP_SECONDS

    def _settle(self):
        """Wait for the dispatched refreshes -- they run on daemon threads."""
        for thread in list(getattr(self, "_switch_refresh_threads", {}).values()):
            thread.join(timeout=5)

    def __init__(self):
        self.refreshed = []
        self.logger = type("L", (), {"info": lambda *a, **k: None,
                                     "debug": lambda *a, **k: None})()

    def _ensure_manager_updated(self, manager):
        self.refreshed.append(manager)


class _Stub(_Base):
    """The afl/nrl shape: one manager per mode."""

    def __init__(self, manager=_MISSING):
        super().__init__()
        self._mgr = _Manager() if manager is _MISSING else manager

    def _get_manager(self, mode_type):
        return self._mgr


print("the switch path refreshes before it reads")
s = _Stub()
s._refresh_switch_mode_managers("live")
s._settle()
check("refreshes the mode's manager", len(s.refreshed) == 1, f"{len(s.refreshed)}")

s = _Stub(manager=None)
try:
    s._refresh_switch_mode_managers("live")
    check("no manager is survivable", len(s.refreshed) == 0)
except Exception as exc:
    check("no manager is survivable", False, str(exc))


class _Angry(_Stub):
    def _get_manager(self, mode_type):
        raise OSError("registry on fire")


try:
    _Angry()._refresh_switch_mode_managers("live")
    check("a manager lookup that raises does not take down the frame", True)
except Exception as exc:
    check("a manager lookup that raises does not take down the frame", False, str(exc))

print("\nthe refresh never runs on the render thread")
PER_CALL = 1


class _Slow(_Stub):
    def _ensure_manager_updated(self, manager):
        time.sleep(0.5)
        self.refreshed.append(manager)


s = _Slow()
_started = time.monotonic()
s._refresh_switch_mode_managers("live")
_elapsed = time.monotonic() - _started
check("returns before a slow update finishes", _elapsed < 0.2, f"{_elapsed:.3f}s")
check("the update is still running in the background", not s.refreshed)
s._SWITCH_REFRESH_MIN_GAP_SECONDS = 0
s._refresh_switch_mode_managers("live")
s._settle()
check("a manager already refreshing is not started twice",
      len(s.refreshed) == PER_CALL, f"{len(s.refreshed)}")

s = _Stub()
s._refresh_switch_mode_managers("live")
s._settle()
s._refresh_switch_mode_managers("live")
s._settle()
check("dispatches inside the gap are skipped", len(s.refreshed) == PER_CALL,
      f"{len(s.refreshed)}")
s._switch_refresh_at = {k: v - 60 for k, v in getattr(s, "_switch_refresh_at", {}).items()}
s._refresh_switch_mode_managers("live")
s._settle()
check("the next dispatch after the gap refreshes again",
      len(s.refreshed) == 2 * PER_CALL, f"{len(s.refreshed)}")

CALLERS = ["_display_switch_mode"]


# The call has to actually be wired into the switch path. Dropping it leaves
# every behavioural check above passing while the panel silently goes stale,
# which is exactly how this survived in three plugins.
with open(os.path.join(PLUGIN_DIR, "manager.py")) as _fh:
    _src = _fh.read()
_tree = ast.parse(_src)
_found = {}
for _node in ast.walk(_tree):
    if not isinstance(_node, ast.FunctionDef) or _node.name not in CALLERS:
        continue
    _found[_node.name] = any(
        isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
        and c.func.attr == "_refresh_switch_mode_managers"
        for c in ast.walk(_node))
_missing = [n for n in CALLERS if not _found.get(n)]
check("the switch path calls the refresh", not _missing,
      f"wired: {sorted(k for k, v in _found.items() if v)}"
      + (f"; MISSING: {_missing}" if _missing else ""))

# The check above asserts the function CONTAINS a refresh, which is not enough:
# soccer gathers switch-mode managers in three separate places, and an early
# version of this fix guarded only one of them. display() still contained a
# call, so this test passed while the per-league display modes -- the ones the
# core actually registers -- refreshed nothing. So pin every gathering site.
_sites, _unguarded = 0, []
for _node in ast.walk(_tree):
    _body = getattr(_node, "body", None)
    if not isinstance(_body, list):
        continue
    for _i, _stmt in enumerate(_body):
        if not (isinstance(_stmt, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "managers_to_try"
                        for t in _stmt.targets)
                and isinstance(_stmt.value, ast.List) and not _stmt.value.elts):
            continue
        _sites += 1
        _prev = _body[_i - 1] if _i else None
        guarded = (isinstance(_prev, ast.Expr) and isinstance(_prev.value, ast.Call)
                   and isinstance(_prev.value.func, ast.Attribute)
                   and _prev.value.func.attr == "_refresh_switch_mode_managers")
        if not guarded:
            _unguarded.append(_stmt.lineno)
check("every switch-mode manager gathering site refreshes first",
      not _unguarded,
      f"{_sites} site(s)" + (f"; UNGUARDED at {_unguarded}" if _unguarded else ""))

# And the refresh path must hand the update to a thread, never call it inline:
# an inline manager.update() blocks the frame for a whole network round trip.
_inline = []
for _node in ast.walk(_tree):
    if isinstance(_node, ast.FunctionDef) and _node.name == "_refresh_switch_mode_managers":
        _inline = [c.func.attr for c in ast.walk(_node)
                   if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                   and c.func.attr in ("_ensure_manager_updated", "update")]
check("the refresh path never updates a manager inline", not _inline,
      f"inline calls: {_inline}" if _inline else "")

print("\n" + "=" * 62)
if FAILURES:
    print(f"{len(FAILURES)} check(s) failed: {FAILURES}")
    sys.exit(1)
print("All checks passed.")
