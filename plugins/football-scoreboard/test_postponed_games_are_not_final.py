#!/usr/bin/env python3
"""A postponed, cancelled or suspended game is not a final.

ESPN reports STATUS_POSTPONED with state "post" and a 0-0 score, and the
extractor set is_final from the state alone, so a postponement reached Recent
as "Final 0-0". is_final now also needs the game completed and not in one of
the never-played statuses.

Run: <core-venv>/bin/python plugins/football-scoreboard/test_postponed_games_are_not_final.py
"""
import inspect
import sys
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

try:
    import sports  # noqa: E402
except ImportError as exc:
    print("SKIP: cannot import sports.py (%s)" % exc)
    sys.exit(2)


def _status(state, name, completed=None):
    stype = {"state": state, "name": name}
    if completed is not None:
        stype["completed"] = completed
    return {"type": stype}


CASES = [
    ("finished game", _status("post", "STATUS_FINAL", True), True),
    ("final, feed without a completed flag", _status("post", "STATUS_FINAL"), True),
    ("postponed", _status("post", "STATUS_POSTPONED", False), False),
    ("postponed, completed flag missing", _status("post", "STATUS_POSTPONED"), False),
    ("cancelled", _status("post", "STATUS_CANCELED", False), False),
    ("suspended", _status("post", "STATUS_SUSPENDED", False), False),
    ("post but not completed", _status("post", "STATUS_FINAL", False), False),
    ("in progress", _status("in", "STATUS_IN_PROGRESS", False), False),
    ("no status at all", None, False),
]


def main():
    fn = getattr(sports, "_status_is_final", None)
    if fn is None:
        print("  [FAIL] sports._status_is_final does not exist")
        return 1
    failures = 0
    for name, status, want in CASES:
        got = fn(status)
        ok = got is want
        failures += not ok
        print("  [%s] %s -> %r" % ("pass" if ok else "FAIL", name, got))

    # The extractor has to use it, or the helper protects nothing.
    src = inspect.getsource(sports)
    wired = '"is_final": _status_is_final(status)' in src
    failures += not wired
    print("  [%s] the extractor sets is_final through the helper"
          % ("pass" if wired else "FAIL"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
