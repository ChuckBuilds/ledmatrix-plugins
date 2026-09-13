#!/usr/bin/env python3
"""Vegas cards must follow the game data, from their own display, off-network.

get_vegas_content() returned get_all_vegas_content_items() and built content
only when that came back empty. Once anything was cached it was served
forever: a live score changed and the ticker kept the first strip it built
until a restart. It also returned the union of every scroll display, so a
standalone scroll mode's cards leaked into Vegas. Ported from
baseball-scoreboard: rebuild when the game signature changes, read only the
'mixed' display, and never call update() (network) on the render path.

These checks pin:

  * the first call builds, and a repeat with the same slate does not rebuild;
  * a score change rebuilds;
  * the clock ticking alone does not;
  * another display's cards are not returned;
  * no manager update() is called, and the active strip is not hijacked.

Run: <core-venv>/bin/python plugins/afl-scoreboard/test_vegas_content_follows_the_slate.py
"""

import logging
import os
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))

_core = os.environ.get('LEDMATRIX_CORE', '')
for _candidate in (_core, str(PLUGIN_DIR.parents[2] / 'LEDMatrix')):
    if _candidate and (Path(_candidate) / 'src' / 'plugin_system').is_dir():
        sys.path.insert(0, _candidate)
        break
else:
    if not any((Path(p) / 'src' / 'plugin_system').is_dir() for p in sys.path if p):
        print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
        sys.exit(2)

from PIL import Image  # noqa: E402

import manager as m  # noqa: E402

failures = []


def check(name, ok, detail=None):
    if ok:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s%s" % (name, " -- %r" % (detail,) if detail is not None else ""))
        failures.append(name)


class FakeDisplay:
    def __init__(self, items=None):
        self._vegas_content_items = list(items or [])
        self.builds = 0

    def prepare_scroll_content(self, games, game_type, leagues, rankings):
        self.builds += 1
        self._vegas_content_items = [Image.new("RGB", (20, 8)) for _ in games]
        return True


class FakeScrollManager:
    def __init__(self):
        self._scroll_displays = {"live": FakeDisplay([Image.new("RGB", (99, 8))] * 3)}
        self.hijacked = False

    def get_scroll_display(self, key):
        return self._scroll_displays.setdefault(key, FakeDisplay())

    def prepare_and_display(self, *a, **k):
        self.hijacked = True
        return False

    def get_all_vegas_content_items(self):
        items = []
        for d in self._scroll_displays.values():
            items.extend(d._vegas_content_items)
        return items


class FakeManager:
    def __init__(self, attr, games):
        setattr(self, attr, games)
        self.updated = False

    def update(self):
        self.updated = True
        raise AssertionError("update() called on the Vegas render path")


def _live(score, clock="12:00"):
    return {"id": "g1", "home_abbr": "COLL", "away_abbr": "GEEL",
            "home_score": score, "away_score": "40", "period": 2,
            "is_live": True, "is_final": False, "is_upcoming": False,
            "clock": clock, "period_text": "Q2 %s" % clock}


def main():
    plugin = m.AflScoreboardPlugin.__new__(m.AflScoreboardPlugin)
    plugin.logger = logging.getLogger("vegas_probe")
    scroll = FakeScrollManager()
    plugin._scroll_manager = scroll
    live = FakeManager("live_games", [_live("50")])
    recent = FakeManager("recent_games", [{
        "id": "g0", "home_abbr": "RICH", "away_abbr": "CARL",
        "home_score": "80", "away_score": "70", "is_final": True}])
    plugin._managers = {"live": live, "recent": recent, "upcoming": None}

    print("first call builds the Vegas display")
    images = plugin.get_vegas_content()
    mixed = scroll._scroll_displays.get("mixed")
    check("built once", mixed is not None and mixed.builds == 1,
          mixed and mixed.builds)
    check("one card per game, none from the other display",
          images is not None and len(images) == 2, images and len(images))

    print("\nsame slate: served from cache")
    plugin.get_vegas_content()
    check("no rebuild", mixed.builds == 1, mixed.builds)

    print("\nthe clock ticks, nothing else changes")
    live.live_games = [_live("50", clock="11:59")]
    plugin.get_vegas_content()
    check("no rebuild for a clock tick", mixed.builds == 1, mixed.builds)

    print("\na score changes")
    live.live_games = [_live("56", clock="11:30")]
    plugin.get_vegas_content()
    check("rebuilt", mixed.builds == 2, mixed.builds)

    print("\nthe render path stays off the network and off the active strip")
    check("no manager update() was called", not live.updated and not recent.updated)
    check("prepare_and_display was not used", not scroll.hijacked)

    print("\nno games: nothing to show")
    live.live_games = []
    recent.recent_games = []
    check("returns None", plugin.get_vegas_content() is None)

    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
