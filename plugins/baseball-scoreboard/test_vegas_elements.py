"""Live Vegas cards: one per game, redrawn only when that game changes.

With LEDMatrix 3.8.0 the Vegas ticker asks get_vegas_elements() for one card
per game and swaps a card in place while it scrolls when its game changes. A
card's width must never change (the ticker refuses a redraw of another
width), only the card whose game changed may be drawn again, and a game that
goes final must keep its card -- now showing FINAL -- rather than vanish from
the slate until the recent list's next refresh -- in every enabled league. A
suspended or postponed game leaves the live list too, but is not final, so it
is not held as one. A live card is the scroll strip's card for the same game,
pixel for pixel, without the padding the strip bakes around it.

update() leaves a slow manager finishing in the background after it returns,
which is after the ticker has redrawn: that manager tells the ticker itself.

The slate is the plugin's own simulated live game (mlb.test_mode, the safety
harness's fixture), copied into two games so one can change while the other
does not. A game leaves the live list through a real poll of the live
manager, fed the harness's in-progress BOS @ NYY event with its status
changed.

Run: <core-venv>/bin/python -m pytest plugins/baseball-scoreboard/test_vegas_elements.py
(with the core checkout on PYTHONPATH).
"""
import copy
import json
import logging
import sys
import threading
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))

logging.disable(logging.CRITICAL)

try:
    from src.plugin_system.testing import harness
    from src.plugin_system.testing.harness import _instantiate
    from src.plugin_system.testing.loading import (
        build_full_config, load_harness_spec, load_manifest,
    )
    from src.plugin_system.testing.vegas import check_vegas_elements, render_vegas_elements
    from src.plugin_system.testing.visual_display_manager import VisualTestDisplayManager
    from src.common import sports_vegas  # noqa: F401 - LEDMatrix 3.8.0
except ImportError as exc:  # a core without live Vegas cards
    pytest.skip(f"core has no live Vegas cards ({exc})", allow_module_level=True)

# The renderer reads logos and league icons from assets/ under the working
# directory, which on a rig is the core checkout.
CORE = Path(harness.__file__).resolve().parents[3]

W, H = 128, 32

_EVENTS = json.loads((PLUGIN_DIR / "test" / "fixtures" / "mock.json").read_text(
    encoding="utf-8"))["mlb_schedule_window_14_7"]["events"]
IN_PROGRESS = next(e for e in _EVENTS if e["id"] == "7002")      # BOS @ NYY, Top 7th


def _make_plugin(monkeypatch, width=W, height=H, config=None):
    monkeypatch.chdir(CORE)
    spec = load_harness_spec(PLUGIN_DIR)
    config = build_full_config(PLUGIN_DIR, spec, config or {})
    dm = VisualTestDisplayManager(width=width, height=height)
    plugin = _instantiate("baseball-scoreboard", load_manifest(PLUGIN_DIR), PLUGIN_DIR,
                          config, {}, dm)
    plugin.dm = dm
    return plugin


@pytest.fixture
def plugin(monkeypatch):
    plugin = _make_plugin(monkeypatch)
    live = plugin.mlb_live.live_games[0]      # test_mode: the simulated BOS @ NYY game
    plugin.slate = {
        "7002": dict(copy.deepcopy(live), id="7002", league="mlb", status={"state": "in"}),
        "7010": dict(copy.deepcopy(live), id="7010", league="mlb", status={"state": "in"},
                     inning=2, home_score="0", away_score="1"),
    }
    plugin._collect_games_for_scroll = lambda live_priority_active=False: (
        [dict(g) for g in plugin.slate.values()], ["mlb"])
    return plugin


def _cards(plugin):
    elements = render_vegas_elements(plugin, plugin.dm)
    return {e.key: e for e in elements if e.live}


def _renders(plugin):
    return plugin._scroll_manager.get_scroll_display("mixed")._vegas_cards.renders


def _poll(**status_type):
    """The harness's in-progress game as ESPN would send it, its status changed."""
    event = copy.deepcopy(IN_PROGRESS)
    for status in (event["status"], event["competitions"][0]["status"]):
        status["type"].update(status_type)
    return {"events": [event]}


def _poll_live_manager(plugin, poll):
    """One real poll of the MLB live manager, after which game 7002 is no longer live."""
    live = plugin.mlb_live
    live.live_games = [plugin.slate["7002"]]  # what the live manager was showing
    live.test_mode = False                    # poll the feed, not the simulation
    live.last_update = 0
    live._fetch_data = lambda: poll
    live.update()
    assert live.live_games == []              # this poll dropped it...
    del plugin.slate["7002"]                  # ...and the recent list has not caught up


def test_one_live_card_per_game_keyed_by_its_id(plugin):
    cards = _cards(plugin)
    assert list(cards) == ["game:mlb:7002", "game:mlb:7010"]
    assert len({card.image.width for card in cards.values()}) == 1


def test_a_pitch_redraws_only_that_games_card(plugin):
    before = _cards(plugin)
    drawn = _renders(plugin)
    plugin.slate["7002"].update(balls=3, strikes=2)
    after = _cards(plugin)
    assert _renders(plugin) == drawn + 1
    assert after["game:mlb:7010"].image is before["game:mlb:7010"].image
    assert after["game:mlb:7002"].image.tobytes() != before["game:mlb:7002"].image.tobytes()


def test_nothing_new_draws_nothing(plugin):
    before = _cards(plugin)
    drawn = _renders(plugin)
    after = _cards(plugin)
    assert _renders(plugin) == drawn
    assert all(after[k].image is before[k].image for k in before)


@pytest.mark.parametrize("change", [
    {"home_score": "10", "away_score": "12"},
    {"inning": 11, "inning_half": "bottom"},
    {"bases_occupied": [True, True, True], "outs": 2, "balls": 3, "strikes": 2},
    {"has_count_data": False},
    {"odds": {"spread": -1.5, "over_under": 8.5,
              "home_team_odds": {"spread_odds": -1.5},
              "away_team_odds": {"spread_odds": 1.5}}},
])
def test_a_card_keeps_its_width_whatever_it_draws(plugin, change):
    before = _cards(plugin)["game:mlb:7002"].image
    plugin.slate["7002"].update(change)
    after = _cards(plugin)["game:mlb:7002"].image
    assert after.width == before.width
    assert after.tobytes() != before.tobytes()


def test_the_outs_changing_sides_keeps_the_width(plugin):
    # The outs column is drawn left of the bases in the top half, right of
    # them in the bottom; the card must not grow to make room either way.
    game = plugin.slate["7002"]
    cards = {}
    for half in ("top", "bottom", "top"):
        game["inning_half"] = half
        cards.setdefault(half, []).append(_cards(plugin)["game:mlb:7002"].image)
    widths = {image.width for images in cards.values() for image in images}
    assert len(widths) == 1
    assert cards["top"][0].tobytes() != cards["bottom"][0].tobytes()
    assert cards["top"][1].tobytes() == cards["top"][0].tobytes()


def test_odds_a_live_poll_left_out_do_not_redraw_the_card(plugin):
    plugin.slate["7002"]["odds"] = {"spread": -1.5, "over_under": 8.5}
    _cards(plugin)
    drawn = _renders(plugin)
    del plugin.slate["7002"]["odds"]
    _cards(plugin)
    assert _renders(plugin) == drawn


def test_a_game_that_goes_final_keeps_its_card_and_shows_final(plugin):
    before = _cards(plugin)["game:mlb:7002"]
    _poll_live_manager(plugin, _poll(name="STATUS_FINAL", state="post", completed=True,
                                     detail="Final", shortDetail="Final"))
    after = _cards(plugin)
    assert "game:mlb:7002" in after
    card = after["game:mlb:7002"]
    assert card.image.width == before.image.width
    assert card.image.tobytes() != before.image.tobytes()
    # Next time round it follows the games still live, ahead of the rest.
    assert list(after) == ["game:mlb:7010", "game:mlb:7002"]


def test_a_game_the_live_loop_judges_over_keeps_its_card_too(plugin, monkeypatch):
    # The live loop's other exit: the feed still says in progress, but the
    # shared over-check says the game is done.
    before = _cards(plugin)["game:mlb:7002"]
    monkeypatch.setattr(plugin.mlb_live, "_is_game_really_over", lambda details: True)
    _poll_live_manager(plugin, _poll())
    card = _cards(plugin)["game:mlb:7002"]
    assert card.image.width == before.image.width
    assert card.image.tobytes() != before.image.tobytes()


def test_a_suspended_game_is_not_held_as_final(plugin):
    _cards(plugin)
    _poll_live_manager(plugin, _poll(name="STATUS_SUSPENDED", detail="Suspended",
                                     shortDetail="Suspended"))
    assert list(_cards(plugin)) == ["game:mlb:7010"]


def test_every_enabled_leagues_finished_game_keeps_its_card(monkeypatch):
    # Each league's live manager holds its own finished games; the slate has
    # to ask all of them, and none of a league that is switched off.
    plugin = _make_plugin(monkeypatch, config={
        "milb": {"enabled": True, "test_mode": True},
        "ncaa_baseball": {"enabled": True, "test_mode": True},
    })
    keys = ["game:mlb:test001", "game:milb:testMiLB001",
            "game:ncaa_baseball:testNCAABB001"]
    live_cards = _cards(plugin)
    assert list(live_cards) == keys
    for league in ("mlb", "milb", "ncaa_baseball"):
        manager = plugin._get_manager_for_league_mode(league, "live")
        game = manager.live_games[0]
        manager._keep_final_for_vegas(dict(game, is_live=False, is_final=True,
                                           status="status_final"))
        manager.live_games = []               # the poll that saw it final dropped it
    final_cards = _cards(plugin)
    assert list(final_cards) == keys
    for key in keys:
        assert final_cards[key].image.width == live_cards[key].image.width
        assert final_cards[key].image.tobytes() != live_cards[key].image.tobytes()
    plugin.milb_enabled = False
    assert list(_cards(plugin)) == [keys[0], keys[2]]


def test_a_live_card_is_the_scroll_strips_card_without_its_padding(monkeypatch):
    # At 256x64 the card (sized from the panel height) is narrower than the
    # panel, so a renderer built at the wrong width -- or drawing any
    # differently from the one the strip uses -- shows here. The harness's
    # final, in-progress and scheduled games, records and odds drawn.
    plugin = _make_plugin(monkeypatch, 256, 64, config={
        "mlb": {"display_options": {"show_records": True, "show_odds": True}}})
    games = []
    for event in _EVENTS:
        game = plugin.mlb_live._extract_game_details(copy.deepcopy(event))
        game.update(league="mlb", status={"state": game["status_state"]},
                    away_record="57-40", home_record="61-36")
        games.append(game)
    assert [g["status"]["state"] for g in games] == ["post", "in", "pre"]
    games[1]["odds"] = {"spread": -1.5, "over_under": 8.5,
                        "home_team_odds": {"spread_odds": -1.5},
                        "away_team_odds": {"spread_odds": 1.5}}
    plugin._collect_games_for_scroll = lambda live_priority_active=False: (
        [dict(g) for g in games], ["mlb"])
    elements = render_vegas_elements(plugin, plugin.dm)

    display = plugin._scroll_manager.get_scroll_display("mixed")
    assert display.prepare_scroll_content([dict(g) for g in games], "mixed", ["mlb"])
    items = display._vegas_content_items
    assert len(items) == len(elements) and sum(e.live for e in elements) == 3
    for element, item in zip(elements, items):
        card = element.image
        if not element.live:                  # the league separator, as it is
            assert item.tobytes() == card.tobytes()
            continue
        assert card.width < plugin.dm.width
        pad = (item.width - card.width) // 2
        assert pad > 0 and item.width == card.width + 2 * pad
        assert item.crop((pad, 0, pad + card.width, item.height)).tobytes() == card.tobytes()


def _quick_managers(plugin, *names):
    for name in names:
        setattr(getattr(plugin, name), "update", lambda: None)


def test_a_manager_finishing_after_update_returned_tells_the_ticker(plugin, monkeypatch):
    monkeypatch.setattr(sys.modules[type(plugin).__module__],
                        "_MANAGER_UPDATE_WAIT_SECONDS", 0.2)
    notices = []
    noticed = threading.Event()
    plugin.plugin_manager.notify_data_changed = lambda plugin_id: (
        notices.append(plugin_id), noticed.set())
    release = threading.Event()

    def slow_live_update():
        release.wait(5)
        plugin.slate["7002"]["home_score"] = "9"

    plugin.mlb_live.update = slow_live_update
    _quick_managers(plugin, "mlb_recent", "mlb_upcoming")
    before = _cards(plugin)["game:mlb:7002"].image

    plugin.update()                           # returns with MLB Live still running
    # The ticker has just redrawn on update() returning; nothing new yet.
    assert notices == []
    release.set()
    assert noticed.wait(5), "the straggler's data landed without telling the ticker"
    assert notices == ["baseball-scoreboard"]
    # By the time it is told, the straggler's data is there to draw.
    assert _cards(plugin)["game:mlb:7002"].image.tobytes() != before.tobytes()


def test_managers_finishing_in_time_need_no_extra_notice(plugin):
    notices = []
    plugin.plugin_manager.notify_data_changed = notices.append
    _quick_managers(plugin, "mlb_live", "mlb_recent", "mlb_upcoming")
    plugin.update()
    assert notices == []


def test_the_harness_contract_holds(plugin):
    report = check_vegas_elements(plugin, plugin.dm)
    assert report.implemented and report.ok, report.errors
    assert report.live == 2
