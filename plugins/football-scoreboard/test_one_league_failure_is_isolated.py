#!/usr/bin/env python3
"""One league failing to initialise must not take the other league down.

_initialize_managers built NFL and NCAA FB inside a single try, so an NFL
manager raising in its constructor skipped NCAA FB entirely and the plugin
showed nothing. Each league is now built on its own; the failed one is left
as None, which the update and display paths skip.
"""
import logging
import sys
from pathlib import Path
from unittest.mock import Mock, patch

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))
sys.path.insert(0, str(plugin_dir.parent.parent))

logging.disable(logging.CRITICAL)


def _display_manager():
    dm = Mock()
    dm.display_width = dm.width = 128
    dm.display_height = dm.height = 32
    matrix = Mock()
    matrix.width, matrix.height = 128, 32
    dm.matrix = matrix
    return dm


def _league():
    return {"enabled": True, "favorite_teams": [],
            "display_modes": {"show_live": True, "show_recent": True,
                              "show_upcoming": True}}


class _Boom:
    def __init__(self, *a, **k):
        raise RuntimeError("NFL manager exploded")


def main():
    try:
        import manager
    except ImportError as exc:
        print("SKIP: cannot import the plugin (%s)" % exc)
        return 2

    pm = Mock()
    pm.get_plugin = Mock(return_value=None)
    with patch.object(manager, "NFLRecentManager", _Boom):
        plugin = manager.FootballScoreboardPlugin(
            plugin_id="football-scoreboard",
            config={"enabled": True, "timezone": "UTC",
                    "nfl": _league(), "ncaa_fb": _league()},
            display_manager=_display_manager(),
            cache_manager=Mock(),
            plugin_manager=pm,
        )

    failures = 0
    for league, want_built in (("ncaa_fb", True), ("nfl", False)):
        for mode in ("live", "recent", "upcoming"):
            value = getattr(plugin, "%s_%s" % (league, mode), "missing")
            ok = (value is not None and value != "missing") if want_built else value is None
            failures += not ok
            print("  [%s] %s_%s %s" % ("pass" if ok else "FAIL", league, mode,
                                       "built" if want_built else "left as None"))

    # The update loop has to step over the None managers and still reach
    # the league that did initialise.
    calls = []
    for mode in ("live", "recent", "upcoming"):
        setattr(plugin, "ncaa_fb_%s" % mode,
                Mock(update=Mock(side_effect=lambda m=mode: calls.append(m))))
    plugin._check_favorite_teams = lambda *a, **k: None
    try:
        plugin.update()
        ok = sorted(calls) == ["live", "recent", "upcoming"]
    except Exception as exc:  # noqa: BLE001
        ok = False
        calls.append(repr(exc))
    failures += not ok
    print("  [%s] update() skips the failed league and updates the other (%s)"
          % ("pass" if ok else "FAIL", calls))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
