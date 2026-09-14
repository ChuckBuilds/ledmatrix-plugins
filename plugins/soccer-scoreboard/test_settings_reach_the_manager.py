#!/usr/bin/env python3
"""A setting the user can change must actually reach the code that reads it.

Managers do not read the plugin config. `_adapt_config_for_manager` translates
it into the shape the managers expect, and that translation is an explicit
whitelist -- every key is named. A key missing from it is not a crash and not a
log line: the setting appears in the web UI, the user changes it, saves, and
nothing happens. The code silently keeps its own default.

This used to probe a fixed list of eight keys, which is how the celebration
settings (declared in every league block, read by SportsLive, never forwarded)
and the odds intervals sat inert while this test passed. The probe is now built
from config_schema.json itself: every leaf the schema offers in a league block
(and in a custom league) is set to a value that is NOT its default, the real
translation runs, and the value has to arrive. A key that is legitimately
consumed somewhere other than the managers is allowlisted below with the reason,
so adding a schema key without either forwarding it or explaining it fails.

Run: <core-venv>/bin/python plugins/soccer-scoreboard/test_settings_reach_the_manager.py
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

# League-block keys (first path segment) that are consumed outside the
# translated manager block. Each needs a reason; anything else must arrive.
LEAGUE_ALLOW = {
    "display_modes": "translated into soccer_<league>_<mode> flags; the "
                     "*_display_mode keys are read by manager._parse_display_mode_settings",
    "dynamic_duration": "read by manager.py's dynamic-duration hooks from the plugin config",
    "mode_durations": "read by manager._get_mode_duration from the plugin config",
    "scroll_settings": "retired in 2.27.0: never read (the strip is one multi-league "
                       "surface); kept declared only so saved configs still validate",
}

# Custom-league item keys consumed outside the manager block.
CUSTOM_ALLOW = {
    "name": "arrives renamed as league_name",
    "priority": "read by manager._load_custom_leagues for registry ordering",
    "display_modes": "container; translated into soccer_<code>_<mode> flags",
    "game_limits": "container; its keys are forwarded individually",
    "filtering": "container; forwarded as-is and flattened",
    "dynamic_duration": "read by manager.py's dynamic-duration hooks",
}

# Plugin-root keys. Root keys SportsCore reads are forwarded via
# _ROOT_CONFIG_KEYS and checked; every other root key needs a reason.
ROOT_ALLOW = {
    "enabled": "plugin on/off, read by the core and manager.py",
    "display_duration": "read by the core scheduler and manager.py",
    "game_display_duration": "read by manager.py",
    "timezone": "resolved by resolve_timezone_name and forwarded as 'timezone'",
    "leagues": "container this adapter translates",
    "custom_leagues": "container translated by _adapt_config_for_custom_league",
    "customization": "forwarded whole as 'customization' (checked below)",
    "background_service": "not forwarded: the adapter pins request_timeout/"
                          "max_retries/priority per league (legacy duplicate)",
}
# Root duplicates of league-block keys. After the core merges schema defaults
# every league block carries its own copy, which always wins, so the root copy
# is only the adapter's last-resort fallback.
for _dup in ("show_records", "show_ranking", "show_odds", "live_game_duration",
             "update_interval_seconds", "live_update_interval",
             "stale_game_timeout", "recent_update_interval",
             "upcoming_update_interval", "recent_games_to_show",
             "upcoming_games_to_show", "show_favorite_teams_only",
             "other_upcoming_games_to_show", "other_recent_games_to_show",
             "other_rotation_interval_seconds", "favorite_rotation_boost",
             "other_games_min_quality", "other_games_divisions"):
    ROOT_ALLOW[_dup] = "root duplicate of the league-block key, which wins"

results = []


def check(case, passed, detail=""):
    results.append((case, passed))
    print("  [%s] %s%s" % ("pass" if passed else "FAIL", case,
                           "" if passed else "  <- " + str(detail)))


def leaves(node, path=()):
    """(path, schema node) for every leaf property under ``node``."""
    for key, child in (node.get("properties") or {}).items():
        if not isinstance(child, dict):
            continue
        if child.get("type") == "object" and child.get("properties"):
            yield from leaves(child, path + (key,))
        else:
            yield path + (key,), child


def probe_value(node):
    """A schema-valid value that differs from the node's default."""
    default = node.get("default")
    types = node.get("type")
    types = [t for t in (types if isinstance(types, list) else [types]) if t != "null"]
    kind = types[0] if types else None
    if node.get("enum"):
        others = [v for v in node["enum"] if v != default]
        if others:
            return others[0]
    if kind == "boolean":
        return not default if isinstance(default, bool) else True
    if kind in ("integer", "number"):
        lo = node.get("minimum", 0)
        hi = node.get("maximum", 10 ** 6)
        base = default if isinstance(default, (int, float)) else lo
        for cand in (base + 7, lo + 1, hi, lo):
            if lo <= cand <= hi and cand != default:
                return int(cand) if kind == "integer" else float(cand)
    if kind == "array":
        return ["zz-probe"]
    return "zz-probe"


def set_path(target, path, value):
    for key in path[:-1]:
        target = target.setdefault(key, {})
    target[path[-1]] = value


def arrived(block, path, want):
    """The value is in the manager block, flattened or under its sub-block."""
    if block.get(path[-1]) == want:
        return True
    if len(path) > 1:
        sub = block.get(path[0])
        return isinstance(sub, dict) and sub.get(path[-1]) == want
    return False


def make_plugin(cls):
    obj = cls.__new__(cls)
    obj.logger = logging.getLogger("adapt_probe")
    for attr in ("cache_manager", "display_manager", "plugin_manager",
                 "config_manager", "font_manager"):
        setattr(obj, attr, MagicMock())
    return obj


def main():
    os.chdir(str(CORE))
    import manager as plugin_manager

    cls = next((obj for obj in vars(plugin_manager).values()
                if isinstance(obj, type) and hasattr(obj, "_adapt_config_for_manager")
                and hasattr(obj, "_adapt_config_for_custom_league")), None)
    if cls is None:
        print("FAILED: no plugin class with both adapters")
        return 1

    schema = json.load(open(plugin_dir / "config_schema.json", encoding="utf-8"))
    props = schema["properties"]
    league = "eng.1"
    league_schema = props["leagues"]["properties"][league]

    # --- predefined league block -----------------------------------------
    print("league block (%s), probe built from the schema" % league)
    block_cfg, expected = {}, []
    for path, node in leaves(league_schema):
        if path[0] in LEAGUE_ALLOW:
            continue
        value = probe_value(node)
        set_path(block_cfg, path, value)
        expected.append((path, value))
    check("the schema offers something to probe", len(expected) > 20, len(expected))

    obj = make_plugin(cls)
    obj.config = {"leagues": {league: block_cfg}, "customization": {"zz": 1}}
    adapted = obj._adapt_config_for_manager(league)
    block = adapted.get("soccer_%s_scoreboard" % league, {})
    for path, want in expected:
        check("%s reaches the manager" % ".".join(path),
              arrived(block, path, want), "got %r" % (block.get(path[-1]),))
    check("customization is forwarded whole",
          adapted.get("customization") == {"zz": 1}, adapted.get("customization"))

    # Every allowlisted prefix has to still exist in the schema, or the
    # allowlist is hiding nothing and should shrink.
    for key in LEAGUE_ALLOW:
        if key == "scroll_settings":
            continue  # retired block may be property-less
        check("allowlisted league key %s is still declared" % key,
              key in (league_schema.get("properties") or {}))

    # --- plugin root -------------------------------------------------------
    print("\nplugin root keys")
    root_keys = getattr(plugin_manager, "_ROOT_CONFIG_KEYS", ())
    root_cfg = {"leagues": {league: {}}}
    root_expected = []
    for key, node in props.items():
        if key in ROOT_ALLOW:
            continue
        value = probe_value(node) if node.get("type") != "object" else {"zz": 2}
        root_cfg[key] = value
        root_expected.append((key, value))
    obj.config = root_cfg
    adapted = obj._adapt_config_for_manager(league)
    for key, want in root_expected:
        check("root %s is forwarded (or allowlisted)" % key,
              key in root_keys and adapted.get(key) == want,
              "not in _ROOT_CONFIG_KEYS" if key not in root_keys
              else "got %r" % (adapted.get(key),))

    # --- custom league -----------------------------------------------------
    print("\ncustom league item")
    item_schema = props["custom_leagues"]["items"]
    custom = {"league_code": "sco.1", "name": "Scottish Premiership"}
    custom_expected = []
    for path, node in leaves(item_schema):
        if path[0] in CUSTOM_ALLOW or path[0] == "league_code":
            continue
        value = probe_value(node)
        set_path(custom, path, value)
        custom_expected.append((path, value))
    adapted = obj._adapt_config_for_custom_league(custom)
    block = adapted.get("soccer_sco.1_scoreboard", {})
    for path, want in custom_expected:
        check("custom %s reaches the manager" % ".".join(path),
              arrived(block, path, want), "got %r" % (block.get(path[-1]),))
    check("custom league_code arrives", block.get("league_code") == "sco.1")
    check("custom name arrives as league_name",
          block.get("league_name") == "Scottish Premiership")

    failed = [c for c, ok in results if not ok]
    print("\n%d checks, %d failed" % (len(results), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
