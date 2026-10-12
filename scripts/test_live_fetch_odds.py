#!/usr/bin/env python3
"""What each scoreboard asks ESPN for live games and odds, and when odds land.

WHY THIS EXISTS
---------------
Live fetch and odds are family 9 of the sports consolidation (LEDMatrix
docs/SPORTS_UNIFICATION.md): ``SportsCore._fetch_todays_games`` and
``_fetch_odds``, with ``_drain_odds_queue`` (the odds worker) beside them.
They were seven and three bodies across the nine plugins; they are now one
each. They decide which scoreboard requests a live poll makes, which cache
keys it reads and writes and for how long, what a failed or malformed answer
turns into, how long ``update()`` waits for odds (never, now) and when an odds
line appears. The tables record what every plugin does, so any later change to
the family shows up in a PR as a diff of them, cell by cell.
``_attach_odds_to_rotated_games`` and ``_wants_live_odds`` are already one
body in core (``sports_rotation``, ``sports_fetch``); they are pinned through
``update()`` here and by ``test_other_games_rotation.py``.

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
the call under test has returned. Afterwards every held request is let go and
its threads joined, so a line that lands in the background shows up as
``later``. (Before the reconcile six plugins waited 1.5-2 s per game on a
worker and hockey and lacrosse asked on the calling thread: up to 12 s of
``update()`` for four games; ledmatrix-plugins #649 pinned that.)

* ``OVERRIDES``: family methods a league manager takes from outside sports.py
  and core (``file:qualname``), or ``none``.
* ``FETCH``: ``_fetch_todays_games`` on the Live manager per league x Eastern
  time: the requests (``dates/limit``, the path only when it is not the
  manager's own league), the cache keys read (``key@max_age``) and written,
  and the event ids returned. ``sk:`` is the plugin's ``sport_key``;
  ``espn:`` is core's canonical ``espn_scoreboard_<sport>_<league>_``.
* ``CACHE``: requests made by each call in a sequence, and the ids the last
  call returned (``seed`` came from the cache entry the row seeded).
* ``FAILURE``: what one answer from ESPN turns into: the ids, ``None``, or
  ``!Name`` if it raised. Whether a malformed answer is cached is core's
  ``get_espn_scoreboard`` (its tests pin it; the core release after 3.8.5
  stops caching one without an ``events`` list), so it is not a column here.
* ``ODDS``: ``_fetch_odds`` for one game per kind x endpoint: where the odds
  request ran (``main`` / ``bg``) and its ``update_interval_seconds``, the
  seconds the call waited, and whether the line was on the game when the call
  returned (``now``), only after the background work finished (``later``),
  or never (``no``).
* ``UPDATE``: the real ``update()`` over four games with the slow endpoint
  (Live twice: the first pass, when nothing is on screen yet, then the next
  poll; Upcoming also with two of the four shown): odds requests, seconds
  waited, games with odds now / later.
* ``CONCURRENCY``: ``update()`` and ``display()`` on two threads against a
  20 ms endpoint, ``RUNS`` times per plugin with the thread switch interval
  at its shortest: exceptions, ERROR logs (printed on failure), the most odds
  requests and odds workers in flight at once (one each: one batch per
  manager), and the rounds in which every game ended with its odds.

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
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import requests
from PIL import Image

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
    ('own league', '10:00 ET'): '20261012/500 ; read espn:20261012@1 ; wrote espn:20261012 -> 1012a,1012b | 20261012/500 ; read espn:20261012@1 ; wrote espn:20261012 -> 1012a,1012b | 20261012/500 ; read espn:20261012@1 ; wrote espn:20261012 -> 1012a,1012b | 20261012/500 ; read espn:20261012@1 ; wrote espn:20261012 -> 1012a,1012b | 20261012/500 ; read espn:20261012@1 ; wrote espn:20261012 -> 1012a,1012b | 20261012/500 ; read espn:20261012@1 ; wrote espn:20261012 -> 1012a,1012b | 20261012/500 ; read espn:20261012@1 ; wrote espn:20261012 -> 1012a,1012b | 20261012/500 ; read espn:20261012@1 ; wrote espn:20261012 -> 1012a,1012b | 20261012/500 ; read espn:20261012@1 ; wrote espn:20261012 -> 1012a,1012b',
    ('own league', '02:00 ET'): '20261011-20261012/500>20261011/500>20261012/500 ; read espn:20261011-20261012@1 ; wrote espn:20261011-20261012 -> 1011a,1011b,1012a,1012b | 20261011-20261012/500>20261011/500>20261012/500 ; read espn:20261011-20261012@1 ; wrote espn:20261011-20261012 -> 1011a,1011b,1012a,1012b | 20261011-20261012/500>20261011/500>20261012/500 ; read espn:20261011-20261012@1 ; wrote espn:20261011-20261012 -> 1011a,1011b,1012a,1012b | 20261011-20261012/500>20261011/500>20261012/500 ; read espn:20261011-20261012@1 ; wrote espn:20261011-20261012 -> 1011a,1011b,1012a,1012b | 20261011-20261012/500>20261011/500>20261012/500 ; read espn:20261011-20261012@1 ; wrote espn:20261011-20261012 -> 1011a,1011b,1012a,1012b | 20261011-20261012/500>20261011/500>20261012/500 ; read espn:20261011-20261012@1 ; wrote espn:20261011-20261012 -> 1011a,1011b,1012a,1012b | 20261011-20261012/500>20261011/500>20261012/500 ; read espn:20261011-20261012@1 ; wrote espn:20261011-20261012 -> 1011a,1011b,1012a,1012b | 20261011-20261012/500>20261011/500>20261012/500 ; read espn:20261011-20261012@1 ; wrote espn:20261011-20261012 -> 1011a,1011b,1012a,1012b | 20261011-20261012/500>20261011/500>20261012/500 ; read espn:20261011-20261012@1 ; wrote espn:20261011-20261012 -> 1011a,1011b,1012a,1012b',
    ('mens-college-basketball', '10:00 ET'): '20261012/500 ; read espn:20261012@1 ; wrote espn:20261012 -> 1012a,1012b | 20261012/500 ; read espn:20261012@1 ; wrote espn:20261012 -> 1012a,1012b | 20261012/500 ; read espn:20261012@1 ; wrote espn:20261012 -> 1012a,1012b | 20261012/500 ; read espn:20261012@1 ; wrote espn:20261012 -> 1012a,1012b | 20261012/500 ; read espn:20261012@1 ; wrote espn:20261012 -> 1012a,1012b | 20261012/500 ; read espn:20261012@1 ; wrote espn:20261012 -> 1012a,1012b | 20261012/500 ; read espn:20261012@1 ; wrote espn:20261012 -> 1012a,1012b | 20261012/500 ; read espn:20261012@1 ; wrote espn:20261012 -> 1012a,1012b | 20261012/500 ; read espn:20261012@1 ; wrote espn:20261012 -> 1012a,1012b',
    ('mens-college-basketball', '02:00 ET'): '20261011-20261012/500>20261011/500>20261012/500 ; read espn:20261011-20261012@1 ; wrote espn:20261011-20261012 -> 1011a,1011b,1012a,1012b | 20261011-20261012/500>20261011/500>20261012/500 ; read espn:20261011-20261012@1 ; wrote espn:20261011-20261012 -> 1011a,1011b,1012a,1012b | 20261011-20261012/500>20261011/500>20261012/500 ; read espn:20261011-20261012@1 ; wrote espn:20261011-20261012 -> 1011a,1011b,1012a,1012b | 20261011-20261012/500>20261011/500>20261012/500 ; read espn:20261011-20261012@1 ; wrote espn:20261011-20261012 -> 1011a,1011b,1012a,1012b | 20261011-20261012/500>20261011/500>20261012/500 ; read espn:20261011-20261012@1 ; wrote espn:20261011-20261012 -> 1011a,1011b,1012a,1012b | 20261011-20261012/500>20261011/500>20261012/500 ; read espn:20261011-20261012@1 ; wrote espn:20261011-20261012 -> 1011a,1011b,1012a,1012b | 20261011-20261012/500>20261011/500>20261012/500 ; read espn:20261011-20261012@1 ; wrote espn:20261011-20261012 -> 1011a,1011b,1012a,1012b | 20261011-20261012/500>20261011/500>20261012/500 ; read espn:20261011-20261012@1 ; wrote espn:20261011-20261012 -> 1011a,1011b,1012a,1012b | 20261011-20261012/500>20261011/500>20261012/500 ; read espn:20261011-20261012@1 ; wrote espn:20261011-20261012 -> 1011a,1011b,1012a,1012b',
}

# Requests per call in the sequence -> ids the last call returned.
EXPECTED_CACHE = {
    'again after 20 s': '1,1 -> 1012a,1012b | 1,1 -> 1012a,1012b | 1,1 -> 1012a,1012b | 1,1 -> 1012a,1012b | 1,1 -> 1012a,1012b | 1,1 -> 1012a,1012b | 1,1 -> 1012a,1012b | 1,1 -> 1012a,1012b | 1,1 -> 1012a,1012b',
    'again after 31 s': '1,1 -> 1012a,1012b | 1,1 -> 1012a,1012b | 1,1 -> 1012a,1012b | 1,1 -> 1012a,1012b | 1,1 -> 1012a,1012b | 1,1 -> 1012a,1012b | 1,1 -> 1012a,1012b | 1,1 -> 1012a,1012b | 1,1 -> 1012a,1012b',
    'again after 299 s': '1,1 -> 1012a,1012b | 1,1 -> 1012a,1012b | 1,1 -> 1012a,1012b | 1,1 -> 1012a,1012b | 1,1 -> 1012a,1012b | 1,1 -> 1012a,1012b | 1,1 -> 1012a,1012b | 1,1 -> 1012a,1012b | 1,1 -> 1012a,1012b',
    'legacy key 10 s old': '1 -> 1012a,1012b | 1 -> 1012a,1012b | 1 -> 1012a,1012b | 1 -> 1012a,1012b | 1 -> 1012a,1012b | 1 -> 1012a,1012b | 1 -> 1012a,1012b | 1 -> 1012a,1012b | 1 -> 1012a,1012b',
    'legacy key 10 s old, no events': '1 -> 1012a,1012b | 1 -> 1012a,1012b | 1 -> 1012a,1012b | 1 -> 1012a,1012b | 1 -> 1012a,1012b | 1 -> 1012a,1012b | 1 -> 1012a,1012b | 1 -> 1012a,1012b | 1 -> 1012a,1012b',
    'canonical key 10 s old': '1 -> 1012a,1012b | 1 -> 1012a,1012b | 1 -> 1012a,1012b | 1 -> 1012a,1012b | 1 -> 1012a,1012b | 1 -> 1012a,1012b | 1 -> 1012a,1012b | 1 -> 1012a,1012b | 1 -> 1012a,1012b',
    'canonical key 40 s old': '1 -> 1012a,1012b | 1 -> 1012a,1012b | 1 -> 1012a,1012b | 1 -> 1012a,1012b | 1 -> 1012a,1012b | 1 -> 1012a,1012b | 1 -> 1012a,1012b | 1 -> 1012a,1012b | 1 -> 1012a,1012b',
}

# What ESPN answers -> ids (or None / !raised).
EXPECTED_FAILURE = {
    'games': '1012a,1012b | 1012a,1012b | 1012a,1012b | 1012a,1012b | 1012a,1012b | 1012a,1012b | 1012a,1012b | 1012a,1012b | 1012a,1012b',
    '{}': 'none | none | none | none | none | none | none | none | none',
    'events null': 'none | none | none | none | none | none | none | none | none',
    'events []': 'none | none | none | none | none | none | none | none | none',
    'HTTP 404': 'None | None | None | None | None | None | None | None | None',
    'HTTP 500': 'None | None | None | None | None | None | None | None | None',
    'connection error': 'None | None | None | None | None | None | None | None | None',
    'timeout': 'None | None | None | None | None | None | None | None | None',
    'not JSON': 'None | None | None | None | None | None | None | None | None',
}

# (game kind, odds endpoint): request thread@interval, seconds waited, when the line lands.
EXPECTED_ODDS = {
    ('live', 'fast, odds'): 'bg@60 wait 0 later | bg@60 wait 0 later | bg@60 wait 0 later | bg@60 wait 0 later | bg@60 wait 0 later | bg@60 wait 0 later | bg@60 wait 0 later | bg@60 wait 0 later | bg@60 wait 0 later',
    ('live', 'fast, no odds'): 'bg@60 wait 0 no | bg@60 wait 0 no | bg@60 wait 0 no | bg@60 wait 0 no | bg@60 wait 0 no | bg@60 wait 0 no | bg@60 wait 0 no | bg@60 wait 0 no | bg@60 wait 0 no',
    ('live', 'fast, raises'): 'bg@60 wait 0 no | bg@60 wait 0 no | bg@60 wait 0 no | bg@60 wait 0 no | bg@60 wait 0 no | bg@60 wait 0 no | bg@60 wait 0 no | bg@60 wait 0 no | bg@60 wait 0 no',
    ('live', 'slow 3 s, odds'): 'bg@60 wait 0 later | bg@60 wait 0 later | bg@60 wait 0 later | bg@60 wait 0 later | bg@60 wait 0 later | bg@60 wait 0 later | bg@60 wait 0 later | bg@60 wait 0 later | bg@60 wait 0 later',
    ('live', 'no odds manager'): 'not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no',
    ('live', 'show_odds off'): 'not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no',
    ('upcoming', 'fast, odds'): 'bg@3600 wait 0 later | bg@3600 wait 0 later | bg@3600 wait 0 later | bg@3600 wait 0 later | bg@3600 wait 0 later | bg@3600 wait 0 later | bg@3600 wait 0 later | bg@3600 wait 0 later | bg@3600 wait 0 later',
    ('upcoming', 'fast, no odds'): 'bg@3600 wait 0 no | bg@3600 wait 0 no | bg@3600 wait 0 no | bg@3600 wait 0 no | bg@3600 wait 0 no | bg@3600 wait 0 no | bg@3600 wait 0 no | bg@3600 wait 0 no | bg@3600 wait 0 no',
    ('upcoming', 'fast, raises'): 'bg@3600 wait 0 no | bg@3600 wait 0 no | bg@3600 wait 0 no | bg@3600 wait 0 no | bg@3600 wait 0 no | bg@3600 wait 0 no | bg@3600 wait 0 no | bg@3600 wait 0 no | bg@3600 wait 0 no',
    ('upcoming', 'slow 3 s, odds'): 'bg@3600 wait 0 later | bg@3600 wait 0 later | bg@3600 wait 0 later | bg@3600 wait 0 later | bg@3600 wait 0 later | bg@3600 wait 0 later | bg@3600 wait 0 later | bg@3600 wait 0 later | bg@3600 wait 0 later',
    ('upcoming', 'no odds manager'): 'not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no',
    ('upcoming', 'show_odds off'): 'not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no',
    ('final', 'fast, odds'): 'bg@3600 wait 0 later | bg@3600 wait 0 later | bg@3600 wait 0 later | bg@3600 wait 0 later | bg@3600 wait 0 later | bg@3600 wait 0 later | bg@3600 wait 0 later | bg@3600 wait 0 later | bg@3600 wait 0 later',
    ('final', 'fast, no odds'): 'bg@3600 wait 0 no | bg@3600 wait 0 no | bg@3600 wait 0 no | bg@3600 wait 0 no | bg@3600 wait 0 no | bg@3600 wait 0 no | bg@3600 wait 0 no | bg@3600 wait 0 no | bg@3600 wait 0 no',
    ('final', 'fast, raises'): 'bg@3600 wait 0 no | bg@3600 wait 0 no | bg@3600 wait 0 no | bg@3600 wait 0 no | bg@3600 wait 0 no | bg@3600 wait 0 no | bg@3600 wait 0 no | bg@3600 wait 0 no | bg@3600 wait 0 no',
    ('final', 'slow 3 s, odds'): 'bg@3600 wait 0 later | bg@3600 wait 0 later | bg@3600 wait 0 later | bg@3600 wait 0 later | bg@3600 wait 0 later | bg@3600 wait 0 later | bg@3600 wait 0 later | bg@3600 wait 0 later | bg@3600 wait 0 later',
    ('final', 'no odds manager'): 'not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no',
    ('final', 'show_odds off'): 'not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no | not asked wait 0 no',
}

# update() with the 3 s endpoint: odds requests, seconds waited ; odds now ; later.
EXPECTED_UPDATE = {
    'Upcoming': 'asked 4 wait 0 ; now - ; later u1,u2,u3,u4 | asked 4 wait 0 ; now - ; later u1,u2,u3,u4 | asked 4 wait 0 ; now - ; later u1,u2,u3,u4 | asked 4 wait 0 ; now - ; later u1,u2,u3,u4 | asked 4 wait 0 ; now - ; later u1,u2,u3,u4 | asked 4 wait 0 ; now - ; later u1,u2,u3,u4 | asked 4 wait 0 ; now - ; later u1,u2,u3,u4 | asked 4 wait 0 ; now - ; later u1,u2,u3,u4 | asked 4 wait 0 ; now - ; later u1,u2,u3,u4',
    'Upcoming, 2 of 4 shown': 'asked 2 wait 0 ; now - ; later u1,u2 | asked 2 wait 0 ; now - ; later u1,u2 | asked 2 wait 0 ; now - ; later u1,u2 | asked 2 wait 0 ; now - ; later u1,u2 | asked 2 wait 0 ; now - ; later u1,u2 | asked 2 wait 0 ; now - ; later u1,u2 | asked 2 wait 0 ; now - ; later u1,u2 | asked 2 wait 0 ; now - ; later u1,u2 | asked 4 wait 0 ; now - ; later u3,u4',
    'Recent': 'asked 4 wait 0 ; now - ; later u1,u2,u3,u4 | asked 4 wait 0 ; now - ; later u1,u2,u3,u4 | asked 4 wait 0 ; now - ; later u1,u2,u3,u4 | asked 4 wait 0 ; now - ; later u1,u2,u3,u4 | asked 4 wait 0 ; now - ; later u1,u2,u3,u4 | asked 4 wait 0 ; now - ; later u1,u2,u3,u4 | asked 4 wait 0 ; now - ; later u1,u2,u3,u4 | asked 4 wait 0 ; now - ; later u1,u2,u3,u4 | asked 0 wait 0 ; now - ; later -',
    'Live, first pass': 'asked 4 wait 0 ; now - ; later u4,u3,u2,u1 | asked 4 wait 0 ; now - ; later u4,u3,u2,u1 | asked 4 wait 0 ; now - ; later u4,u3,u2,u1 | asked 4 wait 0 ; now - ; later u4,u3,u2,u1 | asked 4 wait 0 ; now - ; later u4,u3,u2,u1 | asked 4 wait 0 ; now - ; later u4,u3,u2,u1 | asked 4 wait 0 ; now - ; later u4,u3,u2,u1 | asked 4 wait 0 ; now - ; later u4,u3,u2,u1 | asked 4 wait 0 ; now - ; later u4,u3,u2,u1',
    'Live, next poll': 'asked 2 wait 0 ; now - ; later u4,u3 | asked 2 wait 0 ; now - ; later u4,u3 | asked 2 wait 0 ; now - ; later u4,u3 | asked 2 wait 0 ; now - ; later u4,u3 | asked 2 wait 0 ; now - ; later u4,u3 | asked 2 wait 0 ; now - ; later u4,u3 | asked 2 wait 0 ; now - ; later u4,u3 | asked 2 wait 0 ; now - ; later u4,u3 | asked 2 wait 0 ; now - ; later u4,u3',
}

# RUNS rounds of update() 20 times and display() 200 times on two threads, 20 ms
# endpoint: exceptions raised, ERROR logs ; most requests and odds workers at
# once ; rounds in which every game had its odds once every thread was done.
EXPECTED_CONCURRENCY = {
    'update() and display() on two threads': "raised 0 errors 0 ; in flight 1 workers 1 ; every game's odds landed in 25 of 25 | raised 0 errors 0 ; in flight 1 workers 1 ; every game's odds landed in 25 of 25 | raised 0 errors 0 ; in flight 1 workers 1 ; every game's odds landed in 25 of 25 | raised 0 errors 0 ; in flight 1 workers 1 ; every game's odds landed in 25 of 25 | raised 0 errors 0 ; in flight 1 workers 1 ; every game's odds landed in 25 of 25 | raised 0 errors 0 ; in flight 1 workers 1 ; every game's odds landed in 25 of 25 | raised 0 errors 0 ; in flight 1 workers 1 ; every game's odds landed in 25 of 25 | raised 0 errors 0 ; in flight 1 workers 1 ; every game's odds landed in 25 of 25 | raised 0 errors 0 ; in flight 1 workers 1 ; every game's odds landed in 25 of 25",
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

    def release(self):
        with self.lock:
            self.open = True
            gates, self.gates = self.gates, []
        for gate in gates:
            gate.set()



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
        return ids(fetch(mgr))
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
        mgr._fetch_odds(game)
        now = bool(game.get("odds"))
        settle(before)
        asked = ",".join(VIRTUAL.odds.calls) or "not asked"
        return f"{asked} wait {VIRTUAL.waited:g} {when(now, game.get('odds'))}"
    return guarded(run)


def update_games(status, logos=None):
    """Four games as ESPN events, one bout each so ufc's split keeps them;
    with ``logos`` (a directory holding the images), drawable by display()."""
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
        if logos:
            game.update(home_logo_path=logos / f"H{n}.png", away_logo_path=logos / f"A{n}.png",
                        home_logo_url=None, away_logo_url=None,
                        fighter1_id=f"9{n}", fighter2_id=f"8{n}",
                        fighter1_image_path=logos / "f1.png", fighter2_image_path=logos / "f2.png",
                        fighter1_image_url=None, fighter2_image_url=None)
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
            mgr.update()
            shown = list(mgr.live_games if role == "Live" else mgr.games_list)
            now = [g["id"] for g in shown if g.get("odds")]
            settle(before)
        later = [g["id"] for g in shown if g.get("odds") and g["id"] not in now]
        return (f"asked {len(VIRTUAL.odds.calls)} wait {VIRTUAL.waited:g} ; "
                f"now {','.join(now) or '-'} ; later {','.join(later) or '-'}")
    return guarded(run)


class Busy:
    """An odds endpoint taking ``delay`` real seconds, counting the requests
    and odds workers in flight at once."""

    def __init__(self, worker_name, delay=0.02):
        self.worker_name, self.delay, self.lock = worker_name, delay, threading.Lock()
        self.active = self.most_active = self.most_workers = 0

    def get_odds(self, sport, league, event_id, update_interval_seconds=None):
        workers = sum(t.name == self.worker_name and t.is_alive() for t in threading.enumerate())
        with self.lock:
            self.active += 1
            self.most_active = max(self.most_active, self.active)
            self.most_workers = max(self.most_workers, workers)
        time.sleep(self.delay)
        with self.lock:
            self.active -= 1
        return {"details": f"{event_id} -3.5"}


#: How many times each plugin's CONCURRENCY row runs, so a rare interleaving shows.
RUNS = 25
#: plugin -> the ERROR lines its CONCURRENCY runs logged (printed on failure).
CONCURRENCY_ERRORS = {}


class Errors(logging.Handler):
    def __init__(self):
        super().__init__(logging.ERROR)
        self.seen = []

    def emit(self, record):
        self.seen.append(f"{record.name}: {record.getMessage()}")


def concurrency_run(plugin, logos):
    """After a first update(), update() 20 more times on one thread while
    display() draws on another until those are done (200 times at least);
    what happened. The first update() is there so display() has games to draw
    from its first call, however the two threads are scheduled."""
    mgr = build(plugin, "Upcoming", {"upcoming_games_to_show": 4,
                                     "other_upcoming_games_to_show": 4,
                                     "other_games_min_quality": "any"})
    mgr._fetch_team_rankings = lambda *a, **k: None
    events = update_games("upcoming", logos)
    mgr._fetch_data = lambda *a, **k: {"events": copy.deepcopy(events)}
    mgr._extract_game_details = lambda ev: dict(ev["competitions"][0])
    mgr.show_odds, mgr.odds_manager = True, Busy(f"{mgr.sport_key}-odds")
    raised, errors, updated = [], Errors(), threading.Event()

    def update():
        mgr.last_update = 0
        mgr.update()

    def updates():
        try:
            for _ in range(20):
                update()
        except Exception as exc:                      # noqa: BLE001
            raised.append(repr(exc))
        finally:
            updated.set()

    def displays():
        try:
            n = 0
            while n < 200 or not updated.is_set():
                mgr.display(force_clear=False)
                n += 1
        except Exception as exc:                      # noqa: BLE001
            raised.append(repr(exc))

    before = threading.enumerate()
    logging.disable(logging.NOTSET)
    logging.getLogger().addHandler(errors)
    try:
        update()
        threads = [threading.Thread(target=updates), threading.Thread(target=displays)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(120)
        for thread in set(threading.enumerate()) - set(before):
            thread.join(10)
    finally:
        logging.getLogger().removeHandler(errors)
        logging.disable(logging.CRITICAL)
    complete = len(mgr.games_list) == 4 and all(g.get("odds") for g in mgr.games_list)
    return raised, errors.seen, mgr.odds_manager, complete


def concurrency_row(plugin):
    """RUNS rounds of concurrency_run, with the thread switch interval at its
    shortest so the two threads interleave as finely as Python allows. The
    games' logos are real files in a temporary directory, so display() fetches
    and creates nothing: a logo path it cannot write (/nonexistent on Linux)
    logs ERRORs of its own that have nothing to do with odds."""
    def run():
        raised, errors, active, workers, complete = [], [], 0, 0, 0
        interval = sys.getswitchinterval()
        with tempfile.TemporaryDirectory() as tmp:
            logos = Path(tmp)
            for name in ("H1", "H2", "H3", "H4", "A1", "A2", "A3", "A4", "f1", "f2"):
                Image.new("RGBA", (16, 16), (200, 40, 40, 255)).save(logos / f"{name}.png")
            sys.setswitchinterval(1e-6)
            try:
                for _ in range(RUNS):
                    r, e, odds, done = concurrency_run(plugin, logos)
                    raised += r
                    errors += e
                    active, workers = max(active, odds.most_active), max(workers, odds.most_workers)
                    complete += done
            finally:
                sys.setswitchinterval(interval)
        if raised or errors:
            CONCURRENCY_ERRORS[plugin] = raised + errors
        return (f"raised {len(raised)} errors {len(errors)} ; in flight {active}"
                f" workers {workers} ; every game's odds landed in {complete} of {RUNS}")
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
    tables["CONCURRENCY"]["update() and display() on two threads"] = row(concurrency_row)
    return tables


#: The committed tables by name, as `observe()` keys them.
EXPECTED = {
    "OVERRIDES": EXPECTED_OVERRIDES,
    "FETCH": EXPECTED_FETCH,
    "CACHE": EXPECTED_CACHE,
    "FAILURE": EXPECTED_FAILURE,
    "ODDS": EXPECTED_ODDS,
    "UPDATE": EXPECTED_UPDATE,
    "CONCURRENCY": EXPECTED_CONCURRENCY,
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
    for plugin, lines in CONCURRENCY_ERRORS.items():
        print(f"  CONCURRENCY {plugin}: " + " | ".join(sorted(set(lines)))[:2000])
    if problems:
        return 1
    rows = sum(len(t) for t in observed.values())
    print(f"  [pass] {rows} live-fetch and odds rows across {len(SPORTS)} scoreboards")
    return 0


if __name__ == "__main__":
    sys.exit(main())
