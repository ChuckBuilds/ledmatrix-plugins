#!/usr/bin/env python3
"""Vegas cards follow the games, and reading them never does network work.

get_vegas_content used to return the union of every scroll display's items
and build content only when that union was EMPTY. Once anything had rendered,
a score change never reached the ticker, and once a standalone scroll mode had
run, Vegas inherited that mode's games instead of the full slate. Building
went through prepare_and_display, which also made the Vegas slate the active
scroll display and hijacked the standalone rotation mid-scroll.

These checks pin the ported behaviour (baseball-scoreboard):

  * content is built into the dedicated 'mixed' display via prepare_content;
  * an unchanged slate is a cache read, a changed score rebuilds;
  * the render path never calls update() or prepare_and_display();
  * the per-call "Returning N image(s)" line is debug, not info.

Run: <core-venv>/bin/python plugins/soccer-scoreboard/test_vegas_rebuilds_on_change.py
"""

import logging
import os
import sys
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))
REPO = Path(__file__).resolve().parents[2]
CORE = None
for _c in (os.environ.get("LEDMATRIX_CORE", ""), str(REPO.parent / "LEDMatrix")):
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


class _Img:
    def __init__(self, width):
        self.width = width


class _FakeScrollManager:
    def __init__(self):
        self.prepared = []
        self.items = {}

    def prepare_content(self, games, game_type, leagues, rankings_cache=None):
        self.prepared.append((game_type, [dict(g) for g in games]))
        self.items[game_type] = [_Img(100) for _ in games]
        return True

    def get_vegas_content_items_for(self, game_type):
        return list(self.items.get(game_type, []))

    def get_all_vegas_content_items(self):
        # What a standalone mode left behind: one stale card.
        return [_Img(1)]

    def prepare_and_display(self, *a, **k):
        raise AssertionError("prepare_and_display hijacks the active scroll display")


def main():
    os.chdir(str(CORE))
    try:
        import manager as pm
    except ImportError as exc:
        print("SKIP: cannot import manager.py (%s)" % exc)
        return 2

    cls = next(obj for obj in vars(pm).values()
               if isinstance(obj, type) and hasattr(obj, "get_vegas_content")
               and hasattr(obj, "_collect_games_for_scroll"))

    records = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    obj = cls.__new__(cls)
    obj.logger = logging.getLogger("vegas_probe")
    obj.logger.handlers[:] = [_Capture()]
    obj.logger.setLevel(logging.DEBUG)
    obj.logger.propagate = False
    obj._scroll_manager = _FakeScrollManager()

    games = [
        {"id": "1", "league": "eng.1", "status": {"state": "in"},
         "home_abbr": "ARS", "away_abbr": "CHE", "home_score": "0", "away_score": "0"},
        {"id": "2", "league": "esp.1", "status": {"state": "pre"},
         "home_abbr": "RMA", "away_abbr": "BAR"},
    ]
    obj._collect_games_for_scroll = lambda mode_type=None, **k: (
        [dict(g) for g in games], ["eng.1", "esp.1"])
    obj._get_rankings_cache = lambda: {}

    def no_network(*a, **k):
        raise AssertionError("update() called on the Vegas render path")
    obj.update = no_network

    print("first read builds the full slate into the 'mixed' display")
    images = obj.get_vegas_content()
    sm = obj._scroll_manager
    check("one build", len(sm.prepared) == 1, len(sm.prepared))
    check("built into the dedicated Vegas key",
          sm.prepared and sm.prepared[0][0] == "mixed", sm.prepared[:1])
    check("returns one card per game, not the stale union",
          images is not None and len(images) == 2, images and len(images))

    print("\nan unchanged slate is a cache read")
    obj.get_vegas_content()
    obj.get_vegas_content()
    check("no rebuild", len(sm.prepared) == 1, len(sm.prepared))

    print("\na score change rebuilds")
    games[0]["home_score"] = "1"
    obj.get_vegas_content()
    check("rebuilt once", len(sm.prepared) == 2, len(sm.prepared))
    check("with the new score",
          sm.prepared[-1][1][0].get("home_score") == "1")

    print("\nlogging")
    returning = [r for r in records if "Returning" in r.getMessage()]
    check("the per-call 'Returning' line is logged", bool(returning))
    check("... at debug, not info",
          all(r.levelno <= logging.DEBUG for r in returning),
          [r.levelname for r in returning])

    print("\nnothing to show")
    games.clear()
    check("no games returns None", obj.get_vegas_content() is None)

    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
