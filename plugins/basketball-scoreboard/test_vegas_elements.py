"""Live Vegas cards: one per game, redrawn only when that game changes.

With LEDMatrix 3.8.0 the Vegas ticker asks get_vegas_elements() for one card
per game and swaps a card in place while it scrolls when its game changes. A
card's width must never change (the ticker refuses a redraw of another
width), only the card whose game changed may be drawn again, and a game that
goes final must keep its card -- now showing FINAL -- rather than vanish from
the slate until the recent list's next refresh.

The games are the safety harness's fixture (test/fixtures/mock.json): its
in-progress NBA game, plus a copy of it between two other teams so one game
can change while the other does not. Each poll hands them to
NBALiveManager.update() through the scoreboard cache, so every card is drawn
from what _extract_game_details makes of an ESPN event.

Run: <core-venv>/bin/python -m pytest plugins/basketball-scoreboard/test_vegas_elements.py
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
    from src.common import sports_vegas  # LEDMatrix 3.8.0
except ImportError as exc:  # a core without live Vegas cards
    pytest.skip(f"core has no live Vegas cards ({exc})", allow_module_level=True)

W, H = 128, 32
#: The core checkout. The league separator icons are read relative to it.
CORE = Path(sports_vegas.__file__).resolve().parents[2]

FINAL = {"clock": 0.0, "displayClock": "0:00", "period": 4, "type": {
    "id": "3", "name": "STATUS_FINAL", "state": "post", "completed": True,
    "description": "Final", "detail": "Final", "shortDetail": "Final"}}
#: Still "in" on the feed, but over by _is_game_really_over(): Q4 at 0:00.
BUZZER = {"clock": 0.0, "displayClock": "0:00", "period": 4, "type": {
    "id": "2", "name": "STATUS_IN_PROGRESS", "state": "in", "completed": False,
    "description": "In Progress", "detail": "Q4 0:00", "shortDetail": "Q4 0:00"}}


def _other_game(event):
    """The fixture's live game, as another game between two other teams."""
    event = copy.deepcopy(event)
    event["id"] = event["competitions"][0]["id"] = "6004"
    home, away = event["competitions"][0]["competitors"]
    for side, team_id, abbr, score in ((home, "2", "BOS", "50"), (away, "18", "NY", "48")):
        side.update(id=team_id, score=score)
        side["team"].update(id=team_id, abbreviation=abbr)
    return event


def _poll(plugin):
    """One live poll, of the scoreboard plugin.events describe."""
    plugin.cache_manager.set(
        "nba_scoreboard_current", {"events": copy.deepcopy(list(plugin.events.values()))})
    plugin.nba_live.last_update = 0          # due now, whatever the interval
    plugin.nba_live.update()


def _make_plugin(width=W, height=H):
    spec = load_harness_spec(PLUGIN_DIR)
    config = build_full_config(PLUGIN_DIR, spec, {})
    dm = VisualTestDisplayManager(width=width, height=height)
    plugin = _instantiate("basketball-scoreboard", load_manifest(PLUGIN_DIR), PLUGIN_DIR,
                          config, spec["mock_data_contents"], dm)
    live = copy.deepcopy(spec["mock_data_contents"]["nba_scoreboard_current"]["events"][0])
    plugin.events = {"6002": live, "6004": _other_game(live)}
    for event in plugin.events.values():
        event["status"] = event["competitions"][0]["status"]    # one status to edit
    _poll(plugin)
    assert [g["id"] for g in plugin.nba_live.live_games] == ["6002", "6004"]
    plugin.dm = dm
    plugin.spec = spec
    return plugin


@pytest.fixture
def plugin(monkeypatch):
    monkeypatch.chdir(CORE)
    return _make_plugin()


def _cards(plugin):
    elements = render_vegas_elements(plugin, plugin.dm)
    return {e.key: e for e in elements if e.live}


def _renders(plugin):
    return plugin._scroll_manager.get_scroll_display("mixed")._vegas_cards.renders


def _live(plugin, game_id):
    """The live manager's own dict for a game, which the next slate reads."""
    return next(g for g in plugin.nba_live.live_games if g["id"] == game_id)


def test_one_live_card_per_game_keyed_by_its_id(plugin):
    elements = render_vegas_elements(plugin, plugin.dm)
    assert [e.key for e in elements] == ["sep:0:nba", "game:nba:6002", "game:nba:6004"]
    assert not elements[0].live
    assert {e.image.size for e in elements[1:]} == {(W, H)}


@pytest.mark.parametrize("size", [(128, 32), (64, 32), (192, 48)])
def test_each_card_is_the_scroll_paths_card_without_its_padding(monkeypatch, size):
    """The slate get_vegas_content() shows, card for card: live, recent and
    upcoming games, each drawn at the card width (not the panel's) and as the
    type the scroll path picks, differing only by the padding it bakes in."""
    monkeypatch.chdir(CORE)
    plugin = _make_plugin(*size)
    schedule = plugin.spec["mock_data_contents"]["nba_schedule_window_14_7"]["events"]
    details = {event["id"]: plugin.nba_recent._extract_game_details(copy.deepcopy(event))
               for event in schedule}
    plugin.nba_recent.games_list = [details["6001"]]          # final
    plugin.nba_upcoming.games_list = [details["6003"]]        # scheduled
    games, leagues = plugin._collect_games_for_scroll(mode_type=None)
    assert plugin._build_vegas_scroll_content(games, leagues)
    items = plugin._vegas_items()
    elements = render_vegas_elements(plugin, plugin.dm)
    assert [e.key for e in elements] == [
        "sep:0:nba", "game:nba:6002", "game:nba:6004", "game:nba:6001", "game:nba:6003"]
    assert len(items) == len(elements)
    assert elements[0].image.tobytes() == items[0].tobytes()
    for item, element in zip(items[1:], elements[1:]):
        card = element.image
        pad = (item.width - card.width) // 2
        assert pad > 0 and item.width == card.width + 2 * pad, element.key
        assert item.crop((pad, 0, pad + card.width, item.height)).tobytes() == card.tobytes(), \
            element.key


def test_a_clock_tick_redraws_only_that_games_card(plugin):
    before = _cards(plugin)
    drawn = _renders(plugin)
    plugin.events["6002"]["status"]["displayClock"] = "7:21"
    _poll(plugin)
    after = _cards(plugin)
    assert _renders(plugin) == drawn + 1
    assert after["game:nba:6004"].image is before["game:nba:6004"].image
    assert after["game:nba:6002"].image.tobytes() != before["game:nba:6002"].image.tobytes()


def test_a_poll_with_nothing_new_draws_nothing(plugin):
    before = _cards(plugin)
    drawn = _renders(plugin)
    _poll(plugin)
    after = _cards(plugin)
    assert _renders(plugin) == drawn
    assert all(after[k].image is before[k].image for k in before)


@pytest.mark.parametrize("change", [
    {"home_score": "118", "away_score": "121"},
    {"is_halftime": True, "period_text": "HALF"},
    {"period": 5, "period_text": "OT1", "clock": "4:59"},
    {"odds": {"spread": -6.5, "over_under": 228.5, "home_team_odds": {}, "away_team_odds": {}}},
    {"is_tournament": True, "tournament_round": "Elite 8", "home_seed": 1, "away_seed": 12},
])
def test_a_card_keeps_its_width_whatever_it_draws(plugin, change):
    before = _cards(plugin)["game:nba:6002"]
    _live(plugin, "6002").update(change)
    after = _cards(plugin)["game:nba:6002"]
    assert after.image.tobytes() != before.image.tobytes()      # it was drawn
    assert after.image.size == before.image.size


def test_odds_a_live_poll_left_out_do_not_redraw_the_card(plugin):
    _live(plugin, "6002")["odds"] = {"spread": -6.5, "over_under": 228.5}
    _cards(plugin)
    drawn = _renders(plugin)
    _poll(plugin)                            # the next poll fetched no odds for it
    assert "odds" not in _live(plugin, "6002")
    _cards(plugin)
    assert _renders(plugin) == drawn


@pytest.mark.parametrize("status", [FINAL, BUZZER], ids=["final", "q4-at-0:00"])
def test_a_game_that_goes_final_keeps_its_card_and_shows_final(plugin, status):
    before = _cards(plugin)["game:nba:6002"]
    plugin.events["6002"]["status"].update(copy.deepcopy(status))
    _poll(plugin)
    assert [g["id"] for g in plugin.nba_live.live_games] == ["6004"]
    after = _cards(plugin)
    assert "game:nba:6002" in after
    card = after["game:nba:6002"]
    assert card.image.size == before.image.size
    assert card.image.tobytes() != before.image.tobytes()
    # Next time round it follows the games still live, ahead of the rest.
    assert list(after) == ["game:nba:6004", "game:nba:6002"]


def test_a_game_over_at_the_buzzer_is_held_as_the_final_it_is(monkeypatch):
    """Still "in" on the feed at Q4 0:00, it is held as a final: its card is the
    one ESPN's own final gives, reading Final rather than Q4."""
    monkeypatch.chdir(CORE)
    held = []
    for status in (FINAL, BUZZER):
        plugin = _make_plugin()
        plugin.events["6002"]["status"].update(copy.deepcopy(status))
        _poll(plugin)
        held.append(_cards(plugin)["game:nba:6002"].image.tobytes())
    assert held[0] == held[1]


def test_a_tie_at_the_end_of_regulation_is_not_held_as_a_final(plugin):
    """Level at Q4 0:00 is overtime coming, not a result: the game stays live
    through the break (_is_game_really_over's tie guard), nothing is held,
    and its card is still there, live, once the next poll has it in overtime."""
    event = plugin.events["6002"]
    for side in event["competitions"][0]["competitors"]:
        side["score"] = "100"
    event["status"].update(copy.deepcopy(BUZZER))
    _poll(plugin)
    assert plugin.nba_live.finished_games_snapshot() == []
    assert "game:nba:6002" in _cards(plugin)
    event["status"].update(displayClock="5:00", period=5, type=dict(
        BUZZER["type"], detail="OT 5:00", shortDetail="OT 5:00"))
    _poll(plugin)
    assert list(_cards(plugin)) == ["game:nba:6002", "game:nba:6004"]


def test_a_tournament_slate_opens_on_the_march_madness_separator(plugin):
    game = dict(_live(plugin, "6002"), league="ncaam", is_tournament=True)
    elements = plugin._scroll_manager.get_vegas_elements_for("mixed", [game], ["ncaam"])
    assert [e.key for e in elements] == ["sep:0:ncaam", "game:ncaam:6002"]
    # The separator get_vegas_content() heads the same slate with.
    scroll = plugin._scroll_manager.get_scroll_display("check")
    assert scroll.prepare_scroll_content([game], "mixed", ["ncaam"])
    assert elements[0].image.tobytes() == scroll._vegas_content_items[0].tobytes()


def test_building_the_cards_never_polls(plugin, monkeypatch):
    def poll(*_args, **_kwargs):
        raise AssertionError("get_vegas_elements() polled")

    monkeypatch.setattr(plugin, "update", poll)
    for manager in (plugin.nba_live, plugin.nba_recent, plugin.nba_upcoming):
        monkeypatch.setattr(manager, "update", poll)
    monkeypatch.setattr("requests.Session.request", poll)
    assert len(_cards(plugin)) == 2


def test_the_harness_contract_holds(plugin):
    report = check_vegas_elements(plugin, plugin.dm)
    assert report.implemented and report.ok, report.errors
    assert report.live == 2
