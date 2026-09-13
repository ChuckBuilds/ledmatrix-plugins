#!/usr/bin/env python3
"""A setting the user can change must actually reach the code that reads it.

Managers do not read the plugin config. `_adapt_config_for_manager` translates
it into the shape the managers expect, and that translation is an explicit
whitelist -- every key is named. A key missing from it is not a crash and not a
log line: the setting appears in the web UI, the user changes it, saves, and
nothing happens. The code silently keeps its own default.

That is exactly what happened to the five settings added for favourite
prioritisation, and later to update_intervals.odds. This test used to probe a
fixed list of keys, which is how odds slipped through: nobody added it to the
list. The probe list is now built from config_schema.json itself -- every leaf
setting of every league block -- so a key added to the schema is checked the
day it is added.

The check is deliberately blunt and shape-agnostic: translate a config with the
setting at a non-default value, translate one without it, and require the two
results to differ. Two distinct probe values are tried, so a probe that
happens to equal the translation's own fallback cannot fake a miss.

Keys consumed somewhere other than the translation are listed in ELSEWHERE,
each with the reason. Adding to that list needs a reason, not a shrug.

Run: <core-venv>/bin/python plugins/lacrosse-scoreboard/test_settings_reach_the_manager.py
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

#: League-block settings read outside _adapt_config_for_manager, by dotted
#: path relative to the league block.
ELSEWHERE = {
    "enabled": "plugin __init__ reads <league>.enabled into ncaa_*_enabled",
    "display_modes.live": "per-mode enable check in manager.py (display_modes_config.get('live'))",
    "display_modes.recent": "per-mode enable check in manager.py (display_modes_config.get('recent'))",
    "display_modes.upcoming": "per-mode enable check in manager.py (display_modes_config.get('upcoming'))",
    "display_modes.live_display_mode": "switch/scroll choice read by _parse_display_mode_settings",
    "display_modes.recent_display_mode": "switch/scroll choice read by _parse_display_mode_settings",
    "display_modes.upcoming_display_mode": "switch/scroll choice read by _parse_display_mode_settings",
    "display_durations.recent": "read by _get_game_duration / _get_mode_duration from the league block",
    "display_durations.upcoming": "read by _get_game_duration / _get_mode_duration from the league block",
    "display_durations.base": "declared but never read (drift report section 2)",
    "live_priority": "plugin __init__ reads it into ncaa_*_live_priority",
    "scroll_settings": "read by the core scroll display via SCROLL_LEAGUE_KEYS, not the managers",
    "mode_durations": "read by _get_mode_duration from the league block",
    "dynamic_duration": "read by supports_dynamic_duration / get_dynamic_duration_cap from the league block",
}


def _leaves(node, prefix=()):
    """(path, schema) for every non-object setting under a schema node."""
    for name, sub in ((node or {}).get("properties") or {}).items():
        if not isinstance(sub, dict):
            continue
        path = prefix + (name,)
        if sub.get("type") == "object" and isinstance(sub.get("properties"), dict):
            yield from _leaves(sub, path)
        else:
            yield path, sub


def _probe_values(spec):
    """Two distinct values differing from the schema default, or []."""
    kind = spec.get("type")
    if isinstance(kind, list):
        kind = next((k for k in kind if k != "null"), None)
    default = spec.get("default")
    if spec.get("enum"):
        return [v for v in spec["enum"] if v != default][:2]
    if kind == "boolean":
        return [not bool(default)]
    if kind in ("integer", "number"):
        lo = spec.get("minimum", 0)
        hi = spec.get("maximum", (default or 0) + 1000)
        out = []
        for cand in (lo, hi, lo + 1, hi - 1, (lo + hi) // 2):
            if lo <= cand <= hi and cand != default and cand not in out:
                out.append(cand)
        return out[:2]
    if kind == "array":
        items = spec.get("items") or {}
        if items.get("enum"):
            vals = [v for v in items["enum"] if [v] != default]
            return [[v] for v in vals[:2]]
        return [["PROBEA"], ["PROBEB", "PROBEC"]]
    if kind == "string":
        return ["probe_a", "probe_b"]
    return []


def _set(block, path, value):
    cur = block
    for key in path[:-1]:
        cur = cur.setdefault(key, {})
    cur[path[-1]] = value


def _allowlisted(path):
    dotted = ".".join(path)
    return next((reason for key, reason in ELSEWHERE.items()
                 if dotted == key or dotted.startswith(key + ".")), None)


results = []


def check(case, passed, detail=""):
    results.append((case, passed))
    print("  [%s] %s%s" % ("pass" if passed else "FAIL", case,
                           "" if passed else "  <- " + str(detail)))


def main():
    os.chdir(str(CORE))
    import manager as plugin_manager

    cls = plugin_manager.LacrosseScoreboardPlugin
    obj = cls.__new__(cls)
    obj.logger = logging.getLogger("adapt_probe")
    obj.logger.addHandler(logging.NullHandler())
    obj.logger.propagate = False
    for attr in ("cache_manager", "display_manager", "plugin_manager",
                 "config_manager", "font_manager"):
        setattr(obj, attr, MagicMock())

    def adapt(config, league):
        obj.config = config
        for _ in range(40):
            try:
                return obj._adapt_config_for_manager(league)
            except AttributeError as exc:
                name = str(exc).rsplit("'", 2)[-2] if "'" in str(exc) else ""
                if not name or hasattr(obj, name):
                    raise
                setattr(obj, name, MagicMock())
        raise RuntimeError("gave up filling in attributes")

    schema = json.load(open(plugin_dir / "config_schema.json", encoding="utf-8"))
    props = schema.get("properties") or {}
    leagues = [name for name, node in props.items()
               if isinstance(node, dict) and "display_modes" in (node.get("properties") or {})]
    if not leagues:
        print("FAILED: no league blocks found in config_schema.json")
        return 1

    probed = 0
    for league in leagues:
        print("  league: %s" % league)
        base_block = {"enabled": True, "favorite_teams": ["DUKE"]}
        baseline = adapt({league: json.loads(json.dumps(base_block))}, league)
        for path, spec in _leaves(props[league]):
            dotted = ".".join(path)
            if dotted in ("enabled", "favorite_teams", "teams.favorite_teams"):
                continue  # held fixed by the baseline
            reason = _allowlisted(path)
            if reason:
                continue
            values = _probe_values(spec)
            if not values:
                continue
            probed += 1
            reached, detail = False, "translation output unchanged"
            for value in values:
                block = json.loads(json.dumps(base_block))
                _set(block, path, value)
                try:
                    out = adapt({league: block}, league)
                except Exception as exc:
                    reached, detail = False, "%s: %s" % (type(exc).__name__, exc)
                    break
                if out != baseline:
                    reached = True
                    break
            check("%s.%s reaches the manager" % (league, dotted), reached, detail)

    if probed == 0:
        print("FAILED: the schema produced no probe-able settings")
        return 1
    failed = [c for c, ok in results if not ok]
    print("\n%d checks, %d failed" % (len(results), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
