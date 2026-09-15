#!/usr/bin/env python3
"""
Regression tests for the leaderboard's render path and settings plumbing.

1. display() never fetches. It called update(force=True) on every frame while
   there was no data, so an ESPN outage blocked the render loop for up to the
   30s request timeout per league, per frame.
2. The fallback message fits the panel ("No Leaderboard Data" is 152px in the
   8px font; it was centred on 128px and cut at both edges), and the scroll
   state is released while it shows.
3. update_interval is honoured. The manifest's 3600 won over the configured
   value, and the code read global.update_interval, which the schema does not
   declare; get_update_interval() now returns the top-level update_interval.
4. A web-UI save applies without a restart (there was no on_config_change), and
   re-runs the scroll resolver.
5. enabled_sports.ncaam_hockey.show_ranking does something.

Exit codes follow scripts/run_plugin_tests.py: 0 pass, 1 fail, 2 skip.

    LEDMATRIX_CORE=/path/to/LEDMatrix python plugins/ledmatrix-leaderboard/test_display_and_live_config.py
"""

import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
_core = os.environ.get("LEDMATRIX_CORE")
if _core and _core not in sys.path:
    sys.path.insert(0, _core)

try:
    from PIL import Image
    import src
    from src.common import scroll_config  # noqa: F401  (3.4.0 floor)
except ImportError as exc:
    print(f"SKIP: LEDMatrix core (3.4.0+) or Pillow not importable: {exc}")
    sys.exit(2)

# The renderer's fonts resolve relative to the core checkout, as on an install.
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(src.__file__))))

import data_fetcher  # noqa: E402
from manager import LeaderboardPlugin  # noqa: E402

failures = []


def check(cond, msg):
    print(("  PASS: " if cond else "  FAIL: ") + msg)
    if not cond:
        failures.append(msg)


class FakeDisplay:
    refresh_hz = 100.0

    def __init__(self, width=128, height=32):
        self.width = width
        self.height = height
        self.image = Image.new("RGB", (width, height))
        self.calls = []

    def set_scrolling_state(self, is_scrolling, frame_hold=1):
        self.calls.append((is_scrolling, frame_hold))

    def process_deferred_updates(self):
        pass

    def update_display(self):
        pass


ONLY_NBA = {league: {"enabled": league == "nba"} for league in (
    "nfl", "nba", "mlb", "ncaa_fb", "nhl", "ncaam_basketball",
    "ncaam_hockey", "ncaaw_basketball", "ncaa_baseball")}


def make(config, display):
    return LeaderboardPlugin("ledmatrix-leaderboard", config, display,
                             types.SimpleNamespace(), types.SimpleNamespace())


def test_display_does_not_fetch():
    print("[display() with no data]")
    fetches = []
    data_fetcher.DataFetcher.fetch_standings = lambda self, cfg: fetches.append(cfg["league"]) or []

    display = FakeDisplay()
    plugin = make({"enabled": True, "enabled_sports": ONLY_NBA, "global": {}}, display)
    at_load = len(fetches)
    for _ in range(5):
        plugin.display()
    check(len(fetches) == at_load,
          f"five frames made no fetches (fetches went {at_load} -> {len(fetches)})")
    check(display.calls[-1:] == [(False, 1)],
          f"the scroll state is released while the fallback shows (calls {display.calls[-3:]})")

    box = display.image.getbbox()
    check(box is not None, "the fallback message was drawn")
    if box:
        check(box[0] > 0 and box[2] < display.width,
              f"the fallback message fits the 128px panel (ink spans x={box[0]}..{box[2]})")
    check(plugin.get_update_interval() == 300,
          f"with nothing fetched, update() is asked for again within 5 minutes "
          f"(got {plugin.get_update_interval()})")


def test_update_interval_and_live_save():
    print("[update_interval and on_config_change]")
    data_fetcher.DataFetcher.fetch_standings = lambda self, cfg: [
        {"abbreviation": "BOS", "name": "Celtics", "id": "2", "record_summary": "1-0"}]

    display = FakeDisplay()
    config = {"enabled": True, "update_interval": 900, "enabled_sports": ONLY_NBA,
              "global": {"display": {"scroll_speed": 1.0, "scroll_delay": 0.01}}}
    plugin = make(config, display)
    check(plugin.get_update_interval() == 900,
          f"get_update_interval() returns the configured 900 (got {plugin.get_update_interval()})")

    new_config = {"enabled": True, "update_interval": 1800,
                  "enabled_sports": dict(ONLY_NBA, nhl={"enabled": True}),
                  "global": {"display": {"scroll_speed": 1.0, "scroll_delay": 0.02}}}
    plugin.on_config_change(new_config)
    settings = getattr(plugin, "_scroll_settings", None)
    requested = getattr(settings, "requested_pixels_per_second", None)
    check(requested is not None and abs(requested - 50.0) < 0.01,
          f"the scroll resolver re-ran for the new 50 px/s (got {requested})")
    check(plugin.get_update_interval() == 1800,
          f"a new update_interval applies without a restart (got {plugin.get_update_interval()})")
    check(plugin.league_config.get_enabled_leagues() == ["nba", "nhl"],
          f"a newly enabled league applies without a restart "
          f"(got {plugin.league_config.get_enabled_leagues()})")


def test_hockey_show_ranking():
    print("[ncaam_hockey.show_ranking]")
    display = FakeDisplay()
    data_fetcher.DataFetcher.fetch_standings = lambda self, cfg: []
    for show, expected in ((True, "#3"), (False, "1.")):
        sports = dict(ONLY_NBA, ncaam_hockey={"enabled": False, "show_ranking": show})
        plugin = make({"enabled": True, "enabled_sports": sports, "global": {}}, display)
        league = plugin.league_config.get_league_config("ncaam_hockey")
        text = plugin.image_renderer._get_number_text("ncaam_hockey", league, {"rank": 3}, 0)
        check(text == expected, f"show_ranking={show} draws {expected!r} (got {text!r})")


if __name__ == "__main__":
    for test in (test_display_does_not_fetch, test_update_interval_and_live_save,
                 test_hockey_show_ranking):
        try:
            test()
        except Exception as exc:  # a crash is a failure, not a skip
            failures.append(f"{test.__name__} raised {exc!r}")
            print(f"  FAIL: {test.__name__} raised {exc!r}")
    print(f"\n{len(failures)} failed")
    sys.exit(1 if failures else 0)
