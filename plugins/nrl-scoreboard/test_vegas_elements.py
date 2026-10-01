"""Live Vegas cards: one per game, redrawn only when that game changes.

With LEDMatrix 3.8.0 the Vegas ticker asks get_vegas_elements() for one card
per game and swaps a card in place while it scrolls when its game changes. A
card's width must never change (the ticker refuses a redraw of another
width), only the card whose game changed may be drawn again, and a game that
goes final must keep its card -- now showing Final -- rather than vanish from
the slate until the recent list's next refresh.

The harness has no test_mode, so the slate is its fixture
(test/fixtures/mock.json): the in-progress game, copied under a second id so
one can change while the other does not, is fed to the live manager's own
update() -- the real _extract_game_details and the real final-game branches --
and the fixture's final and scheduled games fill the recent and upcoming
lists. The poll is stubbed and live odds are not fetched. Instantiating the
plugin still looks the league's teams up on ESPN (and downloads a logo that is
not on disk yet), as the harness does; offline that fails quietly, and no
assertion depends on it.

Run: <core-venv>/bin/python -m pytest plugins/nrl-scoreboard/test_vegas_elements.py
(with the core checkout on PYTHONPATH).
"""
import copy
import json
import logging
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

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
LIVE, OTHER = "401700001", "401700004"
# ESPN's NRL slug is "3", and the plugin keys its games by it.
KEYS = ["game:3:401700001", "game:3:401700004", "game:3:401700002", "game:3:401700003"]


def _fixture_events():
    """The harness fixture's ESPN events, one per state: in, post, pre."""
    mock = json.loads((PLUGIN_DIR / "test" / "fixtures" / "mock.json").read_text(encoding="utf-8"))
    events = {}
    for payload in mock.values():
        for event in payload.get("events", []):
            events.setdefault(event["competitions"][0]["status"]["type"]["state"], event)
    return events


EVENTS = _fixture_events()


def _live(event_id, home_score, away_score, clock="52'"):
    """The fixture's in-progress game as a poll reports it, under ``event_id``."""
    event = copy.deepcopy(EVENTS["in"])
    competition = event["competitions"][0]
    event["id"] = competition["id"] = event_id
    competition["status"]["displayClock"] = clock
    for team in competition["competitors"]:
        team["score"] = home_score if team["homeAway"] == "home" else away_score
    return event


def _final(event, completed=True):
    """``event`` at full time, with the status the fixture's final game has."""
    event = copy.deepcopy(event)
    status = event["competitions"][0]["status"]
    status["displayClock"] = "80'"
    status["type"] = dict(EVENTS["post"]["competitions"][0]["status"]["type"],
                          completed=completed)
    return event


def _poll(plugin):
    """One live poll that returns plugin.feed, through the live manager's update()."""
    live = plugin._get_manager("live")
    live._fetch_data = lambda: {"events": copy.deepcopy(list(plugin.feed.values()))}
    live.last_update = 0
    live.update()


def _draw_logos(plugin):
    """A distinct logo at every path the slate's games point to.

    A card without both logos is only "BRI@PEN", no score or clock, and the
    core's assets/sports/nrl_logos/ is untracked -- empty on a fresh checkout,
    whatever a previous run downloaded otherwise. The managers were pointed
    at a temporary directory, so these are the only logos they see.
    """
    games = []
    for mode in ("live", "recent", "upcoming"):
        manager = plugin._get_manager(mode)
        games += list(getattr(manager, "live_games", None) or [])
        games += list(getattr(manager, "games_list", None) or [])
    for index, path in enumerate(sorted({str(g[side]) for g in games
                                         for side in ("home_logo_path", "away_logo_path")})):
        logo = Image.new("RGBA", (48, 48), (0, 0, 0, 0))
        colour = (60 + 40 * index % 196, 200 - 30 * index % 160, 90 + 50 * index % 166, 255)
        ImageDraw.Draw(logo).ellipse((2, 2, 45, 45), fill=colour, outline=(255, 255, 255, 255))
        logo.save(path)


def _make_plugin(logo_dir, width=W, height=H, config=None):
    spec = load_harness_spec(PLUGIN_DIR)
    config = build_full_config(PLUGIN_DIR, spec, config or {})
    dm = VisualTestDisplayManager(width=width, height=height)
    plugin = _instantiate("nrl-scoreboard", load_manifest(PLUGIN_DIR), PLUGIN_DIR,
                          config, {}, dm)
    for mode in ("live", "recent", "upcoming"):
        plugin._get_manager(mode).logo_dir = Path(logo_dir)
    plugin._get_manager("live")._fetch_odds = lambda game: None
    plugin.feed = {LIVE: _live(LIVE, "18", "12"), OTHER: _live(OTHER, "6", "0")}
    _poll(plugin)
    for mode, state in (("recent", "post"), ("upcoming", "pre")):
        manager = plugin._get_manager(mode)
        manager.games_list = [manager._extract_game_details(copy.deepcopy(EVENTS[state]))]
    _draw_logos(plugin)
    plugin.dm = dm
    return plugin


@pytest.fixture
def plugin(tmp_path):
    return _make_plugin(tmp_path)


def _cards(plugin):
    elements = render_vegas_elements(plugin, plugin.dm)
    return {e.key: e for e in elements if e.live}


def _renders(plugin):
    return plugin._scroll_manager.get_scroll_display("mixed")._vegas_cards.renders


def _live_game(plugin, game_id):
    return next(g for g in plugin._get_manager("live").live_games if g["id"] == game_id)


def test_one_live_card_per_game_keyed_by_its_id(plugin):
    cards = _cards(plugin)
    assert list(cards) == KEYS
    assert len({card.image.width for card in cards.values()}) == 1


def test_a_clock_tick_redraws_only_that_games_card(plugin):
    before = _cards(plugin)
    drawn = _renders(plugin)
    plugin.feed[LIVE] = _live(LIVE, "18", "12", clock="53'")
    _poll(plugin)
    after = _cards(plugin)
    assert _renders(plugin) == drawn + 1
    assert all(after[k].image is before[k].image for k in KEYS[1:])
    assert after[KEYS[0]].image.tobytes() != before[KEYS[0]].image.tobytes()


def test_a_poll_with_nothing_new_draws_nothing(plugin):
    before = _cards(plugin)
    drawn = _renders(plugin)
    _poll(plugin)
    after = _cards(plugin)
    assert _renders(plugin) == drawn
    assert all(after[k].image is before[k].image for k in before)


@pytest.mark.parametrize("change", [
    {"home_score": "40", "away_score": "38"},
    {"is_halftime": True, "period_text": "HALF"},
    {"period": 3, "period_text": "ET 84'", "clock": "84'"},        # golden point
    {"odds": {"spread": -6.5, "over_under": 44.5,
              "home_team_odds": {"spread_odds": -6.5},
              "away_team_odds": {"spread_odds": 6.5}}},
    {"home_id": "999", "home_logo_path": PLUGIN_DIR / "no-such-logo.png"},  # text fallback
])
def test_a_card_keeps_its_width_whatever_it_draws(plugin, change):
    width = _cards(plugin)[KEYS[0]].image.width
    drawn = _renders(plugin)
    _live_game(plugin, LIVE).update(change)
    assert _cards(plugin)[KEYS[0]].image.width == width
    assert _renders(plugin) == drawn + 1


def test_odds_a_live_poll_left_out_do_not_redraw_the_card(plugin):
    _live_game(plugin, LIVE)["odds"] = {"spread": -6.5, "over_under": 44.5}
    _cards(plugin)
    drawn = _renders(plugin)
    _poll(plugin)                             # live odds are fetched only now and then
    assert "odds" not in _live_game(plugin, LIVE)
    _cards(plugin)
    assert _renders(plugin) == drawn


# Both branches of the live update that drop a finished game: the feed marks
# it completed, or it says post with "Final" before it marks it completed.
@pytest.mark.parametrize("completed", [True, False], ids=["final", "over-not-completed"])
def test_a_game_that_goes_final_keeps_its_card_and_shows_final(plugin, completed):
    before = _cards(plugin)[KEYS[0]]
    plugin.feed[LIVE] = _final(plugin.feed[LIVE], completed=completed)
    _poll(plugin)
    assert [g["id"] for g in plugin._get_manager("live").live_games] == [OTHER]
    after = _cards(plugin)
    assert KEYS[0] in after
    card = after[KEYS[0]]
    assert card.image.width == before.image.width
    assert card.image.tobytes() != before.image.tobytes()
    # Next time round it follows the game still live, ahead of the rest.
    assert list(after) == [KEYS[1], KEYS[0]] + KEYS[2:]


def test_a_game_postponed_mid_play_leaves_no_final_card(plugin):
    # "post" but not played to a result: it leaves the live list, and no
    # branch that keeps a final may keep it -- a Final card would show the
    # score it had when play stopped as a result.
    event = copy.deepcopy(plugin.feed[LIVE])
    event["competitions"][0]["status"]["type"] = {
        "id": "6", "name": "STATUS_POSTPONED", "state": "post", "completed": False,
        "description": "Postponed", "detail": "Postponed", "shortDetail": "Postponed"}
    plugin.feed[LIVE] = event
    _poll(plugin)
    assert [g["id"] for g in plugin._get_manager("live").live_games] == [OTHER]
    assert plugin._get_manager("live").finished_games_snapshot() == []
    assert list(_cards(plugin)) == KEYS[1:]


# The scroll path's card for the same game, less the padding it bakes in, at
# sizes where the card is not the panel's width (128 on 64x32, 176 on 128x64),
# with rankings and odds drawn: the renderer must be prepare_scroll_content's.
@pytest.mark.parametrize("size", [(64, 32), (128, 64)], ids=["64x32", "128x64"])
def test_a_live_card_is_the_scroll_paths_card_without_its_padding(size, tmp_path):
    plugin = _make_plugin(tmp_path, *size, config={"show_ranking": True, "show_odds": True})
    plugin._get_manager("live")._team_rankings_cache = {"BRI": 1, "PEN": 2, "MEL": 3}
    _live_game(plugin, LIVE)["odds"] = {"spread": -6.5, "over_under": 44.5}
    cards = [e.image for e in render_vegas_elements(plugin, plugin.dm) if e.live]
    items = plugin.get_vegas_content()
    display = plugin._scroll_manager.get_scroll_display("mixed")
    pad = max(4, display._get_scroll_settings().get("gap_between_games", 48) // 2)
    assert cards[0].width != size[0]
    assert len(items) == len(cards) == len(KEYS)
    for card, item in zip(cards, items):
        unpadded = item.crop((pad, 0, item.width - pad, item.height))
        assert unpadded.size == card.size
        assert unpadded.tobytes() == card.tobytes()


def test_a_finished_game_is_not_shown_with_the_live_mode_off(plugin):
    plugin.config["display_modes"]["live"] = False
    plugin.feed[LIVE] = _final(plugin.feed[LIVE])
    _poll(plugin)
    assert list(_cards(plugin)) == KEYS[2:]


def test_the_harness_contract_holds(plugin):
    report = check_vegas_elements(plugin, plugin.dm)
    assert report.implemented and report.ok, report.errors
    assert report.live == len(KEYS)
