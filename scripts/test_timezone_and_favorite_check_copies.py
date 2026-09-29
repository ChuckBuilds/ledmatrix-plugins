#!/usr/bin/env python3
"""Keep the scoreboards' timezone and favourite-check copies equal to core's.

LEDMatrix core now ships two modules the scoreboards carried as copies:
``src/common/favorite_team_check.py`` (the seven ``<sport>_favorite_check.py``)
and ``src/common/sports_timezone.py`` (the ten ``<sport>_timezone.py``). The
plugins import core's module when the core has it and keep their copy as the
fallback for older cores, so for a while the same behaviour lives in two
places. A fix made on one side only would make a plugin behave differently
depending on the core it runs on. This check fails on that, and on a plugin
that stops using core's module, which is what makes deleting the copies later
(once the plugins floor on the core release that ships them) a no-op.

Favourite check
  1. Every ``*_favorite_check.py`` copy is byte-identical to every other.
  2. Each equals core's module as an AST with type annotations dropped (core
     added annotations for its type checker; nothing else may differ).
  3. Each plugin with a copy imports ``FavoriteTeamCheck`` from core through
     the guard: ``except ModuleNotFoundError`` naming
     ``src.common.favorite_team_check``, then the bundled copy.

Timezone
  4. Each ``*_timezone.py``'s ``_from_config_manager``, ``system_timezone_name``
     and ``_validated`` equal core's as ASTs (docstrings and annotations dropped).
  5. Behaviour: each plugin's bundled resolver (loaded with core's module made
     unavailable) and core's resolver given that plugin's values return the
     same zone and log the same records (logger, level, text) across a grid of
     configs, config managers and system zones.
  6. Each plugin in ``ADOPTERS`` resolves through core when core has the
     module (its ``_core`` is core's module, and its answers and records match
     its own fallback's), and imports it through the exact-name guard.

f1-scoreboard's copy is compared in 4 and 5 but does not use core (an owner
decision), so it is not in ``ADOPTERS``.

Checks 2 and 4-6 need a core checkout that ships both modules (LEDMATRIX_CORE,
or ../LEDMatrix); without one they are skipped with a note, never failed.

Run: LEDMATRIX_CORE=<core> PYTHONPATH=<core> python scripts/test_timezone_and_favorite_check_copies.py
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import logging
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLUGINS = REPO / "plugins"

FAVORITE_CORE = "src.common.favorite_team_check"
TIMEZONE_CORE = "src.common.sports_timezone"
TIMEZONE_HELPERS = ("_from_config_manager", "system_timezone_name", "_validated")

#: Plugins whose <sport>_timezone.py resolves through core when core has it.
ADOPTERS = {"afl", "baseball", "basketball", "football", "hockey",
            "lacrosse", "nrl", "soccer", "ufc"}

failures: list[str] = []


def check(name: str, ok: bool, detail: object = None) -> None:
    if ok:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}" + (f" -- {detail}" if detail else ""))
        failures.append(name)


def copies(suffix: str) -> dict[str, Path]:
    """{sport: path} for every plugins/<sport>-scoreboard/<sport><suffix>."""
    found = {}
    for plugin in sorted(PLUGINS.glob("*-scoreboard")):
        sport = plugin.name[: -len("-scoreboard")]
        path = plugin / f"{sport}{suffix}"
        if path.is_file():
            found[sport] = path
    return found


def find_core() -> Path | None:
    for candidate in (os.environ.get("LEDMATRIX_CORE", ""), str(REPO.parent / "LEDMatrix")):
        if candidate and (Path(candidate) / "src" / "plugin_system").is_dir():
            return Path(candidate)
    return None


# --------------------------------------------------------------------------
# AST comparison

class _Normalise(ast.NodeTransformer):
    """Drop type annotations, and docstrings when asked."""

    def __init__(self, docstrings: bool):
        self.docstrings = docstrings

    def _body(self, node):
        body = node.body
        if (not self.docstrings and body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            node.body = body[1:] or [ast.Pass()]

    def visit_Module(self, node):
        self._body(node)
        return self.generic_visit(node)

    def _func(self, node):
        self._body(node)
        node.returns = None
        return self.generic_visit(node)

    visit_FunctionDef = visit_AsyncFunctionDef = _func

    def visit_ClassDef(self, node):
        self._body(node)
        return self.generic_visit(node)

    def visit_arg(self, node):
        node.annotation = None
        return node

    def visit_AnnAssign(self, node):
        if node.value is None:
            return None
        return ast.copy_location(ast.Assign(targets=[node.target], value=node.value), node)

    def visit_ImportFrom(self, node):
        # ``from typing import ...`` exists only to serve annotations.
        return None if node.module == "typing" else node


def normalised(tree: ast.AST, docstrings: bool) -> str:
    tree = _Normalise(docstrings).visit(ast.parse(ast.unparse(tree)))
    return ast.dump(ast.fix_missing_locations(tree))


def functions(path: Path) -> dict[str, ast.FunctionDef]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}


def guarded_import(tree: ast.AST, core_module: str, fallback: str) -> bool:
    """A ``try`` importing ``core_module``, whose ``except ModuleNotFoundError``
    handler names ``core_module`` in its ``exc.name`` set and then imports
    ``fallback`` (or, with ``fallback`` None, is a try/else shim)."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        imports_core = any(
            (isinstance(n, ast.ImportFrom) and n.module == core_module)
            or (isinstance(n, ast.Import) and any(a.name == core_module for a in n.names))
            for n in node.body)
        for handler in node.handlers:
            if not (imports_core and isinstance(handler.type, ast.Name)
                    and handler.type.id == "ModuleNotFoundError"):
                continue
            names_it = any(isinstance(n, ast.Set) and any(
                isinstance(e, ast.Constant) and e.value == core_module for e in n.elts)
                for n in ast.walk(handler))
            falls_back = (bool(node.orelse) if fallback is None else any(
                isinstance(n, ast.ImportFrom) and n.module == fallback
                for n in ast.walk(handler)))
            if names_it and falls_back:
                return True
    return False


# --------------------------------------------------------------------------
# behaviour

class _Holder:
    def __init__(self, config_manager=None):
        if config_manager is not None:
            self.config_manager = config_manager


class _Getter:
    def __init__(self, zone):
        self.zone = zone

    def get_timezone(self):
        return self.zone


class _RealCore:
    """get_config() plus get_timezone() defaulting to "UTC", like core's."""

    def __init__(self, config):
        self.config = config

    def get_config(self):
        return self.config

    def get_timezone(self):
        return self.config.get("timezone", "UTC")


class _Broken:
    def get_timezone(self):
        raise RuntimeError("config not loaded")


CONFIGS = [None, {}, {"timezone": "America/Denver"}, {"timezone": "UTC"},
           {"timezone": "utc"}, {"timezone": "Etc/UTC"}, {"timezone": "   "},
           {"timezone": "Not/AZone"}, {"timezone": 5}]
PLUGIN_MANAGERS = [None, _Holder(), _Holder(_Getter("America/Chicago")),
                   _Holder(_RealCore({"timezone": "Europe/London"})),
                   _Holder(_RealCore({"display": {}})), _Holder(_Broken()),
                   _Holder(_RealCore({"timezone": "UTC"})),
                   _Holder(_RealCore({"timezone": "Etc/UTC"})), _Holder(_Getter("Bad/Zone"))]
CACHE_MANAGERS = [None, _Holder(_Getter("Asia/Tokyo"))]
SYSTEM_ZONES = [None, "America/Chicago", "UTC"]


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.records: list[tuple] = []

    def emit(self, record):
        self.records.append((record.name, record.levelname, record.getMessage()))


def outcomes(resolvers, set_system_zone, logger_name: str) -> list[tuple]:
    """(zone, log records) for every scenario, through each of ``resolvers``
    (``resolve_timezone_name`` and ``resolve_timezone``: callers use both)."""
    capture = _Capture()
    watched = logging.getLogger(logger_name)
    given = logging.getLogger("timezone-copies.given")
    for lg in (watched, given):
        lg.addHandler(capture)
        lg.setLevel(logging.DEBUG)
        lg.propagate = False
    results = []
    try:
        for system in SYSTEM_ZONES:
            set_system_zone(lambda system=system: system)
            for config in CONFIGS:
                for pm in PLUGIN_MANAGERS:
                    for cm in CACHE_MANAGERS:
                        for log in (None, given):
                            for resolve in resolvers:
                                capture.records = []
                                zone = resolve(config=config, plugin_manager=pm,
                                               cache_manager=cm, log=log)
                                results.append((str(zone), capture.records))
    finally:
        for lg in (watched, given):
            lg.removeHandler(capture)
            lg.propagate = True
    return results


def load(path: Path, without_core: bool):
    """Execute a plugin's timezone module under its own name, optionally with
    core's module made unimportable (so its fallback is what runs)."""
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    saved = sys.modules.get(TIMEZONE_CORE, False)
    if without_core:
        sys.modules[TIMEZONE_CORE] = None  # any import of it raises
    try:
        spec.loader.exec_module(module)
    finally:
        if without_core:
            if saved is False:
                sys.modules.pop(TIMEZONE_CORE, None)
            else:
                sys.modules[TIMEZONE_CORE] = saved
    return module


def run_with_zone_source(module, source, logger_name):
    """outcomes() for ``module``'s resolver, stubbing system_timezone_name on
    ``source`` (the module the resolver reads it from)."""
    real = source.system_timezone_name
    try:
        return outcomes((module.resolve_timezone_name, module.resolve_timezone),
                        lambda f: setattr(source, "system_timezone_name", f), logger_name)
    finally:
        source.system_timezone_name = real


def core_outcomes(core_tz, logger_name, label, fixed_in):
    def bind(function):
        def resolve(**kwargs):
            # Core's default logger is its own; a shim passes the plugin module's.
            kwargs["log"] = kwargs["log"] or logging.getLogger(logger_name)
            return function(**kwargs, plugin_label=label, writeback_fixed_in=fixed_in)
        return resolve
    real = core_tz.system_timezone_name
    try:
        return outcomes((bind(core_tz.resolve_timezone_name), bind(core_tz.resolve_timezone)),
                        lambda f: setattr(core_tz, "system_timezone_name", f), logger_name)
    finally:
        core_tz.system_timezone_name = real


# --------------------------------------------------------------------------

def main() -> int:
    fav = copies("_favorite_check.py")
    tz = copies("_timezone.py")
    print(f"favorite_check copies: {', '.join(fav)}")
    print(f"timezone copies:       {', '.join(tz)}")
    check("found the favorite_check copies", len(fav) >= 7, len(fav))
    check("found the timezone copies", len(tz) >= 10, len(tz))
    check("every adopter still has its timezone copy", ADOPTERS <= set(tz),
          sorted(ADOPTERS - set(tz)))

    print("\nfavorite_check copies agree with each other")
    texts = {s: p.read_bytes().replace(b"\r\n", b"\n") for s, p in fav.items()}
    first = next(iter(texts.values()), b"")
    check("all copies byte-identical", all(t == first for t in texts.values()),
          [s for s, t in texts.items() if t != first])

    print("\nevery plugin with a favorite_check copy imports core's first")
    for sport in fav:
        tree = ast.parse((PLUGINS / f"{sport}-scoreboard" / "manager.py").read_text(encoding="utf-8"))
        check(f"{sport}: guarded import of {FAVORITE_CORE}",
              guarded_import(tree, FAVORITE_CORE, f"{sport}_favorite_check"))

    print("\nevery adopter's timezone module is a guarded core shim")
    for sport in sorted(ADOPTERS & set(tz)):
        tree = ast.parse(tz[sport].read_text(encoding="utf-8"))
        check(f"{sport}: guarded import of {TIMEZONE_CORE}",
              guarded_import(tree, TIMEZONE_CORE, None))

    core = find_core()
    have = core and all((core / "src" / "common" / f).is_file()
                        for f in ("favorite_team_check.py", "sports_timezone.py"))
    if not have:
        print(f"\n  SKIP  core comparison: no core checkout shipping both modules "
              f"(looked at {core or 'LEDMATRIX_CORE / ../LEDMatrix'})")
        return report()

    print(f"\ncore: {core}")
    core_fav = core / "src" / "common" / "favorite_team_check.py"
    core_tz_path = core / "src" / "common" / "sports_timezone.py"

    print("\nfavorite_check copies equal core's module (annotations aside)")
    want = normalised(ast.parse(core_fav.read_text(encoding="utf-8")), docstrings=True)
    for sport, path in fav.items():
        got = normalised(ast.parse(path.read_text(encoding="utf-8")), docstrings=True)
        check(f"{sport}: {path.name} == core", got == want)

    print("\ntimezone helpers equal core's (docstrings and annotations aside)")
    core_funcs = functions(core_tz_path)
    for sport, path in tz.items():
        mine = functions(path)
        drifted = [n for n in TIMEZONE_HELPERS
                   if n not in mine or normalised(mine[n], False) != normalised(core_funcs[n], False)]
        check(f"{sport}: {', '.join(TIMEZONE_HELPERS)}", not drifted, drifted)

    sys.path.insert(0, str(core))
    core_tz = importlib.import_module(TIMEZONE_CORE)
    scenarios = len(SYSTEM_ZONES) * len(CONFIGS) * len(PLUGIN_MANAGERS) * len(CACHE_MANAGERS) * 2
    print(f"\ntimezone resolution: bundled copy vs core, {scenarios} scenarios x 2 resolvers each")
    for sport, path in tz.items():
        fallback = load(path, without_core=True)
        check(f"{sport}: fallback load does not use core", not hasattr(fallback, "_core"))
        fixed_in = fallback._WRITEBACK_FIXED_IN if fallback._HAD_WRITEBACK_BUG else None
        bundled = run_with_zone_source(fallback, fallback, path.stem)
        expected = core_outcomes(core_tz, path.stem, _label(path), fixed_in)
        diff = next((i for i, (a, b) in enumerate(zip(bundled, expected)) if a != b), None)
        check(f"{sport}: bundled resolver == core resolver", diff is None and len(bundled) == len(expected) > 0,
              diff is not None and (bundled[diff], expected[diff]))
        if sport not in ADOPTERS:
            continue
        shimmed = load(path, without_core=False)
        check(f"{sport}: resolves through core's module",
              getattr(shimmed, "_core", None) is core_tz)
        through = run_with_zone_source(shimmed, core_tz, path.stem)
        diff = next((i for i, (a, b) in enumerate(zip(through, bundled)) if a != b), None)
        check(f"{sport}: core path == fallback path, zones and log records",
              diff is None and len(through) == len(bundled),
              diff is not None and (through[diff], bundled[diff]))
    return report()


def _label(path: Path) -> str:
    """The plugin name its copy puts in the nothing-resolved warning."""
    text = path.read_text(encoding="utf-8")
    return re.search(r'"in the (.+?)\'s Advanced Settings to override\."', text).group(1)


def report() -> int:
    if failures:
        print(f"\n{len(failures)} check(s) failed")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
