"""Live Vegas cards: one per game, redrawn only when that game changes.

With LEDMatrix 3.8.0 the Vegas ticker asks get_vegas_elements() for one card
per game and swaps a card in place while it scrolls when its game changes. A
card's width must never change (the ticker refuses a redraw of another
width), only the card whose game changed may be drawn again, and a game that
goes final must keep its card -- now showing Final -- rather than vanish from
the slate until the recent list's next refresh.

The slate is the plugin's own simulated live game (nhl.test_mode, the safety
harness's fixture), copied into two games so one can change while the other
does not. A game going final is a real poll through SportsLive.update(), built
from the harness's in-progress fixture event, so both places the poll drops a
finished game are covered.

Run: <core-venv>/bin/python -m pytest plugins/hockey-scoreboard/test_vegas_elements.py
(with the core checkout on PYTHONPATH).
"""
import copy
import json
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
    from src.common import sports_vegas  # LEDMatrix 3.8.0
except ImportError as exc:  # a core without live Vegas cards
    pytest.skip(f"core has no live Vegas cards ({exc})", allow_module_level=True)

# The card renderer reads logos from paths relative to the core checkout, where
# the display service runs; anywhere else every card is the "DAL@TB" error card.
CORE = Path(sports_vegas.__file__).resolve().parents[2]

W, H = 128, 32


@pytest.fixture
def plugin(request, monkeypatch):
    width, height = getattr(request, "param", (W, H))     # the panel
    monkeypatch.chdir(CORE)
    spec = load_harness_spec(PLUGIN_DIR)
    config = build_full_config(PLUGIN_DIR, spec, {})
    dm = VisualTestDisplayManager(width=width, height=height)
    plugin = _instantiate("hockey-scoreboard", load_manifest(PLUGIN_DIR), PLUGIN_DIR,
                          config, {}, dm)
    live_manager = plugin.nhl_live
    live_manager.update()                     # test_mode: the simulated P2 game
    live = live_manager.live_games[0]
    live_manager.live_games = [
        dict(copy.deepcopy(live), id="401"),
        dict(copy.deepcopy(live), id="402", home_score="0", away_score="0"),
    ]
    live_manager.current_game = live_manager.live_games[0]   # what test_mode ticks
    plugin.dm = dm
    return plugin


def _cards(plugin):
    elements = render_vegas_elements(plugin, plugin.dm)
    return {e.key: e for e in elements if e.live}


def _renders(plugin):
    return plugin._scroll_manager.get_scroll_display("mixed")._vegas_cards.renders


def _game(plugin, game_id):
    return next(g for g in plugin.nhl_live.live_games if g["id"] == game_id)


def _poll_event(game_id, state, period, clock, short_detail, away_score="2", home_score=None):
    """The harness's in-progress DAL@TB event, as a poll would return it now."""
    fixture = json.loads((PLUGIN_DIR / "test" / "fixtures" / "mock.json")
                         .read_text(encoding="utf-8"))
    event = copy.deepcopy(next(e for e in fixture["nhl_schedule_window_14_7"]["events"]
                               if e["competitions"][0]["status"]["type"]["state"] == "in"))
    event["id"] = game_id
    competition = event["competitions"][0]
    status = competition["status"]
    status.update(period=period, displayClock=clock)
    status["type"].update(state=state, shortDetail=short_detail, detail=short_detail,
                          completed=state == "post",
                          name="STATUS_FINAL" if state == "post" else "STATUS_IN_PROGRESS")
    next(c for c in competition["competitors"] if c["homeAway"] == "away")["score"] = away_score
    if home_score is not None:
        next(c for c in competition["competitors"]
             if c["homeAway"] == "home")["score"] = home_score
    return event


def test_one_live_card_per_game_keyed_by_its_id(plugin):
    cards = _cards(plugin)
    assert list(cards) == ["game:nhl:401", "game:nhl:402"]
    assert len({card.image.width for card in cards.values()}) == 1


# The card is sized from the panel's height, not its width: only at 128x32 are
# the two the same, so the other panels catch a renderer built at the wrong width.
@pytest.mark.parametrize("plugin", [(W, H), (64, 32), (192, 48)], indirect=True,
                         ids=lambda size: "%dx%d" % size)
def test_a_live_card_is_the_vegas_content_card_without_its_padding(plugin):
    cards = list(_cards(plugin).values())
    padded = plugin.get_vegas_content()[-2:]  # after the NHL separator
    assert len(cards) == len(padded) == 2
    for card, item in zip(cards, padded):
        pad = (item.width - card.image.width) // 2
        assert pad > 0
        assert item.crop((pad, 0, pad + card.image.width, item.height)).tobytes() \
            == card.image.tobytes()


def test_a_clock_tick_redraws_only_that_games_card(plugin):
    before = _cards(plugin)
    drawn = _renders(plugin)
    plugin.nhl_live.last_update = 0
    plugin.nhl_live.update()                  # test_mode ticks game 401's clock in place
    after = _cards(plugin)
    assert _renders(plugin) == drawn + 1
    assert after["game:nhl:402"].image is before["game:nhl:402"].image
    assert after["game:nhl:401"].image.tobytes() != before["game:nhl:401"].image.tobytes()


def test_nothing_new_draws_nothing(plugin):
    before = _cards(plugin)
    drawn = _renders(plugin)
    after = _cards(plugin)
    assert _renders(plugin) == drawn
    assert all(after[k].image is before[k].image for k in before)


@pytest.mark.parametrize("change", [
    {"home_score": "10", "away_score": "12"},
    {"power_play": True},
    {"home_shots": 45, "away_shots": 38},
    {"period": 4, "clock": "4:59"},
])
def test_a_card_keeps_its_width_whatever_it_draws(plugin, change):
    before = _cards(plugin)["game:nhl:401"].image
    _game(plugin, "401").update(change)
    after = _cards(plugin)["game:nhl:401"].image
    assert after.tobytes() != before.tobytes()     # the card does draw it
    assert after.size == before.size


def test_odds_a_live_poll_left_out_do_not_redraw_the_card(plugin):
    game = _game(plugin, "401")
    game["odds"] = {"spread": -1.5, "over_under": 6.5}
    _cards(plugin)
    drawn = _renders(plugin)
    del game["odds"]
    _cards(plugin)
    assert _renders(plugin) == drawn


@pytest.mark.parametrize("state, period, clock, short_detail", [
    ("post", 3, "0:00", "Final"),             # is_final
    ("in", 3, "0:00", "P3 0:00"),             # still "in", but the clock has run out
])
def test_a_game_that_goes_final_keeps_its_card_and_shows_final(
        plugin, state, period, clock, short_detail):
    before = _cards(plugin)["game:nhl:401"]
    live_manager = plugin.nhl_live
    live_manager.test_mode = False
    live_manager._fetch_data = lambda: {"events": [
        _poll_event("401", state, period, clock, short_detail, away_score="4"),
        _poll_event("402", "in", 2, "8:10", "P2 8:10"),
    ]}
    live_manager.last_update = 0
    live_manager.update()
    assert [g["id"] for g in live_manager.live_games] == ["402"]
    after = _cards(plugin)
    assert "game:nhl:401" in after
    card = after["game:nhl:401"]
    assert ("is_final", True) in card.version[0]
    assert card.image.size == before.image.size
    assert card.image.tobytes() != before.image.tobytes()
    # Next time round it follows the games still live, ahead of the rest.
    assert list(after) == ["game:nhl:402", "game:nhl:401"]


@pytest.mark.parametrize("period, short_detail", [
    (3, "End of 3rd"),                        # regulation over: overtime next
    (4, "End of OT"),                         # overtime over: a shootout next
])
def test_a_level_game_at_0_00_is_not_held_as_final(plugin, period, short_detail):
    """Level at 0:00 is not over in hockey. Held, the card would read "Final
    3-3" and, the game gone from live_games, keep reading it after the
    shootout, ahead of the recent list's real result."""
    live_manager = plugin.nhl_live
    live_manager.test_mode = False
    live_manager._fetch_data = lambda: {"events": [
        _poll_event("401", "in", period, "0:00", short_detail,
                    away_score="3", home_score="3"),
        _poll_event("402", "in", 2, "8:10", "P2 8:10"),
    ]}
    live_manager.last_update = 0
    live_manager.update()
    assert [g["id"] for g in live_manager.live_games] == ["402"]   # dropped, as before
    assert live_manager.finished_games_snapshot() == []
    assert list(_cards(plugin)) == ["game:nhl:402"]


def test_the_harness_contract_holds(plugin):
    report = check_vegas_elements(plugin, plugin.dm)
    assert report.implemented and report.ok, report.errors
    assert report.live == 2
    assert not [w for w in report.warnings if "changed version" in w], report.warnings
