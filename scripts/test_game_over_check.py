#!/usr/bin/env python3
"""What each scoreboard's live manager calls "over", cell by cell.

WHY THIS EXISTS
---------------
``SportsLive._is_game_really_over`` drops a game ESPN still lists as live
from the live rotation (and the plugin's live-priority filters). The nine
copies were five different bodies (LEDMatrix docs/SPORTS_UNIFICATION.md,
family 5). They are now one body, and each plugin's ``FINAL_PERIOD`` says
from which period a 0:00 clock ends a game (None: never). The tables below
record what every plugin answers, so any later change to the method or a
plugin's ``FINAL_PERIOD`` shows up in a PR as a diff of them, cell by cell.

For each plugin it builds a real live manager (fake display and cache) and
calls ``_is_game_really_over`` on:

* a matrix of game shapes: ESPN status x clock x period, where period runs
  missing (baseball's games carry none), 1..6 (OT for the four-period sports,
  OT and beyond for hockey, every ufc round);
* edge shapes: null or non-numeric fields, a non-string clock, a tied score
  at the end of regulation;
* ufc only: its recorded ESPN MMA payloads
  (plugins/ufc-scoreboard/test/fixtures/espn_mma_round_states.json), through
  its own ``_extract_game_details``, including the round breaks ESPN sends
  as STATUS_END_OF_ROUND with displayClock "-".

The method reads only ``period_text``, ``clock``, ``period``, the two scores
(level at 0:00 is not over) and (baseball) ``status``, so each status is
given the period text its feed would carry; the matrix scores are 1-2.
Every league's live manager in a plugin must resolve to the same method, so
one manager per plugin covers them all; that is checked too.

A cell is ``Y`` (over), ``.`` (not over) or ``!`` (raised). To see the
current tables after an intended change:

    python scripts/test_game_over_check.py --print

Exit 0 pass, 2 skip (no core checkout), 1 fail.
"""
from __future__ import annotations

import inspect
import json
import logging
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_sports_shared_methods import REPO, SPORTS, core_root, load  # noqa: E402

#: plugin -> (module, live manager class, extra constructor args)
LIVE_MANAGERS = {
    "afl": ("afl_managers.py", "AflLiveManager", ()),
    "baseball": ("mlb_managers.py", "MLBLiveManager", ()),
    "basketball": ("nba_managers.py", "NBALiveManager", ()),
    "football": ("nfl_managers.py", "NFLLiveManager", ()),
    "hockey": ("nhl_managers.py", "NHLLiveManager", ()),
    "lacrosse": ("ncaam_lacrosse_managers.py", "NCAAMLacrosseLiveManager", ()),
    "nrl": ("nrl_managers.py", "NrlLiveManager", ()),
    "soccer": ("soccer_managers.py", "SoccerLiveManager", ("eng.1",)),
    "ufc": ("ufc_managers.py", "UFCLiveManager", ()),
}

MISSING = object()  # the key is absent from the game dict

#: ESPN status -> the period text a game in it carries, given its period.
STATUSES = {
    "STATUS_IN_PROGRESS": lambda p: "" if p is MISSING else f"P{p}",
    "STATUS_END_PERIOD": lambda p: "" if p is MISSING else f"End P{p}",
    "STATUS_HALFTIME": lambda p: "Halftime",
    "STATUS_END_OF_ROUND": lambda p: "" if p is MISSING else f"End R{p}",
    "STATUS_FINAL": lambda p: "Final",
    "STATUS_POSTPONED": lambda p: "Postponed",
}
PERIODS = (MISSING, 1, 2, 3, 4, 5, 6)
CLOCKS = {"12:00": "12:00", "0:00": "0:00", ":00": ":00", "0.0": "0.0",
          "-": "-", "''": "", "None": None, "missing": MISSING}


def game(status, period_text, period, clock, **extra):
    g = {"away_abbr": "AWY", "home_abbr": "HOM", "away_score": "1",
         "home_score": "2", "status": status.lower(), "period_text": period_text}
    if period is not MISSING:
        g["period"] = period
    if clock is not MISSING:
        g["clock"] = clock
    g.update(extra)
    return g


#: label -> game; one expected cell per plugin.
EDGES = {
    "period_text None, P4 0:00": game("STATUS_IN_PROGRESS", None, 4, "0:00"),
    "period None, 0:00": game("STATUS_IN_PROGRESS", "", None, "0:00"),
    "period 'OT', 0:00": game("STATUS_IN_PROGRESS", "OT", "OT", "0:00"),
    "period '4' (str), 0:00": game("STATUS_IN_PROGRESS", "P4", "4", "0:00"),
    "clock int 0, P4": game("STATUS_IN_PROGRESS", "P4", 4, 0),
    "clock float 0.0, P4": game("STATUS_IN_PROGRESS", "P4", 4, 0.0),
    "tied, end of P3, 0:00": game("STATUS_END_PERIOD", "End P3", 3, "0:00",
                                  away_score="2"),
    "tied, end of P4, 0:00": game("STATUS_END_PERIOD", "End P4", 4, "0:00",
                                  away_score="2"),
    "period_text 'Final/OT', P5 0:00": game("STATUS_FINAL", "Final/OT", 5, "0:00"),
}

UFC_FIXTURES = (REPO / "plugins" / "ufc-scoreboard" / "test" / "fixtures"
                / "espn_mma_round_states.json")

# --------------------------------------------------------------------------
# Expected (current) behaviour. Columns per plugin, in SPORTS order:
#   afl baseball basketball football hockey lacrosse nrl soccer ufc
# Within a plugin, one cell per period: missing, 1, 2, 3, 4, 5, 6.
# --------------------------------------------------------------------------
EXPECTED_MATRIX = {
    ("STATUS_IN_PROGRESS", "12:00"): "....... ....... ....... ....... ....... ....... ....... ....... .......",
    ("STATUS_IN_PROGRESS", "0:00"): "....... ....... ....YYY ....YYY ...YYYY ....YYY ....... ....... .......",
    ("STATUS_IN_PROGRESS", ":00"): "....... ....... ....YYY ....YYY ...YYYY ....YYY ....... ....... .......",
    ("STATUS_IN_PROGRESS", "0.0"): "....... ....... ....... ....... ....... ....... ....... ....... .......",
    ("STATUS_IN_PROGRESS", "-"): "....... ....... ....... ....... ....... ....... ....... ....... .......",
    ("STATUS_IN_PROGRESS", "''"): "....... ....... ....... ....... ....... ....... ....... ....... .......",
    ("STATUS_IN_PROGRESS", "None"): "....... ....... ....... ....... ....... ....... ....... ....... .......",
    ("STATUS_IN_PROGRESS", "missing"): "....... ....... ....... ....... ....... ....... ....... ....... .......",
    ("STATUS_END_PERIOD", "12:00"): "....... ....... ....... ....... ....... ....... ....... ....... .......",
    ("STATUS_END_PERIOD", "0:00"): "....... ....... ....YYY ....YYY ...YYYY ....YYY ....... ....... .......",
    ("STATUS_END_PERIOD", ":00"): "....... ....... ....YYY ....YYY ...YYYY ....YYY ....... ....... .......",
    ("STATUS_END_PERIOD", "0.0"): "....... ....... ....... ....... ....... ....... ....... ....... .......",
    ("STATUS_END_PERIOD", "-"): "....... ....... ....... ....... ....... ....... ....... ....... .......",
    ("STATUS_END_PERIOD", "''"): "....... ....... ....... ....... ....... ....... ....... ....... .......",
    ("STATUS_END_PERIOD", "None"): "....... ....... ....... ....... ....... ....... ....... ....... .......",
    ("STATUS_END_PERIOD", "missing"): "....... ....... ....... ....... ....... ....... ....... ....... .......",
    ("STATUS_HALFTIME", "12:00"): "....... ....... ....... ....... ....... ....... ....... ....... .......",
    ("STATUS_HALFTIME", "0:00"): "....... ....... ....YYY ....YYY ...YYYY ....YYY ....... ....... .......",
    ("STATUS_HALFTIME", ":00"): "....... ....... ....YYY ....YYY ...YYYY ....YYY ....... ....... .......",
    ("STATUS_HALFTIME", "0.0"): "....... ....... ....... ....... ....... ....... ....... ....... .......",
    ("STATUS_HALFTIME", "-"): "....... ....... ....... ....... ....... ....... ....... ....... .......",
    ("STATUS_HALFTIME", "''"): "....... ....... ....... ....... ....... ....... ....... ....... .......",
    ("STATUS_HALFTIME", "None"): "....... ....... ....... ....... ....... ....... ....... ....... .......",
    ("STATUS_HALFTIME", "missing"): "....... ....... ....... ....... ....... ....... ....... ....... .......",
    ("STATUS_END_OF_ROUND", "12:00"): "....... ....... ....... ....... ....... ....... ....... ....... .......",
    ("STATUS_END_OF_ROUND", "0:00"): "....... ....... ....YYY ....YYY ...YYYY ....YYY ....... ....... .......",
    ("STATUS_END_OF_ROUND", ":00"): "....... ....... ....YYY ....YYY ...YYYY ....YYY ....... ....... .......",
    ("STATUS_END_OF_ROUND", "0.0"): "....... ....... ....... ....... ....... ....... ....... ....... .......",
    ("STATUS_END_OF_ROUND", "-"): "....... ....... ....... ....... ....... ....... ....... ....... .......",
    ("STATUS_END_OF_ROUND", "''"): "....... ....... ....... ....... ....... ....... ....... ....... .......",
    ("STATUS_END_OF_ROUND", "None"): "....... ....... ....... ....... ....... ....... ....... ....... .......",
    ("STATUS_END_OF_ROUND", "missing"): "....... ....... ....... ....... ....... ....... ....... ....... .......",
    ("STATUS_FINAL", "12:00"): "YYYYYYY YYYYYYY YYYYYYY YYYYYYY YYYYYYY YYYYYYY YYYYYYY YYYYYYY YYYYYYY",
    ("STATUS_FINAL", "0:00"): "YYYYYYY YYYYYYY YYYYYYY YYYYYYY YYYYYYY YYYYYYY YYYYYYY YYYYYYY YYYYYYY",
    ("STATUS_FINAL", ":00"): "YYYYYYY YYYYYYY YYYYYYY YYYYYYY YYYYYYY YYYYYYY YYYYYYY YYYYYYY YYYYYYY",
    ("STATUS_FINAL", "0.0"): "YYYYYYY YYYYYYY YYYYYYY YYYYYYY YYYYYYY YYYYYYY YYYYYYY YYYYYYY YYYYYYY",
    ("STATUS_FINAL", "-"): "YYYYYYY YYYYYYY YYYYYYY YYYYYYY YYYYYYY YYYYYYY YYYYYYY YYYYYYY YYYYYYY",
    ("STATUS_FINAL", "''"): "YYYYYYY YYYYYYY YYYYYYY YYYYYYY YYYYYYY YYYYYYY YYYYYYY YYYYYYY YYYYYYY",
    ("STATUS_FINAL", "None"): "YYYYYYY YYYYYYY YYYYYYY YYYYYYY YYYYYYY YYYYYYY YYYYYYY YYYYYYY YYYYYYY",
    ("STATUS_FINAL", "missing"): "YYYYYYY YYYYYYY YYYYYYY YYYYYYY YYYYYYY YYYYYYY YYYYYYY YYYYYYY YYYYYYY",
    ("STATUS_POSTPONED", "12:00"): "....... YYYYYYY ....... ....... ....... ....... ....... ....... .......",
    ("STATUS_POSTPONED", "0:00"): "....... YYYYYYY ....YYY ....YYY ...YYYY ....YYY ....... ....... .......",
    ("STATUS_POSTPONED", ":00"): "....... YYYYYYY ....YYY ....YYY ...YYYY ....YYY ....... ....... .......",
    ("STATUS_POSTPONED", "0.0"): "....... YYYYYYY ....... ....... ....... ....... ....... ....... .......",
    ("STATUS_POSTPONED", "-"): "....... YYYYYYY ....... ....... ....... ....... ....... ....... .......",
    ("STATUS_POSTPONED", "''"): "....... YYYYYYY ....... ....... ....... ....... ....... ....... .......",
    ("STATUS_POSTPONED", "None"): "....... YYYYYYY ....... ....... ....... ....... ....... ....... .......",
    ("STATUS_POSTPONED", "missing"): "....... YYYYYYY ....... ....... ....... ....... ....... ....... .......",
}

# One cell per plugin, in SPORTS order.
EXPECTED_EDGES = {
    "period_text None, P4 0:00": "..YYYY...",
    "period None, 0:00": ".........",
    "period 'OT', 0:00": ".........",
    "period '4' (str), 0:00": "..YYYY...",
    "clock int 0, P4": ".........",
    "clock float 0.0, P4": ".........",
    "tied, end of P3, 0:00": ".........",
    "tied, end of P4, 0:00": ".........",
    "period_text 'Final/OT', P5 0:00": "YYYYYYYYY",
}

# ufc's recorded ESPN payloads, through its own _extract_game_details. A
# finished bout reads ".": ufc's period text is "R<n>", never "Final", so it
# leaves the live list on is_final, before this method is asked.
EXPECTED_UFC_RECORDED = {
    "in_round_3_of_3": ".",
    "break_after_round_1": ".",
    "end_of_round_after_stoppage": ".",
    "walkouts_five_rounder": ".",
    "final_five_round_decision": ".",
    "final_five_round_stoppage": ".",
    "final_three_round_decision": ".",
    "final_three_round_stoppage": ".",
    "break_after_round_4_of_5": ".",
    "end_of_round_5_awaiting_decision": ".",
}


def build_live_manager(plugin):
    module, cls_name, extra = LIVE_MANAGERS[plugin]
    display = MagicMock()
    display.width, display.height = 128, 32
    display.matrix.width, display.matrix.height = 128, 32
    cache = MagicMock()
    cache.get.return_value = None
    cls = getattr(load(plugin, module), cls_name)
    return cls({"timezone": "UTC"}, display, cache, *extra)


def method_identity(cls):
    """Where a class's _is_game_really_over is defined: (file, qualname, line)."""
    fn = cls._is_game_really_over
    return (Path(fn.__code__.co_filename).name, fn.__qualname__,
            fn.__code__.co_firstlineno)


def league_managers_agree(plugin, chosen):
    """Yield a problem for every league live manager whose method differs from ``chosen``'s."""
    want = method_identity(type(chosen))
    pdir = REPO / "plugins" / f"{plugin}-scoreboard"
    for path in sorted(pdir.glob("*_managers.py")):
        mod = load(plugin, path.name)
        for name, cls in inspect.getmembers(mod, inspect.isclass):
            if name.endswith("LiveManager") and cls.__module__ == mod.__name__:
                got = method_identity(cls)
                if got != want:
                    yield f"{path.name}:{name} resolves {got}, not {want}"


def cell(mgr, g):
    try:
        return "Y" if mgr._is_game_really_over(dict(g)) else "."
    except Exception:                                 # noqa: BLE001
        return "!"


def observe(managers):
    """The three tables as this checkout answers them."""
    matrix = {}
    for status, text_for in STATUSES.items():
        for clock_label, clock in CLOCKS.items():
            matrix[(status, clock_label)] = " ".join(
                "".join(cell(managers[p], game(status, text_for(period), period, clock))
                        for period in PERIODS)
                for p in SPORTS)
    edges = {label: "".join(cell(managers[p], g) for p in SPORTS)
             for label, g in EDGES.items()}
    ufc = managers["ufc"]
    cases = json.loads(UFC_FIXTURES.read_text(encoding="utf-8"))["cases"]
    recorded = {c["name"]: cell(ufc, ufc._extract_game_details(c["event"]))
                for c in cases}
    return matrix, edges, recorded


def print_tables(matrix, edges, recorded):
    print("EXPECTED_MATRIX = {")
    for key, row in matrix.items():
        print(f"    {key!r}: {row!r},")
    print("}\n\nEXPECTED_EDGES = {")
    for key, row in edges.items():
        print(f"    {key!r}: {row!r},")
    print("}\n\nEXPECTED_UFC_RECORDED = {")
    for key, row in recorded.items():
        print(f"    {key!r}: {row!r},")
    print("}")


def diff(name, expected, observed, explain):
    problems = []
    for key in sorted(set(expected) | set(observed), key=str):
        want, got = expected.get(key), observed.get(key)
        if want != got:
            problems.append(f"{name}[{key!r}]: expected {want!r}, got {got!r}{explain(want, got)}")
    return problems


def changed_plugins(want, got):
    """Which plugins' cells differ between two rows (blank-separated or one char each)."""
    def per_plugin(row):
        return row.split() if " " in row else list(row)

    if not (isinstance(want, str) and isinstance(got, str)):
        return ""
    w, g = per_plugin(want), per_plugin(got)
    if len(w) != len(SPORTS) or len(g) != len(SPORTS):
        return ""
    return f"  <- {', '.join(p for p, a, b in zip(SPORTS, w, g) if a != b)}"


def main() -> int:
    core = core_root()
    if core is None:
        print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
        return 2
    sys.path.insert(0, str(core))
    logging.disable(logging.CRITICAL)
    os.chdir(core)  # the managers resolve fonts against the core

    managers, problems = {}, []
    for plugin in SPORTS:
        try:
            managers[plugin] = build_live_manager(plugin)
            problems += [f"{plugin}: {p}" for p in league_managers_agree(plugin, managers[plugin])]
        except Exception as exc:                      # noqa: BLE001
            problems.append(f"{plugin}: building the live manager raised "
                            f"{type(exc).__name__}: {exc}")
    if len(managers) < len(SPORTS):
        for p in problems:
            print(f"  [FAIL] {p}")
        return 1

    matrix, edges, recorded = observe(managers)
    if "--print" in sys.argv:
        print_tables(matrix, edges, recorded)
        return 0

    problems += diff("matrix", EXPECTED_MATRIX, matrix, changed_plugins)
    problems += diff("edges", EXPECTED_EDGES, edges, changed_plugins)
    problems += diff("ufc recorded", EXPECTED_UFC_RECORDED, recorded, lambda *_: "")
    for p in problems:
        print(f"  [FAIL] {p}")
    if problems:
        return 1
    cells = (len(matrix) * len(PERIODS) + len(edges)) * len(SPORTS) + len(recorded)
    print(f"  [pass] {cells} game-over answers across {len(SPORTS)} scoreboards")
    return 0


if __name__ == "__main__":
    sys.exit(main())
