#!/usr/bin/env python3
"""Keep the rankings copies gone: they live in core.

LEDMatrix core 3.8.5 ships ``src.common.sports_rankings`` -- the bodies the
nine scoreboards' copies were reconciled to (sports family 8):
``SportsRankingsMixin`` (``_fetch_team_rankings``, ``_choose_poll``,
``_poll_season_ended``, ``_load_division_team_ids``, ``_ranked_positions``,
``_is_ranked_game``, ``_best_rank``, ``_passes_other_filters`` and the class
constants ``_NON_TOP_POLL_TYPES``, ``_NON_TOP_POLL_NAMES``,
``_DIVISION_GROUPS_BY_LEAGUE``, ``_DIVISION_CACHE_TTL``,
``_DIVISION_RETRY_SECONDS``) and ``choose_top_division_poll()``, which the
dynamic team resolvers call. Each plugin floors on 3.8.5, inherits the mixin on
``SportsCore`` and deleted its copies. A copy that comes back is dead weight at
best; at worst it is a fix made on one side only, overriding core's without
anyone noticing. So, for every scoreboard:

1. No runtime file (tests excluded) defines one of the eight methods or five
   constants, on any class or at module level, or ``choose_top_division_poll``.
2. Every import from ``src.common.sports_rankings`` is plain -- not aliased,
   and not inside a ``try`` that catches ImportError, which can only hide which
   module was missing.
3. ``sports.py`` imports ``SportsRankingsMixin`` and ``SportsCore`` lists it
   after ``SportsRotationMixin`` (whose ``_by_importance`` reads ``_best_rank``
   and whose ``_rankings_loaded`` it reads) and before ``SportsCoreSharedMixin``
   (which calls it) and ``SportsHelpersMixin``.
4. With a core checkout, the mixin defines exactly the eight methods and five
   constants, and the module ``choose_top_division_poll``.

What the methods answer is pinned by ``scripts/test_rankings.py`` and
``scripts/test_poll_choice.py`` on the real managers; this guard is structural
only.

Self-check: planted sources must fail each of the checks above, so a broken
finder cannot report success.

Exit: 0 clean, 1 failure. The core comparison is skipped (with a note), never
failed, when no core checkout ships the module.

Run: python scripts/test_rankings_mixin_copies.py
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLUGINS = REPO / "plugins"

SPORTS = ("afl", "baseball", "basketball", "football", "hockey", "lacrosse", "nrl", "soccer", "ufc")
MODULE = "src.common.sports_rankings"
MIXIN = "SportsRankingsMixin"
CHOOSER = "choose_top_division_poll"
METHODS = ("_fetch_team_rankings", "_choose_poll", "_poll_season_ended", "_load_division_team_ids",
           "_ranked_positions", "_is_ranked_game", "_best_rank", "_passes_other_filters")
CONSTANTS = ("_NON_TOP_POLL_TYPES", "_NON_TOP_POLL_NAMES", "_DIVISION_GROUPS_BY_LEAGUE",
             "_DIVISION_CACHE_TTL", "_DIVISION_RETRY_SECONDS")
NAMES = set(METHODS) | set(CONSTANTS)

#: SportsCore's bases in order, from SportsRotationMixin on (others may sit between).
BASES = ("SportsRotationMixin", MIXIN, "SportsCoreSharedMixin", "SportsHelpersMixin")

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
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            found.append(n.target.id)
    return found


def copies(source: str) -> list[str]:
    """Where one of the eight methods or five constants is defined again."""
    tree = ast.parse(source)
    found = [f"module-level {n} is back -- {MODULE} ships it; delete the copy"
             for n in _defined(tree.body) if n in NAMES | {CHOOSER}]
    for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
        found += [f"{cls.name}.{n} is back -- {MODULE} ships it; delete the copy"
                  for n in _defined(cls.body) if n in NAMES]
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
    """``sports.py``: imports the mixin and lists it among SportsCore's bases, in order."""
    tree = ast.parse(source)
    problems = []
    if not any(a.name == MIXIN for n in ast.walk(tree)
               if isinstance(n, ast.ImportFrom) and n.module == MODULE for a in n.names):
        problems.append(f"does not import {MIXIN} from {MODULE}")
    core = next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "SportsCore"), None)
    if core is None:
        return problems + ["no class SportsCore"]
    bases = [b.id for b in core.bases if isinstance(b, ast.Name)]
    missing = [b for b in BASES if b not in bases]
    if missing:
        problems.append(f"SportsCore does not inherit {', '.join(missing)}")
    elif [b for b in bases if b in BASES] != list(BASES):
        problems.append(f"SportsCore lists its bases as {bases}; expected {' before '.join(BASES)}")
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
            failures += [f"{sport} {path.relative_to(plugin)}: {w}"
                         for w in copies(source) + import_problems(source)]
    return failures


def find_core() -> Path | None:
    for candidate in (os.environ.get("LEDMATRIX_CORE", ""), str(REPO.parent / "LEDMatrix")):
        if candidate and (Path(candidate) / "src" / "plugin_system").is_dir():
            return Path(candidate)
    return None


def check_core(core: Path) -> list[str]:
    """Core's mixin defines exactly METHODS and CONSTANTS; the module, the chooser."""
    path = core / (MODULE.replace(".", "/") + ".py")
    if not path.is_file():
        return []  # a core older than 3.8.5: nothing to compare
    tree = ast.parse(path.read_text(encoding="utf-8"))
    failures = [] if CHOOSER in _defined(tree.body) else [f"{MODULE}: no {CHOOSER}"]
    cls = next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == MIXIN), None)
    if cls is None:
        return failures + [f"{MODULE}: no {MIXIN}"]
    names = {n.name for n in cls.body if isinstance(n, ast.FunctionDef)}
    names |= {n.target.id for n in cls.body if isinstance(n, ast.AnnAssign) and n.value is not None}
    names |= {t.id for n in cls.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
    if names != NAMES:
        failures.append(f"{MODULE}: {MIXIN} defines {sorted(names)}, expected {sorted(NAMES)}")
    return failures


GOOD = ("from src.common.sports_rankings import SportsRankingsMixin\n"
        "class SportsCore(SportsFetchMixin, SportsFavoritesMixin, SportsRotationMixin,\n"
        "                 SportsRankingsMixin, SportsCoreSharedMixin, SportsHelpersMixin, ABC):\n"
        "    def _rankings_loaded(self) -> bool:\n"
        "        return True\n")


def self_check() -> list[str]:
    failures = []
    planted = ("def choose_top_division_poll(data):\n    return {}\n"
               "_DIVISION_CACHE_TTL = 1\n"
               "class SportsCore:\n    def _fetch_team_rankings(self):\n        return {}\n"
               "    _NON_TOP_POLL_TYPES: frozenset = frozenset()\n"
               "    _NON_TOP_POLL_NAMES = ()\n"
               "class SportsLive:\n    @staticmethod\n    def _poll_season_ended(poll, now):\n        return False\n"
               "class DynamicTeamResolver:\n    def _choose_poll(self, data):\n        return {}\n")
    if len(copies(planted)) != 7:
        failures.append(f"self-check: planted copies were not all found: {copies(planted)}")
    if copies(GOOD) or import_problems(GOOD) or adoption_problems(GOOD):
        failures.append("self-check: a correct adoption was flagged: "
                        f"{copies(GOOD) + import_problems(GOOD) + adoption_problems(GOOD)}")
    for label, source, expect in (
            ("a guarded import",
             "try:\n    " + GOOD.replace("\nclass", "\nexcept ImportError:\n    SportsRankingsMixin = object\nclass", 1),
             "inside a try"),
            ("an aliased import", GOOD.replace("import SportsRankingsMixin", "import SportsRankingsMixin as R"),
             "as R"),
            ("a guarded chooser import",
             "try:\n    from src.common.sports_rankings import choose_top_division_poll\n"
             "except Exception:\n    pass\n", "inside a try")):
        if not any(expect in p for p in import_problems(source)):
            failures.append(f"self-check: {label} was not flagged")
    for label, source, expect in (
            ("a missing import", GOOD.replace("import SportsRankingsMixin", "import Other"),
             f"does not import {MIXIN}"),
            ("a missing base", GOOD.replace("SportsRankingsMixin, SportsCoreSharedMixin", "SportsCoreSharedMixin"),
             f"SportsCore does not inherit {MIXIN}"),
            ("the base before the rotation mixin",
             GOOD.replace("SportsRotationMixin,\n                 SportsRankingsMixin,",
                          "SportsRankingsMixin,\n                 SportsRotationMixin,"),
             "SportsCore lists its bases"),
            ("the base after the shared mixin",
             GOOD.replace("SportsRankingsMixin, SportsCoreSharedMixin,", "SportsCoreSharedMixin, SportsRankingsMixin,"),
             "SportsCore lists its bases")):
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
    print(f"  [pass] no rankings copy is back in {len(SPORTS)} scoreboards; "
          f"all inherit core's {MIXIN}, after SportsRotationMixin")
    return 0


if __name__ == "__main__":
    sys.exit(main())
