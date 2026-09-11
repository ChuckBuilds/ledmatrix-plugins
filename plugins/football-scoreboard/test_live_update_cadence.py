#!/usr/bin/env python3
"""get_update_interval() asks for a faster poll only while a game is live.

Reported by a user: "the football plugin with live games only updates the live
game in progress if I restart the display."

The data path was fine -- ESPN was being fetched with no cache and current_game
was refreshed in place. The problem was cadence. The manifest pins
update_interval to 60, that is the only number the core scheduler looked at, and
the plugin's own live_update_interval (15s default) could therefore never fire
more often than once a minute. Measured on a live rig during the fourth quarter
of the game in the report:

    23:21:49  23:22:50  23:23:50  23:24:50  23:25:50    <- exactly 60s apart

A clock and score up to a minute stale during a two-minute drill reads as a
frozen panel.

Core now consults get_update_interval() per tick (LEDMatrix#...); this is the
plugin half. The risk to guard against is the opposite of the bug: asking for a
15-second poll when nothing is live would hammer ESPN year-round.

Run: <core-venv>/bin/python plugins/football-scoreboard/test_live_update_cadence.py
"""

import os
import sys

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

from manager import FootballScoreboardPlugin  # noqa: E402

FAILURES = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILURES.append(label)


class _LiveManager:
    """Stands in for NFLLiveManager/NCAAFBLiveManager."""

    def __init__(self, live_games=(), update_interval=15):
        self.live_games = list(live_games)
        self.update_interval = update_interval


class _Stub:
    """Carries only what get_update_interval() reads."""

    get_update_interval = FootballScoreboardPlugin.get_update_interval

    def __init__(self, nfl=None, ncaa=None, enabled=True,
                 nfl_enabled=True, ncaa_fb_enabled=True):
        self.is_enabled = enabled
        self.nfl_enabled = nfl_enabled
        self.ncaa_fb_enabled = ncaa_fb_enabled
        self.nfl_live = nfl
        self.ncaa_fb_live = ncaa


GAME = {"id": "401872656", "away_abbr": "NE", "home_abbr": "SEA"}


print("nothing live -> no opinion, so the manifest's 60s stands")
check("no live games anywhere",
      _Stub(nfl=_LiveManager(), ncaa=_LiveManager()).get_update_interval() is None)
check("managers not built yet",
      _Stub(nfl=None, ncaa=None).get_update_interval() is None)
check("plugin disabled",
      _Stub(nfl=_LiveManager([GAME]), enabled=False).get_update_interval() is None)

# The regression that would be worse than the bug: polling ESPN every 15s in
# July because a stale manager object still has an update_interval attribute.
check("a league with an interval but no games does not speed anything up",
      _Stub(nfl=_LiveManager(live_games=[], update_interval=15)).get_update_interval() is None)


print("\na game in progress -> ask for the live interval")
check("nfl live", _Stub(nfl=_LiveManager([GAME]), ncaa=_LiveManager()).get_update_interval() == 15)
check("ncaa live", _Stub(nfl=_LiveManager(), ncaa=_LiveManager([GAME])).get_update_interval() == 15)
check("a configured non-default interval is honoured",
      _Stub(nfl=_LiveManager([GAME], update_interval=30)).get_update_interval() == 30)


print("\nboth leagues live -> the faster of the two wins")
check("nfl 15 / ncaa 30 -> 15",
      _Stub(nfl=_LiveManager([GAME], 15), ncaa=_LiveManager([GAME], 30)).get_update_interval() == 15)
check("nfl 30 / ncaa 10 -> 10",
      _Stub(nfl=_LiveManager([GAME], 30), ncaa=_LiveManager([GAME], 10)).get_update_interval() == 10)


print("\na disabled league is not consulted")
check("ncaa live but disabled",
      _Stub(nfl=_LiveManager(), ncaa=_LiveManager([GAME]),
            ncaa_fb_enabled=False).get_update_interval() is None)
check("nfl live but disabled",
      _Stub(nfl=_LiveManager([GAME]), ncaa=_LiveManager(),
            nfl_enabled=False).get_update_interval() is None)


print("\nit stays cheap -- the scheduler calls this on every tick")


class _Counting(_LiveManager):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.reads = 0

    def __getattribute__(self, name):
        if name == "live_games":
            object.__setattr__(self, "reads", object.__getattribute__(self, "reads") + 1)
        return object.__getattribute__(self, name)


counting = _Counting([GAME])
_Stub(nfl=counting, ncaa=_LiveManager()).get_update_interval()
check("live_games is read once per league, not walked", counting.reads == 1,
      f"{counting.reads} reads")


class _Exploding:
    """has_live_content() walks games and applies favourite filtering; calling it
    from here would put that on every scheduling tick."""

    live_games = [GAME]
    update_interval = 15

    def has_live_content(self):
        raise AssertionError("get_update_interval() must not call has_live_content()")


check("has_live_content() is not called",
      _Stub(nfl=_Exploding(), ncaa=_LiveManager()).get_update_interval() == 15)


print("\n" + "=" * 60)
if FAILURES:
    print(f"{len(FAILURES)} check(s) failed: {FAILURES}")
    sys.exit(1)
print("All checks passed.")
