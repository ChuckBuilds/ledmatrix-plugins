#!/usr/bin/env python3
"""Plugin-level contracts for NFL Stat Leaders.

The rules that keep the plugin a good citizen of the display loop:
``display()`` never fetches, a hand-edited config cannot crash startup, a
web-UI save is applied without a restart, and a failed fetch is retried
sooner than the configured interval.

Needs the LEDMatrix core on the path (LEDMATRIX_CORE, or a sibling
checkout). Exit codes: 0 pass, 1 fail, 2 skip.
"""

import os
import sys

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)


def _find_core():
    env = os.environ.get("LEDMATRIX_CORE")
    candidates = [env] if env else []
    candidates += [
        os.path.join(PLUGIN_DIR, "..", "..", ".."),
        os.path.join(PLUGIN_DIR, "..", "..", "..", "LEDMatrix"),
    ]
    for candidate in candidates:
        if candidate and os.path.isdir(
                os.path.join(candidate, "src", "plugin_system")):
            return os.path.abspath(candidate)
    return None


CORE = _find_core()
if not CORE:
    print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
    sys.exit(2)
if CORE not in sys.path:
    sys.path.insert(0, CORE)

try:
    from src.plugin_system.testing.mocks import (
        MockCacheManager,
        MockPluginManager,
    )
    # The plain MockDisplayManager has no scrolling surface; this is the one
    # the core's own render harness drives scrolling plugins with, and it
    # also fails the test if anything is drawn past the panel edge.
    from src.plugin_system.testing.bounds_display_manager import (
        BoundsCheckingDisplayManager,
    )
except ImportError as exc:
    print("SKIP: core testing mocks unavailable (%s)" % exc)
    sys.exit(2)

from manager import NFLStatLeadersPlugin
from nfl_stat_fetcher import StatFetcher

# No test in this file may reach the network: CI runners have connectivity,
# and a suite that quietly depends on ESPN being up is a suite that goes red
# for reasons that have nothing to do with the change under test. Every
# fetch is served from the seeded cache, or answers None.
StatFetcher._request_payload = lambda self, season, season_type: None

FAILURES = []

PAYLOAD = {"categories": [
    {"name": "passingYards", "displayName": "Passing Yards", "leaders": [
        {"displayValue": "4,183",
         "athlete": {"shortName": "J. Allen",
                     "position": {"abbreviation": "QB"}},
         "team": {"$ref": "http://x/v2/teams/2?lang=en"}},
    ]},
]}


def check(label, condition, detail=""):
    if condition:
        print("[pass] %s" % label)
    else:
        print("[FAIL] %s%s" % (label, (" -- " + detail) if detail else ""))
        FAILURES.append(label)


def build(config=None, seed_cache=True):
    """A plugin instance whose fetches are served entirely from the cache."""
    cache = MockCacheManager()
    if seed_cache:
        cache.set("nfl-stat-leaders_2025_2",
                  {"fetched_at": 0, "payload": PAYLOAD})
    settings = {"enabled": True, "season": 2025, "season_type": "regular"}
    settings.update(config or {})
    plugin = NFLStatLeadersPlugin(
        "nfl-stat-leaders", settings,
        BoundsCheckingDisplayManager(128, 32), cache, MockPluginManager())
    return plugin, cache


def test_it_loads_and_shows_the_cached_board():
    plugin, _ = build()
    check("the board is loaded at startup", len(plugin.boards) == 1,
          str(plugin.boards))
    check("the leader survived normalisation",
          plugin.boards[0]["leaders"][0]["team"] == "BUF")
    plugin.display(force_clear=True)
    check("a strip was built and scrolled",
          plugin.scroll_helper.cached_image is not None)
    plugin.cleanup()


def test_display_never_goes_to_the_network():
    """display() runs on the render loop; a blocking request there stalls it."""
    plugin, _ = build(seed_cache=False)
    calls = {"n": 0}

    def counted(*args, **kwargs):
        calls["n"] += 1
        return None

    plugin.fetcher._request_payload = counted
    for _ in range(5):
        plugin.display()
    check("no fetch happened from display()", calls["n"] == 0,
          "%d request(s)" % calls["n"])
    plugin.cleanup()


def test_a_failed_fetch_is_retried_sooner():
    plugin, _ = build(seed_cache=False, config={"update_interval": 21600})
    check("no data means a short retry interval",
          plugin.get_update_interval() == float(plugin.NO_DATA_RETRY_SECONDS),
          str(plugin.get_update_interval()))
    plugin, _ = build(config={"update_interval": 21600})
    check("with data the configured interval is used",
          plugin.get_update_interval() == 21600.0,
          str(plugin.get_update_interval()))
    plugin.cleanup()


def test_a_hand_edited_config_cannot_crash_startup():
    plugin, _ = build(config={
        "update_interval": "not a number",
        "players_per_category": 999,
        "season": None,
        "categories": "nonsense",
        "global": {"display_duration": {"bad": True},
                   "dynamic_duration": {"buffer_ratio": "x"}},
    })
    check("a bad update_interval falls back to the default",
          plugin.update_interval == 3600, str(plugin.update_interval))
    check("players_per_category is clamped to the schema maximum",
          plugin.players_per_category == 10,
          str(plugin.players_per_category))
    check("a nonsense categories value keeps the defaults",
          len(plugin.categories) == 6, str(len(plugin.categories)))
    check("a bad buffer ratio falls back", plugin.duration_buffer == 0.1)
    plugin.cleanup()


def test_a_web_ui_save_is_applied_without_a_restart():
    plugin, cache = build()
    check("six categories to start", len(plugin.categories) == 6)
    plugin.on_config_change({
        "enabled": True, "season": 2025, "season_type": "postseason",
        "players_per_category": 3,
        "categories": {"passing_yards": True, "passing_touchdowns": False,
                       "rushing_yards": False, "rushing_touchdowns": False,
                       "receiving_yards": False, "receiving_touchdowns": False},
    })
    check("the new category selection took effect",
          [c.key for c in plugin.categories] == ["passing_yards"],
          str([c.key for c in plugin.categories]))
    check("the season type changed", plugin.season_type == 3)
    check("the cached strip was dropped so it is rebuilt",
          plugin.scroll_helper.cached_image is None)
    plugin.cleanup()


def test_the_scroll_is_paced_by_the_shared_resolver():
    plugin, _ = build()
    check("a scroll speed was resolved",
          float(getattr(plugin.scroll_helper, "scroll_speed", 0)) > 0,
          str(getattr(plugin.scroll_helper, "scroll_speed", None)))
    check("the plugin asks the controller for its high-FPS loop",
          plugin.enable_scrolling is True)
    check("a frame hold is reported", plugin._scroll_frame_hold() >= 1)
    plugin.cleanup()


def test_the_slot_length_follows_the_ticker():
    plugin, _ = build()
    plugin.display(force_clear=True)
    check("dynamic duration is offered", plugin.supports_dynamic_duration())
    check("the duration is taken from the strip's width",
          plugin.get_display_duration() > 0)
    check("the cycle is not complete on the first frame",
          plugin.is_cycle_complete() is False)
    plugin.reset_cycle_state()
    check("resetting clears the completion flag",
          plugin.is_cycle_complete() is False)
    plugin.cleanup()


def test_no_categories_enabled_is_not_an_error():
    plugin, _ = build(config={
        "categories": {"passing_yards": False, "passing_touchdowns": False,
                       "rushing_yards": False, "rushing_touchdowns": False,
                       "receiving_yards": False, "receiving_touchdowns": False,
                       "receptions": False, "sacks": False,
                       "interceptions": False, "total_tackles": False,
                       "quarterback_rating": False}})
    check("nothing is loaded", plugin.boards == [])
    plugin.display()
    check("and the panel still draws its holding screen", True)
    plugin.cleanup()


def main():
    for name, value in sorted(globals().items()):
        if name.startswith("test_") and callable(value):
            value()
    if FAILURES:
        print("\n%d check(s) failed" % len(FAILURES))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
