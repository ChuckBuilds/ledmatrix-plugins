#!/usr/bin/env python3
"""Fail when a plugin calls a core method, or passes it a keyword, that its
manifest floor does not guarantee.

## Why this exists: module tracking missed #462

``check_min_core_version.py`` knows which core *modules* arrived in which
release. It cannot see a new *argument*. Plugins PR #462 (2026-09-07) made
seven scrolling plugins call::

    self.display_manager.set_scrolling_state(True, frame_hold=...)

``frame_hold`` arrived with core #523, which is on core main but in no tagged
release: v3.3.1 still has ``set_scrolling_state(self, is_scrolling)``. Every
module those plugins import exists in 3.3.1, so the module gate passed, the
manifests still floored at 2.0.0, and the store served them to 3.3.x cores,
where the call raises ``TypeError`` on every frame and the ticker is blank.

## What this checks

For every runtime ``.py`` file in a plugin (tests excluded), each attribute
call ``<anything>.<method>(...)`` matching an entry in ``API_FIRST_VERSION``
is reported when that entry is newer than the plugin's effective floor and the
call is not guarded. An entry is either a *keyword* (``frame_hold`` on
``set_scrolling_state``, passed by name or by position) or a whole *method*.
The receiver's type is invisible to an AST check, so matching is by method
name; a method-only entry is skipped for a plugin that defines a function of
that name itself.

The floor is the one the install gate enforces, computed exactly as
``check_min_core_version.effective_floor`` does (shared, not copied).

**Guarded** means a fallback really exists, which is narrower than "somewhere
inside a try":

- the call is the *only* statement of a ``try`` body, and that statement is a
  simple one (expression, assignment, return), and a handler catches
  ``TypeError`` (keyword entries) or ``AttributeError`` (method entries), or
  ``Exception`` / ``BaseException`` / bare ``except:``. A try wrapping the
  whole frame does not count: there a ``TypeError`` aborts the frame, which is
  what odds-ticker and text-display did on 3.3.x -- one drew its fallback
  message instead of the odds, the other drew nothing.
- for a method entry only, the call sits in the body of an ``if`` whose test
  is ``hasattr(<x>, "<method>")``. A ``hasattr`` check cannot protect a
  *keyword*, so it never guards one.

## Versions, and entries in no tagged release

A version string is the first core release tag that ships the API.
``REPORTED_AS`` from the module gate applies (v3.3.1 reports 3.3.0).

``None`` means "on core main, in no tagged release yet" -- the same spelling
``MODULE_FIRST_VERSION`` uses. Unlike an untagged module, an untagged API here
is satisfied by a floor at or above ``UNTAGGED_SATISFIED_BY``: the version
core main already reports in ``src/__init__.py``. No tagged release reports
that version, so a core that passes such a floor is core main after its
version bump (#580, 2026-09-14), which contains every ``None`` entry below
(#523 landed 2026-09-07). When that version is tagged, replace each ``None``
with it.

Limits: an API not in the table is assumed old enough (add a row when core
changes a signature plugins call); ``**kwargs`` unpacking and ``getattr``
calls are invisible.

Usage:
    python scripts/check_core_api_signatures.py              # every plugin
    python scripts/check_core_api_signatures.py news odds-ticker

Exit: 0 PASS, 1 FAIL, 2 prerequisites missing (no plugins directory, none of
the requested plugins exist, or a whole-tree scan saw no call to any tracked
method, which means the scan itself is broken).
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_min_core_version as modgate  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGINS = REPO_ROOT / "plugins"


class ApiChange(NamedTuple):
    method: str
    keyword: Optional[str]     # None: the method itself is new
    position: Optional[int]    # 0-based positional index of `keyword`, if any
    core_file: str             # where core defines it (for the tag test)
    first_version: Optional[str]  # first release tag; None: core main only
    note: str


#: Core APIs whose signature changed after 3.0.0, with the release that first
#: ships them. Add a row whenever core adds a keyword or method plugins call.
API_FIRST_VERSION: Tuple[ApiChange, ...] = (
    ApiChange("set_scrolling_state", "frame_hold", 1, "src/display_manager.py",
              None, "core #523, planned 3.4.0"),
    ApiChange("set_frame_hold", None, None, "src/display_manager.py",
              None, "core #523, planned 3.4.0"),
    ApiChange("set_pixels_per_frame", None, None, "src/common/scroll_helper.py",
              None, "core main, planned 3.4.0"),
)

#: The version core main reports. See "entries in no tagged release".
UNTAGGED_SATISFIED_BY = "3.4.0"

_BROAD = {"Exception", "BaseException"}
_SIMPLE_STMTS = (ast.Expr, ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Return)


class Call(NamedTuple):
    method: str
    keywords: Set[str]
    positional: int
    lineno: int
    narrow_catches: Tuple[frozenset, ...]  # handler names of narrow trys
    hasattr_names: frozenset


def _handler_names(handler: ast.ExceptHandler) -> Set[str]:
    if handler.type is None:
        return {"<bare>"}
    nodes = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return {n.attr if isinstance(n, ast.Attribute) else getattr(n, "id", "")
            for n in nodes}


def _hasattr_branches(test: ast.AST) -> Tuple[frozenset, frozenset]:
    """Method names an ``if`` test proves present in (body, orelse).

    Only a branch that runs *because* ``hasattr`` was true is guarded: in
    ``if not hasattr(dm, "m"): dm.m()`` the call runs exactly when the method
    is missing, so counting it as guarded inverted the check. ``not`` swaps the
    branches; ``and`` proves every operand in the body and nothing in the else
    (any one may have failed); ``or`` is the mirror image. Anything else proves
    nothing.
    """
    empty = frozenset()
    if (isinstance(test, ast.Call) and getattr(test.func, "id", None) == "hasattr"
            and len(test.args) == 2 and isinstance(test.args[1], ast.Constant)
            and isinstance(test.args[1].value, str)):
        return frozenset({test.args[1].value}), empty
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        body, orelse = _hasattr_branches(test.operand)
        return orelse, body
    if isinstance(test, ast.BoolOp):
        parts = [_hasattr_branches(v) for v in test.values]
        if isinstance(test.op, ast.And):
            return frozenset().union(*[p[0] for p in parts]), empty
        return empty, frozenset().union(*[p[1] for p in parts])
    return empty, empty


def tracked_calls(source: str, methods: Set[str]) -> List[Call]:
    """Every attribute call to one of `methods`, with its guard context."""
    tree = ast.parse(source)
    found: List[Call] = []

    def visit(node, narrow, has):
        if isinstance(node, ast.Try) or type(node).__name__ == "TryStar":
            is_narrow = (len(node.body) == 1
                         and isinstance(node.body[0], _SIMPLE_STMTS))
            names = frozenset().union(*[_handler_names(h) for h in node.handlers]) \
                if node.handlers else frozenset()
            inner = narrow + (names,) if is_narrow and names else narrow
            for child in node.body:
                visit(child, inner, has)
            for child in node.handlers + node.orelse + node.finalbody:
                visit(child, narrow, has)
            return
        if isinstance(node, ast.If):
            visit(node.test, narrow, has)
            proven_body, proven_else = _hasattr_branches(node.test)
            for child in node.body:
                visit(child, narrow, has | proven_body)
            for child in node.orelse:
                visit(child, narrow, has | proven_else)
            return
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in methods):
            found.append(Call(
                node.func.attr,
                {k.arg for k in node.keywords if k.arg},
                sum(1 for a in node.args if not isinstance(a, ast.Starred)),
                node.lineno, narrow, frozenset(has)))
        for child in ast.iter_child_nodes(node):
            visit(child, narrow, has)

    visit(tree, (), frozenset())
    return found


def uses(call: Call, change: ApiChange) -> bool:
    if call.method != change.method:
        return False
    if change.keyword is None:
        return True
    return change.keyword in call.keywords or (
        change.position is not None and call.positional > change.position)


def guarded(call: Call, change: ApiChange) -> bool:
    wanted = {"TypeError"} if change.keyword else {"AttributeError"}
    wanted |= _BROAD | {"<bare>"}
    if any(names & wanted for names in call.narrow_catches):
        return True
    return change.keyword is None and change.method in call.hasattr_names


def required(change: ApiChange) -> Tuple[str, str]:
    """(floor that satisfies it, how to describe where it first ships)."""
    if change.first_version is None:
        return (UNTAGGED_SATISFIED_BY,
                f"core main only, in no tagged release ({change.note})")
    enforceable = modgate.REPORTED_AS.get(change.first_version, change.first_version)
    return enforceable, f"core {change.first_version}"


def _signature(change: ApiChange) -> str:
    return (f"{change.method}({change.keyword}=)" if change.keyword
            else f"{change.method}()")


def check_plugin(plugin_dir: Path, seen: Optional[Dict[str, int]] = None) -> List[str]:
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

    floor = modgate.effective_floor(manifest)
    methods = {c.method for c in API_FIRST_VERSION}
    parsed = []
    local_defs: Set[str] = set()
    for path in modgate.runtime_files(plugin_dir):
        rel = path.relative_to(plugin_dir).as_posix()
        source = path.read_text(encoding="utf-8", errors="replace")
        try:
            calls = tracked_calls(source, methods)
            local_defs |= {n.name for n in ast.walk(ast.parse(source))
                           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        except SyntaxError as exc:
            print(f"  ! {pid}/{rel}: not parseable, skipped ({exc.msg})",
                  file=sys.stderr)
            continue
        parsed.append((rel, calls))

    problems: List[str] = []
    for rel, calls in parsed:
        for call in calls:
            if seen is not None:
                seen[call.method] = seen.get(call.method, 0) + 1
            for change in API_FIRST_VERSION:
                if not uses(call, change) or guarded(call, change):
                    continue
                if change.keyword is None and change.method in local_defs:
                    continue  # the plugin's own method of that name
                need, where = required(change)
                if modgate.parse_version(need) <= floor:
                    continue
                problems.append(
                    f"{pid}/{rel}:{call.lineno}: calls {_signature(change)}, "
                    f"which ships in {where}, but the manifest admits "
                    f"{modgate.fmt(floor)}. On an older core this raises "
                    f"{'TypeError' if change.keyword else 'AttributeError'}. "
                    f"Raise the floor to >= {need} (ledmatrix_min_version / "
                    f"compatible_versions), or wrap just this call in a try "
                    f"with a fallback.")
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
        for pid in sorted(set(args.plugin_ids) - {d.name for d in dirs}):
            print(f"  ! {pid}: no plugins/{pid}/manifest.json, skipped",
                  file=sys.stderr)
    else:
        dirs = sorted(p for p in PLUGINS.iterdir()
                      if (p / "manifest.json").is_file())
    if not dirs:
        print("SKIP: no plugin manifests to check", file=sys.stderr)
        return 2

    seen: Dict[str, int] = {}
    problems = [p for d in dirs for p in check_plugin(d, seen)]

    # Plausibility: set_scrolling_state is called by every scrolling plugin.
    # A whole-tree scan that saw none is not looking, and must not say PASS.
    if not args.plugin_ids and not seen:
        print("SKIP: scanned the whole tree but saw no call to any tracked "
              "method; the scan is broken, not clean.", file=sys.stderr)
        return 2

    if not problems:
        print(f"PASS: {len(dirs)} plugin(s), {sum(seen.values())} call(s) to "
              f"tracked core methods; none needs a newer core than its "
              f"manifest admits.")
        return 0
    for problem in problems:
        print(f"  - {problem}", file=sys.stderr)
    print(f"\nFAIL: {len(problems)} call(s) need a newer core than the "
          f"manifest admits.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
