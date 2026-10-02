#!/usr/bin/env python3
"""Keep the stage 3 copies gone: celebration drawing, fetch methods, card delegations.

LEDMatrix core 3.7.0 ships three modules holding code the scoreboards used to
carry as identical copies:

- ``src.common.sports_celebration`` -- ``SportsCelebrationMixin`` (the score/win
  takeover's drawing) and the colour helpers, for afl, football, hockey, nrl
  and soccer;
- ``src.common.sports_fetch`` -- ``SportsFetchMixin`` (season fetch, live
  lookback, live-odds narrowing), for all nine;
- ``src.common.sports_card_wrappers`` -- ``SportsCardWrappersMixin`` (the game
  renderer's ``sports_card`` delegations), for the eight with a renderer.

The plugins floor on 3.7.0, inherit the mixins and deleted their copies. A copy
that comes back is dead weight at best; at worst it is a fix made on one side
only, overriding core's without anyone noticing. So, for every adopting plugin:

1. No runtime file (tests excluded) defines a moved name: a module-level
   function or constant, or a method or class constant on any class. The
   deliberate exceptions are listed in ``KEEP`` (football's own
   ``_format_game_date`` and ``_upcoming_center_mode``, which follow the
   switch-mode settings and override the mixin's).
2. The file imports the mixin from core plainly -- a ``try`` around it can only
   hide which module was missing -- and the class lists it as a base.
3. With a core checkout, the names listed here are the ones core defines, so
   this list cannot drift from what the plugins now rely on.

Self-check: planted sources must fail each of the checks above, so a broken
finder cannot report success.

Exit: 0 clean, 1 failure. The core comparison is skipped (with a note), never
failed, when no core checkout ships the modules.

Run: python scripts/test_stage3_mixin_copies.py
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

#: core module -> (mixin, plugin file, class that inherits it, adopting plugins,
#: moved module-level names, moved class-level names). Private names are the
#: plugins' spelling; core's free functions drop the leading underscore.
MOVED = {
    "src.common.sports_fetch": (
        "SportsFetchMixin", "sports.py", "SportsCore", ALL, (),
        ("_fetch_season_directly", "_background_fetches_espn_ranges",
         "_needs_previous_day", "_wants_live_odds",
         "_LOOKBACK_CUTOFF_HOUR", "_LIVE_ODDS_LOOKAHEAD")),
    "src.common.sports_celebration": (
        "SportsCelebrationMixin", "sports.py", "SportsLive",
        ("afl", "football", "hockey", "nrl", "soccer"),
        ("_rgb_luminance", "_rgb_saturation", "_color_distance", "_mix_color",
         "_scale_color", "_lift_color", "_cap_luminance", "_dim_rgba",
         "_palette_buckets", "_bucket_mean", "_bucket_headline_score",
         "_logo_palette", "_PALETTE_SAMPLE_PX", "_PALETTE_VIVID_SATURATION",
         "_PALETTE_MIN_CHANNEL", "_PALETTE_DISTINCT_DISTANCE",
         "_PALETTE_MIN_SATURATION", "_PALETTE_HEADLINE_LUMINANCE",
         "_PALETTE_LEGIBLE_LUMINANCE", "_PALETTE_LEGIBLE_SATURATION",
         "_PALETTE_LEGIBLE_AREA", "_PALETTE_BACKDROP_LUMINANCE",
         "_PALETTE_SCENERY_LUMINANCE"),
        ("_fit_font", "_celebration_palette", "_celebration_backdrop",
         "_draw_celebration_motif", "_celebration_confetti",
         "_draw_celebration_confetti", "_celebration_crests",
         "_draw_celebration_layout", "_DEFAULT_CELEBRATION_PALETTE",
         "_CELEBRATION_IMPACT", "_CELEBRATION_SETTLE",
         "_CELEBRATION_BREATH_SECONDS")),
    "src.common.sports_card_wrappers": (
        "SportsCardWrappersMixin", "game_renderer.py", "GameRenderer",
        tuple(s for s in ALL if s != "ufc"), (),
        ("_card_tzinfo", "_coerce_rgb", "_crisp_size", "_element_color",
         "_favorite_result", "_font_color", "_format_game_date",
         "_format_game_time", "_recent_score_color", "_score_color_for",
         "_scroll_card_option", "_side_is_favorite", "_side_score",
         "_unshare_element_fonts", "_upcoming_center_mode", "_vs_text",
         "_weekday_for")),
}

#: (plugin, name) pairs a plugin keeps on purpose: its own version differs.
KEEP = {
    ("football", "_format_game_date"),
    ("football", "_upcoming_center_mode"),
    # Wraps core's method rather than copying it: calls super() to draw the
    # takeover, then lays the goal light (hockey_goal_light.py) over the frame.
    ("hockey", "_draw_celebration_layout"),
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
    found = [f"module-level {_name(n)}" for n in tree.body if _name(n) in module_names]
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


def adoption_problems(source: str, module: str, mixin: str, class_name: str) -> list[str]:
    """The mixin must be imported plainly and be a base of ``class_name``."""
    tree = ast.parse(source)
    guarded = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Try) and any(_catches_import_error(h) for h in node.handlers):
            for stmt in node.body:
                guarded.update(n.lineno for n in ast.walk(stmt) if hasattr(n, "lineno"))
    imports = [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
               and n.module == module and any(a.name == mixin and not a.asname for a in n.names)]
    problems = []
    if not imports:
        problems.append(f"does not import {mixin} from {module}")
    problems += [f"line {n.lineno}: the {module} import is inside a try" for n in imports
                 if n.lineno in guarded]
    cls = next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name), None)
    if cls is None:
        problems.append(f"no class {class_name}")
    elif not any(isinstance(b, ast.Name) and b.id == mixin for b in cls.bases):
        problems.append(f"{class_name} does not inherit {mixin}")
    return problems


def runtime_files(plugin: Path):
    for path in sorted(plugin.rglob("*.py")):
        relative = path.relative_to(plugin)
        if relative.parts[0] == "test" or path.name.startswith("test_"):
            continue
        yield path


def check_plugins() -> list[str]:
    failures = []
    for module, (mixin, filename, class_name, adopters, module_names, class_names) in MOVED.items():
        for sport in adopters:
            plugin = PLUGINS / f"{sport}-scoreboard"
            target = plugin / filename
            if not target.is_file():
                failures.append(f"{sport}: {filename} is missing")
                continue
            failures += [f"{sport} {filename}: {p}" for p in adoption_problems(
                target.read_text(encoding="utf-8"), module, mixin, class_name)]
            keep = {name for s, name in KEEP if s == sport}
            for path in runtime_files(plugin):
                found = copies(path.read_text(encoding="utf-8"), set(module_names),
                               set(class_names) - keep)
                failures += [f"{sport} {path.relative_to(plugin)}: {where} is back -- "
                             f"{module} ships it; delete the copy (or, if it must "
                             f"differ, add it to KEEP and say why)" for where in found]
    return failures


def find_core() -> Path | None:
    for candidate in (os.environ.get("LEDMATRIX_CORE", ""), str(REPO.parent / "LEDMatrix")):
        if candidate and (Path(candidate) / "src" / "plugin_system").is_dir():
            return Path(candidate)
    return None


def check_core(core: Path) -> list[str]:
    """The names above are exactly what core defines."""
    failures = []
    for module, (mixin, _file, _cls, _adopters, module_names, class_names) in MOVED.items():
        path = core / (module.replace(".", "/") + ".py")
        if not path.is_file():
            return []  # a core older than 3.7.0: nothing to compare
        tree = ast.parse(path.read_text(encoding="utf-8"))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == mixin)
        in_core = {_name(n) for n in cls.body
                   if not (isinstance(n, ast.AnnAssign) and n.value is None)} - {None}
        core_module = {_name(n) for n in tree.body} - {None}
        missing = [n for n in class_names if n not in in_core]
        missing += [n for n in module_names if n not in core_module and n.lstrip("_") not in core_module]
        extra = sorted(in_core - set(class_names))
        if missing:
            failures.append(f"{module}: listed here but not in core: {missing}")
        if extra:
            failures.append(f"{module}: {mixin} defines {extra}, not listed here")
    return failures


def self_check() -> list[str]:
    failures = []
    planted = ("def _mix_color(a, b, t):\n    pass\n"
               "class SportsLive:\n    _CELEBRATION_IMPACT = 0.1\n"
               "    def _draw_celebration_layout(self):\n        pass\n")
    found = copies(planted, {"_mix_color"}, {"_draw_celebration_layout", "_CELEBRATION_IMPACT"})
    if len(found) != 3:
        failures.append(f"self-check: planted copies found as {found}")
    guarded = ("try:\n    from src.common.sports_fetch import SportsFetchMixin\n"
               "except ImportError:\n    SportsFetchMixin = object\n"
               "class SportsCore(SportsFetchMixin):\n    pass\n")
    if not any("inside a try" in p for p in adoption_problems(
            guarded, "src.common.sports_fetch", "SportsFetchMixin", "SportsCore")):
        failures.append("self-check: a guarded import was not flagged")
    not_based = "from src.common.sports_fetch import SportsFetchMixin\nclass SportsCore:\n    pass\n"
    if not any("does not inherit" in p for p in adoption_problems(
            not_based, "src.common.sports_fetch", "SportsFetchMixin", "SportsCore")):
        failures.append("self-check: a missing base was not flagged")
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
    print(f"  [pass] no stage 3 copy is back in {len(ALL)} scoreboards; all inherit core's mixins")
    return 0


if __name__ == "__main__":
    sys.exit(main())
