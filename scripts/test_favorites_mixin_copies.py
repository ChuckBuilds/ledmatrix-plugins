#!/usr/bin/env python3
"""Keep the favourite-matching copies gone: they live in core.

LEDMatrix core 3.8.2 ships ``src.common.sports_favorites`` -- the bodies the
nine scoreboards' copies were reconciled to (sports family 6):
``SportsFavoritesMixin`` (``SportsCore._is_favorite_game`` and
``_favorite_code``), ``SportsUpcomingFavoritesMixin``
(``_select_games_for_display``) and ``SportsRecentFavoritesMixin``
(``_select_recent_games_for_display``). Each plugin floors on 3.8.2, inherits
the three and deleted its copies. Each side of a game is named by
``_favorite_key`` (core's ``SportsHelpersMixin``: the abbreviation); nrl keeps
its override, the ESPN team id, because its abbreviations are not unique. A
copy that comes back is dead weight at best; at worst it is a fix made on one
side only, overriding core's without anyone noticing. So, for every
scoreboard:

1. No runtime file (tests excluded) defines one of the four methods, on any
   class or at module level.
2. ``sports.py`` imports the three mixins from core plainly -- a ``try``
   around it can only hide which module was missing -- and each class lists
   its mixin in ``BASES`` order: ``SportsCore`` before
   ``SportsCoreSharedMixin`` (whose ``_favorites_first`` calls
   ``_is_favorite_game``) and ``SportsHelpersMixin``; ``SportsUpcoming`` and
   ``SportsRecent`` first.
3. Only nrl overrides ``_favorite_key``, on ``SportsCore``. What it returns
   (the side's ESPN team id as a string, None when the id is missing) is
   pinned by ``scripts/test_favourite_matching.py`` on the real managers.
4. With a core checkout, each mixin defines exactly the names listed here.

Self-check: planted sources must fail each of the checks above, so a broken
finder cannot report success.

Exit: 0 clean, 1 failure. The core comparison is skipped (with a note), never
failed, when no core checkout ships the module.

Run: python scripts/test_favorites_mixin_copies.py
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLUGINS = REPO / "plugins"

SPORTS = ("afl", "baseball", "basketball", "football", "hockey", "lacrosse", "nrl", "soccer", "ufc")
MODULE = "src.common.sports_favorites"

#: mixin -> the methods it carries (and nothing else).
METHODS = {
    "SportsFavoritesMixin": ("_favorite_code", "_is_favorite_game"),
    "SportsUpcomingFavoritesMixin": ("_select_games_for_display",),
    "SportsRecentFavoritesMixin": ("_select_recent_games_for_display",),
}

#: plugin class -> its bases in order, from the mixin on (others may sit between).
BASES = {
    "SportsCore": ("SportsFavoritesMixin", "SportsCoreSharedMixin", "SportsHelpersMixin"),
    "SportsUpcoming": ("SportsUpcomingFavoritesMixin", "SportsCore"),
    "SportsRecent": ("SportsRecentFavoritesMixin", "SportsRecentSharedMixin", "SportsCore"),
}

#: The sports that name a team by something other than its abbreviation.
OVERRIDES_FAVORITE_KEY = {"nrl"}

_ALL_METHODS = {m for names in METHODS.values() for m in names}
_CATCHES_IMPORT_ERROR = {"ImportError", "ModuleNotFoundError", "Exception", "BaseException"}


def _catches_import_error(handler: ast.ExceptHandler) -> bool:
    kind = handler.type
    if kind is None:
        return True
    names = kind.elts if isinstance(kind, ast.Tuple) else [kind]
    return any(isinstance(n, ast.Name) and n.id in _CATCHES_IMPORT_ERROR for n in names)


def _defs(body, names):
    return [n for n in body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]


def copies(source: str) -> list[str]:
    """Where one of the four methods is defined again."""
    tree = ast.parse(source)
    found = [f"module-level {n.name}" for n in _defs(tree.body, _ALL_METHODS)]
    for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
        found += [f"{cls.name}.{n.name} is back -- {MODULE} ships it; delete the copy"
                  for n in _defs(cls.body, _ALL_METHODS)]
    return found


def key_overrides(source: str) -> list[str]:
    """Every class in the file that defines ``_favorite_key``."""
    return [cls.name for cls in ast.walk(ast.parse(source)) if isinstance(cls, ast.ClassDef)
            and _defs(cls.body, {"_favorite_key"})]


def adoption_problems(source: str) -> list[str]:
    """``sports.py``: a plain import of the three mixins and each base in order."""
    tree = ast.parse(source)
    problems = []
    imports = [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == MODULE]
    imported = {a.name for n in imports for a in n.names if a.asname is None}
    problems += [f"does not import {m} from {MODULE}" for m in METHODS if m not in imported]
    guarded = {n.lineno for t in ast.walk(tree)
               if isinstance(t, ast.Try) and any(_catches_import_error(h) for h in t.handlers)
               for stmt in t.body for n in ast.walk(stmt) if hasattr(n, "lineno")}
    problems += [f"line {n.lineno}: the {MODULE} import is inside a try"
                 for n in imports if n.lineno in guarded]
    classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
    for name, want in BASES.items():
        if name not in classes:
            problems.append(f"no class {name}")
            continue
        bases = [b.id for b in classes[name].bases if isinstance(b, ast.Name)]
        missing = [b for b in want if b not in bases]
        if missing:
            problems.append(f"{name} does not inherit {', '.join(missing)}")
        elif [b for b in bases if b in want] != list(want):
            problems.append(f"{name} lists its bases as {bases}; expected {' before '.join(want)}")
        elif name != "SportsCore" and bases[0] != want[0]:
            problems.append(f"{name} does not list {want[0]} first")
    return problems


def key_problems(source: str) -> list[str]:
    """nrl's ``SportsCore._favorite_key`` override is still there.

    Its answers are pinned by ``scripts/test_favourite_matching.py``, which
    calls it on the real managers; this guard only checks it was not dropped.
    """
    tree = ast.parse(source)
    core = next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "SportsCore"), None)
    if not (core and _defs(core.body, {"_favorite_key"})):
        return ["SportsCore._favorite_key is gone: nrl matches favourites by team id, "
                "not by its non-unique abbreviations"]
    return []


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
        source = target.read_text(encoding="utf-8")
        failures += [f"{sport} sports.py: {p}" for p in adoption_problems(source)]
        if sport in OVERRIDES_FAVORITE_KEY:
            failures += [f"{sport} sports.py: {p}" for p in key_problems(source)]
        for path in runtime_files(plugin):
            text = path.read_text(encoding="utf-8")
            where = f"{sport} {path.relative_to(plugin)}"
            failures += [f"{where}: {w}" for w in copies(text)]
            failures += [f"{where}: {cls} overrides _favorite_key; only nrl's SportsCore does"
                         for cls in key_overrides(text)
                         if not (sport in OVERRIDES_FAVORITE_KEY and path == target and cls == "SportsCore")]
    return failures


def find_core() -> Path | None:
    for candidate in (os.environ.get("LEDMATRIX_CORE", ""), str(REPO.parent / "LEDMatrix")):
        if candidate and (Path(candidate) / "src" / "plugin_system").is_dir():
            return Path(candidate)
    return None


def check_core(core: Path) -> list[str]:
    """Each of core's mixins defines exactly the methods listed in METHODS."""
    path = core / (MODULE.replace(".", "/") + ".py")
    if not path.is_file():
        return []  # a core older than 3.8.2: nothing to compare
    tree = ast.parse(path.read_text(encoding="utf-8"))
    failures = []
    for mixin, want in METHODS.items():
        cls = next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == mixin), None)
        if cls is None:
            failures.append(f"{MODULE}: no {mixin}")
            continue
        names = {n.name for n in cls.body if isinstance(n, ast.FunctionDef)}
        names |= {n.target.id for n in cls.body
                  if isinstance(n, ast.AnnAssign) and n.value is not None}
        if names != set(want):
            failures.append(f"{MODULE}: {mixin} defines {sorted(names)}, expected {sorted(want)}")
    return failures


GOOD = ("from src.common.sports_favorites import (\n"
        "    SportsFavoritesMixin,\n    SportsRecentFavoritesMixin,\n    SportsUpcomingFavoritesMixin,\n)\n"
        "class SportsCore(SportsFetchMixin, SportsFavoritesMixin, SportsCoreSharedMixin,\n"
        "                 SportsHelpersMixin, ABC):\n"
        "    def _favorite_key(self, game: Dict, side: str) -> Optional[str]:\n"
        "        team_id = game.get(f\"{side}_id\")\n"
        "        return None if team_id is None else str(team_id)\n"
        "class SportsUpcoming(SportsUpcomingFavoritesMixin, SportsCore):\n    pass\n"
        "class SportsRecent(SportsRecentFavoritesMixin, SportsRecentSharedMixin, SportsCore):\n    pass\n")


def self_check() -> list[str]:
    failures = []
    planted = ("def _is_favorite_game(game):\n    pass\n"
               "class SportsCore:\n    @staticmethod\n    def _favorite_code(value):\n        return value\n"
               "class SportsLive:\n    def _is_favorite_game(self, game):\n        return False\n"
               "class SportsUpcoming:\n    def _select_games_for_display(self, g, f):\n        return g\n"
               "class SportsRecent:\n    def _select_recent_games_for_display(self, g, f):\n        return g\n")
    if len(copies(planted)) != 5:
        failures.append("self-check: planted copies were not all found")
    if adoption_problems(GOOD) or key_problems(GOOD):
        failures.append(f"self-check: a correct adoption was flagged: "
                        f"{adoption_problems(GOOD) + key_problems(GOOD)}")
    for label, source, expect in (
            ("a guarded import", "try:\n    " + GOOD.replace("\n    Sports", " Sports", 3)
             .replace(",\n)\n", ")\nexcept ImportError:\n    SportsFavoritesMixin = object\n", 1),
             "inside a try"),
            ("an aliased import", GOOD.replace("    SportsRecentFavoritesMixin,",
                                               "    SportsRecentFavoritesMixin as Recent,"),
             "does not import SportsRecentFavoritesMixin"),
            ("a missing base", GOOD.replace("SportsFetchMixin, SportsFavoritesMixin, ", "SportsFetchMixin, "),
             "SportsCore does not inherit SportsFavoritesMixin"),
            ("the base after the shared mixin",
             GOOD.replace("SportsFavoritesMixin, SportsCoreSharedMixin,", "SportsCoreSharedMixin, SportsFavoritesMixin,"),
             "SportsCore lists its bases"),
            ("the base after SportsHelpersMixin",
             GOOD.replace("SportsFavoritesMixin, SportsCoreSharedMixin,\n                 SportsHelpersMixin,",
                          "SportsCoreSharedMixin,\n                 SportsHelpersMixin, SportsFavoritesMixin,"),
             "SportsCore lists its bases"),
            ("an Upcoming base after SportsCore",
             GOOD.replace("SportsUpcoming(SportsUpcomingFavoritesMixin, SportsCore)",
                          "SportsUpcoming(SportsCore, SportsUpcomingFavoritesMixin)"),
             "SportsUpcoming lists its bases"),
            ("a Recent base not first",
             GOOD.replace("SportsRecent(SportsRecentFavoritesMixin,", "SportsRecent(SportsBase, SportsRecentFavoritesMixin,"),
             "SportsRecent does not list SportsRecentFavoritesMixin first"),
            ("a missing Recent base", GOOD.replace("SportsRecent(SportsRecentFavoritesMixin, ", "SportsRecent("),
             "SportsRecent does not inherit SportsRecentFavoritesMixin")):
        if not any(expect in p for p in adoption_problems(source)):
            failures.append(f"self-check: {label} was not flagged")
    for label, source, expect in (
            ("nrl's override gone", GOOD.replace("_favorite_key", "_other_key"), "is gone"),):
        if not any(expect in p for p in key_problems(source)):
            failures.append(f"self-check: {label} was not flagged")
    if key_overrides(GOOD) != ["SportsCore"]:
        failures.append("self-check: a _favorite_key override was not found")
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
    print(f"  [pass] no favourite-matching copy is back in {len(SPORTS)} scoreboards; "
          f"all inherit core's {', '.join(METHODS)}; only nrl overrides _favorite_key")
    return 0


if __name__ == "__main__":
    sys.exit(main())
