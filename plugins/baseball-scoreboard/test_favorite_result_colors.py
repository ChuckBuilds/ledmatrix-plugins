#!/usr/bin/env python3
"""
Tests for customization.favorite_result_colors -- tinting a finished game's
score green when a favorite team won and red when it lost.

Covers both render paths, because they resolve the color independently:
  * SportsCore._recent_score_color   (switch mode, sports.py)
  * GameRenderer._recent_score_color (scroll/Vegas cards, game_renderer.py)

And the cases that must NOT be tinted: the feature off (the default), no
favorites configured, a game between two non-favorites, and a game between
two favorites -- there is no losing side worth flagging red in that one.

Run: <core-venv>/bin/python plugins/baseball-scoreboard/test_favorite_result_colors.py
"""

import logging
import os
import sys

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

from game_renderer import GameRenderer  # noqa: E402
from sports import SportsCore  # noqa: E402

WHITE = (255, 255, 255)
AMBER = (255, 200, 0)   # the built-in tie color
GREEN = (0, 255, 0)
RED = (255, 0, 0)

ON = {"customization": {"favorite_result_colors": {"enabled": True}}}


def _game(home, away, home_score, away_score, favorites=None, league="mlb"):
    game = {
        "id": f"{away}@{home}",
        "league": league,
        "home_abbr": home,
        "away_abbr": away,
        "home_id": f"id-{home}",
        "away_id": f"id-{away}",
        "home_score": home_score,
        "away_score": away_score,
        "is_final": True,
    }
    if favorites is not None:
        game["favorite_teams"] = favorites
    return game


class _ConcreteCore(SportsCore):
    """Concrete SportsCore so it can be instantiated without the manager stack."""

    def _extract_game_details(self, game):  # abstract in SportsCore
        return None

    def _fetch_data(self):  # abstract in SportsCore
        return None


def _core(favorite_teams, config=None):
    """A SportsCore with just the attributes the color helpers touch."""
    core = object.__new__(_ConcreteCore)
    core.logger = logging.getLogger("test_favorite_result_colors")
    core.config = config if config is not None else dict(ON)
    core.favorite_teams = favorite_teams
    return core


def _renderer(config):
    renderer = object.__new__(GameRenderer)
    renderer.logger = logging.getLogger("test_favorite_result_colors")
    renderer.config = config
    return renderer


def _check(label, actual, expected):
    assert actual == expected, f"{label}: expected {expected}, got {actual}"
    print(f"  PASS {label}")


def test_switch_mode_colors():
    print("\n[switch mode] SportsCore._recent_score_color")
    core = _core(["ATL"])

    _check("favorite won at home",
           core._recent_score_color(_game("ATL", "NYM", "5", "2"), WHITE), GREEN)
    _check("favorite won away",
           core._recent_score_color(_game("NYM", "ATL", "2", "5"), WHITE), GREEN)
    _check("favorite lost at home",
           core._recent_score_color(_game("ATL", "NYM", "1", "7"), WHITE), RED)
    _check("favorite lost away",
           core._recent_score_color(_game("NYM", "ATL", "7", "1"), WHITE), RED)
    _check("tie",
           core._recent_score_color(_game("ATL", "NYM", "3", "3"), WHITE), AMBER)
    _check("neither team is a favorite",
           core._recent_score_color(_game("NYM", "PHI", "4", "1"), WHITE), WHITE)


def test_disabled_by_default():
    print("\n[default off]")
    core = _core(["ATL"], config={})
    _check("no customization block",
           core._recent_score_color(_game("ATL", "NYM", "5", "2"), WHITE), WHITE)

    core = _core(["ATL"], config={"customization": {"favorite_result_colors": {}}})
    _check("block present, enabled omitted",
           core._recent_score_color(_game("ATL", "NYM", "5", "2"), WHITE), WHITE)


def test_no_single_team_to_root_for():
    print("\n[no single favorite]")
    _check("no favorites configured",
           _core([])._recent_score_color(_game("ATL", "NYM", "5", "2"), WHITE), WHITE)
    _check("both teams are favorites",
           _core(["ATL", "NYM"])._recent_score_color(_game("ATL", "NYM", "5", "2"), WHITE),
           WHITE)


def test_unusable_scores():
    print("\n[unusable scores]")
    core = _core(["ATL"])
    _check("postponed, no score",
           core._recent_score_color(_game("ATL", "NYM", "", ""), WHITE), WHITE)
    _check("non-numeric score",
           core._recent_score_color(_game("ATL", "NYM", "-", "-"), WHITE), WHITE)


def test_custom_colors():
    print("\n[custom colors]")
    core = _core(["ATL"], config={"customization": {"favorite_result_colors": {
        "enabled": True,
        "win_color": [0, 128, 255],
        "loss_color": [128, 0, 128],
    }}})
    _check("configured win color",
           core._recent_score_color(_game("ATL", "NYM", "5", "2"), WHITE), (0, 128, 255))
    _check("configured loss color",
           core._recent_score_color(_game("ATL", "NYM", "2", "5"), WHITE), (128, 0, 128))

    core = _core(["ATL"], config={"customization": {"favorite_result_colors": {
        "enabled": True,
        "win_color": [999, -5, "12"],
    }}})
    _check("out-of-range channels are clamped",
           core._recent_score_color(_game("ATL", "NYM", "5", "2"), WHITE), (255, 0, 12))

    core = _core(["ATL"], config={"customization": {"favorite_result_colors": {
        "enabled": True,
        "win_color": "not a color",
    }}})
    _check("garbage color falls back to the built-in win color",
           core._recent_score_color(_game("ATL", "NYM", "5", "2"), WHITE), GREEN)


def test_scroll_card_colors():
    print("\n[scroll/Vegas] GameRenderer._recent_score_color")
    renderer = _renderer({"customization": {"favorite_result_colors": {"enabled": True}},
                          "mlb": {"favorite_teams": ["ATL"]}})

    # With the feature off the caller's own default is handed straight back,
    # whatever it is, so an existing install sees no change until it opts in.
    off = _renderer({"mlb": {"favorite_teams": ["ATL"]}})
    _check("feature off keeps the card's own default",
           off._recent_score_color(_game("ATL", "NYM", "5", "2"), WHITE), WHITE)

    _check("favorite won", renderer._recent_score_color(
        _game("ATL", "NYM", "5", "2"), WHITE), GREEN)
    _check("favorite lost", renderer._recent_score_color(
        _game("ATL", "NYM", "2", "5"), WHITE), RED)
    _check("other matchup untouched", renderer._recent_score_color(
        _game("NYM", "PHI", "4", "1"), WHITE), WHITE)

    # Only finished games are tinted; a live card keeps its normal color even
    # when the favorite happens to be ahead.
    _check("live game not tinted", renderer._score_color_for(
        _game("ATL", "NYM", "5", "2"), "live"), WHITE)
    _check("upcoming game not tinted", renderer._score_color_for(
        _game("ATL", "NYM", "0", "0"), "upcoming"), WHITE)
    _check("recent game tinted", renderer._score_color_for(
        _game("ATL", "NYM", "5", "2"), "recent"), GREEN)


def test_scroll_card_favorite_sources():
    print("\n[scroll/Vegas] where favorites come from")

    # Soccer-style config, where favorites live under a per-league section the
    # renderer cannot find by name -- the game's stamped list carries them.
    stamped = _renderer({"customization": {"favorite_result_colors": {"enabled": True}}})
    _check("favorites stamped on the game", stamped._recent_score_color(
        _game("ATL", "NYM", "5", "2", favorites=["ATL"]), WHITE), GREEN)

    # A league section the renderer can find, with nothing stamped (hand-built
    # game dicts, and config edits that beat the next data refresh).
    from_config = _renderer({"customization": {"favorite_result_colors": {"enabled": True}},
                             "mlb": {"favorite_teams": ["ATL"]}})
    _check("favorites read from config", from_config._recent_score_color(
        _game("ATL", "NYM", "5", "2"), WHITE), GREEN)

    # NRL keys favorites by ESPN id because its abbreviations collide.
    by_id = _renderer({"customization": {"favorite_result_colors": {"enabled": True}},
                       "nrl": {"favorite_teams": ["id-ATL"]}})
    _check("favorites matched by id", by_id._recent_score_color(
        _game("ATL", "NYM", "5", "2", league="nrl"), WHITE), GREEN)


def test_scroll_card_nested_payload():
    print("\n[scroll/Vegas] nested payload (hockey/lacrosse shape)")
    renderer = _renderer({"customization": {"favorite_result_colors": {"enabled": True}},
                          "nhl": {"favorite_teams": ["TB"]}})
    game = {
        "league": "nhl",
        "is_final": True,
        "home_team": {"abbrev": "TB", "score": "4"},
        "away_team": {"abbrev": "BOS", "score": "1"},
    }
    _check("nested favorite won", renderer._recent_score_color(game, WHITE), GREEN)

    game["home_team"]["score"] = "0"
    _check("nested favorite lost", renderer._recent_score_color(game, WHITE), RED)


def main():
    tests = [
        test_switch_mode_colors,
        test_disabled_by_default,
        test_no_single_team_to_root_for,
        test_unusable_scores,
        test_custom_colors,
        test_scroll_card_colors,
        test_scroll_card_favorite_sources,
        test_scroll_card_nested_payload,
    ]
    for test in tests:
        test()
    print(f"\nAll {len(tests)} test groups passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
