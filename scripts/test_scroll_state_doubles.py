#!/usr/bin/env python3
"""A display-manager double must accept every argument the plugins pass it.

`DisplayManager.set_scrolling_state` gained a `frame_hold` argument, and the
plugins that pace their scroll now pass it. A test double still declaring
`set_scrolling_state(self, state)` raises TypeError the moment display() runs,
so the test fails for a reason that has nothing to do with what it asserts --
and the traceback is swallowed by the plugin's own `except Exception` in
display(), leaving only a bare "no frame reached the display".

Three doubles in this repo were behind at once (odds-ticker, news,
ledmatrix-elections) and CI caught exactly one of them, because the other two
never reach the scrolling branch. That is why this is a check and not a
convention.

Run: python scripts/test_scroll_state_doubles.py
"""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def accepts_frame_hold(fn: ast.FunctionDef) -> bool:
    """True if this def can take frame_hold, positionally or by keyword."""
    named = [a.arg for a in fn.args.args] + [a.arg for a in fn.args.kwonlyargs]
    if "frame_hold" in named:
        return True
    if fn.args.kwarg is not None:      # **kwargs absorbs it
        return True
    # *args alone does NOT: the call passes frame_hold as a keyword.
    return False


def check(path: Path) -> list:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return []
    bad = []
    for node in ast.walk(tree):
        if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "set_scrolling_state"
                and not accepts_frame_hold(node)):
            bad.append((node.lineno, ast.unparse(node.args)))
    return bad


def main() -> int:
    files = sorted(ROOT.glob("plugins/**/*.py")) + sorted(ROOT.glob("scripts/*.py"))
    failures = []
    for path in files:
        for lineno, sig in check(path):
            failures.append(f"{path.relative_to(ROOT)}:{lineno}: set_scrolling_state({sig})")

    if failures:
        print("A set_scrolling_state double cannot accept frame_hold.")
        print("Plugins pass it as a keyword, so these raise TypeError at render time:\n")
        for f in failures:
            print(f"  {f}")
        print("\nAdd `frame_hold=1` to the signature (or accept **kwargs).")
        return 1

    print(f"OK: every set_scrolling_state double accepts frame_hold "
          f"({len(files)} files checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
