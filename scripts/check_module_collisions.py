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

A top-level *package* is a module name too: a deferred ``import data.teams``
resolves ``data`` the same way, so a subdirectory holding ``.py`` files counts
as a collision candidate alongside the ``*.py`` files (test and tooling
directories excepted).

A file that cannot be parsed fails the check. Treating it as import-free would
report "OK" for exactly the file the check could not read.

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

# Subdirectories that hold .py files but are never imported by the plugin at
# runtime: its own tests and developer tooling.
NON_RUNTIME_DIRS = {"test", "tests", "scripts", "__pycache__"}

# A run that inspects fewer plugins than this is not looking at the plugin tree.
MIN_PLAUSIBLE_PLUGINS = 20


class UnparseableFile(Exception):
    """A plugin file the checker could not parse, so could not vouch for."""


def _top_level_modules(plugin_dir: Path, entry_stem: str) -> Set[str]:
    """Bare-importable top-level module and package names for a plugin.

    Excludes the entry point (loaded as ``plugin_<id>``, never bare-imported),
    test files (not shipped on the import path at runtime), and test/tooling
    directories.
    """
    mods: Set[str] = set()
    for py in plugin_dir.glob("*.py"):
        stem = py.stem
        if stem == entry_stem or stem.startswith("test_") or stem == "conftest":
            continue
        mods.add(stem)
    for sub in plugin_dir.iterdir():
        if (sub.is_dir() and sub.name not in NON_RUNTIME_DIRS
                and not sub.name.startswith(".") and sub.name.isidentifier()
                and any(sub.rglob("*.py"))):
            mods.add(sub.name)
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

    Raises UnparseableFile when the file cannot be read or parsed.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError, ValueError, OSError) as e:
        raise UnparseableFile(f"{type(e).__name__}: {e}") from e

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


def find_problems(plugins_dir: Path):
    """Scan `plugins_dir`.

    Returns (violations, unparseable, owners, plugin_count, files_scanned):
    violations are (plugin, module_name, source_file) and unparseable are
    (source_file, error).
    """
    plugin_dirs = sorted(
        p for p in plugins_dir.iterdir()
        if p.is_dir() and (p / "manifest.json").is_file()
    )

    # Map every bare-importable top-level name to the plugins that ship it.
    owners: Dict[str, Set[str]] = {}
    tops: Dict[str, Set[str]] = {}
    for pdir in plugin_dirs:
        pid = pdir.name
        try:
            manifest = json.loads((pdir / "manifest.json").read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            manifest = {}
        entry_stem = Path(manifest.get("entry_point", "manager.py")).stem
        mods = _top_level_modules(pdir, entry_stem)
        tops[pid] = mods
        for m in mods:
            owners.setdefault(m, set()).add(pid)

    violations: List[Tuple[str, str, str]] = []
    unparseable: List[Tuple[str, str]] = []
    files_scanned = 0
    for pdir in plugin_dirs:
        pid = pdir.name
        sibling_tops = tops[pid]

        scan: List[Tuple[Path, bool]] = []
        for sub in _subpackage_dirs(pdir):
            if NON_RUNTIME_DIRS & set(sub.relative_to(pdir).parts):
                continue
            for py in sub.rglob("*.py"):
                scan.append((py, True))   # subpackage file: all imports deferred
        for py in pdir.glob("*.py"):
            if py.stem.startswith("test_"):
                continue
            scan.append((py, False))      # top-level file: only func-scoped deferred

        for py, treat_all in dict.fromkeys(scan):
            rel = str(py.relative_to(plugins_dir))
            files_scanned += 1
            try:
                names = _deferred_imports_in_file(py, treat_all)
            except UnparseableFile as e:
                unparseable.append((rel, str(e)))
                continue
            for name in names:
                # Only a hazard if it targets a sibling top-level module whose
                # name is shared with at least one other plugin.
                if name in sibling_tops and len(owners.get(name, set())) > 1:
                    violations.append((pid, name, rel))

    return violations, unparseable, owners, len(plugin_dirs), files_scanned


def main(plugins_dir: Path = PLUGINS_DIR, min_plugins: int = MIN_PLAUSIBLE_PLUGINS) -> int:
    violations, unparseable, owners, n_plugins, n_files = find_problems(plugins_dir)
    failed = False

    if n_plugins < min_plugins:
        print(f"FAIL only {n_plugins} plugins found under {plugins_dir}; the check "
              f"is not looking at the plugin tree")
        failed = True

    if unparseable:
        print("Plugin files that could not be parsed (so could not be checked):\n")
        for src, err in sorted(unparseable):
            print(f"  FAIL {src}: {err}")
        print()
        failed = True

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
        failed = True

    if failed:
        return 1
    print(f"OK: no cross-plugin deferred-import collisions across {n_plugins} plugins "
          f"({n_files} files parsed).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
