#!/usr/bin/env python3
"""Keep the stage 4 copies gone: plugin-class helpers, live scroll, display rules, font path.

LEDMatrix core 3.8.0 ships four modules holding code the scoreboards used to
carry as identical copies (the "identical sweep" of docs/SPORTS_UNIFICATION.md
in the core repo):

- ``src.common.sports_plugin_host`` -- ``SportsPluginHostMixin``: ten helpers
  of the plugin class in ``manager.py`` (Vegas weighting, the off-thread
  switch refresh, ...), for all nine;
- ``src.common.sports_live_scroll`` -- ``SportsLiveScrollMixin``: the
  mid-cycle live strip rebuild, for the eight with a live strip (not ufc);
- ``src.common.sports_display_rules`` -- ``SportsCardOptionsMixin``
  (``_card_option``, ``_recent_date_text``; the eight team scoreboards) and
  ``SportsGameRulesMixin`` (``_filtered_or_all``,
  ``_effective_live_duration``; all nine), on ``SportsCore``;
- ``src.common.sports_font_path`` -- ``resolve_font_path``, which every
  ``_resolve_font_path`` copy now is (imported under that name).

The plugins floor on 3.8.0, inherit the mixins and deleted their copies. A
copy that comes back is dead weight at best; at worst it is a fix made on one
side only, overriding core's without anyone noticing. So, for every adopting
plugin:

1. No runtime file (tests excluded) defines a moved name: a method or class
   constant on any class, or a module-level ``_resolve_font_path``. The
   deliberate exceptions are in ``KEEP``, each with its reason.
2. The file imports the mixin from core plainly -- a ``try`` around it can
   only hide which module was missing -- and the class lists it as a base.
   ``SportsCardOptionsMixin`` must come before ``SportsCoreSharedMixin``: it
   wraps that mixin's ``_card_option``, and in the other order it is never
   reached.
3. With a core checkout, the names listed here are the ones core defines, so
   this list cannot drift from what the plugins now rely on.

Self-check: planted sources must fail each of the checks above, so a broken
finder cannot report success.

Exit: 0 clean, 1 failure. The core comparison is skipped (with a note), never
failed, when no core checkout ships the modules.

Run: python scripts/test_stage4_mixin_copies.py
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLUGINS = REPO / "plugins"

ALL = ("afl", "baseball", "basketball", "football", "hockey", "lacrosse",
       "nrl", "soccer", "ufc")
NO_UFC = tuple(s for s in ALL if s != "ufc")

#: The plugin class in each manager.py.
PLUGIN_CLASS = {s: ("UFC" if s == "ufc" else s.capitalize()) + "ScoreboardPlugin" for s in ALL}

#: (core module, mixin, plugin file, class that inherits it -- a name or
#: {sport: name} --, adopting plugins, moved class-level names).
MOVED = [
    ("src.common.sports_plugin_host", "SportsPluginHostMixin", "manager.py", PLUGIN_CLASS, ALL,
     ("_SWITCH_REFRESH_MIN_GAP_SECONDS", "_dispatch_switch_refresh",
      "get_vegas_priority_weight", "_favorite_team_is_live",
      "_favorite_scan_targets", "_favorite_scan_games", "_game_involves",
      "get_vegas_content_type", "_dynamic_feature_enabled",
      "_get_total_games_for_manager", "_build_manager_key")),
    ("src.common.sports_live_scroll", "SportsLiveScrollMixin", "manager.py", PLUGIN_CLASS, NO_UFC,
     ("LIVE_SCROLL_REBUILD_MIN_SECONDS", "LIVE_SCROLL_REBUILD_DUTY_DIVISOR",
      "_live_scroll_managers", "_refresh_live_scroll_managers",
      "_live_scroll_fields", "_fingerprint_games", "_live_scroll_fingerprint",
      "_live_scroll_needs_rebuild", "_note_live_scroll_built",
      "_preserving_scroll_position")),
    ("src.common.sports_display_rules", "SportsCardOptionsMixin", "sports.py", "SportsCore", NO_UFC,
     ("_card_option", "_recent_date_text")),
    ("src.common.sports_display_rules", "SportsGameRulesMixin", "sports.py", "SportsCore", ALL,
     ("_filtered_or_all", "_effective_live_duration")),
]

FONT_MODULE = "src.common.sports_font_path"
FONT_NAME = "_resolve_font_path"
#: Files that must take _resolve_font_path from core.
FONT_FILES = {s: ("sports.py",) + (("fight_renderer.py", "headshot_downloader.py")
                                    if s == "ufc" else ("game_renderer.py",))
              for s in ALL}

#: (plugin, file, name) a plugin keeps on purpose, and why.
KEEP = {
    # A different method on a different class: the scroll card's own date
    # line, not SportsCore's scorebug one.
    ("baseball", "game_renderer.py", "_recent_date_text"),
    # A standalone asset generator run by hand, with no core on its path.
    ("ufc", "generate_placeholder_icon.py", FONT_NAME),
}

_CATCHES_IMPORT_ERROR = {"ImportError", "ModuleNotFoundError", "Exception", "BaseException"}


def _name(node):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return node.name
    target = (node.targets[0] if isinstance(node, ast.Assign) and len(node.targets) == 1
              else getattr(node, "target", None))
    return target.id if isinstance(target, ast.Name) else None


def copies(source: str, module_names, class_names) -> list[str]:
    """Where a moved name is defined again in this source."""
    tree = ast.parse(source)
    found = [f"module-level {_name(n)}" for n in tree.body
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and _name(n) in module_names]
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            found += [f"{node.name}.{_name(item)}" for item in node.body
                      if _name(item) in class_names]
    return found


def _catches_import_error(handler: ast.ExceptHandler) -> bool:
    kind = handler.type
    if kind is None:
        return True
    names = kind.elts if isinstance(kind, ast.Tuple) else [kind]
    return any(isinstance(n, ast.Name) and n.id in _CATCHES_IMPORT_ERROR for n in names)


def _guarded_lines(tree) -> set:
    guarded = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Try) and any(_catches_import_error(h) for h in node.handlers):
            for stmt in node.body:
                guarded.update(n.lineno for n in ast.walk(stmt) if hasattr(n, "lineno"))
    return guarded


def import_problems(tree, module: str, name: str, asname: str | None = None) -> list[str]:
    """``name`` must be imported from ``module`` plainly (not inside a try)."""
    imports = [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == module
               and any(a.name == name and a.asname == asname for a in n.names)]
    if not imports:
        shown = f"{name} as {asname}" if asname else name
        return [f"does not import {shown} from {module}"]
    guarded = _guarded_lines(tree)
    return [f"line {n.lineno}: the {module} import is inside a try" for n in imports
            if n.lineno in guarded]


def adoption_problems(source: str, module: str, mixin: str, class_name: str) -> list[str]:
    """The mixin must be imported plainly and be a base of ``class_name``."""
    tree = ast.parse(source)
    problems = import_problems(tree, module, mixin)
    cls = next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name), None)
    if cls is None:
        return problems + [f"no class {class_name}"]
    bases = [b.id for b in cls.bases if isinstance(b, ast.Name)]
    if mixin not in bases:
        problems.append(f"{class_name} does not inherit {mixin}")
    elif (mixin == "SportsCardOptionsMixin" and "SportsCoreSharedMixin" in bases
          and bases.index(mixin) > bases.index("SportsCoreSharedMixin")):
        problems.append(f"{class_name} lists {mixin} after SportsCoreSharedMixin, "
                        f"whose _card_option then wins")
    return problems


def runtime_files(plugin: Path):
    for path in sorted(plugin.rglob("*.py")):
        relative = path.relative_to(plugin)
        if relative.parts[0] == "test" or path.name.startswith("test_"):
            continue
        yield path


def check_plugins() -> list[str]:
    failures = []
    for module, mixin, filename, owner, adopters, class_names in MOVED:
        for sport in adopters:
            class_name = owner[sport] if isinstance(owner, dict) else owner
            target = PLUGINS / f"{sport}-scoreboard" / filename
            if not target.is_file():
                failures.append(f"{sport}: {filename} is missing")
                continue
            failures += [f"{sport} {filename}: {p}" for p in adoption_problems(
                target.read_text(encoding="utf-8"), module, mixin, class_name)]
    moved = {name for *_rest, names in MOVED for name in names}
    for sport in ALL:
        plugin = PLUGINS / f"{sport}-scoreboard"
        for path in runtime_files(plugin):
            keep = {name for s, f, name in KEEP if s == sport and f == path.name}
            found = copies(path.read_text(encoding="utf-8"), {FONT_NAME} - keep, moved - keep)
            failures += [f"{sport} {path.relative_to(plugin)}: {where} is back -- core ships "
                         f"it; delete the copy (or, if it must differ, add it to KEEP and "
                         f"say why)" for where in found]
        for filename in FONT_FILES[sport]:
            path = plugin / filename
            tree = ast.parse(path.read_text(encoding="utf-8"))
            failures += [f"{sport} {filename}: {p}" for p in import_problems(
                tree, FONT_MODULE, "resolve_font_path", FONT_NAME)]
    return failures


def find_core() -> Path | None:
    for candidate in (os.environ.get("LEDMATRIX_CORE", ""), str(REPO.parent / "LEDMatrix")):
        if candidate and (Path(candidate) / "src" / "plugin_system").is_dir():
            return Path(candidate)
    return None


def check_core(core: Path) -> list[str]:
    """The names above are exactly what core defines."""
    failures = []
    for module, mixin, _file, _cls, _adopters, class_names in MOVED:
        path = core / (module.replace(".", "/") + ".py")
        if not path.is_file():
            return []  # a core older than 3.8.0: nothing to compare
        tree = ast.parse(path.read_text(encoding="utf-8"))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == mixin)
        in_core = {_name(n) for n in cls.body
                   if not (isinstance(n, ast.AnnAssign) and n.value is None)} - {None}
        missing = [n for n in class_names if n not in in_core]
        extra = sorted(in_core - set(class_names))
        if missing:
            failures.append(f"{module}: listed here but not in {mixin}: {missing}")
        if extra:
            failures.append(f"{module}: {mixin} defines {extra}, not listed here")
    font = core / (FONT_MODULE.replace(".", "/") + ".py")
    if font.is_file() and "def resolve_font_path(" not in font.read_text(encoding="utf-8"):
        failures.append(f"{FONT_MODULE}: no resolve_font_path")
    return failures


def self_check() -> list[str]:
    failures = []
    planted = ("def _resolve_font_path(path):\n    return path\n"
               "class SoccerScoreboardPlugin:\n    LIVE_SCROLL_REBUILD_MIN_SECONDS = 5.0\n"
               "    def get_vegas_content_type(self):\n        return 'multi'\n")
    found = copies(planted, {FONT_NAME}, {"get_vegas_content_type", "LIVE_SCROLL_REBUILD_MIN_SECONDS"})
    if len(found) != 3:
        failures.append(f"self-check: planted copies found as {found}")
    guarded = ("try:\n    from src.common.sports_plugin_host import SportsPluginHostMixin\n"
               "except ImportError:\n    SportsPluginHostMixin = object\n"
               "class AflScoreboardPlugin(SportsPluginHostMixin):\n    pass\n")
    if not any("inside a try" in p for p in adoption_problems(
            guarded, "src.common.sports_plugin_host", "SportsPluginHostMixin", "AflScoreboardPlugin")):
        failures.append("self-check: a guarded import was not flagged")
    not_based = ("from src.common.sports_live_scroll import SportsLiveScrollMixin\n"
                 "class NrlScoreboardPlugin:\n    pass\n")
    if not any("does not inherit" in p for p in adoption_problems(
            not_based, "src.common.sports_live_scroll", "SportsLiveScrollMixin", "NrlScoreboardPlugin")):
        failures.append("self-check: a missing base was not flagged")
    wrong_order = ("from src.common.sports_display_rules import SportsCardOptionsMixin\n"
                   "class SportsCore(SportsCoreSharedMixin, SportsCardOptionsMixin):\n    pass\n")
    if not any("after SportsCoreSharedMixin" in p for p in adoption_problems(
            wrong_order, "src.common.sports_display_rules", "SportsCardOptionsMixin", "SportsCore")):
        failures.append("self-check: SportsCardOptionsMixin after the shared mixin was not flagged")
    unaliased = "from src.common.sports_font_path import resolve_font_path\n"
    if not import_problems(ast.parse(unaliased), FONT_MODULE, "resolve_font_path", FONT_NAME):
        failures.append("self-check: the font import without its alias was not flagged")
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
    print(f"  [pass] no stage 4 copy is back in {len(ALL)} scoreboards; all inherit core's mixins")
    return 0


if __name__ == "__main__":
    sys.exit(main())
