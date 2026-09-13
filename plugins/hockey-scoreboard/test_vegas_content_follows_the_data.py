#!/usr/bin/env python3
"""Vegas cards follow the game data, from their own display, without network.

get_vegas_content returned get_all_vegas_content_items() -- the union of every
scroll display -- and built the combined slate only when that union was empty.
So once anything had rendered, a goal never reached the Vegas ticker until a
restart, and after a standalone mode had rendered, Vegas showed that mode's
games. baseball-scoreboard fixed this by fingerprinting the slate, rendering it
into a dedicated 'mixed' display with prepare_content (which does not steal the
standalone scroll), and never calling update() from the render path.

Run: <core-venv>/bin/python plugins/hockey-scoreboard/test_vegas_content_follows_the_data.py
"""

import logging
import os
import sys
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

_core = os.environ.get("LEDMATRIX_CORE", "")
for _candidate in (_core, str(plugin_dir.parents[2] / "LEDMatrix")):
    if _candidate and (Path(_candidate) / "src" / "plugin_system").is_dir():
        sys.path.insert(0, _candidate)
        break
else:
    print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
    sys.exit(2)

import manager as m  # noqa: E402

failures = []


def check(name, ok, detail=None):
    if ok:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s%s" % (name, " -- %r" % (detail,) if detail is not None else ""))
        failures.append(name)


class _Card:
    width = 100


class _ScrollManager:
    def __init__(self):
        self.items = {}
        self.builds = []

    def prepare_content(self, games, game_type, leagues, rankings=None):
        self.builds.append((game_type, [g.get("home_score") for g in games]))
        self.items[game_type] = [_Card() for _ in games]
        return True

    def get_vegas_content_items_for(self, game_type):
        return list(self.items.get(game_type, []))

    def get_all_vegas_content_items(self):
        # A standalone mode's leftovers: must not be what Vegas shows.
        return [_Card()] * 7

    def prepare_and_display(self, *a, **k):
        raise AssertionError("Vegas must not take over the standalone scroll")


def _plugin(games):
    p = m.HockeyScoreboardPlugin.__new__(m.HockeyScoreboardPlugin)
    p.logger = logging.getLogger("vegas_probe")
    p._scroll_manager = _ScrollManager()
    p._vegas_signature = None
    p.update_calls = 0

    def _update():
        p.update_calls += 1
    p.update = _update
    p._collect_games_for_scroll = lambda: (games, ["nhl"])
    return p


def _game(gid, home_score="1"):
    return {"id": gid, "league": "nhl", "status": {"state": "in"},
            "home_abbr": "TOR", "away_abbr": "MTL",
            "home_score": home_score, "away_score": "0",
            "period": 2, "period_text": "P2", "clock": "12:34"}


def main():
    games = [_game("1"), _game("2")]
    p = _plugin(games)

    print("first call builds the slate into the 'mixed' display")
    images = p.get_vegas_content()
    check("one card per game", images is not None and len(images) == 2,
          images and len(images))
    check("built once, into 'mixed'",
          [b[0] for b in p._scroll_manager.builds] == ["mixed"],
          p._scroll_manager.builds)

    print("\nunchanged data is a cache read")
    p.get_vegas_content()
    check("no rebuild", len(p._scroll_manager.builds) == 1, p._scroll_manager.builds)

    print("\nthe clock ticking alone does not rebuild")
    games[0]["clock"] = "11:02"
    p.get_vegas_content()
    check("no rebuild", len(p._scroll_manager.builds) == 1, p._scroll_manager.builds)

    print("\na goal rebuilds")
    games[0]["home_score"] = "2"
    p.get_vegas_content()
    check("rebuilt with the new score",
          len(p._scroll_manager.builds) == 2
          and p._scroll_manager.builds[-1][1][0] == "2", p._scroll_manager.builds)

    print("\na game joining the slate rebuilds")
    games.append(_game("3"))
    images = p.get_vegas_content()
    check("three cards", images is not None and len(images) == 3)

    print("\nno network on the render path")
    check("update() was never called", p.update_calls == 0, p.update_calls)

    print("\nnothing to show")
    p = _plugin([])
    check("no games returns None, not another display's cards",
          p.get_vegas_content() is None)

    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
