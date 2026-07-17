#!/usr/bin/env python3
"""Smoke tests for the AFL scoreboard plugin.

Runs standalone from the plugin directory (no LEDMatrix host required):

    cd plugins/afl-scoreboard
    python test_afl_plugin.py

Covers:
- The plugin class and its three display modes are exposed as expected.
- The plugin instantiates with stubbed managers and routes ``display()`` to the
  right manager per mode (empty managers are skipped so the panel never blanks).
- ``get_live_modes`` / ``has_live_content`` reflect live favorite-team games.
- The AFL quarter ``period_text`` mapping (the sport-specific parsing logic).
"""

from __future__ import annotations

import logging
import sys
import types
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))


def _install_thirdparty_stubs() -> None:
    """Stub heavy third-party deps so the plugin imports without them installed.

    ``setdefault`` means real packages (e.g. in CI) are used when present; the
    stubs only kick in on a bare interpreter. The tests use ``__new__`` to skip
    ``__init__``, so none of these are actually exercised at runtime.
    """
    def _mod(name, **attrs):
        m = sys.modules.get(name)
        if m is None:
            m = types.ModuleType(name)
            sys.modules[name] = m
        for k, v in attrs.items():
            if not hasattr(m, k):
                setattr(m, k, v)
        return m

    class _Any:
        def __init__(self, *a, **k):
            pass

        def __getattr__(self, _):
            return _Any()

        def __call__(self, *a, **k):
            return _Any()

    _mod("pytz", utc=_Any(), timezone=lambda *a, **k: _Any())
    _mod("requests", Session=_Any, get=lambda *a, **k: _Any(), exceptions=_Any())
    _mod("requests.adapters", HTTPAdapter=_Any)
    _mod("urllib3")
    _mod("urllib3.util")
    _mod("urllib3.util.retry", Retry=_Any)
    _mod("PIL", Image=_Any(), ImageDraw=_Any(), ImageFont=_Any(), ImageOps=_Any())
    _mod("PIL.Image", Resampling=_Any(), new=lambda *a, **k: _Any(), open=lambda *a, **k: _Any())
    _mod("PIL.ImageDraw", Draw=lambda *a, **k: _Any())
    _mod("PIL.ImageFont")


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


_install_thirdparty_stubs()
_install_host_stubs()
logging.basicConfig(level=logging.CRITICAL)

import manager  # noqa: E402


class FakeManager:
    """Stand-in for a Live/Recent/Upcoming manager."""

    def __init__(self, games=None, live_games=None, favorite_teams=None):
        self.games_list = list(games or [])
        self.live_games = list(live_games or [])
        self.favorite_teams = list(favorite_teams or [])
        self.show_all_live = False
        self.display_calls = 0

    def display(self, force_clear=False):
        self.display_calls += 1
        if self.live_games:
            return True
        return bool(self.games_list)

    def has_active_celebration(self):
        return False


def _make_plugin(live=None, recent=None, upcoming=None):
    plugin = manager.AflScoreboardPlugin.__new__(manager.AflScoreboardPlugin)
    plugin.is_enabled = True
    plugin.logger = logging.getLogger("test")
    plugin.live_priority = False
    plugin.config = {}
    plugin.display_duration = 15.0
    plugin.last_mode_switch = 0
    plugin.current_mode_index = 0
    plugin.modes = list(manager.DISPLAY_MODES)
    plugin._scroll_manager = None
    plugin._display_mode_settings = {"live": "switch", "recent": "switch", "upcoming": "switch"}
    plugin._dynamic_cycle_seen_modes = set()
    plugin._dynamic_mode_to_manager_key = {}
    plugin._dynamic_manager_progress = {}
    plugin._dynamic_managers_completed = set()
    plugin._dynamic_cycle_complete = False
    plugin._current_display_league = "afl"
    plugin._current_display_mode_type = None
    import threading
    plugin._config_lock = threading.Lock()
    plugin._managers = {
        "live": live or FakeManager(),
        "recent": recent or FakeManager(),
        "upcoming": upcoming or FakeManager(),
    }
    return plugin


def test_display_modes_exposed() -> None:
    assert manager.DISPLAY_MODES == ("afl_live", "afl_recent", "afl_upcoming"), manager.DISPLAY_MODES
    assert manager._mode_type_of("afl_recent") == "recent"
    assert manager._mode_type_of("afl_live") == "live"
    assert manager._mode_type_of("bogus") is None
    print("  [ok] display modes exposed: afl_live/afl_recent/afl_upcoming")


def test_populated_recent_displays() -> None:
    recent = FakeManager(games=[{"id": "g1"}])
    plugin = _make_plugin(recent=recent)
    result = plugin.display("afl_recent")
    assert result is True, f"expected content, got {result!r}"
    assert recent.display_calls == 1
    print("  [ok] afl_recent with a game displays")


def test_empty_recent_skipped() -> None:
    recent = FakeManager(games=[])
    plugin = _make_plugin(recent=recent)
    result = plugin.display("afl_recent")
    assert result is False, f"expected False so controller skips, got {result!r}"
    assert recent.display_calls == 0, "empty manager must not be asked to display (it blanks)"
    print("  [ok] empty afl_recent returns False, manager not drawn")


def test_live_modes_and_content() -> None:
    live = FakeManager(
        live_games=[{"home_abbr": "COLL", "away_abbr": "GEEL"}],
        favorite_teams=["COLL"],
    )
    plugin = _make_plugin(live=live)
    assert plugin.has_live_content() is True
    assert plugin.get_live_modes() == ["afl_live"], plugin.get_live_modes()

    # No favorite in the live game -> no live content
    live2 = FakeManager(
        live_games=[{"home_abbr": "SYD", "away_abbr": "HAW"}],
        favorite_teams=["COLL"],
    )
    plugin2 = _make_plugin(live=live2)
    assert plugin2.has_live_content() is False
    assert plugin2.get_live_modes() == []
    print("  [ok] live content / get_live_modes track favorite live games")


def test_period_text_mapping() -> None:
    """AFL quarters map to Q1..Q4 + HALF/Final/pre-game time."""
    import afl_managers

    mgr = afl_managers.BaseAflManager.__new__(afl_managers.BaseAflManager)
    mgr.logger = logging.getLogger("test")
    mgr.league_key = "afl"

    def common_stub(event):
        details = {
            "id": event["id"],
            "home_abbr": "COLL",
            "away_abbr": "GEEL",
            "game_time": event.get("_game_time", ""),
            "is_live": False,
            "is_final": False,
            "is_upcoming": False,
        }
        status = event["status"]
        return details, {"a": 1}, {"a": 1}, status, None

    mgr._extract_game_details_common = common_stub

    def pt(state, name, period, clock="", game_time=""):
        ev = {
            "id": "x",
            "_game_time": game_time,
            "status": {"period": period, "displayClock": clock,
                       "type": {"state": state, "name": name}},
        }
        return mgr._extract_game_details(ev)["period_text"]

    assert pt("in", "STATUS_IN_PROGRESS", 1, "18:20") == "Q1 18:20"
    assert pt("in", "STATUS_IN_PROGRESS", 3, "05:00") == "Q3 05:00"
    assert pt("in", "STATUS_IN_PROGRESS", 4, "00:30") == "Q4 00:30"
    assert pt("halftime", "STATUS_HALFTIME", 2) == "HALF"
    # ESPN can report halftime as state="in" + name="STATUS_HALFTIME" (not
    # state="halftime") with a non-empty displayClock -- this must not
    # corrupt "HALF" into "HALF <clock>" (regression: the clock-append
    # branch used to key only on status_state == "in", which is also true
    # during this form of halftime).
    assert pt("in", "STATUS_HALFTIME", 2, "0:00") == "HALF"
    assert pt("post", "STATUS_FINAL", 4) == "Final"
    assert pt("pre", "STATUS_SCHEDULED", 0, game_time="Sat 7:40 PM") == "Sat 7:40 PM"
    print("  [ok] AFL quarter period_text mapping (Q1-Q4 / HALF / Final / pre-game)")


def main() -> int:
    tests = [
        test_display_modes_exposed,
        test_populated_recent_displays,
        test_empty_recent_skipped,
        test_live_modes_and_content,
        test_period_text_mapping,
    ]
    for t in tests:
        try:
            t()
        except AssertionError as e:
            print(f"  [FAIL] {t.__name__}: {e}")
            return 1
        except Exception as e:  # noqa: BLE001
            print(f"  [ERROR] {t.__name__}: {e}")
            return 1
    print("All AFL plugin tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
