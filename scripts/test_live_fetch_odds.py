#!/usr/bin/env python3
"""What each scoreboard asks ESPN for live games and odds, and when odds land.

WHY THIS EXISTS
---------------
Live fetch and odds are family 9 of the sports consolidation (LEDMatrix
docs/SPORTS_UNIFICATION.md): ``SportsCore._fetch_todays_games`` (seven bodies
across the nine plugins) and ``_fetch_odds`` (three). They decide which
scoreboard requests a live poll makes, which cache keys it reads and writes
and for how long, what a failed or malformed answer turns into, how long
``update()`` waits for odds and when an odds line appears. The tables record
what every plugin does today, so the reconcile shows up in a PR as a diff of
them, cell by cell. ``_attach_odds_to_rotated_games`` and ``_wants_live_odds``
are already one body in core (``sports_rotation``, ``sports_fetch``); they are
pinned through ``update()`` here and by ``test_other_games_rotation.py``.

For each plugin it builds the primary league's real managers (fake display;
``test_favourite_matching.build``) and swaps in a recording cache (each entry
stamped, read back against the reader's ``max_age``) and a fake odds manager.
Nothing reaches the network: ``requests.Session.get`` is answered by ``ESPN``
below, shaped as ESPN answered on 2026-10-12: a single ``dates=YYYYMMDD`` is
200 for every league tried, college basketball included (14 men's games on
2026-03-13, none on 2026-10-12); a ``YYYYMMDD-YYYYMMDD`` range is 400 for every
league; no ``dates`` is ESPN's own "current" day. ``time.time`` is frozen and
the plugins' ``datetime.now`` is pinned to an Eastern wall time.

Odds run on a virtual clock, so the test never sleeps. The fake odds endpoint
takes ``LATENCY`` (3 s) when "slow": a request made on the calling thread adds
it to the time ``update()`` waited; a worker thread's request is held until
the call under test has returned. ``queue.Queue.get`` called by
``_fetch_odds`` on the calling thread with a timeout adds that timeout (or
the latency, whichever is shorter) and gives up as the real one would; on a
fast endpoint it waits for the worker. Afterwards every held request is let
go and its threads joined, so a line that lands in the background shows up as
``later``. A background thread's own timeout (basketball's 5 s attach wait)
runs on the real clock, so it is not pinned here.

* ``OVERRIDES``: family methods a league manager takes from outside sports.py
  and core (``file:qualname``), or ``none``.
* ``FETCH``: ``_fetch_todays_games`` on the Live manager per league x Eastern
  time: the requests (``dates/limit``, the path only when it is not the
  manager's own league), the cache keys read (``key@max_age``) and written,
  and the event ids returned. ``sk:`` is the plugin's ``sport_key``;
  ``espn:`` is core's canonical ``espn_scoreboard_<sport>_<league>_``.
* ``CACHE``: requests made by each call in a sequence, and the ids the last
  call returned (``seed`` came from the cache entry the row seeded).
* ``FAILURE``: what one answer from ESPN turns into: the ids (or ``None``,
  ``!Name`` if it raised), then the keys written.
* ``ODDS``: ``_fetch_odds`` for one game per kind x endpoint: where the odds
  request ran (``main`` / ``bg``) and its ``update_interval_seconds``, the
  seconds the call waited, and whether the line was on the game when the call
  returned (``now``), only after the background work finished (``later``),
  or never (``no``).
* ``UPDATE``: the real ``update()`` over four games with the slow endpoint
  (Live twice: the first pass, when nothing is on screen yet, then the next
  poll; Upcoming also with two of the four shown): odds requests, seconds
  waited, games with odds now / later.

To see the current tables after an intended change:

    python scripts/test_live_fetch_odds.py --print

Exit 0 pass, 2 skip (no core checkout), 1 fail.
"""
from __future__ import annotations

import copy
import inspect
import json
import logging
import os
import queue
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_favourite_matching import NOW, build, changed_plugins  # noqa: E402
from test_game_over_check import diff  # noqa: E402
from test_sports_shared_methods import REPO, SPORTS, core_root, load  # noqa: E402

SITE = "https://site.api.espn.com/apis/site/v2/sports/"
T0 = 100_000.0
LATENCY = 3.0

#: label -> Eastern wall time ``datetime.now`` answers (before 06:00 the live
#: fetch also asks for yesterday).
TIMES = {"10:00 ET": datetime(2026, 10, 12, 10, 0), "02:00 ET": datetime(2026, 10, 12, 2, 0)}

#: (sport, league) the Live manager is pointed at; None keeps its own.
LEAGUES = {"own league": None, "mens-college-basketball": ("basketball", "mens-college-basketball")}

#: label -> what ESPN answers a single-day request with (a payload, an HTTP
#: status, raw bytes, or an exception class). "games" is the default.
ANSWERS = {
    "games": "games",
    "{}": {},
    "events null": {"events": None},
    "events []": {"events": []},
    "HTTP 404": 404,
    "HTTP 500": 500,
    "connection error": requests.ConnectionError,
    "timeout": requests.Timeout,
    "not JSON": b"<html>",
}

#: label -> (seconds after the first call of each later call, cache entry
#: seeded before the first call: (key template, age in seconds, payload)).
CACHE_CASES = {
    "again after 20 s": ((0, 20), None),
    "again after 31 s": ((0, 31), None),
    "again after 299 s": ((0, 299), None),
    "legacy key 10 s old": ((0,), ("{sk}_scoreboard_current", 10, "games")),
    "legacy key 10 s old, no events": ((0,), ("{sk}_scoreboard_current", 10, {"day": {}})),
    "canonical key 10 s old": ((0,), ("espn_scoreboard_{sport}_{league}_20261012", 10, "games")),
    "canonical key 40 s old": ((0,), ("espn_scoreboard_{sport}_{league}_20261012", 40, "games")),
}

#: label -> the view-model flags of the game whose odds are asked for.
KINDS = {"live": {"is_live": True}, "upcoming": {"is_upcoming": True},
         "final": {"is_final": True}}

#: label -> (what get_odds returns, or an exception class; slow?).
ENDPOINTS = {
    "fast, odds": ("odds", False),
    "fast, no odds": (None, False),
    "fast, raises": (RuntimeError, False),
    "slow 3 s, odds": ("odds", True),
    "no odds manager": ("no manager", False),
    "show_odds off": ("odds off", False),
}

# --------------------------------------------------------------------------
# Expected (current) behaviour. Columns per plugin, in SPORTS order:
#   afl baseball basketball football hockey lacrosse nrl soccer ufc
# --------------------------------------------------------------------------
# Family methods league managers define outside sports.py and core.
EXPECTED_OVERRIDES = {
    'league managers': 'none | milb_managers.py:BaseMiLBManager._fetch_todays_games | none | none | hockeytech_managers.py:BaseHockeyTechManager._fetch_todays_games | none | none | none | mma.py:MMALive._fetch_todays_games',
}

# (league, Eastern time): requests ; cache read ; cache written -> event ids.
EXPECTED_FETCH = {
    ('own league', '10:00 ET'): '20261012/500 ; read sk:scoreboard_current@30 ; wrote sk:scoreboard_current -> 1012a,1012b | 20261012/500 ; read - ; wrote espn:20261012 -> 1012a,1012b | 20261012/500 ; read espn:20261012@30,sk:scoreboard_current@30 ; wrote espn:20261012 -> 1012a,1012b | 20261012/500 ; read - ; wrote espn:20261012 -> 1012a,1012b | 20261012/500 ; read - ; wrote espn:20261012 -> 1012a,1012b | 20261012/500 ; read - ; wrote - -> 1012a,1012b | 20261012/500 ; read sk:scoreboard_current@30 ; wrote sk:scoreboard_current -> 1012a,1012b | 20261012/500 ; read espn:20261012@30,sk:scoreboard_current@30 ; wrote espn:20261012 -> 1012a,1012b | 20261012/500 ; read - ; wrote - -> 1012a,1012b',
    ('own league', '02:00 ET'): '20261011-20261012/500>20261011/500>20261012/500 ; read sk:scoreboard_current@30 ; wrote sk:scoreboard_current -> 1011a,1011b,1012a,1012b | 20261011-20261012/500>20261011/500>20261012/500 ; read - ; wrote espn:20261011-20261012 -> 1011a,1011b,1012a,1012b | 20261011-20261012/500>20261011/500>20261012/500 ; read espn:20261011-20261012@30,sk:scoreboard_current@30 ; wrote espn:20261011-20261012 -> 1011a,1011b,1012a,1012b | 20261011-20261012/500>20261011/500>20261012/500 ; read - ; wrote espn:20261011-20261012 -> 1011a,1011b,1012a,1012b | 20261011-20261012/500>20261011/500>20261012/500 ; read - ; wrote espn:20261011-20261012 -> 1011a,1011b,1012a,1012b | 20261011-20261012/500>20261011/500>20261012/500 ; read - ; wrote - -> 1011a,1011b,1012a,1012b | 20261011-20261012/500>20261011/500>20261012/500 ; read sk:scoreboard_current@30 ; wrote sk:scoreboard_current -> 1011a,1011b,1012a,1012b | 20261011-20261012/500>20261011/500>20261012/500 ; read espn:20261011-20261012@30,sk:scoreboard_current@30 ; wrote espn:20261011-20261012 -> 1011a,1011b,1012a,1012b | 20261011-20261012/500>20261011/500>20261012/500 ; read - ; wrote - -> 1011a,1011b,1012a,1012b',
    ('mens-college-basketball', '10:00 ET'): '20261012/500 ; read sk:scoreboard_current@30 ; wrote sk:scoreboard_current -> 1012a,1012b | 20261012/500 ; read - ; wrote espn:20261012 -> 1012a,1012b | nodates/500 ; read espn:current@30,sk:scoreboard_current@30 ; wrote espn:current -> 1012a,1012b | 20261012/500 ; read - ; wrote espn:20261012 -> 1012a,1012b | 20261012/500 ; read - ; wrote espn:20261012 -> 1012a,1012b | 20261012/500 ; read - ; wrote - -> 1012a,1012b | 20261012/500 ; read sk:scoreboard_current@30 ; wrote sk:scoreboard_current -> 1012a,1012b | 20261012/500 ; read espn:20261012@30,sk:scoreboard_current@30 ; wrote espn:20261012 -> 1012a,1012b | 20261012/500 ; read - ; wrote - -> 1012a,1012b',
    ('mens-college-basketball', '02:00 ET'): '20261011-20261012/500>20261011/500>20261012/500 ; read sk:scoreboard_current@30 ; wrote sk:scoreboard_current -> 1011a,1011b,1012a,1012b | 20261011-20261012/500>20261011/500>20261012/500 ; read - ; wrote espn:20261011-20261012 -> 1011a,1011b,1012a,1012b | nodates/500 ; read espn:current@30,sk:scoreboard_current@30 ; wrote espn:current -> 1012a,1012b | 20261011-20261012/500>20261011/500>20261012/500 ; read - ; wrote espn:20261011-20261012 -> 1011a,1011b,1012a,1012b | 20261011-20261012/500>20261011/500>20261012/500 ; read - ; wrote espn:20261011-20261012 -> 1011a,1011b,1012a,1012b | 20261011-20261012/500>20261011/500>20261012/500 ; read - ; wrote - -> 1011a,1011b,1012a,1012b | 20261011-20261012/500>20261011/500>20261012/500 ; read sk:scoreboard_current@30 ; wrote sk:scoreboard_current -> 1011a,1011b,1012a,1012b | 20261011-20261012/500>20261011/500>20261012/500 ; read espn:20261011-20261012@30,sk:scoreboard_current@30 ; wrote espn:20261011-20261012 -> 1011a,1011b,1012a,1012b | 20261011-20261012/500>20261011/500>20261012/500 ; read - ; wrote - -> 1011a,1011b,1012a,1012b',
}

# Requests per call in the sequence -> ids the last call returned.
EXPECTED_CACHE = {
    'again after 20 s': '1,0 -> 1012a,1012b | 1,1 -> 1012a,1012b | 1,0 -> 1012a,1012b | 1,1 -> 1012a,1012b | 1,1 -> 1012a,1012b | 1,1 -> 1012a,1012b | 1,0 -> 1012a,1012b | 1,0 -> 1012a,1012b | 1,1 -> 1012a,1012b',
    'again after 31 s': '1,1 -> 1012a,1012b | 1,1 -> 1012a,1012b | 1,1 -> 1012a,1012b | 1,1 -> 1012a,1012b | 1,1 -> 1012a,1012b | 1,1 -> 1012a,1012b | 1,1 -> 1012a,1012b | 1,1 -> 1012a,1012b | 1,1 -> 1012a,1012b',
    'again after 299 s': '1,1 -> 1012a,1012b | 1,1 -> 1012a,1012b | 1,1 -> 1012a,1012b | 1,1 -> 1012a,1012b | 1,1 -> 1012a,1012b | 1,1 -> 1012a,1012b | 1,1 -> 1012a,1012b | 1,1 -> 1012a,1012b | 1,1 -> 1012a,1012b',
    'legacy key 10 s old': '0 -> seed | 1 -> 1012a,1012b | 0 -> seed | 1 -> 1012a,1012b | 1 -> 1012a,1012b | 1 -> 1012a,1012b | 0 -> seed | 0 -> seed | 1 -> 1012a,1012b',
    'legacy key 10 s old, no events': '1 -> 1012a,1012b | 1 -> 1012a,1012b | 1 -> 1012a,1012b | 1 -> 1012a,1012b | 1 -> 1012a,1012b | 1 -> 1012a,1012b | 1 -> 1012a,1012b | 1 -> 1012a,1012b | 1 -> 1012a,1012b',
    'canonical key 10 s old': '1 -> 1012a,1012b | 1 -> 1012a,1012b | 0 -> seed | 1 -> 1012a,1012b | 1 -> 1012a,1012b | 1 -> 1012a,1012b | 1 -> 1012a,1012b | 0 -> seed | 1 -> 1012a,1012b',
    'canonical key 40 s old': '1 -> 1012a,1012b | 1 -> 1012a,1012b | 1 -> 1012a,1012b | 1 -> 1012a,1012b | 1 -> 1012a,1012b | 1 -> 1012a,1012b | 1 -> 1012a,1012b | 1 -> 1012a,1012b | 1 -> 1012a,1012b',
}

# What ESPN answers -> ids (or None / !raised) ; cache written.
EXPECTED_FAILURE = {
    'games': '1012a,1012b ; wrote sk:scoreboard_current | 1012a,1012b ; wrote espn:20261012 | 1012a,1012b ; wrote espn:20261012 | 1012a,1012b ; wrote espn:20261012 | 1012a,1012b ; wrote espn:20261012 | 1012a,1012b ; wrote - | 1012a,1012b ; wrote sk:scoreboard_current | 1012a,1012b ; wrote espn:20261012 | 1012a,1012b ; wrote -',
    '{}': 'none ; wrote sk:scoreboard_current | none ; wrote espn:20261012 | none ; wrote espn:20261012 | none ; wrote espn:20261012 | none ; wrote espn:20261012 | none ; wrote - | none ; wrote sk:scoreboard_current | none ; wrote espn:20261012 | none ; wrote -',
    'events null': '!TypeError ; wrote - | !TypeError ; wrote espn:20261012 | !TypeError ; wrote - | !TypeError ; wrote espn:20261012 | !TypeError ; wrote espn:20261012 | !TypeError ; wrote - | !TypeError ; wrote - | !TypeError ; wrote - | !TypeError ; wrote -',
    'events []': 'none ; wrote sk:scoreboard_current | none ; wrote espn:20261012 | none ; wrote espn:20261012 | none ; wrote espn:20261012 | none ; wrote espn:20261012 | none ; wrote - | none ; wrote sk:scoreboard_current | none ; wrote espn:20261012 | none ; wrote -',
    'HTTP 404': 'None ; wrote - | None ; wrote - | None ; wrote - | None ; wrote - | None ; wrote - | None ; wrote - | None ; wrote - | None ; wrote - | None ; wrote -',
    'HTTP 500': 'None ; wrote - | None ; wrote - | None ; wrote - | None ; wrote - | None ; wrote - | None ; wrote - | None ; wrote - | None ; wrote - | None ; wrote -',
    'connection error': 'None ; wrote - | None ; wrote - | None ; wrote - | None ; wrote - | None ; wrote - | None ; wrote - | None ; wrote - | None ; wrote - | None ; wrote -',
    'timeout': 'None ; wrote - | None ; wrote - | None ; wrote - | None ; wrote - | None ; wrote - | None ; wrote - | None ; wrote - | None ; wrote - | None ; wrote -',
    'not JSON': 'None ; wrote - | None ; wrote - | None ; wrote - | None ; wrote - | None ; wrote - | None ; wrote - | None ; wrote - | None ; wrote - | None ; wrote -',
}

# (game kind, odds endpoint): request thread@interval, seconds waited, when the line lands.
EXPECTED_ODDS = {
    ('live', 'fast, odds'): 'bg@60 wait 0 now | bg@60 wait 0 now | bg@60 wait 0 now | bg@60 wait 0 now | main@60 wait 0 now | main@60 wait 0 now | bg@60 wait 0 now | bg@60 wait 0 now | bg@60 wait 0 now',
    ('live', 'fast, no odds'): 'bg@60 wait 0 no | bg@60 wait 0 no | bg@60 wait 0 no | bg@60 wait 0 no | main@60 wait 0 no | main@60 wait 0 no | bg@60 wait 0 no | bg@60 wait 0 no | bg@60 wait 0 no',
    ('live', 'fast, raises'): 'bg@60 wait 0 no | bg@60 wait 0 no | bg@60 wait 0 no | bg@60 wait 0 no | main@60 wait 0 no | main@60 wait 0 no | bg@60 wait 0 no | bg@60 wait 0 no | bg@60 wait 0 no',
    ('live', 'slow 3 s, odds'): 'bg@60 wait 2 no | bg@60 wait 2 no | bg@60 wait 2 no | bg@60 wait 2 no | main@60 wait 3 now | main@60 wait 3 now | bg@60 wait 2 no | bg@60 wait 2 no | bg@60 wait 2 no',
    ('live', 'no odds manager'): 'not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no',
    ('live', 'show_odds off'): 'not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no',
    ('upcoming', 'fast, odds'): 'bg@3600 wait 0 now | bg@3600 wait 0 now | bg@3600 wait 0 later | bg@3600 wait 0 now | main@3600 wait 0 now | main@3600 wait 0 now | bg@3600 wait 0 now | bg@3600 wait 0 now | bg@3600 wait 0 now',
    ('upcoming', 'fast, no odds'): 'bg@3600 wait 0 no | bg@3600 wait 0 no | bg@3600 wait 0 no | bg@3600 wait 0 no | main@3600 wait 0 no | main@3600 wait 0 no | bg@3600 wait 0 no | bg@3600 wait 0 no | bg@3600 wait 0 no',
    ('upcoming', 'fast, raises'): 'bg@3600 wait 0 no | bg@3600 wait 0 no | bg@3600 wait 0 no | bg@3600 wait 0 no | main@3600 wait 0 no | main@3600 wait 0 no | bg@3600 wait 0 no | bg@3600 wait 0 no | bg@3600 wait 0 no',
    ('upcoming', 'slow 3 s, odds'): 'bg@3600 wait 1.5 no | bg@3600 wait 1.5 no | bg@3600 wait 0 later | bg@3600 wait 1.5 no | main@3600 wait 3 now | main@3600 wait 3 now | bg@3600 wait 1.5 no | bg@3600 wait 1.5 no | bg@3600 wait 1.5 no',
    ('upcoming', 'no odds manager'): 'not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no',
    ('upcoming', 'show_odds off'): 'not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no',
    ('final', 'fast, odds'): 'bg@3600 wait 0 now | bg@3600 wait 0 now | bg@3600 wait 0 now | bg@3600 wait 0 now | main@3600 wait 0 now | main@3600 wait 0 now | bg@3600 wait 0 now | bg@3600 wait 0 now | bg@3600 wait 0 now',
    ('final', 'fast, no odds'): 'bg@3600 wait 0 no | bg@3600 wait 0 no | bg@3600 wait 0 no | bg@3600 wait 0 no | main@3600 wait 0 no | main@3600 wait 0 no | bg@3600 wait 0 no | bg@3600 wait 0 no | bg@3600 wait 0 no',
    ('final', 'fast, raises'): 'bg@3600 wait 0 no | bg@3600 wait 0 no | bg@3600 wait 0 no | bg@3600 wait 0 no | main@3600 wait 0 no | main@3600 wait 0 no | bg@3600 wait 0 no | bg@3600 wait 0 no | bg@3600 wait 0 no',
    ('final', 'slow 3 s, odds'): 'bg@3600 wait 1.5 no | bg@3600 wait 1.5 no | bg@3600 wait 1.5 no | bg@3600 wait 1.5 no | main@3600 wait 3 now | main@3600 wait 3 now | bg@3600 wait 1.5 no | bg@3600 wait 1.5 no | bg@3600 wait 1.5 no',
    ('final', 'no odds manager'): 'not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no',
    ('final', 'show_odds off'): 'not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no',
}

# update() with the 3 s endpoint: odds requests, seconds waited ; odds now ; later.
EXPECTED_UPDATE = {
    'Upcoming': 'asked 4 wait 6 ; now - ; later - | asked 4 wait 6 ; now - ; later - | asked 4 wait 0 ; now - ; later u1,u2,u3,u4 | asked 4 wait 6 ; now - ; later - | asked 4 wait 12 ; now u1,u2,u3,u4 ; later - | asked 4 wait 12 ; now u1,u2,u3,u4 ; later - | asked 4 wait 6 ; now - ; later - | asked 4 wait 6 ; now - ; later - | asked 4 wait 6 ; now - ; later -',
    'Upcoming, 2 of 4 shown': 'asked 2 wait 3 ; now - ; later - | asked 2 wait 3 ; now - ; later - | asked 2 wait 0 ; now - ; later u1,u2 | asked 2 wait 3 ; now - ; later - | asked 2 wait 6 ; now u1,u2 ; later - | asked 2 wait 6 ; now u1,u2 ; later - | asked 2 wait 3 ; now - ; later - | asked 2 wait 3 ; now - ; later - | asked 4 wait 6 ; now - ; later -',
    'Recent': 'asked 4 wait 6 ; now - ; later - | asked 4 wait 6 ; now - ; later - | asked 4 wait 6 ; now - ; later - | asked 4 wait 6 ; now - ; later - | asked 4 wait 12 ; now u1,u2,u3,u4 ; later - | asked 4 wait 12 ; now u1,u2,u3,u4 ; later - | asked 4 wait 6 ; now - ; later - | asked 4 wait 6 ; now - ; later - | asked 0 wait 0 ; now - ; later -',
    'Live, first pass': 'asked 4 wait 8 ; now - ; later - | asked 4 wait 8 ; now - ; later - | asked 4 wait 8 ; now - ; later - | asked 4 wait 8 ; now - ; later - | asked 4 wait 12 ; now u4,u3,u2,u1 ; later - | asked 4 wait 12 ; now u4,u3,u2,u1 ; later - | asked 4 wait 8 ; now - ; later - | asked 4 wait 8 ; now - ; later - | asked 4 wait 8 ; now - ; later -',
    'Live, next poll': 'asked 2 wait 4 ; now - ; later - | asked 2 wait 4 ; now - ; later - | asked 2 wait 4 ; now - ; later - | asked 2 wait 4 ; now - ; later - | asked 2 wait 6 ; now u4,u3 ; later - | asked 2 wait 6 ; now u4,u3 ; later - | asked 2 wait 4 ; now - ; later - | asked 2 wait 4 ; now - ; later - | asked 2 wait 4 ; now - ; later -',
}


class Clock:
    """``time.time``, frozen until a row moves it."""

    now = T0

    def time(self):
        return self.now


CLOCK = Clock()

#: Seconds the call under test spent waiting on odds, and the fake endpoint.
VIRTUAL = SimpleNamespace(waited=0.0, odds=None)


def event(eid):
    """A scoreboard event with the fields the live fetch logs."""
    return {"id": eid, "name": f"Away at Home {eid}", "date": "2026-10-12T23:00Z",
            "competitions": [{"id": eid, "status": {"type": {
                "state": "in", "name": "STATUS_IN_PROGRESS", "shortDetail": "2nd"}},
                "competitors": []}]}


def games_on(day):
    return {"events": [event(day[4:] + "a"), event(day[4:] + "b")],
            "day": {"date": f"{day[:4]}-{day[4:6]}-{day[6:]}"}}


def response(url, answer):
    """A real ``requests.Response``: a status, raw bytes, or a JSON payload."""
    resp = requests.Response()
    resp.url = url
    resp.status_code = answer if isinstance(answer, int) else 200
    if isinstance(answer, bytes):
        resp._content = answer
    else:
        resp._content = json.dumps({} if isinstance(answer, int) else answer).encode()
    return resp


class ESPN:
    """Answers the scoreboard requests, and records them."""

    def __init__(self):
        self.reset("games", None)

    def reset(self, answer, own):
        self.answer, self.own, self.log = answer, own, []

    def get(self, url, params=None, **_kwargs):
        params = dict(params or {})
        dates = params.get("dates")
        path = url[len(SITE):] if url.startswith(SITE) else url
        where = "" if path == self.own else f"{path}?"
        self.log.append(f"{where}{dates or 'nodates'}/{params.get('limit', '-')}")
        if dates and "-" in str(dates):
            return response(url, 400)            # ESPN rejects every range
        if isinstance(self.answer, type):
            raise self.answer("refused by the test")
        if self.answer == "games":
            return response(url, games_on(dates or "20261012"))
        return response(url, self.answer)

    def count(self):
        return len(self.log)


SERVER = ESPN()


class Cache:
    """Entries stamped with ``time.time``; reads answer by the reader's
    ``max_age`` (``get``) or hand the record back (``get_cached_data``)."""

    def __init__(self, short):
        self.short, self.store, self.reads, self.writes = short, {}, [], []

    def _fresh(self, key, max_age):
        self.reads.append(f"{self.short(key)}@{max_age}")
        if key not in self.store:
            return None
        data, stamp = self.store[key]
        if max_age is not None and CLOCK.now - stamp > max_age:
            return None
        return data, stamp

    def get(self, key, max_age=300, memory_ttl=None):
        found = self._fresh(key, max_age)
        return found and found[0]

    def get_cached_data(self, key, max_age=300, memory_ttl=None):
        found = self._fresh(key, max_age)
        return found and {"data": found[0], "timestamp": found[1]}

    def set(self, key, data, ttl=None):
        self.writes.append(self.short(key) + ("" if ttl is None else f"~{ttl}"))
        self.store[key] = (data, CLOCK.now)


class Frozen(datetime):
    """``datetime``, with ``now()`` pinned to an Eastern wall time."""

    at = TIMES["10:00 ET"]

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return cls.at
        return tz.localize(cls.at) if hasattr(tz, "localize") else cls.at.replace(tzinfo=tz)


class Odds:
    """The odds manager: records each request, answers it, and holds a
    worker thread's request until the call under test lets it go."""

    def __init__(self, answer, slow):
        self.answer, self.slow, self.calls = answer, slow, []
        self.lock, self.open, self.gates = threading.Lock(), False, []

    def get_odds(self, sport, league, event_id, update_interval_seconds=None):
        on_main = threading.current_thread() is threading.main_thread()
        self.calls.append(f"{'main' if on_main else 'bg'}@{update_interval_seconds}")
        if on_main:
            VIRTUAL.waited += LATENCY if self.slow else 0
        else:
            with self.lock:
                gate = None if self.open else threading.Event()
                if gate:
                    self.gates.append(gate)
            if gate:
                gate.wait(10)
        if isinstance(self.answer, type):
            raise self.answer("odds endpoint failed")
        return {"details": f"{event_id} -3.5", "over_under": 220.5} if self.answer else None

    def release(self, keep_open=True):
        with self.lock:
            self.open = keep_open
            gates, self.gates = self.gates, []
        for gate in gates:
            gate.set()


_REAL_GET = queue.Queue.get


def waiting_get(q, block=True, timeout=None):
    """``Queue.get`` on a virtual clock for the calling thread (see top)."""
    odds = VIRTUAL.odds
    if threading.current_thread() is not threading.main_thread() or timeout is None \
            or odds is None or sys._getframe(1).f_code.co_name != "_fetch_odds":
        return _REAL_GET(q, block, timeout)
    if odds.slow:
        VIRTUAL.waited += min(timeout, LATENCY)
        if timeout < LATENCY:
            raise queue.Empty
    odds.release()
    try:
        return _REAL_GET(q, True, 10)
    finally:
        odds.release(keep_open=False)


def guarded(fn):
    try:
        return fn()
    except Exception as exc:                          # noqa: BLE001
        return f"!{type(exc).__name__}"


def live_manager(plugin, league_label):
    """The plugin's Live manager with a recording cache, pointed at a league."""
    CLOCK.now = T0
    mgr = build(plugin, "Live", {})
    if LEAGUES[league_label]:
        mgr.sport, mgr.league = LEAGUES[league_label]
    head = f"espn_scoreboard_{mgr.sport}_{mgr.league}_"

    def short(key):
        return key.replace(head, "espn:").replace(f"{mgr.sport_key}_", "sk:")
    mgr.cache_manager = Cache(short)
    return mgr


def fetch(mgr, when="10:00 ET"):
    """``_fetch_todays_games`` at an Eastern wall time, with a clean range state."""
    from src.common import espn_dates
    core_cls = next(c for c in type(mgr).__mro__ if c.__name__ == "SportsCore")
    Frozen.at = TIMES[when]
    with patch.dict(core_cls._fetch_todays_games.__globals__, {"datetime": Frozen}), \
            patch.object(espn_dates, "_ranges_rejected_until", 0.0):
        return mgr._fetch_todays_games()


def ids(data):
    if data is None:
        return "None"
    if not isinstance(data, dict):
        return f"<{type(data).__name__}>"
    events = data.get("events")
    if not isinstance(events, list):
        return f"events={events!r}"
    return ",".join(str(e.get("id")) for e in events) or "none"


def fetch_row(plugin, league_label, when):
    def run():
        mgr = live_manager(plugin, league_label)
        SERVER.reset("games", f"{mgr.sport}/{mgr.league}/scoreboard")
        got = fetch(mgr, when)
        cache = mgr.cache_manager
        return (f"{'>'.join(SERVER.log) or 'none'} ; read {','.join(cache.reads) or '-'}"
                f" ; wrote {','.join(cache.writes) or '-'} -> {ids(got)}")
    return guarded(run)


def cache_row(plugin, case):
    def run():
        mgr = live_manager(plugin, "own league")
        SERVER.reset("games", f"{mgr.sport}/{mgr.league}/scoreboard")
        offsets, seed = CACHE_CASES[case]
        if seed:
            template, age, payload = seed
            key = template.format(sk=mgr.sport_key, sport=mgr.sport, league=mgr.league)
            payload = {"events": [event("seed")]} if payload == "games" else payload
            mgr.cache_manager.store[key] = (payload, T0 - age)
        per_call, got = [], None
        for offset in offsets:
            CLOCK.now = T0 + offset
            before = SERVER.count()
            got = fetch(mgr)
            per_call.append(str(SERVER.count() - before))
        return f"{','.join(per_call)} -> {ids(got)}"
    return guarded(run)


def failure_row(plugin, answer):
    def run():
        mgr = live_manager(plugin, "own league")
        SERVER.reset(ANSWERS[answer], f"{mgr.sport}/{mgr.league}/scoreboard")
        got = guarded(lambda: ids(fetch(mgr)))
        return f"{got} ; wrote {','.join(mgr.cache_manager.writes) or '-'}"
    return guarded(run)


def with_odds(mgr, endpoint):
    """Give ``mgr`` the endpoint's odds manager and set VIRTUAL up for it."""
    answer, slow = ENDPOINTS[endpoint]
    VIRTUAL.waited, VIRTUAL.odds = 0.0, Odds(answer, slow)
    mgr.show_odds = answer != "odds off"
    mgr.odds_manager = None if answer == "no manager" else VIRTUAL.odds
    return threading.enumerate()


def settle(before):
    """Let every held odds request go and wait for the threads this row started."""
    VIRTUAL.odds.release()
    for thread in set(threading.enumerate()) - set(before):
        thread.join(10)


def when(now, later):
    return "now" if now else "later" if later else "no"


def odds_row(plugin, kind, endpoint):
    def run():
        mgr = build(plugin, "Upcoming", {})
        game = {"id": "g1", "is_live": False, "is_upcoming": False, "is_final": False,
                **KINDS[kind]}
        before = with_odds(mgr, endpoint)
        with patch.object(queue.Queue, "get", waiting_get):
            mgr._fetch_odds(game)
            now = bool(game.get("odds"))
            settle(before)
        asked = ",".join(VIRTUAL.odds.calls) or "not asked"
        return f"{asked} wait {VIRTUAL.waited:g} {when(now, game.get('odds'))}"
    return guarded(run)


def update_games(status):
    """Four games as ESPN events, one bout each so ufc's split keeps them."""
    out = []
    for n in range(1, 5):
        hours = n if status == "upcoming" else -n
        game = {"id": f"u{n}", "home_abbr": f"H{n}", "away_abbr": f"A{n}",
                "home_id": str(n), "away_id": str(10 + n),
                "fighter1_name": f"Home {n}", "fighter2_name": f"Away {n}",
                "fight_class": "LW", "home_score": "1", "away_score": "0",
                "clock": "10:00", "period": 2, "period_text": "Q2",
                "is_live": status == "live", "is_halftime": False,
                "is_final": status == "final", "is_upcoming": status == "upcoming",
                "start_time_utc": NOW + timedelta(hours=hours)}
        out.append({"id": f"u{n}", "competitions": [game]})
    return out


#: label -> (role, game status, update() passes, games to show).
UPDATE_ROLES = {"Upcoming": ("Upcoming", "upcoming", 1, 4),
                "Upcoming, 2 of 4 shown": ("Upcoming", "upcoming", 1, 2),
                "Recent": ("Recent", "final", 1, 4),
                "Live, first pass": ("Live", "live", 1, 4),
                "Live, next poll": ("Live", "live", 2, 4)}


def update_row(plugin, label):
    def run():
        role, status, passes, shown = UPDATE_ROLES[label]
        word = role.lower()
        mgr = build(plugin, role, {f"{word}_games_to_show": shown,
                                   f"other_{word}_games_to_show": shown,
                                   "other_games_min_quality": "any"})
        mgr._fetch_team_rankings = lambda *a, **k: None
        events = update_games(status)
        mgr._fetch_data = lambda *a, **k: {"events": copy.deepcopy(events)}
        mgr._extract_game_details = lambda ev: dict(ev["competitions"][0])
        CLOCK.now = T0
        for n in range(passes):
            before = with_odds(mgr, "slow 3 s, odds")
            CLOCK.now = T0 + n * 3600
            mgr.last_update = 0
            with patch.object(queue.Queue, "get", waiting_get):
                mgr.update()
                shown = list(mgr.live_games if role == "Live" else mgr.games_list)
                now = [g["id"] for g in shown if g.get("odds")]
                settle(before)
        later = [g["id"] for g in shown if g.get("odds") and g["id"] not in now]
        return (f"asked {len(VIRTUAL.odds.calls)} wait {VIRTUAL.waited:g} ; "
                f"now {','.join(now) or '-'} ; later {','.join(later) or '-'}")
    return guarded(run)


FAMILY = ("_fetch_todays_games", "_fetch_odds", "_attach_odds_to_rotated_games",
          "_wants_live_odds", "_needs_previous_day")


def overrides(plugin):
    found = set()
    pdir = REPO / "plugins" / f"{plugin}-scoreboard"
    for path in sorted(pdir.glob("*_managers.py")):
        mod = load(plugin, path.name)
        for name, cls in inspect.getmembers(mod, inspect.isclass):
            if cls.__module__ != mod.__name__ or not name.endswith("Manager"):
                continue
            for method in FAMILY:
                fn = getattr(cls, method, None)
                where = Path(fn.__code__.co_filename) if fn else pdir / "sports.py"
                if where.parent == pdir and where.name != "sports.py":
                    found.add(f"{where.name}:{fn.__qualname__}")
    return ",".join(sorted(found)) or "none"


def row(fn, *args):
    return " | ".join(fn(p, *args) for p in SPORTS)


def observe():
    """Every table as this checkout answers it."""
    tables = {name: {} for name in EXPECTED}
    tables["OVERRIDES"]["league managers"] = " | ".join(overrides(p) for p in SPORTS)
    for league in LEAGUES:
        for at in TIMES:
            tables["FETCH"][(league, at)] = row(fetch_row, league, at)
    for case in CACHE_CASES:
        tables["CACHE"][case] = row(cache_row, case)
    for answer in ANSWERS:
        tables["FAILURE"][answer] = row(failure_row, answer)
    for kind in KINDS:
        for endpoint in ENDPOINTS:
            tables["ODDS"][(kind, endpoint)] = row(odds_row, kind, endpoint)
    for label in UPDATE_ROLES:
        tables["UPDATE"][label] = row(update_row, label)
    return tables


#: The committed tables by name, as `observe()` keys them.
EXPECTED = {
    "OVERRIDES": EXPECTED_OVERRIDES,
    "FETCH": EXPECTED_FETCH,
    "CACHE": EXPECTED_CACHE,
    "FAILURE": EXPECTED_FAILURE,
    "ODDS": EXPECTED_ODDS,
    "UPDATE": EXPECTED_UPDATE,
}


def print_tables(observed):
    for name, rows in observed.items():
        print(f"EXPECTED_{name} = {{")
        for key, value in rows.items():
            print(f"    {key!r}: {value!r},")
        print("}")
        print()


def main() -> int:
    core = core_root()
    if core is None:
        print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
        return 2
    sys.path.insert(0, str(core))
    logging.disable(logging.CRITICAL)
    os.chdir(core)  # the managers resolve fonts against the core

    with patch("requests.get", side_effect=OSError("no network in this test")), \
            patch("requests.Session.get", side_effect=SERVER.get), \
            patch("time.time", CLOCK.time):
        try:
            observed = observe()
        except Exception as exc:                      # noqa: BLE001
            print(f"  [FAIL] building the managers raised {type(exc).__name__}: {exc}")
            return 1
    if "--print" in sys.argv:
        print_tables(observed)
        return 0

    problems = []
    for name, got in observed.items():
        problems += diff(name, EXPECTED[name], got, changed_plugins)
    for p in problems:
        print(f"  [FAIL] {p}")
    if problems:
        return 1
    rows = sum(len(t) for t in observed.values())
    print(f"  [pass] {rows} live-fetch and odds rows across {len(SPORTS)} scoreboards")
    return 0


if __name__ == "__main__":
    sys.exit(main())
