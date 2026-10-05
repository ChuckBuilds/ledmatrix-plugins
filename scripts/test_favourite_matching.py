#!/usr/bin/env python3
"""What each scoreboard calls a favourite, and which games it then picks.

WHY THIS EXISTS
---------------
Favourite matching is family 6 of the sports consolidation (LEDMatrix
docs/SPORTS_UNIFICATION.md): ``_is_favorite_game`` (16 copies, 7 bodies across
SportsCore, SportsUpcoming and SportsLive), ``_select_games_for_display`` (2
bodies) and ``_select_recent_games_for_display`` (3), plus the helpers they
call (nrl's ``_team_in``; ``_is_favorite`` in the five live classes that have
it). Before those copies are reconciled onto the ``_favorite_key`` seam, the
tables below record what every plugin answers today, so the reconcile shows up
in its PR as a diff of them, cell by cell.

For each plugin it builds the primary league's real Upcoming, Recent and Live
managers (fake display and cache, no network), with ``favorite_teams`` set in
the config as a user would type it, so the plugin's own resolver runs first
(nrl's turns names and unique abbreviations into ESPN team ids; it is given a
recorded-shape team list in which NEW, as in the real NRL, is two clubs).
Then:

* ``IS_FAVORITE``: ``_is_favorite_game`` on each manager, for every favourites
  list x game shape. Cells are U, R, L (Upcoming, Recent, Live) per plugin.
* ``IS_FAVORITE_HELPER``: the live ``_is_favorite(value)`` helper (``-``: the
  plugin has none).
* ``FAVORITE_KEY``: core's ``_favorite_key`` seam as each plugin inherits it.
* ``SELECT``: the two selection methods over one shuffled slate, for every
  favourites list x per-team limit (``upcoming_games_to_show`` /
  ``recent_games_to_show``): the game ids picked, in order.
* ``UPDATE``: the real ``update()`` over a small slate, with
  ``show_favorite_teams_only`` on (it calls the selection method) and off (core's
  ``_favorites_first``, which asks ``_is_favorite_game``). ufc is ``n/a``:
  its MMA managers override ``update()`` and select by fighter.
* ``INFO_LOG``: whether each selection method logs its summary at INFO.

Every league's managers in a plugin must resolve to the same family methods,
so one league per plugin covers them all; that is checked too.

A cell is ``Y`` (favourite), ``.`` (not) or ``!`` (raised); a selection is the
picked ids, ``none`` for an empty pick, ``~`` for a game without an id. To see
the current tables after an intended change:

    python scripts/test_favourite_matching.py --print

Exit 0 pass, 2 skip (no core checkout), 1 fail.
"""
from __future__ import annotations

import inspect
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_game_over_check import LIVE_MANAGERS, diff  # noqa: E402
from test_sports_shared_methods import REPO, SPORTS, core_root, load  # noqa: E402

ROLES = ("Upcoming", "Recent", "Live")

#: plugin -> the config block its managers read (``mode_config``).
CONFIG_KEYS = {
    "afl": "afl_scoreboard", "baseball": "mlb_scoreboard",
    "basketball": "nba_scoreboard", "football": "nfl_scoreboard",
    "hockey": "nhl_scoreboard", "lacrosse": "ncaam_lacrosse_scoreboard",
    "nrl": "nrl_scoreboard", "soccer": "soccer_eng.1_scoreboard",
    "ufc": "ufc_scoreboard",
}

#: The teams every fixture uses: (id, abbreviation, name). nrl's resolver gets
#: them as its ESPN team list; NEW is a real NRL collision (Knights, Warriors).
TEAMS = (("1", "AAA", "Alpha Club"), ("2", "BBB", "Bravo Club"),
         ("3", "CCC", "Charlie Club"), ("4", "DDD", "Delta Club"),
         ("41", "NEW", "Newcastle Knights"), ("42", "NEW", "New Zealand Warriors"))
TEAM = {tid: abbr for tid, abbr, _ in TEAMS}
NRL_TEAMS_PAYLOAD = {"sports": [{"leagues": [{"teams": [
    {"team": {"id": tid, "abbreviation": abbr, "displayName": name}}
    for tid, abbr, name in TEAMS]}]}]}

#: label -> favorite_teams as configured.
FAVORITES = {
    "none": [],
    "abbr AAA": ["AAA"],
    "id 1": ["1"],
    "lower aaa": ["aaa"],
    "padded ' AAA '": [" AAA "],
    "two AAA,CCC": ["AAA", "CCC"],
    "colliding NEW": ["NEW"],
    "name Newcastle Knights": ["Newcastle Knights"],
    "id 41 (Knights)": ["41"],
    "unknown ZZZ": ["ZZZ"],
    "AAA + unknown ZZZ": ["AAA", "ZZZ"],
    "literal 'None'": ["None"],
}


def side(prefix, tid):
    return {f"{prefix}_id": tid, f"{prefix}_abbr": TEAM[tid]}


def match(home, away, **extra):
    g = {**side("home", home), **side("away", away)}
    g.update(extra)
    return g


#: label -> game, for _is_favorite_game.
GAMES = {
    "AAA home v BBB": match("1", "2"),
    "BBB home v AAA": match("2", "1"),
    "CCC v DDD": match("3", "4"),
    "Knights (NEW 41) v CCC": match("41", "3"),
    "Warriors (NEW 42) v CCC": match("42", "3"),
    "AAA v BBB, no ids": {"home_abbr": "AAA", "away_abbr": "BBB"},
    "ids 1 v 2, no abbrs": {"home_id": "1", "away_id": "2"},
    "AAA v BBB, int ids": match("1", "2", home_id=1, away_id=2),
    "empty game": {},
}

HELPER_FAVORITES = ("abbr AAA", "id 1", "colliding NEW", "name Newcastle Knights",
                    "literal 'None'")
HELPER_ARGS = {"'AAA'": "AAA", "'1'": "1", "'41'": "41", "None": None}

#: id, home, away, hours from now (None: no start time). Listed out of order;
#: both methods sort. Two games share id s2, and two have no id at all.
SLATE = (("s5", "41", "2", 5), ("s1", "1", "2", 1), ("s3", "4", "3", 3),
         ("s2", "3", "1", 2), ("s7", "2", "3", 7), ("s4", "1", "4", 4),
         ("s6", "42", "4", 6), ("s2", "1", "4", 8), ("s9", "1", "3", None),
         (None, "3", "1", 9), (None, "2", "1", 10))
SELECT_FAVORITES = ("none", "abbr AAA", "two AAA,CCC", "lower aaa", "colliding NEW",
                    "name Newcastle Knights", "id 41 (Knights)", "AAA + unknown ZZZ")
LIMITS = (1, 2, 5)
SELECT_METHODS = {"Upcoming": "_select_games_for_display",
                  "Recent": "_select_recent_games_for_display"}

UPDATE_FAVORITES = ("none", "abbr AAA", "two AAA,CCC", "colliding NEW",
                    "name Newcastle Knights")
#: id, home, away, hours from now -- the slate update() is given.
UPDATE_SLATE = (("u1", "1", "2", 1), ("u2", "3", "4", 2), ("u3", "2", "1", 3),
                ("u4", "41", "3", 4), ("u5", "4", "42", 5), ("u6", "1", "3", 6))

NOW = datetime.now(timezone.utc)

# --------------------------------------------------------------------------
# Expected (current) behaviour. Columns per plugin, in SPORTS order:
#   afl baseball basketball football hockey lacrosse nrl soccer ufc
# --------------------------------------------------------------------------
# (favourites, game): _is_favorite_game on the Upcoming, Recent, Live managers.
EXPECTED_IS_FAVORITE = {
    ('none', 'AAA home v BBB'): '... ... ... ... ... ... ... ... ...',
    ('none', 'BBB home v AAA'): '... ... ... ... ... ... ... ... ...',
    ('none', 'CCC v DDD'): '... ... ... ... ... ... ... ... ...',
    ('none', 'Knights (NEW 41) v CCC'): '... ... ... ... ... ... ... ... ...',
    ('none', 'Warriors (NEW 42) v CCC'): '... ... ... ... ... ... ... ... ...',
    ('none', 'AAA v BBB, no ids'): '... ... ... ... ... ... ... ... ...',
    ('none', 'ids 1 v 2, no abbrs'): '... ... ... ... ... ... ... ... ...',
    ('none', 'AAA v BBB, int ids'): '... ... ... ... ... ... ... ... ...',
    ('none', 'empty game'): '... ... ... ... ... ... ... ... ...',
    ('abbr AAA', 'AAA home v BBB'): 'YYY YYY YYY YYY YYY YYY YYY YYY YYY',
    ('abbr AAA', 'BBB home v AAA'): 'YYY YYY YYY YYY YYY YYY YYY YYY YYY',
    ('abbr AAA', 'CCC v DDD'): '... ... ... ... ... ... ... ... ...',
    ('abbr AAA', 'Knights (NEW 41) v CCC'): '... ... ... ... ... ... ... ... ...',
    ('abbr AAA', 'Warriors (NEW 42) v CCC'): '... ... ... ... ... ... ... ... ...',
    ('abbr AAA', 'AAA v BBB, no ids'): 'YYY YYY YYY YYY YYY YYY ... YYY YYY',
    ('abbr AAA', 'ids 1 v 2, no abbrs'): '... ... ... ... ... ... YYY ... ...',
    ('abbr AAA', 'AAA v BBB, int ids'): 'YYY YYY YYY YYY YYY YYY YYY YYY YYY',
    ('abbr AAA', 'empty game'): '... ... ... ... ... ... ... ... ...',
    ('id 1', 'AAA home v BBB'): '... ... ... ... ... ... YYY ... ...',
    ('id 1', 'BBB home v AAA'): '... ... ... ... ... ... YYY ... ...',
    ('id 1', 'CCC v DDD'): '... ... ... ... ... ... ... ... ...',
    ('id 1', 'Knights (NEW 41) v CCC'): '... ... ... ... ... ... ... ... ...',
    ('id 1', 'Warriors (NEW 42) v CCC'): '... ... ... ... ... ... ... ... ...',
    ('id 1', 'AAA v BBB, no ids'): '... ... ... ... ... ... ... ... ...',
    ('id 1', 'ids 1 v 2, no abbrs'): '... ... ... ... ... ... YYY ... ...',
    ('id 1', 'AAA v BBB, int ids'): '... ... ... ... ... ... YYY ... ...',
    ('id 1', 'empty game'): '... ... ... ... ... ... ... ... ...',
    ('lower aaa', 'AAA home v BBB'): '... ... ... ... ... ... YYY ... ...',
    ('lower aaa', 'BBB home v AAA'): '... ... ... ... ... ... YYY ... ...',
    ('lower aaa', 'CCC v DDD'): '... ... ... ... ... ... ... ... ...',
    ('lower aaa', 'Knights (NEW 41) v CCC'): '... ... ... ... ... ... ... ... ...',
    ('lower aaa', 'Warriors (NEW 42) v CCC'): '... ... ... ... ... ... ... ... ...',
    ('lower aaa', 'AAA v BBB, no ids'): '... ... ... ... ... ... ... ... ...',
    ('lower aaa', 'ids 1 v 2, no abbrs'): '... ... ... ... ... ... YYY ... ...',
    ('lower aaa', 'AAA v BBB, int ids'): '... ... ... ... ... ... YYY ... ...',
    ('lower aaa', 'empty game'): '... ... ... ... ... ... ... ... ...',
    ("padded ' AAA '", 'AAA home v BBB'): '... ... ... ... ... ... YYY ... ...',
    ("padded ' AAA '", 'BBB home v AAA'): '... ... ... ... ... ... YYY ... ...',
    ("padded ' AAA '", 'CCC v DDD'): '... ... ... ... ... ... ... ... ...',
    ("padded ' AAA '", 'Knights (NEW 41) v CCC'): '... ... ... ... ... ... ... ... ...',
    ("padded ' AAA '", 'Warriors (NEW 42) v CCC'): '... ... ... ... ... ... ... ... ...',
    ("padded ' AAA '", 'AAA v BBB, no ids'): '... ... ... ... ... ... ... ... ...',
    ("padded ' AAA '", 'ids 1 v 2, no abbrs'): '... ... ... ... ... ... YYY ... ...',
    ("padded ' AAA '", 'AAA v BBB, int ids'): '... ... ... ... ... ... YYY ... ...',
    ("padded ' AAA '", 'empty game'): '... ... ... ... ... ... ... ... ...',
    ('two AAA,CCC', 'AAA home v BBB'): 'YYY YYY YYY YYY YYY YYY YYY YYY YYY',
    ('two AAA,CCC', 'BBB home v AAA'): 'YYY YYY YYY YYY YYY YYY YYY YYY YYY',
    ('two AAA,CCC', 'CCC v DDD'): 'YYY YYY YYY YYY YYY YYY YYY YYY YYY',
    ('two AAA,CCC', 'Knights (NEW 41) v CCC'): 'YYY YYY YYY YYY YYY YYY YYY YYY YYY',
    ('two AAA,CCC', 'Warriors (NEW 42) v CCC'): 'YYY YYY YYY YYY YYY YYY YYY YYY YYY',
    ('two AAA,CCC', 'AAA v BBB, no ids'): 'YYY YYY YYY YYY YYY YYY ... YYY YYY',
    ('two AAA,CCC', 'ids 1 v 2, no abbrs'): '... ... ... ... ... ... YYY ... ...',
    ('two AAA,CCC', 'AAA v BBB, int ids'): 'YYY YYY YYY YYY YYY YYY YYY YYY YYY',
    ('two AAA,CCC', 'empty game'): '... ... ... ... ... ... ... ... ...',
    ('colliding NEW', 'AAA home v BBB'): '... ... ... ... ... ... ... ... ...',
    ('colliding NEW', 'BBB home v AAA'): '... ... ... ... ... ... ... ... ...',
    ('colliding NEW', 'CCC v DDD'): '... ... ... ... ... ... ... ... ...',
    ('colliding NEW', 'Knights (NEW 41) v CCC'): 'YYY YYY YYY YYY YYY YYY ... YYY YYY',
    ('colliding NEW', 'Warriors (NEW 42) v CCC'): 'YYY YYY YYY YYY YYY YYY ... YYY YYY',
    ('colliding NEW', 'AAA v BBB, no ids'): '... ... ... ... ... ... ... ... ...',
    ('colliding NEW', 'ids 1 v 2, no abbrs'): '... ... ... ... ... ... ... ... ...',
    ('colliding NEW', 'AAA v BBB, int ids'): '... ... ... ... ... ... ... ... ...',
    ('colliding NEW', 'empty game'): '... ... ... ... ... ... ... ... ...',
    ('name Newcastle Knights', 'AAA home v BBB'): '... ... ... ... ... ... ... ... ...',
    ('name Newcastle Knights', 'BBB home v AAA'): '... ... ... ... ... ... ... ... ...',
    ('name Newcastle Knights', 'CCC v DDD'): '... ... ... ... ... ... ... ... ...',
    ('name Newcastle Knights', 'Knights (NEW 41) v CCC'): '... ... ... ... ... ... YYY ... ...',
    ('name Newcastle Knights', 'Warriors (NEW 42) v CCC'): '... ... ... ... ... ... ... ... ...',
    ('name Newcastle Knights', 'AAA v BBB, no ids'): '... ... ... ... ... ... ... ... ...',
    ('name Newcastle Knights', 'ids 1 v 2, no abbrs'): '... ... ... ... ... ... ... ... ...',
    ('name Newcastle Knights', 'AAA v BBB, int ids'): '... ... ... ... ... ... ... ... ...',
    ('name Newcastle Knights', 'empty game'): '... ... ... ... ... ... ... ... ...',
    ('id 41 (Knights)', 'AAA home v BBB'): '... ... ... ... ... ... ... ... ...',
    ('id 41 (Knights)', 'BBB home v AAA'): '... ... ... ... ... ... ... ... ...',
    ('id 41 (Knights)', 'CCC v DDD'): '... ... ... ... ... ... ... ... ...',
    ('id 41 (Knights)', 'Knights (NEW 41) v CCC'): '... ... ... ... ... ... YYY ... ...',
    ('id 41 (Knights)', 'Warriors (NEW 42) v CCC'): '... ... ... ... ... ... ... ... ...',
    ('id 41 (Knights)', 'AAA v BBB, no ids'): '... ... ... ... ... ... ... ... ...',
    ('id 41 (Knights)', 'ids 1 v 2, no abbrs'): '... ... ... ... ... ... ... ... ...',
    ('id 41 (Knights)', 'AAA v BBB, int ids'): '... ... ... ... ... ... ... ... ...',
    ('id 41 (Knights)', 'empty game'): '... ... ... ... ... ... ... ... ...',
    ('unknown ZZZ', 'AAA home v BBB'): '... ... ... ... ... ... ... ... ...',
    ('unknown ZZZ', 'BBB home v AAA'): '... ... ... ... ... ... ... ... ...',
    ('unknown ZZZ', 'CCC v DDD'): '... ... ... ... ... ... ... ... ...',
    ('unknown ZZZ', 'Knights (NEW 41) v CCC'): '... ... ... ... ... ... ... ... ...',
    ('unknown ZZZ', 'Warriors (NEW 42) v CCC'): '... ... ... ... ... ... ... ... ...',
    ('unknown ZZZ', 'AAA v BBB, no ids'): '... ... ... ... ... ... ... ... ...',
    ('unknown ZZZ', 'ids 1 v 2, no abbrs'): '... ... ... ... ... ... ... ... ...',
    ('unknown ZZZ', 'AAA v BBB, int ids'): '... ... ... ... ... ... ... ... ...',
    ('unknown ZZZ', 'empty game'): '... ... ... ... ... ... ... ... ...',
    ('AAA + unknown ZZZ', 'AAA home v BBB'): 'YYY YYY YYY YYY YYY YYY YYY YYY YYY',
    ('AAA + unknown ZZZ', 'BBB home v AAA'): 'YYY YYY YYY YYY YYY YYY YYY YYY YYY',
    ('AAA + unknown ZZZ', 'CCC v DDD'): '... ... ... ... ... ... ... ... ...',
    ('AAA + unknown ZZZ', 'Knights (NEW 41) v CCC'): '... ... ... ... ... ... ... ... ...',
    ('AAA + unknown ZZZ', 'Warriors (NEW 42) v CCC'): '... ... ... ... ... ... ... ... ...',
    ('AAA + unknown ZZZ', 'AAA v BBB, no ids'): 'YYY YYY YYY YYY YYY YYY ... YYY YYY',
    ('AAA + unknown ZZZ', 'ids 1 v 2, no abbrs'): '... ... ... ... ... ... YYY ... ...',
    ('AAA + unknown ZZZ', 'AAA v BBB, int ids'): 'YYY YYY YYY YYY YYY YYY YYY YYY YYY',
    ('AAA + unknown ZZZ', 'empty game'): '... ... ... ... ... ... ... ... ...',
    ("literal 'None'", 'AAA home v BBB'): '... ... ... ... ... ... ... ... ...',
    ("literal 'None'", 'BBB home v AAA'): '... ... ... ... ... ... ... ... ...',
    ("literal 'None'", 'CCC v DDD'): '... ... ... ... ... ... ... ... ...',
    ("literal 'None'", 'Knights (NEW 41) v CCC'): '... ... ... ... ... ... ... ... ...',
    ("literal 'None'", 'Warriors (NEW 42) v CCC'): '... ... ... ... ... ... ... ... ...',
    ("literal 'None'", 'AAA v BBB, no ids'): '... ... ... ... ... ... YYY ... ...',
    ("literal 'None'", 'ids 1 v 2, no abbrs'): '... ... ... ... ... ... ... ... ...',
    ("literal 'None'", 'AAA v BBB, int ids'): '... ... ... ... ... ... ... ... ...',
    ("literal 'None'", 'empty game'): '... ... ... ... ... ... YYY ... ...',
}
# (favourites, argument): the live manager's _is_favorite(argument).
EXPECTED_IS_FAVORITE_HELPER = {
    ('abbr AAA', "'AAA'"): 'YY-YY-.Y-',
    ('abbr AAA', "'1'"): '..-..-Y.-',
    ('abbr AAA', "'41'"): '..-..-..-',
    ('abbr AAA', 'None'): '..-..-..-',
    ('id 1', "'AAA'"): '..-..-..-',
    ('id 1', "'1'"): 'YY-YY-YY-',
    ('id 1', "'41'"): '..-..-..-',
    ('id 1', 'None'): '..-..-..-',
    ('colliding NEW', "'AAA'"): '..-..-..-',
    ('colliding NEW', "'1'"): '..-..-..-',
    ('colliding NEW', "'41'"): '..-..-..-',
    ('colliding NEW', 'None'): '..-..-..-',
    ('name Newcastle Knights', "'AAA'"): '..-..-..-',
    ('name Newcastle Knights', "'1'"): '..-..-..-',
    ('name Newcastle Knights', "'41'"): '..-..-Y.-',
    ('name Newcastle Knights', 'None'): '..-..-..-',
    ("literal 'None'", "'AAA'"): '..-..-..-',
    ("literal 'None'", "'1'"): '..-..-..-',
    ("literal 'None'", "'41'"): '..-..-..-',
    ("literal 'None'", 'None'): '..-..-Y.-',
}
# (game, side): _favorite_key(game, side). Core's default; no plugin overrides it.
EXPECTED_FAVORITE_KEY = {
    ('AAA home v BBB', 'home'): "'AAA' | 'AAA' | 'AAA' | 'AAA' | 'AAA' | 'AAA' | 'AAA' | 'AAA' | 'AAA'",
    ('AAA home v BBB', 'away'): "'BBB' | 'BBB' | 'BBB' | 'BBB' | 'BBB' | 'BBB' | 'BBB' | 'BBB' | 'BBB'",
    ('Knights (NEW 41) v CCC', 'home'): "'NEW' | 'NEW' | 'NEW' | 'NEW' | 'NEW' | 'NEW' | 'NEW' | 'NEW' | 'NEW'",
    ('Knights (NEW 41) v CCC', 'away'): "'CCC' | 'CCC' | 'CCC' | 'CCC' | 'CCC' | 'CCC' | 'CCC' | 'CCC' | 'CCC'",
    ('ids 1 v 2, no abbrs', 'home'): 'None | None | None | None | None | None | None | None | None',
    ('ids 1 v 2, no abbrs', 'away'): 'None | None | None | None | None | None | None | None | None',
}
# (role, favourites, per-team limit): the selection method's picks over SLATE.
EXPECTED_SELECT = {
    ('Upcoming', 'none', 1): 's1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9',
    ('Upcoming', 'none', 2): 's1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9',
    ('Upcoming', 'none', 5): 's1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9',
    ('Upcoming', 'abbr AAA', 1): 's1 | s1 | s1 | s1 | s1 | s1 | s1 | s1 | s1',
    ('Upcoming', 'abbr AAA', 2): 's1,s2 | s1,s2 | s1,s2 | s1,s2 | s1,s2 | s1,s2 | s1,s2 | s1,s2 | s1,s2',
    ('Upcoming', 'abbr AAA', 5): 's1,s2,s4,~,s9 | s1,s2,s4,~,s9 | s1,s2,s4,~,s9 | s1,s2,s4,~,s9 | s1,s2,s4,~,s9 | s1,s2,s4,~,s9 | s1,s2,s4,~,s9 | s1,s2,s4,~,s9 | s1,s2,s4,~,s9',
    ('Upcoming', 'two AAA,CCC', 1): 's1,s2 | s1,s2 | s1,s2 | s1,s2 | s1,s2 | s1,s2 | s1,s2 | s1,s2 | s1,s2',
    ('Upcoming', 'two AAA,CCC', 2): 's1,s2,s3 | s1,s2,s3 | s1,s2,s3 | s1,s2,s3 | s1,s2,s3 | s1,s2,s3 | s1,s2,s3 | s1,s2,s3 | s1,s2,s3',
    ('Upcoming', 'two AAA,CCC', 5): 's1,s2,s3,s4,s7,~,s9 | s1,s2,s3,s4,s7,~,s9 | s1,s2,s3,s4,s7,~,s9 | s1,s2,s3,s4,s7,~,s9 | s1,s2,s3,s4,s7,~,s9 | s1,s2,s3,s4,s7,~,s9 | s1,s2,s3,s4,s7,~,s9 | s1,s2,s3,s4,s7,~,s9 | s1,s2,s3,s4,s7,~,s9',
    ('Upcoming', 'lower aaa', 1): 'none | none | none | none | none | none | s1 | none | none',
    ('Upcoming', 'lower aaa', 2): 'none | none | none | none | none | none | s1,s2 | none | none',
    ('Upcoming', 'lower aaa', 5): 'none | none | none | none | none | none | s1,s2,s4,~,s9 | none | none',
    ('Upcoming', 'colliding NEW', 1): 's5 | s5 | s5 | s5 | s5 | s5 | none | s5 | s5',
    ('Upcoming', 'colliding NEW', 2): 's5,s6 | s5,s6 | s5,s6 | s5,s6 | s5,s6 | s5,s6 | none | s5,s6 | s5,s6',
    ('Upcoming', 'colliding NEW', 5): 's5,s6 | s5,s6 | s5,s6 | s5,s6 | s5,s6 | s5,s6 | none | s5,s6 | s5,s6',
    ('Upcoming', 'name Newcastle Knights', 1): 'none | none | none | none | none | none | s5 | none | none',
    ('Upcoming', 'name Newcastle Knights', 2): 'none | none | none | none | none | none | s5 | none | none',
    ('Upcoming', 'name Newcastle Knights', 5): 'none | none | none | none | none | none | s5 | none | none',
    ('Upcoming', 'id 41 (Knights)', 1): 'none | none | none | none | none | none | s5 | none | none',
    ('Upcoming', 'id 41 (Knights)', 2): 'none | none | none | none | none | none | s5 | none | none',
    ('Upcoming', 'id 41 (Knights)', 5): 'none | none | none | none | none | none | s5 | none | none',
    ('Upcoming', 'AAA + unknown ZZZ', 1): 's1 | s1 | s1 | s1 | s1 | s1 | s1 | s1 | s1',
    ('Upcoming', 'AAA + unknown ZZZ', 2): 's1,s2 | s1,s2 | s1,s2 | s1,s2 | s1,s2 | s1,s2 | s1,s2 | s1,s2 | s1,s2',
    ('Upcoming', 'AAA + unknown ZZZ', 5): 's1,s2,s4,~,s9 | s1,s2,s4,~,s9 | s1,s2,s4,~,s9 | s1,s2,s4,~,s9 | s1,s2,s4,~,s9 | s1,s2,s4,~,s9 | s1,s2,s4,~,s9 | s1,s2,s4,~,s9 | s1,s2,s4,~,s9',
    ('Recent', 'none', 1): 's1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9',
    ('Recent', 'none', 2): 's1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9',
    ('Recent', 'none', 5): 's1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9 | s1,s2,s3,s4,s5,s6,s7,s2,~,~,s9',
    ('Recent', 'abbr AAA', 1): 's1 | s1 | s1 | s1 | s1 | s1 | s1 | s1 | s1',
    ('Recent', 'abbr AAA', 2): 's1,s2 | s1,s2 | s1,s2 | s1,s2 | s1,s2 | s1,s2 | s1,s2 | s1,s2 | s1,s2',
    ('Recent', 'abbr AAA', 5): 's1,s2,s4,~,s9 | s1,s2,s4,~,s9 | s1,s2,s4,~,s9 | s1,s2,s4,~,s9 | s1,s2,s4,~,s9 | s1,s2,s4,~,s9 | s1,s2,s4,~,s9 | s1,s2,s4,~,s9 | s1,s2,s4,~,s9',
    ('Recent', 'two AAA,CCC', 1): 's1,s2 | s1,s2 | s1,s2 | s1,s2 | s1,s2 | s1,s2 | s1,s2 | s1,s2 | s1,s2',
    ('Recent', 'two AAA,CCC', 2): 's1,s2,s3 | s1,s2,s3 | s1,s2,s3 | s1,s2,s3 | s1,s2,s3 | s1,s2,s3 | s1,s2,s3 | s1,s2,s3 | s1,s2,s3',
    ('Recent', 'two AAA,CCC', 5): 's1,s2,s3,s4,s7,~,s9 | s1,s2,s3,s4,s7,~,s9 | s1,s2,s3,s4,s7,~,s9 | s1,s2,s3,s4,s7,~,s9 | s1,s2,s3,s4,s7,~,s9 | s1,s2,s3,s4,s7,~,s9 | s1,s2,s3,s4,s7,~,s9 | s1,s2,s3,s4,s7,~,s9 | s1,s2,s3,s4,s7,~,s9',
    ('Recent', 'lower aaa', 1): 'none | none | none | none | none | none | s1 | none | none',
    ('Recent', 'lower aaa', 2): 'none | none | none | none | none | none | s1,s2 | none | none',
    ('Recent', 'lower aaa', 5): 'none | none | none | none | none | none | s1,s2,s4,~,s9 | none | none',
    ('Recent', 'colliding NEW', 1): 's5 | s5 | s5 | s5 | s5 | s5 | none | s5 | s5',
    ('Recent', 'colliding NEW', 2): 's5,s6 | s5,s6 | s5,s6 | s5,s6 | s5,s6 | s5,s6 | none | s5,s6 | s5,s6',
    ('Recent', 'colliding NEW', 5): 's5,s6 | s5,s6 | s5,s6 | s5,s6 | s5,s6 | s5,s6 | none | s5,s6 | s5,s6',
    ('Recent', 'name Newcastle Knights', 1): 'none | none | none | none | none | none | s5 | none | none',
    ('Recent', 'name Newcastle Knights', 2): 'none | none | none | none | none | none | s5 | none | none',
    ('Recent', 'name Newcastle Knights', 5): 'none | none | none | none | none | none | s5 | none | none',
    ('Recent', 'id 41 (Knights)', 1): 'none | none | none | none | none | none | s5 | none | none',
    ('Recent', 'id 41 (Knights)', 2): 'none | none | none | none | none | none | s5 | none | none',
    ('Recent', 'id 41 (Knights)', 5): 'none | none | none | none | none | none | s5 | none | none',
    ('Recent', 'AAA + unknown ZZZ', 1): 's1 | s1 | s1 | s1 | s1 | s1 | s1 | s1 | s1',
    ('Recent', 'AAA + unknown ZZZ', 2): 's1,s2 | s1,s2 | s1,s2 | s1,s2 | s1,s2 | s1,s2 | s1,s2 | s1,s2 | s1,s2',
    ('Recent', 'AAA + unknown ZZZ', 5): 's1,s2,s4,~,s9 | s1,s2,s4,~,s9 | s1,s2,s4,~,s9 | s1,s2,s4,~,s9 | s1,s2,s4,~,s9 | s1,s2,s4,~,s9 | s1,s2,s4,~,s9 | s1,s2,s4,~,s9 | s1,s2,s4,~,s9',
}
# (role, favourites, show_favorite_teams_only): update()'s games_list over
# UPDATE_SLATE, with a per-team limit of 2 and room for 1 other game.
EXPECTED_UPDATE = {
    ('Upcoming', 'none', 'only'): 'u1,u2 | u1,u2 | u1,u2 | u1,u2 | u1,u2 | u1,u2 | u1,u2 | u1,u2 | n/a',
    ('Upcoming', 'none', 'not only'): 'u1,u2 | u1,u2 | u1,u2 | u1,u2 | u1,u2 | u1,u2 | u1,u2 | u1,u2 | n/a',
    ('Upcoming', 'abbr AAA', 'only'): 'u1,u3 | u1,u3 | u1,u3 | u1,u3 | u1,u3 | u1,u3 | u1,u3 | u1,u3 | n/a',
    ('Upcoming', 'abbr AAA', 'not only'): 'u1,u2,u3 | u1,u2,u3 | u1,u2,u3 | u1,u2,u3 | u1,u2,u3 | u1,u2,u3 | u1,u2,u3 | u1,u2,u3 | n/a',
    ('Upcoming', 'two AAA,CCC', 'only'): 'u1,u2,u3,u4 | u1,u2,u3,u4 | u1,u2,u3,u4 | u1,u2,u3,u4 | u1,u2,u3,u4 | u1,u2,u3,u4 | u1,u2,u3,u4 | u1,u2,u3,u4 | n/a',
    ('Upcoming', 'two AAA,CCC', 'not only'): 'u1,u2,u5 | u1,u2,u5 | u1,u2,u5 | u1,u2,u5 | u1,u2,u5 | u1,u2,u5 | u1,u2,u5 | u1,u2,u5 | n/a',
    ('Upcoming', 'colliding NEW', 'only'): 'u4,u5 | u4,u5 | u4,u5 | u4,u5 | u4,u5 | u4,u5 | none | u4,u5 | n/a',
    ('Upcoming', 'colliding NEW', 'not only'): 'u1,u4,u5 | u1,u4,u5 | u1,u4,u5 | u1,u4,u5 | u1,u4,u5 | u1,u4,u5 | u1 | u1,u4,u5 | n/a',
    ('Upcoming', 'name Newcastle Knights', 'only'): 'none | none | none | none | none | none | u4 | none | n/a',
    ('Upcoming', 'name Newcastle Knights', 'not only'): 'u1 | u1 | u1 | u1 | u1 | u1 | u1,u4 | u1 | n/a',
    ('Recent', 'none', 'only'): 'u1,u2 | u1,u2 | u1,u2 | u1,u2 | u1,u2 | u1,u2 | u1,u2 | u1,u2 | n/a',
    ('Recent', 'none', 'not only'): 'u1,u2 | u1,u2 | u1,u2 | u1,u2 | u1,u2 | u1,u2 | u1,u2 | u1,u2 | n/a',
    ('Recent', 'abbr AAA', 'only'): 'u1,u3 | u1,u3 | u1,u3 | u1,u3 | u1,u3 | u1,u3 | u1,u3 | u1,u3 | n/a',
    ('Recent', 'abbr AAA', 'not only'): 'u1,u2,u3 | u1,u2,u3 | u1,u2,u3 | u1,u2,u3 | u1,u2,u3 | u1,u2,u3 | u1,u2,u3 | u1,u2,u3 | n/a',
    ('Recent', 'two AAA,CCC', 'only'): 'u1,u2,u3,u4 | u1,u2,u3,u4 | u1,u2,u3,u4 | u1,u2,u3,u4 | u1,u2,u3,u4 | u1,u2,u3,u4 | u1,u2,u3,u4 | u1,u2,u3,u4 | n/a',
    ('Recent', 'two AAA,CCC', 'not only'): 'u1,u2,u5 | u1,u2,u5 | u1,u2,u5 | u1,u2,u5 | u1,u2,u5 | u1,u2,u5 | u1,u2,u5 | u1,u2,u5 | n/a',
    ('Recent', 'colliding NEW', 'only'): 'u4,u5 | u4,u5 | u4,u5 | u4,u5 | u4,u5 | u4,u5 | none | u4,u5 | n/a',
    ('Recent', 'colliding NEW', 'not only'): 'u1,u4,u5 | u1,u4,u5 | u1,u4,u5 | u1,u4,u5 | u1,u4,u5 | u1,u4,u5 | u1 | u1,u4,u5 | n/a',
    ('Recent', 'name Newcastle Knights', 'only'): 'none | none | none | none | none | none | u4 | none | n/a',
    ('Recent', 'name Newcastle Knights', 'not only'): 'u1 | u1 | u1 | u1 | u1 | u1 | u1,u4 | u1 | n/a',
}
# role: whether the selection method logs its summary at INFO.
EXPECTED_INFO_LOG = {
    'Upcoming': 'YYYYYYYYY',
    'Recent': 'Y.Y.YYYY.',
}


def slate_games(slate, recent):
    """The slate as view-model games: upcoming ahead of now, recent behind it."""
    sign = -1 if recent else 1
    games = []
    for gid, home, away, hours in slate:
        g = match(home, away, id=gid, home_score="10", away_score="20",
                  is_upcoming=not recent, is_final=recent, is_live=False)
        if hours is not None:
            g["start_time_utc"] = NOW + timedelta(hours=sign * hours)
        games.append(g)
    return games


_MODULES = {}


def build(plugin, role, mode_config):
    """The plugin's primary-league manager for ``role``, configured as given."""
    module, live_name, extra = LIVE_MANAGERS[plugin]
    if plugin not in _MODULES:
        _MODULES[plugin] = load(plugin, module)
    cls = getattr(_MODULES[plugin], live_name.replace("Live", role))
    sports_core = next(c for c in cls.__mro__ if c.__name__ == "SportsCore")
    resolver = sports_core.__init__.__globals__.get("DynamicTeamResolver")
    if hasattr(resolver, "_build_index"):           # nrl: seed its team list
        resolver._teams_index_cache["nrl"] = resolver._build_index(NRL_TEAMS_PAYLOAD)
        resolver._teams_index_timestamp["nrl"] = time.time()
    display = MagicMock()
    display.width, display.height = 128, 32
    display.matrix.width, display.matrix.height = 128, 32
    cache = MagicMock()
    cache.get.return_value = None
    config = {"timezone": "UTC",
              CONFIG_KEYS[plugin]: {"enabled": True, "show_odds": False, **mode_config}}
    return cls(config, display, cache, *extra)


def family_identity(cls):
    """Where each family method a class has is defined: {name: (file, qualname)}."""
    out = {}
    for name in ("_is_favorite_game", "_is_favorite", "_favorite_key", *SELECT_METHODS.values()):
        fn = getattr(cls, name, None)
        if fn is not None:
            out[name] = (Path(fn.__code__.co_filename).name, fn.__qualname__)
    return out


def league_managers_agree(plugin, chosen):
    """Yield a problem for every league manager whose family methods differ from ``chosen``'s."""
    pdir = REPO / "plugins" / f"{plugin}-scoreboard"
    for path in sorted(pdir.glob("*_managers.py")):
        mod = load(plugin, path.name)
        for name, cls in inspect.getmembers(mod, inspect.isclass):
            role = next((r for r in ROLES if name.endswith(f"{r}Manager")), None)
            if role and cls.__module__ == mod.__name__:
                want, got = family_identity(type(chosen[role])), family_identity(cls)
                if got != want:
                    yield f"{path.name}:{name} resolves {got}, not {want}"


def cell(fn, *args):
    try:
        return "Y" if fn(*args) else "."
    except Exception:                                 # noqa: BLE001
        return "!"


def picked(games):
    return ",".join("~" if g.get("id") is None else g["id"] for g in games) or "none"


def select(mgr, role, limit, games):
    setattr(mgr, f"{role.lower()}_games_to_show", limit)
    try:
        return picked(getattr(mgr, SELECT_METHODS[role])(
            [dict(g) for g in games], mgr.favorite_teams))
    except Exception as exc:                          # noqa: BLE001
        return f"!{type(exc).__name__}"


def logs_info(mgr, role):
    """Whether the selection method emits an INFO record of its own."""
    records = []
    handler = logging.Handler(logging.INFO)
    handler.emit = records.append
    level, propagate = mgr.logger.level, mgr.logger.propagate
    mgr.logger.addHandler(handler)
    mgr.logger.setLevel(logging.INFO)
    mgr.logger.propagate = False
    logging.disable(logging.NOTSET)
    try:
        select(mgr, role, 1, slate_games(SLATE, role == "Recent"))
    finally:
        logging.disable(logging.CRITICAL)
        mgr.logger.removeHandler(handler)
        mgr.logger.setLevel(level)
        mgr.logger.propagate = propagate
    name = SELECT_METHODS[role]
    return "Y" if any(r.levelno == logging.INFO and r.funcName == name for r in records) else "."


def run_update(plugin, role, favorites, only):
    if plugin == "ufc":
        return "n/a"
    mgr = build(plugin, role, {
        "favorite_teams": FAVORITES[favorites], "show_favorite_teams_only": only,
        f"{role.lower()}_games_to_show": 2, f"other_{role.lower()}_games_to_show": 1,
        "other_games_min_quality": "any"})
    games = slate_games(UPDATE_SLATE, role == "Recent")
    mgr._fetch_data = lambda *a, **k: {"events": [dict(g) for g in games]}
    mgr._extract_game_details = dict
    mgr.last_update = 0
    try:
        mgr.update()
    except Exception as exc:                          # noqa: BLE001
        return f"!{type(exc).__name__}"
    return picked(mgr.games_list)


def observe():
    """Every table as this checkout answers it, plus structural problems."""
    tables = {name: {} for name in ("IS_FAVORITE", "IS_FAVORITE_HELPER", "FAVORITE_KEY",
                                    "SELECT", "UPDATE", "INFO_LOG")}
    problems = []
    managers = {}                    # (plugin, favorites label) -> {role: manager}
    for plugin in SPORTS:
        for label, favs in FAVORITES.items():
            managers[plugin, label] = {
                role: build(plugin, role, {"favorite_teams": favs}) for role in ROLES}
        problems += [f"{plugin}: {p}"
                     for p in league_managers_agree(plugin, managers[plugin, "none"])]

    for fav in FAVORITES:
        for game_label, game in GAMES.items():
            tables["IS_FAVORITE"][(fav, game_label)] = " ".join(
                "".join(cell(managers[p, fav][r]._is_favorite_game, dict(game)) for r in ROLES)
                for p in SPORTS)
    for fav in HELPER_FAVORITES:
        for arg_label, arg in HELPER_ARGS.items():
            live = [managers[p, fav]["Live"] for p in SPORTS]
            tables["IS_FAVORITE_HELPER"][(fav, arg_label)] = "".join(
                cell(m._is_favorite, arg) if hasattr(m, "_is_favorite") else "-" for m in live)
    for game_label in ("AAA home v BBB", "Knights (NEW 41) v CCC", "ids 1 v 2, no abbrs"):
        for s in ("home", "away"):
            tables["FAVORITE_KEY"][(game_label, s)] = " | ".join(
                repr(managers[p, "none"]["Live"]._favorite_key(dict(GAMES[game_label]), s))
                for p in SPORTS)
    for role in SELECT_METHODS:
        games = slate_games(SLATE, role == "Recent")
        for fav in SELECT_FAVORITES:
            for limit in LIMITS:
                tables["SELECT"][(role, fav, limit)] = " | ".join(
                    select(managers[p, fav][role], role, limit, games) for p in SPORTS)
        tables["INFO_LOG"][role] = "".join(
            logs_info(managers[p, "abbr AAA"][role], role) for p in SPORTS)
        for fav in UPDATE_FAVORITES:
            for only in (True, False):
                tables["UPDATE"][(role, fav, "only" if only else "not only")] = " | ".join(
                    run_update(p, role, fav, only) for p in SPORTS)
    return tables, problems


#: The committed tables by name, as `observe()` keys them.
EXPECTED = {
    "IS_FAVORITE": EXPECTED_IS_FAVORITE,
    "IS_FAVORITE_HELPER": EXPECTED_IS_FAVORITE_HELPER,
    "FAVORITE_KEY": EXPECTED_FAVORITE_KEY,
    "SELECT": EXPECTED_SELECT,
    "UPDATE": EXPECTED_UPDATE,
    "INFO_LOG": EXPECTED_INFO_LOG,
}


def print_tables(tables):
    for name, rows in tables.items():
        print(f"EXPECTED_{name} = {{")
        for key, row in rows.items():
            print(f"    {key!r}: {row!r},")
        print("}\n")


def changed_plugins(want, got):
    """Which plugins' entries differ between two rows (`` | ``, blank or one char apart)."""
    def per_plugin(row):
        for sep in (" | ", " "):
            if sep in row:
                return row.split(sep)
        return list(row)

    if not (isinstance(want, str) and isinstance(got, str)):
        return ""
    w, g = per_plugin(want), per_plugin(got)
    if len(w) != len(SPORTS) or len(g) != len(SPORTS):
        return ""
    return f"  <- {', '.join(p for p, a, b in zip(SPORTS, w, g) if a != b)}"


def main() -> int:
    core = core_root()
    if core is None:
        print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
        return 2
    sys.path.insert(0, str(core))
    logging.disable(logging.CRITICAL)
    os.chdir(core)  # the managers resolve fonts against the core

    with patch("requests.get", side_effect=OSError("no network in this test")):
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
    print(f"  [pass] {rows} favourite-matching rows across {len(SPORTS)} scoreboards")
    return 0


if __name__ == "__main__":
    sys.exit(main())
