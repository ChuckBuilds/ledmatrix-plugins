#!/usr/bin/env python3
"""Keep the scoreboards' helper copies identical to core's sports_helpers.

LEDMatrix core ships ``src/common/sports_helpers.py`` (core PR #583): helpers
every scoreboard's ``sports.py`` carries a byte-identical private copy of --
``_clamp_window``, ``_clamp_seconds``, ``_logo_needs_refresh`` (with
``_MIN_WINDOW_DAYS`` / ``_MAX_WINDOW_DAYS``) and the ``SportsCore`` methods
``_mode_customization``, ``_setting_int``, ``_reset_dwell_on_reentry``,
``_next_switch_index``, ``_spread_weighted_order``, ``_odds_color`` and
``_upcoming_date_and_time_text``.

Core has its own parity test, but it only runs when ``LEDMATRIX_PLUGINS`` is
set, and core CI never sets it. This repo's CI already checks core out, so the
comparison lives here.

## What this checks

The promoted set is read from core's module itself: its public free functions
and constants, plus ``SportsHelpersMixin``'s methods and upper-case class
constants. Each is mapped to the plugins' private name (``RENAMES``), located in
every ``*-scoreboard/sports.py`` (module level, or on ``SportsCore``), and
compared as a normalised AST -- exactly the normalisation core's
``test/test_sports_helpers.py`` uses: docstrings and decorators dropped, public
names folded to the plugins' private spelling. Constants compare by value.

Per copy the result is **identical**, **DRIFTED** (fails, with a diff) or
**absent**. Absent is fine: a plugin that deleted its copy after adopting the
core module is the goal state, and ufc never had ``_odds_color`` /
``_upcoming_date_and_time_text``.

The mixin's ``_spread_weighted_order = staticmethod(spread_weighted_order)`` is
an alias, not a body; the free function is what gets compared against the
plugins' ``SportsCore._spread_weighted_order`` (as core's test does).

## Self-checks (so a broken finder cannot pass silently)

- a public core name missing from ``RENAMES`` (or a ``RENAMES`` key core no
  longer defines) fails: the map is stale;
- a promoted name no plugin carries fails, unless some plugin imports
  ``src.common.sports_helpers`` (then absence means adoption);
- fewer than ``MIN_PLUGINS`` scoreboards found fails;
- a scoreboard carrying none of the promoted names and not importing the core
  module fails: the finder is not seeing it.

A plugin that keeps a copy *and* imports ``src.common.sports_helpers`` is a
warning: its local copy shadows the core one.

Core is parsed with ``ast`` only, never imported.

Usage:
    python scripts/check_sports_helpers_parity.py
    python scripts/check_sports_helpers_parity.py --core ../LEDMatrix --plugins-dir plugins

Exit: 0 clean, 1 drift or a failed self-check, 2 skipped (no core checkout, or
core does not ship ``src/common/sports_helpers.py`` yet).
"""

from __future__ import annotations

import argparse
import ast
import difflib
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parent.parent
PLUGINS_DIR = REPO / "plugins"
CORE_MODULE = Path("src") / "common" / "sports_helpers.py"
CORE_DOTTED = "src.common.sports_helpers"
MIXIN = "SportsHelpersMixin"
PLUGIN_CLASS = "SportsCore"

#: Public names in core that are private in the plugins. Mirrors ``_RENAMES``
#: in core's test/test_sports_helpers.py. Mixin methods keep their names.
RENAMES = {
    "clamp_window": "_clamp_window",
    "clamp_seconds": "_clamp_seconds",
    "logo_needs_refresh": "_logo_needs_refresh",
    "spread_weighted_order": "_spread_weighted_order",
    "MIN_WINDOW_DAYS": "_MIN_WINDOW_DAYS",
    "MAX_WINDOW_DAYS": "_MAX_WINDOW_DAYS",
}

#: Names in core with no plugin copy, and why.
CORE_ONLY = {
    "_favorite_key": "override seam carried from src/base_classes; no plugin defines it",
    "favorite_rotation_boost": "a mixin default; the plugins set it per instance in __init__",
}

#: The nine scoreboards carrying the copies today.
MIN_PLUGINS = 8

_SKIP_DIRS = {"test", "tests", "__pycache__", ".venv", "venv", "node_modules"}


# --------------------------------------------------------------------------
# locating core

def find_core(explicit: Optional[str] = None) -> Optional[Path]:
    """A LEDMatrix core checkout: --core, LEDMATRIX_CORE, then the usual siblings."""
    candidates = [explicit] if explicit else [
        os.environ.get("LEDMATRIX_CORE", ""),
        str(REPO.parent / "LEDMatrix"),
        str(Path.home() / "projects" / "LEDMatrix"),
    ]
    for candidate in candidates:
        if candidate and (Path(candidate) / "src").is_dir():
            return Path(candidate)
    return None


# --------------------------------------------------------------------------
# normalisation (same as core's test/test_sports_helpers.py)

class _Normalise(ast.NodeTransformer):
    def visit_Name(self, node):
        node.id = RENAMES.get(node.id, node.id)
        return node

    def _func(self, node):
        node.name = RENAMES.get(node.name, node.name)
        node.decorator_list = []
        body = node.body
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            node.body = body[1:] or [ast.Pass()]
        self.generic_visit(node)
        return node

    visit_FunctionDef = _func


def normalised(node: ast.AST) -> ast.AST:
    """A detached, normalised copy of one definition."""
    copy = ast.parse(ast.unparse(node)).body[0]
    return _Normalise().visit(copy)


def _value_of(node: ast.AST) -> ast.AST:
    return node.value


def _const_key(node: ast.AST):
    """Constants compare by value (core's test uses literal_eval)."""
    try:
        return ("literal", ast.literal_eval(_value_of(node)))
    except (ValueError, SyntaxError, TypeError):
        value = ast.parse(ast.unparse(_value_of(node)), mode="eval").body
        return ("ast", ast.dump(_Normalise().visit(value)))


def _source(node: ast.AST, kind: str) -> str:
    if kind == "const":
        return f"= {ast.unparse(_value_of(node))}\n"
    return ast.unparse(normalised(node)) + "\n"


# --------------------------------------------------------------------------
# core side

@dataclass
class Promoted:
    core_name: str
    plugin_name: str
    kind: str            # "func" or "const"
    node: ast.AST

    def key(self, node: ast.AST):
        if self.kind == "const":
            return _const_key(node)
        return ast.dump(normalised(node))


def _target_name(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        target = node.targets[0]
    elif isinstance(node, ast.AnnAssign) and node.value is not None:
        target = node.target
    else:
        return None
    return target.id if isinstance(target, ast.Name) else None


def _is_static_alias(node: ast.AST, free_functions) -> bool:
    """``x = staticmethod(<promoted free function>)``."""
    value = getattr(node, "value", None)
    return (isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
            and value.func.id == "staticmethod" and len(value.args) == 1
            and isinstance(value.args[0], ast.Name)
            and value.args[0].id in free_functions)


def load_promoted(source: str) -> Tuple[List[Promoted], List[str]]:
    """(promoted definitions, problems) read from core's module source."""
    tree = ast.parse(source)
    promoted: List[Promoted] = []
    problems: List[str] = []
    seen = set()

    def add(name, kind, node):
        seen.add(name)
        if name in CORE_ONLY:
            return
        if not name.startswith("_") and name not in RENAMES:
            problems.append(
                f"core defines public {name!r} but RENAMES has no plugin name for "
                f"it: add the mapping (or a CORE_ONLY entry) so it is compared")
            return
        promoted.append(Promoted(name, RENAMES.get(name, name), kind, node))

    free_functions = {n.name for n in tree.body
                      if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")}
    mixin = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
            add(node.name, "func", node)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            name = _target_name(node)
            if name and name.isupper() and not name.startswith("_"):
                add(name, "const", node)
        elif isinstance(node, ast.ClassDef) and node.name == MIXIN:
            mixin = node

    if mixin is None:
        problems.append(f"core module has no class {MIXIN}")
    else:
        for item in mixin.body:
            if isinstance(item, ast.FunctionDef):
                add(item.name, "func", item)
            elif isinstance(item, (ast.Assign, ast.AnnAssign)):
                name = _target_name(item)
                if not name:
                    continue
                if _is_static_alias(item, free_functions):
                    seen.add(name)   # compared through the free function
                    continue
                if name.lstrip("_").isupper():
                    add(name, "const", item)
                else:
                    seen.add(name)
                    if name not in CORE_ONLY:
                        problems.append(
                            f"{MIXIN}.{name} is a class attribute this check does "
                            f"not know how to compare: add it to CORE_ONLY or teach "
                            f"the check")

    for name in sorted(set(RENAMES) - seen):
        problems.append(f"RENAMES maps {name!r}, which core no longer defines: "
                        f"the name map is stale")
    return promoted, problems


# --------------------------------------------------------------------------
# plugin side

def plugin_definitions(tree: ast.Module) -> Tuple[Dict[str, ast.AST], Dict[str, ast.AST]]:
    """(module-level, SportsCore-level) definitions by name."""
    module, core = {}, {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            module[node.name] = node
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            name = _target_name(node)
            if name:
                module[name] = node
        elif isinstance(node, ast.ClassDef) and node.name == PLUGIN_CLASS:
            for item in node.body:
                if isinstance(item, ast.FunctionDef):
                    core[item.name] = item
                elif isinstance(item, (ast.Assign, ast.AnnAssign)):
                    name = _target_name(item)
                    if name:
                        core[name] = item
    return module, core


def imports_core_module(source: str) -> bool:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(a.name == CORE_DOTTED for a in node.names):
                return True
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            if node.module == CORE_DOTTED:
                return True
            if node.module == "src.common" and any(a.name == "sports_helpers"
                                                   for a in node.names):
                return True
    return False


@dataclass
class PluginReport:
    name: str
    identical: List[str] = field(default_factory=list)
    absent: List[str] = field(default_factory=list)
    drifted: List[Tuple[str, str]] = field(default_factory=list)   # (name, diff)
    imports_core: bool = False
    error: Optional[str] = None


def _diff(name: str, plugin: str, ours: str, theirs: str, limit: int = 30) -> str:
    lines = list(difflib.unified_diff(
        ours.splitlines(keepends=True), theirs.splitlines(keepends=True),
        fromfile=f"core:{CORE_MODULE.as_posix()}::{name}",
        tofile=f"{plugin}/sports.py::{name}", n=2))
    if len(lines) > limit:
        lines = lines[:limit] + [f"... ({len(lines) - limit} more diff lines)\n"]
    return "".join(lines)


def scan_plugin(plugin_dir: Path, promoted: List[Promoted]) -> PluginReport:
    report = PluginReport(plugin_dir.name)
    for path in sorted(plugin_dir.rglob("*.py")):
        rel = path.relative_to(plugin_dir)
        if any(part in _SKIP_DIRS for part in rel.parts[:-1]):
            continue
        if imports_core_module(path.read_text(encoding="utf-8", errors="replace")):
            report.imports_core = True
            break
    try:
        tree = ast.parse((plugin_dir / "sports.py").read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        report.error = f"sports.py could not be parsed ({exc})"
        return report
    module, core = plugin_definitions(tree)
    for item in promoted:
        # Free functions may live at module level or on SportsCore
        # (spread_weighted_order is a staticmethod there); methods and class
        # constants only on SportsCore.
        if item.kind == "func" and item.core_name in RENAMES:
            theirs = module.get(item.plugin_name) or core.get(item.plugin_name)
        elif item.kind == "const" and item.core_name in RENAMES:
            theirs = module.get(item.plugin_name)
        else:
            theirs = core.get(item.plugin_name)
        if theirs is None or (item.kind == "func") != isinstance(theirs, ast.FunctionDef):
            report.absent.append(item.plugin_name)
        elif item.key(theirs) == item.key(item.node):
            report.identical.append(item.plugin_name)
        else:
            report.drifted.append((item.plugin_name, _diff(
                item.plugin_name, report.name,
                _source(item.node, item.kind), _source(theirs, item.kind))))
    return report


def scoreboards(plugins_dir: Path) -> List[Path]:
    return sorted(p for p in plugins_dir.iterdir()
                  if p.is_dir() and p.name.endswith("-scoreboard")
                  and (p / "sports.py").is_file())


# --------------------------------------------------------------------------
# the check

def run(core: Optional[Path], plugins_dir: Path, min_plugins: int = MIN_PLUGINS,
        verbose: bool = True) -> int:
    if core is None:
        print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE or pass --core)")
        return 2
    core_file = core / CORE_MODULE
    if not core_file.is_file():
        print(f"SKIP: core does not ship sports_helpers yet "
              f"({core_file.as_posix()} not found; lands with ChuckBuilds/LEDMatrix#583)")
        return 2
    if not plugins_dir.is_dir():
        print(f"SKIP: no plugins directory at {plugins_dir}")
        return 2

    try:
        promoted, problems = load_promoted(core_file.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        print(f"FAIL: {core_file.as_posix()} is not parseable ({exc})")
        return 1

    print(f"Core: {core_file.as_posix()}")
    print(f"Promoted names ({len(promoted)}): "
          + ", ".join(f"{p.core_name}->{p.plugin_name}" if p.core_name != p.plugin_name
                      else p.core_name for p in promoted))

    reports = [scan_plugin(d, promoted) for d in scoreboards(plugins_dir)]
    warnings: List[str] = []
    print(f"\nScoreboards scanned: {len(reports)}")
    for r in reports:
        if r.error:
            problems.append(f"{r.name}: {r.error}")
            continue
        flag = "  imports core sports_helpers" if r.imports_core else ""
        print(f"  {r.name}: {len(r.identical)} identical, {len(r.drifted)} DRIFTED, "
              f"{len(r.absent)} absent{flag}")
        if verbose:
            if r.identical:
                print(f"      identical: {', '.join(r.identical)}")
            if r.absent:
                print(f"      absent:    {', '.join(r.absent)}")
        for name, _ in r.drifted:
            print(f"      DRIFTED:   {name}")
        if r.imports_core and (r.identical or r.drifted):
            carried = [n for n in r.identical] + [n for n, _ in r.drifted]
            warnings.append(
                f"{r.name} imports {CORE_DOTTED} but still defines "
                f"{', '.join(carried)}; the local copies shadow the core ones -- "
                f"delete them once the plugin floors on the release that ships it")
        if not (r.identical or r.drifted or r.imports_core):
            problems.append(
                f"{r.name}: carries none of the {len(promoted)} promoted names and "
                f"does not import {CORE_DOTTED} -- the finder is not seeing its copies")

    if len(reports) < min_plugins:
        problems.append(f"found {len(reports)} scoreboard(s) with sports.py under "
                        f"{plugins_dir}, expected at least {min_plugins}: the finder "
                        f"is not looking where the copies are")

    any_adopter = any(r.imports_core for r in reports)
    for item in promoted:
        carriers = [r for r in reports
                    if item.plugin_name in r.identical
                    or any(n == item.plugin_name for n, _ in r.drifted)]
        if reports and not carriers and not any_adopter:
            problems.append(
                f"{item.core_name} (plugin name {item.plugin_name}) matched no plugin "
                f"copy and no plugin imports {CORE_DOTTED}: the name map is stale")

    drifted = [(r.name, n, d) for r in reports for n, d in r.drifted]
    comparisons = sum(len(r.identical) + len(r.drifted) for r in reports)
    absent = sum(len(r.absent) for r in reports)
    print(f"\n{comparisons} comparison(s): {comparisons - len(drifted)} identical, "
          f"{len(drifted)} drifted; {absent} absent.")

    for w in warnings:
        print(f"WARN: {w}")

    if drifted:
        print(f"\nDRIFT: {len(drifted)} plugin copy(ies) differ from core's "
              f"{CORE_MODULE.as_posix()}:\n")
        for plugin, name, diff in drifted:
            print(f"  {plugin}: {name}")
            print("    " + diff.replace("\n", "\n    ").rstrip())
            print()
        print("Port the change to core's src/common/sports_helpers.py and every "
              "plugin copy together, or stop treating the helper as shared.")
    for p in problems:
        print(f"FAIL: {p}")
    if drifted or problems:
        return 1
    print("\nPASS: every plugin copy of a sports_helpers name matches core.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--core", help="LEDMatrix core checkout (default: LEDMATRIX_CORE, "
                                   "then ../LEDMatrix)")
    ap.add_argument("--plugins-dir", default=str(PLUGINS_DIR),
                    help="directory holding the plugins (default: this repo's plugins/)")
    ap.add_argument("--quiet", action="store_true",
                    help="only per-plugin counts, not the names compared")
    args = ap.parse_args(argv)
    return run(find_core(args.core), Path(args.plugins_dir), verbose=not args.quiet)


if __name__ == "__main__":
    sys.exit(main())
