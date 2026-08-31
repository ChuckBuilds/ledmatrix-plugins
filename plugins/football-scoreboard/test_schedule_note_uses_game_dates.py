#!/usr/bin/env python3
"""
Tests that the "nothing on until" advisory reports a game date, not a
calendar boundary.

_schedule_note used to pool ESPN's rolled-forward event dates with the
league calendar's week/phase startDates and take the earliest. Calendar
weeks routinely open days before their first game, so the note reported
"nothing on until 06 September" for a league whose first snap was the
10th -- and NCAA's twin was off by a day the other way. Events now win;
the calendar only speaks when the scoreboard has no events at all.

requests.get is stubbed; no network.

Run: <core-venv>/bin/python plugins/football-scoreboard/test_schedule_note_uses_game_dates.py
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

import requests  # noqa: E402

import football_favorite_check as ffc  # noqa: E402


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _iso(days_out):
    return (datetime.now(timezone.utc) + timedelta(days=days_out)).strftime(
        "%Y-%m-%dT%H:%MZ")


def _with_payload(payload):
    requests.get = lambda url, timeout=None: _Response(payload)


failures = []


def check(name, ok, detail=None):
    if ok:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s%s" % (name, " -- %r" % (detail,) if detail is not None else ""))
        failures.append(name)


def main():
    original_get = requests.get
    try:
        print("events and an earlier calendar boundary: the game date wins")
        first_game = datetime.now(timezone.utc) + timedelta(days=10)
        _with_payload({
            "events": [{"date": _iso(10)}, {"date": _iso(14)}],
            "leagues": [{"calendar": [{"startDate": _iso(6)}]}],
        })
        note = ffc.FavoriteTeamCheck._schedule_note("football/nfl")
        expected = first_game.strftime("%d %B %Y")
        check("the note names the first game's date", note is not None
              and expected in note, note)
        boundary = (datetime.now(timezone.utc) + timedelta(days=6)).strftime("%d %B %Y")
        check("and not the calendar boundary", note is not None
              and boundary not in note, note)

        print("\nno events at all: the calendar still gets a say")
        _with_payload({
            "events": [],
            "leagues": [{"calendar": [_iso(20)]}],
        })
        note = ffc.FavoriteTeamCheck._schedule_note("football/nfl")
        expected = (datetime.now(timezone.utc) + timedelta(days=20)).strftime("%d %B %Y")
        check("the calendar date is reported", note is not None
              and expected in note, note)

        print("\nonly past dates published: the finished-season wording")
        _with_payload({
            "events": [{"date": _iso(-40)}],
            "leagues": [{"calendar": []}],
        })
        note = ffc.FavoriteTeamCheck._schedule_note("football/nfl")
        check("season-finished note", note is not None and "finished" in note, note)

        print("\nan imminent slate is not worth a note")
        _with_payload({
            "events": [{"date": _iso(1)}],
            "leagues": [{"calendar": [{"startDate": _iso(6)}]}],
        })
        note = ffc.FavoriteTeamCheck._schedule_note("football/nfl")
        check("a game a day out draws no conclusion", note is None, note)
    finally:
        requests.get = original_get

    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
