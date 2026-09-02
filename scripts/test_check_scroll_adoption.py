#!/usr/bin/env python3
"""Regression tests for the scroll-adoption gate.

The gate exists because three plugins shipped `scroll_display.py` as the
pre-adoption and adopted files concatenated, leaving a second copy of the
fallback classes nobody referenced. That dead block is where the missing
separator-icon constants were hiding, which is why the file read as correct to
both a reviewer and to a checker that only asked whether a name was defined
*somewhere*.

So these pin the two ways the gate could quietly stop working:

- **Scope, not nesting depth.** A `Legacy*` class inside a module-level
  `if`/`try`/`with`/loop still binds a module global. The guarded import in
  these very files is an `if/else`, so the likeliest hiding place is inside a
  block — checking only `tree.body` would miss exactly the case that matters.
  Classes nested in a function or another class are *not* module globals and
  must stay allowed, as must the fallback branch's legitimate *import* of the
  Legacy names.
- **A file that cannot be parsed is not a file that passed.** Swallowing
  `SyntaxError` and returning no findings would let a malformed
  `scroll_display.py` skip the check and exit 0.

`sunset_violations` gets its own table, because it takes a DIRECTORY rather
than a file and asks the opposite question: not "is the fallback inlined" but
"is the fallback gone". Its most important case is the negative one -- an
unrelated `try/except` must not read as the guard returning. These files carry
two of those already (ScrollHelper, the Pillow resample constant) and
basketball has three, so a check that fired on any try/except would fail every
sunset plugin the day it landed.

Exit codes follow the convention in `run_plugin_tests.py`: 0 pass, 1 fail.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_scroll_adoption as gate  # noqa: E402

GUARDED_IMPORT = (
    "try:\n"
    "    from src.common.sports_scroll import ScrollDisplay\n"
    "except ImportError:\n"
    "    class LegacyScrollDisplay:\n        pass\n"
)

# name -> (source, expected offending class names)
CASES = {
    "module level": (
        "class LegacyScrollDisplay:\n    pass\n",
        ["LegacyScrollDisplay"],
    ),
    "inside the guarded import's except branch": (
        GUARDED_IMPORT,
        ["LegacyScrollDisplay"],
    ),
    "inside an if body": (
        "if True:\n    class LegacyScrollDisplayManager:\n        pass\n",
        ["LegacyScrollDisplayManager"],
    ),
    "inside an else branch": (
        "if False:\n    pass\nelse:\n    class LegacyScrollDisplay:\n        pass\n",
        ["LegacyScrollDisplay"],
    ),
    "inside a loop": (
        "for _ in range(1):\n    class LegacyThing:\n        pass\n",
        ["LegacyThing"],
    ),
    "inside a with block": (
        "with open(__file__) as fh:\n    class LegacyThing:\n        pass\n",
        ["LegacyThing"],
    ),
    "two in one file, reported sorted": (
        "class LegacyScrollDisplayManager:\n    pass\n"
        "class LegacyScrollDisplay:\n    pass\n",
        ["LegacyScrollDisplay", "LegacyScrollDisplayManager"],
    ),
    # Allowed: not module globals, or not definitions at all.
    "nested in a function": (
        "def make():\n"
        "    class LegacyScrollDisplay:\n        pass\n"
        "    return LegacyScrollDisplay\n",
        [],
    ),
    "nested in a class": (
        "class Outer:\n    class LegacyInner:\n        pass\n",
        [],
    ),
    "imported, not defined": (
        "from scroll_display_legacy import LegacyScrollDisplay\n",
        [],
    ),
    "adopted file's own non-Legacy classes": (
        "class ScrollDisplay:\n    pass\n\nclass ScrollDisplayManager:\n    pass\n",
        [],
    ),
}


CORE_IMPORT = "from src.common.sports_scroll import SportsScrollDisplay\n"

# name -> (scroll_display.py source, bundled copy present, expected problems)
SUNSET_CASES = {
    "collapsed and unguarded": (
        CORE_IMPORT + "class ScrollDisplay(SportsScrollDisplay):\n    pass\n",
        False, 0),
    "the guard came back": (
        "try:\n"
        "    from src.common.sports_scroll import SportsScrollDisplay\n"
        "except ModuleNotFoundError:\n"
        "    SportsScrollDisplay = None\n",
        False, 2),           # guarded, and no top-level import
    "the bundled copy came back": (
        CORE_IMPORT, True, 1),
    "the import moved into an if": (
        "if True:\n"
        "    from src.common.sports_scroll import SportsScrollDisplay\n",
        False, 1),
    # The negative case, and the one most likely to be got wrong: these files
    # legitimately guard OTHER imports.
    "an unrelated try/except is fine": (
        "try:\n    import ujson as json\nexcept ImportError:\n    import json\n"
        + CORE_IMPORT,
        False, 0),
}


def check_sunset_cases() -> list[str]:
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        plugin_dir = Path(tmp)
        scroll = plugin_dir / "scroll_display.py"
        legacy = plugin_dir / "scroll_display_legacy.py"
        for name, (source, has_copy, expected) in SUNSET_CASES.items():
            scroll.write_text(source, encoding="utf-8")
            if has_copy:
                legacy.write_text("class LegacyScrollDisplay:\n    pass\n",
                                  encoding="utf-8")
            elif legacy.exists():
                legacy.unlink()
            actual = gate.sunset_violations(plugin_dir)
            if len(actual) == expected:
                print(f"  ok   sunset: {name}")
            else:
                print(f"  FAIL sunset: {name}: expected {expected} problem(s), "
                      f"got {len(actual)}: {actual}")
                failures.append(f"sunset {name}: expected {expected}, got {actual}")
    return failures


def main() -> int:
    failures: list[str] = []

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "scroll_display.py"

        for name, (source, expected) in CASES.items():
            path.write_text(source, encoding="utf-8")
            actual = gate.offending_classes(path)
            if actual == expected:
                print(f"  ok   {name}")
            else:
                print(f"  FAIL {name}: expected {expected}, got {actual}")
                failures.append(f"{name}: expected {expected}, got {actual}")

        path.write_text("class Legacy(:\n", encoding="utf-8")
        try:
            actual = gate.offending_classes(path)
        except SyntaxError:
            print("  ok   malformed file raises instead of reporting clean")
        else:
            print(f"  FAIL malformed file returned {actual} instead of raising")
            failures.append(f"malformed file returned {actual} instead of raising")

        failures.extend(check_sunset_cases())

    print()
    if failures:
        print(f"{len(failures)} failure(s):", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print(f"All {len(CASES) + len(SUNSET_CASES) + 1} cases passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
