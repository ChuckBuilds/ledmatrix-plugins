#!/usr/bin/env python3
"""Every real manager class must carry the selection helpers, not just one.

The helpers first landed on SportsUpcoming. SportsRecent is a SIBLING of it,
not a subclass, so the recent path called a method it did not have --
AttributeError, swallowed by update()'s own try/except, recent games silently
blank. Tests that drove SportsUpcoming directly all passed.

So this drives the classes the plugin actually instantiates: live, recent and
upcoming, for both leagues. A helper that goes missing from any of them, or a
favourite matcher that stops matching, fails here rather than on a panel.

Favourite detection is asserted in both directions on purpose. Checking only
that a favourite returns True passes against a matcher that returns True for
everything, which would put the whole league in the favourites bucket and
quietly empty the "other games" slots.

Run: <core-venv>/bin/python plugins/football-scoreboard/test_managers_have_the_selection_helpers.py
"""

import os
import sys
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

results = []

HELPERS = (
    "_is_favorite_game",
    "_favorites_first",
    "_passes_other_filters",
    "_other_games_window",
    "_game_divisions",
    "_is_ranked_game",
    "_league_has_rankings",
    "_load_division_team_ids",
)

SETTINGS = (
    "other_upcoming_games_to_show",
    "other_recent_games_to_show",
    "other_rotation_interval_seconds",
    "other_games_min_quality",
    "other_games_divisions",
)


def check(case, passed, detail=""):
    results.append((case, passed))
    print("  [%s] %s%s" % ("pass" if passed else "FAIL", case,
                           "" if passed else "  <- " + str(detail)))


def main():
    os.chdir(str(CORE))
    import logging
    from unittest.mock import MagicMock
    logging.disable(logging.INFO)

    import nfl_managers as nfl
    import ncaa_fb_managers as ncaa

    display = MagicMock()
    display.matrix.width, display.matrix.height = 128, 32
    cache = MagicMock()
    cache.get.return_value = None

    def build(cls, key, favourites):
        config = {key: {
            "enabled": True,
            "favorite_teams": favourites,
            "display_modes": {},
            "recent_games_to_show": 2,
            "upcoming_games_to_show": 2,
            "other_upcoming_games_to_show": 2,
            "other_recent_games_to_show": 2,
            "other_rotation_interval_seconds": 1800,
            "other_games_min_quality": "ranked",
            "other_games_divisions": ["fbs"],
            "show_odds": False,
            "show_ranking": False,
        }}
        return cls(config, display, cache)

    favourite = {"id": "a", "home_abbr": "TB", "away_abbr": "KC",
                 "home_id": 27, "away_id": 12}
    stranger = {"id": "b", "home_abbr": "SEA", "away_abbr": "TEN",
                "home_id": 26, "away_id": 10}

    managers = (
        ("NFLLiveManager", nfl.NFLLiveManager, "nfl_scoreboard"),
        ("NFLRecentManager", nfl.NFLRecentManager, "nfl_scoreboard"),
        ("NFLUpcomingManager", nfl.NFLUpcomingManager, "nfl_scoreboard"),
        ("NCAAFBLiveManager", ncaa.NCAAFBLiveManager, "ncaa_fb_scoreboard"),
        ("NCAAFBRecentManager", ncaa.NCAAFBRecentManager, "ncaa_fb_scoreboard"),
        ("NCAAFBUpcomingManager", ncaa.NCAAFBUpcomingManager, "ncaa_fb_scoreboard"),
    )

    for name, cls, key in managers:
        manager = build(cls, key, ["TB"])

        missing = [h for h in HELPERS if not hasattr(manager, h)]
        check("%s has every selection helper" % name, not missing, missing)

        unset = [s for s in SETTINGS if not hasattr(manager, s)]
        check("%s has every selection setting" % name, not unset, unset)

        check("%s matches a favourite" % name,
              manager._is_favorite_game(favourite) is True)
        check("%s does NOT match a stranger" % name,
              manager._is_favorite_game(stranger) is False)

    print("\nand the settings arrive with the values that were configured")
    manager = build(nfl.NFLUpcomingManager, "nfl_scoreboard", ["TB"])
    check("other_upcoming_games_to_show", manager.other_upcoming_games_to_show == 2,
          manager.other_upcoming_games_to_show)
    check("other_games_min_quality", manager.other_games_min_quality == "ranked",
          manager.other_games_min_quality)
    check("other_games_divisions", list(manager.other_games_divisions) == ["fbs"],
          manager.other_games_divisions)

    print("\nrankings are only sought where a poll exists")
    ncaa_up = build(ncaa.NCAAFBUpcomingManager, "ncaa_fb_scoreboard", ["UGA"])
    nfl_up = build(nfl.NFLUpcomingManager, "nfl_scoreboard", ["TB"])
    check("college-football looks for a poll", ncaa_up._league_has_rankings() is True,
          ncaa_up.league)
    check("nfl does not", nfl_up._league_has_rankings() is False, nfl_up.league)

    failed = [c for c, ok in results if not ok]
    print("\n%d checks, %d failed" % (len(results), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
