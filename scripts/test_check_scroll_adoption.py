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

    print()
    if failures:
        print(f"{len(failures)} failure(s):", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print(f"All {len(CASES) + 1} cases passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
