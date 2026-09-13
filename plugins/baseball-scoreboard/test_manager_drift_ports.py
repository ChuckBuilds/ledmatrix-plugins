#!/usr/bin/env python3
"""Manager-init and odds-cache fixes ported from sibling scoreboards.

  * P-A4 -- each league's managers are built in their own try. One shared try
    meant a constructor raising for MLB skipped MiLB and NCAA as well.
  * M12 -- other_games_divisions is passed through raw. list() in the
    translation turned a hand-edited "fcs" into ['f','c','s'] (matching no
    division, so every non-favourite game was filtered out) and raised
    TypeError on null, leaving every league unbuilt.
  * P-OVF -- a config Infinity (json parses a bare Infinity) falls back to the
    default instead of raising OverflowError from manager construction.
  * P-B1 -- a cached {"no_odds": True} marker is a cache hit: get_odds returns
    None without asking ESPN again until the entry expires.

Run: <core-venv>/bin/python plugins/baseball-scoreboard/test_manager_drift_ports.py
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
           str(REPO.parent / "LEDMatrix"),
           str(Path.home() / "projects" / "LEDMatrix")):
    if _c and (Path(_c) / "assets" / "fonts").is_dir():
        CORE = Path(_c)
        break
if CORE is None:
    print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
    sys.exit(2)
sys.path.insert(0, str(CORE))

failures = []


def check(name, ok, detail=None):
    if ok:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s%s" % (name, " -- %r" % (detail,) if detail is not None else ""))
        failures.append(name)


def _plugin():
    import manager as plugin_manager
    cls = plugin_manager.BaseballScoreboardPlugin
    obj = cls.__new__(cls)
    obj.logger = logging.getLogger("manager_probe")
    obj.display_manager = MagicMock()
    obj.cache_manager = MagicMock()
    obj.plugin_manager = MagicMock()
    obj.timezone_str = "America/Chicago"
    return obj


class _Built:
    def __init__(self, config, display_manager, cache_manager):
        self.config = config


class _Boom:
    def __init__(self, *a, **k):
        raise RuntimeError("constructor failed")


def test_leagues_initialise_independently():
    print("P-A4: one failing league does not skip the others")
    obj = _plugin()
    obj.mlb_enabled = obj.milb_enabled = obj.ncaa_baseball_enabled = True
    obj._adapt_config_for_manager = lambda league: {"league": league}
    obj._LEAGUE_MANAGER_CLASSES = (
        ("mlb", "mlb_enabled", (_Boom, _Boom, _Boom), "MLB"),
        ("milb", "milb_enabled", (_Built, _Built, _Built), "MiLB"),
        ("ncaa_baseball", "ncaa_baseball_enabled", (_Built, _Built, _Built), "NCAA"),
    )
    obj._initialize_managers()
    check("the failing league's managers are None",
          obj.mlb_live is None and obj.mlb_recent is None and obj.mlb_upcoming is None)
    check("the league after it was still built",
          isinstance(getattr(obj, "milb_live", None), _Built)
          and isinstance(getattr(obj, "milb_upcoming", None), _Built))
    check("and the one after that",
          isinstance(getattr(obj, "ncaa_baseball_recent", None), _Built))

    obj = _plugin()
    obj.mlb_enabled, obj.milb_enabled, obj.ncaa_baseball_enabled = True, False, False
    obj._adapt_config_for_manager = lambda league: {"league": league}
    obj._LEAGUE_MANAGER_CLASSES = (
        ("mlb", "mlb_enabled", (_Built, _Built, _Built), "MLB"),
        ("milb", "milb_enabled", (_Boom, _Boom, _Boom), "MiLB"),
        ("ncaa_baseball", "ncaa_baseball_enabled", (_Boom, _Boom, _Boom), "NCAA"),
    )
    obj._initialize_managers()
    check("a disabled league is not constructed",
          getattr(obj, "milb_live", None) is None
          and isinstance(obj.mlb_live, _Built))


def test_divisions_pass_through():
    print("\nM12: other_games_divisions reaches sports.py unmangled")
    obj = _plugin()
    for raw in ("fcs", None, ["fbs", "fcs"]):
        obj.config = {"mlb": {"game_limits": {"other_games_divisions": raw}}}
        try:
            adapted = obj._adapt_config_for_manager("mlb")["mlb_scoreboard"]
        except Exception as exc:
            check("translation survives %r" % (raw,), False, exc)
            continue
        check("translation passes %r through unchanged" % (raw,),
              adapted.get("other_games_divisions") == raw,
              adapted.get("other_games_divisions"))

    import sports
    check("a string becomes one division, not three letters",
          sports.SportsCore._normalise_divisions("fcs") == ["fcs"],
          sports.SportsCore._normalise_divisions("fcs"))
    check("null means no division filter",
          sports.SportsCore._normalise_divisions(None) == [])

    obj.config = {"mlb": {}}
    adapted = obj._adapt_config_for_manager("mlb")["mlb_scoreboard"]
    check("the baseball default has no football division filter",
          adapted.get("other_games_divisions") == [],
          adapted.get("other_games_divisions"))
    check("MLB's default quality is neutral",
          adapted.get("other_games_min_quality") == "any",
          adapted.get("other_games_min_quality"))


def test_infinity_falls_back():
    print("\nP-OVF: a config Infinity falls back instead of raising")
    import sports
    inf = float("inf")
    try:
        got = sports._clamp_window(inf, 7)
    except OverflowError as exc:
        got = exc
    check("_clamp_window(inf) returns the fallback", got == 7, got)

    stubs = dict((name, lambda self, *a, **k: None)
                 for name in getattr(sports.SportsUpcoming, "__abstractmethods__", ()))
    probe_cls = type("OverflowProbe", (sports.SportsUpcoming,), stubs)
    probe = probe_cls.__new__(probe_cls)
    probe.logger = logging.getLogger("ovf_probe")
    probe.league = "mlb"
    probe.mode_config = {"other_rotation_interval_seconds": inf}
    try:
        got = probe._setting_int("other_rotation_interval_seconds", 1800, 0, 86400)
    except OverflowError as exc:
        got = exc
    check("_setting_int(inf) returns the default", got == 1800, got)


def test_no_odds_marker_is_a_cache_hit():
    print("\nP-B1: a cached no-odds marker does not refetch")
    import base_odds_manager as bom
    cache = MagicMock()
    cache.get.return_value = {"no_odds": True}
    manager = bom.BaseOddsManager(cache, None)
    original = bom.requests.get

    def boom(*a, **k):
        raise AssertionError("ESPN must not be asked while the marker is cached")

    bom.requests.get = boom
    try:
        try:
            got = manager.get_odds("baseball", "mlb", "401")
            asked = False
        except AssertionError:
            got, asked = None, True
    finally:
        bom.requests.get = original
    check("the marker returns None", got is None, got)
    check("no request was made", not asked)
    check("nothing was written back over the marker", not cache.set.called,
          cache.set.call_args)


def main():
    os.chdir(str(CORE))
    test_leagues_initialise_independently()
    test_divisions_pass_through()
    test_infinity_falls_back()
    test_no_odds_marker_is_a_cache_hit()
    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
