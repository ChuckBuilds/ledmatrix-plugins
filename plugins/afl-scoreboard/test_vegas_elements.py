"""Live Vegas cards: one per game, redrawn only when that game changes.

With LEDMatrix 3.8.0 the Vegas ticker asks get_vegas_elements() for one card
per game and swaps a card in place while it scrolls when its game changes. A
card's width must never change (the ticker refuses a redraw of another
width), only the card whose game changed may be drawn again, and a game that
goes final must keep its card -- now showing Final -- rather than vanish from
the slate until the recent list's next refresh.

The harness has no test_mode, so the feed is its fixture's live game
(test/fixtures/mock.json), copied into two games so one can change while the
other does not. Every poll goes through the live manager's own update() and
_extract_game_details(); only _fetch_data and _fetch_odds, the network, are
stubbed.

The team logos are drawn here, into a temporary directory the managers are
pointed at. The core's assets/sports/afl_logos/ is untracked and empty in a
fresh checkout, and a card without both logos is only "FRE@SYD" -- no score,
no clock, no odds -- so every "the change was drawn" check below would fail
there, and pass elsewhere only on placeholders another tool happened to leave.

Run: <core-venv>/bin/python -m pytest plugins/afl-scoreboard/test_vegas_elements.py
(with the core checkout on PYTHONPATH).
"""
import copy
import logging
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))

logging.disable(logging.CRITICAL)

try:
    from src.logo_downloader import LogoDownloader
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
SPEC = load_harness_spec(PLUGIN_DIR)


def _fixture_event(state):
    """The first event in the harness fixture whose status is in ``state``."""
    for payload in SPEC["mock_data_contents"].values():
        for event in payload.get("events", []):
            if event["competitions"][0]["status"]["type"]["state"] == state:
                return copy.deepcopy(event)
    raise LookupError(state)


def _set_status(event, status):
    event["status"] = copy.deepcopy(status)
    event["competitions"][0]["status"] = copy.deepcopy(status)


def _draw_logos(logo_dir):
    """A distinct logo for every team in the fixture, where the managers look."""
    teams = sorted({team["team"]["abbreviation"]
                    for payload in SPEC["mock_data_contents"].values()
                    for event in payload.get("events", [])
                    for team in event["competitions"][0]["competitors"]})
    for index, abbr in enumerate(teams):
        logo = Image.new("RGBA", (48, 48), (0, 0, 0, 0))
        colour = (60 + 40 * index % 196, 200 - 30 * index % 160, 90 + 50 * index % 166, 255)
        ImageDraw.Draw(logo).ellipse((2, 2, 45, 45), fill=colour, outline=(255, 255, 255, 255))
        logo.save(logo_dir / f"{LogoDownloader.normalize_abbreviation(abbr)}.png")


def _make_plugin(logo_dir, width=W, height=H):
    config = build_full_config(PLUGIN_DIR, SPEC, {})
    dm = VisualTestDisplayManager(width=width, height=height)
    plugin = _instantiate("afl-scoreboard", load_manifest(PLUGIN_DIR), PLUGIN_DIR,
                          config, {}, dm)
    _draw_logos(logo_dir)
    for manager in plugin._managers.values():
        manager.logo_dir = logo_dir             # read by _extract_game_details
    live = plugin._managers["live"]
    first = _fixture_event("in")                    # FRE v SYD, Q3 12:45
    second = copy.deepcopy(first)
    second["id"] = second["competitions"][0]["id"] = "live-demo-002"
    plugin.feed = [first, second]
    plugin.odds = {}
    live._fetch_data = lambda: {"events": copy.deepcopy(plugin.feed)}
    live._fetch_odds = lambda details: (
        details.update(odds=plugin.odds[details["id"]]) if details["id"] in plugin.odds else None)
    plugin.dm = dm
    _poll(plugin)
    return plugin


@pytest.fixture
def plugin(tmp_path):
    return _make_plugin(tmp_path)


def _poll(plugin):
    """One live update of the feed, due now."""
    live = plugin._managers["live"]
    live.last_update = 0
    live.update()


def _cards(plugin):
    elements = render_vegas_elements(plugin, plugin.dm)
    return {e.key: e for e in elements if e.live}


def _renders(plugin):
    return plugin._scroll_manager.get_scroll_display("mixed")._vegas_cards.renders


def test_one_live_card_per_game_keyed_by_its_id(plugin):
    cards = _cards(plugin)
    assert list(cards) == ["game:afl:live-demo-001", "game:afl:live-demo-002"]
    assert {card.image.size for card in cards.values()} == {(W, H)}


def _content_cards(plugin):
    """get_vegas_content()'s game cards, without the black padding it bakes around each."""
    settings = plugin._scroll_manager.get_scroll_display("mixed")._get_scroll_settings()
    pad = max(4, settings["gap_between_games"] // 2)
    width = settings["game_card_width"]
    return [image.crop((pad, 0, pad + width, image.height))
            for image in plugin.get_vegas_content() or []
            if image.width == width + 2 * pad]


# AFL sizes a card from the panel's height (two full-height logos and the
# score), so on most panels the card is not the panel's width: 128 on a 64x32,
# 192 on a 128x64. Only a renderer built exactly as prepare_scroll_content
# builds it draws the same card there.
@pytest.mark.parametrize("size", [(128, 32), (64, 32), (128, 64)])
def test_live_cards_are_the_cards_get_vegas_content_draws(tmp_path, size):
    plugin = _make_plugin(tmp_path, *size)
    plugin.odds["live-demo-001"] = {"spread": -12.5, "over_under": 165.5}
    _poll(plugin)
    for mode, state in (("recent", "post"), ("upcoming", "pre")):
        manager = plugin._managers[mode]
        manager.games_list = [manager._extract_game_details(_fixture_event(state))]
    content = _content_cards(plugin)
    cards = list(_cards(plugin).values())
    display = plugin._scroll_manager.get_scroll_display("mixed")
    kinds = [display._determine_game_type(game) for game in plugin._collect_vegas_games()]
    assert kinds == ["live", "live", "recent", "upcoming"]
    assert len(content) == len(cards) == 4
    for drawn, card in zip(content, cards):
        assert card.image.size == drawn.size
        assert card.image.tobytes() == drawn.tobytes(), card.key
    if size != (128, 32):
        assert cards[0].image.width != size[0]      # the case a panel-wide card gets wrong


def test_a_clock_tick_redraws_only_that_games_card(plugin):
    before = _cards(plugin)
    drawn = _renders(plugin)
    plugin.feed[0]["competitions"][0]["status"]["displayClock"] = "12:44"
    _poll(plugin)
    after = _cards(plugin)
    assert _renders(plugin) == drawn + 1
    assert after["game:afl:live-demo-002"].image is before["game:afl:live-demo-002"].image
    assert after["game:afl:live-demo-001"].image.tobytes() != \
        before["game:afl:live-demo-001"].image.tobytes()


def test_nothing_new_draws_nothing(plugin):
    before = _cards(plugin)
    drawn = _renders(plugin)
    _poll(plugin)                                   # new dicts, same data
    after = _cards(plugin)
    assert _renders(plugin) == drawn
    assert all(after[k].image is before[k].image for k in before)


@pytest.mark.parametrize("change", [
    {"home_score": "142", "away_score": "138"},
    # goals.behinds (total): the longest score an AFL card could be handed.
    {"home_score": "21.16 (142)", "away_score": "20.18 (138)"},
    {"odds": {"spread": -12.5, "over_under": 165.5,
              "home_team_odds": {}, "away_team_odds": {}}},
    {"is_period_break": True, "status_text": "End of 3rd Quarter"},
    {"is_halftime": True, "period_text": "HALF"},
])
def test_a_card_keeps_its_width_whatever_it_draws(plugin, change):
    before = _cards(plugin)["game:afl:live-demo-001"].image
    plugin._managers["live"].live_games[0].update(change)
    after = _cards(plugin)["game:afl:live-demo-001"].image
    assert after.size == before.size
    assert after.tobytes() != before.tobytes()      # the change was drawn


def test_odds_a_live_poll_left_out_do_not_redraw_the_card(plugin):
    plugin.odds["live-demo-001"] = {"spread": -12.5, "over_under": 165.5}
    _poll(plugin)
    assert plugin._managers["live"].live_games[0].get("odds")
    _cards(plugin)
    drawn = _renders(plugin)
    plugin.odds.clear()                             # this poll does not ask
    _poll(plugin)
    assert not plugin._managers["live"].live_games[0].get("odds")
    _cards(plugin)
    assert _renders(plugin) == drawn


# Both ways the live update drops a game that has ended: ESPN says final, or
# its period text does before the completed flag is set (_is_game_really_over).
@pytest.mark.parametrize("completed", [True, False])
def test_a_game_that_goes_final_keeps_its_card_and_shows_final(plugin, completed):
    before = _cards(plugin)["game:afl:live-demo-001"]
    final = _fixture_event("post")["competitions"][0]["status"]
    final["type"]["completed"] = completed
    _set_status(plugin.feed[0], final)
    _poll(plugin)
    assert [g["id"] for g in plugin._managers["live"].live_games] == ["live-demo-002"]
    after = _cards(plugin)
    assert "game:afl:live-demo-001" in after
    card = after["game:afl:live-demo-001"]
    assert card.image.size == before.image.size
    assert card.image.tobytes() != before.image.tobytes()
    # Next time round it follows the games still live, ahead of the rest.
    assert list(after) == ["game:afl:live-demo-002", "game:afl:live-demo-001"]


def test_the_cards_never_fetch_or_update(plugin):
    def offline(*_args, **_kwargs):
        raise AssertionError("network or update() on the Vegas render path")
    for manager in plugin._managers.values():
        manager.update = manager._fetch_data = offline
    plugin._managers["live"]._fetch_odds = offline
    assert len(_cards(plugin)) == 2


def test_the_harness_contract_holds(plugin):
    report = check_vegas_elements(plugin, plugin.dm)
    assert report.implemented and report.ok, report.errors
    assert report.live == 2
