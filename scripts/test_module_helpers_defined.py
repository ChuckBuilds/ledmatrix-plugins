#!/usr/bin/env python3
"""A module-level helper must be defined in every module that calls it.

Five sports plugins got the same BDF-font fix: load a .bdf through
ImageFont.truetype, and when FreeType rejects the requested size, retry at the
size the file declares. The retry needs a small `_bdf_pixel_size()` reader --
which was added to one of the five and called in all five:

    except OSError:
        native = _bdf_pixel_size(font_path)   # NameError in four of them

Nothing caught it. The call sits inside an `except OSError:` handler, so it
only runs when a BDF is requested at a non-native size -- which is precisely
the case the fix exists for, and precisely the case no test exercised. Every
unit test passed and the plugins imported fine; the fix was simply dead in
four plugins and raised NameError in the one situation it was written for.

This checks the general invariant rather than that one helper: a call to a
bare `_name(...)` must resolve to something the module actually defines or
imports. `pylint --errors-only` reports the same class of fault (E0602) if you
would rather run that.

Run: python scripts/test_module_helpers_defined.py
"""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Names that look module-level but are supplied by the runtime or a star
#: import. Kept explicit so an addition here is a deliberate decision.
ALLOWED_UNDEFINED = {
    "__name__", "__file__", "__doc__", "__package__", "__spec__",
}


def _bound_names(tree: ast.AST) -> set:
    """Every name the module binds: defs, classes, imports, assignments."""
    bound = set(dir(__builtins__)) | ALLOWED_UNDEFINED
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            bound.add(node.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                bound.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, (ast.arg,)):
            bound.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, ast.Global):
            bound.update(node.names)
    return bound


def check(path: Path) -> list:
    """Underscore-prefixed calls in `path` that nothing in it defines."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return []

    bound = _bound_names(tree)
    missing = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        # Only bare `_name(...)`. An attribute call (self._x, mod._x) resolves
        # at runtime against an object this check cannot see.
        if isinstance(fn, ast.Name) and fn.id.startswith("_") and fn.id not in bound:
            missing.append((node.lineno, fn.id))
    return missing


def main() -> int:
    files = sorted(ROOT.glob("plugins/*/**/*.py"))
    failures = []
    for path in files:
        for lineno, name in check(path):
            failures.append(f"{path.relative_to(ROOT)}:{lineno}: {name}() is never defined here")

    if failures:
        print("A module-level helper is called but not defined.")
        print("This raises NameError the first time that line runs:\n")
        for f in failures:
            print(f"  {f}")
        print("\nDefine the helper in each module that calls it, or import it.")
        return 1

    print(f"OK: every module-level helper call resolves ({len(files)} files checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
