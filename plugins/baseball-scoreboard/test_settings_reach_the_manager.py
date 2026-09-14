#!/usr/bin/env python3
"""A setting the user can change must actually reach the code that reads it.

Managers do not read the plugin config. `_adapt_config_for_manager` translates
it into the shape the managers expect, and that translation is an explicit
whitelist -- every key is named. A key missing from it is not a crash and not a
log line: the setting appears in the web UI, the user changes it, saves, and
nothing happens. The code silently keeps its own default.

That is exactly what happened to the five settings added for favourite
prioritisation, and later to display_options.show_series_summary: declared in
the schema, rendered in the UI, read by baseball.py -- and never passed through
the translation.

This test used to probe a fixed list of keys, which is how show_series_summary
slipped past it: nobody had added it to the list. The probe list is now built
from config_schema.json itself, so a key added to the schema is checked the
moment it exists. Keys that are deliberately NOT forwarded (read from the
plugin config by something other than the managers) are allowlisted below, one
line of reason each -- adding to that list is a decision, not an oversight.

The check is deliberately blunt: set every value to something that is NOT its
default, in the place the schema declares it, run the real translation, and
assert each value arrives. A test using default values would pass against a
translation that dropped the key entirely.

Run: <core-venv>/bin/python plugins/baseball-scoreboard/test_settings_reach_the_manager.py
"""

import json
import os
import sys
from pathlib import Path

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

results = []

#: League-block sub-objects whose leaf keys the translation forwards one by
#: one. Anything declared inside them is probed.
FORWARDED_BLOCKS = ("game_limits", "display_options", "filtering")

#: League-block keys that are not forwarded key-by-key, and why.
NOT_FORWARDED = {
    # Translated into "<league>_live"/"_recent"/"_upcoming" booleans; the
    # *_display_mode choices are read by manager.py from self.config.
    "display_modes": "translated to per-mode booleans; display modes read by manager.py",
    "scroll_settings": "read by scroll_display.py from the whole plugin config",
    "mode_durations": "read by manager.py _get_mode_duration from self.config",
    "dynamic_duration": "read by manager.py dynamic-duration helpers from self.config",
}

#: Leaf keys inside FORWARDED_BLOCKS consumed somewhere other than the
#: translated top level.
NESTED_ELSEWHERE = {
    # sports.py reads it out of the forwarded "filtering" dict.
    ("filtering", "favorite_live_boost"),
}


def check(case, passed, detail=""):
    results.append((case, passed))
    print("  [%s] %s%s" % ("pass" if passed else "FAIL", case,
                           "" if passed else "  <- " + str(detail)))


def probe_value(node):
    """A valid value for this schema node that differs from its default."""
    kind = node.get("type")
    default = node.get("default")
    if isinstance(kind, list):
        kind = next((k for k in kind if k != "null"), None)
    if kind == "boolean":
        return not bool(default)
    if "enum" in node:
        for choice in node["enum"]:
            if choice != default:
                return choice
        return None
    if kind in ("integer", "number"):
        low = node.get("minimum", 0)
        high = node.get("maximum", 10 ** 6)
        base = default if isinstance(default, (int, float)) else low
        step = 1 if kind == "integer" else 0.5
        want = base + step
        if want > high:
            want = base - step
        if want < low:
            return None
        return want
    if kind == "string":
        return "probe-value"
    if kind == "array":
        items = node.get("items") or {}
        choices = [c for c in (items.get("enum") or []) if c not in (default or [])]
        if choices:
            return [choices[0]]
        if items.get("type") in ("integer", "number"):
            return [7]
        return ["PRB"]
    return None


def build_probe(league_node):
    """[(where, key, value)] for every forwardable leaf in a league block."""
    probes = []
    for key, node in (league_node.get("properties") or {}).items():
        if not isinstance(node, dict):
            continue
        if key in FORWARDED_BLOCKS:
            for sub_key, sub_node in (node.get("properties") or {}).items():
                value = probe_value(sub_node)
                if value is not None:
                    probes.append((key, sub_key, value))
            continue
        if node.get("type") == "object" or key in NOT_FORWARDED:
            if key not in NOT_FORWARDED:
                probes.append((None, key, "__UNLISTED_OBJECT__"))
            continue
        value = probe_value(node)
        if value is not None:
            probes.append((None, key, value))
    return probes


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

    import logging
    from unittest.mock import MagicMock
    obj = cls.__new__(cls)
    obj.logger = logging.getLogger("adapt_probe")
    for attr in ("cache_manager", "display_manager", "plugin_manager",
                 "config_manager", "font_manager"):
        setattr(obj, attr, MagicMock())
    obj.timezone_str = "America/Chicago"

    schema = json.load(open(plugin_dir / "config_schema.json", encoding="utf-8"))
    leagues = [
        name for name, node in (schema.get("properties") or {}).items()
        if isinstance(node, dict) and isinstance(node.get("properties"), dict)
        and any(k in node["properties"] for k in ("game_limits", "display_options"))
    ]
    if not leagues:
        print("FAILED: no league blocks found in config_schema.json")
        return 1

    for league in leagues:
        print("league: %s" % league)
        probes = build_probe(schema["properties"][league])
        block = {}
        for where, key, value in probes:
            if value == "__UNLISTED_OBJECT__":
                check("%s.%s is forwarded or allowlisted" % (league, key), False,
                      "object setting with no NOT_FORWARDED entry")
                continue
            target = block.setdefault(where, {}) if where else block
            target[key] = value
        obj.config = {league: block}
        try:
            adapted = obj._adapt_config_for_manager(league)
        except Exception as exc:
            check("%s: the translation runs" % league, False,
                  "%s: %s" % (type(exc).__name__, exc))
            continue
        landed = adapted.get("%s_scoreboard" % league) or {}
        for where, key, want in probes:
            if want == "__UNLISTED_OBJECT__":
                continue
            label = "%s.%s" % (where, key) if where else key
            if (where, key) in NESTED_ELSEWHERE:
                got = (landed.get(where) or {}).get(key)
            else:
                got = landed.get(key)
            check("%s: %s reaches the manager (%r)" % (league, label, want),
                  got == want, "got %r" % (got,))

    failed = [c for c, ok in results if not ok]
    print("\n%d checks, %d failed" % (len(results), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
