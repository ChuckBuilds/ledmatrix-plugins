#!/usr/bin/env python3
"""Guard against cross-plugin module-name collisions that break deferred imports.

The LEDMatrix core loads every plugin's top-level ``*.py`` files as BARE-name
modules on ``sys.path`` (e.g. ``import data_model``), then namespace-isolates
them *after* the entry point finishes loading. That isolation makes it safe for
two plugins to ship identically-named top-level modules (the sports plugins all
share ``sports.py``, ``scroll_display.py``, ...) **as long as every intra-plugin
import happens while the entry point is loading.**

It breaks for *deferred* imports — a ``from data_model import X`` that runs after
isolation, e.g.:
  * inside a subpackage's ``__init__`` that is imported lazily during the
    plugin's instantiation (``providers/__init__.py``), or
  * inside a function/method body that runs at update/display time.
By then the bare name has been popped, so the import re-resolves via sys.path
and can bind a *different* plugin's identically-named module — the plugin fails
to load. (This is exactly what hit ledmatrix-elections vs ledmatrix-flights,
both shipping ``data_model.py``.)

This check fails when a plugin's deferred import targets a sibling top-level
module whose name also exists as a top-level module in another plugin. The fix
is to give that module a plugin-unique name (e.g. ``election_data_model.py``).

Usage:
    python scripts/check_module_collisions.py
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGINS_DIR = REPO_ROOT / "plugins"


def _top_level_modules(plugin_dir: Path, entry_stem: str) -> Set[str]:
    """Bare-importable top-level module names for a plugin.

    Excludes the entry point (loaded as ``plugin_<id>``, never bare-imported)
    and test files (not shipped on the import path at runtime).
    """
    mods: Set[str] = set()
    for py in plugin_dir.glob("*.py"):
        stem = py.stem
        if stem == entry_stem or stem.startswith("test_") or stem == "conftest":
            continue
        mods.add(stem)
    return mods


def _subpackage_dirs(plugin_dir: Path) -> List[Path]:
    """Directories under the plugin that are Python packages (have __init__.py)."""
    return [p.parent for p in plugin_dir.rglob("__init__.py") if p.parent != plugin_dir]


def _imported_top_names(node: ast.AST) -> Set[str]:
    """Top-level module name(s) a single import statement references (level 0 only)."""
    names: Set[str] = set()
    if isinstance(node, ast.Import):
        for alias in node.names:
            names.add(alias.name.split(".")[0])
    elif isinstance(node, ast.ImportFrom):
        # Relative imports (level > 0) resolve within the package — not a bare
        # sys.path lookup, so they can't bind another plugin's module.
        if node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def _deferred_imports_in_file(path: Path, treat_all_as_deferred: bool) -> Set[str]:
    """Bare top-level module names imported in a *deferred* position in `path`.

    A subpackage file is treated as entirely deferred (the package itself may be
    imported lazily). In top-level files, only imports nested inside a function
    or method body are deferred; module-level imports there run during entry-point
    load and are safe.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return set()

    found: Set[str] = set()

    if treat_all_as_deferred:
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                found |= _imported_top_names(node)
        return found

    # Top-level file: only imports inside a function/method are deferred.
    class FuncImportVisitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.depth = 0

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self.depth += 1
            self.generic_visit(node)
            self.depth -= 1

        visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

        def visit_Import(self, node: ast.Import) -> None:
            if self.depth > 0:
                found.update(_imported_top_names(node))

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            if self.depth > 0:
                found.update(_imported_top_names(node))

    FuncImportVisitor().visit(tree)
    return found


def main() -> int:
    plugin_dirs = sorted(
        p for p in PLUGINS_DIR.iterdir()
        if p.is_dir() and (p / "manifest.json").is_file()
    )

    # Map every bare-importable top-level module name to the plugins that ship it.
    owners: Dict[str, Set[str]] = {}
    entry_stems: Dict[str, str] = {}
    tops: Dict[str, Set[str]] = {}
    for pdir in plugin_dirs:
        pid = pdir.name
        try:
            manifest = json.loads((pdir / "manifest.json").read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            manifest = {}
        entry_stem = Path(manifest.get("entry_point", "manager.py")).stem
        entry_stems[pid] = entry_stem
        mods = _top_level_modules(pdir, entry_stem)
        tops[pid] = mods
        for m in mods:
            owners.setdefault(m, set()).add(pid)

    violations: List[Tuple[str, str, str]] = []  # (plugin, module_name, source_file)
    for pdir in plugin_dirs:
        pid = pdir.name
        sibling_tops = tops[pid]
        sub_dirs = _subpackage_dirs(pdir)

        scan: List[Tuple[Path, bool]] = []
        for sub in sub_dirs:
            for py in sub.rglob("*.py"):
                scan.append((py, True))   # subpackage file: all imports deferred
        for py in pdir.glob("*.py"):
            if py.stem.startswith("test_"):
                continue
            scan.append((py, False))      # top-level file: only func-scoped deferred

        for py, treat_all in scan:
            for name in _deferred_imports_in_file(py, treat_all):
                # Only a hazard if it targets a sibling top-level module whose
                # name is shared with at least one other plugin.
                if name in sibling_tops and len(owners.get(name, set())) > 1:
                    rel = py.relative_to(PLUGINS_DIR)
                    violations.append((pid, name, str(rel)))

    if violations:
        print("Cross-plugin module collision via deferred import detected:\n")
        for pid, name, src in sorted(set(violations)):
            others = sorted(owners[name] - {pid})
            print(f"  {pid}: '{src}' deferred-imports '{name}', also shipped by: {', '.join(others)}")
        print(
            "\nThe core isolates bare-name plugin modules after the entry point loads, so a\n"
            "deferred import (subpackage __init__ or function-scoped) can bind another\n"
            "plugin's same-named module and fail to load. Rename the module to a\n"
            "plugin-unique name (e.g. '<plugin>_<module>.py') and update its imports."
        )
        return 1

    print(f"OK: no cross-plugin deferred-import collisions across {len(plugin_dirs)} plugins.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
