#!/usr/bin/env python3
"""Keep the live fetch and odds copies gone: they live in core.

LEDMatrix core 3.8.6 ships ``src.common.sports_live_fetch`` -- the bodies the
nine scoreboards' copies were reconciled to (sports family 9):
``SportsLiveFetchMixin`` (``_fetch_todays_games``, ``_fetch_odds`` and the odds
worker ``_drain_odds_queue``). Each plugin floors on 3.8.6, inherits the mixin
on ``SportsCore`` and deleted its copies. A copy that comes back is dead weight
at best; at worst it is a fix made on one side only, overriding core's without
anyone noticing. So, for every scoreboard:

1. No runtime file (tests excluded) defines one of the three methods, on any
   class or at module level -- except the league overrides of
   ``_fetch_todays_games`` in ``OVERRIDES`` (MiLB's and HockeyTech's own
   feeds, and UFC's live manager, which splits core's answer into bouts).
2. Every import from ``src.common.sports_live_fetch`` is plain -- not aliased,
   and not inside a ``try`` that catches ImportError, which can only hide which
   module was missing.
3. ``sports.py`` imports ``SportsLiveFetchMixin`` and ``SportsCore`` lists it
   among its bases. Where does not matter: no other base defines these names
   (core's module docstring, BASE ORDER).
4. With a core checkout, the mixin defines exactly the three methods and no
   class attribute with a value.

What the methods answer is pinned by ``scripts/test_live_fetch_odds.py`` on the
real managers; this guard is structural only.

Self-check: planted sources must fail each of the checks above, so a broken
finder cannot report success.

Exit: 0 clean, 1 failure. The core comparison is skipped (with a note), never
failed, when no core checkout ships the module.

Run: python scripts/test_live_fetch_mixin_copies.py
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLUGINS = REPO / "plugins"

SPORTS = ("afl", "baseball", "basketball", "football", "hockey", "lacrosse", "nrl", "soccer", "ufc")
MODULE = "src.common.sports_live_fetch"
MIXIN = "SportsLiveFetchMixin"
METHODS = {"_fetch_todays_games", "_fetch_odds", "_drain_odds_queue"}

#: League managers that keep their own _fetch_todays_games: (plugin, file, class).
OVERRIDES = {("baseball", "milb_managers.py", "BaseMiLBManager"),
             ("hockey", "hockeytech_managers.py", "BaseHockeyTechManager"),
             ("ufc", "mma.py", "MMALive")}

_CATCHES_IMPORT_ERROR = {"ImportError", "ModuleNotFoundError", "Exception", "BaseException"}


def _catches_import_error(handler: ast.ExceptHandler) -> bool:
    kind = handler.type
    if kind is None:
        return True
    names = kind.elts if isinstance(kind, ast.Tuple) else [kind]
    return any(isinstance(n, ast.Name) and n.id in _CATCHES_IMPORT_ERROR for n in names)


def _defined(body) -> list[str]:
    """The names a class or module body defines: functions and (annotated) assignments."""
    found = []
    for n in body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            found.append(n.name)
        elif isinstance(n, ast.Assign):
            found += [t.id for t in n.targets if isinstance(t, ast.Name)]
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.value is not None:
            found.append(n.target.id)
    return found


def copies(source: str, allowed: set[str] = frozenset()) -> list[str]:
    """Where one of the three methods is defined again (``allowed``: classes that may
    override ``_fetch_todays_games``)."""
    tree = ast.parse(source)
    found = [f"module-level {n} is back -- {MODULE} ships it; delete the copy"
             for n in _defined(tree.body) if n in METHODS]
    for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
        found += [f"{cls.name}.{n} is back -- {MODULE} ships it; delete the copy"
                  for n in _defined(cls.body)
                  if n in METHODS and not (n == "_fetch_todays_games" and cls.name in allowed)]
    return found


def import_problems(source: str) -> list[str]:
    """Every import from the module is plain: not aliased, not inside a try."""
    tree = ast.parse(source)
    imports = [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == MODULE]
    guarded = {n.lineno for t in ast.walk(tree)
               if isinstance(t, ast.Try) and any(_catches_import_error(h) for h in t.handlers)
               for stmt in t.body for n in ast.walk(stmt) if hasattr(n, "lineno")}
    problems = [f"line {n.lineno}: the {MODULE} import is inside a try"
                for n in imports if n.lineno in guarded]
    problems += [f"line {n.lineno}: {a.name} is imported from {MODULE} as {a.asname}"
                 for n in imports for a in n.names if a.asname]
    return problems


def adoption_problems(source: str) -> list[str]:
    """``sports.py``: imports the mixin and lists it among SportsCore's bases."""
    tree = ast.parse(source)
    problems = []
    if not any(a.name == MIXIN for n in ast.walk(tree)
               if isinstance(n, ast.ImportFrom) and n.module == MODULE for a in n.names):
        problems.append(f"does not import {MIXIN} from {MODULE}")
    core = next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "SportsCore"), None)
    if core is None:
        return problems + ["no class SportsCore"]
    if not any(isinstance(b, ast.Name) and b.id == MIXIN for b in core.bases):
        problems.append(f"SportsCore does not inherit {MIXIN}")
    return problems


def runtime_files(plugin: Path):
    for path in sorted(plugin.rglob("*.py")):
        relative = path.relative_to(plugin)
        if relative.parts[0] == "test" or path.name.startswith("test_"):
            continue
        yield path


def check_plugins() -> list[str]:
    failures = []
    for sport in SPORTS:
        plugin = PLUGINS / f"{sport}-scoreboard"
        target = plugin / "sports.py"
        if not target.is_file():
            failures.append(f"{sport}: sports.py is missing")
            continue
        failures += [f"{sport} sports.py: {p}" for p in adoption_problems(target.read_text(encoding="utf-8"))]
        for path in runtime_files(plugin):
            source = path.read_text(encoding="utf-8")
            allowed = {c for s, f, c in OVERRIDES if s == sport and f == path.name}
            failures += [f"{sport} {path.relative_to(plugin)}: {w}"
                         for w in copies(source, allowed) + import_problems(source)]
    return failures


def find_core() -> Path | None:
    for candidate in (os.environ.get("LEDMATRIX_CORE", ""), str(REPO.parent / "LEDMatrix")):
        if candidate and (Path(candidate) / "src" / "plugin_system").is_dir():
            return Path(candidate)
    return None


def check_core(core: Path) -> list[str]:
    """Core's mixin defines exactly METHODS and no valued class attribute."""
    path = core / (MODULE.replace(".", "/") + ".py")
    if not path.is_file():
        return []  # a core older than 3.8.6: nothing to compare
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == MIXIN), None)
    if cls is None:
        return [f"{MODULE}: no {MIXIN}"]
    names = set(_defined(cls.body))
    if names != METHODS:
        return [f"{MODULE}: {MIXIN} defines {sorted(names)}, expected {sorted(METHODS)}"]
    return []


GOOD = ("from src.common.sports_live_fetch import SportsLiveFetchMixin\n"
        "class SportsCore(SportsFetchMixin, SportsRankingsMixin, SportsLiveFetchMixin,\n"
        "                 SportsCoreSharedMixin, SportsHelpersMixin, ABC):\n"
        "    def _fetch_data(self):\n"
        "        return self._fetch_todays_games()\n")


def self_check() -> list[str]:
    failures = []
    planted = ("def _drain_odds_queue(self):\n    pass\n"
               "class SportsCore:\n    def _fetch_todays_games(self):\n        return {}\n"
               "    _fetch_odds = lambda self, game: None\n"
               "class SportsLive:\n    @staticmethod\n    def _drain_odds_queue():\n        pass\n"
               "class MMALive:\n    def _fetch_todays_games(self):\n        return {}\n")
    if len(copies(planted)) != 5:
        failures.append(f"self-check: planted copies were not all found: {copies(planted)}")
    if len(copies(planted, {"MMALive"})) != 4:
        failures.append("self-check: an allowed league override was flagged, or one too many let through")
    if copies(GOOD) or import_problems(GOOD) or adoption_problems(GOOD):
        failures.append("self-check: a correct adoption was flagged: "
                        f"{copies(GOOD) + import_problems(GOOD) + adoption_problems(GOOD)}")
    for label, source, expect in (
            ("a guarded import",
             "try:\n    " + GOOD.replace("\nclass", "\nexcept ImportError:\n    SportsLiveFetchMixin = object\nclass", 1),
             "inside a try"),
            ("an aliased import", GOOD.replace("import SportsLiveFetchMixin", "import SportsLiveFetchMixin as L"),
             "as L")):
        if not any(expect in p for p in import_problems(source)):
            failures.append(f"self-check: {label} was not flagged")
    for label, source, expect in (
            ("a missing import", GOOD.replace("import SportsLiveFetchMixin", "import Other"),
             f"does not import {MIXIN}"),
            ("a missing base", GOOD.replace(" SportsLiveFetchMixin,\n", "\n"),
             f"SportsCore does not inherit {MIXIN}")):
        if not any(expect in p for p in adoption_problems(source)):
            failures.append(f"self-check: {label} was not flagged")
    return failures


def main() -> int:
    failures = self_check() + check_plugins()
    core = find_core()
    if core is None:
        print("  [note] no LEDMatrix core checkout: the names are not compared with core")
    else:
        failures += check_core(core)
    for f in failures:
        print(f"  [FAIL] {f}")
    if failures:
        return 1
    print(f"  [pass] no live fetch or odds copy is back in {len(SPORTS)} scoreboards; "
          f"all inherit core's {MIXIN}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
