#!/usr/bin/env python3
"""A setting the user can change must actually reach the code that reads it.

Managers do not read the plugin config. `_adapt_config_for_manager` translates
it into the shape the managers expect, and that translation is an explicit
whitelist -- every key is named. A key missing from it is not a crash and not a
log line: the setting appears in the web UI, the user changes it, saves, and
nothing happens. The code silently keeps its own default.

That is exactly what happened to the five settings added for favourite
prioritisation, and later to update_intervals.odds and test_mode. A fixed list
of keys to probe could only ever catch the bugs somebody already knew about,
so the probe list is now built from config_schema.json itself: every leaf
setting of every league block, and every plugin-root setting, is set -- at the
place the schema declares it, to a value that is NOT its default -- and the
translated config must change. A key the adapter does not read leaves the
translation untouched and fails, unless ALLOWLIST names it with the reason it
is legitimately consumed somewhere else.

Run: <core-venv>/bin/python plugins/hockey-scoreboard/test_settings_reach_the_manager.py
"""

import copy
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

LEAGUES = ("nhl", "ncaa_mens", "ncaa_womens")

#: Schema paths (league-relative for league blocks, prefixed "<root>." for
#: plugin-root settings) that legitimately do not pass through the adapter.
#: Each needs a reason; a new entry without one is a bug being hidden.
ALLOWLIST = {
    # Read straight from the plugin config by the core scroll engine
    # (SportsScrollDisplay._get_scroll_settings walks config[league]).
    "scroll_settings.*": "core sports_scroll reads config[league] directly",
    # Read by manager.py itself for mode timing, not by the league managers.
    "mode_durations.*": "manager.py reads it for per-mode durations",
    "display_modes.live_display_mode": "manager.py _parse_display_mode_settings (switch/scroll)",
    "display_modes.recent_display_mode": "manager.py _parse_display_mode_settings (switch/scroll)",
    "display_modes.upcoming_display_mode": "manager.py _parse_display_mode_settings (switch/scroll)",
    "dynamic_duration.*": "manager.py reads it for dynamic duration",
    "display_durations.recent": "manager.py reads it for per-game dwell",
    "display_durations.upcoming": "manager.py reads it for per-game dwell",
    # Declared but never read anywhere (audit dead-code list); left for the
    # schema owner rather than silently wired to something.
    "display_durations.base": "dead schema key: nothing reads it",
    "<root>.enabled": "plugin on/off, read by the core plugin manager",
    "<root>.defaults.display_duration": "manager.py __init__ reads it",
    "<root>.defaults.show_records": "manager.py __init__ reads it (adapter fallback)",
    "<root>.defaults.show_ranking": "manager.py __init__ reads it (adapter fallback)",
    "<root>.defaults.show_odds": "manager.py __init__ reads it (adapter fallback)",
    "<root>.defaults.show_shots_on_goal": "adapter reads defaults only on nested paths; flat defaults are legacy",
    "<root>.defaults.show_powerplay": "adapter reads defaults only on nested paths; flat defaults are legacy",
    "<root>.defaults.update_interval_seconds": "adapter reads defaults only on nested paths; flat defaults are legacy",
    "<root>.defaults.season_cache_duration_seconds": "dead schema key: nothing reads it",
}

results = []


def check(case, passed, detail=""):
    results.append((case, passed))
    print("  [%s] %s%s" % ("pass" if passed else "FAIL", case,
                           "" if passed else "  <- " + str(detail)))


def allowlisted(path):
    for pattern in ALLOWLIST:
        if pattern.endswith(".*"):
            if path.startswith(pattern[:-1]):
                return True
        elif path == pattern:
            return True
    return False


def leaves(props, prefix=()):
    """(path, node) for every non-object setting under a schema properties map."""
    for name, node in (props or {}).items():
        if not isinstance(node, dict):
            continue
        if node.get("type") == "object" and isinstance(node.get("properties"), dict):
            yield from leaves(node["properties"], prefix + (name,))
        else:
            yield prefix + (name,), node


#: Settings whose generic probe would be rejected as invalid (and so resolve
#: to the same fallback as the default, which looks like a dropped key).
PROBE_OVERRIDES = {
    "timezone": "Asia/Tokyo",
}


def probe_value(node, name=""):
    """A valid value for this setting that is not its default."""
    if name in PROBE_OVERRIDES:
        return PROBE_OVERRIDES[name]
    default = node.get("default")
    if node.get("enum"):
        for option in node["enum"]:
            if option != default:
                return option
    kind = node.get("type")
    if isinstance(kind, list):
        kind = next((k for k in kind if k != "null"), "string")
    if kind == "boolean":
        return not bool(default)
    if kind in ("integer", "number"):
        lo = node.get("minimum", 0)
        hi = node.get("maximum", lo + 1000)
        for candidate in (lo + (hi - lo) // 3 + 1, lo, hi, lo + 1):
            candidate = int(candidate) if kind == "integer" else float(candidate) + 0.25
            if candidate != default and lo <= candidate <= hi:
                return candidate
        return hi
    if kind == "array":
        return ["PROBE"]
    return "probe-value"


def set_path(target, path, value):
    for key in path[:-1]:
        target = target.setdefault(key, {})
    target[path[-1]] = value


def main():
    os.chdir(str(CORE))
    import manager as plugin_manager

    cls = plugin_manager.HockeyScoreboardPlugin
    obj = cls.__new__(cls)
    obj.logger = logging.getLogger("adapt_probe")
    for attr in ("cache_manager", "display_manager", "plugin_manager",
                 "config_manager", "font_manager"):
        setattr(obj, attr, MagicMock())
    obj.show_records = False
    obj.show_ranking = False
    obj.show_odds = False

    schema = json.loads((plugin_dir / "config_schema.json").read_text(encoding="utf-8"))
    props = schema["properties"]

    def adapt(config, league):
        obj.config = config
        return json.dumps(obj._adapt_config_for_manager(league),
                          sort_keys=True, default=repr)

    base_config = {"enabled": True, "timezone": "America/Chicago"}
    for league in LEAGUES:
        base_config[league] = {"enabled": True}

    unreached = []
    checked = 0

    def baseline_for(path, node, league_or_root):
        """The translation with this one setting at its schema default.

        Comparing against a config that merely omits the key would pass or
        fail on whether the adapter's own fallback happens to equal the probe
        -- the core merges schema defaults in, so the default is the value a
        real config holds."""
        config = copy.deepcopy(base_config)
        if "default" in node:
            target = config if league_or_root is None else config[league_or_root]
            set_path(target, path, node["default"])
        return config

    print("league settings, from the schema")
    for league in LEAGUES:
        for path, node in leaves(props[league]["properties"]):
            dotted = ".".join(path)
            if dotted == "enabled":
                continue
            baseline = adapt(baseline_for(path, node, league), league)
            config = copy.deepcopy(base_config)
            set_path(config[league], path, probe_value(node))
            try:
                changed = adapt(config, league) != baseline
            except Exception as exc:
                check("%s.%s translates" % (league, dotted), False,
                      "%s: %s" % (type(exc).__name__, exc))
                continue
            checked += 1
            if not changed and not allowlisted(dotted):
                unreached.append("%s.%s" % (league, dotted))

    print("plugin-root settings, from the schema")
    for name, node in props.items():
        if name in LEAGUES:
            continue
        sub = node.get("properties") if node.get("type") == "object" else None
        items = leaves(sub, (name,)) if isinstance(sub, dict) else [((name,), node)]
        for path, leaf in items:
            dotted = "<root>." + ".".join(path)
            baseline = adapt(baseline_for(path, leaf, None), "nhl")
            config = copy.deepcopy(base_config)
            set_path(config, path, probe_value(leaf, path[-1]))
            try:
                changed = adapt(config, "nhl") != baseline
            except Exception as exc:
                check("%s translates" % dotted, False, "%s: %s" % (type(exc).__name__, exc))
                continue
            checked += 1
            if not changed and not allowlisted(dotted):
                unreached.append(dotted)

    check("probed %d schema settings (the schema was actually walked)" % checked,
          checked > 100, checked)
    check("every schema setting reaches the managers or is allowlisted",
          not unreached, ", ".join(unreached))

    print("\nexact values for the settings that have bitten before")
    config = copy.deepcopy(base_config)
    config["nhl"].update({
        "filtering": {"other_games_divisions": "fcs",
                      "other_games_min_quality": "broadcast",
                      "other_rotation_interval_seconds": 900},
        "update_intervals": {"odds": 7200, "live_odds": 90,
                             "recent": 1234, "upcoming": 2345,
                             "stale_game_timeout": 456},
        "test_mode": True,
    })
    obj.config = config
    block = obj._adapt_config_for_manager("nhl")["nhl_scoreboard"]
    for key, want in (("other_games_divisions", "fcs"),
                      ("other_games_min_quality", "broadcast"),
                      ("other_rotation_interval_seconds", 900),
                      ("odds_update_interval", 7200),
                      ("live_odds_update_interval", 90),
                      ("recent_update_interval", 1234),
                      ("upcoming_update_interval", 2345),
                      ("stale_game_timeout", 456),
                      ("test_mode", True)):
        check("%s arrives as %r" % (key, want), block.get(key) == want,
              "got %r" % (block.get(key),))

    print("\nother_games_divisions is passed through, not list()-ed")
    for raw in (None, 5):
        config = copy.deepcopy(base_config)
        config["nhl"]["filtering"] = {"other_games_divisions": raw}
        obj.config = config
        try:
            obj._adapt_config_for_manager("nhl")
            check("a %r value does not break the translation" % (raw,), True)
        except Exception as exc:
            check("a %r value does not break the translation" % (raw,), False,
                  "%s: %s" % (type(exc).__name__, exc))

    failed = [c for c, ok in results if not ok]
    print("\n%d checks, %d failed" % (len(results), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
