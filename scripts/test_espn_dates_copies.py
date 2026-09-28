#!/usr/bin/env python3
"""Keep the scoreboards on the ESPN date-range helper, and any copy whole.

Since 2026-09-15 ESPN answers scoreboard ``dates=YYYYMMDD-YYYYMMDD`` queries
with ``400 Bad Request`` for every sport, and ``limit`` above 500 silently
truncates. The fix lives in LEDMatrix core as ``src/common/espn_dates.py``,
first released in core v3.5.0. The scoreboards used to bundle a copy as
``<sport>_espn_dates.py`` for older cores; the ones in ``SUNSET_PLUGINS``
floor on 3.5.0 and have deleted it. ufc still bundles one.

Three things decay without a check, so this guard checks all three:

1. **A sunset plugin grows its fallback back.** For each id in
   ``SUNSET_PLUGINS``: ``<sport>_espn_dates.py`` must be absent, no runtime
   module may import a ``*_espn_dates`` bare name, every
   ``src.common.espn_dates`` import must be unguarded (a ``try`` around it can
   only hide which module was missing -- there is nothing left to fall back
   to), and at least one module must import it (else the finder is blind).
   The same shape as ``check_scroll_adoption.py``'s sunset check.
2. **A remaining copy drifts.** A fix made in one copy and not the others is
   exactly what CLAUDE.md non-negotiable #7 forbids. Every bundled copy must
   match every other (ignoring its three-line header comment) and, when a core
   checkout that ships the module is available, behave as core's does:
   compared as an AST with type annotations, ``typing`` imports and
   ``cast(T, x)`` wrappers removed, since core's typing-only edits (a mypy
   ratchet, core #661) change no behaviour.
3. **A new fetch bypasses the helper.** A ``session.get`` / ``requests.get``
   that sends ``dates`` goes straight to ESPN, so a range 400s again. Every
   such call in a scoreboard's shipped code fails this check; route it through
   ``fetch_espn_scoreboard``. "Sends ``dates``" means any of:

   - ``params={"dates": ...}`` or ``params=dict(..., dates=...)``;
   - ``params=<name>`` where that name, in the same function (or at module
     level), is built with a ``"dates"`` key: a dict literal, ``dict(dates=)``,
     ``name["dates"] = ...``, ``name.update(...)`` or ``name.setdefault(...)``;
   - a URL (the first argument or ``url=``) with ``dates=`` in a string part,
     directly or through a name assigned such a string.

   Not seen: a params dict handed in as a function argument by a caller, or
   built in another module. A bundled helper itself is not scanned -- it is
   the one place allowed to send ``dates``, and the copy check above pins it.

Self-check: the scanner must flag each planted bypass shape and pass each
planted legitimate call, and the guard finder must flag a planted guarded
import, so a broken finder cannot report success.

Exit: 0 clean, 1 failure. The core comparison is skipped (with a note), never
failed, when no core checkout or no ``src/common/espn_dates.py`` is found.

Run: python scripts/test_espn_dates_copies.py
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLUGINS = REPO / "plugins"
SPORTS = ("afl", "baseball", "basketball", "football", "hockey",
          "lacrosse", "nrl", "soccer", "ufc")
CORE_MODULE = "src.common.espn_dates"

#: Scoreboards that completed the espn_dates sunset: bundled copy deleted,
#: core import unguarded, manifest floored at 3.5.0 (the first core release
#: that ships the module). Listed, not inferred, as in check_scroll_adoption:
#: adding an id is the moment somebody states the sunset holds for it.
SUNSET_PLUGINS = frozenset({
    "afl-scoreboard",
    "baseball-scoreboard",
    "basketball-scoreboard",
    "football-scoreboard",
    "hockey-scoreboard",
    "lacrosse-scoreboard",
    "nrl-scoreboard",
    "soccer-scoreboard",
})
HEADER_LINES = 3

_CATCHES_IMPORT_ERROR = {"ImportError", "ModuleNotFoundError", "Exception", "BaseException"}


def body_of(path: Path) -> str:
    """A bundled copy minus its header comment, with line endings normalised."""
    lines = path.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")
    header = lines[:HEADER_LINES]
    if not all(line.startswith("#") for line in header):
        raise ValueError(f"{path}: expected a {HEADER_LINES}-line '#' header naming the core module")
    return "\n".join(lines[HEADER_LINES:])


class _Untyped(ast.NodeTransformer):
    """Drop what only a type checker reads: annotations, typing imports, cast()."""

    def visit_ImportFrom(self, node):
        return None if node.module == "typing" else node

    def visit_arg(self, node):
        node.annotation = None
        return node

    def _func(self, node):
        node.returns = None
        self.generic_visit(node)
        return node

    visit_FunctionDef = visit_AsyncFunctionDef = _func

    def visit_AnnAssign(self, node):
        self.generic_visit(node)
        if node.value is None:
            return None
        return ast.copy_location(ast.Assign(targets=[node.target], value=node.value), node)

    def visit_Call(self, node):
        self.generic_visit(node)
        if isinstance(node.func, ast.Name) and node.func.id == "cast" and len(node.args) == 2:
            return node.args[1]
        return node


def behaviour_of(source: str) -> str:
    """An AST dump that two type-annotation variants of one module share."""
    tree = _Untyped().visit(ast.parse(source))
    return ast.dump(ast.fix_missing_locations(tree), include_attributes=False)


def find_core() -> Path | None:
    for candidate in (os.environ.get("LEDMATRIX_CORE", ""), str(REPO.parent / "LEDMatrix")):
        if candidate and (Path(candidate) / "src" / "plugin_system").is_dir():
            return Path(candidate)
    return None


def _catches_import_error(handler: ast.ExceptHandler) -> bool:
    kind = handler.type
    if kind is None:
        return True
    names = kind.elts if isinstance(kind, ast.Tuple) else [kind]
    return any(isinstance(n, ast.Name) and n.id in _CATCHES_IMPORT_ERROR for n in names)


def espn_imports(source: str, filename: str) -> list[tuple[int, str, bool]]:
    """(line, module, guarded) for each import of the core helper or a bundled copy."""
    tree = ast.parse(source, filename=filename)
    guarded_lines = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Try) and any(_catches_import_error(h) for h in node.handlers):
            for stmt in node.body:
                guarded_lines.update(n.lineno for n in ast.walk(stmt) if hasattr(n, "lineno"))
    found = []
    for node in ast.walk(tree):
        modules = []
        if isinstance(node, ast.ImportFrom) and node.module:
            modules = [node.module]
            if node.module == "src.common":
                modules += [f"src.common.{a.name}" for a in node.names]
        elif isinstance(node, ast.Import):
            modules = [a.name for a in node.names]
        for module in modules:
            if module == CORE_MODULE or module.endswith("_espn_dates"):
                found.append((node.lineno, module, node.lineno in guarded_lines))
    return found


def runtime_files(plugin: Path):
    for path in sorted(plugin.rglob("*.py")):
        relative = path.relative_to(plugin)
        if relative.parts[0] == "test" or path.name.startswith("test_"):
            continue
        yield path


_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def _scope_nodes(scope: ast.AST):
    """Nodes of ``scope`` itself, not descending into nested functions/classes."""
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, _SCOPES):
            stack.extend(ast.iter_child_nodes(node))


def _is_dates_key(node) -> bool:
    return isinstance(node, ast.Constant) and node.value == "dates"


def _has_dates_string(node) -> bool:
    return any(isinstance(n, ast.Constant) and isinstance(n.value, str)
               and "dates=" in n.value for n in ast.walk(node))


class _Scanner:
    """Resolve names within one file's scopes, then judge each ``.get`` call."""

    def __init__(self, tree: ast.AST):
        self.tree = tree
        self.parents = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                self.parents[child] = parent

    def _scopes_of(self, node):
        """Enclosing function scopes, innermost first, then the module."""
        scopes = []
        cur = self.parents.get(node)
        while cur is not None:
            if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                scopes.append(cur)
            cur = self.parents.get(cur)
        scopes.append(self.tree)
        return scopes

    def _name_info(self, name: str, at: ast.AST):
        """(values assigned to ``name``, whether ``dates`` is set on it in place).

        Looks in the innermost scope that binds or mutates the name.
        """
        for scope in self._scopes_of(at):
            values, mutated, bound = [], False, False
            for node in _scope_nodes(scope):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id == name:
                            values.append(node.value)
                            bound = True
                        elif (isinstance(target, ast.Subscript)
                              and isinstance(target.value, ast.Name)
                              and target.value.id == name and _is_dates_key(target.slice)):
                            mutated = True
                elif (isinstance(node, (ast.AnnAssign, ast.AugAssign, ast.NamedExpr))
                      and isinstance(node.target, ast.Name) and node.target.id == name
                      and node.value is not None):
                    values.append(node.value)
                    bound = True
                elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                      and isinstance(node.func.value, ast.Name) and node.func.value.id == name):
                    if (node.func.attr == "setdefault" and node.args
                            and _is_dates_key(node.args[0])):
                        mutated = True
                    elif node.func.attr == "update" and (
                            any(k.arg == "dates" for k in node.keywords)
                            or any(self.carries_dates(a, {name}) for a in node.args)):
                        mutated = True
            if bound or mutated:
                return values, mutated
        return [], False

    def carries_dates(self, node, seen: set) -> bool:
        """Does this ``params`` expression put a ``dates`` key in the request?"""
        if isinstance(node, ast.Dict):
            return (any(_is_dates_key(k) for k in node.keys)
                    or any(k is None and self.carries_dates(v, seen)
                           for k, v in zip(node.keys, node.values)))
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "dict"):
            return (any(k.arg == "dates"
                        or (k.arg is None and self.carries_dates(k.value, seen))
                        for k in node.keywords)
                    or any(self.carries_dates(a, seen) for a in node.args))
        if isinstance(node, ast.Name):
            if node.id in seen:
                return False
            values, mutated = self._name_info(node.id, node)
            return mutated or any(self.carries_dates(v, seen | {node.id}) for v in values)
        if isinstance(node, ast.BoolOp):
            return any(self.carries_dates(v, seen) for v in node.values)
        if isinstance(node, ast.IfExp):
            return self.carries_dates(node.body, seen) or self.carries_dates(node.orelse, seen)
        if isinstance(node, ast.BinOp):  # {...} | {...}
            return self.carries_dates(node.left, seen) or self.carries_dates(node.right, seen)
        return False

    def url_has_dates(self, node, seen: set) -> bool:
        """Does this URL expression carry a ``dates=`` query string?"""
        if _has_dates_string(node):
            return True
        for name in (n for n in ast.walk(node) if isinstance(n, ast.Name)):
            if name.id in seen:
                continue
            values, _ = self._name_info(name.id, name)
            if any(self.url_has_dates(v, seen | {name.id}) for v in values):
                return True
        return False

    def is_bypass(self, call: ast.Call) -> bool:
        if any(k.arg == "params" and self.carries_dates(k.value, set())
               for k in call.keywords):
            return True
        urls = call.args[:1] + [k.value for k in call.keywords if k.arg == "url"]
        return any(self.url_has_dates(url, set()) for url in urls)


def bypasses(source: str, filename: str) -> list[int]:
    """Line numbers of ``*.get(...)`` calls that send ESPN a ``dates`` value."""
    tree = ast.parse(source, filename=filename)
    scanner = _Scanner(tree)
    return sorted(node.lineno for node in ast.walk(tree)
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                  and node.func.attr == "get" and scanner.is_bypass(node))


#: (label, source, flagged lines). Every bypass shape must be caught and every
#: legitimate shape left alone; a scanner that gets either wrong is broken.
SELF_CHECKS = [
    ("params dict literal",
     'r = self.session.get(url, params={"dates": d, "limit": 1000}, timeout=5)\n', [1]),
    ("params variable built as a dict literal",
     'def f(self, d):\n'
     '    params = {"dates": d, "limit": 500}\n'
     '    return self.session.get(url, params=params, timeout=15)\n', [3]),
    ("params variable given dates by subscript",
     'def f(s, d):\n    params = {"limit": 5}\n    params["dates"] = d\n'
     '    return s.get(u, params=params)\n', [4]),
    ("params variable given dates by update()",
     'def f(s, d):\n    p = {}\n    p.update(dates=d)\n    return s.get(u, params=p)\n', [4]),
    ("params variable given dates by setdefault()",
     'def f(s, d):\n    p = {}\n    p.setdefault("dates", d)\n    return s.get(u, params=p)\n', [4]),
    ("params=dict(dates=...)",
     'requests.get(url, params=dict(dates=rng))\n', [1]),
    ("params variable built with dict(base, dates=...)",
     'def f(base, rng):\n    q = dict(base, dates=rng)\n    return requests.get(url, params=q)\n', [3]),
    ("dict spread of a dated dict",
     'def f(d):\n    base = {"dates": d}\n'
     '    return requests.get(url, params={**base, "limit": 5})\n', [3]),
    ("module-level params variable",
     'PARAMS = {"dates": "2026"}\ndef f(s):\n    return s.get(URL, params=PARAMS)\n', [3]),
    ("f-string URL with ?dates=",
     'requests.get(f"https://x/scoreboard?dates={a}-{b}")\n', [1]),
    ("URL variable built by concatenation",
     'def f(s, a):\n    url = BASE + "?dates=" + a\n    return s.get(url, timeout=5)\n', [3]),
    ("url= keyword with a query string",
     'requests.get(url="https://x/scoreboard?limit=5&dates=2026", timeout=5)\n', [1]),
    ("OK: dated params routed through fetch_espn_scoreboard",
     'def f(s, d):\n    params = {"dates": d}\n'
     '    return fetch_espn_scoreboard(s, url, params=params)\n', []),
    ("OK: a params variable without dates",
     'def f(s):\n    params = {"limit": 300}\n    return s.get(url, params=params)\n', []),
    ("OK: another function's dated params of the same name",
     'def a(d):\n    params = {"dates": d}\n    return fetch_espn_scoreboard(s, u, params=params)\n'
     'def b(s):\n    params = {"event": 1}\n    return s.get(u, params=params)\n', []),
    ("OK: reading a dates key with dict.get",
     'x = payload.get("dates", [])\n', []),
]


#: (label, source, expected [(module, guarded)]) for the import finder.
GUARD_SELF_CHECKS = [
    ("plain core import",
     "from src.common.espn_dates import fetch_espn_scoreboard\n",
     [(CORE_MODULE, False)]),
    ("the old guarded shape",
     "try:\n    from src.common.espn_dates import fetch_espn_scoreboard\n"
     "except ModuleNotFoundError as exc:\n    from afl_espn_dates import fetch_espn_scoreboard\n",
     [(CORE_MODULE, True), ("afl_espn_dates", False)]),
    ("a guard with nothing behind it",
     "try:\n    from src.common import espn_dates\nexcept ImportError:\n    pass\n",
     [(CORE_MODULE, True)]),
    ("a try that catches something else is not a guard",
     "try:\n    import src.common.espn_dates\nexcept KeyError:\n    pass\n",
     [(CORE_MODULE, False)]),
]


def sunset_violations(plugin: Path, sport: str) -> list[str]:
    problems = []
    copy = plugin / f"{sport}_espn_dates.py"
    if copy.exists():
        problems.append(f"{copy.relative_to(REPO)} is back; the sunset deleted it and the "
                        "manifest floor guarantees core ships src/common/espn_dates.py")
    adopted = False
    for path in runtime_files(plugin):
        for line, module, guarded in espn_imports(path.read_text(encoding="utf-8"), str(path)):
            where = f"{path.relative_to(REPO)}:{line}"
            if module != CORE_MODULE:
                problems.append(f"{where} imports the bundled {module}; import {CORE_MODULE}")
            elif guarded:
                problems.append(f"{where} guards the {CORE_MODULE} import again; with no "
                                "fallback left, catching only hides which module was missing")
            else:
                adopted = True
    if not adopted:
        problems.append(f"{plugin.name}: no runtime module imports {CORE_MODULE}; "
                        "the finder is not seeing it, or the helper was dropped")
    return problems


def main() -> int:
    failures: list[str] = []

    broken = []
    for label, source, want in SELF_CHECKS:
        got = bypasses(source, "<planted>")
        if got != want:
            broken.append(f"{label} (flagged lines {got}, expected {want})")
    for label, source, want in GUARD_SELF_CHECKS:
        got = [(module, guarded) for _line, module, guarded in espn_imports(source, "<planted>")]
        if got != want:
            broken.append(f"import finder: {label} (found {got}, expected {want})")
    if broken:
        for label in broken:
            print(f"FAIL: self-check -- the scanner is wrong on: {label}")
        return 1
    print(f"  ok: scanner self-check, {len(SELF_CHECKS) + len(GUARD_SELF_CHECKS)} planted shapes")

    sunset = [s for s in SPORTS if f"{s}-scoreboard" in SUNSET_PLUGINS]
    for sport in sunset:
        failures.extend(sunset_violations(PLUGINS / f"{sport}-scoreboard", sport))
    if not failures:
        print(f"  ok: {len(sunset)} sunset scoreboard(s) import {CORE_MODULE}, unguarded, "
              "with no bundled copy")

    copies = {}
    for sport in SPORTS:
        if sport in sunset:
            continue
        path = PLUGINS / f"{sport}-scoreboard" / f"{sport}_espn_dates.py"
        if not path.is_file():
            failures.append(f"missing {path.relative_to(REPO)} (not in SUNSET_PLUGINS, so it "
                            "still bundles the helper)")
            continue
        try:
            copies[sport] = body_of(path)
        except ValueError as exc:
            failures.append(str(exc))

    if copies:
        reference_sport, reference = next(iter(copies.items()))
        for sport, body in copies.items():
            if body != reference:
                failures.append(f"{sport}_espn_dates.py differs from {reference_sport}_espn_dates.py")

        core = find_core()
        core_module = core / "src" / "common" / "espn_dates.py" if core else None
        if core_module and core_module.is_file():
            core_body = core_module.read_text(encoding="utf-8").replace("\r\n", "\n")
            if behaviour_of(reference) != behaviour_of(core_body):
                failures.append(f"the bundled copies differ from {core_module} "
                                "(beyond type annotations)")
            else:
                exact = "byte-identical" if reference == core_body else "identical but for typing"
                print(f"  ok: bundled copies ({', '.join(copies)}) match {core_module}: {exact}")
        else:
            print("  note: no core checkout shipping src/common/espn_dates.py; "
                  "compared the copies with each other only")

    for sport in SPORTS:
        plugin = PLUGINS / f"{sport}-scoreboard"
        for path in runtime_files(plugin):
            if path.name == f"{sport}_espn_dates.py":
                continue  # the helper itself, pinned by the copy check above
            for line in bypasses(path.read_text(encoding="utf-8"), str(path)):
                failures.append(
                    f"{path.relative_to(REPO)}:{line} sends ESPN a dates param directly; "
                    "use fetch_espn_scoreboard so a rejected range is re-fetched in chunks"
                )

    if failures:
        for failure in failures:
            print("FAIL: " + failure)
        return 1
    print(f"OK: {len(sunset)} scoreboards on core's ESPN date helper, {len(copies)} bundled "
          "copy/copies intact, no direct dates fetches")
    return 0


if __name__ == "__main__":
    sys.exit(main())
