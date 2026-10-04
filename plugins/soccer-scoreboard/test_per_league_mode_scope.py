#!/usr/bin/env python3
"""Regression test: a per-league mode shows only that league's games.

Soccer registers one set of modes per league (``soccer_eng.1_recent``,
``soccer_esp.1_recent``, ...). In switch mode, ``display()`` parsed the league
out of the mode name and then ignored it: it tried every enabled league's
manager for the mode type and drew the first one with games. So
``soccer_esp.1_recent`` showed the eng.1 card whenever La Liga had nothing (or
ranked below the Premier League), and every league's slot repeated one game.

Expected: only the named league is consulted. If it has nothing to show,
``display()`` returns False so the core's empty-mode handling moves on.

Run standalone from the plugin directory:

    cd plugins/soccer-scoreboard
    python test_per_league_mode_scope.py
"""

from __future__ import annotations

import logging
import os
import sys
import types
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))


def _install_host_stubs() -> None:
    for name in (
        "src",
        "src.plugin_system",
        "src.plugin_system.base_plugin",
        "src.background_data_service",
        "src.common",
        "src.common.scroll_helper",
        "src.logo_downloader",
    ):
        sys.modules.setdefault(name, types.ModuleType(name))
    sys.modules["src.plugin_system.base_plugin"].BasePlugin = object
    sys.modules["src.plugin_system.base_plugin"].VegasDisplayMode = None
    sys.modules["src.background_data_service"].get_background_service = lambda *a, **k: None
    sys.modules["src.common.scroll_helper"].ScrollHelper = None
    sys.modules["src.logo_downloader"].LogoDownloader = object
    sys.modules["src.logo_downloader"].download_missing_logo = lambda *a, **k: None

    # Plain ModuleType stubs are not packages; give them a __path__ so genuine
    # core submodules (sports_shared, sports_card, ...) resolve from a core
    # checkout while the stubbed ones stay stubbed.
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


_install_host_stubs()
logging.basicConfig(level=logging.CRITICAL)

import manager  # noqa: E402


class FakeManager:
    """A league's recent/upcoming/live manager: True when it has a game."""

    def __init__(self, name, games):
        self.name = name
        self.games_list = list(games)
        self.live_games = list(games)
        self.display_calls = 0

    def display(self, force_clear=False):
        self.display_calls += 1
        return bool(self.games_list)


def _make_plugin(managers_by_league, enabled=None):
    """A plugin wired to fake managers, in switch mode, with no celebration.

    ``enabled`` is what _get_enabled_leagues_for_mode returns, in priority
    order; it defaults to every league given.
    """
    enabled = list(managers_by_league) if enabled is None else list(enabled)
    plugin = manager.SoccerScoreboardPlugin.__new__(manager.SoccerScoreboardPlugin)
    plugin.is_enabled = True
    plugin.logger = logging.getLogger("test")
    plugin._should_use_scroll_mode = lambda mode_type: False
    plugin._get_active_celebration_manager = lambda: None
    plugin._refresh_switch_mode_managers = lambda mode_type: None
    plugin._get_enabled_leagues_for_mode = lambda mode_type: list(enabled)
    plugin._get_league_manager_for_mode = (
        lambda key, mode_type: managers_by_league.get(key))
    plugin._record_dynamic_progress = lambda m: None
    plugin._evaluate_dynamic_cycle_completion = lambda: None
    plugin._current_display_league = None
    plugin._current_display_mode_type = None
    return plugin


def test_league_mode_does_not_show_another_league() -> None:
    """soccer_esp.1_* with an empty La Liga must not draw the eng.1 card."""
    eng = FakeManager("eng.1", [{"id": "ars-che"}])
    esp = FakeManager("esp.1", [])
    plugin = _make_plugin({"eng.1": eng, "esp.1": esp})

    for mode_type in ("recent", "upcoming", "live"):
        result = plugin.display(f"soccer_esp.1_{mode_type}")
        assert result is False, (
            f"soccer_esp.1_{mode_type}: La Liga has nothing, expected False so "
            f"the core moves on, got {result!r}"
        )
    assert eng.display_calls == 0, (
        f"the eng.1 manager was drawn {eng.display_calls} time(s) in the esp.1 "
        "slot -- a per-league mode fell through to another league"
    )
    assert esp.display_calls == 0, "an empty manager must not be asked to draw"
    print("  [ok] empty esp.1 slot returns False without drawing eng.1")


def test_league_mode_draws_its_own_league_not_a_higher_priority_one() -> None:
    """Both leagues have games: each slot draws its own, not the top-priority one."""
    eng = FakeManager("eng.1", [{"id": "ars-che"}])
    esp = FakeManager("esp.1", [{"id": "rma-bar"}])
    plugin = _make_plugin({"eng.1": eng, "esp.1": esp})

    assert plugin.display("soccer_esp.1_recent") is True
    assert (esp.display_calls, eng.display_calls) == (1, 0), (
        f"esp.1 slot drew esp={esp.display_calls} eng={eng.display_calls}"
    )
    assert plugin._current_display_league == "esp.1"

    assert plugin.display("soccer_eng.1_recent") is True
    assert (esp.display_calls, eng.display_calls) == (1, 1)
    assert plugin._current_display_league == "eng.1"
    print("  [ok] each league's slot draws its own league")


def test_custom_league_key_with_underscores() -> None:
    """A custom league code containing underscores is still matched exactly."""
    eng = FakeManager("eng.1", [{"id": "ars-che"}])
    custom = FakeManager("my_cup", [{"id": "x"}])
    plugin = _make_plugin({"eng.1": eng, "my_cup": custom})

    assert plugin.display("soccer_my_cup_recent") is True
    assert (custom.display_calls, eng.display_calls) == (1, 0)
    print("  [ok] custom league with underscores routes to itself")


def test_disabled_league_mode_returns_false() -> None:
    """A league (or its mode) switched off shows nothing, even with games."""
    eng = FakeManager("eng.1", [{"id": "ars-che"}])
    esp = FakeManager("esp.1", [{"id": "rma-bar"}])
    plugin = _make_plugin({"eng.1": eng, "esp.1": esp}, enabled=["eng.1"])

    assert plugin.display("soccer_esp.1_recent") is False
    assert (esp.display_calls, eng.display_calls) == (0, 0)
    print("  [ok] disabled league's mode returns False")


def main() -> int:
    tests = [
        test_league_mode_does_not_show_another_league,
        test_league_mode_draws_its_own_league_not_a_higher_priority_one,
        test_custom_league_key_with_underscores,
        test_disabled_league_mode_returns_false,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            print(f"  [FAIL] {t.__name__}: {e}")
            failed += 1
    if failed:
        return 1
    print("All tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
