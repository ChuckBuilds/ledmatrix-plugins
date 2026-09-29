#!/usr/bin/env python3
"""Keep the scoreboards on core's favourite check and timezone resolver.

LEDMatrix core ships ``src/common/favorite_team_check.py`` and
``src/common/sports_timezone.py`` (first released in 3.6.0; 3.6.1 fixed the
favourite check calling a started postseason a finished season). The
scoreboards used to bundle copies: ``<sport>_favorite_check.py`` in seven,
and the resolver inside ``<sport>_timezone.py`` in ten. The plugins below
floor on 3.6.1 and have deleted them (the sunset), so this guard checks that
the sunset holds:

Favourite check, for each id in ``FAVORITE_SUNSET``
  1. ``<sport>_favorite_check.py`` is absent.
  2. No runtime module imports a ``*_favorite_check`` bare name, every
     ``src.common.favorite_team_check`` import is unguarded (a ``try`` around
     it can only hide which module was missing -- there is nothing left to
     fall back to), and ``manager.py`` imports it.

Timezone, for each id in ``TIMEZONE_SUNSET``
  3. ``<sport>_timezone.py`` is a thin binding: it imports
     ``src.common.sports_timezone`` unguarded, and its only functions are
     ``resolve_timezone_name`` and ``resolve_timezone``, each returning core's
     function of the same name. The resolver lives in core; a copy of it
     growing back here fails.
  4. Behaviour (needs a core checkout that ships the module): each binding
     gives core this plugin's label and write-back release, from
     ``BINDINGS`` below, and its own module logger when the caller passes no
     ``log``. Checked by running the plugin's ``resolve_timezone_name`` and
     ``resolve_timezone`` against core's given those values over a grid of
     configs, config managers and system zones, comparing the zone and every
     log record (logger, level, text).

Self-check: the import finder must flag a planted guarded import and pass a
plain one, so a broken finder cannot report success.

Exit: 0 clean, 1 failure. Check 4 is skipped (with a note), never failed,
without a core checkout (LEDMATRIX_CORE, or ../LEDMatrix) that ships
``src/common/sports_timezone.py``.

Run: LEDMATRIX_CORE=<core> PYTHONPATH=<core> python scripts/test_timezone_and_favorite_check_copies.py
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import logging
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLUGINS = REPO / "plugins"

FAVORITE_CORE = "src.common.favorite_team_check"
TIMEZONE_CORE = "src.common.sports_timezone"

#: Scoreboards that completed the favourite-check sunset: bundled copy
#: deleted, core import unguarded, manifest floored at 3.6.1. Listed, not
#: inferred, as in test_espn_dates_copies.py: adding an id is the moment
#: somebody states the sunset holds for it.
FAVORITE_SUNSET = frozenset({
    "afl", "baseball", "basketball", "football", "hockey", "lacrosse", "nrl",
})

#: Each timezone binding's values: (plugin_label, writeback_fixed_in). The
#: label is the name in core's "could not determine a timezone" warning. A
#: write-back release is set only for the plugins that once wrote a resolved
#: "UTC" back into the saved config; core names it in its warning when it
#: overrides such a "UTC".
BINDINGS = {
    "afl": ("AFL scoreboard", None),
    "baseball": ("baseball scoreboard", "1.20.0"),
    "basketball": ("basketball scoreboard", None),
    "f1": ("F1 scoreboard", None),
    "football": ("football scoreboard", "2.9.0"),
    "hockey": ("hockey scoreboard", None),
    "lacrosse": ("lacrosse scoreboard", None),
    "nrl": ("NRL scoreboard", None),
    "soccer": ("soccer scoreboard", None),
    "ufc": ("UFC scoreboard", None),
}
TIMEZONE_SUNSET = frozenset(BINDINGS)
RESOLVERS = ("resolve_timezone_name", "resolve_timezone")

_CATCHES_IMPORT_ERROR = {"ImportError", "ModuleNotFoundError", "Exception", "BaseException"}

failures: list[str] = []


def check(name: str, ok: bool, detail: object = None) -> None:
    if ok:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}" + (f" -- {detail}" if detail else ""))
        failures.append(name)


def plugin_dir(sport: str) -> Path:
    return PLUGINS / f"{sport}-scoreboard"


def find_core() -> Path | None:
    for candidate in (os.environ.get("LEDMATRIX_CORE", ""), str(REPO.parent / "LEDMatrix")):
        if candidate and (Path(candidate) / "src" / "plugin_system").is_dir():
            return Path(candidate)
    return None


# --------------------------------------------------------------------------
# imports

def _catches_import_error(handler: ast.ExceptHandler) -> bool:
    kind = handler.type
    if kind is None:
        return True
    names = kind.elts if isinstance(kind, ast.Tuple) else [kind]
    return any(isinstance(n, ast.Name) and n.id in _CATCHES_IMPORT_ERROR for n in names)


def imports(source: str, wanted) -> list[tuple[int, str, bool]]:
    """(line, module, guarded) for each import whose module ``wanted(module)``."""
    tree = ast.parse(source)
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
        found += [(node.lineno, m, node.lineno in guarded_lines) for m in modules if wanted(m)]
    return found


def _favorite_module(module: str) -> bool:
    return module == FAVORITE_CORE or module.endswith("_favorite_check")


#: (label, source, expected [(module, guarded)]) for the import finder.
SELF_CHECKS = [
    ("plain core import",
     f"from {FAVORITE_CORE} import FavoriteTeamCheck\n",
     [(FAVORITE_CORE, False)]),
    ("the old guarded shape",
     f"try:\n    from {FAVORITE_CORE} import FavoriteTeamCheck\n"
     "except ModuleNotFoundError as exc:\n    from afl_favorite_check import FavoriteTeamCheck\n",
     [(FAVORITE_CORE, True), ("afl_favorite_check", False)]),
    ("a guard with nothing behind it",
     "try:\n    from src.common import favorite_team_check\nexcept ImportError:\n    pass\n",
     [(FAVORITE_CORE, True)]),
    ("a try that catches something else is not a guard",
     f"try:\n    import {FAVORITE_CORE}\nexcept KeyError:\n    pass\n",
     [(FAVORITE_CORE, False)]),
]


def runtime_files(plugin: Path):
    for path in sorted(plugin.rglob("*.py")):
        relative = path.relative_to(plugin)
        if relative.parts[0] == "test" or path.name.startswith("test_"):
            continue
        yield path


def favorite_violations(sport: str) -> list[str]:
    plugin = plugin_dir(sport)
    problems = []
    copy = plugin / f"{sport}_favorite_check.py"
    if copy.exists():
        problems.append(f"{copy.relative_to(REPO)} is back; the manifest floor guarantees "
                        f"core ships {FAVORITE_CORE}")
    in_manager = False
    for path in runtime_files(plugin):
        for line, module, guarded in imports(path.read_text(encoding="utf-8"), _favorite_module):
            where = f"{path.relative_to(REPO)}:{line}"
            if module != FAVORITE_CORE:
                problems.append(f"{where} imports the bundled {module}; import {FAVORITE_CORE}")
            elif guarded:
                problems.append(f"{where} guards the {FAVORITE_CORE} import again; with no "
                                "fallback left, catching only hides which module was missing")
            elif path.name == "manager.py":
                in_manager = True
    if not in_manager:
        problems.append(f"{plugin.name}/manager.py does not import {FAVORITE_CORE}")
    return problems


def _returns_core(func: ast.FunctionDef) -> bool:
    """The body (docstring aside) is ``return _core.<func.name>(...)``."""
    body = func.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    if len(body) != 1 or not isinstance(body[0], ast.Return):
        return False
    call = body[0].value
    return (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name) and call.func.value.id == "_core"
            and call.func.attr == func.name)


def timezone_violations(sport: str) -> list[str]:
    path = plugin_dir(sport) / f"{sport}_timezone.py"
    if not path.is_file():
        return [f"missing {path.relative_to(REPO)}; the plugin's callers import it"]
    source = path.read_text(encoding="utf-8")
    rel = path.relative_to(REPO)
    problems = []
    found = imports(source, lambda m: m == TIMEZONE_CORE)
    if not found:
        problems.append(f"{rel} does not import {TIMEZONE_CORE}")
    problems += [f"{rel}:{line} guards the {TIMEZONE_CORE} import; nothing is left to fall back to"
                 for line, _module, guarded in found if guarded]
    funcs = {n.name: n for n in ast.walk(ast.parse(source))
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    extra = sorted(set(funcs) - set(RESOLVERS))
    if extra:
        problems.append(f"{rel} defines {', '.join(extra)}; the resolver lives in core's "
                        f"{TIMEZONE_CORE} -- fix it there")
    for name in RESOLVERS:
        if name not in funcs:
            problems.append(f"{rel} lacks {name}(); the plugin's callers use it")
        elif not _returns_core(funcs[name]):
            problems.append(f"{rel}: {name}() must just return _core.{name}(...)")
    return problems


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


def outcomes(resolvers, core_tz) -> list[tuple]:
    """(zone, log records) for every scenario through each of ``resolvers``.

    The capture sits on the root logger, so a record is seen whichever logger
    it goes to -- a binding that dropped its own logger would show up as
    records named after core's module instead.
    """
    capture = _Capture()
    root = logging.getLogger()
    saved_level = root.level
    root.addHandler(capture)
    root.setLevel(logging.DEBUG)
    given = logging.getLogger("timezone-copies.given")
    real = core_tz.system_timezone_name
    results = []
    try:
        for system in SYSTEM_ZONES:
            core_tz.system_timezone_name = lambda system=system: system
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
        core_tz.system_timezone_name = real
        root.removeHandler(capture)
        root.setLevel(saved_level)
    return results


def load(path: Path):
    """Execute a plugin's timezone module under its own (bare) name."""
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def expected_outcomes(core_tz, logger_name: str, label: str, fixed_in):
    def bind(function):
        def resolve(**kwargs):
            kwargs["log"] = kwargs["log"] or logging.getLogger(logger_name)
            return function(**kwargs, plugin_label=label, writeback_fixed_in=fixed_in)
        return resolve
    return outcomes([bind(getattr(core_tz, name)) for name in RESOLVERS], core_tz)


# --------------------------------------------------------------------------

def main() -> int:
    broken = []
    for label, source, want in SELF_CHECKS:
        got = [(module, guarded) for _line, module, guarded in imports(source, _favorite_module)]
        if got != want:
            broken.append(f"{label} (found {got}, expected {want})")
    check(f"import finder self-check, {len(SELF_CHECKS)} planted shapes", not broken, broken)

    print("\nfavourite check: no bundled copy, core's imported plainly")
    for sport in sorted(FAVORITE_SUNSET):
        problems = favorite_violations(sport)
        check(f"{sport}: {FAVORITE_CORE}", not problems, "; ".join(problems))
    strays = sorted(p.relative_to(REPO).as_posix() for p in PLUGINS.glob("*/*_favorite_check.py"))
    check("no *_favorite_check.py anywhere under plugins/", not strays, strays)

    print("\ntimezone: each <sport>_timezone.py is a thin binding of core's resolver")
    for sport in sorted(TIMEZONE_SUNSET):
        problems = timezone_violations(sport)
        check(f"{sport}: {sport}_timezone.py", not problems, "; ".join(problems))

    core = find_core()
    if not (core and (core / "src" / "common" / "sports_timezone.py").is_file()):
        print(f"\n  SKIP  binding values: no core checkout shipping {TIMEZONE_CORE} "
              f"(looked at {core or 'LEDMATRIX_CORE / ../LEDMatrix'})")
        return report()

    print(f"\ncore: {core}")
    sys.path.insert(0, str(core))
    core_tz = importlib.import_module(TIMEZONE_CORE)
    scenarios = len(SYSTEM_ZONES) * len(CONFIGS) * len(PLUGIN_MANAGERS) * len(CACHE_MANAGERS) * 2
    print(f"timezone bindings vs core given BINDINGS' values, {scenarios} scenarios x "
          f"{len(RESOLVERS)} resolvers each")
    for sport in sorted(TIMEZONE_SUNSET):
        path = plugin_dir(sport) / f"{sport}_timezone.py"
        if not path.is_file():
            continue  # reported above
        label, fixed_in = BINDINGS[sport]
        module = load(path)
        got = outcomes([getattr(module, name) for name in RESOLVERS], core_tz)
        want = expected_outcomes(core_tz, path.stem, label, fixed_in)
        diff = next((i for i, (a, b) in enumerate(zip(got, want)) if a != b), None)
        check(f"{sport}: label {label!r}, write-back {fixed_in!r}, logger {path.stem!r}",
              diff is None and len(got) == len(want) > 0,
              diff is not None and (got[diff], want[diff]))
    return report()


def report() -> int:
    if failures:
        print(f"\n{len(failures)} check(s) failed")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
