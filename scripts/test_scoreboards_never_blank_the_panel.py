#!/usr/bin/env python3
"""The scoreboards never blank the panel themselves.

WHY THIS EXISTS
---------------
``display_manager.clear()`` does not just reset the drawing buffer: it calls
``Clear()`` on both canvases and on the matrix, so the physical panel goes
black at once. Every scoreboard called it before drawing a card whenever
``force_clear`` was set, and then spent a frame or more rendering logos and
text -- long enough for the black to show. With one favourite team the card
that came back was the same one, so the board read as "flashing", as if it
had tried to switch to a second game and found none.

``force_clear`` is set far more often than a card changes: on every mode
change, on every block boundary, and whenever ``_reset_dwell_on_reentry``
sees more than five seconds between display() calls -- which a slow update()
holding the plugin lock produces with the same mode still on screen.

None of those clears was needed:

* Every draw path builds a full-size frame and assigns it to
  ``display_manager.image``, so the new frame replaces the old one whole.
  Without the clear the panel keeps the previous frame until
  ``update_display()`` swaps the finished one in, and the core's dirty-frame
  check skips the push entirely when the pixels are unchanged (``clear()``
  reset that digest, forcing a full push).
* A mode with nothing to show returns False and the controller moves to the
  next mode at once ("Don't clear display when immediately moving to next
  mode - this causes black flashes", display_controller.py). When the whole
  rotation is empty the controller blanks the panel once itself
  (``_note_empty_pass``).

calendar fixed the same flash the same way in #328 (``_fresh_frame``).

WHAT THIS CHECKS
----------------
No function in the nine scoreboards' modules calls ``display_manager.clear()``.
Tests are excluded: they stub the display manager.

    python scripts/test_scoreboards_never_blank_the_panel.py

Exit 0 pass, 1 fail.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SCOREBOARDS = (
    "afl-scoreboard", "baseball-scoreboard", "basketball-scoreboard",
    "football-scoreboard", "hockey-scoreboard", "lacrosse-scoreboard",
    "nrl-scoreboard", "soccer-scoreboard", "ufc-scoreboard",
)


def _clear_calls(path: Path):
    """(line, function) for every ``<...>.display_manager.clear()`` call."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = []

    def visit(node, func):
        for child in ast.iter_child_nodes(node):
            name = func
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = child.name
            if (isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Attribute)
                    and child.func.attr == "clear"
                    and isinstance(child.func.value, ast.Attribute)
                    and child.func.value.attr == "display_manager"):
                found.append((child.lineno, func or "<module>"))
            visit(child, name)

    visit(tree, None)
    return found


def main() -> int:
    failures = []
    checked = 0
    for plugin in SCOREBOARDS:
        plugin_dir = REPO / "plugins" / plugin
        if not plugin_dir.is_dir():
            failures.append(f"{plugin}: plugin directory missing")
            continue
        for path in sorted(plugin_dir.glob("*.py")):
            if path.name.startswith("test_"):
                continue
            checked += 1
            for line, func in _clear_calls(path):
                failures.append(
                    f"{path.relative_to(REPO)}:{line} in {func}() calls "
                    "display_manager.clear(), which blanks the panel before "
                    "the next frame is drawn")
    if failures:
        print("FAIL: scoreboards must not blank the panel themselves")
        for f in failures:
            print("  " + f)
        return 1
    print(f"PASS: none of the {len(SCOREBOARDS)} scoreboards ({checked} modules) "
          "calls display_manager.clear()")
    return 0


if __name__ == "__main__":
    sys.exit(main())
