#!/usr/bin/env python3
"""What each scoreboard asks ESPN for rankings, and what it does with them.

WHY THIS EXISTS
---------------
Rankings are family 8 of the sports consolidation (LEDMatrix
docs/SPORTS_UNIFICATION.md): ``SportsCore._fetch_team_rankings``,
``_choose_poll``, ``_load_division_team_ids``, ``_passes_other_filters``,
``_best_rank`` and ``_is_ranked_game``. They were three, three and two bodies
each; they are now one each in all nine, with ``_ranked_positions`` (ranks by
ESPN team id, then abbreviation) and ``_poll_season_ended`` (a poll whose
season's ``endDate`` has passed loads nothing) beside them. The standings-as-
ranks branch is gone, college football's division rosters are asked for the
season year, and baseball's leagues no longer keep their own class-level copy
of the table. The data source's ``fetch_standings`` decides the endpoints
(held with ``data_sources.py``, but pinned here because it is what the fetch
asks; every college or NCAA league now asks /rankings first). The tables
record what every plugin answers, so any later change to the family shows up
in a PR as a diff of them, cell by cell.

For each plugin it builds the primary league's real Upcoming manager (fake
display and cache; ``test_favourite_matching.build``), then points it at the
league a row names (``sport``/``league`` are what the family reads). Nothing
reaches the network: ``requests.Session.get`` is answered by ``ESPN`` below,
which records each request and returns a payload shaped like ESPN's (recorded
2026-10-12: college-football /rankings fronted AP Top 25 then the AFCA Coaches
Poll; college hockey's fronted the USCHO poll, with tournament seedings in
season; site-API /standings answered ``{}`` for usa.ncaa.m.1 and eng.1 and a
``fullViewLink`` stub for nba, never ``children``; core-API
``seasons/2026/.../groups/80/teams`` listed 148 FBS teams and ``seasons/2027``
none). ``time.time``/``time.monotonic`` and the ``datetime`` of the module
``_load_division_team_ids`` lives in are frozen. Then:

* ``FETCH``: ``_fetch_team_rankings`` per league x what ESPN answers: the
  requests in order (``>``), then the abbreviation table and the id table
  (``-``: the plugin keeps none).
* ``POLL``: ``_choose_poll`` per poll set (AP, Coaches, CFP fronted, FCS and
  Division II fronted, seedings, empty, None): the poll's name.
* ``SEASON``: ``_load_division_team_ids`` on each date: the requests, then the
  roster sizes. ESPN here lists rosters for seasons up to 2026 only.
* ``CACHE``: requests made by each call in a sequence (rankings TTL, an empty
  result, a failed request, a second manager of the same league; the division
  rosters' day and 10-minute retry, and the cache manager's copy).
* ``SEASON_OVER``: the AP poll carrying its season's ``endDate`` (ESPN's
  shape: college basketball's /rankings still served April's final poll,
  season ending 2026-04-08, on 2026-10-12), fetched at a given moment: the
  tables.
* ``MALFORMED``: payloads ESPN could send back for the poll, and transport
  failures: the tables, and whether the result was cached.
* ``RANKED``: ``_is_ranked_game`` and ``_best_rank`` over games, with the AP
  poll loaded through the real fetch (abbreviations shared across divisions,
  games without ids, no poll loaded).
* ``FILTER``: ``_passes_other_filters`` per game x ``other_games_min_quality``
  x ``other_games_divisions``: ``Y`` kept, ``.`` dropped.

* ``OVERRIDES``: family methods a league manager takes from its own module
  rather than sports.py (baseball's three leagues wrapped the fetch in a
  class-level cache until the reconcile). With none, every manager resolves
  to the methods the primary league's does, so one per plugin covers them.

``!Name`` in a cell means it raised. To see the current tables after an
intended change:

    python scripts/test_rankings.py --print

Exit 0 pass, 2 skip (no core checkout), 1 fail.
"""
from __future__ import annotations

import inspect
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_favourite_matching import build, changed_plugins  # noqa: E402
from test_game_over_check import diff  # noqa: E402
from test_sports_shared_methods import REPO, SPORTS, core_root, load  # noqa: E402

SITE = "https://site.api.espn.com/apis/site/v2/sports/"
CORE = "https://sports.core.api.espn.com/v2/sports/"

#: (ESPN id, abbreviation). OSU twice is real: ESPN's college-football team
#: list has Ohio State and Ohio State Newark both as OSU (Newark's id here is
#: made up). SDSU/SDST are San Diego State (FBS) and South Dakota State (FCS).
UGA, ND, OSU, TEX, VAN, SDSU = ("61", "UGA"), ("87", "ND"), ("194", "OSU"), \
    ("251", "TEX"), ("238", "VAN"), ("21", "SDSU")
SDST, NDSU, NEWARK, FRST, DEN = ("2571", "SDST"), ("2449", "NDSU"), \
    ("9194", "OSU"), ("9001", "FRST"), ("2172", "DEN")
FBS_IDS, FCS_IDS = (UGA, ND, OSU, TEX, VAN, SDSU), (SDST, NDSU)


def poll(name, kind, *teams):
    """A /rankings block: the fields the family reads, plus a few it ignores."""
    return {"name": name, "shortName": name, "type": kind, "ranks": [
        {"current": n, "previous": n, "points": 100.0 - n, "firstPlaceVotes": 0,
         "team": {"id": tid, "abbreviation": abbr, "location": abbr, "name": abbr}}
        for n, (tid, abbr) in enumerate(teams, 1)]}


AP = poll("AP Top 25", "ap", UGA, ND, OSU, SDSU)
COACHES = poll("AFCA Coaches Poll", "usa", ND, UGA, TEX)
CFP = poll("College Football Playoff Rankings", "cfp", OSU, UGA)
FCS = poll("FCS Coaches Poll", "fcs", NDSU, SDST)
D2 = poll("AFCA Division II Coaches Poll", "afca", FRST)
SEEDS = poll("NCAA Men's Hockey Tournament Seedings", "tournament", DEN)
USCHO = poll("USCHO Men's Poll", "USCHOMENSPOLL", DEN, ND)

POLL_SETS = {
    "AP, Coaches (live)": [AP, COACHES],
    "Coaches first": [COACHES, AP],
    "CFP fronted": [CFP, AP, COACHES],
    "FCS and D2 fronted": [FCS, D2, AP, COACHES],
    "only lower divisions": [FCS, D2],
    "FCS by type alone": [poll("Coaches Poll", "fcs", NDSU, SDST), AP],
    "seedings, USCHO (hockey)": [SEEDS, USCHO],
    "unnamed, untyped block": [{"ranks": AP["ranks"]}],
    "empty list": [],
    "None": None,
}

#: What /standings would carry if it carried a table (the shape the standings
#: branch parses; the site API answers {} today).
STANDINGS_TABLE = {"children": [
    {"name": "East", "standings": {"entries": [{"team": {"id": "1", "abbreviation": "BOS"}},
                                               {"team": {"id": "2", "abbreviation": "NYK"}}]}},
    {"name": "West", "standings": {"entries": [{"team": {"id": "3", "abbreviation": "OKC"}},
                                               {"team": {"id": "", "abbreviation": ""}}]}}]}

#: label -> what ESPN answers per site endpoint: a payload, an HTTP status, or
#: an exception class.
ANSWERS = {
    "live": {"rankings": {"rankings": [AP, COACHES]}, "standings": {}},
    "standings carry a table": {"rankings": 404, "standings": STANDINGS_TABLE},
    "no poll (404), standings {}": {"rankings": 404, "standings": {}},
}

#: (sport, league): what a manager is pointed at.
LEAGUES = (("football", "nfl"), ("football", "college-football"),
           ("basketball", "nba"), ("basketball", "mens-college-basketball"),
           ("hockey", "mens-college-hockey"), ("baseball", "college-baseball"),
           ("soccer", "usa.ncaa.m.1"))

MALFORMED = {
    "{}": {},
    "rankings []": {"rankings": []},
    "rankings null": {"rankings": None},
    "rankings is a dict": {"rankings": {"name": "AP Top 25"}},
    "block without ranks": {"rankings": [{"name": "AP Top 25", "type": "ap"}]},
    "current 0 / -1 / missing": {"rankings": [{"name": "AP Top 25", "type": "ap", "ranks": [
        {"current": 0, "team": {"id": "61", "abbreviation": "UGA"}},
        {"current": -1, "team": {"id": "87", "abbreviation": "ND"}},
        {"team": {"id": "194", "abbreviation": "OSU"}},
        {"current": 4, "team": {"id": "251", "abbreviation": "TEX"}}]}]},
    "no team / no abbr / bad id": {"rankings": [{"name": "AP Top 25", "type": "ap", "ranks": [
        {"current": 1},
        {"current": 2, "team": {"id": "87"}},
        {"current": 3, "team": {"id": "abc", "abbreviation": "OSU"}},
        {"current": 4, "team": {"abbreviation": "TEX"}}]}]},
    "HTTP 500": 500,
    "connection error": requests.ConnectionError,
    "not JSON": b"<html>",
}

#: label -> (the poll's season endDate, or None for no season block; when it
#: is fetched, UTC).
SEASON_OVER = {
    "Oct 12, season ended Apr 8": ("2026-04-08T06:59Z", "2026-10-12T12:00"),
    "a minute before endDate": ("2026-04-08T06:59Z", "2026-04-08T06:58"),
    "at endDate": ("2026-04-08T06:59Z", "2026-04-08T06:59"),
    "a minute after endDate": ("2026-04-08T06:59Z", "2026-04-08T07:00"),
    "bowl week, season ends Jan 28": ("2027-01-28T07:59Z", "2027-01-10T12:00"),
    "new season's first poll": ("2027-04-08T06:59Z", "2026-11-03T12:00"),
    "endDate with seconds": ("2026-04-08T06:59:00Z", "2026-10-12T12:00"),
    "endDate unreadable": ("April", "2026-10-12T12:00"),
    "no season block": (None, "2026-10-12T12:00"),
}

#: Frozen "now" for the season year. ESPN here lists rosters up to 2026.
DATES = ("2026-01-15", "2026-06-30", "2026-07-01", "2026-10-12", "2026-12-31",
         "2027-01-15")
LAST_ROSTER_SEASON = 2026

GAMES = {
    "UGA v TEX (#1)": (UGA, TEX),
    "TEX v VAN (unranked)": (TEX, VAN),
    "OSU v VAN (#3)": (OSU, VAN),
    "Newark 'OSU' v VAN": (NEWARK, VAN),
    "SDSU v SDST (#4, FBS v FCS)": (SDSU, SDST),
    "SDST v NDSU (FCS, FCS-ranked)": (SDST, NDSU),
    "'OSU' v VAN, no ids": ((None, "OSU"), (None, "VAN")),
    "id 61 v 238, no abbrs": (("61", None), ("238", None)),
}

#: label -> (other_games_min_quality, other_games_divisions, poll loaded?)
FILTERS = {
    "any": ("any", [], True),
    "ranked": ("ranked", [], True),
    "ranked, no poll loaded": ("ranked", [], False),
    "any, fbs": ("any", ["fbs"], True),
    "ranked, fbs": ("ranked", ["fbs"], True),
    "any, fcs": ("any", ["fcs"], True),
}

# --------------------------------------------------------------------------
# Expected (current) behaviour. Columns per plugin, in SPORTS order:
#   afl baseball basketball football hockey lacrosse nrl soccer ufc
# --------------------------------------------------------------------------
# Family methods league managers define outside sports.py.
EXPECTED_OVERRIDES = {
    'league managers': 'none | none | none | none | none | none | none | none | none',
}

# (league, what ESPN answers): requests -> abbreviation table ; id table.
EXPECTED_FETCH = {
    ('nfl', 'live'): 'none -> {} ; ids {} | none -> {} ; ids {} | none -> {} ; ids {} | none -> {} ; ids {} | none -> {} ; ids {} | none -> {} ; ids {} | none -> {} ; ids {} | none -> {} ; ids {} | none -> {} ; ids {}',
    ('nfl', 'standings carry a table'): 'none -> {} ; ids {} | none -> {} ; ids {} | none -> {} ; ids {} | none -> {} ; ids {} | none -> {} ; ids {} | none -> {} ; ids {} | none -> {} ; ids {} | none -> {} ; ids {} | none -> {} ; ids {}',
    ('nfl', 'no poll (404), standings {}'): 'none -> {} ; ids {} | none -> {} ; ids {} | none -> {} ; ids {} | none -> {} ; ids {} | none -> {} ; ids {} | none -> {} ; ids {} | none -> {} ; ids {} | none -> {} ; ids {} | none -> {} ; ids {}',
    ('college-football', 'live'): 'rankings -> ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | rankings -> ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | rankings -> ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | rankings -> ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | rankings -> ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | rankings -> ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | rankings -> ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | rankings -> ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | none -> {} ; ids {}',
    ('college-football', 'standings carry a table'): 'rankings -> {} ; ids {} | rankings>standings -> {} ; ids {} | rankings -> {} ; ids {} | rankings>standings -> {} ; ids {} | rankings>standings -> {} ; ids {} | rankings>standings -> {} ; ids {} | rankings -> {} ; ids {} | rankings -> {} ; ids {} | none -> {} ; ids {}',
    ('college-football', 'no poll (404), standings {}'): 'rankings -> {} ; ids {} | rankings>standings -> {} ; ids {} | rankings -> {} ; ids {} | rankings>standings -> {} ; ids {} | rankings>standings -> {} ; ids {} | rankings>standings -> {} ; ids {} | rankings -> {} ; ids {} | rankings -> {} ; ids {} | none -> {} ; ids {}',
    ('nba', 'live'): 'none -> {} ; ids {} | none -> {} ; ids {} | none -> {} ; ids {} | none -> {} ; ids {} | none -> {} ; ids {} | none -> {} ; ids {} | none -> {} ; ids {} | none -> {} ; ids {} | none -> {} ; ids {}',
    ('nba', 'standings carry a table'): 'none -> {} ; ids {} | none -> {} ; ids {} | none -> {} ; ids {} | none -> {} ; ids {} | none -> {} ; ids {} | none -> {} ; ids {} | none -> {} ; ids {} | none -> {} ; ids {} | none -> {} ; ids {}',
    ('nba', 'no poll (404), standings {}'): 'none -> {} ; ids {} | none -> {} ; ids {} | none -> {} ; ids {} | none -> {} ; ids {} | none -> {} ; ids {} | none -> {} ; ids {} | none -> {} ; ids {} | none -> {} ; ids {} | none -> {} ; ids {}',
    ('mens-college-basketball', 'live'): 'rankings -> ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | rankings -> ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | rankings -> ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | rankings -> ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | rankings -> ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | rankings -> ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | rankings -> ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | rankings -> ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | none -> {} ; ids {}',
    ('mens-college-basketball', 'standings carry a table'): 'rankings -> {} ; ids {} | rankings>standings -> {} ; ids {} | rankings -> {} ; ids {} | rankings>standings -> {} ; ids {} | rankings>standings -> {} ; ids {} | rankings>standings -> {} ; ids {} | rankings -> {} ; ids {} | rankings -> {} ; ids {} | none -> {} ; ids {}',
    ('mens-college-basketball', 'no poll (404), standings {}'): 'rankings -> {} ; ids {} | rankings>standings -> {} ; ids {} | rankings -> {} ; ids {} | rankings>standings -> {} ; ids {} | rankings>standings -> {} ; ids {} | rankings>standings -> {} ; ids {} | rankings -> {} ; ids {} | rankings -> {} ; ids {} | none -> {} ; ids {}',
    ('mens-college-hockey', 'live'): 'rankings -> ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | rankings -> ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | rankings -> ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | rankings -> ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | rankings -> ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | rankings -> ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | rankings -> ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | rankings -> ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | none -> {} ; ids {}',
    ('mens-college-hockey', 'standings carry a table'): 'rankings -> {} ; ids {} | rankings>standings -> {} ; ids {} | rankings -> {} ; ids {} | rankings>standings -> {} ; ids {} | rankings>standings -> {} ; ids {} | rankings>standings -> {} ; ids {} | rankings -> {} ; ids {} | rankings -> {} ; ids {} | none -> {} ; ids {}',
    ('mens-college-hockey', 'no poll (404), standings {}'): 'rankings -> {} ; ids {} | rankings>standings -> {} ; ids {} | rankings -> {} ; ids {} | rankings>standings -> {} ; ids {} | rankings>standings -> {} ; ids {} | rankings>standings -> {} ; ids {} | rankings -> {} ; ids {} | rankings -> {} ; ids {} | none -> {} ; ids {}',
    ('college-baseball', 'live'): 'rankings -> ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | none -> {} ; ids {} | rankings -> ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | rankings -> ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | rankings -> ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | rankings -> ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | rankings -> ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | rankings -> ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | none -> {} ; ids {}',
    ('college-baseball', 'standings carry a table'): 'rankings -> {} ; ids {} | none -> {} ; ids {} | rankings -> {} ; ids {} | rankings>standings -> {} ; ids {} | rankings>standings -> {} ; ids {} | rankings>standings -> {} ; ids {} | rankings -> {} ; ids {} | rankings -> {} ; ids {} | none -> {} ; ids {}',
    ('college-baseball', 'no poll (404), standings {}'): 'rankings -> {} ; ids {} | none -> {} ; ids {} | rankings -> {} ; ids {} | rankings>standings -> {} ; ids {} | rankings>standings -> {} ; ids {} | rankings>standings -> {} ; ids {} | rankings -> {} ; ids {} | rankings -> {} ; ids {} | none -> {} ; ids {}',
    ('usa.ncaa.m.1', 'live'): 'rankings -> ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | rankings -> ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | rankings -> ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | rankings -> ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | rankings -> ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | rankings -> ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | rankings -> ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | rankings -> ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | none -> {} ; ids {}',
    ('usa.ncaa.m.1', 'standings carry a table'): 'rankings -> {} ; ids {} | rankings>standings -> {} ; ids {} | rankings -> {} ; ids {} | rankings>standings -> {} ; ids {} | rankings>standings -> {} ; ids {} | rankings>standings -> {} ; ids {} | rankings -> {} ; ids {} | rankings -> {} ; ids {} | none -> {} ; ids {}',
    ('usa.ncaa.m.1', 'no poll (404), standings {}'): 'rankings -> {} ; ids {} | rankings>standings -> {} ; ids {} | rankings -> {} ; ids {} | rankings>standings -> {} ; ids {} | rankings>standings -> {} ; ids {} | rankings>standings -> {} ; ids {} | rankings -> {} ; ids {} | rankings -> {} ; ids {} | none -> {} ; ids {}',
}

# poll set: the block _choose_poll picks (its name).
EXPECTED_POLL = {
    'AP, Coaches (live)': 'AP Top 25 | AP Top 25 | AP Top 25 | AP Top 25 | AP Top 25 | AP Top 25 | AP Top 25 | AP Top 25 | AP Top 25',
    'Coaches first': 'AFCA Coaches Poll | AFCA Coaches Poll | AFCA Coaches Poll | AFCA Coaches Poll | AFCA Coaches Poll | AFCA Coaches Poll | AFCA Coaches Poll | AFCA Coaches Poll | AFCA Coaches Poll',
    'CFP fronted': 'College Football Playoff Rankings | College Football Playoff Rankings | College Football Playoff Rankings | College Football Playoff Rankings | College Football Playoff Rankings | College Football Playoff Rankings | College Football Playoff Rankings | College Football Playoff Rankings | College Football Playoff Rankings',
    'FCS and D2 fronted': 'AP Top 25 | AP Top 25 | AP Top 25 | AP Top 25 | AP Top 25 | AP Top 25 | AP Top 25 | AP Top 25 | AP Top 25',
    'only lower divisions': 'none | none | none | none | none | none | none | none | none',
    'FCS by type alone': 'AP Top 25 | AP Top 25 | AP Top 25 | AP Top 25 | AP Top 25 | AP Top 25 | AP Top 25 | AP Top 25 | AP Top 25',
    'seedings, USCHO (hockey)': "USCHO Men's Poll | USCHO Men's Poll | USCHO Men's Poll | USCHO Men's Poll | USCHO Men's Poll | USCHO Men's Poll | USCHO Men's Poll | USCHO Men's Poll | USCHO Men's Poll",
    'unnamed, untyped block': 'none | none | none | none | none | none | none | none | none',
    'empty list': 'none | none | none | none | none | none | none | none | none',
    'None': 'none | none | none | none | none | none | none | none | none',
}

# (date, league): division roster requests -> roster sizes.
EXPECTED_SEASON = {
    ('2026-01-15', 'college-football'): 'seasons/2025/groups/80>seasons/2025/groups/81 -> fbs:6,fcs:2 | seasons/2025/groups/80>seasons/2025/groups/81 -> fbs:6,fcs:2 | seasons/2025/groups/80>seasons/2025/groups/81 -> fbs:6,fcs:2 | seasons/2025/groups/80>seasons/2025/groups/81 -> fbs:6,fcs:2 | seasons/2025/groups/80>seasons/2025/groups/81 -> fbs:6,fcs:2 | seasons/2025/groups/80>seasons/2025/groups/81 -> fbs:6,fcs:2 | seasons/2025/groups/80>seasons/2025/groups/81 -> fbs:6,fcs:2 | seasons/2025/groups/80>seasons/2025/groups/81 -> fbs:6,fcs:2 | seasons/2025/groups/80>seasons/2025/groups/81 -> fbs:6,fcs:2',
    ('2026-06-30', 'college-football'): 'seasons/2025/groups/80>seasons/2025/groups/81 -> fbs:6,fcs:2 | seasons/2025/groups/80>seasons/2025/groups/81 -> fbs:6,fcs:2 | seasons/2025/groups/80>seasons/2025/groups/81 -> fbs:6,fcs:2 | seasons/2025/groups/80>seasons/2025/groups/81 -> fbs:6,fcs:2 | seasons/2025/groups/80>seasons/2025/groups/81 -> fbs:6,fcs:2 | seasons/2025/groups/80>seasons/2025/groups/81 -> fbs:6,fcs:2 | seasons/2025/groups/80>seasons/2025/groups/81 -> fbs:6,fcs:2 | seasons/2025/groups/80>seasons/2025/groups/81 -> fbs:6,fcs:2 | seasons/2025/groups/80>seasons/2025/groups/81 -> fbs:6,fcs:2',
    ('2026-07-01', 'college-football'): 'seasons/2026/groups/80>seasons/2026/groups/81 -> fbs:6,fcs:2 | seasons/2026/groups/80>seasons/2026/groups/81 -> fbs:6,fcs:2 | seasons/2026/groups/80>seasons/2026/groups/81 -> fbs:6,fcs:2 | seasons/2026/groups/80>seasons/2026/groups/81 -> fbs:6,fcs:2 | seasons/2026/groups/80>seasons/2026/groups/81 -> fbs:6,fcs:2 | seasons/2026/groups/80>seasons/2026/groups/81 -> fbs:6,fcs:2 | seasons/2026/groups/80>seasons/2026/groups/81 -> fbs:6,fcs:2 | seasons/2026/groups/80>seasons/2026/groups/81 -> fbs:6,fcs:2 | seasons/2026/groups/80>seasons/2026/groups/81 -> fbs:6,fcs:2',
    ('2026-10-12', 'college-football'): 'seasons/2026/groups/80>seasons/2026/groups/81 -> fbs:6,fcs:2 | seasons/2026/groups/80>seasons/2026/groups/81 -> fbs:6,fcs:2 | seasons/2026/groups/80>seasons/2026/groups/81 -> fbs:6,fcs:2 | seasons/2026/groups/80>seasons/2026/groups/81 -> fbs:6,fcs:2 | seasons/2026/groups/80>seasons/2026/groups/81 -> fbs:6,fcs:2 | seasons/2026/groups/80>seasons/2026/groups/81 -> fbs:6,fcs:2 | seasons/2026/groups/80>seasons/2026/groups/81 -> fbs:6,fcs:2 | seasons/2026/groups/80>seasons/2026/groups/81 -> fbs:6,fcs:2 | seasons/2026/groups/80>seasons/2026/groups/81 -> fbs:6,fcs:2',
    ('2026-12-31', 'college-football'): 'seasons/2026/groups/80>seasons/2026/groups/81 -> fbs:6,fcs:2 | seasons/2026/groups/80>seasons/2026/groups/81 -> fbs:6,fcs:2 | seasons/2026/groups/80>seasons/2026/groups/81 -> fbs:6,fcs:2 | seasons/2026/groups/80>seasons/2026/groups/81 -> fbs:6,fcs:2 | seasons/2026/groups/80>seasons/2026/groups/81 -> fbs:6,fcs:2 | seasons/2026/groups/80>seasons/2026/groups/81 -> fbs:6,fcs:2 | seasons/2026/groups/80>seasons/2026/groups/81 -> fbs:6,fcs:2 | seasons/2026/groups/80>seasons/2026/groups/81 -> fbs:6,fcs:2 | seasons/2026/groups/80>seasons/2026/groups/81 -> fbs:6,fcs:2',
    ('2027-01-15', 'college-football'): 'seasons/2026/groups/80>seasons/2026/groups/81 -> fbs:6,fcs:2 | seasons/2026/groups/80>seasons/2026/groups/81 -> fbs:6,fcs:2 | seasons/2026/groups/80>seasons/2026/groups/81 -> fbs:6,fcs:2 | seasons/2026/groups/80>seasons/2026/groups/81 -> fbs:6,fcs:2 | seasons/2026/groups/80>seasons/2026/groups/81 -> fbs:6,fcs:2 | seasons/2026/groups/80>seasons/2026/groups/81 -> fbs:6,fcs:2 | seasons/2026/groups/80>seasons/2026/groups/81 -> fbs:6,fcs:2 | seasons/2026/groups/80>seasons/2026/groups/81 -> fbs:6,fcs:2 | seasons/2026/groups/80>seasons/2026/groups/81 -> fbs:6,fcs:2',
    ('2026-01-15', 'mens-college-basketball'): 'none -> none | none -> none | none -> none | none -> none | none -> none | none -> none | none -> none | none -> none | none -> none',
}

# case: requests per call at +0, +60, +3599, +3601 s (rankings; then the table
# the +3599 call left),
# +0 s (a second manager of the league, after the first fetched) or
# +0, +60, +601, +86401 s (divisions; then the rosters).
EXPECTED_CACHE = {
    'rankings live': '1,0,0,1 -> ND=2,OSU=3,SDSU=4,UGA=1 | 1,0,0,1 -> ND=2,OSU=3,SDSU=4,UGA=1 | 1,0,0,1 -> ND=2,OSU=3,SDSU=4,UGA=1 | 1,0,0,1 -> ND=2,OSU=3,SDSU=4,UGA=1 | 1,0,0,1 -> ND=2,OSU=3,SDSU=4,UGA=1 | 1,0,0,1 -> ND=2,OSU=3,SDSU=4,UGA=1 | 1,0,0,1 -> ND=2,OSU=3,SDSU=4,UGA=1 | 1,0,0,1 -> ND=2,OSU=3,SDSU=4,UGA=1 | 0,0,0,0 -> {}',
    'rankings empty': '1,0,0,1 -> {} | 2,0,0,2 -> {} | 1,0,0,1 -> {} | 2,0,0,2 -> {} | 2,0,0,2 -> {} | 2,0,0,2 -> {} | 1,0,0,1 -> {} | 1,0,0,1 -> {} | 0,0,0,0 -> {}',
    'rankings refused': '1,0,0,1 -> {} | 2,0,0,2 -> {} | 1,0,0,1 -> {} | 2,0,0,2 -> {} | 2,0,0,2 -> {} | 2,0,0,2 -> {} | 1,0,0,1 -> {} | 1,0,0,1 -> {} | 0,0,0,0 -> {}',
    'rankings, a second manager': '1 -> ND=2,OSU=3,SDSU=4,UGA=1 | 1 -> ND=2,OSU=3,SDSU=4,UGA=1 | 1 -> ND=2,OSU=3,SDSU=4,UGA=1 | 1 -> ND=2,OSU=3,SDSU=4,UGA=1 | 1 -> ND=2,OSU=3,SDSU=4,UGA=1 | 1 -> ND=2,OSU=3,SDSU=4,UGA=1 | 1 -> ND=2,OSU=3,SDSU=4,UGA=1 | 1 -> ND=2,OSU=3,SDSU=4,UGA=1 | 0 -> {}',
    'divisions ok': '2,0,0,2 -> fbs:6,fcs:2 | 2,0,0,2 -> fbs:6,fcs:2 | 2,0,0,2 -> fbs:6,fcs:2 | 2,0,0,2 -> fbs:6,fcs:2 | 2,0,0,2 -> fbs:6,fcs:2 | 2,0,0,2 -> fbs:6,fcs:2 | 2,0,0,2 -> fbs:6,fcs:2 | 2,0,0,2 -> fbs:6,fcs:2 | 2,0,0,2 -> fbs:6,fcs:2',
    'divisions empty': '2,0,2,2 -> fbs:0,fcs:0 | 2,0,2,2 -> fbs:0,fcs:0 | 2,0,2,2 -> fbs:0,fcs:0 | 2,0,2,2 -> fbs:0,fcs:0 | 2,0,2,2 -> fbs:0,fcs:0 | 2,0,2,2 -> fbs:0,fcs:0 | 2,0,2,2 -> fbs:0,fcs:0 | 2,0,2,2 -> fbs:0,fcs:0 | 2,0,2,2 -> fbs:0,fcs:0',
    'divisions cached': '0,0,0,0 -> fbs:2,fcs:1 | 0,0,0,0 -> fbs:2,fcs:1 | 0,0,0,0 -> fbs:2,fcs:1 | 0,0,0,0 -> fbs:2,fcs:1 | 0,0,0,0 -> fbs:2,fcs:1 | 0,0,0,0 -> fbs:2,fcs:1 | 0,0,0,0 -> fbs:2,fcs:1 | 0,0,0,0 -> fbs:2,fcs:1 | 0,0,0,0 -> fbs:2,fcs:1',
}

# when the AP poll's season ends, and when it is fetched: the tables.
EXPECTED_SEASON_OVER = {
    'Oct 12, season ended Apr 8': '{} ; ids {} | {} ; ids {} | {} ; ids {} | {} ; ids {} | {} ; ids {} | {} ; ids {} | {} ; ids {} | {} ; ids {} | {} ; ids {}',
    'a minute before endDate': 'ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | {} ; ids {}',
    'at endDate': 'ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | {} ; ids {}',
    'a minute after endDate': '{} ; ids {} | {} ; ids {} | {} ; ids {} | {} ; ids {} | {} ; ids {} | {} ; ids {} | {} ; ids {} | {} ; ids {} | {} ; ids {}',
    'bowl week, season ends Jan 28': 'ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | {} ; ids {}',
    "new season's first poll": 'ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | {} ; ids {}',
    'endDate with seconds': '{} ; ids {} | {} ; ids {} | {} ; ids {} | {} ; ids {} | {} ; ids {} | {} ; ids {} | {} ; ids {} | {} ; ids {} | {} ; ids {}',
    'endDate unreadable': 'ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | {} ; ids {}',
    'no season block': 'ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | ND=2,OSU=3,SDSU=4,UGA=1 ; ids 194=3,21=4,61=1,87=2 | {} ; ids {}',
}

# payload or failure on /rankings (college-football): requests -> tables ; cached?
EXPECTED_MALFORMED = {
    '{}': 'rankings -> {} ; ids {} ; cached | rankings>standings -> {} ; ids {} ; cached | rankings -> {} ; ids {} ; cached | rankings>standings -> {} ; ids {} ; cached | rankings>standings -> {} ; ids {} ; cached | rankings>standings -> {} ; ids {} ; cached | rankings -> {} ; ids {} ; cached | rankings -> {} ; ids {} ; cached | none -> {} ; ids {} ; cached',
    'rankings []': 'rankings -> {} ; ids {} ; cached | rankings>standings -> {} ; ids {} ; cached | rankings -> {} ; ids {} ; cached | rankings>standings -> {} ; ids {} ; cached | rankings>standings -> {} ; ids {} ; cached | rankings>standings -> {} ; ids {} ; cached | rankings -> {} ; ids {} ; cached | rankings -> {} ; ids {} ; cached | none -> {} ; ids {} ; cached',
    'rankings null': 'rankings -> {} ; ids {} ; cached | rankings>standings -> {} ; ids {} ; cached | rankings -> {} ; ids {} ; cached | rankings>standings -> {} ; ids {} ; cached | rankings>standings -> {} ; ids {} ; cached | rankings>standings -> {} ; ids {} ; cached | rankings -> {} ; ids {} ; cached | rankings -> {} ; ids {} ; cached | none -> {} ; ids {} ; cached',
    'rankings is a dict': 'rankings -> {} ; ids {} ; not cached | rankings -> {} ; ids {} ; not cached | rankings -> {} ; ids {} ; not cached | rankings -> {} ; ids {} ; not cached | rankings -> {} ; ids {} ; not cached | rankings -> {} ; ids {} ; not cached | rankings -> {} ; ids {} ; not cached | rankings -> {} ; ids {} ; not cached | none -> {} ; ids {} ; cached',
    'block without ranks': 'rankings -> {} ; ids {} ; cached | rankings -> {} ; ids {} ; cached | rankings -> {} ; ids {} ; cached | rankings -> {} ; ids {} ; cached | rankings -> {} ; ids {} ; cached | rankings -> {} ; ids {} ; cached | rankings -> {} ; ids {} ; cached | rankings -> {} ; ids {} ; cached | none -> {} ; ids {} ; cached',
    'current 0 / -1 / missing': 'rankings -> TEX=4 ; ids 251=4 ; cached | rankings -> TEX=4 ; ids 251=4 ; cached | rankings -> TEX=4 ; ids 251=4 ; cached | rankings -> TEX=4 ; ids 251=4 ; cached | rankings -> TEX=4 ; ids 251=4 ; cached | rankings -> TEX=4 ; ids 251=4 ; cached | rankings -> TEX=4 ; ids 251=4 ; cached | rankings -> TEX=4 ; ids 251=4 ; cached | none -> {} ; ids {} ; cached',
    'no team / no abbr / bad id': 'rankings -> OSU=3,TEX=4 ; ids 87=2 ; cached | rankings -> OSU=3,TEX=4 ; ids 87=2 ; cached | rankings -> OSU=3,TEX=4 ; ids 87=2 ; cached | rankings -> OSU=3,TEX=4 ; ids 87=2 ; cached | rankings -> OSU=3,TEX=4 ; ids 87=2 ; cached | rankings -> OSU=3,TEX=4 ; ids 87=2 ; cached | rankings -> OSU=3,TEX=4 ; ids 87=2 ; cached | rankings -> OSU=3,TEX=4 ; ids 87=2 ; cached | none -> {} ; ids {} ; cached',
    'HTTP 500': 'rankings -> {} ; ids {} ; cached | rankings>standings -> {} ; ids {} ; cached | rankings -> {} ; ids {} ; cached | rankings>standings -> {} ; ids {} ; cached | rankings>standings -> {} ; ids {} ; cached | rankings>standings -> {} ; ids {} ; cached | rankings -> {} ; ids {} ; cached | rankings -> {} ; ids {} ; cached | none -> {} ; ids {} ; cached',
    'connection error': 'rankings -> {} ; ids {} ; cached | rankings>standings -> {} ; ids {} ; cached | rankings -> {} ; ids {} ; cached | rankings>standings -> {} ; ids {} ; cached | rankings>standings -> {} ; ids {} ; cached | rankings>standings -> {} ; ids {} ; cached | rankings -> {} ; ids {} ; cached | rankings -> {} ; ids {} ; cached | none -> {} ; ids {} ; cached',
    'not JSON': 'rankings -> {} ; ids {} ; cached | rankings>standings -> {} ; ids {} ; cached | rankings -> {} ; ids {} ; cached | rankings>standings -> {} ; ids {} ; cached | rankings>standings -> {} ; ids {} ; cached | rankings>standings -> {} ; ids {} ; cached | rankings -> {} ; ids {} ; cached | rankings -> {} ; ids {} ; cached | none -> {} ; ids {} ; cached',
}

# game, AP poll loaded: _is_ranked_game and _best_rank.
EXPECTED_RANKED = {
    'UGA v TEX (#1)': 'ranked 1 | ranked 1 | ranked 1 | ranked 1 | ranked 1 | ranked 1 | ranked 1 | ranked 1 | unranked 99',
    'TEX v VAN (unranked)': 'unranked 99 | unranked 99 | unranked 99 | unranked 99 | unranked 99 | unranked 99 | unranked 99 | unranked 99 | unranked 99',
    'OSU v VAN (#3)': 'ranked 3 | ranked 3 | ranked 3 | ranked 3 | ranked 3 | ranked 3 | ranked 3 | ranked 3 | unranked 99',
    "Newark 'OSU' v VAN": 'unranked 99 | unranked 99 | unranked 99 | unranked 99 | unranked 99 | unranked 99 | unranked 99 | unranked 99 | unranked 99',
    'SDSU v SDST (#4, FBS v FCS)': 'ranked 4 | ranked 4 | ranked 4 | ranked 4 | ranked 4 | ranked 4 | ranked 4 | ranked 4 | unranked 99',
    'SDST v NDSU (FCS, FCS-ranked)': 'unranked 99 | unranked 99 | unranked 99 | unranked 99 | unranked 99 | unranked 99 | unranked 99 | unranked 99 | unranked 99',
    "'OSU' v VAN, no ids": 'ranked 3 | ranked 3 | ranked 3 | ranked 3 | ranked 3 | ranked 3 | ranked 3 | ranked 3 | unranked 99',
    'id 61 v 238, no abbrs': 'ranked 1 | ranked 1 | ranked 1 | ranked 1 | ranked 1 | ranked 1 | ranked 1 | ranked 1 | unranked 99',
}

# filter: _passes_other_filters over GAMES in order (Y kept, . dropped).
EXPECTED_FILTER = {
    'any': 'YYYYYYYY | YYYYYYYY | YYYYYYYY | YYYYYYYY | YYYYYYYY | YYYYYYYY | YYYYYYYY | YYYYYYYY | YYYYYYYY',
    'ranked': 'Y.Y.Y.YY | Y.Y.Y.YY | Y.Y.Y.YY | Y.Y.Y.YY | Y.Y.Y.YY | Y.Y.Y.YY | Y.Y.Y.YY | Y.Y.Y.YY | YYYYYYYY',
    'ranked, no poll loaded': 'YYYYYYYY | YYYYYYYY | YYYYYYYY | YYYYYYYY | YYYYYYYY | YYYYYYYY | YYYYYYYY | YYYYYYYY | YYYYYYYY',
    'any, fbs': 'YYYYY.YY | YYYYY.YY | YYYYY.YY | YYYYY.YY | YYYYY.YY | YYYYY.YY | YYYYY.YY | YYYYY.YY | YYYYY.YY',
    'ranked, fbs': 'Y.Y.Y.YY | Y.Y.Y.YY | Y.Y.Y.YY | Y.Y.Y.YY | Y.Y.Y.YY | Y.Y.Y.YY | Y.Y.Y.YY | Y.Y.Y.YY | YYYYY.YY',
    'any, fcs': '....YYY. | ....YYY. | ....YYY. | ....YYY. | ....YYY. | ....YYY. | ....YYY. | ....YYY. | ....YYY.',
}


class Clock:
    """``time.time`` and ``time.monotonic``, frozen until a row moves them."""

    now = 100_000.0

    def time(self):
        return self.now

    monotonic = time


class ESPN:
    """Answers every request the family makes, and records it."""

    def __init__(self):
        self.reset({})

    def reset(self, site, rosters=LAST_ROSTER_SEASON):
        self.site, self.rosters, self.log = site, rosters, []

    def get(self, url, params=None, **_kwargs):
        if url.startswith(CORE):
            found = re.search(r"/seasons/(\d+)/types/2/groups/(\d+)/teams$", url)
            season, group = int(found.group(1)), found.group(2)
            self.log.append(f"seasons/{season}/groups/{group}")
            ids = {"80": FBS_IDS, "81": FCS_IDS}.get(group, ())
            items = [{"$ref": f"{CORE}x/teams/{tid}?lang=en"} for tid, _ in ids]
            return response(url, {"count": len(items), "items": items}
                            if season <= self.rosters else {"count": 0, "items": []})
        endpoint = url.rsplit("/", 1)[-1]
        self.log.append(endpoint)
        answer = self.site.get(endpoint, 404)
        if isinstance(answer, type):
            raise answer("refused by the test")
        return response(url, answer)

    def requests(self):
        return ">".join(self.log) or "none"


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


CLOCK, SERVER = Clock(), ESPN()


class Frozen(datetime):
    """``datetime``, with ``now()`` pinned to ``at``."""

    at = datetime(2026, 10, 12, 12, 0)

    @classmethod
    def now(cls, tz=None):
        return cls.at if tz is None else cls.at.replace(tzinfo=tz)


def manager(plugin, sport="football", league="college-football", keep_shared=False):
    """The plugin's real Upcoming manager, pointed at ``sport``/``league``.

    Baseball's leagues keep their rankings on the class as well, shared by the
    league's managers; that copy is emptied unless ``keep_shared``."""
    CLOCK.now = 100_000.0
    mgr = build(plugin, "Upcoming", {"other_games_min_quality": "any",
                                     "other_games_divisions": []})
    mgr.sport, mgr.league = sport, league
    for cls in type(mgr).__mro__:
        if "_shared_rankings_cache" in vars(cls) and not keep_shared:
            cls._shared_rankings_cache, cls._shared_rankings_timestamp = {}, 0
    return mgr


def frozen_at(mgr, when):
    """Freeze ``datetime.now()`` where ``_load_division_team_ids`` reads it.

    The plugin's sports module, or core's ``src.common.sports_rankings`` once
    the plugin inherits it (core 3.8.5)."""
    Frozen.at = when
    return patch.dict(type(mgr)._load_division_team_ids.__globals__, {"datetime": Frozen})


def table(mapping):
    return ",".join(f"{k}={v}" for k, v in sorted(mapping.items(), key=str)) or "{}"


def tables(mgr):
    ids = getattr(mgr, "_ranked_team_ids", None)
    return f"{table(mgr._team_rankings_cache)} ; ids {'-' if ids is None else table(ids)}"


def guarded(fn):
    try:
        return fn()
    except Exception as exc:                          # noqa: BLE001
        return f"!{type(exc).__name__}"


def fetch_row(plugin, sport, league, answers):
    def run():
        mgr = manager(plugin, sport, league)
        SERVER.reset(ANSWERS[answers])
        mgr._fetch_team_rankings()
        return f"{SERVER.requests()} -> {tables(mgr)}"
    return guarded(run)


def poll_row(plugin, label):
    mgr = manager(plugin)
    return guarded(lambda: mgr._choose_poll(POLL_SETS[label]).get("name", "none") or "none")


def rosters(mgr):
    return ",".join(f"{k}:{len(v)}" for k, v in sorted(mgr._load_division_team_ids().items())) \
        or "none"


def season_row(plugin, date, league):
    def run():
        mgr = manager(plugin, "football", league)
        SERVER.reset({})
        with frozen_at(mgr, datetime.fromisoformat(date)):
            found = rosters(mgr)
        return f"{SERVER.requests()} -> {found}"
    return guarded(run)


def requests_per_call(call, steps):
    """Run ``call`` at each offset (s) in ``steps``: requests made by each."""
    counts = []
    for step in steps:
        CLOCK.now = 100_000.0 + step
        before = len(SERVER.log)
        call()
        counts.append(str(len(SERVER.log) - before))
    return ",".join(counts)


def cache_row(plugin, case):
    def run():
        mgr = manager(plugin)
        if case == "rankings, a second manager":
            SERVER.reset(ANSWERS["live"])
            mgr._fetch_team_rankings()
            other = manager(plugin, keep_shared=True)
            counts = requests_per_call(other._fetch_team_rankings, (0,))
            return f"{counts} -> {table(other._team_rankings_cache)}"
        if case.startswith("rankings"):
            SERVER.reset({"live": ANSWERS["live"], "empty": {"rankings": {"rankings": []}},
                          "refused": {"rankings": requests.ConnectionError,
                                      "standings": requests.ConnectionError},
                          }[case.split()[1]])
            counts = requests_per_call(mgr._fetch_team_rankings, (0, 60, 3599))
            held = table(mgr._team_rankings_cache)        # what the cache served
            counts += "," + requests_per_call(mgr._fetch_team_rankings, (3601,))
            return f"{counts} -> {held}"
        SERVER.reset({}, rosters={"ok": LAST_ROSTER_SEASON, "empty": 0,
                                  "cached": LAST_ROSTER_SEASON}[case.split()[1]])
        if case == "divisions cached":
            mgr.cache_manager.get.side_effect = lambda key, *a, **k: (
                ["61", "87"] if key.endswith("_80") else ["2571"])
        with frozen_at(mgr, datetime(2026, 10, 12, 12, 0)):
            counts = requests_per_call(mgr._load_division_team_ids, (0, 60, 601, 86_401))
        return f"{counts} -> {rosters(mgr)}"
    return guarded(run)


CACHE_CASES = ("rankings live", "rankings empty", "rankings refused", "rankings, a second manager",
               "divisions ok", "divisions empty", "divisions cached")


def season_over_row(plugin, label):
    end, at = SEASON_OVER[label]

    def run():
        mgr = manager(plugin)
        block = dict(AP, season={"year": 2026, "endDate": end}) if end else AP
        SERVER.reset({"rankings": {"rankings": [block, COACHES]}, "standings": {}})
        CLOCK.now = datetime.fromisoformat(at).replace(tzinfo=timezone.utc).timestamp()
        mgr._fetch_team_rankings()
        return tables(mgr)
    return guarded(run)


def malformed_row(plugin, label):
    def run():
        mgr = manager(plugin)
        SERVER.reset({"rankings": MALFORMED[label], "standings": {}})
        mgr._fetch_team_rankings()
        cached = "cached" if mgr._rankings_cache_timestamp else "not cached"
        return f"{SERVER.requests()} -> {tables(mgr)} ; {cached}"
    return guarded(run)


def game(home, away):
    g = {"id": "g"}
    for side, (tid, abbr) in (("home", home), ("away", away)):
        if tid is not None:
            g[f"{side}_id"] = tid
        if abbr is not None:
            g[f"{side}_abbr"] = abbr
    return g


def loaded(plugin, with_poll=True):
    """A college-football manager with the AP poll loaded by the real fetch."""
    mgr = manager(plugin)
    SERVER.reset({"rankings": {"rankings": [AP, COACHES] if with_poll else []},
                  "standings": {}})
    mgr._fetch_team_rankings()
    return mgr


def ranked_row(plugin, label):
    def run():
        mgr = loaded(plugin)
        g = game(*GAMES[label])
        return f"{'ranked' if mgr._is_ranked_game(g) else 'unranked'} {mgr._best_rank(g)}"
    return guarded(run)


def filter_row(plugin, label):
    quality, divisions, with_poll = FILTERS[label]

    def run():
        mgr = loaded(plugin, with_poll)
        mgr.other_games_min_quality, mgr.other_games_divisions = quality, divisions
        with frozen_at(mgr, datetime(2026, 10, 12, 12, 0)):
            return "".join("Y" if mgr._passes_other_filters(game(*GAMES[g])) else "."
                           for g in GAMES)
    return guarded(run)


FAMILY = ("_fetch_team_rankings", "_choose_poll", "_load_division_team_ids",
          "_passes_other_filters", "_best_rank", "_is_ranked_game", "_rankings_loaded",
          "_league_has_rankings", "_game_divisions")


def overrides(plugin):
    """Family methods any league manager takes from outside sports.py and core:
    ``file:qualname``, or ``none``."""
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
    tables_ = {name: {} for name in EXPECTED}
    tables_["OVERRIDES"]["league managers"] = " | ".join(overrides(p) for p in SPORTS)
    for sport, league in LEAGUES:
        for answers in ANSWERS:
            tables_["FETCH"][(league, answers)] = row(fetch_row, sport, league, answers)
    for label in POLL_SETS:
        tables_["POLL"][label] = row(poll_row, label)
    for date in DATES:
        tables_["SEASON"][(date, "college-football")] = row(season_row, date, "college-football")
    tables_["SEASON"][(DATES[0], "mens-college-basketball")] = row(
        season_row, DATES[0], "mens-college-basketball")
    for case in CACHE_CASES:
        tables_["CACHE"][case] = row(cache_row, case)
    for label in SEASON_OVER:
        tables_["SEASON_OVER"][label] = row(season_over_row, label)
    for label in MALFORMED:
        tables_["MALFORMED"][label] = row(malformed_row, label)
    for label in GAMES:
        tables_["RANKED"][label] = row(ranked_row, label)
    for label in FILTERS:
        tables_["FILTER"][label] = row(filter_row, label)
    return tables_


#: The committed tables by name, as `observe()` keys them.
EXPECTED = {
    "OVERRIDES": EXPECTED_OVERRIDES,
    "FETCH": EXPECTED_FETCH,
    "POLL": EXPECTED_POLL,
    "SEASON": EXPECTED_SEASON,
    "CACHE": EXPECTED_CACHE,
    "SEASON_OVER": EXPECTED_SEASON_OVER,
    "MALFORMED": EXPECTED_MALFORMED,
    "RANKED": EXPECTED_RANKED,
    "FILTER": EXPECTED_FILTER,
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
            patch("time.monotonic", CLOCK.monotonic), patch("time.time", CLOCK.time):
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
    print(f"  [pass] {rows} rankings rows across {len(SPORTS)} scoreboards")
    return 0


if __name__ == "__main__":
    sys.exit(main())
