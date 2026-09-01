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

A second check covers the opposite direction. The one above asks whether the
fallback has been INLINED; it cannot ask whether the fallback still exists,
because it opens `scroll_display.py` and nothing else. For plugins that have
completed the B6 sunset -- listed in SUNSET_PLUGINS -- the copy is supposed to
be gone, and two regressions would otherwise pass silently: a resurrected
`scroll_display_legacy.py` (invisible to a check that never looks for the
file), and a returned guard with a different fallback (which defines no
`Legacy*` class at all).

Run: python scripts/check_scroll_adoption.py [plugin-id ...]
Exit code 0 when clean, 1 when a plugin inlines a legacy class or a sunset
plugin has grown its fallback back.
"""

import ast
import sys
from pathlib import Path

PLUGINS_DIR = Path(__file__).resolve().parent.parent / "plugins"

CORE_SCROLL_MODULE = "src.common.sports_scroll"

#: Scoreboards that have completed the B6 sunset: bundled copy deleted, core
#: import unguarded, manifest floored at the release that ships the module.
#:
#: Listed rather than inferred. A plugin that never adopted the core module
#: legitimately has neither a guard nor a bundled copy, so "no fallback here"
#: means the opposite thing for it. Adding an id is a deliberate act, and that
#: is the point -- it is the moment somebody states, in the same PR as the
#: deletion, that the sunset holds for that plugin.
SUNSET_PLUGINS = frozenset({
    "afl-scoreboard",
    "baseball-scoreboard",
    "basketball-scoreboard",
    "football-scoreboard",
    "lacrosse-scoreboard",
    "nrl-scoreboard",
    "soccer-scoreboard",
})


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


def sunset_violations(plugin_dir: Path) -> list[str]:
    """Ways a sunset plugin could quietly grow its fallback back.

    `offending_classes` asks whether the fallback is INLINED; this asks whether
    it exists at all, in either of the two shapes that would restore it.

    A guarded core import counts as a violation even with nothing to fall back
    to. Swallowing the ModuleNotFoundError leaves ScrollDisplay unbound, so the
    plugin loads and fails later with a NameError from the display path instead
    of failing at import with the missing module's name attached. That name is
    the entire user-visible contract of the sunset: PluginManager catches the
    error and records one line.
    """
    problems: list[str] = []

    if (plugin_dir / "scroll_display_legacy.py").exists():
        problems.append(
            "scroll_display_legacy.py is back. The sunset removed it and the "
            "manifest floor now guarantees the core module ships")

    tree = ast.parse((plugin_dir / "scroll_display.py").read_text(encoding="utf-8"))

    # tree.body, not _module_scope_statements: nesting the import inside an
    # `if` is precisely how the guard returns, and a scope walk would still
    # find it there and call it top-level.
    if not any(isinstance(n, ast.ImportFrom) and n.module == CORE_SCROLL_MODULE
               for n in tree.body):
        problems.append(
            f"scroll_display.py has no top-level `from {CORE_SCROLL_MODULE} "
            f"import`; after the sunset that is the only source of the base "
            f"classes")

    for node in ast.walk(tree):
        if isinstance(node, ast.Try) and any(
                isinstance(sub, ast.ImportFrom)
                and sub.module == CORE_SCROLL_MODULE
                for sub in ast.walk(node)):
            problems.append(
                f"the {CORE_SCROLL_MODULE} import is inside a try/except "
                f"again; with no fallback, catching only hides which module "
                f"was missing")
            break

    return problems


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

    # Sunset plugins, checked by directory rather than by that one file --
    # deliberately NOT inside the loop above, which `continue`s past a plugin
    # with no scroll_display.py. That is right for the general scan and wrong
    # here: a named sunset plugin that lost the file would exempt itself.
    sunset_problems: list[tuple[str, list[str]]] = []
    for pid in sorted(SUNSET_PLUGINS & set(ids)):
        plugin_dir = PLUGINS_DIR / pid
        if not (plugin_dir / "scroll_display.py").exists():
            sunset_problems.append(
                (pid, [f"listed in SUNSET_PLUGINS but {pid}/scroll_display.py "
                       f"is missing"]))
            continue
        try:
            found = sunset_violations(plugin_dir)
        except (SyntaxError, ValueError, OSError) as exc:
            unreadable.append((pid, str(exc)))
            continue
        if found:
            sunset_problems.append((pid, found))

    for pid, reasons in sunset_problems:
        for reason in reasons:
            print(f"::error::{pid}: {reason}")

    for pid, names in problems:
        print(f"::error::{pid}/scroll_display.py defines {', '.join(names)} at "
              f"module level. The fallback implementation belongs in "
              f"scroll_display_legacy.py; this file should only prefer the core "
              f"module and fall back to it.")

    for pid, reason in unreadable:
        print(f"::error::{pid}/scroll_display.py could not be parsed ({reason}). "
              f"Treating that as a pass would let a malformed file skip this "
              f"check entirely.")

    if problems or unreadable or sunset_problems:
        if sunset_problems:
            print(f"\nFAIL: {len(sunset_problems)} sunset plugin(s) regressed "
                  f"toward a bundled fallback.")
        if problems:
            print(f"\nFAIL: {len(problems)} of {checked} plugin(s) inline a legacy "
                  f"scroll implementation.")
        if unreadable:
            print(f"FAIL: {len(unreadable)} of {checked} plugin(s) could not be parsed.")
        return 1

    print(f"OK: {checked} plugin(s) with a scroll_display.py, none inlining a "
          f"legacy implementation; {len(SUNSET_PLUGINS & set(ids))} sunset "
          f"plugin(s) still free of one.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
