#!/usr/bin/env python3
"""Composing the map must not write debug PNGs unless debug logging is on.

_get_map_background() saved two images on every composite, ungated -- no debug
flag, no config check, and the comment above it read "Debug: Save composite
image to see what's happening". Left-over debugging shipped as production
behaviour.

Measured on a live rig: debug_composite.png is 5.36 MB and debug_cropped.png
0.04 MB, with five composites in six hours. That is roughly 108 MB a day
written to an SD card for files nothing reads, on a device whose cards have
already failed twice. Honouring the ticker's narrower render request makes the
plugin compose at two widths rather than one, so the count roughly doubles.

They also landed in the process's working directory -- the install root --
where a pre-commit hook has previously swept them into a commit.

Run: <core-venv>/bin/python plugins/ledmatrix-flights/test_no_debug_image_writes.py
"""

import ast
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent
MANAGER = PLUGIN / "manager.py"
failures = []


def check(label, ok):
    print(("  PASS  " if ok else "  FAIL  ") + label)
    if not ok:
        failures.append(label)


def _save_calls(tree):
    """Every `<something>.save(...)` in the module, with its line number."""
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and getattr(n.func, "attr", None) == "save"]


def _guarding_debug_check(tree, lineno):
    """True when the statement at `lineno` sits under an isEnabledFor guard."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = ast.dump(node.test)
        if "isEnabledFor" not in test:
            continue
        for child in ast.walk(node):
            if getattr(child, "lineno", None) == lineno:
                return True
    return False


def main():
    tree = ast.parse(MANAGER.read_text(encoding="utf-8"))

    print("debug images are written only when debug logging is enabled")
    saves = _save_calls(tree)
    check(f"{len(saves)} save() call(s) found in manager.py", bool(saves))
    for call in saves:
        guarded = _guarding_debug_check(tree, call.lineno)
        check(f"the save at line {call.lineno} is behind a debug-level guard",
              guarded)

    print("\nand not into the process working directory")
    source = MANAGER.read_text(encoding="utf-8")
    check('no bare Path("debug_composite.png")',
          'Path("debug_composite.png")' not in source)
    check('no bare Path("debug_cropped.png")',
          'Path("debug_cropped.png")' not in source)
    check("debug images go under the tile cache directory",
          "tile_cache_dir" in source.split("debug_composite.png")[0][-600:])

    print("\n%s" % ("FAILED: %d" % len(failures) if failures
                    else "All checks passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
