#!/usr/bin/env python3
"""Every plugin that draws from a ScrollHelper must rebuild when its cache goes.

Vegas invalidates a plugin's scroll cache whenever the plugin reports an update
-- ``PluginAdapter.invalidate_plugin_scroll_cache`` sets ``cached_image`` and
``cached_array`` to None -- which is what stops last night's live game being
redrawn this morning. It cannot clear whatever private flag the plugin uses to
decide "I already built this", because core does not know the attribute exists.

A plugin that gates its rebuild on that private flag therefore skips the
rebuild, gets None back from the helper, and renders nothing or, worse, a
"no data" message over data it holds perfectly well. That is what odds-ticker
did on a live rig: ten misleading frames in three days, with games_data never
once empty.

This checks the decision structurally, per plugin, so a new scroll plugin
copying the old shape is caught. odds-ticker additionally has a behavioural
reproduction in plugins/odds-ticker/test_scroll_cache_invalidation.py.

Run: <core-venv>/bin/python scripts/test_scroll_cache_rebuild.py
"""

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
failures = []


def check(label, ok):
    print(("  PASS  " if ok else "  FAIL  ") + label)
    if not ok:
        failures.append(label)


def _methods_using(tree, call_name):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call) and getattr(sub.func, 'attr', None) == call_name:
                    yield node
                    break


def audit(path):
    """Which methods draw from the helper, and do they consult its cache?"""
    tree = ast.parse(path.read_text(encoding='utf-8'))
    out = []
    for fn in _methods_using(tree, 'get_visible_portion'):
        body = ast.dump(fn)
        out.append((fn.name, "cached_image" in body or "cached_array" in body))
    return out


# Plugins whose frame is drawn from a ScrollHelper the plugin itself owns, so
# core's invalidation reaches it. f1-scoreboard is deliberately absent: it
# serves Vegas from get_vegas_content() natively and never reads the helper
# cache there, which the rig confirms -- 21 of 21 native successes, no
# fallbacks -- so a guard there would assert against a path nothing takes.
EXPECTED = [
    ("odds-ticker", "manager.py"),
    ("march-madness", "manager.py"),
    ("ledmatrix-elections", "manager.py"),
    ("nfl-draft", "manager.py"),
]


def main():
    print("plugins that draw from their own ScrollHelper must consult its cache")
    for plugin, filename in EXPECTED:
        path = REPO / "plugins" / plugin / filename
        if not path.is_file():
            check(f"{plugin}: {filename} exists", False)
            continue
        drawing = audit(path)
        if not drawing:
            check(f"{plugin}: still draws from a ScrollHelper", False)
            continue
        for name, consults in drawing:
            check(f"{plugin}.{name}() rebuilds on an empty scroll cache", consults)

    print("\nno other plugin has quietly grown the same shape")
    known = {p for p, _ in EXPECTED} | {"f1-scoreboard"}
    stragglers = []
    for path in sorted((REPO / "plugins").glob("*/*.py")):
        if path.name.startswith("test_"):
            continue
        plugin = path.parent.name
        if plugin in known:
            continue
        try:
            for name, consults in audit(path):
                if not consults:
                    stragglers.append(f"{plugin}/{path.name}:{name}()")
        except SyntaxError:
            continue
    check("every other get_visible_portion() caller consults the cache: %s"
          % (", ".join(stragglers) if stragglers else "none missing"),
          not stragglers)

    print("\n%s" % ("FAILED: %d" % len(failures) if failures
                    else "All checks passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
