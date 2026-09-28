#!/usr/bin/env python3
"""ufc-scoreboard must not bind another plugin's dynamic_team_resolver.

sports.py did `from dynamic_team_resolver import DynamicTeamResolver`, but ufc
ships no such module. The core loader leaves earlier plugins' directories on
sys.path, so the name resolved to whichever scoreboard loaded first -- and
sports.py then called `DynamicTeamResolver(cache_manager=...)`. Hockey's copy
(like most) takes no cache_manager, so after a live re-enable with hockey
running every UFC manager failed with TypeError and the plugin showed nothing.

UFC has no teams to resolve (favourites are fighters), so the import is gone.
This plants a hostile `dynamic_team_resolver` the way another plugin's would
sit on sys.path and builds the real plugin: all three managers must exist.

Run: LEDMATRIX_CORE=<core> <core-venv>/bin/python plugins/ufc-scoreboard/test_no_foreign_team_resolver.py
"""

import ast
import logging
import os
import sys
import types
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))
_core = os.environ.get("LEDMATRIX_CORE", "")
for _candidate in (_core, str(PLUGIN_DIR.parents[2] / "LEDMatrix")):
    if _candidate and (Path(_candidate) / "src" / "plugin_system").is_dir():
        sys.path.insert(0, _candidate)
        break
else:
    print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
    sys.exit(2)

logging.disable(logging.CRITICAL)

FAILURES = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILURES.append(label)


print("sports.py imports no dynamic_team_resolver")
tree = ast.parse((PLUGIN_DIR / "sports.py").read_text(encoding="utf-8"))
imported = set()
for node in ast.walk(tree):
    if isinstance(node, ast.ImportFrom) and node.module:
        imported.add(node.module)
    elif isinstance(node, ast.Import):
        imported.update(alias.name for alias in node.names)
check("no import of dynamic_team_resolver",
      not any(name.split(".")[-1] == "dynamic_team_resolver" for name in imported),
      sorted(n for n in imported if "resolver" in n))
check("ufc ships no dynamic_team_resolver.py",
      not (PLUGIN_DIR / "dynamic_team_resolver.py").exists())


# Another scoreboard's resolver, as the loader would leave it importable. Its
# constructor has no cache_manager, like hockey's; resolving would also be
# wrong for fighters, so it raises if it is ever used.
class _ForeignResolver:
    def __init__(self, request_timeout=30):
        pass

    def resolve_teams(self, *a, **k):
        raise AssertionError("ufc used another plugin's team resolver")


foreign = types.ModuleType("dynamic_team_resolver")
foreign.DynamicTeamResolver = _ForeignResolver
sys.modules["dynamic_team_resolver"] = foreign

from src.plugin_system.testing import (  # noqa: E402
    MockCacheManager, MockDisplayManager, MockPluginManager)
from manager import UFCScoreboardPlugin  # noqa: E402

print("\nbuilding the plugin with a foreign resolver importable")
config = {
    "enabled": True,
    "ufc": {"enabled": True, "favorite_fighters": [], "favorite_teams": ["X"]},
}
plugin = UFCScoreboardPlugin("ufc-scoreboard", config, MockDisplayManager(128, 32),
                             MockCacheManager(), MockPluginManager())
for kind in ("live", "recent", "upcoming"):
    mgr = getattr(plugin, f"ufc_{kind}", None)
    check(f"the {kind} manager was built", mgr is not None)
    if mgr is not None:
        check(f"  its dynamic_resolver is None", mgr.dynamic_resolver is None,
              type(mgr.dynamic_resolver).__name__)
        check(f"  its favorite_teams are the configured list, untouched",
              mgr.favorite_teams == mgr.mode_config.get("favorite_teams", []),
              mgr.favorite_teams)

print()
if FAILURES:
    print(f"{len(FAILURES)} check(s) failed")
    sys.exit(1)
print("all checks passed")
