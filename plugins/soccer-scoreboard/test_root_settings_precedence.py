#!/usr/bin/env python3
"""Plugin-root settings that duplicate a league setting must do something.

config_schema.json declares eighteen keys both at the plugin root and inside
every league block (show_records/show_ranking/show_odds, the update intervals,
live_game_duration, the game limits and the other-games selection keys,
show_favorite_teams_only). Both copies render in the web UI, and the UI saves
schema defaults into both. The adapter only ever read the league copy -- the
root show_* keys as a fallback the saved league value always beat, the rest not
at all -- so changing a root one saved and did nothing.

Precedence now, the same rule afl and nrl use for their display_options
duplicates: a league value changed from its default wins, then a root value
changed from its default, then the league value. Each copy is compared with its
OWN default, because live_game_duration's root default (30) differs from the
league's (20): a root left at 30 must not override every league.

Run: <core-venv>/bin/python plugins/soccer-scoreboard/test_root_settings_precedence.py
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
           str(REPO.parent / "LEDMatrix")):
    if _c and (Path(_c) / "src" / "plugin_system" / "base_plugin.py").exists():
        CORE = Path(_c)
        break
if CORE is None:
    print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
    sys.exit(2)
sys.path.insert(0, str(CORE))

failures = []

BLOCKS = ("game_limits", "display_options", "filtering")


def check(name, ok, detail=None):
    print("  %s  %s%s" % ("PASS" if ok else "FAIL", name,
                          "" if ok or detail is None else " -- %r" % (detail,)))
    if not ok:
        failures.append(name)


def locate(league_props, key):
    """(sub-block or None, schema node) where a league block declares key."""
    if key in league_props:
        return None, league_props[key]
    for block in BLOCKS:
        props = (league_props.get(block) or {}).get("properties") or {}
        if key in props:
            return block, props[key]
    return None, None


def other_value(node, avoid):
    """A schema-valid value equal to none of ``avoid``, or None if none exists."""
    if node.get("type") == "boolean":
        choices = [True, False]
    elif "enum" in node:
        choices = list(node["enum"])
    elif node.get("type") == "array":
        choices = [[c] for c in (node.get("items") or {}).get("enum") or ["zz"]]
    else:
        low, high = node.get("minimum", 0), node.get("maximum", 10 ** 6)
        choices = range(low, min(high, low + 100) + 1)
    return next((c for c in choices if c not in avoid), None)


def main():
    os.chdir(str(CORE))
    import manager as pm

    schema = json.load(open(plugin_dir / "config_schema.json", encoding="utf-8"))
    props = schema["properties"]
    leagues = props["leagues"]["properties"]
    table = pm._ROOT_DUPLICATE_DEFAULTS

    print("the defaults table mirrors config_schema.json")
    for key, (league_default, root_default) in table.items():
        check("%s root default" % key,
              props.get(key, {}).get("default") == root_default,
              (props.get(key, {}).get("default"), root_default))
        for league, node in leagues.items():
            _, leaf = locate(node["properties"], key)
            if leaf is None or leaf.get("default") != league_default:
                check("%s default in %s" % (key, league), False,
                      (leaf or {}).get("default"))
                break
        else:
            check("%s default in every league block" % key, True)
    declared = {k for k in props
                if all(locate(n["properties"], k)[1] is not None for n in leagues.values())}
    declared -= {"enabled"}       # the plugin switch vs the league switch
    check("every root/league duplicate is in the table",
          declared <= set(table), sorted(declared - set(table)))

    obj = pm.SoccerScoreboardPlugin.__new__(pm.SoccerScoreboardPlugin)
    obj.logger = logging.getLogger("precedence_probe")
    for attr in ("cache_manager", "display_manager", "plugin_manager"):
        setattr(obj, attr, MagicMock())

    league = "eng.1"
    league_props = leagues[league]["properties"]

    def adapt(root, block_key, key, league_value=None):
        league_cfg = {}
        if league_value is not None:
            target = league_cfg.setdefault(block_key, {}) if block_key else league_cfg
            target[key] = league_value
        obj.config = dict(root, leagues={league: league_cfg})
        return obj._adapt_config_for_manager(league)["soccer_%s_scoreboard" % league]

    for key, (league_default, root_default) in table.items():
        block_key, node = locate(league_props, key)
        root_changed = other_value(node, [league_default, root_default])
        # Two-valued settings (booleans, a two-choice enum) have no third value,
        # so "league and root changed to different things" cannot be built.
        league_changed = (other_value(node, [league_default, root_default, root_changed])
                          or root_changed)
        print("\n%s (%s)" % (key, block_key or "league root"))

        got = adapt({key: root_changed}, block_key, key, league_default)[key]
        check("a changed root value reaches a league left at its default",
              got == root_changed, got)
        if league_changed != root_changed:
            got = adapt({key: root_changed}, block_key, key, league_changed)[key]
            check("a changed league value beats a changed root value",
                  got == league_changed, got)
        got = adapt({key: root_default}, block_key, key, league_changed)[key]
        check("a changed league value beats a root left at its default",
              got == league_changed, got)
        got = adapt({key: root_default}, block_key, key, league_default)[key]
        check("both at their defaults: the league default",
              got == league_default, got)

    print("\nlive_game_duration: the root default is 30, the league default 20")
    got = adapt({"live_game_duration": 30}, None, "live_game_duration", 20)["live_game_duration"]
    check("a root left at 30 does not override the league's 20", got == 20, got)

    print("\nnon-root keys are untouched")
    got = adapt({}, "game_limits", "recent_games_to_show", None)["recent_games_to_show"]
    check("a league block with no value keeps the adapter's own fallback", got == 5, got)

    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
