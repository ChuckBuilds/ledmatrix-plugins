#!/usr/bin/env python3
"""Tests that a live game's dwell does not depend on the data refresh rate.

The rotation used to live in update(), which runs on live_update_interval --
30s by default. A game could therefore only be advanced at that cadence, so
every configured duration was quantised to it. Measured on a live rig with
four NFL games: live_game_duration=45 and non_favorite_live_game_duration=10
both produced a flat 30s rotation, and only changing live_update_interval
changed anything. Setting a short non-favorite dwell did nothing at all.

It is driven from display() now, so the dwell is what was configured and the
refresh rate is just the refresh rate.

Run: <core-venv>/bin/python plugins/baseball-scoreboard/test_live_dwell.py
"""

import ast
import sys
import time
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))

import os  # noqa: E402
_core = os.environ.get('LEDMATRIX_CORE', '')
for _candidate in (_core, str(PLUGIN_DIR.parents[2] / 'LEDMatrix')):
    if _candidate and (Path(_candidate) / 'src' / 'plugin_system').is_dir():
        sys.path.insert(0, _candidate)
        break
else:
    print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
    sys.exit(2)

import inspect  # noqa: E402
import sports as sp  # noqa: E402  # pylint: disable=wrong-import-position

Base = dict(inspect.getmembers(sp, inspect.isclass))['SportsLive']
failures = []


def check(name, cond, detail=""):
    if cond:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s%s" % (name, (": " + detail) if detail else ""))
        failures.append(name)


class Live(Base):
    """A live manager with the network and rendering removed."""

    def __init__(self):
        import threading
        self.test_mode = False
        self._games_lock = threading.RLock()
        self.logger = type("L", (), {m: (lambda *a, **k: None) for m in
                                     ("debug", "info", "warning", "error",
                                      "exception")})()
        self.live_games = [
            {"id": "1", "home_abbr": "NE", "away_abbr": "IND"},
            {"id": "2", "home_abbr": "CIN", "away_abbr": "DET"},
            {"id": "3", "home_abbr": "PIT", "away_abbr": "GB"},
        ]
        self._rotation_schedule = ["1", "2", "3"]
        self.current_game_index = 0
        self.current_game = self.live_games[0]
        self.last_game_switch = time.time()
        self.favorite_teams = []
        self.game_display_duration = 30
        self.non_favorite_live_game_duration = 0
        self.favorite_live_boost = 1
        # Some sports consult a running celebration while rotating.
        self.active_celebration = None

    def _extract_game_details(self, *a, **k):
        return {}

    def _fetch_data(self, *a, **k):
        return {}


def main():
    print("the dwell is honoured without update() ever running")
    m = Live()
    first = m.current_game["id"]
    m._advance_live_game_if_due()
    check("holds before the duration elapses", m.current_game["id"] == first)

    # Rewind the clock rather than sleeping 30s. The assertion is that the
    # rotation *ran* -- last_game_switch is restamped only on a switch. Which
    # game it picks is the sport's own business: some weight favorites through
    # _swrr_advance, some index a prepared schedule, and that was never what
    # was broken here.
    m.last_game_switch = time.time() - 31
    stamp = m.last_game_switch
    m._advance_live_game_if_due()
    check("advances once it has", m.last_game_switch > stamp,
          "dwell never expired")

    print("\na short dwell is reachable, which it was not before")
    # This is the case that was impossible: a duration below the 30s refresh
    # interval could never be observed, because nothing evaluated it in
    # between.
    m = Live()
    m.game_display_duration = 5
    m.last_game_switch = time.time() - 6
    stamp = m.last_game_switch
    m._advance_live_game_if_due()
    check("a 5s dwell advances at 5s", m.last_game_switch > stamp)

    print("\nand a long one is not cut short")
    m = Live()
    m.game_display_duration = 45
    m.last_game_switch = time.time() - 31
    stamp = m.last_game_switch
    m._advance_live_game_if_due()
    check("a 45s dwell still holds at 31s", m.last_game_switch == stamp)

    print("\ncalling it every frame is safe")
    m = Live()
    m.game_display_duration = 30
    stamp = m.last_game_switch
    for _ in range(500):
        m._advance_live_game_if_due()
    check("500 frames inside the dwell change nothing",
          m.last_game_switch == stamp)

    print("\nit does not rotate when there is nothing to rotate")
    m = Live()
    m.live_games = [m.live_games[0]]
    m._rotation_schedule = ["1"]
    m.last_game_switch = time.time() - 999
    stamp = m.last_game_switch
    m._advance_live_game_if_due()
    check("a single live game stays put", m.last_game_switch == stamp)

    m = Live()
    m.last_game_switch = 0          # games have not loaded yet
    m._advance_live_game_if_due()
    check("does not rotate before the first game has had its turn",
          m.last_game_switch == 0)

    m = Live()
    m.test_mode = True
    m.last_game_switch = time.time() - 999
    stamp = m.last_game_switch
    m._advance_live_game_if_due()
    check("test mode is left alone", m.last_game_switch == stamp)

    print("\nSportsLive owns the rotation")
    # Resolved through the class, not by searching the file. An earlier
    # revision of this change put the call in SportsUpcoming.display(): a
    # file-wide substring search accepts that, and live games never rotate,
    # because upcoming display() is not on the live path at all.
    source = (PLUGIN_DIR / "sports.py").read_text(encoding="utf-8")
    live_cls = next(c for c in ast.walk(ast.parse(source))
                    if isinstance(c, ast.ClassDef) and c.name == "SportsLive")

    def method(name):
        return next((m for m in live_cls.body
                     if isinstance(m, ast.FunctionDef) and m.name == name), None)

    def advance_calls(node):
        if node is None:
            return []
        return [n for n in ast.walk(node)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "_advance_live_game_if_due"]

    check("the helper is defined on SportsLive",
          method("_advance_live_game_if_due") is not None)
    display_method = method("display")
    check("SportsLive.display() drives it",
          len(advance_calls(display_method)) == 1)
    update_method = method("update")
    check("SportsLive.update() does not drive it",
          not advance_calls(update_method))
    check("update() does not switch the live view",
          update_method is not None
          and "Switched live view to" not in (
              ast.get_source_segment(source, update_method) or ""))

    # A celebration owns the screen and resets the dwell when it expires;
    # rotating above it would switch away from the scoring game and undo
    # that reset. Only meaningful where display() handles celebrations.
    celebration_lines = [n.lineno for n in ast.walk(display_method)
                         if isinstance(n, ast.Attribute)
                         and n.attr == "active_celebration"]
    if celebration_lines and advance_calls(display_method):
        check("rotation is checked below the celebration branch",
              advance_calls(display_method)[0].lineno > max(celebration_lines))

    print("\n%s" % ("FAILED: %d" % len(failures) if failures
                    else "All checks passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
