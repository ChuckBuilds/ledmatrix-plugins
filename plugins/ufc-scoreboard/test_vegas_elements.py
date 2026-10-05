"""Live Vegas cards: one per fight, redrawn only when that fight changes.

With LEDMatrix 3.8.0 the Vegas ticker asks get_vegas_elements() for one card
per fight and swaps a card in place while it scrolls when its fight changes. A
card's width must never change (the ticker refuses a redraw of another width),
only the card whose fight changed may be drawn again, and a fight that ends
must keep its card -- now showing the result -- rather than vanish from the
slate until the recent list's next refresh.

The slate is the plugin's own simulated live fight (ufc.test_mode, the safety
harness's fixture), copied into two fights so one can change while the other
does not. The fight that ends is real ESPN data (test/fixtures/
espn_mma_round_states.json) polled through the live manager's own update().
Nothing here may reach the network: every request is refused and counted.

Run: <core-venv>/bin/python -m pytest plugins/ufc-scoreboard/test_vegas_elements.py
(with the core checkout on PYTHONPATH).
"""
import copy
import json
import logging
import sys
from pathlib import Path

import pytest
import requests
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
CASES = {c["name"]: c["event"] for c in json.loads(
    (PLUGIN_DIR / "test" / "fixtures" / "espn_mma_round_states.json")
    .read_text(encoding="utf-8"))["cases"]}


@pytest.fixture
def requests_made(monkeypatch):
    made = []

    def refuse(self, method, url, *args, **kwargs):
        made.append(url)
        raise requests.ConnectionError(f"the test reached the network: {url}")

    monkeypatch.setattr(requests.Session, "request", refuse)
    return made


@pytest.fixture
def plugin(tmp_path, requests_made):
    spec = load_harness_spec(PLUGIN_DIR)
    config = build_full_config(PLUGIN_DIR, spec, {})
    dm = VisualTestDisplayManager(width=W, height=H)
    plugin = _instantiate("ufc-scoreboard", load_manifest(PLUGIN_DIR), PLUGIN_DIR,
                          config, {}, dm)
    live = plugin.ufc_live.live_games[0]      # test_mode: the simulated R2 fight
    # Headshots are looked for in tmp_path, where there are none: nothing
    # a card does can write into the core checkout's assets.
    live = dict(copy.deepcopy(live), league="ufc", status={"state": "in"},
                fighter1_image_path=tmp_path / "12345.png",
                fighter2_image_path=tmp_path / "67890.png")
    plugin.slate = {
        "701": dict(copy.deepcopy(live), id="701"),
        "702": dict(copy.deepcopy(live), id="702", status_text="R1 4:10"),
    }
    plugin._collect_fights_for_scroll = lambda mode_type=None: (
        [dict(f) for f in plugin.slate.values()], ["ufc"])
    plugin.dm = dm
    plugin.headshots = tmp_path
    yield plugin
    assert requests_made == [], "the test reached the network"


def _cards(plugin):
    elements = render_vegas_elements(plugin, plugin.dm)
    return {e.key: e for e in elements if e.live}


def _renders(plugin):
    return plugin._scroll_manager._vegas_cards.renders


def _poll(manager, *events):
    """One real live update against an ESPN scoreboard holding ``events``."""
    manager._fetch_data = lambda: {"events": list(events)}
    manager.last_update = 0
    manager.update()


def test_one_live_card_per_fight_keyed_by_its_id(plugin):
    cards = _cards(plugin)
    assert list(cards) == ["game:ufc:701", "game:ufc:702"]
    assert {card.image.size for card in cards.values()} == {(128, H)}


def test_a_live_card_is_the_scroll_card_without_its_padding(plugin):
    # A card width that is not the panel's, and one fight of each card type:
    # the live path must size each card and pick its type as the scroll does.
    config = copy.deepcopy(plugin.config)
    config["ufc"].setdefault("scroll_settings", {})["game_card_width"] = 96
    plugin.on_config_change(config)
    live = plugin.slate["701"]
    plugin.slate["703"] = dict(live, id="703", is_live=False, is_final=True,
                               status={"state": "post"}, status_text="KO/TKO R1 2:13")
    plugin.slate["704"] = dict(live, id="704", is_live=False, is_upcoming=True,
                               status={"state": "pre"}, game_date="10/4", game_time="10:00PM")
    scroll_manager = plugin._scroll_manager
    for fighter_id in ("12345", "67890"):     # shared by both paths: no disk, no network
        scroll_manager._headshot_cache[fighter_id] = Image.new("RGBA", (30, 30), (200, 90, 40, 255))
    scroll_manager._separator_icons["ufc"] = Image.new("RGBA", (18, 28), (255, 0, 0, 255))
    elements = render_vegas_elements(plugin, plugin.dm)
    scrolled = plugin.get_vegas_content()
    assert [(e.key, e.live) for e in elements] == [
        ("sep:0:ufc", False), ("game:ufc:701", True), ("game:ufc:702", True),
        ("game:ufc:703", True), ("game:ufc:704", True)]
    assert elements[0].image.tobytes() == scrolled[0].tobytes()
    assert len(scrolled) == len(elements)
    for element, padded in zip(elements[1:], scrolled[1:]):
        assert element.image.size == (96, H)
        unpadded = padded.crop((12, 0, padded.width - 12, padded.height))
        assert element.image.tobytes() == unpadded.tobytes(), element.key


def test_a_fight_in_two_lists_gets_one_card(plugin):
    # Around the end of a fight the live list and the recent list (or the
    # held result) can both have it: two cards with one key would be refused.
    live_card = _cards(plugin)["game:ufc:701"]
    plugin.slate["701-recent"] = dict(plugin.slate["701"], is_live=False, is_final=True,
                                      status={"state": "post"}, status_text="Final")
    keys = [e.key for e in render_vegas_elements(plugin, plugin.dm) if e.live]
    assert keys == ["game:ufc:701", "game:ufc:702"]
    assert _cards(plugin)["game:ufc:701"].image is live_card.image     # the live copy


def test_a_fight_that_leaves_the_slate_is_forgotten(plugin):
    _cards(plugin)
    del plugin.slate["702"]
    assert list(_cards(plugin)) == ["game:ufc:701"]
    assert len(plugin._scroll_manager._vegas_cards) == 1


def test_a_round_clock_tick_redraws_only_that_fights_card(plugin):
    before = _cards(plugin)
    drawn = _renders(plugin)
    plugin.slate["701"].update(status_text="R2 3:44", clock="3:44")
    after = _cards(plugin)
    assert _renders(plugin) == drawn + 1
    assert after["game:ufc:702"].image is before["game:ufc:702"].image
    assert after["game:ufc:701"].image.tobytes() != before["game:ufc:701"].image.tobytes()


def test_nothing_new_draws_nothing(plugin):
    before = _cards(plugin)
    drawn = _renders(plugin)
    after = _cards(plugin)
    assert _renders(plugin) == drawn
    assert all(after[k].image is before[k].image for k in before)


@pytest.mark.parametrize("change", [
    {"status_text": "End R2", "is_period_break": True},
    {"odds": {"home_team_odds": {"money_line": -250}, "away_team_odds": {"money_line": 210}}},
    {"fighter1_record": "", "fighter2_record": "", "fight_class": ""},
    {"fighter1_name_short": "K. Holland-Oliveira", "fighter2_name_short": "A. Volkanovski"},
    {"is_live": False, "is_final": True, "status": {"state": "post"}, "status_text": "Final"},
    {"is_live": False, "is_upcoming": True, "status": {"state": "pre"},
     "game_date": "10/4", "game_time": "10:00PM"},
])
def test_a_card_keeps_its_width_whatever_it_draws(plugin, change):
    width = _cards(plugin)["game:ufc:701"].image.width
    plugin.slate["701"].update(change)
    assert _cards(plugin)["game:ufc:701"].image.width == width


def test_odds_a_live_poll_left_out_do_not_redraw_the_card(plugin):
    plugin.slate["701"]["odds"] = {"home_team_odds": {"money_line": -250},
                                   "away_team_odds": {"money_line": 210}}
    _cards(plugin)
    drawn = _renders(plugin)
    del plugin.slate["701"]["odds"]
    _cards(plugin)
    assert _renders(plugin) == drawn


def test_cards_need_no_network_and_no_update(plugin, requests_made):
    updates = []
    plugin.update = lambda: updates.append("plugin")
    plugin.ufc_live.update = lambda: updates.append("live")
    cards = _cards(plugin)
    assert list(cards) == ["game:ufc:701", "game:ufc:702"]
    assert requests_made == [] and updates == []
    assert list(plugin.headshots.iterdir()) == []     # no headshot fetched or faked


def test_a_headshot_that_lands_redraws_its_card(plugin):
    before = _cards(plugin)["game:ufc:701"]
    drawn = _renders(plugin)
    # What update() does for a fighter it had no headshot for.
    Image.new("RGBA", (40, 40), (90, 160, 220, 255)).save(plugin.headshots / "12345.png")
    after = _cards(plugin)["game:ufc:701"]
    assert _renders(plugin) == drawn + 2     # both fights show fighter 12345
    assert after.image.tobytes() != before.image.tobytes()


def test_a_settings_change_redraws_every_card(plugin):
    before = _cards(plugin)
    config = copy.deepcopy(plugin.config)
    config["ufc"]["display_options"]["show_fighter_names"] = False
    plugin.on_config_change(config)
    after = _cards(plugin)
    assert _renders(plugin) == 2              # a new scroll manager, a new cache
    assert all(after[k].image.tobytes() != before[k].image.tobytes() for k in before)


def _clock_run_out():
    """The five-rounder still "in progress" at R5 0:00 (derived, not recorded)."""
    event = copy.deepcopy(CASES["break_after_round_4_of_5"])
    status = copy.deepcopy(CASES["in_round_3_of_3"]["competitions"][0]["status"])
    status.update(period=5, clock=0.0, displayClock="0:00")
    status["type"].update(detail="R5, 0:00", shortDetail="R5, 0:00")
    event["competitions"][0]["status"] = status
    return event


@pytest.mark.parametrize("ended", ["final_five_round_decision"])
def test_a_fight_that_ends_keeps_its_card_and_shows_the_result(
        plugin, tmp_path, requests_made, ended):
    del plugin._collect_fights_for_scroll     # the plugin's own collector
    live = plugin.ufc_live
    live.update_interval = 0
    live.logo_dir = tmp_path                  # headshot paths, as in the fixture
    live._fetch_missing_headshots = lambda *a, **k: None
    live._fetch_odds = lambda *a, **k: None
    ending, ongoing = "game:ufc:401903509", "game:ufc:401905378"
    final = CASES[ended]

    _poll(live, CASES["break_after_round_4_of_5"], CASES["in_round_3_of_3"])
    before = _cards(plugin)
    assert list(before) == [ending, ongoing]

    _poll(live, final, CASES["in_round_3_of_3"])
    assert [f["id"] for f in live.live_games] == ["401905378"]
    after = _cards(plugin)
    assert ending in after
    assert after[ending].image.width == before[ending].image.width
    assert after[ending].image.tobytes() != before[ending].image.tobytes()
    assert after[ongoing].image is before[ongoing].image
    # Next time round it follows the fights still live, ahead of the rest.
    assert list(after) == [ongoing, ending]
    assert requests_made == []


def test_a_fight_at_0_00_stays_live_until_espn_calls_it_final(plugin, tmp_path):
    """ufc declares FINAL_PERIOD = None: no clock ends a bout, only ESPN's
    final status does, so the horn at R5 0:00 does not drop it."""
    del plugin._collect_fights_for_scroll     # the plugin's own collector
    live = plugin.ufc_live
    live.update_interval = 0
    live.logo_dir = tmp_path
    live._fetch_missing_headshots = lambda *a, **k: None
    live._fetch_odds = lambda *a, **k: None
    _poll(live, _clock_run_out(), CASES["in_round_3_of_3"])
    assert [f["id"] for f in live.live_games] == ["401903509", "401905378"]
    assert live.finished_games_snapshot() == []


def test_the_harness_contract_holds(plugin):
    report = check_vegas_elements(plugin, plugin.dm)
    assert report.implemented and report.ok, report.errors
    assert report.live == 2
