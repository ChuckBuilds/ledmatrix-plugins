"""Live Vegas cards: one per game, redrawn only when that game changes.

With LEDMatrix 3.8.0 the Vegas ticker asks get_vegas_elements() for one card
per game and swaps a card in place while it scrolls when its game changes. A
card's width must never change (the ticker refuses a redraw of another
width), only the card whose game changed may be drawn again, and a game that
goes final must keep its card -- now showing FINAL -- rather than vanish from
the slate until the recent list's next refresh.

The slate is the plugin's own simulated live game (nfl.test_mode, the safety
harness's fixture), copied into two games so one can change while the other
does not.

Run: <core-venv>/bin/python -m pytest plugins/football-scoreboard/test_vegas_elements.py
(with the core checkout on PYTHONPATH).
"""
import copy
import logging
import sys
from pathlib import Path

import pytest

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


@pytest.fixture
def plugin():
    spec = load_harness_spec(PLUGIN_DIR)
    config = build_full_config(PLUGIN_DIR, spec, {})
    dm = VisualTestDisplayManager(width=W, height=H)
    plugin = _instantiate("football-scoreboard", load_manifest(PLUGIN_DIR), PLUGIN_DIR,
                          config, {}, dm)
    plugin.nfl_live.update()                  # test_mode: the simulated Q4 game
    live = plugin.nfl_live.live_games[0]
    plugin.slate = {
        "401": dict(copy.deepcopy(live), id="401", league="nfl", status={"state": "in"}),
        "402": dict(copy.deepcopy(live), id="402", league="nfl", status={"state": "in"},
                    home_score="3", away_score="0"),
    }
    plugin._collect_games_for_scroll = lambda live_priority_active=False: (
        [dict(g) for g in plugin.slate.values()], ["nfl"])
    plugin.dm = dm
    return plugin


def _cards(plugin):
    elements = render_vegas_elements(plugin, plugin.dm)
    return {e.key: e for e in elements if e.live}


def _renders(plugin):
    return plugin._scroll_manager.get_scroll_display("mixed")._vegas_cards.renders


def test_one_live_card_per_game_keyed_by_its_id(plugin):
    cards = _cards(plugin)
    assert list(cards) == ["game:nfl:401", "game:nfl:402"]
    assert len({card.image.width for card in cards.values()}) == 1


def test_a_clock_tick_redraws_only_that_games_card(plugin):
    before = _cards(plugin)
    drawn = _renders(plugin)
    plugin.slate["401"]["clock"] = "02:04"
    after = _cards(plugin)
    assert _renders(plugin) == drawn + 1
    assert after["game:nfl:402"].image is before["game:nfl:402"].image
    assert after["game:nfl:401"].image.tobytes() != before["game:nfl:401"].image.tobytes()


def test_nothing_new_draws_nothing(plugin):
    before = _cards(plugin)
    drawn = _renders(plugin)
    after = _cards(plugin)
    assert _renders(plugin) == drawn
    assert all(after[k].image is before[k].image for k in before)


@pytest.mark.parametrize("change", [
    {"home_score": "28"},
    {"home_timeouts": 0, "away_timeouts": 0},
    {"odds": {"spread": -3.5, "over_under": 47.5, "home_team_odds": {}, "away_team_odds": {}}},
    {"possession": None, "down_distance_text": ""},
])
def test_a_card_keeps_its_width_whatever_it_draws(plugin, change):
    width = _cards(plugin)["game:nfl:401"].image.width
    plugin.slate["401"].update(change)
    assert _cards(plugin)["game:nfl:401"].image.width == width


def test_odds_a_live_poll_left_out_do_not_redraw_the_card(plugin):
    plugin.slate["401"]["odds"] = {"spread": -3.5, "over_under": 47.5}
    _cards(plugin)
    drawn = _renders(plugin)
    del plugin.slate["401"]["odds"]
    _cards(plugin)
    assert _renders(plugin) == drawn


def test_a_game_that_goes_final_keeps_its_card_and_shows_final(plugin):
    before = _cards(plugin)["game:nfl:401"]
    live = plugin.slate.pop("401")
    plugin.nfl_live.live_games = [live]       # what the live manager was showing
    final = dict(live, is_live=False, is_final=True, clock="0:00",
                 period_text="Final", status_text="Final")
    plugin.nfl_live._keep_final_for_vegas(final)
    after = _cards(plugin)
    assert "game:nfl:401" in after
    card = after["game:nfl:401"]
    assert card.image.width == before.image.width
    assert card.image.tobytes() != before.image.tobytes()
    # Next time round it follows the games still live, ahead of the rest.
    assert list(after) == ["game:nfl:402", "game:nfl:401"]


def test_the_harness_contract_holds(plugin):
    report = check_vegas_elements(plugin, plugin.dm)
    assert report.implemented and report.ok, report.errors
    assert report.live == 2
