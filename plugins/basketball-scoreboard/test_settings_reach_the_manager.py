#!/usr/bin/env python3
"""A setting the user can change must actually reach the code that reads it.

Managers do not read the plugin config. `_adapt_config_for_manager` translates
it into the shape the managers expect, and that translation is an explicit
whitelist -- every key is named. A key missing from it is not a crash and not a
log line: the setting appears in the web UI, the user changes it, saves, and
nothing happens. The code silently keeps its own default.

That is exactly what happened to the five settings added for favourite
prioritisation, and later to odds_update_interval: declared (or read), shown,
and never passed through.

The probe list is built from config_schema.json, not typed out here. A fixed
list only ever covered the keys someone remembered, which is how a dead
setting in a sibling plugin sat next to a passing copy of this test. Every
leaf the schema declares on a league block, and every plugin-root key, is set
to a value that is NOT its default, run through the real translation, and must
arrive. A key that is legitimately consumed somewhere other than the league
managers is allowlisted below with the reason, so adding a schema key without
either forwarding it or explaining it fails here.

Run: <core-venv>/bin/python plugins/basketball-scoreboard/test_settings_reach_the_manager.py
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

#: League-block keys the league managers do not read, and who does.
LEAGUE_ALLOW = {
    "enabled": "the fixture turns the league on; forwarded verbatim",
    "favorite_teams": "the fixture sets it; forwarded verbatim",
    "display_modes": "show_* are renamed to <league>_live/_recent/_upcoming "
                     "(checked separately below); *_display_mode is read from "
                     "the plugin config by manager._get_display_mode",
    "scroll_settings": "read from the plugin config by the scroll display",
    "display_durations": "read from the plugin config by manager.get_display_duration",
    "dynamic_duration": "read from the plugin config by the manager's "
                        "dynamic-duration helpers",
    "mode_durations": "read from the plugin config by manager.get_display_duration",
}

#: Plugin-root keys the league managers do not read, and who does.
ROOT_ALLOW = {
    "enabled": "read by the core plugin manager",
    "display_duration": "read by the core plugin manager",
    "update_interval": "read by the core plugin manager (the manifest wins)",
    "game_display_duration": "read by manager.py from the plugin config",
    "background_service": "plugin-level; the adapter pins the per-league "
                          "service settings",
    "timezone": "resolved into the adapter's root 'timezone' (checked separately)",
}


def check(case, passed, detail=""):
    results.append((case, passed))
    print("  [%s] %s%s" % ("pass" if passed else "FAIL", case,
                           "" if passed else "  <- " + str(detail)))


def _types(spec):
    t = spec.get("type")
    return set(t) if isinstance(t, list) else {t}


def probe_value(spec):
    """A value valid for ``spec`` that differs from its default."""
    default = spec.get("default")
    if "enum" in spec:
        return next(v for v in spec["enum"] if v != default)
    types = _types(spec)
    if "boolean" in types:
        return not bool(default)
    if "integer" in types or "number" in types:
        lo = spec.get("minimum", 0)
        hi = spec.get("maximum", 10 ** 6)
        base = default if isinstance(default, (int, float)) else lo
        step = 7 if "integer" in types else 1.5
        for cand in (base + step, base - step, lo, hi, lo + 1):
            if lo <= cand <= hi and cand != default:
                return int(cand) if "integer" in types else cand
        raise AssertionError("no probe value for %r" % spec)
    if "array" in types:
        items = spec.get("items") or {}
        if "enum" in items:
            return [next(v for v in items["enum"] if v not in (default or []))]
        return ["PROBE"]
    if "object" in types:
        return {k: probe_value(v) for k, v in (spec.get("properties") or {}).items()
                if not (v.get("type") == "object")}
    return "probe-value"


def main():
    os.chdir(str(CORE))
    import manager as plugin_manager
    import logging
    from unittest.mock import MagicMock

    cls = next(obj for obj in vars(plugin_manager).values()
               if isinstance(obj, type) and hasattr(obj, "_adapt_config_for_manager"))
    obj = cls.__new__(cls)
    obj.logger = logging.getLogger("adapt_probe")
    for attr in ("cache_manager", "display_manager", "plugin_manager",
                 "config_manager", "font_manager"):
        setattr(obj, attr, MagicMock())

    def adapt(league):
        # Fill in collaborators the translation reads, bounded so a genuine
        # AttributeError still surfaces.
        for _ in range(40):
            try:
                return obj._adapt_config_for_manager(league)
            except AttributeError as exc:
                name = str(exc).rsplit("'", 2)[-2] if "'" in str(exc) else ""
                if not name or hasattr(obj, name):
                    raise
                setattr(obj, name, MagicMock())
        raise RuntimeError("gave up filling in attributes")

    schema = json.loads((plugin_dir / "config_schema.json").read_text(encoding="utf-8"))
    props = schema["properties"]
    leagues = [name for name, node in props.items()
               if isinstance(node, dict) and "game_limits" in (node.get("properties") or {})]
    check("the schema declares league blocks", bool(leagues), leagues)

    for league in leagues:
        print("\n  league: %s" % league)
        block_props = props[league]["properties"]
        probes = {}          # leaf -> (path, value)
        block = {"enabled": True, "favorite_teams": ["UGA"]}
        for key, spec in block_props.items():
            if key in LEAGUE_ALLOW:
                continue
            if spec.get("type") == "object" and spec.get("properties"):
                sub_block = block.setdefault(key, {})
                for sub, sub_spec in spec["properties"].items():
                    assert sub not in probes, "leaf name %s declared twice" % sub
                    value = probe_value(sub_spec)
                    sub_block[sub] = value
                    probes[sub] = ((key, sub), value)
            else:
                assert key not in probes, "leaf name %s declared twice" % key
                value = probe_value(spec)
                block[key] = value
                probes[key] = ((key,), value)
        block["display_modes"] = {"show_live": False, "show_recent": False,
                                  "show_upcoming": False}

        obj.config = {league: block}
        try:
            adapted = adapt(league)
        except Exception as exc:
            check("%s: the translation survives the probe config" % league, False,
                  "%s: %s" % (type(exc).__name__, exc))
            continue
        landed = max((v for v in adapted.values() if isinstance(v, dict)),
                     key=lambda v: sum(1 for leaf in probes if leaf in v))

        for leaf, (path, want) in sorted(probes.items()):
            got = landed.get(leaf, (landed.get(path[0]) or {}).get(leaf)
                             if len(path) == 2 and isinstance(landed.get(path[0]), dict)
                             else None)
            check("%s.%s reaches the manager" % (league, ".".join(path)),
                  got == want, "got %r, want %r" % (got, want))

        modes = landed.get("display_modes") or {}
        check("%s.display_modes.show_* reach the manager as %s_live/_recent/_upcoming"
              % (league, league),
              all(modes.get("%s_%s" % (league, m)) is False
                  for m in ("live", "recent", "upcoming")), modes)

    # -- plugin-root keys --
    print("\n  plugin root")
    root_probes = {}
    root_config = {}
    for key, spec in props.items():
        if key in leagues or key in ROOT_ALLOW:
            continue
        value = probe_value(spec)
        root_config[key] = value
        root_probes[key] = value
    root_config["timezone"] = "America/Chicago"
    league = leagues[0]
    root_config[league] = {"enabled": True}
    obj.config = root_config
    adapted = adapt(league)
    for key, want in sorted(root_probes.items()):
        check("root %s reaches the manager" % key, adapted.get(key) == want,
              "got %r" % (adapted.get(key),))
    check("root timezone reaches the manager",
          adapted.get("timezone") == "America/Chicago", adapted.get("timezone"))

    failed = [c for c, ok in results if not ok]
    print("\n%d checks, %d failed" % (len(results), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
