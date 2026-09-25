"""Fantasy Blitz as the display controller sees it.

Loads the plugin against the core's mocks with the harness fixture (recorded
2026 week 2 data, frozen on the Tuesday after), then drives display(),
update(), live priority, big-play detection, the spoiler delay, the
off-season and the ESPN fallback. Needs the LEDMatrix core on the path
(``scripts/run_plugin_tests.py --core``); skipped without it.
"""

import calendar
import copy
import json
import os
import sys
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

pytest.importorskip("src.plugin_system.base_plugin", reason="needs the LEDMatrix core on PYTHONPATH")
freezegun = pytest.importorskip("freezegun")
from src.plugin_system.testing import MockCacheManager, MockDisplayManager, MockPluginManager  # noqa: E402

import fantasy_blitz_data as data_mod  # noqa: E402
import manager as manager_mod  # noqa: E402

with open(os.path.join(HERE, "test", "harness.json"), encoding="utf-8") as fh:
    HARNESS = json.load(fh)
with open(os.path.join(HERE, "test", "fixtures", "cache.json"), encoding="utf-8") as fh:
    FIXTURE = json.load(fh)
with open(os.path.join(HERE, "test", "fixtures", "raw_payloads.json"), encoding="utf-8") as fh:
    RAW = json.load(fh)
FROZEN = HARNESS["freeze_time"]
FROZEN_EPOCH = calendar.timegm(time.strptime(FROZEN, "%Y-%m-%d %H:%M:%S"))
ID = "fantasy-blitz"


class NoNetwork:
    """A session that refuses every request, so a test can never reach the internet."""

    headers = {}

    def get(self, url, **kwargs):
        raise ConnectionError(f"tests are offline: {url}")

    def close(self):
        pass


def make_plugin(overrides=None, fixture=None, size=(128, 64)):
    config = copy.deepcopy(HARNESS["config"])
    for key, value in (overrides or {}).items():
        if isinstance(value, dict) and isinstance(config.get(key), dict):
            config[key] = {**config[key], **value}
        else:
            config[key] = value
    cache = MockCacheManager()
    for key, value in (fixture or FIXTURE).items():
        cache.set(key, copy.deepcopy(value))
    display = MockDisplayManager(*size)
    plugin = manager_mod.FantasyBlitzPlugin(ID, config, display, cache, MockPluginManager())
    plugin.data.session = NoNetwork()
    return plugin, display, cache


@pytest.fixture
def frozen():
    with freezegun.freeze_time(FROZEN) as clock:
        yield clock


def test_recap_week_draws_every_screen(frozen):
    plugin, display, _ = make_plugin()
    plugin.update()
    assert (plugin.phase, plugin.week, plugin.results_week) == ("recap", 3, 2)
    assert set(plugin.content) == {
        "player_card", "leaderboard", "dud_alert", "hot_pickups", "position_kings", "injury_report",
        "watchlist", "weekly_awards", "league_matchup", "season_race"}
    for mode in plugin.modes:
        display.image.paste((0, 0, 0), (0, 0, 128, 64))
        assert plugin.display(force_clear=True, display_mode=mode) is True, mode
        assert display.image.getbbox() is not None, f"{mode} drew nothing"


def test_every_mode_is_registered_up_front(frozen):
    plugin, _, _ = make_plugin()
    assert plugin.modes == list(manager_mod.MODE_SCREENS)
    assert plugin.get_live_modes() == ["fantasy_live"]


def test_big_play_takes_live_priority_then_steps_aside(frozen):
    plugin, _, _ = make_plugin()
    plugin.update()
    assert plugin.has_live_priority() and plugin.has_live_content()
    assert plugin.display(force_clear=True, display_mode="fantasy_live") is True
    assert plugin.get_display_duration() == 8
    frozen.tick(9)
    assert plugin.display(display_mode="fantasy_live") is False, "the alert is done after 8 s"
    assert not plugin.has_live_content(), "one alert a minute"


def test_live_priority_can_be_turned_off(frozen):
    plugin, _, _ = make_plugin({"live_priority": False})
    plugin.update()
    assert not plugin.has_live_content()
    assert plugin.display(force_clear=True, display_mode="fantasy_live") is True, "still shown in rotation"


def _live_fixture(jsn_points):
    """Week 2 as if Seattle's game were on, with Smith-Njigba at ``jsn_points``."""
    fixture = copy.deepcopy(FIXTURE)
    now = FROZEN_EPOCH
    fixture[f"{ID}:state"]["data"]["week"] = 2
    games = fixture[f"{ID}:games:2026:2"]
    games["fetched_at"] = now
    sea = next(g for g in games["data"] if "SEA" in (g["home"], g["away"]))
    sea["state"] = "in"
    stats = fixture[f"{ID}:stats:2026:2"]
    stats["fetched_at"] = now
    stats["data"]["9488"]["pts"] = {"ppr": jsn_points, "half_ppr": jsn_points, "standard": jsn_points}
    fixture[f"{ID}:plays:{sea['id']}"] = {"fetched_at": now,
                                          "data": data_mod.normalize_scoring_plays(RAW["espn_summary"])}
    fixture.pop(f"{ID}:bigplay")
    return fixture, sea


def test_a_points_jump_during_a_live_game_becomes_an_alert(frozen):
    fixture, _ = _live_fixture(27.3)
    plugin, _, cache = make_plugin(fixture=fixture)
    plugin.update()
    assert plugin.phase == "live" and not plugin.alerts.pending, "the first look sets the baseline"
    frozen.tick(61)
    stats = cache.get(f"{ID}:stats:2026:2")
    stats["data"]["9488"]["pts"] = {"ppr": 42.5, "half_ppr": 38.0, "standard": 33.5}
    stats["fetched_at"] += 61
    cache.set(f"{ID}:stats:2026:2", stats)
    plugin.update()
    alert = plugin.alerts.pending[0]
    assert (alert["id"], alert["gain"], alert["desc"], alert["td"]) == ("9488", 15.2, "12-YD TD CATCH", True)
    saved = cache.get(f"{ID}:bigplay")["data"]
    assert saved["pending"][0]["key"] == alert["key"], "survives a restart"
    assert plugin.get_update_interval() == 60


def test_spoiler_delay_holds_the_alert(frozen):
    plugin, _, _ = make_plugin({"spoiler_delay_seconds": 90})
    plugin.update()
    assert not plugin.has_live_content(), "detected 30 s ago; the delay is 90 s"
    frozen.tick(61)
    assert plugin.has_live_content()


def test_off_season_shows_nothing(frozen):
    fixture = copy.deepcopy(FIXTURE)
    fixture[f"{ID}:state"]["data"]["season_type"] = "off"
    plugin, _, _ = make_plugin(fixture=fixture)
    plugin.update()
    assert plugin.phase == "idle"
    assert not any(plugin.display(force_clear=True, display_mode=m) for m in plugin.modes)
    assert not plugin.has_live_content()


def test_screens_can_be_switched_off(frozen):
    plugin, _, _ = make_plugin({"screens": {"leaderboard": {"enabled": False}}})
    plugin.update()
    assert plugin.display(force_clear=True, display_mode="fantasy_leaderboard") is False
    assert plugin.display(force_clear=True, display_mode="fantasy_player_card") is True


def test_screens_outside_their_part_of_the_week_are_skipped(frozen):
    plugin, _, _ = make_plugin()
    plugin.update()
    plugin.phase = "live"
    assert plugin.display(force_clear=True, display_mode="fantasy_hot_pickups") is False
    assert plugin.display(force_clear=True, display_mode="fantasy_injury_report") is False
    assert plugin.display(force_clear=True, display_mode="fantasy_player_card") is True


def test_durations(frozen):
    plugin, _, _ = make_plugin()
    plugin.update()
    plugin.display(force_clear=True, display_mode="fantasy_player_card")
    assert plugin.get_display_duration() == 5 * plugin.item_seconds
    plugin.display(force_clear=True, display_mode="fantasy_leaderboard")
    assert plugin.get_display_duration() == 2 * manager_mod.PAGE_SECONDS, "top ten over two pages"
    configured, _, _ = make_plugin({"screens": {"leaderboard": {"duration": 45}}})
    configured.update()
    configured.display(force_clear=True, display_mode="fantasy_leaderboard")
    assert configured.get_display_duration() == 45


def test_cards_rotate_on_their_timer(frozen):
    plugin, display, _ = make_plugin()
    plugin.update()
    plugin.display(force_clear=True, display_mode="fantasy_player_card")
    first = display.image.copy()
    frozen.tick(plugin.item_seconds + 0.5)
    plugin.display(display_mode="fantasy_player_card")
    assert display.image.tobytes() != first.tobytes()


def test_a_still_frame_is_pushed_once(frozen):
    plugin, display, _ = make_plugin()
    plugin.update()
    plugin.display(force_clear=True, display_mode="fantasy_season_race")
    display.update_called = False
    frozen.tick(0.5)
    assert plugin.display(display_mode="fantasy_season_race") is True
    assert not display.update_called, "an unchanged frame is not re-sent"
    plugin.display(display_mode="fantasy_player_card")
    plugin.display(display_mode="fantasy_season_race")
    assert display.update_called, "re-entering a mode always pushes its frame"


def test_high_fps_follows_the_animation_setting(frozen):
    animated, _, _ = make_plugin({"advanced": {"animations": True, "headshot_downloads": False}})
    animated.update()
    animated.display(force_clear=True, display_mode="fantasy_player_card")
    assert animated.needs_high_fps is True
    still, _, _ = make_plugin()
    still.update()
    still.display(force_clear=True, display_mode="fantasy_player_card")
    assert still.needs_high_fps is False


def test_every_panel_size_draws(frozen):
    for size in ((64, 32), (128, 32), (256, 32), (64, 64), (256, 128)):
        plugin, display, _ = make_plugin(size=size)
        plugin.update()
        for mode in plugin.modes:
            assert plugin.display(force_clear=True, display_mode=mode) is True, (size, mode)


def test_vegas_content(frozen):
    plugin, _, _ = make_plugin()
    plugin.update()
    cards = plugin.get_vegas_content()
    assert cards and all(card.height == 64 for card in cards)
    assert plugin.get_vegas_content_type() == "multi"


def test_espn_fallback_when_sleeper_is_down(frozen):
    fixture = copy.deepcopy(FIXTURE)
    fixture.pop(f"{ID}:stats:2026:2")

    class Session(NoNetwork):
        def get(self, url, **kwargs):
            if "fantasy.espn.com" in url:
                return _Response(RAW["espn_fantasy"])
            raise ConnectionError("Sleeper is down")

    plugin, _, _ = make_plugin(fixture=fixture)
    plugin.data.session = Session()
    plugin.update()
    assert "espn:3918298" in plugin.players
    assert plugin.content["player_card"][0]["player"]["id"] == "espn:4430878"


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


def test_config_change_applies_without_a_restart(frozen):
    plugin, _, _ = make_plugin()
    plugin.update()
    new = copy.deepcopy(plugin.config)
    new["scoring_format"] = "standard"
    new["top_n"] = 2
    plugin.on_config_change(new)
    assert plugin.scoring == "standard" and len(plugin.content["player_card"]) == 2


def test_info_reports_the_week(frozen):
    plugin, _, _ = make_plugin()
    plugin.update()
    info = plugin.get_info()
    assert info["phase"] == "recap" and info["results_week"] == 2
    assert "Josh Allen" in info["watchlist_matched"]
