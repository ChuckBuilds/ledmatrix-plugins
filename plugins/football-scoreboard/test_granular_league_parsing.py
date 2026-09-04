#!/usr/bin/env python3
"""A granular mode must resolve to its own league, including ncaa_fb.

get_cycle_duration() extracted the league with display_mode.split("_", 1),
which turns "ncaa_fb_recent" into ("ncaa", "fb_recent"). "ncaa" is not in the
league registry, so league stayed None and the per-league scroll check fell
back to the any-enabled-league one -- handing NCAA FB a scroll duration on the
strength of NFL being set to scroll.

The bug only showed for the league whose id contains an underscore, so nfl_*
behaved correctly throughout and none of the plugin's other tests noticed.
"""
import logging
import sys
from pathlib import Path
from unittest.mock import Mock

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))
sys.path.insert(0, str(plugin_dir.parent.parent))

logging.basicConfig(level=logging.CRITICAL)

SCROLL_SENTINEL = 987.0


def _display_manager():
    dm = Mock()
    dm.display_width = dm.width = 128
    dm.display_height = dm.height = 32
    matrix = Mock()
    matrix.width, matrix.height = 128, 32
    dm.matrix = matrix
    for name in ("clear", "set_image", "show"):
        setattr(dm, name, Mock())
    return dm


def _config(nfl_mode, ncaa_mode):
    def league(mode):
        return {
            "enabled": True,
            "favorite_teams": [],
            "display_modes": {
                "show_live": True, "show_recent": True, "show_upcoming": True,
                "live_display_mode": mode,
                "recent_display_mode": mode,
                "upcoming_display_mode": mode,
            },
        }
    return {
        "enabled": True, "display_duration": 15, "game_display_duration": 5,
        "timezone": "UTC", "nfl": league(nfl_mode), "ncaa_fb": league(ncaa_mode),
    }


def _plugin(nfl_mode, ncaa_mode):
    from manager import FootballScoreboardPlugin

    pm = Mock()
    pm.get_plugin = Mock(return_value=None)
    plugin = FootballScoreboardPlugin(
        plugin_id="football-scoreboard",
        config=_config(nfl_mode, ncaa_mode),
        display_manager=_display_manager(),
        cache_manager=Mock(),
        plugin_manager=pm,
    )
    # A scroll duration that is unmistakable if the scroll branch is taken.
    scroll = Mock()
    scroll.get_dynamic_duration = Mock(return_value=SCROLL_SENTINEL)
    plugin._scroll_manager = scroll
    return plugin


def test_per_league_scroll_duration():
    """nfl=scroll, ncaa_fb=switch: only nfl_* may take the scroll duration."""
    plugin = _plugin(nfl_mode="scroll", ncaa_mode="switch")

    nfl = plugin.get_cycle_duration("nfl_recent")
    ncaa = plugin.get_cycle_duration("ncaa_fb_recent")

    ok = True
    if nfl != SCROLL_SENTINEL:
        print(f"[FAIL] nfl_recent is set to scroll but got {nfl}, "
              f"expected {SCROLL_SENTINEL}")
        ok = False
    if ncaa == SCROLL_SENTINEL:
        print("[FAIL] ncaa_fb_recent is set to switch but received the scroll "
              "duration -- the league did not resolve (split('_', 1) bug)")
        ok = False
    if ok:
        print("[OK] nfl_recent scrolls, ncaa_fb_recent does not")
    return ok


def test_reversed():
    """The mirror case: ncaa_fb=scroll, nfl=switch."""
    plugin = _plugin(nfl_mode="switch", ncaa_mode="scroll")

    nfl = plugin.get_cycle_duration("nfl_recent")
    ncaa = plugin.get_cycle_duration("ncaa_fb_recent")

    ok = True
    if ncaa != SCROLL_SENTINEL:
        print(f"[FAIL] ncaa_fb_recent is set to scroll but got {ncaa}, "
              f"expected {SCROLL_SENTINEL}")
        ok = False
    if nfl == SCROLL_SENTINEL:
        print("[FAIL] nfl_recent is set to switch but received the scroll duration")
        ok = False
    if ok:
        print("[OK] ncaa_fb_recent scrolls, nfl_recent does not")
    return ok


def main():
    results = [
        ("per-league scroll duration", test_per_league_scroll_duration()),
        ("reversed", test_reversed()),
    ]
    failed = [name for name, ok in results if not ok]
    if failed:
        print(f"\n[FAIL] {', '.join(failed)}")
        return 1
    print("\nAll checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
