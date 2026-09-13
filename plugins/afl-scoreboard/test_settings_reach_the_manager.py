#!/usr/bin/env python3
"""A setting the user can change must actually reach the code that reads it.

Managers do not read the plugin config. `_adapt_config_for_manager` translates
it into the shape the managers expect, and that translation is an explicit
whitelist -- every key is named. A key missing from it is not a crash and not a
log line: the setting appears in the web UI, the user changes it, saves, and
nothing happens. The code silently keeps its own default.

That is exactly what happened to the five settings added for favourite
prioritisation, and later to the celebration settings and the display_options
block. A fixed list of keys to probe only catches the ones someone already
thought of, which is how those survived: this test now builds its probe list
from config_schema.json itself, so a key added to the schema is checked the
day it is added. Keys that are genuinely consumed somewhere other than the
managers are allowlisted below, each with its reason.

The check is deliberately blunt: set a value that is NOT the default, run the
real translation, and assert the value arrives. A test using default values
would pass against a translation that dropped the key entirely.

Every location the schema offers is checked on its own: a root key with the
nested blocks absent, and each nested block's keys with the root absent, so
a duplicate declared in two places has to work from both.

Run: <core-venv>/bin/python plugins/afl-scoreboard/test_settings_reach_the_manager.py
"""

import json
import logging
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

REPO = Path(__file__).resolve().parents[2]
CORE = None
for _c in (os.environ.get("LEDMATRIX_CORE", ""),
           str(REPO.parent / "LEDMatrix"),
           str(Path.home() / "projects" / "LEDMatrix")):
    if _c and (Path(_c) / "assets" / "fonts").is_dir():
        CORE = Path(_c)
        break
if CORE is None:
    print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
    sys.exit(2)
sys.path.insert(0, str(CORE))

#: Root keys read by something other than the per-league managers.
ALLOWLIST = {
    "display_modes": "translated to afl_live/afl_recent/afl_upcoming names; covered by test_afl_plugin",
    "scroll_settings": "read by ScrollDisplay from the plugin config, not the managers",
    "display_duration": "read by the plugin (manager.py) for mode rotation",
    "game_display_duration": "read by the plugin (manager.py) for mode rotation",
    "dynamic_duration": "read by the plugin's dynamic-duration hooks",
    "mode_durations": "read by the core display controller per mode",
}

#: Object blocks whose leaves the adapter reads one by one.
NESTED_BLOCKS = ("game_limits", "display_options", "filtering")

#: String settings with a validity constraint the schema cannot express.
STRING_PROBES = {"timezone": "Australia/Perth"}

results = []


def check(case, passed, detail=""):
    results.append((case, passed))
    print("  [%s] %s%s" % ("pass" if passed else "FAIL", case,
                           "" if passed else "  <- " + str(detail)))


def probe_value(name, spec):
    """A schema-valid value for this key that differs from its default."""
    kind = spec.get("type")
    if isinstance(kind, list):
        kind = next((k for k in kind if k != "null"), None)
    default = spec.get("default")
    if kind == "boolean":
        return not bool(default)
    if kind in ("integer", "number"):
        lo, hi = spec.get("minimum"), spec.get("maximum")
        base = default if isinstance(default, (int, float)) else (lo if lo is not None else 1)
        want = int(base) + 1
        if hi is not None and want > hi:
            want = int(base) - 1
        if lo is not None and want < lo:
            want = int(lo)
        return want
    if kind == "string":
        if name in STRING_PROBES:
            return STRING_PROBES[name]
        options = [o for o in spec.get("enum") or [] if o != default]
        return options[0] if options else "probe-%s" % name
    if kind == "array":
        items = spec.get("items") or {}
        options = [o for o in items.get("enum") or []
                   if not (isinstance(default, list) and o in default)]
        if options:
            return [options[0]]
        if items.get("type") in ("integer", "number"):
            return [7]
        return ["PROBE"]
    if kind == "object":
        return {"_probe": name}
    return None


def main():
    os.chdir(str(CORE))
    import manager as plugin_manager

    cls = None
    for name in dir(plugin_manager):
        obj = getattr(plugin_manager, name)
        if isinstance(obj, type) and hasattr(obj, "_adapt_config_for_manager"):
            cls = obj
            break
    if cls is None:
        print("SKIP: no class with _adapt_config_for_manager in this plugin")
        return 2

    obj = cls.__new__(cls)
    obj.logger = logging.getLogger("adapt_probe")
    for attr in ("cache_manager", "display_manager", "plugin_manager",
                 "config_manager", "font_manager"):
        setattr(obj, attr, MagicMock())

    schema = json.load(open(plugin_dir / "config_schema.json"))
    props = schema.get("properties") or {}

    def adapt(config):
        obj.config = config
        adapted = obj._adapt_config_for_manager()
        blocks = [v for v in adapted.values()
                  if isinstance(v, dict) and "favorite_teams" in v]
        if len(blocks) != 1:
            raise AssertionError("expected one league block, got %d" % len(blocks))
        return adapted, blocks[0]

    def arrived(adapted, block, key, want):
        return block.get(key) == want or adapted.get(key) == want

    root_probe, nested_probe = {}, {}
    for key, spec in props.items():
        if key in ALLOWLIST or not isinstance(spec, dict):
            continue
        if key in NESTED_BLOCKS:
            for child, child_spec in (spec.get("properties") or {}).items():
                value = probe_value(child, child_spec)
                if value is not None:
                    nested_probe.setdefault(key, {})[child] = value
            continue
        value = probe_value(key, spec)
        if value is not None:
            root_probe[key] = value

    if not root_probe:
        print("FAILED: the schema yielded no keys to probe")
        return 1

    print("root keys (nested blocks absent): %d" % len(root_probe))
    adapted, block = adapt(dict(root_probe))
    for key, want in root_probe.items():
        check("%s reaches the manager" % key,
              arrived(adapted, block, key, want),
              "block has %r" % (block.get(key, adapted.get(key)),))

    for where, values in nested_probe.items():
        print("\n%s keys (root duplicates absent): %d" % (where, len(values)))
        adapted, block = adapt({where: dict(values)})
        for key, want in values.items():
            check("%s.%s reaches the manager" % (where, key),
                  arrived(adapted, block, key, want),
                  "block has %r" % (block.get(key),))

    stale = [k for k in ALLOWLIST if k not in props]
    check("every allowlisted key is still in the schema", not stale, stale)

    failed = [c for c, ok in results if not ok]
    print("\n%d checks, %d failed" % (len(results), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
