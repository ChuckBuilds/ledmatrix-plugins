#!/usr/bin/env python3
"""
Regression test for exclude_teams + favorite_live_boost in SportsLive.

Covers:
  1. Excluded team never included in the live filter, even with show_all_live=True.
  2. Excluded wins over favorite_teams when a team is in both lists.
  3. favorite_live_boost=1 -> rotation schedule is a single pass in sorted order
     (identical to pre-existing behavior).
  4. favorite_live_boost=2 with one favorite + 2 other live games -> favorite
     appears 2 of every 4 schedule slots, evenly spaced (not clumped).

Run: <core-venv>/bin/python plugins/hockey-scoreboard/test_favorite_live_boost.py
"""

import os
import sys
import types
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))


def _stub_core_src():
    """Stub the core ``src.*``/third-party modules sports.py imports at load
    time, so this test can run from the monorepo without a LEDMatrix core
    checkout or network deps on the path (mirrors
    plugins/soccer-scoreboard/test_live_mode_targeting.py)."""

    def mod(name, **attrs):
        m = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        sys.modules.setdefault(name, m)
        return m

    mod("src")
    mod("src.common")
    mod("src.plugin_system")
    mod("src.logo_downloader", LogoDownloader=object, download_missing_logo=lambda *a, **k: None)
    mod("src.common.scroll_helper", ScrollHelper=object)
    mod("src.plugin_system.base_plugin", BasePlugin=object, VegasDisplayMode=object)
    mod("src.background_data_service", get_background_service=lambda *a, **k: None)

    # The stubs above are plain ModuleTypes, so `from src.common.X import Y`
    # fails with "'src.common' is not a package" even when a real core is on
    # the path. Giving them a __path__ lets genuine submodules -- sports_shared,
    # sports_card -- resolve from the core while the stubbed ones stay stubbed.
    # Stubbing those too would make this test pass against dummies instead of
    # the code under test.
    _core = os.environ.get("LEDMATRIX_CORE") or next(
        (p for p in sys.path
         if p and os.path.isdir(os.path.join(p, "src", "common"))), None)
    if _core:
        if "src" in sys.modules and not hasattr(sys.modules["src"], "__path__"):
            sys.modules["src"].__path__ = [os.path.join(_core, "src")]
        if ("src.common" in sys.modules
                and not hasattr(sys.modules["src.common"], "__path__")):
            sys.modules["src.common"].__path__ = [
                os.path.join(_core, "src", "common")]


_stub_core_src()

from nhl_managers import NHLLiveManager  # noqa: E402


def make_live(favorite_teams=None, exclude_teams=None, show_all_live=False,
              show_favorite_teams_only=False, favorite_live_boost=2):
    """Build a concrete live-manager instance (NHLLiveManager - the only fully
    concrete subclass of SportsLive/SportsCore) with just the attributes the
    logic under test touches, bypassing the network/config-heavy __init__.
    The exclude/boost logic under test lives on SportsLive itself, so this
    exercises the real shared implementation, not a league-specific override.
    """
    live = NHLLiveManager.__new__(NHLLiveManager)
    live.favorite_teams = favorite_teams or []
    live.exclude_teams = exclude_teams or []
    live.show_all_live = show_all_live
    live.show_favorite_teams_only = show_favorite_teams_only
    live.favorite_live_boost = favorite_live_boost
    return live


def game(gid, home, away):
    return {"id": gid, "home_abbr": home, "away_abbr": away}


results = []


def check(name, passed):
    results.append((name, passed))
    print(f"{'PASS' if passed else 'FAIL'}: {name}")


# --- Case 1: excluded team never included, even with show_all_live=True ----
live = make_live(exclude_teams=["TB"], show_all_live=True)
check(
    "excluded team hidden even with show_all_live=True",
    live._is_live_game_included("TB", "BOS") is False,
)
check(
    "non-excluded game still included with show_all_live=True",
    live._is_live_game_included("BOS", "NYR") is True,
)

# --- Case 2: excluded wins over favorite_teams when in both lists ----------
live = make_live(favorite_teams=["TB"], exclude_teams=["TB"], show_favorite_teams_only=True)
check(
    "exclude_teams takes precedence over favorite_teams",
    live._is_live_game_included("TB", "BOS") is False,
)

# --- Case 3: favorite_live_boost=1 -> single pass, no repeats --------------
live = make_live(favorite_teams=["TB"], favorite_live_boost=1)
games = [game("a", "TB", "BOS"), game("b", "NYR", "NJD"), game("c", "PIT", "WSH")]
schedule = live._build_rotation_schedule(games)
check(
    "boost=1 schedule is a single pass over the given games",
    schedule == ["a", "b", "c"],
)

# --- Case 4: favorite_live_boost=2, favorite + 2 others -> 2:1:1 evenly spaced
live = make_live(favorite_teams=["TB"], favorite_live_boost=2)
games = [game("fav", "TB", "BOS"), game("o1", "NYR", "NJD"), game("o2", "PIT", "WSH")]
schedule = live._build_rotation_schedule(games)
check("boost=2 schedule length is total weight (2+1+1=4)", len(schedule) == 4)
check("boost=2 favorite appears exactly twice per cycle", schedule.count("fav") == 2)
check("boost=2 others appear exactly once each per cycle",
      schedule.count("o1") == 1 and schedule.count("o2") == 1)
# Evenly spaced: favorite should not occupy two adjacent slots.
adjacent_fav = any(schedule[i] == "fav" and schedule[i + 1] == "fav"
                   for i in range(len(schedule) - 1))
check("boost=2 favorite slots are not clumped together", not adjacent_fav)

# --- Case 5: no favorite live -> boost has no effect on ordering -----------
live = make_live(favorite_teams=["TB"], favorite_live_boost=3)
games = [game("x", "NYR", "NJD"), game("y", "PIT", "WSH")]
schedule = live._build_rotation_schedule(games)
check(
    "no favorite in live set -> boost is a no-op (single pass)",
    schedule == ["x", "y"],
)

print()
passed = sum(1 for _, p in results if p)
print(f"{passed}/{len(results)} checks passed")
sys.exit(0 if passed == len(results) else 1)
