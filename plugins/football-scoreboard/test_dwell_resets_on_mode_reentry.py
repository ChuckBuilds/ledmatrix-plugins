#!/usr/bin/env python3
"""
Tests that a mode retaking the panel gives its current card a full turn.

The dwell clock (last_game_switch) keeps running while a mode is off
screen, so on re-entry it was always long expired and the first display()
call advanced immediately: the card cut off by the end of the previous
block was skipped instead of shown -- measured live at one in five card
transitions on a 30s block of 15s cards -- and after a service restart the
clock started at manager construction, seconds before the first frame,
producing a 9s card and a 5s card in the first block. _reset_dwell_on_
reentry treats any multi-second gap between display() calls as a block
boundary and restarts the dwell clock for the current card.

These checks pin:

  * the very first display() call after startup resets the clock;
  * calls inside one on-screen stint (sub-second apart) do not;
  * a call after a long away gap does;
  * the live screen's last_game_switch == 0 sentinel is left alone.

Exercised against a stand-in ``self``, same as the other timing tests:
no display hardware, no network.

Run: <core-venv>/bin/python plugins/football-scoreboard/test_dwell_resets_on_mode_reentry.py
"""

import sys
import time
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

import sports  # noqa: E402


class _Manager:
    _reset_dwell_on_reentry = sports.SportsCore._reset_dwell_on_reentry
    _DWELL_REENTRY_GAP_SECONDS = sports.SportsCore._DWELL_REENTRY_GAP_SECONDS

    def __init__(self, last_game_switch):
        self._last_display_call_monotonic = 0.0
        self.last_game_switch = last_game_switch


failures = []


def check(name, ok, detail=None):
    if ok:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s%s" % (name, " -- %r" % (detail,) if detail is not None else ""))
        failures.append(name)


def main():
    print("first frame after startup: the clock had a construction-time value")
    mgr = _Manager(last_game_switch=time.time() - 6.0)  # set ~6s before first frame
    before = mgr.last_game_switch
    check("the first display() call resets the dwell",
          mgr._reset_dwell_on_reentry() is True)
    check("the clock now reads (roughly) now",
          time.time() - mgr.last_game_switch < 1.0, mgr.last_game_switch - before)

    print("\nframes inside one on-screen stint leave the clock alone")
    stamp = mgr.last_game_switch
    changed = [mgr._reset_dwell_on_reentry() for _ in range(3)]
    check("sub-second follow-up calls do not reset", changed == [False] * 3, changed)
    check("the clock is untouched", mgr.last_game_switch == stamp)

    print("\nreturning after other modes' blocks resets again")
    mgr.last_game_switch = time.time() - 150.0          # dwell long expired
    mgr._last_display_call_monotonic = time.monotonic() - 150.0  # mode was away
    check("the re-entry call resets instead of letting the dwell check advance",
          mgr._reset_dwell_on_reentry() is True)
    check("the dwell no longer reads as expired",
          time.time() - mgr.last_game_switch < 1.0)

    print("\na gap just under the threshold is still the same stint")
    mgr._last_display_call_monotonic = time.monotonic() - (
        _Manager._DWELL_REENTRY_GAP_SECONDS - 1.0)
    stamp = mgr.last_game_switch
    check("no reset", mgr._reset_dwell_on_reentry() is False)
    check("clock untouched", mgr.last_game_switch == stamp)

    print("\nthe live screen's zero sentinel is not overwritten")
    mgr = _Manager(last_game_switch=0)
    check("no reset while no game has been shown yet",
          mgr._reset_dwell_on_reentry() is False)
    check("the sentinel survives", mgr.last_game_switch == 0)

    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
