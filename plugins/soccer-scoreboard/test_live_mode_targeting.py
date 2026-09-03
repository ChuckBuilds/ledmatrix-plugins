#!/usr/bin/env python3
"""
Regression test for get_live_modes() per-league targeting.

Before the fix, get_live_modes() returned the generic ["soccer_live"], which
does not match any mode the host actually registers for this plugin (modes are
registered per league as "soccer_<league>_live"). The display controller could
not switch to the league that had the live game and fell back to the first
"*_live" mode in registration order — often an empty league.

This test asserts get_live_modes() returns the real per-league live mode names,
only for leagues whose live games match the favorites filter (or show_all_live).

Run: <core-venv>/bin/python plugins/soccer-scoreboard/test_live_mode_targeting.py
"""

import os
import sys
import threading
import types
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))


def _stub_core_src():
    """Stub the core ``src.*`` modules the plugin imports at load time.

    The plugin's ``sports.py`` does ``from src.logo_downloader import ...`` etc.,
    which only resolve inside a LEDMatrix core checkout. ``get_live_modes`` needs
    none of them at call time, so stubbing keeps this test runnable from the
    monorepo (and CI) without a core tree on the path.
    """
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

from manager import SoccerScoreboardPlugin  # noqa: E402
from sports import SportsLive  # noqa: E402


class StubLiveManager:
    """Minimal stand-in for a league's live manager."""

    def __init__(self, live_games, favorite_teams, show_all_live=False):
        self.live_games = live_games
        self.favorite_teams = favorite_teams
        self.show_all_live = show_all_live


def make_plugin(registry, managers_by_league):
    """Build a plugin instance with just the state get_live_modes() touches."""
    plugin = SoccerScoreboardPlugin.__new__(SoccerScoreboardPlugin)
    plugin.is_enabled = True
    plugin._config_lock = threading.Lock()
    plugin._league_registry = registry
    plugin._get_league_manager_for_mode = (
        lambda league_key, mode_type: managers_by_league.get(league_key)
    )
    return plugin


def game(home, away):
    return {"home_abbr": home, "away_abbr": away}


results = []


def check(name, passed):
    results.append((name, passed))
    print(f"{'PASS' if passed else 'FAIL'}: {name}")


# --- Case 1: two leagues, both with a favorite live game -------------------
registry = {
    "fifa.world": {"enabled": True},
    "usa.1": {"enabled": True},
}
managers = {
    "fifa.world": StubLiveManager([game("GER", "CUW")], ["USA", "GER"]),
    "usa.1": StubLiveManager([game("SEA", "LA")], ["SEA"]),
}
modes = make_plugin(registry, managers).get_live_modes()
check(
    "both live favorites -> both per-league modes",
    modes == ["soccer_fifa.world_live", "soccer_usa.1_live"],
)
check("never returns the generic soccer_live", "soccer_live" not in modes)

# --- Case 2: only one league has a live favorite ---------------------------
managers = {
    "fifa.world": StubLiveManager([game("GER", "CUW")], ["USA", "GER"]),
    "usa.1": StubLiveManager([], ["SEA"]),  # no live game
}
modes = make_plugin(registry, managers).get_live_modes()
check("only the league with a live game", modes == ["soccer_fifa.world_live"])

# --- Case 3: live game whose teams are not favorites is excluded -----------
managers = {
    "fifa.world": StubLiveManager([game("BRA", "ARG")], ["USA", "GER"]),
    "usa.1": StubLiveManager([], ["SEA"]),
}
modes = make_plugin(registry, managers).get_live_modes()
check("non-favorite live game excluded", modes == [])

# --- Case 4: show_all_live includes any live game --------------------------
managers = {
    "fifa.world": StubLiveManager([game("BRA", "ARG")], [], show_all_live=True),
    "usa.1": StubLiveManager([], ["SEA"]),
}
modes = make_plugin(registry, managers).get_live_modes()
check("show_all_live includes any live game", modes == ["soccer_fifa.world_live"])

# --- Case 5: disabled league excluded even with a live favorite ------------
registry_disabled = {
    "fifa.world": {"enabled": False},
    "usa.1": {"enabled": True},
}
managers = {
    "fifa.world": StubLiveManager([game("GER", "CUW")], ["GER"]),
    "usa.1": StubLiveManager([game("SEA", "LA")], ["SEA"]),
}
modes = make_plugin(registry_disabled, managers).get_live_modes()
check("disabled league excluded", modes == ["soccer_usa.1_live"])

# --- Case 6: returned modes match the host's registration scheme -----------
modes = make_plugin(registry, managers).get_live_modes()
check(
    "all modes are soccer_<league>_live",
    all(m.startswith("soccer_") and m.endswith("_live") for m in modes) and modes,
)

# =============================================================================
# exclude_teams / favorite_live_boost: _is_favorite_game(), _swrr_advance(),
# and _classify_live_game()
#
# These exercise the real SportsLive methods (not reimplementations) on a
# bare namespace object carrying just the attributes they read, so we don't
# need to build a full live manager (network fetch, ESPN payload shapes, etc).
# The live-inclusion filter (exclude > show_all_live > favorites-only) was
# extracted from inline code in SportsLive.update() into _classify_live_game()
# specifically so it could be unit-tested directly here, the same way
# _is_favorite_game/_swrr_advance already were.
# =============================================================================


class Games:
    """Bare namespace exposing only what _is_favorite_game/_swrr_advance read.

    Binds the real SportsLive._is_favorite_game as a method (rather than
    reimplementing it) since _swrr_advance calls self._is_favorite_game(g)
    internally.
    """

    _is_favorite_game = SportsLive._is_favorite_game

    def __init__(self, favorite_teams, boost, exclude_teams=None,
                 show_all_live=False, show_favorite_teams_only=False):
        self.favorite_teams = favorite_teams
        self.favorite_live_boost = boost
        self.exclude_teams = exclude_teams or []
        self.show_all_live = show_all_live
        self.show_favorite_teams_only = show_favorite_teams_only


def g(gid, home, away):
    return {"id": gid, "home_abbr": home, "away_abbr": away}


# --- _is_favorite_game --------------------------------------------------
fake = Games(favorite_teams=["LIV"], boost=2)
check(
    "_is_favorite_game: home match",
    SportsLive._is_favorite_game(fake, g("1", "LIV", "MUN")) is True,
)
check(
    "_is_favorite_game: away match",
    SportsLive._is_favorite_game(fake, g("1", "MUN", "LIV")) is True,
)
check(
    "_is_favorite_game: no match",
    SportsLive._is_favorite_game(fake, g("1", "MUN", "ARS")) is False,
)
fake_no_fav = Games(favorite_teams=[], boost=2)
check(
    "_is_favorite_game: no favorites configured -> never favorite",
    SportsLive._is_favorite_game(fake_no_fav, g("1", "LIV", "MUN")) is False,
)

# --- _swrr_advance: boost=1 reproduces plain round-robin order (regression) -
games3 = [g("LIV", "LIV", "X"), g("ARS", "ARS", "Y"), g("MUN", "MUN", "Z")]
fake = Games(favorite_teams=["LIV"], boost=1)
seq = [SportsLive._swrr_advance(fake, games3)["id"] for _ in range(9)]
check(
    "boost=1: identical to plain round robin through games in list order",
    seq == ["LIV", "ARS", "MUN"] * 3,
)

# --- _swrr_advance: favorite not live -> boost has no effect ---------------
fake = Games(favorite_teams=["NOTPLAYING"], boost=4)
seq = [SportsLive._swrr_advance(fake, games3)["id"] for _ in range(9)]
check(
    "favorite not among live games: boost has no effect, plain order",
    seq == ["LIV", "ARS", "MUN"] * 3,
)

# --- _swrr_advance: boost=2 gives the favorite exactly 2x the turns ---------
fake = Games(favorite_teams=["LIV"], boost=2)
seq = [SportsLive._swrr_advance(fake, games3)["id"] for _ in range(16)]
counts = {gid: seq.count(gid) for gid in ("LIV", "ARS", "MUN")}
check(
    "boost=2: favorite gets exactly 2x the turns of each other game",
    counts["LIV"] == 2 * counts["ARS"] == 2 * counts["MUN"] and counts["LIV"] == 8,
)
check(
    "boost=2: favorite never absent from a 16-pick sample",
    counts["LIV"] > 0,
)

# --- _swrr_advance: single game -> always that game -------------------------
fake = Games(favorite_teams=[], boost=3)
seq = [SportsLive._swrr_advance(fake, [g("ONLY", "A", "B")])["id"] for _ in range(4)]
check("single live game: always returned", seq == ["ONLY"] * 4)

# --- _swrr_advance: empty list -> None --------------------------------------
fake = Games(favorite_teams=["LIV"], boost=2)
check("no live games: returns None", SportsLive._swrr_advance(fake, []) is None)

# --- _classify_live_game: exclude wins over everything ----------------------
fake = Games(favorite_teams=[], boost=2, exclude_teams=["LIV"], show_all_live=True)
check(
    "_classify_live_game: excluded team hidden even with show_all_live=True",
    SportsLive._classify_live_game(fake, "LIV", "MUN") is False,
)

fake = Games(favorite_teams=["LIV"], boost=2, exclude_teams=["LIV"],
             show_favorite_teams_only=True)
check(
    "_classify_live_game: exclude wins over favorite_teams",
    SportsLive._classify_live_game(fake, "LIV", "MUN") is False,
)

# --- _classify_live_game: both filters off -> show everything not excluded --
fake = Games(favorite_teams=["LIV"], boost=2, show_favorite_teams_only=False,
             show_all_live=False)
check(
    "_classify_live_game: both filters off shows non-favorite live games",
    SportsLive._classify_live_game(fake, "ARS", "MUN") is True,
)

# --- _classify_live_game: favorites-only filters correctly ------------------
fake = Games(favorite_teams=["LIV"], boost=2, show_favorite_teams_only=True)
check(
    "_classify_live_game: favorites-only includes favorite's game",
    SportsLive._classify_live_game(fake, "LIV", "MUN") is True,
)
check(
    "_classify_live_game: favorites-only excludes non-favorite game",
    SportsLive._classify_live_game(fake, "ARS", "MUN") is False,
)


print()
passed = sum(1 for _, p in results if p)
print(f"{passed}/{len(results)} checks passed")
sys.exit(0 if passed == len(results) else 1)
