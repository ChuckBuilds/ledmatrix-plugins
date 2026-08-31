#!/usr/bin/env python3
"""
Tests that rotating the other-games slice attaches odds to what it swaps in.

Odds are fetched in update(), which for an upcoming list runs hourly, while
_rotate_other_games_on_display re-cuts the non-favourite slice every
other_rotation_interval_seconds on the display path -- deliberately with no
network work. Every slice cut between updates therefore rendered without a
line even though ESPN had one, while the favourites, which survive every
cut, kept the odds update() gave them. Observed live: an hourly cycle
fetched odds for the five games selected at that moment while the panel
rotated through a different five with nothing under the matchup.

The fix hands the freshly rotated-in games to a daemon thread that asks
BaseOddsManager about each one -- bounded by the slice, never the pool, and
get_odds caches per game. These checks pin:

  * the games the rotation swaps in end up carrying odds;
  * games already holding odds are not asked about again;
  * show_odds off means no thread and no requests.

The methods are exercised against a stand-in ``self``, same as
test_rotation_due_check_matches_composer.py: no display hardware, and the
odds manager is a recorder, so no network either.

Run: <core-venv>/bin/python plugins/football-scoreboard/test_rotated_in_games_get_odds.py
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


class _RecordingOddsManager:
    def __init__(self):
        self.requested = []

    def get_odds(self, sport, league, event_id, update_interval_seconds):
        self.requested.append(event_id)
        return {"details": "HOME -3.5", "spread": -3.5}


def _games(prefix, n, with_odds=False):
    kickoff = datetime(2026, 9, 5, tzinfo=timezone.utc)
    games = [
        {'id': '%s%d' % (prefix, i), 'away_abbr': 'A%d' % i, 'home_abbr': 'H%d' % i,
         'start_time_utc': kickoff + timedelta(days=i)}
        for i in range(n)
    ]
    if with_odds:
        for g in games:
            g['odds'] = {"details": "already here"}
    return games


class _Manager:
    """A stand-in ``self`` carrying only what the rotation path touches."""

    def __init__(self, favorites, others, show_odds=True,
                 favorite_limit=2, other_limit=3):
        self.logger = _Logger()
        self._games_lock = threading.RLock()
        self.favorite_teams = ['A0', 'H1']
        self.show_odds = show_odds
        self.mode_config = {}
        self.odds_manager = _RecordingOddsManager()
        self.sport = 'football'
        self.league = 'college-football'
        self.sport_key = 'ncaa_fb'
        self.other_rotation_interval_seconds = 60
        self._other_window_start = 0
        self._other_window_rotated_at = time.monotonic() - 3600  # long overdue
        self.games_list = []
        self.current_game = None
        self.current_game_index = 0
        self.last_game_switch = 0
        self._selection_pools = {
            'favorites': list(favorites),
            'others': list(others),
            'unfiltered': list(others),
            'favorite_limit': favorite_limit,
            'other_limit': other_limit,
            'newest_first': False,
        }

    _rotate_other_games_on_display = sports.SportsCore._rotate_other_games_on_display
    _advance_other_games_if_due = sports.SportsCore._advance_other_games_if_due
    _attach_odds_to_rotated_games = sports.SportsCore._attach_odds_to_rotated_games
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


def _join_odds_threads():
    for thread in threading.enumerate():
        if thread.name.endswith('-rotated-odds'):
            thread.join(timeout=5)


def main():
    print("a due rotation swaps in games that have no odds yet:")
    favorites = _games('f', 2, with_odds=True)
    mgr = _Manager(favorites=favorites, others=_games('o', 8))
    check("the slice rotated", mgr._rotate_other_games_on_display())
    _join_odds_threads()
    rotated_in = [g for g in mgr.games_list if g['id'].startswith('o')]
    check("the rotation put non-favourites on screen", len(rotated_in) == 3)
    check("every rotated-in game now carries odds",
          all(g.get('odds') for g in rotated_in))
    check("only the games without odds were asked about",
          sorted(mgr.odds_manager.requested) ==
          sorted(g['id'] for g in rotated_in))
    check("the favourites' existing odds were not re-fetched",
          not any(r.startswith('f') for r in mgr.odds_manager.requested))

    print("\nshow_odds off: the rotation stays odds-silent")
    mgr = _Manager(favorites=_games('f', 2), others=_games('o', 8),
                   show_odds=False)
    check("the slice rotated", mgr._rotate_other_games_on_display())
    _join_odds_threads()
    check("no odds were requested", mgr.odds_manager.requested == [])

    print("\nevery game in the new slice already holds odds: nothing to do")
    mgr = _Manager(favorites=_games('f', 2, with_odds=True),
                   others=_games('o', 8, with_odds=True))
    check("the slice rotated", mgr._rotate_other_games_on_display())
    _join_odds_threads()
    check("no odds were requested", mgr.odds_manager.requested == [])

    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == '__main__':
    sys.exit(main())
