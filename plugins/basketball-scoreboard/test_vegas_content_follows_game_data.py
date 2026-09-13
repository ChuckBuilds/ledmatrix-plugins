#!/usr/bin/env python3
"""Vegas cards are rebuilt when the games change, from the combined slate.

get_vegas_content() returned the union of every scroll display's cards and
only built its own slate when that union was EMPTY. Once any standalone scroll
mode had rendered, Vegas showed that mode's games, and a changed score never
reached the ticker. These checks pin, against a recording scroll manager:

  * the cards come from the 'mixed' display only;
  * a change in the game data rebuilds them, an unchanged slate does not;
  * the rebuild does not make 'mixed' the active standalone scroll;
  * update() -- network -- is never called from this render path.

Run: <core-venv>/bin/python plugins/basketball-scoreboard/test_vegas_content_follows_game_data.py
"""

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

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

results = []


def check(case, passed):
    results.append((case, passed))
    print("  [%s] %s" % ("pass" if passed else "FAIL", case))


class _Card:
    def __init__(self, tag):
        self.width = 128
        self.tag = tag


class _Display:
    def __init__(self, items):
        self._vegas_content_items = items


class _ScrollManager:
    def __init__(self):
        self._scroll_displays = {"live": _Display([_Card("standalone-live")])}
        self._current_game_type = "live"
        self.builds = 0
        self.prepare_and_display_calls = 0

    def prepare_content(self, games, game_type, leagues, rankings):
        self.builds += 1
        self._scroll_displays[game_type] = _Display(
            [_Card("%s:%s-%s" % (game_type, g["home_score"], g["away_score"]))
             for g in games])
        return True

    def prepare_and_display(self, *a, **k):
        self.prepare_and_display_calls += 1
        self._current_game_type = a[1]
        return self.prepare_content(*a, **k)

    def get_vegas_content_items_for(self, game_type):
        d = self._scroll_displays.get(game_type)
        return list(d._vegas_content_items) if d else []

    def get_all_vegas_content_items(self):
        return [c for d in self._scroll_displays.values() for c in d._vegas_content_items]


def main():
    os.chdir(str(CORE))
    import manager as plugin_manager

    cls = plugin_manager.BasketballScoreboardPlugin
    plugin = cls.__new__(cls)
    plugin.logger = logging.getLogger("test")
    plugin._scroll_manager = _ScrollManager()
    plugin._vegas_signature = None
    plugin._get_rankings_cache = lambda: {}
    games = [{"id": "1", "league": "nba", "status": {"state": "in"},
              "home_abbr": "BOS", "away_abbr": "NY",
              "home_score": "50", "away_score": "48", "period": 2}]
    plugin._collect_games_for_scroll = lambda mode_type=None, live_priority_active=False: (
        [dict(g) for g in games], ["nba"])
    update_calls = []
    plugin.update = lambda: update_calls.append(1)

    images = plugin.get_vegas_content()
    sm = plugin._scroll_manager
    check("the first call builds the combined slate", sm.builds == 1)
    check("only the mixed display's cards are returned, not the standalone one",
          images and [c.tag for c in images] == ["mixed:50-48"])
    check("building does not repoint the active standalone scroll",
          sm._current_game_type == "live" and sm.prepare_and_display_calls == 0)

    plugin.get_vegas_content()
    check("an unchanged slate is served from cache", sm.builds == 1)

    games[0]["home_score"] = "52"
    images = plugin.get_vegas_content()
    check("a score change rebuilds the cards", sm.builds == 2)
    check("and the new score is what Vegas gets",
          images and images[0].tag == "mixed:52-48")

    check("update() is never called from the Vegas path", update_calls == [])

    games.clear()
    check("no games gives no content", plugin.get_vegas_content() is None)

    failed = [c for c, ok in results if not ok]
    print("\n%d checks, %d failed" % (len(results), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
