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


_stub_core_src()

from manager import SoccerScoreboardPlugin  # noqa: E402


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

print()
passed = sum(1 for _, p in results if p)
print(f"{passed}/{len(results)} checks passed")
sys.exit(0 if passed == len(results) else 1)
