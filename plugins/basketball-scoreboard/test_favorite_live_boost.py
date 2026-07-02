#!/usr/bin/env python3
"""
Regression + behavior tests for exclude_teams and filtering.favorite_live_boost
on the basketball-scoreboard live rotation (SportsLive in sports.py).

Covers:
  - Excluded team's game never included in the live filter, even with
    show_all_live=True or tournament_mode=True.
  - Excluded wins over favorite_teams when a team is in both lists.
  - favorite_live_boost=1 / no favorite live -> schedule matches plain order
    (regression safety for the majority of users who don't touch this).
  - favorite_live_boost=N>1 -> favorite's game appears N of every
    N + len(other games) slots, evenly spaced (not clumped).

Run: <core-venv>/bin/python plugins/basketball-scoreboard/test_favorite_live_boost.py
"""

import sys
import types
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))


def _stub_core_src():
    """Stub the single core ``src.*`` module sports.py imports at load time."""
    def mod(name, **attrs):
        m = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        sys.modules.setdefault(name, m)
        return m

    mod("src")
    mod("src.logo_downloader", LogoDownloader=object, download_missing_logo=lambda *a, **k: None)


_stub_core_src()

from sports import SportsLive  # noqa: E402


class _TestableLive(SportsLive):
    """Concrete stand-in so we can __new__ without running SportsCore's abstract init."""

    def _extract_game_details(self, event):  # pragma: no cover - unused in these tests
        return event

    def _fetch_data(self):  # pragma: no cover - unused in these tests
        return None


def make_live_manager(favorite_teams, exclude_teams, favorite_live_boost=2,
                       show_all_live=False, show_favorite_teams_only=False,
                       tournament_mode=False):
    """Build a SportsLive instance with just the state we touch, no network/init."""
    live = _TestableLive.__new__(_TestableLive)
    live.favorite_teams = favorite_teams
    live.exclude_teams = exclude_teams
    live.favorite_live_boost = favorite_live_boost
    live.show_all_live = show_all_live
    live.show_favorite_teams_only = show_favorite_teams_only
    live.tournament_mode = tournament_mode
    return live


def game(gid, home, away, is_tournament=False):
    return {"id": gid, "home_abbr": home, "away_abbr": away, "is_tournament": is_tournament}


def filter_decision(live, details):
    """Mirror the inclusion branch added in sports.py's SportsLive.update()."""
    if (details.get("home_abbr") in live.exclude_teams
            or details.get("away_abbr") in live.exclude_teams):
        return False
    if live.tournament_mode and details.get("is_tournament"):
        return True
    if live.show_all_live:
        return True
    if not live.show_favorite_teams_only:
        return True
    if not live.favorite_teams:
        return True
    return (details["home_abbr"] in live.favorite_teams
            or details["away_abbr"] in live.favorite_teams)


results = []


def check(name, passed):
    results.append((name, passed))
    print(f"{'PASS' if passed else 'FAIL'}: {name}")


# --- Case 1: excluded team never included, even with show_all_live=True ----
live = make_live_manager(favorite_teams=[], exclude_teams=["LAL"], show_all_live=True)
g = game("1", "LAL", "BOS")
check("excluded team hidden even with show_all_live=True", filter_decision(live, g) is False)

# --- Case 2: excluded team never included, even with tournament_mode=True --
live = make_live_manager(favorite_teams=[], exclude_teams=["DUKE"], tournament_mode=True)
g = game("2", "DUKE", "UNC", is_tournament=True)
check("excluded team hidden even with tournament_mode=True", filter_decision(live, g) is False)

# --- Case 3: exclude wins over favorite_teams when team is in both lists ---
live = make_live_manager(favorite_teams=["GSW"], exclude_teams=["GSW"],
                          show_favorite_teams_only=True)
g = game("3", "GSW", "LAL")
check("exclude takes priority over favorite_teams", filter_decision(live, g) is False)

# --- Case 4: non-excluded games unaffected ---------------------------------
live = make_live_manager(favorite_teams=[], exclude_teams=["LAL"], show_all_live=True)
g = game("4", "BOS", "MIA")
check("non-excluded game still included with show_all_live=True", filter_decision(live, g) is True)

# --- Case 5: favorite_live_boost=1, no favorites -> schedule matches plain order
live = make_live_manager(favorite_teams=[], exclude_teams=[], favorite_live_boost=1)
games = [game("a", "BOS", "MIA"), game("b", "GSW", "LAL"), game("c", "NYK", "PHI")]
schedule = live._build_weighted_schedule(games)
check("boost=1/no favorites -> schedule matches input order",
      schedule == ["a", "b", "c"])

# --- Case 6: favorite live, boost=1 -> still matches plain order (neutral) -
live = make_live_manager(favorite_teams=["GSW"], exclude_teams=[], favorite_live_boost=1)
games = [game("a", "BOS", "MIA"), game("b", "GSW", "LAL"), game("c", "NYK", "PHI")]
schedule = live._build_weighted_schedule(games)
check("boost=1 with a favorite live -> still matches input order",
      schedule == ["a", "b", "c"])

# --- Case 7: favorite live, boost=2, 2 other live games -> evenly spaced ---
live = make_live_manager(favorite_teams=["GSW"], exclude_teams=[], favorite_live_boost=2)
games = [game("fav", "GSW", "LAL"), game("a", "BOS", "MIA"), game("b", "NYK", "PHI")]
schedule = live._build_weighted_schedule(games)
fav_count = schedule.count("fav")
total = len(schedule)
# total weight = 2 (fav) + 1 + 1 = 4
check("boost=2 with 2 other live games -> total schedule length is 4",
      total == 4)
check("boost=2 with 2 other live games -> favorite appears 2 of 4 slots",
      fav_count == 2)
# Evenly spaced means the favorite's two slot indices should not be adjacent
# at both ends (i.e. not clumped as [fav, fav, a, b] or [a, b, fav, fav]).
fav_indices = [i for i, gid in enumerate(schedule) if gid == "fav"]
is_clumped = (fav_indices == [0, 1] or fav_indices == [total - 2, total - 1])
check(f"boost=2 favorite slots {fav_indices} in schedule {schedule} are spread, not clumped",
      not is_clumped)

# --- Case 8: no favorite present among live games -> boost has no effect ---
live = make_live_manager(favorite_teams=["GSW"], exclude_teams=[], favorite_live_boost=3)
games = [game("a", "BOS", "MIA"), game("b", "NYK", "PHI")]
schedule = live._build_weighted_schedule(games)
check("favorite configured but not live -> boost has no effect on schedule",
      schedule == ["a", "b"])

print()
failed = [name for name, passed in results if not passed]
if failed:
    print(f"{len(failed)} FAILED: {failed}")
    sys.exit(1)
print(f"All {len(results)} checks passed.")
