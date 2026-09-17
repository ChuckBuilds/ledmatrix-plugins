#!/usr/bin/env python3
"""Keep the scoreboards' bundled ESPN date-range helper whole and in use.

Since 2026-09-15 ESPN answers scoreboard ``dates=YYYYMMDD-YYYYMMDD`` queries
with ``400 Bad Request`` for every sport, and ``limit`` above 500 silently
truncates. The fix lives in LEDMatrix core as ``src/common/espn_dates.py``;
each of the nine scoreboards bundles a copy as ``<sport>_espn_dates.py`` so it
works on cores released before that module existed.

Two things decay without a check, so this guard checks both:

1. **The copies drift.** A fix made in one copy and not the others is exactly
   what CLAUDE.md non-negotiable #7 forbids. Every copy must match every other
   (ignoring its three-line header comment) and, when a core checkout that
   ships the module is available, match core's.
2. **A new fetch bypasses the helper.** A ``session.get`` / ``requests.get``
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
   built in another module. The bundled helper itself is not scanned -- it is
   the one place allowed to send ``dates``, and the copy check above pins it.

Self-check: the scanner must flag each planted bypass shape and pass each
planted legitimate call, so a broken finder cannot report success.

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
HEADER_LINES = 3


def body_of(path: Path) -> str:
    """A bundled copy minus its header comment, with line endings normalised."""
    lines = path.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")
    header = lines[:HEADER_LINES]
    if not all(line.startswith("#") for line in header):
        raise ValueError(f"{path}: expected a {HEADER_LINES}-line '#' header naming the core module")
    return "\n".join(lines[HEADER_LINES:])


def find_core() -> Path | None:
    for candidate in (os.environ.get("LEDMATRIX_CORE", ""), str(REPO.parent / "LEDMatrix")):
        if candidate and (Path(candidate) / "src" / "plugin_system").is_dir():
            return Path(candidate)
    return None


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


def main() -> int:
    failures: list[str] = []

    broken = []
    for label, source, want in SELF_CHECKS:
        got = bypasses(source, "<planted>")
        if got != want:
            broken.append(f"{label} (flagged lines {got}, expected {want})")
    if broken:
        for label in broken:
            print(f"FAIL: self-check -- the scanner is wrong on: {label}")
        return 1
    print(f"  ok: scanner self-check, {len(SELF_CHECKS)} planted shapes")

    copies = {}
    for sport in SPORTS:
        path = PLUGINS / f"{sport}-scoreboard" / f"{sport}_espn_dates.py"
        if not path.is_file():
            failures.append(f"missing {path.relative_to(REPO)}")
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
            if reference != core_body:
                failures.append(f"the bundled copies differ from {core_module}")
            else:
                print(f"  ok: bundled copies match {core_module}")
        else:
            print("  note: no core checkout shipping src/common/espn_dates.py; "
                  "compared the copies with each other only")

    for sport in SPORTS:
        plugin = PLUGINS / f"{sport}-scoreboard"
        for path in sorted(plugin.rglob("*.py")):
            relative = path.relative_to(plugin)
            if relative.parts[0] == "test" or path.name.startswith("test_"):
                continue
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
    print(f"OK: {len(copies)} bundled ESPN date helpers identical, no direct dates fetches")
    return 0


if __name__ == "__main__":
    sys.exit(main())
