"""Live Vegas cards: one per game, redrawn only when that game changes.

With LEDMatrix 3.8.0 the Vegas ticker asks get_vegas_elements() for one card
per game and swaps a card in place while it scrolls when its game changes. A
card's width must never change (the ticker refuses a redraw of another
width), only the card whose game changed may be drawn again, and a game that
goes final must keep its card -- now showing Final -- rather than vanish from
the slate until the recent list's next refresh.

The slate is the plugin's own simulated live game (ncaa_mens.test_mode, the
safety harness's fixture), copied into two games so one can change while the
other does not.

Run: <core-venv>/bin/python -m pytest plugins/lacrosse-scoreboard/test_vegas_elements.py
(with the core checkout on PYTHONPATH).
"""
import copy
import logging
import sys
from pathlib import Path

import pytest
from PIL import Image

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))

logging.disable(logging.CRITICAL)

try:
    from src.plugin_system.testing.harness import _instantiate
    from src.plugin_system.testing.loading import (
        build_full_config, load_harness_spec, load_manifest,
    )
    from src.plugin_system.testing.vegas import check_vegas_elements, render_vegas_elements
    from src.plugin_system.testing.visual_display_manager import VisualTestDisplayManager
    from src.common import sports_vegas  # noqa: F401 - LEDMatrix 3.8.0
except ImportError as exc:  # a core without live Vegas cards
    pytest.skip(f"core has no live Vegas cards ({exc})", allow_module_level=True)

W, H = 128, 32
LEAGUE = "ncaam_lacrosse"


@pytest.fixture
def plugin(tmp_path):
    return _make_plugin(tmp_path, W, H)


def _make_plugin(tmp_path, width, height):
    # The core checkout ships no JHU logo (a rig downloads it on first use),
    # and a card missing a logo is drawn as a text-only error card.
    logos = tmp_path / "ncaa_logos"
    logos.mkdir()
    Image.new("RGBA", (24, 24), (224, 58, 62, 255)).save(logos / "MD.png")
    Image.new("RGBA", (24, 24), (0, 45, 114, 255)).save(logos / "JHU.png")
    spec = load_harness_spec(PLUGIN_DIR)
    # Shots and odds drawn too, so the width checks see them on the card.
    config = build_full_config(PLUGIN_DIR, spec, {
        "defaults": {"show_odds": True},
        "ncaa_mens": {"logo_dir": str(logos), "display_options": {"show_shots": True}},
    })
    dm = VisualTestDisplayManager(width=width, height=height)
    plugin = _instantiate("lacrosse-scoreboard", load_manifest(PLUGIN_DIR), PLUGIN_DIR,
                          config, {}, dm)
    plugin.ncaa_mens_live.update()            # test_mode: the simulated Q2 game
    live = plugin.ncaa_mens_live.live_games[0]
    plugin.slate = {
        "401": dict(copy.deepcopy(live), id="401", league=LEAGUE, status={"state": "in"}),
        "402": dict(copy.deepcopy(live), id="402", league=LEAGUE, status={"state": "in"},
                    home_score="3", away_score="0"),
    }
    plugin._collect_games_for_scroll = lambda: (
        [dict(g) for g in plugin.slate.values()], [LEAGUE])
    plugin.dm = dm
    return plugin


def _cards(plugin):
    elements = render_vegas_elements(plugin, plugin.dm)
    return {e.key: e for e in elements if e.live}


def _renders(plugin):
    return plugin._scroll_manager.get_scroll_display("mixed")._vegas_cards.renders


def _poll(manager, details):
    """One real live poll whose feed holds just this game, offline."""
    manager.test_mode = False
    manager._fetch_data = lambda: {"events": [{"id": details["id"]}]}
    manager._extract_game_details = lambda event: dict(details)
    manager.last_update = 0
    manager.update()


def test_one_live_card_per_game_keyed_by_its_id(plugin):
    cards = _cards(plugin)
    assert list(cards) == [f"game:{LEAGUE}:401", f"game:{LEAGUE}:402"]
    assert len({card.image.width for card in cards.values()}) == 1


def test_a_clock_tick_redraws_only_that_games_card(plugin):
    before = _cards(plugin)
    drawn = _renders(plugin)
    plugin.slate["401"]["clock"] = "02:04"
    after = _cards(plugin)
    assert _renders(plugin) == drawn + 1
    assert after[f"game:{LEAGUE}:402"].image is before[f"game:{LEAGUE}:402"].image
    assert after[f"game:{LEAGUE}:401"].image.tobytes() != \
        before[f"game:{LEAGUE}:401"].image.tobytes()


def test_nothing_new_draws_nothing(plugin):
    before = _cards(plugin)
    drawn = _renders(plugin)
    after = _cards(plugin)
    assert _renders(plugin) == drawn
    assert all(after[k].image is before[k].image for k in before)


@pytest.mark.parametrize("change", [
    {"home_score": "28"},
    {"period": 5, "period_text": "OT1", "clock": "3:59"},
    {"home_shots": 41, "away_shots": 38},
    {"odds": {"spread": -3.5, "over_under": 24.5, "home_team_odds": {}, "away_team_odds": {}}},
])
def test_a_card_keeps_its_width_whatever_it_draws(plugin, change):
    width = _cards(plugin)[f"game:{LEAGUE}:401"].image.width
    plugin.slate["401"].update(change)
    assert _cards(plugin)[f"game:{LEAGUE}:401"].image.width == width


def test_odds_a_live_poll_left_out_do_not_redraw_the_card(plugin):
    plugin.slate["401"]["odds"] = {"spread": -3.5, "over_under": 24.5}
    _cards(plugin)
    drawn = _renders(plugin)
    del plugin.slate["401"]["odds"]
    _cards(plugin)
    assert _renders(plugin) == drawn


@pytest.mark.parametrize("over", [
    {"is_live": False, "is_final": True, "period_text": "Final", "status_text": "Final"},
    # Still "in" on the feed, but the clock has run out in the fourth.
    {"period": 4, "clock": "0:00", "period_text": "Q4"},
], ids=["final", "really_over"])
def test_a_game_that_goes_final_keeps_its_card_and_shows_final(plugin, over):
    before = _cards(plugin)[f"game:{LEAGUE}:401"]
    live = plugin.slate.pop("401")
    manager = plugin.ncaa_mens_live
    manager.live_games = [live]               # what the live manager was showing
    _poll(manager, dict(live, **over))
    assert manager.live_games == []           # the poll dropped it
    after = _cards(plugin)
    assert f"game:{LEAGUE}:401" in after
    card = after[f"game:{LEAGUE}:401"]
    assert card.image.width == before.image.width
    assert card.image.tobytes() != before.image.tobytes()
    # Next time round it follows the games still live, ahead of the rest.
    assert list(after) == [f"game:{LEAGUE}:402", f"game:{LEAGUE}:401"]


def test_a_level_game_at_the_end_of_the_fourth_is_not_kept_as_final(plugin):
    # Level at 0:00 is the break before sudden-victory overtime: the game
    # stays live (_is_game_really_over's tie guard) and is no result, so its
    # card does not turn to "Final 7-7".
    live = plugin.slate.pop("401")
    manager = plugin.ncaa_mens_live
    manager.live_games = [live]
    _poll(manager, dict(live, period=4, clock="0:00", period_text="Q4",
                        home_score="7", away_score="7"))
    assert [g["id"] for g in manager.live_games] == ["401"]
    assert manager.finished_games_snapshot() == []
    assert f"game:{LEAGUE}:401" not in _cards(plugin)   # nothing held as a final


@pytest.mark.parametrize("size", [(128, 32), (128, 64)])
def test_a_card_is_the_scroll_strips_card_without_its_padding(tmp_path, size):
    # At 128x64 the card (sized for two full-height logos) is wider than the
    # panel, so a renderer built at the wrong width shows here.
    plugin = _make_plugin(tmp_path, *size)
    live = plugin.slate["401"]
    plugin.slate["403"] = dict(copy.deepcopy(live), id="403", status={"state": "post"},
                               is_live=False, is_final=True)
    plugin.slate["404"] = dict(copy.deepcopy(live), id="404", status={"state": "pre"},
                               is_live=False, is_upcoming=True)
    games, leagues = plugin._collect_games_for_scroll()
    cards = _cards(plugin)
    display = plugin._scroll_manager.get_scroll_display("mixed")
    assert display.prepare_scroll_content(copy.deepcopy(games), "mixed", leagues, None)
    settings = display._get_scroll_settings()
    pad = max(4, settings.get("gap_between_games", 48) // 2)
    strip = display._vegas_content_items[-len(games):]     # after the league separator
    for game, padded in zip(games, strip):
        card = cards[f"game:{LEAGUE}:{game['id']}"].image
        assert card.width == settings["game_card_width"] == padded.width - 2 * pad
        assert card.tobytes() == padded.crop((pad, 0, padded.width - pad, padded.height)).tobytes()


def test_a_clock_changed_in_place_after_the_first_strip_is_drawn(plugin):
    # test_mode ticks its game's clock on the same dict, and the ticker's
    # first strip (get_vegas_content) has already filled that dict's status.
    plugin.get_vegas_content()
    before = _cards(plugin)[f"game:{LEAGUE}:401"]
    plugin.slate["401"]["clock"] = "02:04"
    after = _cards(plugin)[f"game:{LEAGUE}:401"]
    assert after.image.tobytes() != before.image.tobytes()


def test_the_harness_contract_holds(plugin):
    report = check_vegas_elements(plugin, plugin.dm)
    assert report.implemented and report.ok, report.errors
    assert report.live == 2
