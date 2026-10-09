#!/usr/bin/env python3
"""Keep the other-games rotation copies gone: they live in core.

LEDMatrix core 3.8.4 ships ``src.common.sports_rotation`` -- the bodies the
nine scoreboards' copies were reconciled to (sports family 7):
``SportsRotationMixin`` (``_by_importance``, ``_other_games_window``,
``_advance_other_games_if_due``, ``_rotate_other_games_on_display``,
``_attach_odds_to_rotated_games`` and the default ``_rankings_loaded``). Each
plugin floors on 3.8.4, inherits it on ``SportsCore`` and deleted its copies.
football keeps its ``_rankings_loaded`` override, which also counts its
rankings keyed by ESPN team id. A copy that comes back is dead weight at best;
at worst it is a fix made on one side only, overriding core's without anyone
noticing. So, for every scoreboard:

1. No runtime file (tests excluded) defines one of the six methods, on any
   class or at module level -- except football's ``SportsCore._rankings_loaded``,
   which must still be there.
2. ``sports.py`` imports ``SportsRotationMixin`` from core plainly -- a
   ``try`` around it can only hide which module was missing -- and
   ``SportsCore`` lists it before ``SportsCoreSharedMixin`` (whose
   ``_favorites_first`` and ``_compose_selection`` call it) and
   ``SportsHelpersMixin``.
3. With a core checkout, the mixin defines exactly the six methods.

What the methods answer is pinned by ``scripts/test_other_games_rotation.py``
on the real managers; this guard is structural only.

Self-check: planted sources must fail each of the checks above, so a broken
finder cannot report success.

Exit: 0 clean, 1 failure. The core comparison is skipped (with a note), never
failed, when no core checkout ships the module.

Run: python scripts/test_rotation_mixin_copies.py
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLUGINS = REPO / "plugins"

SPORTS = ("afl", "baseball", "basketball", "football", "hockey", "lacrosse", "nrl", "soccer", "ufc")
MODULE = "src.common.sports_rotation"
MIXIN = "SportsRotationMixin"
METHODS = ("_by_importance", "_other_games_window", "_advance_other_games_if_due",
           "_rotate_other_games_on_display", "_attach_odds_to_rotated_games", "_rankings_loaded")
SEAM = "_rankings_loaded"

#: SportsCore's bases in order, from the mixin on (others may sit between).
BASES = (MIXIN, "SportsCoreSharedMixin", "SportsHelpersMixin")

#: The sports whose SportsCore overrides the seam (owner's decision, family 7).
OVERRIDES_SEAM = {"football"}

_CATCHES_IMPORT_ERROR = {"ImportError", "ModuleNotFoundError", "Exception", "BaseException"}


def _catches_import_error(handler: ast.ExceptHandler) -> bool:
    kind = handler.type
    if kind is None:
        return True
    names = kind.elts if isinstance(kind, ast.Tuple) else [kind]
    return any(isinstance(n, ast.Name) and n.id in _CATCHES_IMPORT_ERROR for n in names)


def _defs(body, names):
    return [n for n in body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]


def copies(source: str, allow_seam: bool = False) -> list[str]:
    """Where one of the six methods is defined again.

    ``allow_seam``: ``SportsCore._rankings_loaded`` is football's override, not a copy.
    """
    tree = ast.parse(source)
    found = [f"module-level {n.name}" for n in _defs(tree.body, METHODS)]
    for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
        found += [f"{cls.name}.{n.name} is back -- {MODULE} ships it; delete the copy"
                  for n in _defs(cls.body, METHODS)
                  if not (allow_seam and cls.name == "SportsCore" and n.name == SEAM)]
    return found


def adoption_problems(source: str) -> list[str]:
    """``sports.py``: a plain import of the mixin and SportsCore's bases in order."""
    tree = ast.parse(source)
    problems = []
    imports = [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == MODULE]
    if not any(a.name == MIXIN and a.asname is None for n in imports for a in n.names):
        problems.append(f"does not import {MIXIN} from {MODULE}")
    guarded = {n.lineno for t in ast.walk(tree)
               if isinstance(t, ast.Try) and any(_catches_import_error(h) for h in t.handlers)
               for stmt in t.body for n in ast.walk(stmt) if hasattr(n, "lineno")}
    problems += [f"line {n.lineno}: the {MODULE} import is inside a try"
                 for n in imports if n.lineno in guarded]
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


def seam_problems(source: str) -> list[str]:
    """football's ``SportsCore._rankings_loaded`` override is still there."""
    tree = ast.parse(source)
    core = next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "SportsCore"), None)
    if not (core and _defs(core.body, {SEAM})):
        return [f"SportsCore.{SEAM} is gone: football counts its rankings keyed by team id too"]
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
        if sport in OVERRIDES_SEAM:
            failures += [f"{sport} sports.py: {p}" for p in seam_problems(source)]
        for path in runtime_files(plugin):
            allow = sport in OVERRIDES_SEAM and path == target
            failures += [f"{sport} {path.relative_to(plugin)}: {w}"
                         for w in copies(path.read_text(encoding="utf-8"), allow)]
    return failures


def find_core() -> Path | None:
    for candidate in (os.environ.get("LEDMATRIX_CORE", ""), str(REPO.parent / "LEDMatrix")):
        if candidate and (Path(candidate) / "src" / "plugin_system").is_dir():
            return Path(candidate)
    return None


def check_core(core: Path) -> list[str]:
    """Core's mixin defines exactly the methods listed in METHODS."""
    path = core / (MODULE.replace(".", "/") + ".py")
    if not path.is_file():
        return []  # a core older than 3.8.4: nothing to compare
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == MIXIN), None)
    if cls is None:
        return [f"{MODULE}: no {MIXIN}"]
    names = {n.name for n in cls.body if isinstance(n, ast.FunctionDef)}
    names |= {n.target.id for n in cls.body if isinstance(n, ast.AnnAssign) and n.value is not None}
    if names != set(METHODS):
        return [f"{MODULE}: {MIXIN} defines {sorted(names)}, expected {sorted(METHODS)}"]
    return []


GOOD = ("from src.common.sports_rotation import SportsRotationMixin\n"
        "class SportsCore(SportsFetchMixin, SportsFavoritesMixin, SportsRotationMixin,\n"
        "                 SportsCoreSharedMixin, SportsHelpersMixin, ABC):\n"
        "    def _rankings_loaded(self) -> bool:\n"
        "        return True\n")


def self_check() -> list[str]:
    failures = []
    planted = ("def _by_importance(games):\n    return games\n"
               "class SportsCore:\n    def _other_games_window(self, o, n):\n        return o\n"
               "    def _rankings_loaded(self):\n        return True\n"
               "class SportsLive:\n    def _advance_other_games_if_due(self):\n        return []\n"
               "class SportsUpcoming:\n    def _rotate_other_games_on_display(self):\n        return False\n"
               "class SportsRecent:\n    def _attach_odds_to_rotated_games(self, g):\n        pass\n"
               "    def _rankings_loaded(self):\n        return True\n")
    if len(copies(planted)) != 7:
        failures.append("self-check: planted copies were not all found")
    if len(copies(planted, allow_seam=True)) != 6:
        failures.append("self-check: the seam allowance reached past SportsCore._rankings_loaded")
    if copies(GOOD, allow_seam=True) or adoption_problems(GOOD) or seam_problems(GOOD):
        failures.append("self-check: a correct adoption was flagged: "
                        f"{copies(GOOD, allow_seam=True) + adoption_problems(GOOD) + seam_problems(GOOD)}")
    for label, source, expect in (
            ("a guarded import",
             "try:\n    " + GOOD.replace("\nclass", "\nexcept ImportError:\n    SportsRotationMixin = object\nclass", 1),
             "inside a try"),
            ("an aliased import", GOOD.replace("import SportsRotationMixin", "import SportsRotationMixin as R"),
             f"does not import {MIXIN}"),
            ("a missing base", GOOD.replace("SportsRotationMixin,\n", "\n"),
             f"SportsCore does not inherit {MIXIN}"),
            ("the base after the shared mixin",
             GOOD.replace("SportsRotationMixin,\n                 SportsCoreSharedMixin,",
                          "SportsCoreSharedMixin,\n                 SportsRotationMixin,"),
             "SportsCore lists its bases"),
            ("the base after SportsHelpersMixin",
             GOOD.replace("SportsRotationMixin,\n                 SportsCoreSharedMixin, SportsHelpersMixin,",
                          "SportsCoreSharedMixin,\n                 SportsHelpersMixin, SportsRotationMixin,"),
             "SportsCore lists its bases")):
        if not any(expect in p for p in adoption_problems(source)):
            failures.append(f"self-check: {label} was not flagged")
    if not seam_problems(GOOD.replace("_rankings_loaded", "_other_name")):
        failures.append("self-check: football's override gone was not flagged")
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
    print(f"  [pass] no other-games rotation copy is back in {len(SPORTS)} scoreboards; "
          f"all inherit core's {MIXIN}; only football overrides {SEAM}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
