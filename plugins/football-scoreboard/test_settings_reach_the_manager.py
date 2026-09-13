#!/usr/bin/env python3
"""A setting the user can change must actually reach the code that reads it.

Managers do not read the plugin config. `_adapt_config_for_manager` translates
it into the shape the managers expect, and that translation is an explicit
whitelist -- every key is named. A key missing from it is not a crash and not a
log line: the setting appears in the web UI, the user changes it, saves, and
nothing happens. The code silently keeps its own default.

That is exactly what happened to the five settings added for favourite
prioritisation, and later to the odds refresh intervals. The probe list used
to be a fixed set of keys, so a setting added to the schema and forgotten in
the translation passed this test. It is now built from config_schema.json:
every setting the league block declares gets a value that differs from its
default, goes through the real translation, and must arrive -- or be named in
ALLOWLIST with the reason it is read somewhere other than the managers.

Run: <core-venv>/bin/python plugins/football-scoreboard/test_settings_reach_the_manager.py
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

LEAGUES = ("nfl", "ncaa_fb")

#: League-block settings that deliberately do not go through the manager
#: translation, keyed by schema path (sub-block names joined with ".").
ALLOWLIST = {
    # Translated to "<league>_live" etc. by name, and the *_display_mode keys
    # are read by the plugin itself (manager.py _parse_display_mode_settings).
    "display_modes": "read from the plugin config by manager.py, not the managers",
    # The scroll display is handed the plugin config directly.
    "scroll_settings": "read from the plugin config by scroll_display.py",
    # get_cycle_duration and friends read the plugin config.
    "dynamic_duration": "read from the plugin config by manager.py",
}

#: Plugin-root settings and where they are read, when not by the managers.
ROOT_ALLOWLIST = {
    "enabled": "read by the core plugin loader",
    "display_duration": "read by the core display controller and the plugin",
    "update_interval": "read by the core scheduler (the manifest value wins)",
    "game_display_duration": "read by the plugin itself (manager.py)",
    "nfl": "league block, checked key by key below",
    "ncaa_fb": "league block, checked key by key below",
    # Resolved (override -> global -> system zone) rather than copied.
    "timezone": "resolved by resolve_timezone_name before it is forwarded",
}

results = []


def check(case, passed, detail=""):
    results.append((case, passed))
    print("  [%s] %s%s" % ("pass" if passed else "FAIL", case,
                           "" if passed else "  <- " + str(detail)))


def probe_value(node):
    """A valid value for this schema node that is not its default."""
    kind = node.get("type")
    default = node.get("default")
    if "enum" in node:
        others = [v for v in node["enum"] if v != default]
        return others[0] if others else default
    if kind == "boolean":
        return not bool(default)
    if kind in ("integer", "number"):
        low, high = node.get("minimum"), node.get("maximum")
        if low is not None and high is not None:
            value = (low + high) / 2
        else:
            value = (default or 0) * 2 + 7
        if kind == "integer":
            value = int(value)
        if value == default:
            value = value + 1
        return value
    if kind == "array":
        return ["ZZ_PROBE"]
    if kind == "string":
        return "zz_probe"
    if kind == "object":
        return {"zz_probe": True}
    return "zz_probe"


def league_probes(block_schema):
    """[(schema path, sub-block or None, key, value)] for one league block."""
    probes = []
    for key, node in (block_schema.get("properties") or {}).items():
        if key in ALLOWLIST:
            continue
        if node.get("type") == "object" and isinstance(node.get("properties"), dict):
            for sub_key, sub_node in node["properties"].items():
                path = "%s.%s" % (key, sub_key)
                if path in ALLOWLIST:
                    continue
                probes.append((path, key, sub_key, probe_value(sub_node)))
        else:
            probes.append((key, None, key, probe_value(node)))
    return probes


def main():
    os.chdir(str(CORE))
    import manager as plugin_manager

    schema = json.load(open(plugin_dir / "config_schema.json", encoding="utf-8"))
    props = schema["properties"]

    plugin = plugin_manager.FootballScoreboardPlugin.__new__(
        plugin_manager.FootballScoreboardPlugin)
    plugin.logger = logging.getLogger("adapt_probe")
    logging.disable(logging.CRITICAL)
    plugin.cache_manager = MagicMock()
    plugin.plugin_manager = None

    # Root keys: forwarded to the root of the translated config, or allowlisted.
    root_config = {}
    root_probes = {}
    for key, node in props.items():
        if key in ROOT_ALLOWLIST:
            continue
        root_probes[key] = probe_value(node)
        root_config[key] = root_probes[key]

    for league in LEAGUES:
        block_schema = props[league]
        probes = league_probes(block_schema)
        block = {}
        for _path, sub, key, value in probes:
            if sub is None:
                block[key] = value
            else:
                block.setdefault(sub, {})[key] = value
        block["enabled"] = True
        config = dict(root_config)
        config["timezone"] = "America/Chicago"
        config[league] = block
        plugin.config = config
        adapted = plugin._adapt_config_for_manager(league)
        out = adapted.get("%s_scoreboard" % league, {})

        for path, sub, key, want in probes:
            if path == "enabled":
                continue
            got = out.get(key)
            if got != want and sub is not None:
                got = (out.get(sub) or {}).get(key)
            check("%s.%s reaches the manager (%r)" % (league, path, want),
                  got == want, "got %r" % (got,))

        if league == LEAGUES[0]:
            for key, want in root_probes.items():
                got = adapted.get(key)
                check("root %s reaches the manager (%r)" % (key, want),
                      got == want, "got %r" % (got,))

    # test_mode is not a schema setting, but the harness depends on it.
    plugin.config = {"timezone": "America/Chicago",
                     "nfl": {"enabled": True, "test_mode": True}}
    check("test_mode is forwarded",
          plugin._adapt_config_for_manager("nfl")["nfl_scoreboard"].get("test_mode") is True)

    failed = [c for c, ok in results if not ok]
    print("\n%d checks, %d failed" % (len(results), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
