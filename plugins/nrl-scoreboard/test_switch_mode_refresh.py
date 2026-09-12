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

Run: PYTHONPATH=<core> <core-venv>/bin/python plugins/nrl-scoreboard/test_switch_mode_refresh.py
"""

import ast
import os
import sys

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

from manager import NrlScoreboardPlugin as Plugin

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
check("refreshes the mode's manager", len(s.refreshed) == 1, f"{len(s.refreshed)}")

s = _Stub(manager=None)
try:
    s._refresh_switch_mode_managers("live")
    check("no manager is survivable", len(s.refreshed) == 0)
except Exception as exc:
    check("no manager is survivable", False, str(exc))


class _Angry(_Stub):
    def _ensure_manager_updated(self, manager):
        raise OSError("network on fire")


try:
    _Angry()._refresh_switch_mode_managers("live")
    check("a manager that raises does not take down the frame", True)
except Exception as exc:
    check("a manager that raises does not take down the frame", False, str(exc))

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

print("\n" + "=" * 62)
if FAILURES:
    print(f"{len(FAILURES)} check(s) failed: {FAILURES}")
    sys.exit(1)
print("All checks passed.")
