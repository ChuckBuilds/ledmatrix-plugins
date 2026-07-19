#!/usr/bin/env python3
"""
Regression tests for live-game logo positioning.

The live scorebug (`BaseballLive._draw_scorebug_layout`) must honor the
configured Home/Away logo x/y offsets (`customization.layout.home_logo` /
`away_logo`) the same way upcoming and recent games already do. It used to
hardcode the logo positions, so any configured offset was ignored and the
logos snapped back to the panel edges once a game went live.

These tests drive the real method and capture the coordinates the logos are
pasted at, asserting that:
  * zero offsets keep the historical baseline placement, and
  * non-zero offsets shift both logos on both axes by exactly that amount.

Run: <core-venv>/bin/python plugins/baseball-scoreboard/test_live_logo_offset.py
"""

import logging
import os
import sys

from PIL import Image, ImageFont

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

import baseball  # noqa: E402
from baseball import BaseballLive  # noqa: E402


class _ConcreteBaseballLive(BaseballLive):
    """Minimal concrete BaseballLive so we can instantiate without the full
    manager stack (mirrors test_traditional_scoreboard.py's version)."""

    def _extract_game_details(self, game_event):  # abstract in SportsCore
        return None

    def _fetch_data(self):  # abstract in SportsCore
        return None


class _DisplayManager:
    def __init__(self, width, height):
        self.image = Image.new("RGB", (width, height))
        self.font = ImageFont.load_default()
        self.draw = None
        self._updated = False

    def update_display(self):
        self._updated = True


def _make_live(width, height, layout=None):
    live = object.__new__(_ConcreteBaseballLive)
    live.display_width = width
    live.display_height = height
    live.display_manager = _DisplayManager(width, height)
    live.config = {"customization": {"layout": layout or {}}}
    live.favorite_teams = []
    live.logger = logging.getLogger("test_live_logo_offset")
    # The scorebug draws bases/count/score after the logos from game fields we
    # deliberately omit; that raises inside the method's own try/except (which
    # logs and swallows) well after both logos are pasted. Silence the expected
    # error log so the test output stays clean.
    live.logger.setLevel(logging.CRITICAL)

    # Skip the alternate live screens so we exercise the standard scorebug.
    live._maybe_draw_at_bat_info_screen = lambda game, force_clear=False: False
    live._maybe_draw_player_card_screen = lambda game, force_clear=False: False
    live._maybe_draw_traditional_scoreboard_screen = (
        lambda game, force_clear=False: False
    )
    return live


def _make_logo(size):
    return Image.new("RGBA", size, (255, 0, 0, 255))


_GAME = {
    "id": "401",
    "home_id": "1",
    "home_abbr": "HOM",
    "home_logo_path": "home.png",
    "home_logo_url": None,
    "away_id": "2",
    "away_abbr": "AWY",
    "away_logo_path": "away.png",
    "away_logo_url": None,
    "is_final": False,
    "inning_half": "top",
    "inning": 3,
    "home_score": 0,
    "away_score": 0,
}


def _capture_logo_pastes(width, height, home_size, away_size, layout):
    """Run the real live scorebug and return the (home_box, away_box)
    coordinates the two team logos were pasted at."""
    live = _make_live(width, height, layout=layout)
    home_logo = _make_logo(home_size)
    away_logo = _make_logo(away_size)
    live._load_and_resize_logo = lambda *a, **k: (
        home_logo if a and str(a[0]) == "1" else away_logo
    )

    pastes = []
    orig_new = baseball.Image.new

    def recording_new(mode, size, color=0):
        img = orig_new(mode, size, color)
        orig_paste = img.paste

        def paste(im, box=None, mask=None):
            pastes.append(box)
            return orig_paste(im, box, mask)

        img.paste = paste
        return img

    baseball.Image.new = recording_new
    try:
        live._draw_scorebug_layout(dict(_GAME))
    finally:
        baseball.Image.new = orig_new

    # The first two paste calls on the scorebug image are home then away.
    assert len(pastes) >= 2, f"expected >=2 logo pastes, got {pastes}"
    return pastes[0], pastes[1]


def test_zero_offsets_keep_baseline_placement():
    w, h = 128, 64
    home_size = away_size = (20, 20)
    home_box, away_box = _capture_logo_pastes(w, h, home_size, away_size, layout={})

    center_y = h // 2
    expected_home = (w - home_size[0] + 2, center_y - home_size[1] // 2)
    expected_away = (-2, center_y - away_size[1] // 2)
    assert home_box == expected_home, f"home baseline: {home_box} != {expected_home}"
    assert away_box == expected_away, f"away baseline: {away_box} != {expected_away}"
    print("test_zero_offsets_keep_baseline_placement: PASS")


def test_offsets_shift_both_logos_on_both_axes():
    w, h = 128, 64
    home_size = away_size = (20, 20)
    layout = {
        "home_logo": {"x_offset": 3, "y_offset": -4},
        "away_logo": {"x_offset": -5, "y_offset": 6},
    }
    home_box, away_box = _capture_logo_pastes(w, h, home_size, away_size, layout=layout)

    center_y = h // 2
    base_home = (w - home_size[0] + 2, center_y - home_size[1] // 2)
    base_away = (-2, center_y - away_size[1] // 2)
    expected_home = (base_home[0] + 3, base_home[1] - 4)
    expected_away = (base_away[0] - 5, base_away[1] + 6)
    assert home_box == expected_home, f"home offset: {home_box} != {expected_home}"
    assert away_box == expected_away, f"away offset: {away_box} != {expected_away}"
    print("test_offsets_shift_both_logos_on_both_axes: PASS")


if __name__ == "__main__":
    test_zero_offsets_keep_baseline_placement()
    test_offsets_shift_both_logos_on_both_axes()
    print("\nAll live logo offset tests passed.")
