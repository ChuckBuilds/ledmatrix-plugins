#!/usr/bin/env python3
"""
Tests for the non_favorite_live_game_duration live-rotation logic added to
SportsLive (_effective_live_duration): live games that involve no favorite team
can be given a shorter on-screen turn than favorite-team games, but only when
favorites are configured (and, in practice, show_favorite_teams_only is off so
non-favorite games are actually shown). Defaults to 0 = unchanged behavior.

Run: <core-venv>/bin/python plugins/lacrosse-scoreboard/test_non_favorite_live_duration.py
"""

import os
import sys
import types
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))


def _stub_core_src():
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
    mod("src.plugin_system.base_plugin", BasePlugin=None, VegasDisplayMode=object)
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

import sports  # noqa: E402


class _TestLive(sports.SportsLive):
    def _extract_game_details(self, game_event):
        return game_event

    def _fetch_data(self):
        return None


def make_live(favorite_teams=None, game_display_duration=30,
              non_favorite_live_game_duration=0):
    live = object.__new__(_TestLive)
    live.favorite_teams = favorite_teams or []
    live.game_display_duration = game_display_duration
    live.non_favorite_live_game_duration = non_favorite_live_game_duration
    return live


def game(home, away):
    return {"id": f"{away}@{home}", "home_abbr": home, "away_abbr": away}


results = []


def check(name, passed):
    results.append((name, passed))
    print(f"{'PASS' if passed else 'FAIL'}: {name}")


fav_game = game("MARYLAND", "SYRACUSE")       # favorite is home
fav_game_away = game("SYRACUSE", "MARYLAND")  # favorite is away
non_fav_game = game("DUKE", "CORNELL")        # no favorite

# --- feature off (default 0) -> every live game uses the base duration -------
live = make_live(favorite_teams=["MARYLAND"], game_display_duration=30,
                 non_favorite_live_game_duration=0)
check("knob=0: favorite game uses base duration",
      live._effective_live_duration(fav_game) == 30)
check("knob=0: non-favorite game uses base duration (backward compatible)",
      live._effective_live_duration(non_fav_game) == 30)

# --- feature on, favorites configured ---------------------------------------
live = make_live(favorite_teams=["MARYLAND"], game_display_duration=30,
                 non_favorite_live_game_duration=5)
check("favorite (home) keeps base duration",
      live._effective_live_duration(fav_game) == 30)
check("favorite (away) keeps base duration",
      live._effective_live_duration(fav_game_away) == 30)
check("non-favorite game uses the shorter duration",
      live._effective_live_duration(non_fav_game) == 5)

# --- no favorites configured -> knob is a no-op even when set ----------------
live = make_live(favorite_teams=[], game_display_duration=30,
                 non_favorite_live_game_duration=5)
check("no favorites: non-favorite game still uses base duration",
      live._effective_live_duration(non_fav_game) == 30)

# --- None current_game (e.g. before any game loads) is safe -----------------
live = make_live(favorite_teams=["MARYLAND"], game_display_duration=30,
                 non_favorite_live_game_duration=5)
check("None game falls back to base duration",
      live._effective_live_duration(None) == 30)

print()
failed = [n for n, p in results if not p]
if failed:
    print(f"{len(failed)} FAILED: {failed}")
    sys.exit(1)
print(f"All {len(results)} checks passed.")
