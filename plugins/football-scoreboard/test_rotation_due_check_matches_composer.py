#!/usr/bin/env python3
"""
Tests that the display-path due-check agrees with the composer about
which pool would rotate.

_compose_selection falls back to the unfiltered list only when NOTHING
survived -- favourites included. _advance_other_games_if_due used to guess
`others or unfiltered` unconditionally, which disagrees in one state:
favourites are playing, the filters reject every other game, and the
unfiltered pool is larger than the limit. The due-check then passed on
every display() call, recomposed an identical favourites-only list each
frame forever, and never advanced _other_window_rotated_at -- correct
output, permanent per-frame recompute on a Pi's render path.

The methods are exercised against a stand-in ``self``, same as
test_empty_mode_signals_no_content.py: no display hardware, no network.

Run: <core-venv>/bin/python plugins/football-scoreboard/test_rotation_due_check_matches_composer.py
"""

import sys
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

import sports  # noqa: E402


class _Logger:
    def warning(self, *a, **k): pass
    def info(self, *a, **k): pass
    def debug(self, *a, **k): pass
    def error(self, *a, **k): pass


def _games(prefix, n):
    kickoff = datetime(2026, 9, 5, tzinfo=timezone.utc)
    return [
        {'id': '%s%d' % (prefix, i), 'away_abbr': 'A%d' % i, 'home_abbr': 'H%d' % i,
         'start_time_utc': kickoff + timedelta(days=i)}
        for i in range(n)
    ]


class _Manager:
    """A stand-in ``self`` carrying only what the rotation path touches."""

    def __init__(self, favorites, others, unfiltered,
                 favorite_limit=2, other_limit=3):
        self.logger = _Logger()
        self._games_lock = threading.RLock()
        self.favorite_teams = ['A0', 'H1']
        self.other_rotation_interval_seconds = 60
        self._other_window_start = 0
        self._other_window_rotated_at = time.monotonic() - 3600  # long overdue
        self._selection_pools = {
            'favorites': list(favorites),
            'others': list(others),
            'unfiltered': list(unfiltered),
            'favorite_limit': favorite_limit,
            'other_limit': other_limit,
            'newest_first': False,
        }

    _advance_other_games_if_due = sports.SportsCore._advance_other_games_if_due
    _compose_selection = sports.SportsCore._compose_selection
    _round_robin_favorites = sports.SportsCore._round_robin_favorites
    _other_games_window = sports.SportsCore._other_games_window


failures = []


def check(name, ok):
    if ok:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s" % name)
        failures.append(name)


def main():
    print("favourites playing + filters rejected every other game:")
    print("nothing will rotate, so the due-check must not fire")
    mgr = _Manager(favorites=_games('f', 2), others=[], unfiltered=_games('u', 10))
    stamp = mgr._other_window_rotated_at
    check("due-check returns [] (no recompose)",
          mgr._advance_other_games_if_due() == [])
    check("the composer agrees: favourites-only, no unfiltered fallback",
          [g['id'] for g in mgr._compose_selection()] == ['f0', 'f1'])
    check("rotation clock untouched", mgr._other_window_rotated_at == stamp)

    print("\nno favourites at all: the unfiltered fallback pool DOES rotate")
    mgr = _Manager(favorites=[], others=[], unfiltered=_games('u', 10))
    check("due-check recomposes from the unfiltered pool",
          len(mgr._advance_other_games_if_due()) == 3)

    print("\nfavourites present but favourite slots are 0: same fallback")
    mgr = _Manager(favorites=_games('f', 2), others=[],
                   unfiltered=_games('u', 10), favorite_limit=0)
    check("due-check recomposes from the unfiltered pool",
          len(mgr._advance_other_games_if_due()) == 3)

    print("\nfiltered others larger than the limit: the normal rotation")
    mgr = _Manager(favorites=_games('f', 2), others=_games('o', 8),
                   unfiltered=_games('u', 10))
    check("due-check recomposes", len(mgr._advance_other_games_if_due()) == 5)

    print("\nothers fit inside the limit: pinned, nothing to rotate through")
    mgr = _Manager(favorites=_games('f', 2), others=_games('o', 2),
                   unfiltered=_games('u', 10))
    check("due-check returns []", mgr._advance_other_games_if_due() == [])

    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == '__main__':
    sys.exit(main())
