#!/usr/bin/env python3
"""A plugin's `scroll_display.py` must not define the fallback implementation.

Plugins that adopted the core scroll orchestration keep two implementations:

    scroll_display.py         prefers the core's src.common.sports_scroll, and
                              falls back to the module below on an older core
    scroll_display_legacy.py  the frozen previous implementation

Three plugins ended up as those two files CONCATENATED rather than one
replacing the other, so `scroll_display.py` also carried a full copy of the
legacy classes at module level. Nothing referenced them -- the fallback branch
imports the real ones from `scroll_display_legacy` -- so they were invisible
dead weight, ~2,000 lines of it.

That is not just untidy. The separator-icon constants whose absence broke
scroll mode on a 3.2.0 core were sitting in that dead block, which is why the
file read as correct both to a reviewer and to an AST checker that only asked
whether the names were defined *somewhere* in the module. Keeping the file down
to one implementation is what makes the next such miss visible.

Run: python scripts/check_scroll_adoption.py [plugin-id ...]
Exit code 0 when clean, 1 when a plugin inlines a legacy class.
"""

import ast
import sys
from pathlib import Path

PLUGINS_DIR = Path(__file__).resolve().parent.parent / "plugins"


def offending_classes(path: Path) -> list[str]:
    """Module-level classes named Legacy* — the ones that do not belong here.

    Only module level: the adopted file legitimately defines `ScrollDisplay`
    and `ScrollDisplayManager` inside the `else:` branch of the guarded import,
    and the fallback branch legitimately *imports* the Legacy names. Defining
    them here is what signals the duplicate.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:  # pragma: no cover - a broken file fails elsewhere
        print(f"  {path}: could not parse ({exc})")
        return []
    return [n.name for n in tree.body
            if isinstance(n, ast.ClassDef) and n.name.startswith("Legacy")]


def main(argv: list[str]) -> int:
    ids = argv or sorted(p.name for p in PLUGINS_DIR.iterdir() if p.is_dir())

    checked = 0
    problems: list[tuple[str, list[str]]] = []
    for pid in ids:
        scroll = PLUGINS_DIR / pid / "scroll_display.py"
        if not scroll.exists():
            continue
        checked += 1
        found = offending_classes(scroll)
        if found:
            problems.append((pid, found))

    for pid, names in problems:
        print(f"::error::{pid}/scroll_display.py defines {', '.join(names)} at "
              f"module level. The fallback implementation belongs in "
              f"scroll_display_legacy.py; this file should only prefer the core "
              f"module and fall back to it.")

    if problems:
        print(f"\nFAIL: {len(problems)} of {checked} plugin(s) inline a legacy "
              f"scroll implementation.")
        return 1

    print(f"OK: {checked} plugin(s) with a scroll_display.py, none inlining a "
          f"legacy implementation.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
