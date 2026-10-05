#!/usr/bin/env python3
"""Keep the game-over copies gone: ``_is_game_really_over`` lives in core.

LEDMatrix core 3.8.1 ships ``src.common.sports_game_over`` --
``SportsGameOverMixin._is_game_really_over``, the body the nine scoreboards'
``SportsLive`` copies were reconciled to (sports family 5). Each plugin floors
on 3.8.1, inherits the mixin and deleted its copy; the one per-sport fact,
``FINAL_PERIOD``, stays declared on its ``SportsLive``. A copy that comes back
is dead weight at best; at worst it is a fix made on one side only, overriding
core's without anyone noticing. So, for every scoreboard:

1. No runtime file (tests excluded) defines ``_is_game_really_over``, on any
   class or at module level. The one exception is baseball's
   ``BaseballLive``, which ends postponed and suspended games first; it must
   defer to core's through ``super()``.
2. ``sports.py`` imports the mixin from core plainly -- a ``try`` around it
   can only hide which module was missing -- and ``SportsLive`` lists it as a
   base before ``SportsLiveSharedMixin``, the order core documents (the shared
   mixin's ``_detect_stale_games`` calls the method).
3. ``SportsLive`` declares ``FINAL_PERIOD`` with the value in ``FINAL_PERIOD``
   below, and no other class sets it.
4. With a core checkout, the mixin defines exactly the names listed here.

Self-check: planted sources must fail each of the checks above, so a broken
finder cannot report success.

Exit: 0 clean, 1 failure. The core comparison is skipped (with a note), never
failed, when no core checkout ships the module.

Run: python scripts/test_game_over_mixin_copies.py
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLUGINS = REPO / "plugins"

MODULE = "src.common.sports_game_over"
MIXIN = "SportsGameOverMixin"
METHOD = "_is_game_really_over"

#: The period from which a 0:00 clock ends a game; None: the clock never does.
FINAL_PERIOD = {"afl": None, "baseball": None, "basketball": 4, "football": 4,
                "hockey": 3, "lacrosse": 4, "nrl": None, "soccer": None, "ufc": None}

#: (plugin, file, class) that overrides the method on purpose; it must call super().
#: Baseball ends postponed and suspended games before core's check runs.
OVERRIDES = {("baseball", "baseball.py", "BaseballLive")}

_CATCHES_IMPORT_ERROR = {"ImportError", "ModuleNotFoundError", "Exception", "BaseException"}


def _catches_import_error(handler: ast.ExceptHandler) -> bool:
    kind = handler.type
    if kind is None:
        return True
    names = kind.elts if isinstance(kind, ast.Tuple) else [kind]
    return any(isinstance(n, ast.Name) and n.id in _CATCHES_IMPORT_ERROR for n in names)


def _calls_super(func: ast.FunctionDef) -> bool:
    """Whether the body calls ``super().<METHOD>(...)``."""
    return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == METHOD and isinstance(n.func.value, ast.Call)
               and isinstance(n.func.value.func, ast.Name) and n.func.value.func.id == "super"
               for n in ast.walk(func))


def copies(source: str, sport: str, filename: str) -> list[str]:
    """Where the method is defined again, or an allowed override skips super()."""
    tree = ast.parse(source)
    found = [f"module-level {METHOD}" for n in tree.body
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == METHOD]
    for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
        for item in cls.body:
            if not (isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == METHOD):
                continue
            if (sport, filename, cls.name) not in OVERRIDES:
                found.append(f"{cls.name}.{METHOD} is back -- {MODULE} ships it; delete the copy")
            elif not _calls_super(item):
                found.append(f"{cls.name}.{METHOD} no longer calls super(): core's check is skipped")
    return found


def _final_period_sets(tree) -> list[tuple[str, ast.expr]]:
    """(class, value) for every ``FINAL_PERIOD`` set in a class body."""
    sets = []
    for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
        for item in cls.body:
            if isinstance(item, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == "FINAL_PERIOD" for t in item.targets):
                sets.append((cls.name, item.value))
            elif (isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)
                  and item.target.id == "FINAL_PERIOD" and item.value is not None):
                sets.append((cls.name, item.value))
    return sets


def adoption_problems(source: str, final_period) -> list[str]:
    """``sports.py``: plain import, the base before the shared mixin, FINAL_PERIOD's value."""
    tree = ast.parse(source)
    problems = []
    imports = [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == MODULE
               and any(a.name == MIXIN and a.asname is None for a in n.names)]
    if not imports:
        problems.append(f"does not import {MIXIN} from {MODULE}")
    guarded = {n.lineno for t in ast.walk(tree)
               if isinstance(t, ast.Try) and any(_catches_import_error(h) for h in t.handlers)
               for stmt in t.body for n in ast.walk(stmt) if hasattr(n, "lineno")}
    problems += [f"line {n.lineno}: the {MODULE} import is inside a try"
                 for n in imports if n.lineno in guarded]
    live = next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "SportsLive"), None)
    if live is None:
        return problems + ["no class SportsLive"]
    bases = [b.id for b in live.bases if isinstance(b, ast.Name)]
    if MIXIN not in bases:
        problems.append(f"SportsLive does not inherit {MIXIN}")
    elif "SportsLiveSharedMixin" in bases and bases.index(MIXIN) > bases.index("SportsLiveSharedMixin"):
        problems.append(f"SportsLive lists {MIXIN} after SportsLiveSharedMixin")
    declared = [ast.literal_eval(v) for c, v in _final_period_sets(tree) if c == "SportsLive"]
    if declared != [final_period]:
        problems.append(f"SportsLive.FINAL_PERIOD is {declared or 'not declared'}, "
                        f"expected {final_period}")
    return problems


def runtime_files(plugin: Path):
    for path in sorted(plugin.rglob("*.py")):
        relative = path.relative_to(plugin)
        if relative.parts[0] == "test" or path.name.startswith("test_"):
            continue
        yield path


def check_plugins() -> list[str]:
    failures = []
    for sport, final_period in FINAL_PERIOD.items():
        plugin = PLUGINS / f"{sport}-scoreboard"
        target = plugin / "sports.py"
        if not target.is_file():
            failures.append(f"{sport}: sports.py is missing")
            continue
        failures += [f"{sport} sports.py: {p}" for p in
                     adoption_problems(target.read_text(encoding="utf-8"), final_period)]
        for path in runtime_files(plugin):
            source = path.read_text(encoding="utf-8")
            failures += [f"{sport} {path.relative_to(plugin)}: {w}"
                         for w in copies(source, sport, path.name)]
            failures += [f"{sport} {path.relative_to(plugin)}: {cls} sets FINAL_PERIOD; "
                         f"only sports.py's SportsLive declares it"
                         for cls, _v in _final_period_sets(ast.parse(source))
                         if not (path == target and cls == "SportsLive")]
    return failures


def find_core() -> Path | None:
    for candidate in (os.environ.get("LEDMATRIX_CORE", ""), str(REPO.parent / "LEDMatrix")):
        if candidate and (Path(candidate) / "src" / "plugin_system").is_dir():
            return Path(candidate)
    return None


def check_core(core: Path) -> list[str]:
    """Core's mixin defines exactly the method and FINAL_PERIOD."""
    path = core / (MODULE.replace(".", "/") + ".py")
    if not path.is_file():
        return []  # a core older than 3.8.1: nothing to compare
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == MIXIN)
    names = {n.name for n in cls.body if isinstance(n, ast.FunctionDef)}
    names |= {n.target.id for n in cls.body
              if isinstance(n, ast.AnnAssign) and n.value is not None}
    if names != {METHOD, "FINAL_PERIOD"}:
        return [f"{MODULE}: {MIXIN} defines {sorted(names)}, expected {METHOD} and FINAL_PERIOD"]
    return []


def self_check() -> list[str]:
    failures = []
    planted = ("def _is_game_really_over(game):\n    pass\n"
               "class SportsLive:\n    def _is_game_really_over(self, game):\n        return False\n")
    if len(copies(planted, "hockey", "sports.py")) != 2:
        failures.append("self-check: planted copies were not all found")
    no_super = ("class BaseballLive:\n    def _is_game_really_over(self, game):\n"
                "        return False\n")
    if not any("super()" in p for p in copies(no_super, "baseball", "baseball.py")):
        failures.append("self-check: an override without super() was not flagged")
    good = ("from src.common.sports_game_over import SportsGameOverMixin\n"
            "class SportsLive(SportsGameOverMixin, SportsLiveSharedMixin, SportsCore):\n"
            "    FINAL_PERIOD: Optional[int] = 3\n")
    if adoption_problems(good, 3):
        failures.append(f"self-check: a correct adoption was flagged: {adoption_problems(good, 3)}")
    for label, source, expect in (
            ("a guarded import", "try:\n    " + good.replace("\nclass", "\nexcept ImportError:\n"
                                                             "    SportsGameOverMixin = object\nclass", 1),
             "inside a try"),
            ("a missing base", good.replace("SportsGameOverMixin, Sports", "Sports", 1), "does not inherit"),
            ("the base after the shared mixin",
             good.replace("SportsGameOverMixin, SportsLiveSharedMixin", "SportsLiveSharedMixin, SportsGameOverMixin"),
             "after SportsLiveSharedMixin"),
            ("a drifted FINAL_PERIOD", good.replace("= 3", "= 4"), "expected 3"),
            ("a missing FINAL_PERIOD", good.replace("    FINAL_PERIOD: Optional[int] = 3\n", "    pass\n"),
             "not declared")):
        if not any(expect in p for p in adoption_problems(source, 3)):
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
    print(f"  [pass] no {METHOD} copy is back in {len(FINAL_PERIOD)} scoreboards; "
          f"all inherit core's {MIXIN}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
