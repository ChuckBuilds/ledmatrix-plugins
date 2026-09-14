#!/usr/bin/env python3
"""ncaa_fb_* modes must take NCAA FB's own mode duration.

_get_effective_mode_duration split display_mode on the first "_", so
"ncaa_fb_recent" became league "ncaa", which is not a league. League stayed
None and NCAA FB silently took the combined-mode duration -- the larger of the
two leagues' settings -- instead of its own. get_cycle_duration was fixed the
same way in 7c6281d; this method was missed.
"""
import logging
import sys
from pathlib import Path
from unittest.mock import Mock

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))
sys.path.insert(0, str(plugin_dir.parent.parent))

logging.basicConfig(level=logging.CRITICAL)


def _display_manager():
    dm = Mock()
    dm.display_width = dm.width = 128
    dm.display_height = dm.height = 32
    matrix = Mock()
    matrix.width, matrix.height = 128, 32
    dm.matrix = matrix
    return dm


def _league(recent_mode_duration):
    return {
        "enabled": True,
        "favorite_teams": [],
        "display_modes": {"show_live": True, "show_recent": True,
                          "show_upcoming": True},
        "mode_durations": {"recent_mode_duration": recent_mode_duration},
    }


def main():
    try:
        from manager import FootballScoreboardPlugin
    except ImportError as exc:
        print("SKIP: cannot import the plugin (%s)" % exc)
        return 2

    pm = Mock()
    pm.get_plugin = Mock(return_value=None)
    plugin = FootballScoreboardPlugin(
        plugin_id="football-scoreboard",
        config={"enabled": True, "timezone": "UTC",
                "nfl": _league(77), "ncaa_fb": _league(33)},
        display_manager=_display_manager(),
        cache_manager=Mock(),
        plugin_manager=pm,
    )
    plugin.supports_dynamic_duration = lambda: False

    failures = 0
    for mode, want in (("nfl_recent", 77.0), ("ncaa_fb_recent", 33.0)):
        got = plugin._get_effective_mode_duration(mode, "recent")
        ok = got == want
        failures += not ok
        print("  [%s] %s -> %r (want %r)" % ("pass" if ok else "FAIL", mode, got, want))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
