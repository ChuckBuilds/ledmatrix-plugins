#!/usr/bin/env python3
"""Regression test: empty switch-mode managers must not blank the panel.

Run standalone from the plugin directory:

    cd plugins/soccer-scoreboard
    python test/test_empty_mode_no_blank.py

Background
----------
In switch mode the plugin pools every enabled league's manager for a given mode
(e.g. ``soccer_usa.1_recent`` tries the recent managers of *all* enabled
leagues). A recent/upcoming manager with no games clears the shared canvas in
its ``display()`` (see ``SportsRecent.display`` / ``SportsUpcoming.display`` in
``sports.py``) and returns False. If that empty manager runs *before* the league
that actually has a game, it wipes the panel; the league with content then hits
its own redraw-dedup ("already showing this game") and returns True without
repainting — so the slot shows content briefly, then goes blank.

The fix gates recent/upcoming managers on having games before their ``display()``
is called, mirroring the live path. This test asserts an empty manager is never
asked to display, and that a mode with no games at all returns False so the
display controller skips it instead of holding a blank slot.
"""

from __future__ import annotations

import logging
import sys
import types
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
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


_install_host_stubs()
logging.basicConfig(level=logging.CRITICAL)

import manager  # noqa: E402


class FakeManager:
    """Stand-in for a recent/upcoming league manager.

    Mirrors the real contract: ``display()`` returns False when there are no
    games (after clearing the canvas), True when it has a game to draw.
    """

    def __init__(self, games):
        self.games_list = list(games)
        self.live_games = []
        self.display_calls = 0

    def display(self, force_clear=False):
        self.display_calls += 1
        return bool(self.games_list)


def _make_plugin(managers_by_league):
    plugin = manager.SoccerScoreboardPlugin.__new__(manager.SoccerScoreboardPlugin)
    plugin.is_enabled = True
    plugin.logger = logging.getLogger("test")
    plugin._should_use_scroll_mode = lambda mode_type: False
    plugin._get_enabled_leagues_for_mode = lambda mode_type: list(managers_by_league.keys())
    plugin._get_league_manager_for_mode = lambda key, mode_type: managers_by_league[key]
    plugin._record_dynamic_progress = lambda m: None
    plugin._evaluate_dynamic_cycle_completion = lambda: None
    plugin._current_display_league = None
    plugin._current_display_mode_type = None
    return plugin


def test_empty_manager_is_skipped() -> None:
    """An empty league manager must not have display() called (it would blank)."""
    empty = FakeManager([])                  # usa.1 recent — no favorite-team games
    populated = FakeManager([{"id": "g1"}])  # fifa.world recent — the USA game
    plugin = _make_plugin({"usa.1": empty, "fifa.world": populated})

    result = plugin.display("soccer_usa.1_recent")

    assert result is True, f"expected content to display, got {result!r}"
    assert empty.display_calls == 0, (
        "empty manager's display() was called — it clears the canvas and blanks "
        "the league that has content"
    )
    assert populated.display_calls == 1, "manager with the game should have displayed once"
    print("  [ok] empty manager skipped; populated manager drawn")


def test_all_empty_mode_returns_false() -> None:
    """A mode with no games anywhere must return False so the controller skips it."""
    a = FakeManager([])
    b = FakeManager([])
    plugin = _make_plugin({"usa.1": a, "fifa.world": b})

    result = plugin.display("soccer_usa.1_upcoming")

    assert result is False, (
        f"expected False so the display controller skips the slot, got {result!r}"
    )
    assert a.display_calls == 0 and b.display_calls == 0, "no empty manager should display"
    print("  [ok] all-empty mode returns False (controller skips, no blank hold)")


def main() -> int:
    tests = [test_empty_manager_is_skipped, test_all_empty_mode_returns_false]
    for t in tests:
        try:
            t()
        except AssertionError as e:
            print(f"  [FAIL] {t.__name__}: {e}")
            return 1
    print("All tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
