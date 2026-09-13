#!/usr/bin/env python3
"""One bad league must not take the rest of the plugin down with it.

Two defects, one symptom (a blank plugin):

  * _initialize_managers wrapped every league in a single try, so the first
    league to raise -- anywhere in its config translation or constructors --
    silently skipped every league after it. Each league now has its own try,
    and a failed league's attributes are None.
  * The adapters wrapped other_games_divisions in list(). A hand-edited "fbs"
    became ['f', 'b', 's'] (matching nothing, so every non-favourite game was
    rejected), and a null raised TypeError inside the translation -- which is
    exactly the kind of failure the first bug then spread to every later
    league. The raw value is passed through now; SportsCore's
    _normalise_divisions coerces it.

Run: <core-venv>/bin/python plugins/soccer-scoreboard/test_manager_init_resilience.py
"""

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


def check(name, ok, detail=None):
    print("  %s  %s%s" % ("PASS" if ok else "FAIL", name,
                          "" if ok or detail is None else " -- %r" % (detail,)))
    if not ok:
        failures.append(name)


def main():
    os.chdir(str(CORE))
    try:
        import manager as pm
        import sports
    except ImportError as exc:
        print("SKIP: cannot import the plugin (%s)" % exc)
        return 2

    cls = next(obj for obj in vars(pm).values()
               if isinstance(obj, type) and hasattr(obj, "_initialize_managers")
               and hasattr(obj, "_adapt_config_for_manager"))

    def plugin(config):
        obj = cls.__new__(cls)
        obj.logger = logging.getLogger("init_probe")
        obj.config = config
        for attr in ("cache_manager", "display_manager", "plugin_manager"):
            setattr(obj, attr, MagicMock())
        return obj

    print("one league failing does not skip the leagues after it")
    obj = plugin({"leagues": {}})
    obj.league_enabled = {"eng.1": True, "esp.1": True, "ger.1": True}
    obj._adapt_config_for_manager = lambda key: {"league": key}

    built = {}

    def ok_factory(name):
        def make(cfg, dm, cm):
            built[name] = cfg
            return ("%s-live" % name, "%s-recent" % name, "%s-upcoming" % name)
        return make

    def boom(cfg, dm, cm):
        raise TypeError("simulated bad league config")

    saved = (pm.create_premier_league_managers, pm.create_la_liga_managers,
             pm.create_bundesliga_managers)
    pm.create_premier_league_managers = ok_factory("eng")
    pm.create_la_liga_managers = boom          # esp.1 comes second in LEAGUE_KEYS
    pm.create_bundesliga_managers = ok_factory("ger")
    logging.disable(logging.CRITICAL)
    try:
        obj._initialize_managers()
    finally:
        logging.disable(logging.NOTSET)
        (pm.create_premier_league_managers, pm.create_la_liga_managers,
         pm.create_bundesliga_managers) = saved

    check("the league before the failure is built", obj.eng1_live == "eng-live")
    check("the league after the failure is still built",
          getattr(obj, "ger1_upcoming", None) == "ger-upcoming",
          getattr(obj, "ger1_upcoming", None))
    check("the failed league's managers are None",
          (obj.esp1_live, obj.esp1_recent, obj.esp1_upcoming) == (None, None, None))
    check("disabled leagues are left untouched", not hasattr(obj, "ita1_live"))

    print("\nother_games_divisions passes through the adapter raw")
    for raw in ("fbs", None, ["fcs"]):
        obj = plugin({"leagues": {"eng.1": {"game_limits": {"other_games_divisions": raw}}}})
        try:
            block = obj._adapt_config_for_manager("eng.1")["soccer_eng.1_scoreboard"]
            got = block["other_games_divisions"]
            check("%r survives the translation unchanged" % (raw,), got == raw, got)
        except Exception as exc:
            check("%r survives the translation" % (raw,), False, exc)
        try:
            custom = obj._adapt_config_for_custom_league(
                {"league_code": "sco.1", "game_limits": {"other_games_divisions": raw}})
            got = custom["soccer_sco.1_scoreboard"]["other_games_divisions"]
            check("%r survives the custom-league translation" % (raw,), got == raw, got)
        except Exception as exc:
            check("%r survives the custom-league translation" % (raw,), False, exc)

    norm = sports.SportsCore._normalise_divisions
    check("a string is one division, not its letters", norm("fbs") == ["fbs"], norm("fbs"))
    check("null means no division filter", norm(None) == [], norm(None))

    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
