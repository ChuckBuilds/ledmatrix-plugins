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
6. global.dynamic_duration.* takes effect. The deprecated flat keys
   (global.min_duration, max_duration, duration_buffer, max_display_time)
   carried schema defaults, core merges schema defaults into every config, and
   the flat keys always overrode the nested ones: a nested min 20 / max 120 ran
   as 45 / 600. A flat key now applies only while its nested key is at default.
7. The code-default enabled leagues (a league block missing from the config)
   match the schema's: they enabled ncaam_hockey and not nba, mlb or nhl.

Exit codes follow scripts/run_plugin_tests.py: 0 pass, 1 fail, 2 skip.

    LEDMATRIX_CORE=/path/to/LEDMatrix python plugins/ledmatrix-leaderboard/test_display_and_live_config.py
"""

import json
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


class _ChecksFailed(AssertionError):
    """Raised after a test whose check() calls recorded failures."""


def _fail_loudly(test):
    """Make a check() failure fail the test under pytest too.

    check() records failures for script mode's exit code; without this, pytest
    collected each test_* as passing whatever it recorded.
    """
    import functools

    @functools.wraps(test)
    def wrapper(*args, **kwargs):
        before = len(failures)
        test(*args, **kwargs)
        if len(failures) > before:
            raise _ChecksFailed("; ".join(failures[before:]))
    return wrapper


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


@_fail_loudly
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


@_fail_loudly
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


@_fail_loudly
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


def _as_core_loads_it(config):
    """The config merged with the schema's defaults, as core's plugin loader does."""
    from src.plugin_system.schema_manager import SchemaManager
    with open(os.path.join(HERE, "config_schema.json"), encoding="utf-8") as f:
        schema = json.load(f)
    manager = SchemaManager()
    return manager.merge_with_defaults(config, manager.extract_defaults_from_schema(schema))


def _durations(plugin):
    return (plugin.min_duration, plugin.max_duration, plugin.duration_buffer,
            plugin.dynamic_duration_cap)


@_fail_loudly
def test_nested_dynamic_duration_wins():
    print("[global.dynamic_duration vs the deprecated flat keys]")
    data_fetcher.DataFetcher.fetch_standings = lambda self, cfg: []
    nested = {"min_duration_seconds": 20, "max_duration_seconds": 120,
              "buffer_ratio": 0.3, "controller_cap_seconds": 900}

    fresh = _as_core_loads_it({"enabled": True, "enabled_sports": ONLY_NBA,
                               "global": {"dynamic_duration": dict(nested)}})
    check(not any(k in fresh["global"] for k in
                  ("min_duration", "max_duration", "duration_buffer", "max_display_time")),
          "the schema no longer supplies the deprecated flat keys "
          f"(global keys {sorted(fresh['global'])})")
    plugin = make(fresh, FakeDisplay())
    check(_durations(plugin) == (20, 120, 0.3, 900),
          f"nested settings apply on a fresh install (got {_durations(plugin)})")

    # Saved from the web UI before the fix: the flat keys' old defaults are
    # stored alongside the user's nested settings.
    saved = {"enabled": True, "enabled_sports": ONLY_NBA,
             "global": {"dynamic_duration": dict(nested), "min_duration": 45,
                        "max_duration": 600, "duration_buffer": 0.1,
                        "max_display_time": 600}}
    plugin = make(_as_core_loads_it(saved), FakeDisplay())
    check(_durations(plugin) == (20, 120, 0.3, 900),
          f"nested settings beat stored flat defaults (got {_durations(plugin)})")

    legacy = {"enabled": True, "enabled_sports": ONLY_NBA,
              "global": {"min_duration": 90, "max_duration": 240,
                         "duration_buffer": 0.2, "max_display_time": 300}}
    plugin = make(_as_core_loads_it(legacy), FakeDisplay())
    check(_durations(plugin) == (90, 240, 0.2, 300),
          f"a legacy-only config keeps its flat values (got {_durations(plugin)})")

    plugin.on_config_change(_as_core_loads_it(
        {"enabled": True, "enabled_sports": ONLY_NBA,
         "global": dict(legacy["global"], dynamic_duration={"min_duration_seconds": 15})}))
    check(_durations(plugin)[:2] == (15, 240),
          f"a nested key set on save wins; untouched ones keep the flat value "
          f"(got {_durations(plugin)})")
    check(plugin.scroll_helper.min_duration == 15,
          f"the scroll helper gets the nested minimum (got {plugin.scroll_helper.min_duration})")


@_fail_loudly
def test_code_default_leagues_match_schema():
    print("[code-default enabled leagues]")
    from league_config import LeagueConfig
    with open(os.path.join(HERE, "config_schema.json"), encoding="utf-8") as f:
        leagues = json.load(f)["properties"]["enabled_sports"]["properties"]
    configs = LeagueConfig({}).league_configs
    check(set(configs) == set(leagues),
          f"the code and the schema know the same leagues ({sorted(configs)} vs {sorted(leagues)})")
    for league, spec in leagues.items():
        if league not in configs:
            continue
        for key, prop in spec["properties"].items():
            if "default" not in prop:
                continue
            got = configs[league].get(key)
            check(got == prop["default"],
                  f"{league}.{key} defaults to the schema's {prop['default']!r} (got {got!r})")


if __name__ == "__main__":
    for test in (test_display_does_not_fetch, test_update_interval_and_live_save,
                 test_hockey_show_ranking, test_nested_dynamic_duration_wins,
                 test_code_default_leagues_match_schema):
        try:
            test()
        except _ChecksFailed:
            pass  # its checks are already recorded in failures
        except Exception as exc:  # a crash is a failure, not a skip
            failures.append(f"{test.__name__} raised {exc!r}")
            print(f"  FAIL: {test.__name__} raised {exc!r}")
    print(f"\n{len(failures)} failed")
    sys.exit(1 if failures else 0)
