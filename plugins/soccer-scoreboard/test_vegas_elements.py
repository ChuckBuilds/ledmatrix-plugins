"""Live Vegas cards: one per game, redrawn only when that game changes.

With LEDMatrix 3.8.0 the Vegas ticker asks get_vegas_elements() for one card
per game and swaps a card in place while it scrolls when its game changes. A
card's width must never change (the ticker refuses a redraw of another
width), only the card whose game changed may be drawn again, and a game that
goes final must keep its card -- now showing Final -- rather than vanish from
the slate until the recent list's next refresh.

The games are the safety harness's own fixture (test/fixtures/mock.json): its
in-progress Premier League match, served from the mocked cache and polled
through the live manager's real update(), as two games so one can change
while the other does not. The away side is Chelsea rather than the fixture's
MNC: core ships no crest for MNC, and a card missing a logo is drawn as a
text placeholder without the score or the clock this test watches. The same
match is polled through other leagues' live managers (a custom league, one
whose live screen is off) to show every league on the slate keeps its
finished games.

Run: <core-venv>/bin/python -m pytest plugins/soccer-scoreboard/test_vegas_elements.py
(with the core checkout on PYTHONPATH).
"""
import copy
import logging
import socket
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
SCOREBOARD_KEY = "soccer_eng.1_scoreboard_current"
SPEC = load_harness_spec(PLUGIN_DIR)
LIVE_EVENT = SPEC["mock_data_contents"][SCOREBOARD_KEY]["events"][0]   # LIV v MNC, 67'
# ESPN's full-time status as the fixture's finished match carries it.
FINAL_STATUS = next(
    event["competitions"][0]["status"]
    for fixture in SPEC["mock_data_contents"].values()
    for event in fixture["events"]
    if event["competitions"][0]["status"]["type"]["state"] == "post")
# And its scheduled one, for an upcoming card.
SCHEDULED_STATUS = next(
    event["competitions"][0]["status"]
    for fixture in SPEC["mock_data_contents"].values()
    for event in fixture["events"]
    if event["competitions"][0]["status"]["type"]["state"] == "pre")
# Odds and records on the cards (the root settings the strip reads), so the
# width checks cover everything a card can draw; off for eng.1's managers,
# which would otherwise fetch odds during update(). A league's own copy of
# show_odds lives under display_options -- a bare leagues.eng.1.show_odds
# never reaches its managers.
CARD_CONFIG = {
    "show_odds": True, "show_records": True,
    "leagues": {"eng.1": {"display_options": {"show_odds": False}}},
}


def _event(game_id, minute=67, score=("1", "1"), status=None):
    """The fixture's live match as ESPN sends it, under another id and minute."""
    event = copy.deepcopy(LIVE_EVENT)
    competition = event["competitions"][0]
    event["id"] = competition["id"] = game_id
    for side, goals in zip(("home", "away"), score):
        team = next(c for c in competition["competitors"] if c["homeAway"] == side)
        team["score"] = goals
        if side == "away":
            team["id"] = team["team"]["id"] = "363"
            team["team"].update(abbreviation="CHE", displayName="Chelsea",
                                shortDisplayName="Chelsea")
    status = copy.deepcopy(status) if status else competition["status"]
    if status["type"]["state"] == "in":
        status["displayClock"] = status["type"]["detail"] = \
            status["type"]["shortDetail"] = f"{minute}'"
    event["status"] = competition["status"] = status
    return event


def _live_manager(plugin, league="eng.1"):
    return plugin._get_league_manager_for_mode(league, "live")


def _poll(plugin, *events, league="eng.1"):
    """One live poll of these events, through the league's live manager's own update()."""
    plugin.cache_manager.set(f"soccer_{league}_scoreboard_current", {"events": list(events)})
    manager = _live_manager(plugin, league)
    manager.last_update = 0
    manager.update()


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def connect(*args, **kwargs):
        raise AssertionError("network I/O in a Vegas card test")
    monkeypatch.setattr(socket.socket, "connect", connect)


def _make_plugin(width=W, height=H, config=CARD_CONFIG):
    """The plugin on a width x height panel, nothing polled yet."""
    dm = VisualTestDisplayManager(width=width, height=height)
    plugin = _instantiate("soccer-scoreboard", load_manifest(PLUGIN_DIR), PLUGIN_DIR,
                          build_full_config(PLUGIN_DIR, SPEC, copy.deepcopy(config)),
                          copy.deepcopy(SPEC["mock_data_contents"]), dm)
    plugin.dm = dm
    return plugin


@pytest.fixture
def plugin():
    plugin = _make_plugin()
    assert not plugin.eng1_live.show_odds       # so update() never fetches odds
    _poll(plugin, _event("5002"), _event("5004", score=("3", "0")))
    return plugin


def _cards(plugin):
    elements = render_vegas_elements(plugin, plugin.dm)
    return {e.key: e for e in elements if e.live}


def _renders(plugin):
    return plugin._scroll_manager.get_scroll_display("mixed")._vegas_cards.renders


def _live_game(plugin, game_id):
    return next(g for g in plugin.eng1_live.live_games if g["id"] == game_id)


def test_one_live_card_per_game_keyed_by_its_id(plugin):
    cards = _cards(plugin)
    assert list(cards) == ["game:eng.1:5002", "game:eng.1:5004"]
    assert {card.image.size for card in cards.values()} == {(W, H)}


def test_a_clock_tick_redraws_only_that_games_card(plugin):
    before = _cards(plugin)
    drawn = _renders(plugin)
    _poll(plugin, _event("5002", minute=68), _event("5004", score=("3", "0")))
    after = _cards(plugin)
    assert _renders(plugin) == drawn + 1
    assert after["game:eng.1:5004"].image is before["game:eng.1:5004"].image
    assert after["game:eng.1:5002"].image.tobytes() != before["game:eng.1:5002"].image.tobytes()


def test_nothing_new_draws_nothing(plugin):
    before = _cards(plugin)
    drawn = _renders(plugin)
    _poll(plugin, _event("5002"), _event("5004", score=("3", "0")))   # the same poll again
    after = _cards(plugin)
    assert _renders(plugin) == drawn
    assert all(after[k].image is before[k].image for k in before)


def test_reading_the_cards_never_polls(plugin):
    def polled(*args, **kwargs):
        raise AssertionError("get_vegas_elements() called update()")
    plugin.update = polled
    for entry in plugin._league_registry.values():
        for manager in entry["managers"].values():
            if manager is not None:
                manager.update = polled
    assert len(_cards(plugin)) == 2


@pytest.mark.parametrize("change", [
    {"home_score": "10", "away_score": "12"},
    {"odds": {"spread": -0.5, "over_under": 2.5,
              "home_team_odds": {"spread_odds": -0.5},
              "away_team_odds": {"spread_odds": 0.5}}},
    {"home_record": "18-4-3", "away_record": "12-8-5"},
    {"is_halftime": True, "period_text": "HALF"},
    {"period": 4, "period_text": "ET2 118'", "clock": "118'"},
    {"period": 5, "period_text": "PEN", "clock": ""},
])
def test_a_card_keeps_its_width_whatever_it_draws(plugin, change):
    before = _cards(plugin)["game:eng.1:5002"].image
    _live_game(plugin, "5002").update(change)
    after = _cards(plugin)["game:eng.1:5002"].image
    assert after.width == before.width
    assert after.tobytes() != before.tobytes()      # it did draw the change


def test_odds_a_live_poll_left_out_do_not_redraw_the_card(plugin):
    _live_game(plugin, "5002")["odds"] = {"spread": -0.5, "over_under": 2.5}
    _cards(plugin)
    drawn = _renders(plugin)
    _poll(plugin, _event("5002"), _event("5004", score=("3", "0")))   # no odds this time
    _cards(plugin)
    assert _renders(plugin) == drawn


@pytest.mark.parametrize("completed", [True, False], ids=["is-final", "really-over"])
def test_a_game_that_goes_final_keeps_its_card_and_shows_final(plugin, completed):
    # completed=False is ESPN's full time before the result is confirmed: the
    # live update drops it through _is_game_really_over rather than is_final.
    before = _cards(plugin)["game:eng.1:5002"]
    status = copy.deepcopy(FINAL_STATUS)
    status["type"].update(completed=completed,
                          name="STATUS_FINAL" if completed else "STATUS_FULL_TIME")
    _poll(plugin, _event("5002", status=status), _event("5004", score=("3", "0")))
    assert [g["id"] for g in plugin.eng1_live.live_games] == ["5004"]
    after = _cards(plugin)
    assert "game:eng.1:5002" in after
    card = after["game:eng.1:5002"]
    assert card.image.width == before.image.width
    assert card.image.tobytes() != before.image.tobytes()
    # Next time round it follows the games still live, ahead of the rest.
    assert list(after) == ["game:eng.1:5004", "game:eng.1:5002"]


def test_a_live_game_stopped_without_a_result_is_not_kept(plugin):
    # Abandoned or suspended mid-match: ESPN files it under "post" but it is
    # not a result, so its card must not turn into a Final one.
    for number, name in enumerate(("STATUS_ABANDONED", "STATUS_SUSPENDED")):
        game_id = f"50{number + 6}"
        _poll(plugin, _event(game_id), _event("5004", score=("3", "0")))
        assert f"game:eng.1:{game_id}" in _cards(plugin)
        status = copy.deepcopy(FINAL_STATUS)
        status["type"].update(name=name, completed=False)
        _poll(plugin, _event(game_id, status=status), _event("5004", score=("3", "0")))
        assert [g["id"] for g in plugin.eng1_live.live_games] == ["5004"]
        assert plugin.eng1_live.finished_games_snapshot() == []
    assert list(_cards(plugin)) == ["game:eng.1:5004"]


def test_every_league_on_the_slate_keeps_its_finished_games():
    # Soccer's leagues come from a registry: custom leagues, and leagues whose
    # live screen is off -- the Vegas slate still carries their live games
    # (_collect_games_for_scroll reads every live list of a league on it), so
    # their finished games must be kept too, not only a fixed set's.
    plugin = _make_plugin(config={
        "show_odds": False,                      # no odds fetches in any league
        "leagues": {"esp.1": {"enabled": True, "show_all_live": True,
                              "display_modes": {"live": False}}},
        "custom_leagues": [{"name": "Test League", "league_code": "eng.3",
                            "enabled": True, "priority": 5,
                            "filtering": {"show_all_live": True}}],
    })
    assert "esp.1" not in plugin._get_enabled_leagues_for_mode("live")
    leagues = {"eng.1": "6001", "esp.1": "6002", "eng.3": "6003"}
    for league, game_id in leagues.items():
        _poll(plugin, _event(game_id), league=league)
    keys = {f"game:{league}:{game_id}" for league, game_id in leagues.items()}
    assert set(_cards(plugin)) == keys
    for league, game_id in leagues.items():
        _poll(plugin, _event(game_id, status=FINAL_STATUS), league=league)
        assert _live_manager(plugin, league).live_games == []
    cards = _cards(plugin)
    # Nothing else is on the slate, so they follow league priority, as the
    # collector orders leagues: eng.1 (1), esp.1 (2), then the custom one (5).
    assert list(cards) == ["game:eng.1:6001", "game:esp.1:6002", "game:eng.3:6003"]
    games = {game_key: game for game_key, game in
             ((f"game:{g['league']}:{g['id']}", g) for g in plugin.vegas_slate()[0])}
    assert all(games[key]["is_final"] for key in keys)


@pytest.mark.parametrize("size", [(128, 32), (64, 32), (128, 64)],
                         ids=lambda size: "%dx%d" % size)
def test_a_card_is_the_strip_card_for_every_card_type_and_league(size):
    # The renderer is the strip's: same card width (which is not the panel's
    # on 64x32 or 128x64), same card type per game, and one logo cache for
    # every league, so a World Cup game's flags and a club game's crests come
    # out the same.
    width, height = size
    plugin = _make_plugin(width, height)
    _poll(plugin, _event("5002"))
    manager = plugin.eng1_live
    club = dict(_live_game(plugin, "5002"), status={"state": "in"})
    final = dict(manager._extract_game_details(_event("5005", status=FINAL_STATUS)),
                 status={"state": "post"})
    upcoming = dict(manager._extract_game_details(_event("5006", status=SCHEDULED_STATUS)),
                    status={"state": "pre"})
    flags = PLUGIN_DIR / "assets" / "flags"
    world_cup = dict(club, id="7001", league="fifa.world",
                     home_abbr="ENG", home_id="448", home_logo_path=flags / "ENG.png",
                     away_abbr="USA", away_id="660", away_logo_path=flags / "USA.png")
    slate = [club, final, upcoming, world_cup]
    plugin._collect_games_for_scroll = lambda mode_type=None, **kw: (
        [dict(game) for game in slate], ["eng.1", "fifa.world"])
    strip = plugin.get_vegas_content()
    cards = list(_cards(plugin).values())
    card_width = plugin._scroll_manager.get_scroll_display("mixed") \
        ._get_scroll_settings()["game_card_width"]
    assert len(strip) == len(cards) == len(slate)
    for item, card in zip(strip, cards):
        assert card.image.size == (card_width, height)
        pad = (item.width - card.image.width) // 2
        assert pad > 0
        crop = item.crop((pad, 0, pad + card.image.width, height))
        assert crop.tobytes() == card.image.tobytes(), card.key


def test_the_harness_contract_holds(plugin):
    report = check_vegas_elements(plugin, plugin.dm)
    assert report.implemented and report.ok, report.errors
    assert report.live == 2
