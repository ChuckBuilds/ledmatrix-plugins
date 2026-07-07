#!/usr/bin/env python3
"""
Regression tests for the traditional (outfield ballpark) scoreboard screen:
linescore/hits/errors extraction, and the inning-window sizing logic that
decides how many innings fit on a given display width.

Run: <core-venv>/bin/python plugins/baseball-scoreboard/test_traditional_scoreboard.py
"""

import os
import sys

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

from baseball import (  # noqa: E402
    BaseballLive,
    _extract_linescore,
    _extract_team_stat,
)


def test_extract_linescore_orders_by_period():
    team = {
        "linescores": [
            {"value": 1.0, "displayValue": "1", "period": 2},
            {"value": 0.0, "displayValue": "0", "period": 1},
        ]
    }
    assert _extract_linescore(team) == ["0", "1"], _extract_linescore(team)
    print("test_extract_linescore_orders_by_period: PASS")


def test_extract_linescore_missing_team():
    assert _extract_linescore(None) == []
    assert _extract_linescore({}) == []
    print("test_extract_linescore_missing_team: PASS")


def test_extract_team_stat_finds_named_stat():
    team = {"statistics": [{"name": "hits", "displayValue": "8"}, {"name": "errors", "displayValue": "1"}]}
    assert _extract_team_stat(team, "hits") == "8"
    assert _extract_team_stat(team, "errors") == "1"
    print("test_extract_team_stat_finds_named_stat: PASS")


def test_extract_team_stat_missing_defaults_to_zero():
    assert _extract_team_stat(None, "hits") == "0"
    assert _extract_team_stat({}, "hits") == "0"
    assert _extract_team_stat({"statistics": []}, "hits") == "0"
    print("test_extract_team_stat_missing_defaults_to_zero: PASS")


def _game(inning=1, away_ls=None, home_ls=None):
    return {"inning": inning, "away_linescore": away_ls or [], "home_linescore": home_ls or []}


def test_inning_window_fits_full_nine():
    # Early game, wide display: show all 9 (some blank), starting at 1.
    start, num = BaseballLive._traditional_scoreboard_inning_window(
        _game(inning=3, away_ls=["1", "0"], home_ls=["0"]), max_cols=9
    )
    assert (start, num) == (1, 9), (start, num)
    print("test_inning_window_fits_full_nine: PASS")


def test_inning_window_extra_innings_fit():
    # 11th inning in progress, display wide enough for all 11: start at 1.
    start, num = BaseballLive._traditional_scoreboard_inning_window(
        _game(inning=11, away_ls=["0"] * 10, home_ls=["0"] * 10), max_cols=12
    )
    assert (start, num) == (1, 11), (start, num)
    print("test_inning_window_extra_innings_fit: PASS")


def test_inning_window_narrow_display_early_game_shows_fixed_view():
    # Early game (inning 2) on a display that can only fit 5 columns --
    # should NOT scroll yet, just show columns 1..5.
    start, num = BaseballLive._traditional_scoreboard_inning_window(
        _game(inning=2, away_ls=["1"], home_ls=["0"]), max_cols=5
    )
    assert (start, num) == (1, 5), (start, num)
    print("test_inning_window_narrow_display_early_game_shows_fixed_view: PASS")


def test_inning_window_narrow_display_scrolls_once_progressed_past_fit():
    # Inning 8 on a display that only fits 5 columns -- must scroll so the
    # current inning (8) is visible: window ends at 8, width 5 -> starts at 4.
    start, num = BaseballLive._traditional_scoreboard_inning_window(
        _game(inning=8, away_ls=["1"] * 7, home_ls=["0"] * 7), max_cols=5
    )
    assert (start, num) == (4, 5), (start, num)
    assert start + num - 1 == 8, "window must end exactly at the current inning"
    print("test_inning_window_narrow_display_scrolls_once_progressed_past_fit: PASS")


def test_inning_window_minimum_one_column():
    start, num = BaseballLive._traditional_scoreboard_inning_window(_game(inning=5), max_cols=0)
    assert num == 1, num
    print("test_inning_window_minimum_one_column: PASS")


class _ConcreteBaseballLive(BaseballLive):
    """Minimal concrete BaseballLive so we can instantiate without the full
    manager stack (mirrors test_pitcher_batter_last_play.py's version)."""

    def _extract_game_details(self, game_event):  # abstract in SportsCore
        return None

    def _fetch_data(self):  # abstract in SportsCore
        return None


class _DisplayManager:
    def __init__(self, width, height):
        from PIL import Image
        self.image = Image.new("RGB", (width, height))
        self._updated = False

    def update_display(self):
        self._updated = True


def _make_live(width, height):
    live = object.__new__(_ConcreteBaseballLive)
    live.display_width = width
    live.display_height = height
    live.display_manager = _DisplayManager(width, height)
    live.config = {}
    live.show_traditional_scoreboard = True
    live._trad_scoreboard_last_shown = 0.0
    live._trad_scoreboard_showing_until = 0.0
    import logging
    from PIL import ImageFont
    live.logger = logging.getLogger("test_traditional_scoreboard")
    _default_font = ImageFont.load_default()
    live._load_custom_font_from_element_config = lambda cfg, default_size=6: _default_font
    return live


def test_draws_without_crashing_at_small_size():
    live = _make_live(64, 32)
    game = {
        "away_abbr": "BOS", "home_abbr": "NYY",
        "away_score": "3", "home_score": "4",
        "away_hits": "5", "home_hits": "7",
        "away_errors": "1", "home_errors": "0",
        "away_linescore": ["0", "1", "0", "0", "2", "0"],
        "home_linescore": ["1", "0", "1", "0", "0", "2"],
        "inning": 7, "inning_half": "top",
        "balls": 2, "strikes": 1, "outs": 1,
        "is_live": True, "is_final": False,
        "has_count_data": True,
    }
    live._draw_traditional_scoreboard_screen(game)
    assert live.display_manager._updated, "expected the screen to render and push a frame"
    print("test_draws_without_crashing_at_small_size: PASS")


def test_draws_without_crashing_when_final_and_no_count_data():
    live = _make_live(128, 64)
    game = {
        "away_abbr": "MISS", "home_abbr": "LSU",
        "away_score": "3", "home_score": "5",
        "away_hits": "6", "home_hits": "9",
        "away_errors": "0", "home_errors": "1",
        "away_linescore": ["1", "0", "0", "1", "1", "0", "0"],
        "home_linescore": ["0", "2", "0", "1", "0", "2"],
        "inning": 9, "inning_half": "bottom",
        "balls": 0, "strikes": 0, "outs": 0,
        "is_live": False, "is_final": True,
        "has_count_data": False,
    }
    live._draw_traditional_scoreboard_screen(game)
    assert live.display_manager._updated
    print("test_draws_without_crashing_when_final_and_no_count_data: PASS")


if __name__ == "__main__":
    print("traditional scoreboard regression tests")
    print("=" * 55)
    failures = []
    for t in (
        test_extract_linescore_orders_by_period,
        test_extract_linescore_missing_team,
        test_extract_team_stat_finds_named_stat,
        test_extract_team_stat_missing_defaults_to_zero,
        test_inning_window_fits_full_nine,
        test_inning_window_extra_innings_fit,
        test_inning_window_narrow_display_early_game_shows_fixed_view,
        test_inning_window_narrow_display_scrolls_once_progressed_past_fit,
        test_inning_window_minimum_one_column,
        test_draws_without_crashing_at_small_size,
        test_draws_without_crashing_when_final_and_no_count_data,
    ):
        try:
            t()
        except AssertionError as e:
            failures.append(t.__name__)
            print(f"FAIL {t.__name__}: {e}")
    print("=" * 55)
    if failures:
        print(f"{len(failures)} test(s) failed: {failures}")
        sys.exit(1)
    print("All tests passed.")
