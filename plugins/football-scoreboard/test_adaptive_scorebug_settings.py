#!/usr/bin/env python3
"""The adaptive full-screen scorebug must honour the settings the user set.

In adaptive mode SportsCore._adaptive_scorebug hands every live/recent/upcoming
frame to GameRenderer. It used to build that renderer from self.config, which
is the manager-shaped dict _adapt_config_for_manager produces: show_odds,
show_records and show_ranking live under "nfl_scoreboard" there, while the
renderer looks in config["nfl"]["display_options"] or at the root. It found
neither, so odds, records and rankings never drew whatever the settings said.
The existing renderer tests built GameRenderer from a plugin-shaped dict and
could not see it -- so this one goes through the real translation.

The same renderer also read the scroll/Vegas upcoming keys (upcoming_center,
show_date, show_time, date_format) on the full-screen scorebug, where the
classic path reads the switch_* twins.

Run: <core-venv>/bin/python plugins/football-scoreboard/test_adaptive_scorebug_settings.py
"""

import logging
import os
import sys
import types
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

REPO = Path(__file__).resolve().parents[2]
CORE = None
for _c in (os.environ.get("LEDMATRIX_CORE", ""),
           str(REPO.parent / "LEDMatrix"),
           str(Path.home() / "projects" / "LEDMatrix")):
    if _c and (Path(_c) / "assets" / "fonts").is_dir():
        CORE = Path(_c)
        break
if CORE is None:
    print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
    sys.exit(2)
sys.path.insert(0, str(CORE))
logging.disable(logging.CRITICAL)

LOGOS = plugin_dir / "assets" / "sports" / "nfl_logos"
WIDTH, HEIGHT = 128, 32

results = []


def check(case, passed, detail=""):
    results.append((case, passed))
    print("  [%s] %s%s" % ("pass" if passed else "FAIL", case,
                           "" if passed else "  <- " + str(detail)))


PLUGIN_CONFIG = {
    "enabled": True,
    "timezone": "America/Chicago",
    "layout_mode": "adaptive",
    "nfl": {
        "enabled": True,
        "favorite_teams": ["KC"],
        "display_options": {"show_odds": True, "show_records": True,
                            "show_ranking": False},
    },
    "ncaa_fb": {"enabled": False},
    # Scroll/Vegas values chosen to differ from the full-screen ones, so a
    # renderer reading the wrong set is visible.
    "scroll_card": {
        "upcoming_center": "vs", "show_date": False, "show_time": False,
        "date_format": "abbrev",
        "switch_upcoming_center": "date_time", "switch_show_date": True,
        "switch_show_time": True, "switch_date_format": "numeric",
    },
}


def _game(**extra):
    game = {
        "id": "401", "league": "nfl",
        "home_id": "1", "home_abbr": "KC", "home_logo_path": str(LOGOS / "KC.png"),
        "away_id": "2", "away_abbr": "GB", "away_logo_path": str(LOGOS / "GB.png"),
        "home_score": "0", "away_score": "0",
        "home_record": "10-2", "away_record": "8-4",
        "is_live": False, "period_text": "",
        "game_time": "7:30PM", "game_date": "10/12",
    }
    game.update(extra)
    return game


ODDS = {"spread": -7.0, "over_under": 47.0,
        "home_team_odds": {"spread_odds": -7.0},
        "away_team_odds": {"spread_odds": 7.0}}


def main():
    os.chdir(str(CORE))
    from unittest.mock import MagicMock

    import manager as plugin_manager
    import sports
    from game_renderer import ADAPTIVE_AVAILABLE, GameRenderer
    if not ADAPTIVE_AVAILABLE:
        print("SKIP: core without src.adaptive_layout")
        return 2

    plugin = plugin_manager.FootballScoreboardPlugin.__new__(
        plugin_manager.FootballScoreboardPlugin)
    plugin.config = PLUGIN_CONFIG
    plugin.logger = logging.getLogger("adaptive_settings_probe")
    plugin.cache_manager = MagicMock()
    plugin.plugin_manager = None
    adapted = plugin._adapt_config_for_manager("nfl")
    mode = adapted["nfl_scoreboard"]

    class _DM:
        def __init__(self):
            self.matrix = types.SimpleNamespace(width=WIDTH, height=HEIGHT)
            self.image = None

        def clear(self):
            pass

        def update_display(self):
            pass

    stub = types.SimpleNamespace(
        config=adapted, show_odds=mode["show_odds"],
        show_records=mode["show_records"], show_ranking=mode["show_ranking"],
        display_manager=_DM(), display_width=WIDTH, display_height=HEIGHT,
        logger=plugin.logger, _team_rankings_cache={},
    )
    drew = sports.SportsCore._adaptive_scorebug(stub, _game(odds=ODDS), "upcoming")
    check("the adaptive scorebug rendered", drew is True)
    renderer = getattr(stub, "_adaptive_renderer", None)
    if renderer is None:
        print("\nno renderer was built")
        return 1

    # C1: the display options reach the renderer through the real adapter.
    check("show_odds reaches the adaptive renderer",
          renderer._get_display_option("nfl", "show_odds") is True)
    check("show_records reaches the adaptive renderer",
          renderer._get_display_option("nfl", "show_records") is True)
    with_odds = renderer.render_game_card(_game(odds=ODDS), "upcoming")
    without = renderer.render_game_card(_game(), "upcoming")
    from PIL import ImageChops
    check("odds actually draw on the adaptive card",
          ImageChops.difference(with_odds, without).getbbox() is not None)

    # Cosmetic: %g odds text, as the classic scorebug draws it.
    drawn = []
    original = renderer._draw_text_with_outline

    def _record(draw, text, *a, **k):
        drawn.append(text)
        return original(draw, text, *a, **k)

    renderer._draw_text_with_outline = _record
    renderer.render_game_card(_game(odds=ODDS), "upcoming")
    del renderer._draw_text_with_outline
    check("whole-number odds drop the trailing .0",
          drawn and not any(".0" in str(t) for t in drawn), drawn)

    # M2: switch context reads the switch_* keys.
    check("renderer knows it draws the full-screen scorebug",
          getattr(renderer, "switch_context", False) is True)
    check("switch_show_date wins over the scroll show_date",
          renderer._upcoming_show("date") is True)
    check("switch_upcoming_center wins over upcoming_center",
          renderer._upcoming_center_mode() == "date_time",
          renderer._upcoming_center_mode())
    check("switch_date_format wins over date_format",
          renderer._format_game_date("10/12") == "10/12",
          renderer._format_game_date("10/12"))

    # ...while the scroll/Vegas renderer keeps reading the scroll keys.
    scroll = GameRenderer(WIDTH, HEIGHT, PLUGIN_CONFIG)
    check("scroll card still follows show_date", scroll._upcoming_show("date") is False)
    check("scroll card still follows upcoming_center",
          scroll._upcoming_center_mode() == "vs")

    # P-B3: both toggles on and the team unranked -> its record, not blank.
    check("unranked team falls back to its record",
          renderer._get_team_display_text("KC", "10-2", True, True) == "10-2")

    failed = [c for c, ok in results if not ok]
    print("\n%d checks, %d failed" % (len(results), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
