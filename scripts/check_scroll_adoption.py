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


# Statement types whose bodies still execute in module scope, so a class
# defined inside one is still a module global. `ast.FunctionDef` and
# `ast.ClassDef` are deliberately absent: a Legacy* class nested in either is
# not a module-level binding and is not what this check is looking for.
_MODULE_SCOPE_BLOCKS = (
    ast.If, ast.Try, ast.With, ast.AsyncWith, ast.For, ast.AsyncFor, ast.While,
)
_MATCH = getattr(ast, "Match", None)  # 3.10+


def _module_scope_statements(body: list[ast.stmt]):
    """Yield every statement that executes in module scope, blocks included.

    The guarded import in these files is an `if/else`, so a legacy class
    tucked into either branch — or into a `try` that swallows ImportError —
    binds a module global exactly like a top-level one does.
    """
    for node in body:
        yield node
        if isinstance(node, _MODULE_SCOPE_BLOCKS):
            yield from _module_scope_statements(node.body)
            yield from _module_scope_statements(getattr(node, "orelse", []))
            yield from _module_scope_statements(getattr(node, "finalbody", []))
            for handler in getattr(node, "handlers", []):
                yield from _module_scope_statements(handler.body)
        elif _MATCH is not None and isinstance(node, _MATCH):
            for case in node.cases:
                yield from _module_scope_statements(case.body)


def offending_classes(path: Path) -> list[str]:
    """Module-scope classes named Legacy* — the ones that do not belong here.

    Only module scope: the adopted file legitimately defines `ScrollDisplay`
    and `ScrollDisplayManager` inside the `else:` branch of the guarded import,
    and the fallback branch legitimately *imports* the Legacy names. Defining
    them here is what signals the duplicate.

    Raises SyntaxError/OSError to the caller: a file this check cannot read is
    not a file it can clear.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return sorted(n.name for n in _module_scope_statements(tree.body)
                  if isinstance(n, ast.ClassDef) and n.name.startswith("Legacy"))


def main(argv: list[str]) -> int:
    ids = argv or sorted(p.name for p in PLUGINS_DIR.iterdir() if p.is_dir())

    checked = 0
    problems: list[tuple[str, list[str]]] = []
    unreadable: list[tuple[str, str]] = []
    for pid in ids:
        scroll = PLUGINS_DIR / pid / "scroll_display.py"
        if not scroll.exists():
            continue
        checked += 1
        try:
            found = offending_classes(scroll)
        except (SyntaxError, ValueError, OSError) as exc:
            unreadable.append((pid, str(exc)))
            continue
        if found:
            problems.append((pid, found))

    for pid, names in problems:
        print(f"::error::{pid}/scroll_display.py defines {', '.join(names)} at "
              f"module level. The fallback implementation belongs in "
              f"scroll_display_legacy.py; this file should only prefer the core "
              f"module and fall back to it.")

    for pid, reason in unreadable:
        print(f"::error::{pid}/scroll_display.py could not be parsed ({reason}). "
              f"Treating that as a pass would let a malformed file skip this "
              f"check entirely.")

    if problems or unreadable:
        if problems:
            print(f"\nFAIL: {len(problems)} of {checked} plugin(s) inline a legacy "
                  f"scroll implementation.")
        if unreadable:
            print(f"FAIL: {len(unreadable)} of {checked} plugin(s) could not be parsed.")
        return 1

    print(f"OK: {checked} plugin(s) with a scroll_display.py, none inlining a "
          f"legacy implementation.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
