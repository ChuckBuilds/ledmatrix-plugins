#!/usr/bin/env python3
"""Which non-favourite games each scoreboard shows, and when the slice moves.

WHY THIS EXISTS
---------------
The other-games rotation is family 7 of the sports consolidation (LEDMatrix
docs/SPORTS_UNIFICATION.md): ``SportsCore._by_importance``,
``_other_games_window``, ``_advance_other_games_if_due``,
``_rotate_other_games_on_display`` and ``_attach_odds_to_rotated_games``. They
were two bodies each (football's three carried a lock and a due-check fix;
ufc's rotation attached no odds); they are now one each, with
``_rankings_loaded`` as the seam football overrides to count its by-id
rankings. They run on core's ``_favorites_first`` / ``_compose_selection`` /
``_round_robin_favorites`` and ``_next_switch_index``, and read the family-8
ranking helpers. The tables record what every plugin answers, so any later
change to the family shows up in a PR as a diff of them, cell by cell.

For each plugin it builds the primary league's real Upcoming and Recent
managers (fake display and cache, no network; the construction is
``test_favourite_matching.build``), with the rotation settings in the config.
``time.monotonic`` and ``time.time`` are frozen and stepped by hand. Then:

* ``IMPORTANCE``: ``_by_importance`` over one slate of non-favourite games
  (ranked and not, a rank tie, a team playing twice, a game with no start
  time, one with no abbreviations, live/final/upcoming mixed), per rankings
  table (by abbreviation, a tie, by ESPN id only, the two disagreeing), soonest and
  newest first: the ids, in order.
* ``POOLS``: core's ``_favorites_first`` over a slate (two favourite slots,
  three others), per favourites x ``other_games_min_quality`` x
  ``other_games_divisions`` x rankings: ``picked ; others pool ; unfiltered``.
* ``WINDOW``: ``_other_games_window`` called at 0, 30, 60, 119, 120 and 300 s
  (an id-only pool ``o1``...),
  per pool size x limit x ``other_rotation_interval_seconds``: each window,
  ``/``-separated (advancing, catch-up over several intervals, wrap-around,
  empty and one-game pools).
* ``ROTATION``: the real ``update()``, then the call ``display()`` makes
  (``_rotate_other_games_on_display``) at +30, +60, +90, +125 and +305 s,
  with the list's last card on screen: ``games_list@card on screen`` after
  update and after each tick (``>``-separated; ``^``: the tick asked for a
  redraw), and how many times
  ``_compose_selection`` ran on those ticks (``#``). ufc is
  ``n/a``: its MMA managers override ``update()``, which never builds the
  selection pools, so its rotation is dormant.
* ``INTERLEAVE``: update() and display() both advancing the window once the
  interval has passed: update alone, either order in sequence, and display's
  advance landing inside update's read-modify-write (a second thread; it
  either completes or blocks on ``_games_lock``). Cells are how many windows
  the start moved, then ``games_list``.
* ``ODDS``: whether a fresh slice swapped in by the display path gets odds
  for the games rotated in (``show_odds`` on, an odds manager answering every
  game): the ids that got a line.
* ``BOOST``: ``favorite_rotation_boost`` 1-3: the order switch mode walks
  ``games_list`` in (``_next_switch_index``), favourite u1 included.

Every league's managers in a plugin must resolve to the same family methods,
so one league per plugin covers them all; that is checked too.

A selection is the picked ids, ``none`` for an empty pick, ``~`` for a game
without an id; ``!Name`` means it raised. To see the current tables after an
intended change:

    python scripts/test_other_games_rotation.py --print

Exit 0 pass, 2 skip (no core checkout), 1 fail.
"""
from __future__ import annotations

import inspect
import logging
import os
import sys
import threading
from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_favourite_matching import NOW, build, changed_plugins  # noqa: E402
from test_game_over_check import diff  # noqa: E402
from test_sports_shared_methods import REPO, SPORTS, core_root, load  # noqa: E402

ROLES = ("Upcoming", "Recent")

#: ESPN id -> abbreviation. 1-4 match test_favourite_matching's teams, so nrl's
#: seeded resolver turns the favourite "AAA" into id 1, as it would a real one.
TEAM = {str(n): chr(64 + n) * 3 for n in range(1, 17)}       # 1 AAA ... 16 PPP
ID_OF = {abbr: int(tid) for tid, abbr in TEAM.items()}


def game(gid, home, away, hours, recent=False, status="upcoming"):
    """A view-model game ``hours`` from now (into the past when ``recent``)."""
    g = {"id": gid, "home_id": home, "away_id": away,
         "home_abbr": TEAM[home], "away_abbr": TEAM[away],
         "home_score": "10", "away_score": "20",
         "is_upcoming": status == "upcoming", "is_live": status == "live",
         "is_final": status == "final"}
    if hours is not None:
        g["start_time_utc"] = NOW + timedelta(hours=-hours if recent else hours)
    return g


def ranks(**by_abbr):
    """A rankings table by abbreviation, and the same table by ESPN id."""
    return by_abbr, {ID_OF[a]: r for a, r in by_abbr.items()}


#: label -> (``_team_rankings_cache``, ``_ranked_team_ids``). Every plugin gets
#: both attributes; only football reads the id table.
RANKINGS = {
    "none": ({}, {}),
    "abbr": ranks(HHH=1, FFF=2, DDD=3, BBB=4),
    "abbr tie": ranks(HHH=1, FFF=2, DDD=2, BBB=4),
    "ids only": ({}, ranks(HHH=1, FFF=2, DDD=3, BBB=4)[1]),
    "ids disagree": ({"HHH": 1, "FFF": 2}, {ID_OF["CCC"]: 1}),
    "matches nothing": ({"ZZZ": 1}, {99: 1}),
}


def importance_slate():
    """Non-favourite games, listed out of kickoff order."""
    no_abbr = game("n9", "15", "16", 9)
    del no_abbr["home_abbr"], no_abbr["away_abbr"]
    return [game("i3", "6", "7", 3, status="final"), game("i1", "1", "3", 1, status="live"),
            game("i2", "4", "5", 2), game("i4", "8", "9", 4), game("i5", "2", "10", 5),
            game("i6", "11", "12", 6),
            game("i7", "4", "11", 7),                 # DDD and KKK again: one per team
            game("i8", "13", "14", None),             # no start time
            no_abbr, game("i10", "2", "15", 10)]      # BBB again


#: id, home, away, hours from now: what update() is given (AAA is the favourite).
UPDATE_SLATE = (("u1", "1", "2", 1), ("u2", "3", "4", 2), ("u3", "5", "6", 3),
                ("u4", "7", "8", 4), ("u5", "2", "3", 5), ("u6", "4", "5", 6),
                ("u7", "6", "7", 7), ("u8", "1", "8", 8))

DIVISIONS = {"fbs": {1, 2, 3, 4, 5}, "fcs": {6, 7, 8}}

#: label -> favorite_teams as configured.
FAVORITES = {"none": [], "AAA": ["AAA"], "AAA,CCC": ["AAA", "CCC"]}

#: The clock everything frozen starts from. Not 0: the window treats a zero
#: stamp as "never cut".
T0 = 100_000.0
WINDOW_TIMES = (0, 30, 60, 119, 120, 300)
TICKS = (30, 60, 90, 125, 305)

#: label -> (config the managers are built with, rankings label).
ROTATION_SCENARIOS = {
    "AAA, 2 others, 60s": ({"favorite_teams": ["AAA"]}, "none"),
    "AAA, 2 others, pinned (0s)": (
        {"favorite_teams": ["AAA"], "other_rotation_interval_seconds": 0}, "none"),
    "AAA, favourites only": ({"favorite_teams": ["AAA"], "show_favorite_teams_only": True},
                             "none"),
    "AAA, 0 others": ({"favorite_teams": ["AAA"], "other_X_games_to_show": 0}, "none"),
    "no favourites, 3 games, 60s": ({"favorite_teams": [], "X_games_to_show": 3}, "none"),
    "AAA, ranked, poll on the slate": (
        {"favorite_teams": ["AAA"], "other_games_min_quality": "ranked"}, "abbr"),
    "AAA, ranked, poll matches nothing": (
        {"favorite_teams": ["AAA"], "other_games_min_quality": "ranked"}, "matches nothing"),
    "ZZZ not playing, ranked, poll matches nothing": (
        {"favorite_teams": ["ZZZ"], "other_games_min_quality": "ranked"}, "matches nothing"),
}

# --------------------------------------------------------------------------
# Expected (current) behaviour. Columns per plugin, in SPORTS order:
#   afl baseball basketball football hockey lacrosse nrl soccer ufc
# --------------------------------------------------------------------------
# (rankings, order): _by_importance over importance_slate().
EXPECTED_IMPORTANCE = {
    ('none', 'soonest'): 'i3,i1,i2,i4,i5,i6,i7,i8,n9,i10 | i3,i1,i2,i4,i5,i6,i7,i8,n9,i10 | i3,i1,i2,i4,i5,i6,i7,i8,n9,i10 | i3,i1,i2,i4,i5,i6,i7,i8,n9,i10 | i3,i1,i2,i4,i5,i6,i7,i8,n9,i10 | i3,i1,i2,i4,i5,i6,i7,i8,n9,i10 | i3,i1,i2,i4,i5,i6,i7,i8,n9,i10 | i3,i1,i2,i4,i5,i6,i7,i8,n9,i10 | i3,i1,i2,i4,i5,i6,i7,i8,n9,i10',
    ('none', 'newest'): 'i3,i1,i2,i4,i5,i6,i7,i8,n9,i10 | i3,i1,i2,i4,i5,i6,i7,i8,n9,i10 | i3,i1,i2,i4,i5,i6,i7,i8,n9,i10 | i3,i1,i2,i4,i5,i6,i7,i8,n9,i10 | i3,i1,i2,i4,i5,i6,i7,i8,n9,i10 | i3,i1,i2,i4,i5,i6,i7,i8,n9,i10 | i3,i1,i2,i4,i5,i6,i7,i8,n9,i10 | i3,i1,i2,i4,i5,i6,i7,i8,n9,i10 | i3,i1,i2,i4,i5,i6,i7,i8,n9,i10',
    ('abbr', 'soonest'): 'i4,i3,i2,i5,i1,i6,n9,i8 | i4,i3,i2,i5,i1,i6,n9,i8 | i4,i3,i2,i5,i1,i6,n9,i8 | i4,i3,i2,i5,i1,i6,n9,i8 | i4,i3,i2,i5,i1,i6,n9,i8 | i4,i3,i2,i5,i1,i6,n9,i8 | i4,i3,i2,i5,i1,i6,n9,i8 | i4,i3,i2,i5,i1,i6,n9,i8 | i4,i3,i2,i5,i1,i6,n9,i8',
    ('abbr', 'newest'): 'i4,i3,i7,i10,n9,i1,i8 | i4,i3,i7,i10,n9,i1,i8 | i4,i3,i7,i10,n9,i1,i8 | i4,i3,i7,i10,n9,i1,i8 | i4,i3,i7,i10,n9,i1,i8 | i4,i3,i7,i10,n9,i1,i8 | i4,i3,i7,i10,n9,i1,i8 | i4,i3,i7,i10,n9,i1,i8 | i4,i3,i7,i10,n9,i1,i8',
    ('abbr tie', 'soonest'): 'i4,i2,i3,i5,i1,i6,n9,i8 | i4,i2,i3,i5,i1,i6,n9,i8 | i4,i2,i3,i5,i1,i6,n9,i8 | i4,i2,i3,i5,i1,i6,n9,i8 | i4,i2,i3,i5,i1,i6,n9,i8 | i4,i2,i3,i5,i1,i6,n9,i8 | i4,i2,i3,i5,i1,i6,n9,i8 | i4,i2,i3,i5,i1,i6,n9,i8 | i4,i2,i3,i5,i1,i6,n9,i8',
    ('abbr tie', 'newest'): 'i4,i7,i3,i10,n9,i1,i8 | i4,i7,i3,i10,n9,i1,i8 | i4,i7,i3,i10,n9,i1,i8 | i4,i7,i3,i10,n9,i1,i8 | i4,i7,i3,i10,n9,i1,i8 | i4,i7,i3,i10,n9,i1,i8 | i4,i7,i3,i10,n9,i1,i8 | i4,i7,i3,i10,n9,i1,i8 | i4,i7,i3,i10,n9,i1,i8',
    ('ids only', 'soonest'): 'i3,i1,i2,i4,i5,i6,i7,i8,n9,i10 | i3,i1,i2,i4,i5,i6,i7,i8,n9,i10 | i3,i1,i2,i4,i5,i6,i7,i8,n9,i10 | i4,i3,i2,i5,i1,i6,n9,i8 | i3,i1,i2,i4,i5,i6,i7,i8,n9,i10 | i3,i1,i2,i4,i5,i6,i7,i8,n9,i10 | i3,i1,i2,i4,i5,i6,i7,i8,n9,i10 | i3,i1,i2,i4,i5,i6,i7,i8,n9,i10 | i3,i1,i2,i4,i5,i6,i7,i8,n9,i10',
    ('ids only', 'newest'): 'i3,i1,i2,i4,i5,i6,i7,i8,n9,i10 | i3,i1,i2,i4,i5,i6,i7,i8,n9,i10 | i3,i1,i2,i4,i5,i6,i7,i8,n9,i10 | i4,i3,i7,i10,n9,i1,i8 | i3,i1,i2,i4,i5,i6,i7,i8,n9,i10 | i3,i1,i2,i4,i5,i6,i7,i8,n9,i10 | i3,i1,i2,i4,i5,i6,i7,i8,n9,i10 | i3,i1,i2,i4,i5,i6,i7,i8,n9,i10 | i3,i1,i2,i4,i5,i6,i7,i8,n9,i10',
    ('ids disagree', 'soonest'): 'i4,i3,i1,i2,i5,i6,n9,i8 | i4,i3,i1,i2,i5,i6,n9,i8 | i4,i3,i1,i2,i5,i6,n9,i8 | i1,i2,i3,i4,i5,i6,n9,i8 | i4,i3,i1,i2,i5,i6,n9,i8 | i4,i3,i1,i2,i5,i6,n9,i8 | i4,i3,i1,i2,i5,i6,n9,i8 | i4,i3,i1,i2,i5,i6,n9,i8 | i4,i3,i1,i2,i5,i6,n9,i8',
    ('ids disagree', 'newest'): 'i4,i3,i10,n9,i7,i1,i8 | i4,i3,i10,n9,i7,i1,i8 | i4,i3,i10,n9,i7,i1,i8 | i1,i10,n9,i7,i4,i3,i8 | i4,i3,i10,n9,i7,i1,i8 | i4,i3,i10,n9,i7,i1,i8 | i4,i3,i10,n9,i7,i1,i8 | i4,i3,i10,n9,i7,i1,i8 | i4,i3,i10,n9,i7,i1,i8',
}

# (favourites, min quality, divisions, rankings): _favorites_first(UPDATE_SLATE, 2, 3)
# as 'picked ; others pool ; unfiltered pool'.
EXPECTED_POOLS = {
    ('none', 'any', 'all', 'none'): 'u1,u2,u3 ; u1,u2,u3,u4,u5,u6,u7,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u4,u5,u6,u7,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u4,u5,u6,u7,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u4,u5,u6,u7,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u4,u5,u6,u7,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u4,u5,u6,u7,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u4,u5,u6,u7,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u4,u5,u6,u7,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u4,u5,u6,u7,u8 ; u1,u2,u3,u4,u5,u6,u7,u8',
    ('none', 'any', 'all', 'abbr'): 'u2,u3,u4 ; u4,u3,u2,u1 ; u4,u3,u2,u1 | u2,u3,u4 ; u4,u3,u2,u1 ; u4,u3,u2,u1 | u2,u3,u4 ; u4,u3,u2,u1 ; u4,u3,u2,u1 | u2,u3,u4 ; u4,u3,u2,u1 ; u4,u3,u2,u1 | u2,u3,u4 ; u4,u3,u2,u1 ; u4,u3,u2,u1 | u2,u3,u4 ; u4,u3,u2,u1 ; u4,u3,u2,u1 | u2,u3,u4 ; u4,u3,u2,u1 ; u4,u3,u2,u1 | u2,u3,u4 ; u4,u3,u2,u1 ; u4,u3,u2,u1 | u2,u3,u4 ; u4,u3,u2,u1 ; u4,u3,u2,u1',
    ('none', 'any', 'all', 'ids only'): 'u1,u2,u3 ; u1,u2,u3,u4,u5,u6,u7,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u4,u5,u6,u7,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u4,u5,u6,u7,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u2,u3,u4 ; u4,u3,u2,u1 ; u4,u3,u2,u1 | u1,u2,u3 ; u1,u2,u3,u4,u5,u6,u7,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u4,u5,u6,u7,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u4,u5,u6,u7,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u4,u5,u6,u7,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u4,u5,u6,u7,u8 ; u1,u2,u3,u4,u5,u6,u7,u8',
    ('none', 'any', 'fbs', 'none'): 'u1,u2,u3 ; u1,u2,u3,u5,u6,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u5,u6,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u5,u6,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u5,u6,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u5,u6,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u5,u6,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u5,u6,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u5,u6,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u5,u6,u8 ; u1,u2,u3,u4,u5,u6,u7,u8',
    ('none', 'any', 'fbs', 'abbr'): 'u1,u2,u3 ; u3,u2,u1 ; u4,u3,u2,u1 | u1,u2,u3 ; u3,u2,u1 ; u4,u3,u2,u1 | u1,u2,u3 ; u3,u2,u1 ; u4,u3,u2,u1 | u1,u2,u3 ; u3,u2,u1 ; u4,u3,u2,u1 | u1,u2,u3 ; u3,u2,u1 ; u4,u3,u2,u1 | u1,u2,u3 ; u3,u2,u1 ; u4,u3,u2,u1 | u1,u2,u3 ; u3,u2,u1 ; u4,u3,u2,u1 | u1,u2,u3 ; u3,u2,u1 ; u4,u3,u2,u1 | u1,u2,u3 ; u3,u2,u1 ; u4,u3,u2,u1',
    ('none', 'any', 'fbs', 'ids only'): 'u1,u2,u3 ; u1,u2,u3,u5,u6,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u5,u6,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u5,u6,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u3,u2,u1 ; u4,u3,u2,u1 | u1,u2,u3 ; u1,u2,u3,u5,u6,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u5,u6,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u5,u6,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u5,u6,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u5,u6,u8 ; u1,u2,u3,u4,u5,u6,u7,u8',
    ('none', 'ranked', 'all', 'none'): 'u1,u2,u3 ; u1,u2,u3,u4,u5,u6,u7,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u4,u5,u6,u7,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u4,u5,u6,u7,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u4,u5,u6,u7,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u4,u5,u6,u7,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u4,u5,u6,u7,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u4,u5,u6,u7,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u4,u5,u6,u7,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u4,u5,u6,u7,u8 ; u1,u2,u3,u4,u5,u6,u7,u8',
    ('none', 'ranked', 'all', 'abbr'): 'u2,u3,u4 ; u4,u3,u2,u1 ; u4,u3,u2,u1 | u2,u3,u4 ; u4,u3,u2,u1 ; u4,u3,u2,u1 | u2,u3,u4 ; u4,u3,u2,u1 ; u4,u3,u2,u1 | u2,u3,u4 ; u4,u3,u2,u1 ; u4,u3,u2,u1 | u2,u3,u4 ; u4,u3,u2,u1 ; u4,u3,u2,u1 | u2,u3,u4 ; u4,u3,u2,u1 ; u4,u3,u2,u1 | u2,u3,u4 ; u4,u3,u2,u1 ; u4,u3,u2,u1 | u2,u3,u4 ; u4,u3,u2,u1 ; u4,u3,u2,u1 | u2,u3,u4 ; u4,u3,u2,u1 ; u4,u3,u2,u1',
    ('none', 'ranked', 'all', 'ids only'): 'u1,u2,u3 ; u1,u2,u3,u4,u5,u6,u7,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u4,u5,u6,u7,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u4,u5,u6,u7,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u2,u3,u4 ; u4,u3,u2,u1 ; u4,u3,u2,u1 | u1,u2,u3 ; u1,u2,u3,u4,u5,u6,u7,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u4,u5,u6,u7,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u4,u5,u6,u7,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u4,u5,u6,u7,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u4,u5,u6,u7,u8 ; u1,u2,u3,u4,u5,u6,u7,u8',
    ('none', 'ranked', 'fbs', 'none'): 'u1,u2,u3 ; u1,u2,u3,u5,u6,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u5,u6,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u5,u6,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u5,u6,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u5,u6,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u5,u6,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u5,u6,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u5,u6,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u5,u6,u8 ; u1,u2,u3,u4,u5,u6,u7,u8',
    ('none', 'ranked', 'fbs', 'abbr'): 'u1,u2,u3 ; u3,u2,u1 ; u4,u3,u2,u1 | u1,u2,u3 ; u3,u2,u1 ; u4,u3,u2,u1 | u1,u2,u3 ; u3,u2,u1 ; u4,u3,u2,u1 | u1,u2,u3 ; u3,u2,u1 ; u4,u3,u2,u1 | u1,u2,u3 ; u3,u2,u1 ; u4,u3,u2,u1 | u1,u2,u3 ; u3,u2,u1 ; u4,u3,u2,u1 | u1,u2,u3 ; u3,u2,u1 ; u4,u3,u2,u1 | u1,u2,u3 ; u3,u2,u1 ; u4,u3,u2,u1 | u1,u2,u3 ; u3,u2,u1 ; u4,u3,u2,u1',
    ('none', 'ranked', 'fbs', 'ids only'): 'u1,u2,u3 ; u1,u2,u3,u5,u6,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u5,u6,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u5,u6,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u3,u2,u1 ; u4,u3,u2,u1 | u1,u2,u3 ; u1,u2,u3,u5,u6,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u5,u6,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u5,u6,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u5,u6,u8 ; u1,u2,u3,u4,u5,u6,u7,u8 | u1,u2,u3 ; u1,u2,u3,u5,u6,u8 ; u1,u2,u3,u4,u5,u6,u7,u8',
    ('AAA', 'any', 'all', 'none'): 'u1,u2,u3,u4,u8 ; u2,u3,u4,u5,u6,u7 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u4,u8 ; u2,u3,u4,u5,u6,u7 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u4,u8 ; u2,u3,u4,u5,u6,u7 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u4,u8 ; u2,u3,u4,u5,u6,u7 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u4,u8 ; u2,u3,u4,u5,u6,u7 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u4,u8 ; u2,u3,u4,u5,u6,u7 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u4,u8 ; u2,u3,u4,u5,u6,u7 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u4,u8 ; u2,u3,u4,u5,u6,u7 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u4,u8 ; u2,u3,u4,u5,u6,u7 ; u2,u3,u4,u5,u6,u7',
    ('AAA', 'any', 'all', 'abbr'): 'u1,u2,u3,u4,u8 ; u4,u3,u2 ; u4,u3,u2 | u1,u2,u3,u4,u8 ; u4,u3,u2 ; u4,u3,u2 | u1,u2,u3,u4,u8 ; u4,u3,u2 ; u4,u3,u2 | u1,u2,u3,u4,u8 ; u4,u3,u2 ; u4,u3,u2 | u1,u2,u3,u4,u8 ; u4,u3,u2 ; u4,u3,u2 | u1,u2,u3,u4,u8 ; u4,u3,u2 ; u4,u3,u2 | u1,u2,u3,u4,u8 ; u4,u3,u2 ; u4,u3,u2 | u1,u2,u3,u4,u8 ; u4,u3,u2 ; u4,u3,u2 | u1,u2,u3,u4,u8 ; u4,u3,u2 ; u4,u3,u2',
    ('AAA', 'any', 'all', 'ids only'): 'u1,u2,u3,u4,u8 ; u2,u3,u4,u5,u6,u7 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u4,u8 ; u2,u3,u4,u5,u6,u7 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u4,u8 ; u2,u3,u4,u5,u6,u7 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u4,u8 ; u4,u3,u2 ; u4,u3,u2 | u1,u2,u3,u4,u8 ; u2,u3,u4,u5,u6,u7 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u4,u8 ; u2,u3,u4,u5,u6,u7 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u4,u8 ; u2,u3,u4,u5,u6,u7 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u4,u8 ; u2,u3,u4,u5,u6,u7 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u4,u8 ; u2,u3,u4,u5,u6,u7 ; u2,u3,u4,u5,u6,u7',
    ('AAA', 'any', 'fbs', 'none'): 'u1,u2,u3,u5,u8 ; u2,u3,u5,u6 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u5,u8 ; u2,u3,u5,u6 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u5,u8 ; u2,u3,u5,u6 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u5,u8 ; u2,u3,u5,u6 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u5,u8 ; u2,u3,u5,u6 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u5,u8 ; u2,u3,u5,u6 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u5,u8 ; u2,u3,u5,u6 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u5,u8 ; u2,u3,u5,u6 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u5,u8 ; u2,u3,u5,u6 ; u2,u3,u4,u5,u6,u7',
    ('AAA', 'any', 'fbs', 'abbr'): 'u1,u2,u3,u8 ; u3,u2 ; u4,u3,u2 | u1,u2,u3,u8 ; u3,u2 ; u4,u3,u2 | u1,u2,u3,u8 ; u3,u2 ; u4,u3,u2 | u1,u2,u3,u8 ; u3,u2 ; u4,u3,u2 | u1,u2,u3,u8 ; u3,u2 ; u4,u3,u2 | u1,u2,u3,u8 ; u3,u2 ; u4,u3,u2 | u1,u2,u3,u8 ; u3,u2 ; u4,u3,u2 | u1,u2,u3,u8 ; u3,u2 ; u4,u3,u2 | u1,u2,u3,u8 ; u3,u2 ; u4,u3,u2',
    ('AAA', 'any', 'fbs', 'ids only'): 'u1,u2,u3,u5,u8 ; u2,u3,u5,u6 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u5,u8 ; u2,u3,u5,u6 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u5,u8 ; u2,u3,u5,u6 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u8 ; u3,u2 ; u4,u3,u2 | u1,u2,u3,u5,u8 ; u2,u3,u5,u6 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u5,u8 ; u2,u3,u5,u6 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u5,u8 ; u2,u3,u5,u6 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u5,u8 ; u2,u3,u5,u6 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u5,u8 ; u2,u3,u5,u6 ; u2,u3,u4,u5,u6,u7',
    ('AAA', 'ranked', 'all', 'none'): 'u1,u2,u3,u4,u8 ; u2,u3,u4,u5,u6,u7 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u4,u8 ; u2,u3,u4,u5,u6,u7 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u4,u8 ; u2,u3,u4,u5,u6,u7 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u4,u8 ; u2,u3,u4,u5,u6,u7 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u4,u8 ; u2,u3,u4,u5,u6,u7 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u4,u8 ; u2,u3,u4,u5,u6,u7 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u4,u8 ; u2,u3,u4,u5,u6,u7 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u4,u8 ; u2,u3,u4,u5,u6,u7 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u4,u8 ; u2,u3,u4,u5,u6,u7 ; u2,u3,u4,u5,u6,u7',
    ('AAA', 'ranked', 'all', 'abbr'): 'u1,u2,u3,u4,u8 ; u4,u3,u2 ; u4,u3,u2 | u1,u2,u3,u4,u8 ; u4,u3,u2 ; u4,u3,u2 | u1,u2,u3,u4,u8 ; u4,u3,u2 ; u4,u3,u2 | u1,u2,u3,u4,u8 ; u4,u3,u2 ; u4,u3,u2 | u1,u2,u3,u4,u8 ; u4,u3,u2 ; u4,u3,u2 | u1,u2,u3,u4,u8 ; u4,u3,u2 ; u4,u3,u2 | u1,u2,u3,u4,u8 ; u4,u3,u2 ; u4,u3,u2 | u1,u2,u3,u4,u8 ; u4,u3,u2 ; u4,u3,u2 | u1,u2,u3,u4,u8 ; u4,u3,u2 ; u4,u3,u2',
    ('AAA', 'ranked', 'all', 'ids only'): 'u1,u2,u3,u4,u8 ; u2,u3,u4,u5,u6,u7 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u4,u8 ; u2,u3,u4,u5,u6,u7 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u4,u8 ; u2,u3,u4,u5,u6,u7 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u4,u8 ; u4,u3,u2 ; u4,u3,u2 | u1,u2,u3,u4,u8 ; u2,u3,u4,u5,u6,u7 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u4,u8 ; u2,u3,u4,u5,u6,u7 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u4,u8 ; u2,u3,u4,u5,u6,u7 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u4,u8 ; u2,u3,u4,u5,u6,u7 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u4,u8 ; u2,u3,u4,u5,u6,u7 ; u2,u3,u4,u5,u6,u7',
    ('AAA', 'ranked', 'fbs', 'none'): 'u1,u2,u3,u5,u8 ; u2,u3,u5,u6 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u5,u8 ; u2,u3,u5,u6 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u5,u8 ; u2,u3,u5,u6 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u5,u8 ; u2,u3,u5,u6 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u5,u8 ; u2,u3,u5,u6 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u5,u8 ; u2,u3,u5,u6 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u5,u8 ; u2,u3,u5,u6 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u5,u8 ; u2,u3,u5,u6 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u5,u8 ; u2,u3,u5,u6 ; u2,u3,u4,u5,u6,u7',
    ('AAA', 'ranked', 'fbs', 'abbr'): 'u1,u2,u3,u8 ; u3,u2 ; u4,u3,u2 | u1,u2,u3,u8 ; u3,u2 ; u4,u3,u2 | u1,u2,u3,u8 ; u3,u2 ; u4,u3,u2 | u1,u2,u3,u8 ; u3,u2 ; u4,u3,u2 | u1,u2,u3,u8 ; u3,u2 ; u4,u3,u2 | u1,u2,u3,u8 ; u3,u2 ; u4,u3,u2 | u1,u2,u3,u8 ; u3,u2 ; u4,u3,u2 | u1,u2,u3,u8 ; u3,u2 ; u4,u3,u2 | u1,u2,u3,u8 ; u3,u2 ; u4,u3,u2',
    ('AAA', 'ranked', 'fbs', 'ids only'): 'u1,u2,u3,u5,u8 ; u2,u3,u5,u6 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u5,u8 ; u2,u3,u5,u6 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u5,u8 ; u2,u3,u5,u6 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u8 ; u3,u2 ; u4,u3,u2 | u1,u2,u3,u5,u8 ; u2,u3,u5,u6 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u5,u8 ; u2,u3,u5,u6 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u5,u8 ; u2,u3,u5,u6 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u5,u8 ; u2,u3,u5,u6 ; u2,u3,u4,u5,u6,u7 | u1,u2,u3,u5,u8 ; u2,u3,u5,u6 ; u2,u3,u4,u5,u6,u7',
    ('AAA,CCC', 'any', 'all', 'none'): 'u1,u2,u3,u4,u6 ; u3,u4,u6,u7 ; u3,u4,u6,u7 | u1,u2,u3,u4,u6 ; u3,u4,u6,u7 ; u3,u4,u6,u7 | u1,u2,u3,u4,u6 ; u3,u4,u6,u7 ; u3,u4,u6,u7 | u1,u2,u3,u4,u6 ; u3,u4,u6,u7 ; u3,u4,u6,u7 | u1,u2,u3,u4,u6 ; u3,u4,u6,u7 ; u3,u4,u6,u7 | u1,u2,u3,u4,u6 ; u3,u4,u6,u7 ; u3,u4,u6,u7 | u1,u2,u3,u4,u6 ; u3,u4,u6,u7 ; u3,u4,u6,u7 | u1,u2,u3,u4,u6 ; u3,u4,u6,u7 ; u3,u4,u6,u7 | u1,u2,u3,u4,u6 ; u3,u4,u6,u7 ; u3,u4,u6,u7',
    ('AAA,CCC', 'any', 'all', 'abbr'): 'u1,u2,u3,u4 ; u4,u3 ; u4,u3 | u1,u2,u3,u4 ; u4,u3 ; u4,u3 | u1,u2,u3,u4 ; u4,u3 ; u4,u3 | u1,u2,u3,u4 ; u4,u3 ; u4,u3 | u1,u2,u3,u4 ; u4,u3 ; u4,u3 | u1,u2,u3,u4 ; u4,u3 ; u4,u3 | u1,u2,u3,u4 ; u4,u3 ; u4,u3 | u1,u2,u3,u4 ; u4,u3 ; u4,u3 | u1,u2,u3,u4 ; u4,u3 ; u4,u3',
    ('AAA,CCC', 'any', 'all', 'ids only'): 'u1,u2,u3,u4,u6 ; u3,u4,u6,u7 ; u3,u4,u6,u7 | u1,u2,u3,u4,u6 ; u3,u4,u6,u7 ; u3,u4,u6,u7 | u1,u2,u3,u4,u6 ; u3,u4,u6,u7 ; u3,u4,u6,u7 | u1,u2,u3,u4 ; u4,u3 ; u4,u3 | u1,u2,u3,u4,u6 ; u3,u4,u6,u7 ; u3,u4,u6,u7 | u1,u2,u3,u4,u6 ; u3,u4,u6,u7 ; u3,u4,u6,u7 | u1,u2,u3,u4,u6 ; u3,u4,u6,u7 ; u3,u4,u6,u7 | u1,u2,u3,u4,u6 ; u3,u4,u6,u7 ; u3,u4,u6,u7 | u1,u2,u3,u4,u6 ; u3,u4,u6,u7 ; u3,u4,u6,u7',
    ('AAA,CCC', 'any', 'fbs', 'none'): 'u1,u2,u3,u6 ; u3,u6 ; u3,u4,u6,u7 | u1,u2,u3,u6 ; u3,u6 ; u3,u4,u6,u7 | u1,u2,u3,u6 ; u3,u6 ; u3,u4,u6,u7 | u1,u2,u3,u6 ; u3,u6 ; u3,u4,u6,u7 | u1,u2,u3,u6 ; u3,u6 ; u3,u4,u6,u7 | u1,u2,u3,u6 ; u3,u6 ; u3,u4,u6,u7 | u1,u2,u3,u6 ; u3,u6 ; u3,u4,u6,u7 | u1,u2,u3,u6 ; u3,u6 ; u3,u4,u6,u7 | u1,u2,u3,u6 ; u3,u6 ; u3,u4,u6,u7',
    ('AAA,CCC', 'any', 'fbs', 'abbr'): 'u1,u2,u3 ; u3 ; u4,u3 | u1,u2,u3 ; u3 ; u4,u3 | u1,u2,u3 ; u3 ; u4,u3 | u1,u2,u3 ; u3 ; u4,u3 | u1,u2,u3 ; u3 ; u4,u3 | u1,u2,u3 ; u3 ; u4,u3 | u1,u2,u3 ; u3 ; u4,u3 | u1,u2,u3 ; u3 ; u4,u3 | u1,u2,u3 ; u3 ; u4,u3',
    ('AAA,CCC', 'any', 'fbs', 'ids only'): 'u1,u2,u3,u6 ; u3,u6 ; u3,u4,u6,u7 | u1,u2,u3,u6 ; u3,u6 ; u3,u4,u6,u7 | u1,u2,u3,u6 ; u3,u6 ; u3,u4,u6,u7 | u1,u2,u3 ; u3 ; u4,u3 | u1,u2,u3,u6 ; u3,u6 ; u3,u4,u6,u7 | u1,u2,u3,u6 ; u3,u6 ; u3,u4,u6,u7 | u1,u2,u3,u6 ; u3,u6 ; u3,u4,u6,u7 | u1,u2,u3,u6 ; u3,u6 ; u3,u4,u6,u7 | u1,u2,u3,u6 ; u3,u6 ; u3,u4,u6,u7',
    ('AAA,CCC', 'ranked', 'all', 'none'): 'u1,u2,u3,u4,u6 ; u3,u4,u6,u7 ; u3,u4,u6,u7 | u1,u2,u3,u4,u6 ; u3,u4,u6,u7 ; u3,u4,u6,u7 | u1,u2,u3,u4,u6 ; u3,u4,u6,u7 ; u3,u4,u6,u7 | u1,u2,u3,u4,u6 ; u3,u4,u6,u7 ; u3,u4,u6,u7 | u1,u2,u3,u4,u6 ; u3,u4,u6,u7 ; u3,u4,u6,u7 | u1,u2,u3,u4,u6 ; u3,u4,u6,u7 ; u3,u4,u6,u7 | u1,u2,u3,u4,u6 ; u3,u4,u6,u7 ; u3,u4,u6,u7 | u1,u2,u3,u4,u6 ; u3,u4,u6,u7 ; u3,u4,u6,u7 | u1,u2,u3,u4,u6 ; u3,u4,u6,u7 ; u3,u4,u6,u7',
    ('AAA,CCC', 'ranked', 'all', 'abbr'): 'u1,u2,u3,u4 ; u4,u3 ; u4,u3 | u1,u2,u3,u4 ; u4,u3 ; u4,u3 | u1,u2,u3,u4 ; u4,u3 ; u4,u3 | u1,u2,u3,u4 ; u4,u3 ; u4,u3 | u1,u2,u3,u4 ; u4,u3 ; u4,u3 | u1,u2,u3,u4 ; u4,u3 ; u4,u3 | u1,u2,u3,u4 ; u4,u3 ; u4,u3 | u1,u2,u3,u4 ; u4,u3 ; u4,u3 | u1,u2,u3,u4 ; u4,u3 ; u4,u3',
    ('AAA,CCC', 'ranked', 'all', 'ids only'): 'u1,u2,u3,u4,u6 ; u3,u4,u6,u7 ; u3,u4,u6,u7 | u1,u2,u3,u4,u6 ; u3,u4,u6,u7 ; u3,u4,u6,u7 | u1,u2,u3,u4,u6 ; u3,u4,u6,u7 ; u3,u4,u6,u7 | u1,u2,u3,u4 ; u4,u3 ; u4,u3 | u1,u2,u3,u4,u6 ; u3,u4,u6,u7 ; u3,u4,u6,u7 | u1,u2,u3,u4,u6 ; u3,u4,u6,u7 ; u3,u4,u6,u7 | u1,u2,u3,u4,u6 ; u3,u4,u6,u7 ; u3,u4,u6,u7 | u1,u2,u3,u4,u6 ; u3,u4,u6,u7 ; u3,u4,u6,u7 | u1,u2,u3,u4,u6 ; u3,u4,u6,u7 ; u3,u4,u6,u7',
    ('AAA,CCC', 'ranked', 'fbs', 'none'): 'u1,u2,u3,u6 ; u3,u6 ; u3,u4,u6,u7 | u1,u2,u3,u6 ; u3,u6 ; u3,u4,u6,u7 | u1,u2,u3,u6 ; u3,u6 ; u3,u4,u6,u7 | u1,u2,u3,u6 ; u3,u6 ; u3,u4,u6,u7 | u1,u2,u3,u6 ; u3,u6 ; u3,u4,u6,u7 | u1,u2,u3,u6 ; u3,u6 ; u3,u4,u6,u7 | u1,u2,u3,u6 ; u3,u6 ; u3,u4,u6,u7 | u1,u2,u3,u6 ; u3,u6 ; u3,u4,u6,u7 | u1,u2,u3,u6 ; u3,u6 ; u3,u4,u6,u7',
    ('AAA,CCC', 'ranked', 'fbs', 'abbr'): 'u1,u2,u3 ; u3 ; u4,u3 | u1,u2,u3 ; u3 ; u4,u3 | u1,u2,u3 ; u3 ; u4,u3 | u1,u2,u3 ; u3 ; u4,u3 | u1,u2,u3 ; u3 ; u4,u3 | u1,u2,u3 ; u3 ; u4,u3 | u1,u2,u3 ; u3 ; u4,u3 | u1,u2,u3 ; u3 ; u4,u3 | u1,u2,u3 ; u3 ; u4,u3',
    ('AAA,CCC', 'ranked', 'fbs', 'ids only'): 'u1,u2,u3,u6 ; u3,u6 ; u3,u4,u6,u7 | u1,u2,u3,u6 ; u3,u6 ; u3,u4,u6,u7 | u1,u2,u3,u6 ; u3,u6 ; u3,u4,u6,u7 | u1,u2,u3 ; u3 ; u4,u3 | u1,u2,u3,u6 ; u3,u6 ; u3,u4,u6,u7 | u1,u2,u3,u6 ; u3,u6 ; u3,u4,u6,u7 | u1,u2,u3,u6 ; u3,u6 ; u3,u4,u6,u7 | u1,u2,u3,u6 ; u3,u6 ; u3,u4,u6,u7 | u1,u2,u3,u6 ; u3,u6 ; u3,u4,u6,u7',
}

# (pool size, limit, interval s): _other_games_window at each of WINDOW_TIMES.
EXPECTED_WINDOW = {
    (0, 0, 0): 'none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none',
    (0, 0, 60): 'none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none',
    (0, 2, 0): 'none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none',
    (0, 2, 60): 'none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none',
    (0, 3, 0): 'none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none',
    (0, 3, 60): 'none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none',
    (1, 0, 0): 'none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none',
    (1, 0, 60): 'none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none',
    (1, 2, 0): 'o1 / o1 / o1 / o1 / o1 / o1 | o1 / o1 / o1 / o1 / o1 / o1 | o1 / o1 / o1 / o1 / o1 / o1 | o1 / o1 / o1 / o1 / o1 / o1 | o1 / o1 / o1 / o1 / o1 / o1 | o1 / o1 / o1 / o1 / o1 / o1 | o1 / o1 / o1 / o1 / o1 / o1 | o1 / o1 / o1 / o1 / o1 / o1 | o1 / o1 / o1 / o1 / o1 / o1',
    (1, 2, 60): 'o1 / o1 / o1 / o1 / o1 / o1 | o1 / o1 / o1 / o1 / o1 / o1 | o1 / o1 / o1 / o1 / o1 / o1 | o1 / o1 / o1 / o1 / o1 / o1 | o1 / o1 / o1 / o1 / o1 / o1 | o1 / o1 / o1 / o1 / o1 / o1 | o1 / o1 / o1 / o1 / o1 / o1 | o1 / o1 / o1 / o1 / o1 / o1 | o1 / o1 / o1 / o1 / o1 / o1',
    (1, 3, 0): 'o1 / o1 / o1 / o1 / o1 / o1 | o1 / o1 / o1 / o1 / o1 / o1 | o1 / o1 / o1 / o1 / o1 / o1 | o1 / o1 / o1 / o1 / o1 / o1 | o1 / o1 / o1 / o1 / o1 / o1 | o1 / o1 / o1 / o1 / o1 / o1 | o1 / o1 / o1 / o1 / o1 / o1 | o1 / o1 / o1 / o1 / o1 / o1 | o1 / o1 / o1 / o1 / o1 / o1',
    (1, 3, 60): 'o1 / o1 / o1 / o1 / o1 / o1 | o1 / o1 / o1 / o1 / o1 / o1 | o1 / o1 / o1 / o1 / o1 / o1 | o1 / o1 / o1 / o1 / o1 / o1 | o1 / o1 / o1 / o1 / o1 / o1 | o1 / o1 / o1 / o1 / o1 / o1 | o1 / o1 / o1 / o1 / o1 / o1 | o1 / o1 / o1 / o1 / o1 / o1 | o1 / o1 / o1 / o1 / o1 / o1',
    (2, 0, 0): 'none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none',
    (2, 0, 60): 'none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none',
    (2, 2, 0): 'o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 | o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 | o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 | o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 | o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 | o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 | o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 | o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 | o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2',
    (2, 2, 60): 'o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 | o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 | o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 | o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 | o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 | o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 | o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 | o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 | o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2',
    (2, 3, 0): 'o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 | o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 | o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 | o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 | o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 | o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 | o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 | o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 | o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2',
    (2, 3, 60): 'o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 | o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 | o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 | o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 | o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 | o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 | o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 | o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 | o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2',
    (7, 0, 0): 'none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none',
    (7, 0, 60): 'none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none | none / none / none / none / none / none',
    (7, 2, 0): 'o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 | o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 | o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 | o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 | o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 | o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 | o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 | o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 | o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2 / o1,o2',
    (7, 2, 60): 'o1,o2 / o1,o2 / o3,o4 / o3,o4 / o5,o6 / o4,o5 | o1,o2 / o1,o2 / o3,o4 / o3,o4 / o5,o6 / o4,o5 | o1,o2 / o1,o2 / o3,o4 / o3,o4 / o5,o6 / o4,o5 | o1,o2 / o1,o2 / o3,o4 / o3,o4 / o5,o6 / o4,o5 | o1,o2 / o1,o2 / o3,o4 / o3,o4 / o5,o6 / o4,o5 | o1,o2 / o1,o2 / o3,o4 / o3,o4 / o5,o6 / o4,o5 | o1,o2 / o1,o2 / o3,o4 / o3,o4 / o5,o6 / o4,o5 | o1,o2 / o1,o2 / o3,o4 / o3,o4 / o5,o6 / o4,o5 | o1,o2 / o1,o2 / o3,o4 / o3,o4 / o5,o6 / o4,o5',
    (7, 3, 0): 'o1,o2,o3 / o1,o2,o3 / o1,o2,o3 / o1,o2,o3 / o1,o2,o3 / o1,o2,o3 | o1,o2,o3 / o1,o2,o3 / o1,o2,o3 / o1,o2,o3 / o1,o2,o3 / o1,o2,o3 | o1,o2,o3 / o1,o2,o3 / o1,o2,o3 / o1,o2,o3 / o1,o2,o3 / o1,o2,o3 | o1,o2,o3 / o1,o2,o3 / o1,o2,o3 / o1,o2,o3 / o1,o2,o3 / o1,o2,o3 | o1,o2,o3 / o1,o2,o3 / o1,o2,o3 / o1,o2,o3 / o1,o2,o3 / o1,o2,o3 | o1,o2,o3 / o1,o2,o3 / o1,o2,o3 / o1,o2,o3 / o1,o2,o3 / o1,o2,o3 | o1,o2,o3 / o1,o2,o3 / o1,o2,o3 / o1,o2,o3 / o1,o2,o3 / o1,o2,o3 | o1,o2,o3 / o1,o2,o3 / o1,o2,o3 / o1,o2,o3 / o1,o2,o3 / o1,o2,o3 | o1,o2,o3 / o1,o2,o3 / o1,o2,o3 / o1,o2,o3 / o1,o2,o3 / o1,o2,o3',
    (7, 3, 60): 'o1,o2,o3 / o1,o2,o3 / o4,o5,o6 / o4,o5,o6 / o7,o1,o2 / o2,o3,o4 | o1,o2,o3 / o1,o2,o3 / o4,o5,o6 / o4,o5,o6 / o7,o1,o2 / o2,o3,o4 | o1,o2,o3 / o1,o2,o3 / o4,o5,o6 / o4,o5,o6 / o7,o1,o2 / o2,o3,o4 | o1,o2,o3 / o1,o2,o3 / o4,o5,o6 / o4,o5,o6 / o7,o1,o2 / o2,o3,o4 | o1,o2,o3 / o1,o2,o3 / o4,o5,o6 / o4,o5,o6 / o7,o1,o2 / o2,o3,o4 | o1,o2,o3 / o1,o2,o3 / o4,o5,o6 / o4,o5,o6 / o7,o1,o2 / o2,o3,o4 | o1,o2,o3 / o1,o2,o3 / o4,o5,o6 / o4,o5,o6 / o7,o1,o2 / o2,o3,o4 | o1,o2,o3 / o1,o2,o3 / o4,o5,o6 / o4,o5,o6 / o7,o1,o2 / o2,o3,o4 | o1,o2,o3 / o1,o2,o3 / o4,o5,o6 / o4,o5,o6 / o7,o1,o2 / o2,o3,o4',
}

# (role, scenario): games_list@on screen after update(), then after each display tick
# (^: it asked for a redraw); #: how many times _compose_selection ran on the ticks.
EXPECTED_ROTATION = {
    ('Upcoming', 'AAA, 2 others, 60s'): 'u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u4,u5,u8@u8^ > u1,u4,u5,u8@u8 > u1,u6,u7,u8@u8^ > u1,u6,u7,u8@u8 #3 | u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u4,u5,u8@u8^ > u1,u4,u5,u8@u8 > u1,u6,u7,u8@u8^ > u1,u6,u7,u8@u8 #3 | u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u4,u5,u8@u8^ > u1,u4,u5,u8@u8 > u1,u6,u7,u8@u8^ > u1,u6,u7,u8@u8 #3 | u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u4,u5,u8@u8^ > u1,u4,u5,u8@u8 > u1,u6,u7,u8@u8^ > u1,u6,u7,u8@u8 #3 | u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u4,u5,u8@u8^ > u1,u4,u5,u8@u8 > u1,u6,u7,u8@u8^ > u1,u6,u7,u8@u8 #3 | u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u4,u5,u8@u8^ > u1,u4,u5,u8@u8 > u1,u6,u7,u8@u8^ > u1,u6,u7,u8@u8 #3 | u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u4,u5,u8@u8^ > u1,u4,u5,u8@u8 > u1,u6,u7,u8@u8^ > u1,u6,u7,u8@u8 #3 | u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u4,u5,u8@u8^ > u1,u4,u5,u8@u8 > u1,u6,u7,u8@u8^ > u1,u6,u7,u8@u8 #3 | n/a',
    ('Upcoming', 'AAA, 2 others, pinned (0s)'): 'u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 #0 | u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 #0 | u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 #0 | u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 #0 | u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 #0 | u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 #0 | u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 #0 | u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 #0 | n/a',
    ('Upcoming', 'AAA, favourites only'): 'u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | n/a',
    ('Upcoming', 'AAA, 0 others'): 'u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | n/a',
    ('Upcoming', 'no favourites, 3 games, 60s'): 'u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 #0 | u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 #0 | u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 #0 | u1,u2,u3@u3 > u1,u2,u3@u3 > u4,u5,u6@u4^ > u4,u5,u6@u4 > u1,u7,u8@u1^ > u1,u2,u8@u1^ #3 | u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 #0 | u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 #0 | u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 #0 | u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 #0 | n/a',
    ('Upcoming', 'AAA, ranked, poll on the slate'): 'u1,u3,u4,u8@u8 > u1,u3,u4,u8@u8 > u1,u2,u4,u8@u8^ > u1,u2,u4,u8@u8 > u1,u2,u3,u8@u8^ > u1,u2,u3,u8@u8 #3 | u1,u3,u4,u8@u8 > u1,u3,u4,u8@u8 > u1,u2,u4,u8@u8^ > u1,u2,u4,u8@u8 > u1,u2,u3,u8@u8^ > u1,u2,u3,u8@u8 #3 | u1,u3,u4,u8@u8 > u1,u3,u4,u8@u8 > u1,u2,u4,u8@u8^ > u1,u2,u4,u8@u8 > u1,u2,u3,u8@u8^ > u1,u2,u3,u8@u8 #3 | u1,u3,u4,u8@u8 > u1,u3,u4,u8@u8 > u1,u2,u4,u8@u8^ > u1,u2,u4,u8@u8 > u1,u2,u3,u8@u8^ > u1,u2,u3,u8@u8 #3 | u1,u3,u4,u8@u8 > u1,u3,u4,u8@u8 > u1,u2,u4,u8@u8^ > u1,u2,u4,u8@u8 > u1,u2,u3,u8@u8^ > u1,u2,u3,u8@u8 #3 | u1,u3,u4,u8@u8 > u1,u3,u4,u8@u8 > u1,u2,u4,u8@u8^ > u1,u2,u4,u8@u8 > u1,u2,u3,u8@u8^ > u1,u2,u3,u8@u8 #3 | u1,u3,u4,u8@u8 > u1,u3,u4,u8@u8 > u1,u2,u4,u8@u8^ > u1,u2,u4,u8@u8 > u1,u2,u3,u8@u8^ > u1,u2,u3,u8@u8 #3 | u1,u3,u4,u8@u8 > u1,u3,u4,u8@u8 > u1,u2,u4,u8@u8^ > u1,u2,u4,u8@u8 > u1,u2,u3,u8@u8^ > u1,u2,u3,u8@u8 #3 | n/a',
    ('Upcoming', 'AAA, ranked, poll matches nothing'): 'u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | n/a',
    ('Upcoming', 'ZZZ not playing, ranked, poll matches nothing'): 'u1,u2@u2 > u1,u2@u2 > u3,u4@u3^ > u3,u4@u3 > u1,u2@u1^ > u3,u4@u3^ #3 | u1,u2@u2 > u1,u2@u2 > u3,u4@u3^ > u3,u4@u3 > u1,u2@u1^ > u3,u4@u3^ #3 | u1,u2@u2 > u1,u2@u2 > u3,u4@u3^ > u3,u4@u3 > u1,u2@u1^ > u3,u4@u3^ #3 | u1,u2@u2 > u1,u2@u2 > u3,u4@u3^ > u3,u4@u3 > u1,u2@u1^ > u3,u4@u3^ #3 | u1,u2@u2 > u1,u2@u2 > u3,u4@u3^ > u3,u4@u3 > u1,u2@u1^ > u3,u4@u3^ #3 | u1,u2@u2 > u1,u2@u2 > u3,u4@u3^ > u3,u4@u3 > u1,u2@u1^ > u3,u4@u3^ #3 | u1,u2@u2 > u1,u2@u2 > u3,u4@u3^ > u3,u4@u3 > u1,u2@u1^ > u3,u4@u3^ #3 | u1,u2@u2 > u1,u2@u2 > u3,u4@u3^ > u3,u4@u3 > u1,u2@u1^ > u3,u4@u3^ #3 | n/a',
    ('Recent', 'AAA, 2 others, 60s'): 'u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u4,u5,u8@u8^ > u1,u4,u5,u8@u8 > u1,u6,u7,u8@u8^ > u1,u6,u7,u8@u8 #3 | u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u4,u5,u8@u8^ > u1,u4,u5,u8@u8 > u1,u6,u7,u8@u8^ > u1,u6,u7,u8@u8 #3 | u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u4,u5,u8@u8^ > u1,u4,u5,u8@u8 > u1,u6,u7,u8@u8^ > u1,u6,u7,u8@u8 #3 | u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u4,u5,u8@u8^ > u1,u4,u5,u8@u8 > u1,u6,u7,u8@u8^ > u1,u6,u7,u8@u8 #3 | u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u4,u5,u8@u8^ > u1,u4,u5,u8@u8 > u1,u6,u7,u8@u8^ > u1,u6,u7,u8@u8 #3 | u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u4,u5,u8@u8^ > u1,u4,u5,u8@u8 > u1,u6,u7,u8@u8^ > u1,u6,u7,u8@u8 #3 | u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u4,u5,u8@u8^ > u1,u4,u5,u8@u8 > u1,u6,u7,u8@u8^ > u1,u6,u7,u8@u8 #3 | u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u4,u5,u8@u8^ > u1,u4,u5,u8@u8 > u1,u6,u7,u8@u8^ > u1,u6,u7,u8@u8 #3 | n/a',
    ('Recent', 'AAA, 2 others, pinned (0s)'): 'u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 #0 | u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 #0 | u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 #0 | u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 #0 | u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 #0 | u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 #0 | u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 #0 | u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 > u1,u2,u3,u8@u8 #0 | n/a',
    ('Recent', 'AAA, favourites only'): 'u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | n/a',
    ('Recent', 'AAA, 0 others'): 'u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | n/a',
    ('Recent', 'no favourites, 3 games, 60s'): 'u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 #0 | u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 #0 | u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 #0 | u1,u2,u3@u3 > u1,u2,u3@u3 > u4,u5,u6@u4^ > u4,u5,u6@u4 > u1,u7,u8@u1^ > u1,u2,u8@u1^ #3 | u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 #0 | u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 #0 | u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 #0 | u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 > u1,u2,u3@u3 #0 | n/a',
    ('Recent', 'AAA, ranked, poll on the slate'): 'u1,u3,u4,u8@u8 > u1,u3,u4,u8@u8 > u1,u2,u4,u8@u8^ > u1,u2,u4,u8@u8 > u1,u2,u3,u8@u8^ > u1,u2,u3,u8@u8 #3 | u1,u3,u4,u8@u8 > u1,u3,u4,u8@u8 > u1,u2,u4,u8@u8^ > u1,u2,u4,u8@u8 > u1,u2,u3,u8@u8^ > u1,u2,u3,u8@u8 #3 | u1,u3,u4,u8@u8 > u1,u3,u4,u8@u8 > u1,u2,u4,u8@u8^ > u1,u2,u4,u8@u8 > u1,u2,u3,u8@u8^ > u1,u2,u3,u8@u8 #3 | u1,u3,u4,u8@u8 > u1,u3,u4,u8@u8 > u1,u2,u4,u8@u8^ > u1,u2,u4,u8@u8 > u1,u2,u3,u8@u8^ > u1,u2,u3,u8@u8 #3 | u1,u3,u4,u8@u8 > u1,u3,u4,u8@u8 > u1,u2,u4,u8@u8^ > u1,u2,u4,u8@u8 > u1,u2,u3,u8@u8^ > u1,u2,u3,u8@u8 #3 | u1,u3,u4,u8@u8 > u1,u3,u4,u8@u8 > u1,u2,u4,u8@u8^ > u1,u2,u4,u8@u8 > u1,u2,u3,u8@u8^ > u1,u2,u3,u8@u8 #3 | u1,u3,u4,u8@u8 > u1,u3,u4,u8@u8 > u1,u2,u4,u8@u8^ > u1,u2,u4,u8@u8 > u1,u2,u3,u8@u8^ > u1,u2,u3,u8@u8 #3 | u1,u3,u4,u8@u8 > u1,u3,u4,u8@u8 > u1,u2,u4,u8@u8^ > u1,u2,u4,u8@u8 > u1,u2,u3,u8@u8^ > u1,u2,u3,u8@u8 #3 | n/a',
    ('Recent', 'AAA, ranked, poll matches nothing'): 'u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 > u1,u8@u8 #0 | n/a',
    ('Recent', 'ZZZ not playing, ranked, poll matches nothing'): 'u1,u2@u2 > u1,u2@u2 > u3,u4@u3^ > u3,u4@u3 > u1,u2@u1^ > u3,u4@u3^ #3 | u1,u2@u2 > u1,u2@u2 > u3,u4@u3^ > u3,u4@u3 > u1,u2@u1^ > u3,u4@u3^ #3 | u1,u2@u2 > u1,u2@u2 > u3,u4@u3^ > u3,u4@u3 > u1,u2@u1^ > u3,u4@u3^ #3 | u1,u2@u2 > u1,u2@u2 > u3,u4@u3^ > u3,u4@u3 > u1,u2@u1^ > u3,u4@u3^ #3 | u1,u2@u2 > u1,u2@u2 > u3,u4@u3^ > u3,u4@u3 > u1,u2@u1^ > u3,u4@u3^ #3 | u1,u2@u2 > u1,u2@u2 > u3,u4@u3^ > u3,u4@u3 > u1,u2@u1^ > u3,u4@u3^ #3 | u1,u2@u2 > u1,u2@u2 > u3,u4@u3^ > u3,u4@u3 > u1,u2@u1^ > u3,u4@u3^ #3 | u1,u2@u2 > u1,u2@u2 > u3,u4@u3^ > u3,u4@u3 > u1,u2@u1^ > u3,u4@u3^ #3 | n/a',
}

# case: windows the start moved once 61 s had passed, then games_list. The advance
# is under _games_lock, so display's lands after update's and skips nothing.
EXPECTED_INTERLEAVE = {
    'update': '1 window(s): u1,u4,u5,u8 | 1 window(s): u1,u4,u5,u8 | 1 window(s): u1,u4,u5,u8 | 1 window(s): u1,u4,u5,u8 | 1 window(s): u1,u4,u5,u8 | 1 window(s): u1,u4,u5,u8 | 1 window(s): u1,u4,u5,u8 | 1 window(s): u1,u4,u5,u8 | n/a',
    'update, then display': '1 window(s): u1,u4,u5,u8 | 1 window(s): u1,u4,u5,u8 | 1 window(s): u1,u4,u5,u8 | 1 window(s): u1,u4,u5,u8 | 1 window(s): u1,u4,u5,u8 | 1 window(s): u1,u4,u5,u8 | 1 window(s): u1,u4,u5,u8 | 1 window(s): u1,u4,u5,u8 | n/a',
    'display, then update': '1 window(s): u1,u4,u5,u8 | 1 window(s): u1,u4,u5,u8 | 1 window(s): u1,u4,u5,u8 | 1 window(s): u1,u4,u5,u8 | 1 window(s): u1,u4,u5,u8 | 1 window(s): u1,u4,u5,u8 | 1 window(s): u1,u4,u5,u8 | 1 window(s): u1,u4,u5,u8 | n/a',
    "display inside update's advance": '1 window(s): u1,u4,u5,u8 | 1 window(s): u1,u4,u5,u8 | 1 window(s): u1,u4,u5,u8 | 1 window(s): u1,u4,u5,u8 | 1 window(s): u1,u4,u5,u8 | 1 window(s): u1,u4,u5,u8 | 1 window(s): u1,u4,u5,u8 | 1 window(s): u1,u4,u5,u8 | n/a',
}

# case: the slice the display path swapped in ; the games in it that got odds.
# Rotated-in fights follow show_odds like every other fight (decided 2026-10-09).
EXPECTED_ODDS = {
    'odds manager': 'u1,u4,u5,u8 ; odds on u1,u4,u5,u8 | u1,u4,u5,u8 ; odds on u1,u4,u5,u8 | u1,u4,u5,u8 ; odds on u1,u4,u5,u8 | u1,u4,u5,u8 ; odds on u1,u4,u5,u8 | u1,u4,u5,u8 ; odds on u1,u4,u5,u8 | u1,u4,u5,u8 ; odds on u1,u4,u5,u8 | u1,u4,u5,u8 ; odds on u1,u4,u5,u8 | u1,u4,u5,u8 ; odds on u1,u4,u5,u8 | u1,u4,u5,u8 ; odds on u1,u4,u5,u8',
    'no odds manager': 'u1,u4,u5,u8 ; odds on none | u1,u4,u5,u8 ; odds on none | u1,u4,u5,u8 ; odds on none | u1,u4,u5,u8 ; odds on none | u1,u4,u5,u8 ; odds on none | u1,u4,u5,u8 ; odds on none | u1,u4,u5,u8 ; odds on none | u1,u4,u5,u8 ; odds on none | u1,u4,u5,u8 ; odds on none',
    'show_odds off': 'u1,u4,u5,u8 ; odds on none | u1,u4,u5,u8 ; odds on none | u1,u4,u5,u8 ; odds on none | u1,u4,u5,u8 ; odds on none | u1,u4,u5,u8 ; odds on none | u1,u4,u5,u8 ; odds on none | u1,u4,u5,u8 ; odds on none | u1,u4,u5,u8 ; odds on none | u1,u4,u5,u8 ; odds on none',
}

# favorite_rotation_boost: the next eight cards switch mode shows from index 0.
EXPECTED_BOOST = {
    1: 'u2,u3,u8,u1,u2,u3,u8,u1 | u2,u3,u8,u1,u2,u3,u8,u1 | u2,u3,u8,u1,u2,u3,u8,u1 | u2,u3,u8,u1,u2,u3,u8,u1 | u2,u3,u8,u1,u2,u3,u8,u1 | u2,u3,u8,u1,u2,u3,u8,u1 | u2,u3,u8,u1,u2,u3,u8,u1 | u2,u3,u8,u1,u2,u3,u8,u1 | n/a',
    2: 'u2,u8,u3,u1,u8,u1,u2,u8 | u2,u8,u3,u1,u8,u1,u2,u8 | u2,u8,u3,u1,u8,u1,u2,u8 | u2,u8,u3,u1,u8,u1,u2,u8 | u2,u8,u3,u1,u8,u1,u2,u8 | u2,u8,u3,u1,u8,u1,u2,u8 | u2,u8,u3,u1,u8,u1,u2,u8 | u2,u8,u3,u1,u8,u1,u2,u8 | n/a',
    3: 'u8,u2,u1,u8,u3,u1,u8,u1 | u8,u2,u1,u8,u3,u1,u8,u1 | u8,u2,u1,u8,u3,u1,u8,u1 | u8,u2,u1,u8,u3,u1,u8,u1 | u8,u2,u1,u8,u3,u1,u8,u1 | u8,u2,u1,u8,u3,u1,u8,u1 | u8,u2,u1,u8,u3,u1,u8,u1 | u8,u2,u1,u8,u3,u1,u8,u1 | n/a',
}


class Clock:
    """``time.monotonic`` and ``time.time``, frozen until a test moves them."""

    def __init__(self):
        self.now = T0

    def monotonic(self):
        return self.now

    def time(self):
        return self.now


CLOCK = Clock()


def ids(games):
    return ",".join("~" if g.get("id") is None else g["id"] for g in games) or "none"


def guarded(fn):
    try:
        return fn()
    except Exception as exc:                          # noqa: BLE001
        return f"!{type(exc).__name__}"


def manager(plugin, role, settings, rankings="none"):
    """The plugin's real manager, rotating every 60 s with two other slots
    unless ``settings`` says otherwise (``X`` in a key is the role)."""
    CLOCK.now = T0
    word = role.lower()
    config = {"other_rotation_interval_seconds": 60, "other_games_min_quality": "any",
              "other_games_divisions": [], f"{word}_games_to_show": 2,
              f"other_{word}_games_to_show": 2}
    config.update({k.replace("X", word): v for k, v in settings.items()})
    mgr = build(plugin, role, config)
    mgr._team_rankings_cache, mgr._ranked_team_ids = (dict(t) for t in RANKINGS[rankings])
    mgr._fetch_team_rankings = lambda *a, **k: None
    return mgr


def importance_row(plugin, rankings, newest_first):
    mgr = manager(plugin, "Upcoming", {}, rankings)
    return guarded(lambda: ids(mgr._by_importance(importance_slate(), newest_first)))


def pools_row(plugin, favorites, quality, divisions, rankings):
    mgr = manager(plugin, "Upcoming", {"favorite_teams": FAVORITES[favorites],
                                       "other_games_min_quality": quality}, rankings)
    if divisions:
        mgr.other_games_divisions = ["fbs"]
        mgr._load_division_team_ids = lambda: DIVISIONS
    slate = [game(*row) for row in UPDATE_SLATE]

    def run():
        picked = ids(mgr._favorites_first(slate, 2, 3))
        pools = mgr._selection_pools
        return f"{picked} ; {ids(pools['others'])} ; {ids(pools['unfiltered'])}"
    return guarded(run)


def window_row(plugin, size, limit, interval):
    mgr = manager(plugin, "Upcoming", {"other_rotation_interval_seconds": interval})
    pool = [{"id": f"o{n}"} for n in range(1, size + 1)]
    out = []
    for t in WINDOW_TIMES:
        CLOCK.now = T0 + t
        out.append(guarded(lambda: ids(mgr._other_games_window(pool, limit))))
    return " / ".join(out)


def updated(plugin, role, settings, rankings="none"):
    """A manager after the real update() over UPDATE_SLATE at T0, or None for ufc."""
    if plugin == "ufc":
        return None
    mgr = manager(plugin, role, settings, rankings)
    events = [game(*row, recent=role == "Recent",
                   status="final" if role == "Recent" else "upcoming") for row in UPDATE_SLATE]
    mgr._fetch_data = lambda *a, **k: {"events": [dict(g) for g in events]}
    mgr._extract_game_details = dict
    run_update(mgr, T0)
    return mgr


def run_update(mgr, at):
    CLOCK.now = at
    mgr.last_update = 0
    mgr.update()


def counting_composes(mgr):
    """Count _compose_selection calls from here on."""
    calls = []
    compose = mgr._compose_selection

    def counted():
        calls.append(1)
        return compose()
    mgr._compose_selection = counted
    return calls


def rotation_row(plugin, role, scenario):
    settings, rankings = ROTATION_SCENARIOS[scenario]

    def run():
        mgr = updated(plugin, role, settings, rankings)
        if mgr is None:
            return "n/a"
        calls = counting_composes(mgr)
        if mgr.games_list:                     # on screen: the last card
            mgr.current_game_index = len(mgr.games_list) - 1
            mgr.current_game = mgr.games_list[-1]

        def shown():
            return f"{ids(mgr.games_list)}@{(mgr.current_game or {}).get('id')}"
        lists = [shown()]
        for tick in TICKS:
            CLOCK.now = T0 + tick
            redraw = mgr._rotate_other_games_on_display()
            lists.append(shown() + ("^" if redraw else ""))
        return f"{' > '.join(lists)} #{len(calls)}"
    return guarded(run)


def racing(mgr, owner, threads):
    """Make ``mgr`` run display()'s rotation on a second thread the first time
    ``owner`` reads ``_other_window_start``. The only such read is the window's
    advance (``start += steps * width``), after update() has decided the
    interval elapsed and before it writes; the second thread either finishes
    first (no lock: both advance) or blocks on ``_games_lock`` until update()
    is done."""
    plain = type(mgr)

    class Interleaved(plain):
        @property
        def _other_window_start(self):
            if threading.get_ident() == owner and not threads:
                display = threading.Thread(
                    target=self._rotate_other_games_on_display, daemon=True)
                threads.append(display)
                display.start()
                display.join(2.0)      # it never finishes while blocked on the lock
            return self.__dict__.get("_other_window_start", 0)

        @_other_window_start.setter
        def _other_window_start(self, value):
            self.__dict__["_other_window_start"] = value

    mgr.__class__ = Interleaved
    return plain


def interleave_row(plugin, case):
    def run():
        mgr = updated(plugin, "Upcoming", ROTATION_SCENARIOS["AAA, 2 others, 60s"][0])
        if mgr is None:
            return "n/a"
        start = mgr._other_window_start
        later = T0 + 61
        if case == "update":
            run_update(mgr, later)
        elif case == "update, then display":
            run_update(mgr, later)
            mgr._rotate_other_games_on_display()
        elif case == "display, then update":
            CLOCK.now = later
            mgr._rotate_other_games_on_display()
            run_update(mgr, later)
        else:                                       # display inside update's advance
            threads = []
            plain = racing(mgr, threading.get_ident(), threads)
            try:
                run_update(mgr, later)
            finally:
                for t in threads:
                    t.join(10)
                mgr.__class__ = plain
            if not threads:
                return "!no advance"
        moved = (mgr._other_window_start - start) // 2
        return f"{moved} window(s): {ids(mgr.games_list)}"
    return guarded(run)


def odds_row(plugin, case):
    def run():
        mgr = manager(plugin, "Upcoming", {"favorite_teams": ["AAA"]})
        mgr._favorites_first([game(*row) for row in UPDATE_SLATE], 2, 2)
        mgr.games_list = list(mgr._compose_selection())
        mgr.show_odds = case != "show_odds off"
        if case == "no odds manager":
            mgr.odds_manager = None
        else:
            mgr.odds_manager = MagicMock()
            mgr.odds_manager.get_odds.side_effect = lambda **k: {"details": k["event_id"]}
        CLOCK.now = T0 + 61
        if not mgr._rotate_other_games_on_display():
            return "not rotated"
        for t in threading.enumerate():
            if t.name.endswith("-rotated-odds"):
                t.join(10)
        with_odds = [g for g in mgr.games_list if g.get("odds")]
        return f"{ids(mgr.games_list)} ; odds on {ids(with_odds)}"
    return guarded(run)


def boost_row(plugin, boost):
    def run():
        mgr = updated(plugin, "Upcoming", {"favorite_teams": ["AAA"],
                                           "favorite_rotation_boost": boost})
        if mgr is None:
            return "n/a"
        walk = []
        with mgr._games_lock:
            mgr.current_game_index = 0
            for _ in range(8):
                mgr.current_game_index = mgr._next_switch_index()
                walk.append(mgr.games_list[mgr.current_game_index]["id"])
        return ",".join(walk)
    return guarded(run)


FAMILY = ("_by_importance", "_other_games_window", "_advance_other_games_if_due",
          "_rotate_other_games_on_display", "_compose_selection", "_favorites_first",
          "_passes_other_filters", "_best_rank", "_attach_odds_to_rotated_games",
          "_next_switch_index")


def family_identity(cls):
    """Where each family method a class has is defined: {name: (file, qualname)}."""
    out = {}
    for name in FAMILY:
        fn = getattr(cls, name, None)
        if fn is not None:
            out[name] = (Path(fn.__code__.co_filename).name, fn.__qualname__)
    return out


def league_managers_agree(plugin):
    """Yield a problem for every league manager resolving the family elsewhere."""
    want = {role: family_identity(type(manager(plugin, role, {}))) for role in ROLES}
    pdir = REPO / "plugins" / f"{plugin}-scoreboard"
    for path in sorted(pdir.glob("*_managers.py")):
        mod = load(plugin, path.name)
        for name, cls in inspect.getmembers(mod, inspect.isclass):
            role = next((r for r in ROLES if name.endswith(f"{r}Manager")), None)
            if role and cls.__module__ == mod.__name__:
                got = family_identity(cls)
                for method in sorted(set(got) | set(want[role])):
                    if got.get(method) != want[role].get(method):
                        yield (f"{path.name}:{name}.{method} is {got.get(method)}, "
                               f"not {want[role].get(method)}")


def row(fn, *args):
    return " | ".join(fn(p, *args) for p in SPORTS)


def observe():
    """Every table as this checkout answers it, plus structural problems."""
    tables = {name: {} for name in EXPECTED}
    problems = []
    for plugin in SPORTS:
        problems += [f"{plugin}: {p}" for p in league_managers_agree(plugin)]
    for rankings in ("none", "abbr", "abbr tie", "ids only", "ids disagree"):
        for order, newest in (("soonest", False), ("newest", True)):
            tables["IMPORTANCE"][(rankings, order)] = row(importance_row, rankings, newest)
    for fav in FAVORITES:
        for quality in ("any", "ranked"):
            for divisions in ("", "fbs"):
                for rankings in ("none", "abbr", "ids only"):
                    tables["POOLS"][(fav, quality, divisions or "all", rankings)] = row(
                        pools_row, fav, quality, divisions, rankings)
    for size in (0, 1, 2, 7):
        for limit in (0, 2, 3):
            for interval in (0, 60):
                tables["WINDOW"][(size, limit, interval)] = row(window_row, size, limit, interval)
    for role in ROLES:
        for scenario in ROTATION_SCENARIOS:
            tables["ROTATION"][(role, scenario)] = row(rotation_row, role, scenario)
    for case in ("update", "update, then display", "display, then update",
                 "display inside update's advance"):
        tables["INTERLEAVE"][case] = row(interleave_row, case)
    for case in ("odds manager", "no odds manager", "show_odds off"):
        tables["ODDS"][case] = row(odds_row, case)
    for boost in (1, 2, 3):
        tables["BOOST"][boost] = row(boost_row, boost)
    return tables, problems


#: The committed tables by name, as `observe()` keys them.
EXPECTED = {
    "IMPORTANCE": EXPECTED_IMPORTANCE,
    "POOLS": EXPECTED_POOLS,
    "WINDOW": EXPECTED_WINDOW,
    "ROTATION": EXPECTED_ROTATION,
    "INTERLEAVE": EXPECTED_INTERLEAVE,
    "ODDS": EXPECTED_ODDS,
    "BOOST": EXPECTED_BOOST,
}


def print_tables(tables):
    for name, rows in tables.items():
        print(f"EXPECTED_{name} = {{")
        for key, value in rows.items():
            print(f"    {key!r}: {value!r},")
        print("}")


def main() -> int:
    core = core_root()
    if core is None:
        print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
        return 2
    sys.path.insert(0, str(core))
    logging.disable(logging.CRITICAL)
    os.chdir(core)  # the managers resolve fonts against the core

    with patch("requests.get", side_effect=OSError("no network in this test")), \
            patch("time.monotonic", CLOCK.monotonic), patch("time.time", CLOCK.time):
        try:
            tables, problems = observe()
        except Exception as exc:                      # noqa: BLE001
            print(f"  [FAIL] building the managers raised {type(exc).__name__}: {exc}")
            return 1
    if "--print" in sys.argv:
        print_tables(tables)
        return 0

    for name, observed in tables.items():
        problems += diff(name, EXPECTED[name], observed, changed_plugins)
    for p in problems:
        print(f"  [FAIL] {p}")
    if problems:
        return 1
    rows = sum(len(t) for t in tables.values())
    print(f"  [pass] {rows} other-games rotation rows across {len(SPORTS)} scoreboards")
    return 0


if __name__ == "__main__":
    sys.exit(main())
