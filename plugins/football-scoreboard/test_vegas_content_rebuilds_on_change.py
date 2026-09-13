#!/usr/bin/env python3
"""Vegas cards must follow the scores, without network I/O on the render path.

get_vegas_content returned whatever any scroll display had rendered and built
the combined slate only when that came back empty -- so once anything had
rendered, the Vegas ticker never rebuilt, and a score change never reached it.
Its build step also called update(), which is network I/O on the Vegas render
loop. It now reads its own 'mixed' display, rebuilds when the slate's
fingerprint changes, and never calls update().
"""
import logging
import sys
from pathlib import Path
from unittest.mock import Mock

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))
sys.path.insert(0, str(plugin_dir.parent.parent))

logging.disable(logging.CRITICAL)


def _display_manager():
    dm = Mock()
    dm.display_width = dm.width = 128
    dm.display_height = dm.height = 32
    matrix = Mock()
    matrix.width, matrix.height = 128, 32
    dm.matrix = matrix
    return dm


class _FakeScroll:
    def __init__(self):
        self.items = {}
        self.builds = 0

    def prepare_content(self, games, game_type, leagues, rankings_cache=None):
        from PIL import Image
        self.builds += 1
        self.items[game_type] = [Image.new("RGB", (10, 32)) for _ in games]
        return True

    def get_vegas_content_items_for(self, game_type):
        return list(self.items.get(game_type, []))

    def get_all_vegas_content_items(self):
        # A standalone mode's leftovers: what the old code wrongly returned.
        return list(self.items.get("recent", []))

    def prepare_and_display(self, *a, **k):
        raise AssertionError("Vegas must not make its slate the active scroll")


def _game(home_score):
    return {"id": "401", "league": "nfl", "status": {"state": "in"},
            "home_abbr": "KC", "away_abbr": "GB",
            "home_score": home_score, "away_score": "7"}


def main():
    try:
        from manager import FootballScoreboardPlugin
    except ImportError as exc:
        print("SKIP: cannot import the plugin (%s)" % exc)
        return 2

    pm = Mock()
    pm.get_plugin = Mock(return_value=None)
    plugin = FootballScoreboardPlugin(
        plugin_id="football-scoreboard",
        config={"enabled": True, "timezone": "UTC",
                "nfl": {"enabled": True}, "ncaa_fb": {"enabled": False}},
        display_manager=_display_manager(),
        cache_manager=Mock(),
        plugin_manager=pm,
    )
    scroll = _FakeScroll()
    # A standalone mode has already rendered two recent cards.
    scroll.items["recent"] = ["r1", "r2"]
    plugin._scroll_manager = scroll
    plugin._get_rankings_cache = lambda: {}

    def _no_network(*a, **k):
        raise AssertionError("update() called on the Vegas render path")

    plugin.update = _no_network
    slate = [_game("14")]
    plugin._collect_games_for_scroll = lambda live_priority_active=False: (
        [dict(g) for g in slate], ["nfl"])

    failures = 0

    def check(name, ok, detail=""):
        nonlocal failures
        failures += not ok
        print("  [%s] %s%s" % ("pass" if ok else "FAIL", name,
                               "" if ok else "  <- %s" % (detail,)))

    try:
        first = plugin.get_vegas_content()
        check("first call builds the combined slate", scroll.builds == 1, scroll.builds)
        check("returns the slate's own cards, not a standalone mode's",
              isinstance(first, list) and len(first) == 1, first)
        plugin.get_vegas_content()
        check("unchanged games do not rebuild", scroll.builds == 1, scroll.builds)
        slate[0] = _game("21")
        plugin.get_vegas_content()
        check("a score change rebuilds", scroll.builds == 2, scroll.builds)
    except AssertionError as exc:
        check("render path stays off the network and the active scroll", False, exc)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
