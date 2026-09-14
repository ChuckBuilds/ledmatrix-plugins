#!/usr/bin/env python3
"""Fail when a plugin needs a newer core than its manifest admits.

A plugin that does an *unguarded* ``from src.common.sports_shared import ...``
cannot even be imported on a core older than 3.3.1, where that module first
shipped. If its manifest still declares a 3.3.0 floor, the install gate lets
it onto a 3.3.0 core and the plugin dies at load with ``ModuleNotFoundError``
-- which is exactly what the eight scoreboards did (drift audit finding M5).
Nothing checked it, because the floor and the imports live in different files
and are edited by different PRs.

## What this checks

For every runtime ``.py`` file in a plugin (tests excluded -- they never run
on a device), each ``import src.X`` / ``from src.X import ...`` whose module
first shipped in a core release *newer than the plugin's effective floor* is
reported, unless the import is guarded.

**Guarded** means the import statement sits in the body of a ``try`` with a
handler that would catch the failure: ``except ImportError``,
``ModuleNotFoundError``, ``Exception``, ``BaseException``, or a bare
``except:`` (alone or in a tuple). That is CLAUDE.md non-negotiable #6's
shape; the fallback is the plugin's business, not this check's.

One more shape counts as guarded: an import *inside a function* of a module
the same file already imports under such a guard. That is the deferred
re-import idiom -- ``try: from src.adaptive_layout import X`` at the top sets
``ADAPTIVE_AVAILABLE``, and a function only reached when it is True does
``from src.adaptive_layout import Region``. The flag is invisible to an AST
check; the guarded sibling import is not. A *module-level* unguarded import is
never excused this way, because it runs on every load.

**Effective floor** is what the core's install gate actually enforces
(``src/plugin_system/compatibility.py``): the declared minimum
(``min_ledmatrix_version``, ``requires.min_ledmatrix_version``, then
``versions[0].ledmatrix_min_version`` / ``ledmatrix_min``), raised to the
lowest bound ``compatible_versions`` admits. No floor at all reads as 0.0.0.

## The table, and what it does not know

``MODULE_FIRST_VERSION`` lists only modules that arrived *after* 3.0.0, the
first core with the plugin system. A plugin cannot load on anything older, so
modules present in 3.0.0 are always there and need no entry. Versions come
from the release tags in the LEDMatrix repo (first tag whose tree contains the
file), regenerated with::

    for t in v3.0.0 v3.1.0 v3.2.0 v3.3.0 v3.3.1; do
        git ls-tree -r --name-only $t -- src | grep '\\.py$' > $t.txt; done
    # then diff consecutive lists

``None`` marks a module on core ``main`` that is in no tagged release yet: no
floor can promise it, so any unguarded import of it is reported.

Limits, stated plainly: a module not in the table is assumed old enough (add
it when core ships one); names re-exported through a package ``__init__``
(``from src.common import draw_fitted_text``) are checked against the package,
not the module that defines the name; and dynamic imports (``importlib``) are
invisible.

Usage:
    python scripts/check_min_core_version.py                 # every plugin
    python scripts/check_min_core_version.py afl-scoreboard  # just these

Exit: 0 clean, 1 findings, 2 prerequisites missing (no plugins directory, or
none of the requested plugins exist).
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGINS = REPO_ROOT / "plugins"

Version = Tuple[int, int, int]

#: module -> first core release that ships it (None: not released yet).
#: A lookup walks up the dotted path, so a package entry covers its submodules
#: unless a submodule has a more specific (later) entry of its own.
MODULE_FIRST_VERSION = {
    # v3.1.0
    "src.backup_manager": "3.1.0",
    "src.common.sync_manager": "3.1.0",
    "src.error_aggregator": "3.1.0",
    "src.plugin_system.testing.visual_display_manager": "3.1.0",
    "src.vegas_mode": "3.1.0",
    # v3.2.0
    "src.adaptive_images": "3.2.0",
    "src.adaptive_layout": "3.2.0",
    # src.base_classes.sports itself was a module in 3.0.0; 3.2.0 made it a
    # package, and only these submodules are new.
    "src.base_classes.sports.capabilities": "3.2.0",
    "src.base_classes.sports.core": "3.2.0",
    "src.base_classes.sports.modes": "3.2.0",
    "src.common.snapshot_policy": "3.2.0",
    "src.common.sports_scroll": "3.2.0",
    "src.element_style": "3.2.0",
    "src.plugin_system.compatibility": "3.2.0",
    "src.plugin_system.testing.bounds_display_manager": "3.2.0",
    "src.plugin_system.testing.harness": "3.2.0",
    "src.plugin_system.testing.loading": "3.2.0",
    "src.plugin_system.testing.sizes": "3.2.0",
    "src.skin_system": "3.2.0",
    "src.vegas_mode.geometry": "3.2.0",
    # v3.3.0
    "src.common.sports_card": "3.3.0",
    "src.common.sports_game_renderer": "3.3.0",
    # v3.3.1 (but see REPORTED_AS: that release reports itself as 3.3.0)
    "src.common.sports_shared": "3.3.1",
    # on core main, in no tagged release yet
    "src.common.font_layout": None,
    "src.common.path_safety": None,
    "src.common.scroll_config": None,
}

#: Releases whose ``src/__init__.py`` ``__version__`` lags their tag. The
#: install gate compares a floor against that string, so the floor that
#: admits such a release is the version it *reports*: core v3.3.1 ships
#: ``__version__ = "3.3.0"``, and no core has ever reported 3.3.1, so a 3.3.1
#: floor would refuse every core. A module first shipped in one of these
#: releases is therefore satisfied by the reported version.
#:
#: That is exact, not a loophole: tag v3.3.0 itself reports "3.2.0" (its
#: bump, #516, landed after the tag), so a core reporting "3.3.0" is v3.3.1 or
#: later and has ``sports_shared``. The only exception is a dev checkout of
#: core main between #516 and #515, a few hours on 2026-09-03. Entries
#: describe published tags, so they are permanent.
REPORTED_AS = {
    "3.3.1": "3.3.0",
}

_TEST_DIRS = {"test", "tests", "__pycache__", ".venv", "venv", "node_modules"}
_CATCHES_IMPORT_ERROR = {"ImportError", "ModuleNotFoundError", "Exception",
                         "BaseException"}


# --------------------------------------------------------------------------
# versions

def parse_version(value) -> Optional[Version]:
    """``X.Y.Z`` (leading v, missing parts, suffixes tolerated) or None."""
    if not isinstance(value, str):
        return None
    m = re.match(r"^\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", value)
    if not m:
        return None
    return tuple(int(g or 0) for g in m.groups())  # type: ignore[return-value]


def fmt(v: Version) -> str:
    return ".".join(str(n) for n in v)


def _declared_min(manifest: dict) -> Optional[str]:
    """Mirror of core `compatibility.declared_min_version`."""
    declared = manifest.get("min_ledmatrix_version")
    if not declared:
        requires = manifest.get("requires")
        if isinstance(requires, dict):
            declared = requires.get("min_ledmatrix_version")
    if declared:
        return declared
    versions = manifest.get("versions")
    if isinstance(versions, list) and versions and isinstance(versions[0], dict):
        return (versions[0].get("ledmatrix_min_version")
                or versions[0].get("ledmatrix_min"))
    return None


def _compatible_lower_bound(manifest: dict) -> Optional[Version]:
    """Lowest core `compatible_versions` admits (entries are alternatives)."""
    specs = manifest.get("compatible_versions")
    if not isinstance(specs, list):
        return None
    lows = []
    for spec in specs:
        if not isinstance(spec, str) or not spec.strip():
            continue
        spec = spec.strip()
        if " - " in spec:
            low = parse_version(spec.partition(" - ")[0])
        elif spec.startswith(("<=", "<")):
            low = (0, 0, 0)
        else:
            low = parse_version(spec.lstrip(">=~^ "))
        if low is not None:
            lows.append(low)
    return min(lows) if lows else None


def effective_floor(manifest: dict) -> Version:
    """The oldest core the install gate would let this plugin onto."""
    floor = parse_version(_declared_min(manifest)) or (0, 0, 0)
    compat = _compatible_lower_bound(manifest)
    if compat is not None and compat > floor:
        floor = compat
    return floor


def first_version(module: str) -> Tuple[Optional[str], Optional[str]]:
    """(matched table key, its version) for `module`, or (None, None).

    The version half is None for an unreleased module; the key half is None
    when nothing in the table covers the module.
    """
    parts = module.split(".")
    for i in range(len(parts), 0, -1):
        key = ".".join(parts[:i])
        if key in MODULE_FIRST_VERSION:
            return key, MODULE_FIRST_VERSION[key]
    return None, None


# --------------------------------------------------------------------------
# imports

def _handler_catches_import_error(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    nodes = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    for node in nodes:
        name = node.attr if isinstance(node, ast.Attribute) else getattr(node, "id", None)
        if name in _CATCHES_IMPORT_ERROR:
            return True
    return False


def core_imports(source: str) -> Iterable[Tuple[str, int, bool, bool]]:
    """Yield (module, lineno, guarded, in_function) per `src.*` import.

    ``from src.common import sports_card`` yields both ``src.common`` and
    ``src.common.sports_card``: the name may be a submodule, and a table entry
    for either should be able to match.
    """
    tree = ast.parse(source)

    def visit(node, guarded, in_func):
        if isinstance(node, ast.Try) or type(node).__name__ == "TryStar":
            body_guarded = guarded or any(
                _handler_catches_import_error(h) for h in node.handlers)
            for child in node.body:
                yield from visit(child, body_guarded, in_func)
            for child in node.handlers + node.orelse + node.finalbody:
                yield from visit(child, guarded, in_func)
            return
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "src" or alias.name.startswith("src."):
                    yield alias.name, node.lineno, guarded, in_func
            return
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level == 0 and (mod == "src" or mod.startswith("src.")):
                yield mod, node.lineno, guarded, in_func
                for alias in node.names:
                    if alias.name != "*":
                        yield f"{mod}.{alias.name}", node.lineno, guarded, in_func
            return
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            in_func = True
        for child in ast.iter_child_nodes(node):
            yield from visit(child, guarded, in_func)

    yield from visit(tree, False, False)


def _is_test_file(rel: Path) -> bool:
    name = rel.name
    if name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py":
        return True
    return any(part in _TEST_DIRS for part in rel.parts[:-1])


def runtime_files(plugin_dir: Path) -> List[Path]:
    return sorted(p for p in plugin_dir.rglob("*.py")
                  if not _is_test_file(p.relative_to(plugin_dir)))


# --------------------------------------------------------------------------
# the check

def check_plugin(plugin_dir: Path) -> List[str]:
    """Problems for one plugin directory (empty when fine)."""
    manifest_path = plugin_dir / "manifest.json"
    if not manifest_path.is_file():
        return []
    pid = plugin_dir.name
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"{pid}: manifest.json could not be read ({exc})"]
    if not isinstance(manifest, dict):
        return [f"{pid}: manifest.json is not an object"]

    floor = effective_floor(manifest)
    problems: List[str] = []
    for path in runtime_files(plugin_dir):
        rel = path.relative_to(plugin_dir).as_posix()
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            found = list(core_imports(source))
        except SyntaxError as exc:
            print(f"  ! {pid}/{rel}: not parseable, skipped ({exc.msg})",
                  file=sys.stderr)
            continue
        guarded_keys = {first_version(m)[0] for m, _, g, _ in found if g}
        reported = set()
        for module, lineno, guarded, in_func in found:
            if guarded:
                continue
            key, needed = first_version(module)
            if key is None or (lineno, key) in reported:
                continue
            if in_func and key in guarded_keys:
                continue  # deferred re-import behind a guarded sibling
            if needed is None:
                reported.add((lineno, key))
                problems.append(
                    f"{pid}/{rel}:{lineno}: unguarded import of {key}, which is "
                    f"in no released core yet (floor {fmt(floor)}). Guard it "
                    f"with try/except ImportError and a fallback.")
                continue
            enforceable = REPORTED_AS.get(needed, needed)
            need_v = parse_version(enforceable)
            if need_v > floor:
                reported.add((lineno, key))
                problems.append(
                    f"{pid}/{rel}:{lineno}: unguarded import of {key} needs core "
                    f">= {enforceable}, but the manifest admits {fmt(floor)}. Raise "
                    f"the floor (ledmatrix_min_version / compatible_versions) "
                    f"or guard the import.")
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("plugin_ids", nargs="*",
                    help="plugin ids to check (default: every plugin)")
    args = ap.parse_args(argv)

    if not PLUGINS.is_dir():
        print(f"SKIP: no plugins directory at {PLUGINS}", file=sys.stderr)
        return 2

    if args.plugin_ids:
        dirs = [PLUGINS / pid for pid in args.plugin_ids
                if (PLUGINS / pid / "manifest.json").is_file()]
        missing = sorted(set(args.plugin_ids) - {d.name for d in dirs})
        for pid in missing:
            print(f"  ! {pid}: no plugins/{pid}/manifest.json, skipped",
                  file=sys.stderr)
    else:
        dirs = sorted(p for p in PLUGINS.iterdir()
                      if (p / "manifest.json").is_file())
    if not dirs:
        print("SKIP: no plugin manifests to check", file=sys.stderr)
        return 2

    problems = [p for d in dirs for p in check_plugin(d)]
    if not problems:
        print(f"OK: {len(dirs)} plugin(s) checked; no unguarded core import "
              f"needs a newer core than its manifest declares.")
        return 0
    for problem in problems:
        print(f"  - {problem}", file=sys.stderr)
    print(f"\n{len(problems)} problem(s). On an older core these imports raise "
          f"ModuleNotFoundError at plugin load.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
