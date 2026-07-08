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
    _parse_team_color,
)


def test_font_fallback_ladder_steps_down_when_default_does_not_fit():
    # Regression: 9x15.bdf (the default traditional-scoreboard font) is a
    # fixed-size bitmap -- it can't shrink to fit a small display the way a
    # scalable .ttf can. Simulate that with a fake loader whose measured
    # row_h depends on which font name was requested, and confirm the
    # ladder steps down to the first same-family sibling that actually fits
    # rather than keeping a font that doesn't leave room for the needed rows.
    live = _make_live(64, 32)
    row_h_by_font = {"9x15.bdf": 17, "8x13.bdf": 15, "7x13.bdf": 15, "6x13.bdf": 15, "6x12.bdf": 14}

    class _FakeFont:
        def __init__(self, row_h):
            self._row_h = row_h

        def getbbox(self, text):
            return (0, 0, 6, self._row_h - 2)

    def fake_loader(cfg, default_size=6):
        return _FakeFont(row_h_by_font.get(cfg.get("font"), 14))

    live._load_custom_font_from_element_config = fake_loader
    font_cfg = {"font": "9x15.bdf"}
    # 6 needed rows in 85px available: 9x15/8x13/7x13/6x13 (row_h 15-17) all
    # overflow (6*15=90 > 85), but 6x12 (row_h 14, 6*14=84 <= 85) fits --
    # the ladder should stop there rather than walking further or picking
    # one of the earlier, too-tall candidates.
    font, char_w, row_h = live._load_traditional_scoreboard_font(font_cfg, needed_rows=6, available_height=85)
    assert row_h == row_h_by_font["6x12.bdf"], (
        f"expected the ladder to stop at the first fitting rung (6x12, row_h=14), got row_h={row_h}"
    )
    print("test_font_fallback_ladder_steps_down_when_default_does_not_fit: PASS")


def test_font_fallback_ladder_keeps_default_when_it_already_fits():
    live = _make_live(256, 128)
    row_h_by_font = {"9x15.bdf": 17}

    class _FakeFont:
        def __init__(self, row_h):
            self._row_h = row_h

        def getbbox(self, text):
            return (0, 0, 6, self._row_h - 2)

    def fake_loader(cfg, default_size=6):
        return _FakeFont(row_h_by_font[cfg.get("font")])

    live._load_custom_font_from_element_config = fake_loader
    font_cfg = {"font": "9x15.bdf"}
    font, char_w, row_h = live._load_traditional_scoreboard_font(font_cfg, needed_rows=6, available_height=126)
    assert row_h == 17, f"expected the default font to be kept since it already fits, got row_h={row_h}"
    print("test_font_fallback_ladder_keeps_default_when_it_already_fits: PASS")


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


def test_parse_team_color_valid_hex():
    assert _parse_team_color("be0a14") == (233, 12, 24)
    assert _parse_team_color("#13294b") == (38, 82, 150)
    assert _parse_team_color("ffc72c") == (255, 199, 44)
    print("test_parse_team_color_valid_hex: PASS")


def test_parse_team_color_missing_or_malformed():
    assert _parse_team_color(None) is None
    assert _parse_team_color("") is None
    assert _parse_team_color("bad") is None
    assert _parse_team_color("zzzzzz") is None
    print("test_parse_team_color_missing_or_malformed: PASS")


def test_parse_team_color_clamps_near_black_and_near_white():
    # Near-black colors get brightened into the legible band; near-white
    # colors get darkened. Pure black is left alone (nothing to scale).
    assert _parse_team_color("000000") == (0, 0, 0)
    r, g, b = _parse_team_color("ffffff")
    assert (r + g + b) / 3 <= 235, (r, g, b)
    dark_r, dark_g, dark_b = _parse_team_color("101010")
    assert (dark_r + dark_g + dark_b) / 3 >= 90, (dark_r, dark_g, dark_b)
    print("test_parse_team_color_clamps_near_black_and_near_white: PASS")


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
    live.favorite_teams = []
    import logging
    from PIL import ImageFont
    live.logger = logging.getLogger("test_traditional_scoreboard")
    _default_font = ImageFont.load_default()
    live._load_custom_font_from_element_config = lambda cfg, default_size=6: _default_font
    return live


def test_test_mode_update_resets_instead_of_climbing_forever():
    # Regression: _test_mode_update() used to increment self.current_game
    # ["inning"] with no cap, so a long-running service would eventually
    # show absurd extra-inning counts. It should now reset to a fresh game
    # once it goes a bit past a normal 9 innings.
    live = _make_live(128, 64)
    live.show_pitcher_batter = False
    live.show_last_play = False
    live._play_by_play_cache = {}
    live.current_game = {
        "id": "test", "is_live": True, "inning": 1, "inning_half": "top",
        "balls": 0, "strikes": 0, "outs": 0, "bases_occupied": [False, False, False],
        "home_score": "0", "away_score": "0",
        "home_linescore": [], "away_linescore": [],
        "home_hits": "0", "away_hits": "0", "home_errors": "0", "away_errors": "0",
    }

    max_inning_seen = 1
    for _ in range(200):
        live._test_mode_update()
        max_inning_seen = max(max_inning_seen, live.current_game["inning"])

    assert max_inning_seen <= BaseballLive._TEST_MODE_MAX_INNING, (
        f"inning climbed to {max_inning_seen}, expected a reset at "
        f"{BaseballLive._TEST_MODE_MAX_INNING}"
    )
    print(f"test_test_mode_update_resets_instead_of_climbing_forever: PASS (max inning seen: {max_inning_seen})")


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


def _image_contains_color(img, rgb) -> bool:
    return rgb in img.getdata()


def _find_pixel_font():
    """Locate PressStart2P-Regular.ttf in the core assets dir (mirrors
    test_score_antialiasing.py's helper -- the plugin runs inside
    LEDMatrix/plugin-repos/<id>/, so the core fonts are a couple levels up)."""
    name = "PressStart2P-Regular.ttf"
    candidates = []
    d = PLUGIN_DIR
    for _ in range(6):
        candidates.append(os.path.join(d, "assets", "fonts", name))
        d = os.path.dirname(d)
    candidates.append(os.path.join(os.getcwd(), "assets", "fonts", name))
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def test_team_colors_used_when_enabled_and_available():
    live = _make_live(128, 64)
    away_color = (233, 12, 24)
    home_color = (38, 82, 150)
    game = {
        "away_abbr": "STL", "home_abbr": "MIL",
        "away_score": "2", "home_score": "3",
        "away_hits": "3", "home_hits": "3",
        "away_errors": "0", "home_errors": "0",
        "away_linescore": ["0", "0", "2"], "home_linescore": ["2", "0", "1"],
        "inning": 4, "inning_half": "top",
        "balls": 1, "strikes": 2, "outs": 2,
        "is_live": True, "is_final": False, "has_count_data": True,
        "away_team_color": away_color, "home_team_color": home_color,
    }
    live.config = {"customization": {"traditional_scoreboard": {"use_team_colors": True}}}
    live._draw_traditional_scoreboard_screen(game)
    img = live.display_manager.image
    assert _image_contains_color(img, away_color), "expected away team color to be drawn"
    assert _image_contains_color(img, home_color), "expected home team color to be drawn"
    print("test_team_colors_used_when_enabled_and_available: PASS")


def test_team_colors_fall_back_to_text_color_when_disabled():
    live = _make_live(128, 64)
    text_color = (255, 255, 255)
    game = {
        "away_abbr": "STL", "home_abbr": "MIL",
        "away_score": "2", "home_score": "3",
        "away_hits": "3", "home_hits": "3",
        "away_errors": "0", "home_errors": "0",
        "away_linescore": ["0", "0", "2"], "home_linescore": ["2", "0", "1"],
        "inning": 4, "inning_half": "top",
        "balls": 1, "strikes": 2, "outs": 2,
        "is_live": True, "is_final": False, "has_count_data": True,
        "away_team_color": (233, 12, 24), "home_team_color": (38, 82, 150),
    }
    live.config = {"customization": {"traditional_scoreboard": {"use_team_colors": False}}}
    live._draw_traditional_scoreboard_screen(game)
    img = live.display_manager.image
    assert not _image_contains_color(img, (233, 12, 24)), "team color should not appear when disabled"
    assert not _image_contains_color(img, (38, 82, 150)), "team color should not appear when disabled"
    assert _image_contains_color(img, text_color), "expected flat text_color fallback to be drawn"
    print("test_team_colors_fall_back_to_text_color_when_disabled: PASS")


def test_at_bat_panel_fits_alongside_bigger_font_at_medium_size():
    # Regression: an earlier version of the auto-fit sizing math budgeted
    # exactly enough rows for the grid + At Bat label but rounded away the
    # room needed for the condensed ball/strike/out dots row, because
    # PressStart2P's actual glyph bbox height sometimes runs ~1px taller
    # than its nominal font_size. That discrepancy only shows up with the
    # real font -- a mocked/default font won't reproduce it -- so this test
    # loads the real PressStart2P.ttf and skips if it can't be found rather
    # than silently passing with a font that can't catch the bug.
    font_path = _find_pixel_font()
    if not font_path:
        print("SKIP test_at_bat_panel_fits_alongside_bigger_font_at_medium_size: "
              "could not locate PressStart2P-Regular.ttf (run from LEDMatrix tree)")
        return

    from PIL import ImageFont

    live = _make_live(128, 64)
    live._load_custom_font_from_element_config = (
        lambda cfg, default_size=6: ImageFont.truetype(font_path, cfg.get("font_size", default_size))
    )
    game = {
        "away_abbr": "BOS", "home_abbr": "NYY",
        "away_score": "3", "home_score": "4",
        "away_hits": "5", "home_hits": "7",
        "away_errors": "1", "home_errors": "0",
        "away_linescore": ["0", "1", "0", "0", "2", "0"],
        "home_linescore": ["1", "0", "1", "0", "0", "2"],
        "inning": 7, "inning_half": "top",
        "balls": 2, "strikes": 1, "outs": 1,
        "is_live": True, "is_final": False, "has_count_data": True,
    }
    live.config = {}
    live._draw_traditional_scoreboard_screen(game)
    img = live.display_manager.image
    # The At Bat panel's ball/strike/out dots are drawn in highlight_color
    # (default orange, 255,140,0); the header row's current-inning digit is
    # drawn in the same color, so also confirm at least a few dozen matching
    # pixels exist -- consistent with a real dots row, not just one digit.
    highlight_pixels = sum(1 for px in img.getdata() if px == (255, 140, 0))
    assert highlight_pixels > 20, (
        f"expected the At Bat panel's ball/strike/out dots to be drawn "
        f"(only {highlight_pixels} highlight-colored pixels found)"
    )
    print("test_at_bat_panel_fits_alongside_bigger_font_at_medium_size: PASS")


def _find_font_asset(name):
    """Generalized version of _find_pixel_font for an arbitrary filename."""
    candidates = []
    d = PLUGIN_DIR
    for _ in range(6):
        candidates.append(os.path.join(d, "assets", "fonts", name))
        d = os.path.dirname(d)
    candidates.append(os.path.join(os.getcwd(), "assets", "fonts", name))
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def _real_bdf_aware_loader(fonts_dir):
    """A _load_custom_font_from_element_config stand-in that mirrors the
    real one's BDF-native-size fallback (via BaseballLive._read_bdf_native_size)
    but resolves filenames against an absolute fonts_dir instead of a
    cwd-relative 'assets/fonts' path, so it works regardless of cwd."""
    from PIL import ImageFont

    def loader(cfg, default_size=6):
        name = cfg.get("font", "9x15.bdf")
        size = cfg.get("font_size", default_size)
        path = os.path.join(fonts_dir, name)
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            native = BaseballLive._read_bdf_native_size(path)
            if native:
                return ImageFont.truetype(path, native)
            raise

    return loader


_LIVE_GAME_WITH_COUNT_DATA = {
    "away_abbr": "BOS", "home_abbr": "NYY",
    "away_score": "3", "home_score": "4",
    "away_hits": "5", "home_hits": "7",
    "away_errors": "1", "home_errors": "0",
    "away_linescore": ["0", "1", "0", "0", "2", "0"],
    "home_linescore": ["1", "0", "1", "0", "0", "2"],
    "inning": 7, "inning_half": "top",
    "balls": 2, "strikes": 1, "outs": 1,
    "is_live": True, "is_final": False, "has_count_data": True,
}


def test_at_bat_column_appears_on_the_right_not_below():
    # The At Bat ball/strike/out column always sits to the right of the
    # grid (past R/H/E), vertically aligned with the header/away/home
    # rows, instead of stacking below it -- verify the dots actually land
    # near the right margin, and that nothing is drawn below the 3-row grid.
    font_path = _find_font_asset("9x15.bdf")
    if not font_path:
        print("SKIP test_at_bat_column_appears_on_the_right_not_below: "
              "could not locate 9x15.bdf (run from LEDMatrix tree)")
        return

    live = _make_live(192, 48)
    live._load_custom_font_from_element_config = _real_bdf_aware_loader(os.path.dirname(font_path))
    live.config = {}
    live._draw_traditional_scoreboard_screen(dict(_LIVE_GAME_WITH_COUNT_DATA))
    img = live.display_manager.image
    w, h = img.size

    margin = 1
    available_height = h - 2 * margin
    _, _, row_h = live._load_traditional_scoreboard_font(
        {"font": "9x15.bdf"}, needed_rows=3, available_height=available_height
    )
    grid_bottom = margin + 3 * row_h
    below_grid_has_content = any(
        img.getpixel((x, y)) != (0, 0, 0) for x in range(w) for y in range(min(grid_bottom, h), h)
    )
    assert not below_grid_has_content, "expected nothing drawn below the 3-row grid"

    highlight = (255, 140, 0)
    # Right third of the display, within the grid's row span -- the At Bat
    # column should land here now, near the right margin, not the left.
    right_third_start = 2 * w // 3
    highlight_pixels_right = sum(
        1 for x in range(right_third_start, w) for y in range(margin, min(grid_bottom, h))
        if img.getpixel((x, y)) == highlight
    )
    assert highlight_pixels_right > 40, (
        f"expected the At Bat column's B/S/O dots near the right margin, "
        f"only found {highlight_pixels_right} highlight-colored px there"
    )
    print("test_at_bat_column_appears_on_the_right_not_below: PASS")


def test_at_bat_column_at_max_counts_does_not_clip_off_either_edge():
    # Regression coverage for two related bugs: (1) the fit check used to
    # compare leftover width against a flush-left grid, but the grid is
    # centered, so it could still run content past an edge; (2) the Outs
    # row's extra batting-team ▲/▼ arrow wasn't factored into the width
    # check at all. Verify nothing draws into either margin column at max
    # counts (3 balls, 2 strikes, 2 outs -- real baseball maximums),
    # across every standard size.
    font_path = _find_font_asset("9x15.bdf")
    if not font_path:
        print("SKIP test_at_bat_column_at_max_counts_does_not_clip_off_either_edge: "
              "could not locate 9x15.bdf (run from LEDMatrix tree)")
        return

    game = dict(_LIVE_GAME_WITH_COUNT_DATA)
    game["balls"], game["strikes"], game["outs"] = 3, 2, 2  # real baseball maximums

    for w, h in ((64, 32), (128, 32), (128, 64), (192, 48), (256, 32), (256, 128)):
        live = _make_live(w, h)
        live._load_custom_font_from_element_config = _real_bdf_aware_loader(os.path.dirname(font_path))
        live.config = {}
        live._draw_traditional_scoreboard_screen(dict(game))
        img = live.display_manager.image
        margin = 1
        clipped = any(
            img.getpixel((x, y)) != (0, 0, 0)
            for edge in (range(0, margin), range(w - margin, w))
            for x in edge
            for y in range(h)
        )
        assert not clipped, (
            f"content drawn into a margin column at {w}x{h} with max "
            f"B/S/O counts -- likely clipped off an edge"
        )
    print("test_at_bat_column_at_max_counts_does_not_clip_off_either_edge: PASS")


def test_at_bat_column_hidden_when_display_too_narrow():
    # At 64x32 there isn't room for the At Bat column alongside even a
    # single inning column -- it should be dropped entirely (grid takes
    # priority) rather than clipped off the edge.
    font_path = _find_font_asset("9x15.bdf")
    if not font_path:
        print("SKIP test_at_bat_column_hidden_when_display_too_narrow: "
              "could not locate 9x15.bdf (run from LEDMatrix tree)")
        return

    live = _make_live(64, 32)
    live._load_custom_font_from_element_config = _real_bdf_aware_loader(os.path.dirname(font_path))
    live.config = {}
    live._draw_traditional_scoreboard_screen(dict(_LIVE_GAME_WITH_COUNT_DATA))
    img = live.display_manager.image
    w, h = img.size

    margin = 1
    available_height = h - 2 * margin
    _, _, row_h = live._load_traditional_scoreboard_font(
        {"font": "9x15.bdf"}, needed_rows=3, available_height=available_height
    )
    grid_bottom = margin + 3 * row_h
    highlight = (255, 140, 0)
    highlight_pixels = sum(
        1 for x in range(w) for y in range(margin, min(grid_bottom, h))
        if img.getpixel((x, y)) == highlight
    )
    assert highlight_pixels <= 30, (
        f"did not expect At Bat column B/S/O dots on a display too narrow "
        f"to fit them, found {highlight_pixels} highlight-colored px there"
    )
    print("test_at_bat_column_hidden_when_display_too_narrow: PASS")


def _make_gate_test_live(game_scope=None, favorites_only=None, favorite_teams=None):
    """A minimal live-like object for testing _maybe_draw_traditional_scoreboard_screen's
    gating logic in isolation, without needing a real font/render pass."""
    live = _make_live(192, 48)
    live.favorite_teams = favorite_teams or []
    cfg = {}
    if game_scope is not None:
        cfg["game_scope"] = game_scope
    if favorites_only is not None:
        cfg["favorites_only"] = favorites_only
    live.config = {"customization": {"traditional_scoreboard": cfg}}
    drawn = []
    live._draw_traditional_scoreboard_screen = lambda game, force_clear=False: drawn.append(game)
    return live, drawn


def test_game_scope_live_only_skips_final_games():
    live, drawn = _make_gate_test_live(game_scope="live")
    live._maybe_draw_traditional_scoreboard_screen({"is_live": False, "is_final": True, "home_abbr": "A", "away_abbr": "B"})
    assert drawn == [], "expected game_scope=live to skip a final game"
    result = live._maybe_draw_traditional_scoreboard_screen({"is_live": True, "is_final": False, "home_abbr": "A", "away_abbr": "B"})
    assert drawn and result is True, "expected game_scope=live to draw a live game"
    print("test_game_scope_live_only_skips_final_games: PASS")


def test_game_scope_recent_only_skips_live_games():
    live, drawn = _make_gate_test_live(game_scope="recent")
    live._maybe_draw_traditional_scoreboard_screen({"is_live": True, "is_final": False, "home_abbr": "A", "away_abbr": "B"})
    assert drawn == [], "expected game_scope=recent to skip a live game"
    result = live._maybe_draw_traditional_scoreboard_screen({"is_live": False, "is_final": True, "home_abbr": "A", "away_abbr": "B"})
    assert drawn and result is True, "expected game_scope=recent to draw a final game"
    print("test_game_scope_recent_only_skips_live_games: PASS")


def test_game_scope_both_draws_live_and_final():
    live, drawn = _make_gate_test_live(game_scope="both")
    live._maybe_draw_traditional_scoreboard_screen({"is_live": True, "is_final": False, "home_abbr": "A", "away_abbr": "B"})
    # Reset the rotation timer so the second call is treated as a fresh
    # rotate-in (due again) instead of "still showing" or "not due yet".
    live._trad_scoreboard_showing_until = 0.0
    live._trad_scoreboard_last_shown = 0.0
    live._maybe_draw_traditional_scoreboard_screen({"is_live": False, "is_final": True, "home_abbr": "A", "away_abbr": "B"})
    assert len(drawn) == 2, f"expected game_scope=both to draw both live and final games, drew {len(drawn)}"
    print("test_game_scope_both_draws_live_and_final: PASS")


def test_favorites_only_skips_non_favorite_teams():
    live, drawn = _make_gate_test_live(favorites_only=True, favorite_teams=["NYY"])
    live._maybe_draw_traditional_scoreboard_screen({"is_live": True, "is_final": False, "home_abbr": "BOS", "away_abbr": "TB"})
    assert drawn == [], "expected favorites_only to skip a game with no favorite team"
    result = live._maybe_draw_traditional_scoreboard_screen({"is_live": True, "is_final": False, "home_abbr": "NYY", "away_abbr": "BOS"})
    assert drawn and result is True, "expected favorites_only to draw a game involving a favorite team"
    print("test_favorites_only_skips_non_favorite_teams: PASS")


def test_favorites_only_has_no_effect_when_favorite_teams_empty():
    live, drawn = _make_gate_test_live(favorites_only=True, favorite_teams=[])
    result = live._maybe_draw_traditional_scoreboard_screen({"is_live": True, "is_final": False, "home_abbr": "BOS", "away_abbr": "TB"})
    assert drawn and result is True, (
        "expected favorites_only to have no effect (draw normally) when favorite_teams is empty"
    )
    print("test_favorites_only_has_no_effect_when_favorite_teams_empty: PASS")


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
        test_parse_team_color_valid_hex,
        test_parse_team_color_missing_or_malformed,
        test_parse_team_color_clamps_near_black_and_near_white,
        test_font_fallback_ladder_steps_down_when_default_does_not_fit,
        test_font_fallback_ladder_keeps_default_when_it_already_fits,
        test_inning_window_fits_full_nine,
        test_inning_window_extra_innings_fit,
        test_inning_window_narrow_display_early_game_shows_fixed_view,
        test_inning_window_narrow_display_scrolls_once_progressed_past_fit,
        test_inning_window_minimum_one_column,
        test_test_mode_update_resets_instead_of_climbing_forever,
        test_draws_without_crashing_at_small_size,
        test_team_colors_used_when_enabled_and_available,
        test_team_colors_fall_back_to_text_color_when_disabled,
        test_at_bat_panel_fits_alongside_bigger_font_at_medium_size,
        test_at_bat_column_appears_on_the_right_not_below,
        test_at_bat_column_at_max_counts_does_not_clip_off_either_edge,
        test_at_bat_column_hidden_when_display_too_narrow,
        test_game_scope_live_only_skips_final_games,
        test_game_scope_recent_only_skips_live_games,
        test_game_scope_both_draws_live_and_final,
        test_favorites_only_skips_non_favorite_teams,
        test_favorites_only_has_no_effect_when_favorite_teams_empty,
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
