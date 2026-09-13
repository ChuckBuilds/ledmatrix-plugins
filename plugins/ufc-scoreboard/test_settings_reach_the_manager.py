#!/usr/bin/env python3
"""A setting the user can change must actually reach the code that reads it.

Managers do not read the plugin config. `_adapt_config_for_manager` translates
it into the shape the managers expect, and that translation is an explicit
whitelist -- every key is named. A key missing from it is not a crash and not a
log line: the setting appears in the web UI, the user changes it, saves, and
nothing happens. The code silently keeps its own default.

The probe list is built from config_schema.json rather than a fixed key list:
a fixed list only ever checks the keys someone remembered to add to it, which
is exactly the failure mode being tested for. Every scalar or list setting the
schema declares on the `ufc` block (and its game_limits / display_options /
filtering sub-blocks) is set to a value that is NOT its default, placed where
the schema declares it, run through the real translation, and must arrive.
Keys consumed somewhere other than the managers are allowlisted below, each
with the reason.

Run: <core-venv>/bin/python plugins/ufc-scoreboard/test_settings_reach_the_manager.py
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

LEAGUE = "ufc"

#: Sub-blocks of the league block whose keys the adapter flattens into the
#: manager config.
FLATTENED_BLOCKS = ("game_limits", "display_options", "filtering")

#: Schema key -> the name the managers read it under.
RENAMED = {
    "favorite_weight_classes": "favorite_weight_class",
}

#: League-block keys that are not the managers' to receive, with the reason.
NOT_FOR_MANAGERS = {
    # manager.py _parse_display_mode_settings reads these off the plugin config.
    "display_modes": "restructured into show_* flags; *_display_mode read by manager.py",
    # ScrollDisplayManager is handed the plugin config itself.
    "scroll_settings": "read by scroll_display.py from the plugin config",
    # Dynamic duration is a plugin-level feature, read in manager.py.
    "dynamic_duration": "read by manager.py _get_dynamic_duration_value",
}

#: Plugin-root keys that are not forwarded, with the reason.
ROOT_NOT_FORWARDED = {
    "enabled": "read by the core plugin manager and manager.py __init__",
    "display_duration": "read by the core scheduler and manager.py __init__",
    "update_interval": "core scheduler setting (the manifest value wins)",
    "game_display_duration": "read by manager.py __init__",
    "timezone": "resolved by ufc_timezone.resolve_timezone_name; see test_timezone_resolution.py",
}

results = []


def check(case, passed, detail=""):
    results.append((case, passed))
    print("  [%s] %s%s" % ("pass" if passed else "FAIL", case,
                           "" if passed else "  <- " + str(detail)))


def probe_value(node):
    """A schema-valid value that differs from the node's default."""
    kind = node.get("type")
    default = node.get("default")
    if "enum" in node:
        for option in node["enum"]:
            if option != default:
                return option
    if kind == "boolean":
        return not bool(default)
    if kind == "integer":
        base = default if isinstance(default, int) else 0
        high, low = node.get("maximum"), node.get("minimum")
        for candidate in (base + 7, base - 1, low, high):
            if candidate is None or candidate == default:
                continue
            if (low is None or candidate >= low) and (high is None or candidate <= high):
                return candidate
        return base + 1
    if kind == "number":
        base = default if isinstance(default, (int, float)) else 0
        high = node.get("maximum")
        candidate = base + 1.5
        if high is not None and candidate > high:
            candidate = base - 0.5
        return candidate
    if kind == "string":
        return "probe-value"
    if kind == "array":
        item_enum = (node.get("items") or {}).get("enum")
        if item_enum:
            return [item_enum[-1]]
        return ["probe-value"]
    return None


def main():
    os.chdir(str(CORE))
    import manager as plugin_manager

    cls = plugin_manager.UFCScoreboardPlugin
    schema = json.load(open(plugin_dir / "config_schema.json"))
    props = schema.get("properties") or {}
    league_props = (props.get(LEAGUE) or {}).get("properties") or {}
    if not league_props:
        print("FAILED: the schema declares no %r block" % LEAGUE)
        return 1

    # (key, where-declared, probe) for every setting the schema offers.
    probes = []
    for key, node in league_props.items():
        if key in NOT_FOR_MANAGERS:
            continue
        if key in FLATTENED_BLOCKS:
            for sub_key, sub_node in (node.get("properties") or {}).items():
                value = probe_value(sub_node)
                if value is not None:
                    probes.append((sub_key, key, value))
            continue
        if node.get("type") == "object":
            check("league key %r is either forwarded or allowlisted" % key, False,
                  "object setting with no rule in this test")
            continue
        value = probe_value(node)
        if value is not None:
            probes.append((key, None, value))

    root_probes = {}
    for key, node in props.items():
        if key == LEAGUE or key in ROOT_NOT_FORWARDED:
            continue
        if node.get("type") == "object":
            continue  # customization: forwarded whole, checked below
        value = probe_value(node)
        if value is not None:
            root_probes[key] = value

    league_block = {}
    for key, where, value in probes:
        if where is None:
            league_block[key] = value
        else:
            league_block.setdefault(where, {})[key] = value

    obj = cls.__new__(cls)
    obj.logger = logging.getLogger("adapt_probe")
    for attr in ("cache_manager", "display_manager", "plugin_manager",
                 "config_manager", "font_manager"):
        setattr(obj, attr, MagicMock())
    customization = {"layout": {"odds": {"x_offset": 3}}}
    obj.config = dict(root_probes, **{LEAGUE: league_block,
                                      "customization": customization})

    adapted = obj._adapt_config_for_manager(LEAGUE)
    block = adapted.get("%s_scoreboard" % LEAGUE)
    if not isinstance(block, dict):
        print("FAILED: the translation produced no %s_scoreboard block" % LEAGUE)
        return 1

    print("  %d league settings, %d root settings from the schema"
          % (len(probes), len(root_probes)))
    for key, where, want in probes:
        name = RENAMED.get(key, key)
        got = block.get(name)
        check("%s%s reaches the manager as %s (%r)"
              % ((where + ".") if where else "", key, name, want),
              got == want, "got %r" % (got,))

    for key, want in root_probes.items():
        got = adapted.get(key)
        check("root %s reaches the manager config (%r)" % (key, want),
              got == want, "got %r" % (got,))
    check("customization reaches the manager config",
          adapted.get("customization") == customization,
          "got %r" % (adapted.get("customization"),))

    failed = [c for c, ok in results if not ok]
    print("\n%d checks, %d failed" % (len(results), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
