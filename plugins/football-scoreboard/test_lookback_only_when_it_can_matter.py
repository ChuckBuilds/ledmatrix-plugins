#!/usr/bin/env python3
"""
Tests that the live fetch stops asking ESPN for yesterday once yesterday is over.

The live poll asked for a two-day window so a game that started yesterday and
is still running would not be lost. ESPN rejects date *ranges*, so that window
is split into one request per day and every live poll costs two requests
instead of one. Measured on 2026-09-19: of 7,226 chunked requests on one rig,
1,858 were for yesterday's date -- which, after breakfast, holds nothing but
final games.

_needs_previous_day keeps the lookback only while it can still pay for itself:

  * early in the Eastern day, when last night's game could still be running;
  * at any hour, if a game we are actually tracking started yesterday.

These checks pin both, and that nothing else keeps it alive.

Run: <core-venv>/bin/python plugins/football-scoreboard/test_lookback_only_when_it_can_matter.py
"""

# A test harness: it reaches into protected members on purpose, builds a
# concrete subclass at runtime, and accepts arguments only to match the
# signatures it stands in for -- none of which pylint can see as intentional.
# pylint: disable=protected-access,abstract-class-instantiated,unused-argument
# pylint: disable=broad-exception-caught

import sys
from datetime import datetime, timedelta
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

import pytz  # noqa: E402
import sports  # noqa: E402

EASTERN = pytz.timezone("America/New_York")


class _Stub:
    _LOOKBACK_CUTOFF_HOUR = sports.SportsCore._LOOKBACK_CUTOFF_HOUR
    _needs_previous_day = sports.SportsCore._needs_previous_day

    def __init__(self, live_games=None):
        if live_games is not None:
            self.live_games = live_games


def _eastern(hour, minute=0):
    base = datetime(2026, 9, 20, hour, minute)
    return EASTERN.localize(base)


failures = []


def check(label, ok):
    print(("  PASS  " if ok else "  FAIL  ") + label)
    if not ok:
        failures.append(label)


def main():
    print("the hour of the Eastern day decides it when nothing is tracked")
    stub = _Stub(live_games=[])
    check("just after midnight, last night's game could still be running",
          stub._needs_previous_day(_eastern(0, 30)))
    check("at 5am it is still asked for",
          stub._needs_previous_day(_eastern(5, 59)))
    check("at 6am it is not", not stub._needs_previous_day(_eastern(6, 0)))
    check("nor at midday", not stub._needs_previous_day(_eastern(12, 0)))
    check("nor during the evening slate",
          not stub._needs_previous_day(_eastern(20, 0)))

    print("\na tracked game that started yesterday keeps its own day")
    now = _eastern(13, 0)
    started_yesterday = now - timedelta(hours=16)
    stub = _Stub(live_games=[{"id": "a", "start_time_utc": started_yesterday}])
    check("the lookback survives past the cutoff for it",
          stub._needs_previous_day(now))

    print("\na game that started today does not")
    stub = _Stub(live_games=[{"id": "a", "start_time_utc": now - timedelta(hours=2)}])
    check("today's game needs only today", not stub._needs_previous_day(now))

    print("\nmixed lists are decided by whether any game is from yesterday")
    stub = _Stub(live_games=[
        {"id": "a", "start_time_utc": now - timedelta(hours=2)},
        {"id": "b", "start_time_utc": started_yesterday},
    ])
    check("one straggler is enough", stub._needs_previous_day(now))

    print("\nnothing else keeps the lookback alive")
    check("an empty live list does not", not _Stub(live_games=[])._needs_previous_day(now))
    check("a host with no live_games attribute does not",
          not _Stub()._needs_previous_day(now))

    print("\njunk in the game list is ignored, not raised")
    stub = _Stub(live_games=[
        {}, {"start_time_utc": None}, {"start_time_utc": "2026-09-19"},
        {"start_time_utc": object()}, "not-a-dict", None,
    ])
    raised = None
    try:
        result = stub._needs_previous_day(now)
    except Exception as exc:                       # noqa: BLE001
        raised = exc
        result = None
    check("no exception escapes", raised is None)
    check("and junk alone does not justify the lookback", result is False)

    print("\nthe cutoff is a real hour of the day, not a placeholder")
    check("0 < cutoff < 12", 0 < _Stub._LOOKBACK_CUTOFF_HOUR < 12)

    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
