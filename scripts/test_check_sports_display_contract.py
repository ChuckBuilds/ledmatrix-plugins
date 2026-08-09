#!/usr/bin/env python3
"""Regression tests for the sports display()-contract gate.

The gate exists because hockey-scoreboard and lacrosse-scoreboard shipped a
stale fork of sports.py whose display() methods returned None. The dispatcher
treats a non-bool as success, so an empty mode reported content, was never
skipped, and held a blank panel for its whole display duration. It was wrong
from the February monorepo migration and only surfaced in August, when the NHL
offseason made "no games" persistent for the first time.

So these pin the ways the gate could quietly stop working:

- **The fall-off-the-end path.** The original bug's worst case had no `return`
  statement at all on the offending path. A checker that only inspects `return`
  nodes sees nothing wrong and passes the exact file it was written for.
- **Truthiness is not the contract.** The dispatcher branches on `result is
  True` / `result is False`, so `return 1` lands in the same "assume success"
  arm as `return None`. Accepting anything but the literals reintroduces the
  bug in a new type.
- **Delegation must stay allowed.** Four plugins' live mode is
  `return super().display(...)`, whose parent this gate has already checked.
  Flagging that would make the gate unusable and invite its removal.
- **A file that cannot be parsed is not a file that passed.** Swallowing
  SyntaxError and reporting no findings would let a malformed sports.py skip
  the check and exit 0.

Exit codes follow the convention in the sibling gate tests: 0 pass, 1 fail.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_sports_display_contract import _check_plugin  # noqa: E402


def _wrap(body: str, cls: str = "SportsRecent") -> str:
    return "class %s:\n    def display(self, force_clear=False):\n%s\n" % (
        cls, body)


CLEAN = [
    ("returns on both paths", _wrap(
        "        if not self.games_list:\n"
        "            return False\n"
        "        return True")),
    ("try/except with returns everywhere", _wrap(
        "        try:\n"
        "            return True\n"
        "        except Exception:\n"
        "            return False")),
    ("delegates to super", _wrap(
        "        return super().display(force_clear)", cls="SportsLive")),
    ("raises instead of returning", _wrap(
        "        if not self.ok:\n"
        "            raise RuntimeError('x')\n"
        "        return True")),
    ("a class the gate does not police is ignored", _wrap(
        "        return", cls="SomeOtherHelper")),
]

DIRTY = [
    # The shape that actually shipped.
    ("bare return", _wrap(
        "        if not self.games_list:\n"
        "            return\n"
        "        return True"), "bare `return`"),
    ("falls off the end", _wrap(
        "        if self.games_list:\n"
        "            return True"), "fall off the end"),
    ("no return at all", _wrap(
        "        self._draw()"), "fall off the end"),
    ("truthy non-bool", _wrap(
        "        return 1"), "not a bool literal"),
    ("returns a variable", _wrap(
        "        result = self._draw()\n"
        "        return result"), "not a bool literal"),
    # An `if` with no `else` falls through even when both its arms return.
    ("if without else", _wrap(
        "        if a:\n"
        "            return True\n"
        "        elif b:\n"
        "            return False"), "fall off the end"),
    # try/except where the handler falls through.
    ("handler falls through", _wrap(
        "        try:\n"
        "            return True\n"
        "        except Exception:\n"
        "            self.logger.error('x')"), "fall off the end"),
]

failures = []


def check(name, cond, detail=""):
    if cond:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s%s" % (name, (": " + detail) if detail else ""))
        failures.append(name)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "sports.py"

        print("valid shapes pass")
        for name, source in CLEAN:
            path.write_text(source, encoding="utf-8")
            problems, reason = _check_plugin(path)
            check(name, not problems and reason is None,
                  "reported %r" % (problems or reason,))

        print("\nbroken shapes are caught")
        for name, source, expected in DIRTY:
            path.write_text(source, encoding="utf-8")
            problems, reason = _check_plugin(path)
            check(name, bool(problems), "reported nothing")
            check("  %s names the reason" % name,
                  any(expected in p for p in problems),
                  "expected %r in %r" % (expected, problems))

        print("\nan unparseable file fails rather than passing silently")
        path.write_text("class SportsRecent(:\n", encoding="utf-8")
        problems, reason = _check_plugin(path)
        check("syntax error is reported", reason is not None,
              "returned %r" % (reason,))
        check("and is not mistaken for a clean file", not problems)

    print("\n%s" % ("FAILED: %d" % len(failures) if failures
                    else "All checks passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
