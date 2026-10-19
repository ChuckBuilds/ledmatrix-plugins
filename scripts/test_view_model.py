#!/usr/bin/env python3
"""The game dict every scoreboard builds from an ESPN event, key by key.

WHY THIS EXISTS
---------------
``SportsCore._extract_game_details_common`` turns one ESPN scoreboard event
into the game dict ("view model") that every renderer reads: the switch-mode
scorebug, the scroll/Vegas card, the managers' selection and live logic. Each
plugin's ``_extract_game_details`` then adds its sport's extras (period text,
clock, down and distance, innings...). The common method was nine different
bodies (LEDMatrix docs/SPORTS_UNIFICATION.md, family 10); it is now one, with
one seam (``_logo_filename``: nrl names a logo by team id too), and its keys
are additive only. The tables record what every plugin builds, so any later
change to either method shows up in a PR as a diff of them, key by key.

For each plugin it builds the primary league's real Recent manager (fake
display; ``test_favourite_matching.build``) with ``favorite_teams`` ["AAA"]
and the timezone America/New_York, and feeds both methods the ESPN-shaped
events in ``ROWS``: one base event (``base_event``) with one thing changed
per row. Nothing reaches the network: football's missing-logo fetcher is
replaced, and ufc's ``format_date_with_ordinal`` (a display-manager call) is
answered with the local time it was given.

* ``COMMON``: the details dict ``_extract_game_details_common`` returns.
* ``FINAL``: the dict ``_extract_game_details`` returns, the game the
  managers keep. ufc's MMA override builds its own without calling the
  common method.

Each entry is ``(row, key): {value: plugins}``, ``all`` standing for all
nine plugins. The ``pre`` row lists every key; any other row lists only the
keys whose value differs from that plugin's own ``pre`` dict, so a plugin
missing from an entry has its ``pre`` value. ``<absent>``: the dict has no
such key. ``<result>``: ``dict``, ``None`` (the method returned no game; its
keys are then not listed) or ``!Name`` (it raised). Values are ``repr``,
datetimes ISO text, paths under the manager's ``logo_dir`` as
``<logo_dir>/...``; a time converted from a naive date is ``<host zone>``.
Every league's managers in a plugin must resolve to the same two methods, so
one league per plugin covers them all; that is checked too.

To see the current tables after an intended change:

    python scripts/test_view_model.py --print

Exit 0 pass, 2 skip (no core checkout), 1 fail.
"""
from __future__ import annotations

import copy
import inspect
import logging
import os
import sys
from datetime import datetime
from pathlib import Path, PurePath
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_favourite_matching import ROLES, build  # noqa: E402
from test_sports_shared_methods import REPO, SPORTS, core_root, load  # noqa: E402

TZ = "America/New_York"
METHODS = ("_extract_game_details_common", "_extract_game_details")
ABSENT = "<absent>"
BASE = "pre"  # the row other rows are recorded against


def competitor(home_away, order, tid, abbr, name, score, record, color):
    return {
        "id": tid, "homeAway": home_away, "order": order, "score": score,
        "team": {"id": tid, "abbreviation": abbr, "name": name,
                 "displayName": f"{name} Club", "color": color,
                 "alternateColor": "ffffff",
                 "logo": f"https://a.espncdn.com/i/teamlogos/{abbr.lower()}.png"},
        "records": [{"name": "overall", "type": "total", "summary": record}],
        "statistics": [{"name": "saves", "displayValue": "20"},
                       {"name": "savePct", "displayValue": ".909"},
                       {"name": "shots", "displayValue": "30"},
                       {"name": "hits", "displayValue": "7"},
                       {"name": "errors", "displayValue": "1"}],
        "linescores": [{"period": 1, "value": 1.0}, {"period": 2, "value": 0.0}],
        "athlete": {"fullName": f"{name} Fighter", "shortName": f"{name[0]}. Fighter",
                    "flag": {"href": f"https://a.espncdn.com/flags/{abbr.lower()}.png"}},
    }


def base_event():
    """A scheduled game, AAA (home, id 1) v BBB (away, id 2), 7:00 PM EDT."""
    return {
        "id": "401", "date": "2026-10-12T23:00Z", "name": "Bravo Club at Alpha Club",
        "competitions": [{
            "id": "4011", "date": "2026-10-12T23:00Z", "broadcast": "ESPN",
            "neutralSite": False, "type": {"id": "1", "abbreviation": "STD"},
            "status": {"displayClock": "0:00", "period": 0, "type": {
                "name": "STATUS_SCHEDULED", "state": "pre", "completed": False,
                "description": "Scheduled", "detail": "Mon, October 12th at 7:00 PM EDT",
                "shortDetail": "10/12 - 7:00 PM EDT"}},
            "competitors": [
                competitor("home", 1, "1", "AAA", "Alpha", "0", "3-1", "c8102e"),
                competitor("away", 2, "2", "BBB", "Bravo", "0", "2-2", "000000"),
            ],
        }],
    }


def comp(e):
    return e["competitions"][0]


def side(e, home_away):
    return next(c for c in comp(e)["competitors"] if c["homeAway"] == home_away)


def status(state, name, short, period=0, clock="0:00", completed=False, **extra):
    """A row edit that sets the competition's status."""
    def edit(e):
        comp(e)["status"] = {"displayClock": clock, "period": period, "type": {
            "name": name, "state": state, "completed": completed,
            "description": short, "detail": short, "shortDetail": short, **extra}}
    return edit


def scores(home, away):
    def edit(e):
        for ha, value in (("home", home), ("away", away)):
            if value is ABSENT:
                side(e, ha).pop("score")
            else:
                side(e, ha)["score"] = value
    return edit


def both(fn):
    """A row edit applied to each competitor."""
    def edit(e):
        for c in comp(e)["competitors"]:
            fn(c)
    return edit


def dated(date, comp_date=None):
    def edit(e):
        e["date"] = date
        comp(e)["date"] = comp_date or date
    return edit


def chain(*edits):
    def edit(e):
        for fn in edits:
            fn(e)
    return edit


def situation(e):
    comp(e)["situation"] = {
        "possession": "1", "isRedZone": True, "downDistanceText": "3rd & 4 at BBB 12",
        "shortDownDistanceText": "3rd & 4", "homeTimeouts": 2, "awayTimeouts": 1,
        "isPowerPlay": True, "penalties": "2 min", "outs": 1,
        "count": {"balls": 2, "strikes": 1}, "onFirst": True}


def tournament(e):
    comp(e)["type"] = {"id": "6", "abbreviation": "TRNMNT"}
    comp(e)["notes"] = [{"headline": "Men's Basketball Championship - South Region - 1st Round"}]
    side(e, "home")["curatedRank"] = {"current": 1}
    side(e, "away")["curatedRank"] = {"current": 16}


IN_PLAY = status("in", "STATUS_IN_PROGRESS", "5:32 - 2nd", period=2, clock="5:32")
FINAL = status("post", "STATUS_FINAL", "Final", period=4, completed=True)

#: label -> (edit applied to base_event(), extra manager config for the row).
ROWS = {
    # States
    "pre": (None, {}),
    "pre, March 5": (dated("2026-03-05T23:00Z"), {}),
    "pre, March 5, short date format": (dated("2026-03-05T23:00Z"),
                                        {"display": {"use_short_date_format": True}}),
    "in, 2nd period 5:32": (chain(IN_PLAY, scores("14", "7"), situation), {}),
    "in, no clock": (chain(IN_PLAY, lambda e: comp(e)["status"].pop("displayClock")), {}),
    "in, halftime": (status("in", "STATUS_HALFTIME", "Halftime", period=2), {}),
    "state halftime": (status("halftime", "STATUS_HALFTIME", "Halftime", period=2), {}),
    "in, end of period 1": (status("in", "STATUS_END_PERIOD", "End of 1st", period=1), {}),
    "in, period 5 (OT)": (status("in", "STATUS_IN_PROGRESS", "OT 2:00", period=5,
                                 clock="2:00"), {}),
    "in, suspended": (status("in", "STATUS_SUSPENDED", "Suspended", period=2), {}),
    "post, final": (chain(FINAL, scores("24", "17")), {}),
    "post, final, period 5 (OT)": (chain(status("post", "STATUS_FINAL", "Final/OT",
                                                period=5, completed=True),
                                         scores("25", "24")), {}),
    "post, final, no completed flag": (chain(FINAL, scores("24", "17"),
                                             lambda e: comp(e)["status"]["type"].pop("completed")), {}),
    "post, postponed": (status("post", "STATUS_POSTPONED", "Postponed"), {}),
    "post, canceled": (status("post", "STATUS_CANCELED", "Canceled"), {}),
    "post, delayed, completed": (status("post", "STATUS_DELAYED", "Delayed", completed=True), {}),
    "post, forfeit, completed": (status("post", "STATUS_FORFEIT", "Forfeit", completed=True), {}),
    # Scores
    "scores int": (chain(FINAL, scores(21, 3)), {}),
    "scores '21.0'": (chain(FINAL, scores("21.0", "3")), {}),
    "scores dict": (chain(FINAL, scores({"value": 21.0, "displayValue": "21"},
                                        {"value": 0, "displayValue": "0"})), {}),
    "scores None and ''": (chain(FINAL, scores(None, "")), {}),
    "scores missing": (chain(FINAL, scores(ABSENT, ABSENT)), {}),
    # Records, ranks, odds
    "records 0-0 and 0-0-0": (lambda e: (side(e, "home")["records"][0].update(summary="0-0"),
                                         side(e, "away")["records"][0].update(summary="0-0-0")), {}),
    "records missing": (both(lambda c: c.pop("records")), {}),
    "records []": (both(lambda c: c.update(records=[])), {}),
    "record, team-schedule shape": (both(lambda c: (c.pop("records"),
                                                    c.update(record=[{"displayValue": "7-0"}]))), {}),
    "ranked, tournament": (tournament, {}),
    "neutral site, odds": (lambda e: comp(e).update(neutralSite=True, odds=[
        {"details": "AAA -3.5", "overUnder": 45.5}]), {}),
    # Teams, logos, colours
    "no abbreviation": (both(lambda c: c["team"].pop("abbreviation")), {}),
    "colliding abbreviations": (lambda e: (side(e, "home")["team"].update(abbreviation="NEW"),
                                           side(e, "away")["team"].update(abbreviation="NEW")), {}),
    "logos array only": (both(lambda c: c["team"].update(
        logos=[{"href": "https://a.espncdn.com/i/teamlogos/500/x.png"}], logo=None)), {}),
    "no logos": (both(lambda c: c["team"].pop("logo")), {}),
    "no colours": (both(lambda c: (c["team"].pop("color"), c["team"].pop("alternateColor"))), {}),
    "competitor without id": (lambda e: side(e, "home").pop("id"), {}),
    "one competitor": (lambda e: comp(e)["competitors"].pop(), {}),
    "no competitors": (lambda e: comp(e).pop("competitors"), {}),
    "no competitions": (lambda e: e.update(competitions=[]), {}),
    "no status": (lambda e: comp(e).pop("status"), {}),
    "broadcast object": (lambda e: comp(e).update(broadcast={"market": "national",
                                                            "names": ["ESPN"]}), {}),
    "broadcast missing": (lambda e: comp(e).pop("broadcast"), {}),
    # Dates and timezones (the board is in America/New_York)
    "no date": (lambda e: e.pop("date"), {}),
    "date 'TBD'": (dated("TBD"), {}),
    "time TBD (timeValid false)": (chain(dated("2026-10-17T04:00Z"),
                                         lambda e: comp(e).update(timeValid=False),
                                         status("pre", "STATUS_SCHEDULED", "10/17 - TBD")), {}),
    "date with seconds": (dated("2026-10-12T23:00:00Z"), {}),
    "date +10:00": (dated("2026-10-13T19:40+10:00"), {}),
    "date naive": (dated("2026-10-12T23:00:00"), {}),
    "late UTC, previous local day": (dated("2026-10-13T03:30Z"), {}),
    "DST ends, 05:30Z (1:30 EDT)": (dated("2026-11-01T05:30Z"), {}),
    "DST ends, 06:30Z (1:30 EST)": (dated("2026-11-01T06:30Z"), {}),
    "DST starts, 07:30Z": (dated("2026-03-08T07:30Z"), {}),
    "naive, repeated DST hour": (dated("2026-11-01T01:30:00"), {}),
    "bout date differs from card date": (dated("2026-10-12T23:00Z", "2026-10-13T02:00Z"), {}),
}

# --------------------------------------------------------------------------
# Expected (current) behaviour: (row, key) -> {value: plugins}. Plugins in
# SPORTS order: afl baseball basketball football hockey lacrosse nrl soccer ufc
# --------------------------------------------------------------------------
EXPECTED_COMMON = {
    ('pre', '<result>'): {'dict': 'all'},
    ('pre', 'away_abbr'): {"'BBB'": 'all'},
    ('pre', 'away_id'): {"'2'": 'all'},
    ('pre', 'away_logo_path'): {'<logo_dir>/BBB.png': 'afl baseball basketball football hockey lacrosse ufc', '<logo_dir>/BBB_2.png': 'nrl soccer'},
    ('pre', 'away_logo_url'): {"'https://a.espncdn.com/i/teamlogos/bbb.png'": 'all'},
    ('pre', 'away_record'): {"'2-2'": 'all'},
    ('pre', 'away_score'): {"'0'": 'all'},
    ('pre', 'broadcast'): {"'ESPN'": 'all'},
    ('pre', 'clock'): {"''": 'all'},
    ('pre', 'favorite_teams'): {"['AAA']": 'afl baseball basketball football hockey lacrosse soccer ufc', "['1']": 'nrl'},
    ('pre', 'game_date'): {"'10/12'": 'all'},
    ('pre', 'game_time'): {"'7:00PM'": 'all'},
    ('pre', 'home_abbr'): {"'AAA'": 'all'},
    ('pre', 'home_id'): {"'1'": 'all'},
    ('pre', 'home_logo_path'): {'<logo_dir>/AAA.png': 'afl baseball basketball football hockey lacrosse ufc', '<logo_dir>/AAA_1.png': 'nrl soccer'},
    ('pre', 'home_logo_url'): {"'https://a.espncdn.com/i/teamlogos/aaa.png'": 'all'},
    ('pre', 'home_record'): {"'3-1'": 'all'},
    ('pre', 'home_score'): {"'0'": 'all'},
    ('pre', 'id'): {"'401'": 'all'},
    ('pre', 'is_final'): {'False': 'all'},
    ('pre', 'is_halftime'): {'False': 'all'},
    ('pre', 'is_live'): {'False': 'all'},
    ('pre', 'is_period_break'): {'False': 'all'},
    ('pre', 'is_upcoming'): {'True': 'all'},
    ('pre', 'is_within_window'): {'True': 'all'},
    ('pre', 'period'): {'0': 'all'},
    ('pre', 'start_time_utc'): {'2026-10-12T23:00:00+00:00': 'all'},
    ('pre', 'status_text'): {"'10/12 - 7:00 PM EDT'": 'all'},
    ('pre, March 5', 'game_date'): {"'03/05'": 'all'},
    ('pre, March 5', 'game_time'): {"'6:00PM'": 'all'},
    ('pre, March 5', 'start_time_utc'): {'2026-03-05T23:00:00+00:00': 'all'},
    ('pre, March 5, short date format', 'game_date'): {"'3/5'": 'all'},
    ('pre, March 5, short date format', 'game_time'): {"'6:00PM'": 'all'},
    ('pre, March 5, short date format', 'start_time_utc'): {'2026-03-05T23:00:00+00:00': 'all'},
    ('in, 2nd period 5:32', 'away_score'): {"'7'": 'all'},
    ('in, 2nd period 5:32', 'home_score'): {"'14'": 'all'},
    ('in, 2nd period 5:32', 'is_live'): {'True': 'all'},
    ('in, 2nd period 5:32', 'is_upcoming'): {'False': 'all'},
    ('in, 2nd period 5:32', 'status_text'): {"'5:32 - 2nd'": 'all'},
    ('in, no clock', 'is_live'): {'True': 'all'},
    ('in, no clock', 'is_upcoming'): {'False': 'all'},
    ('in, no clock', 'status_text'): {"'5:32 - 2nd'": 'all'},
    ('in, halftime', 'is_halftime'): {'True': 'all'},
    ('in, halftime', 'is_live'): {'True': 'all'},
    ('in, halftime', 'is_upcoming'): {'False': 'all'},
    ('in, halftime', 'status_text'): {"'Halftime'": 'all'},
    ('state halftime', 'is_halftime'): {'True': 'all'},
    ('state halftime', 'is_upcoming'): {'False': 'all'},
    ('state halftime', 'status_text'): {"'Halftime'": 'all'},
    ('in, end of period 1', 'is_live'): {'True': 'all'},
    ('in, end of period 1', 'is_period_break'): {'True': 'all'},
    ('in, end of period 1', 'is_upcoming'): {'False': 'all'},
    ('in, end of period 1', 'status_text'): {"'End of 1st'": 'all'},
    ('in, period 5 (OT)', 'is_live'): {'True': 'all'},
    ('in, period 5 (OT)', 'is_upcoming'): {'False': 'all'},
    ('in, period 5 (OT)', 'status_text'): {"'OT 2:00'": 'all'},
    ('in, suspended', 'is_upcoming'): {'False': 'all'},
    ('in, suspended', 'status_text'): {"'Suspended'": 'all'},
    ('post, final', 'away_score'): {"'17'": 'all'},
    ('post, final', 'home_score'): {"'24'": 'all'},
    ('post, final', 'is_final'): {'True': 'all'},
    ('post, final', 'is_upcoming'): {'False': 'all'},
    ('post, final', 'status_text'): {"'Final'": 'all'},
    ('post, final, period 5 (OT)', 'away_score'): {"'24'": 'all'},
    ('post, final, period 5 (OT)', 'home_score'): {"'25'": 'all'},
    ('post, final, period 5 (OT)', 'is_final'): {'True': 'all'},
    ('post, final, period 5 (OT)', 'is_upcoming'): {'False': 'all'},
    ('post, final, period 5 (OT)', 'status_text'): {"'Final/OT'": 'all'},
    ('post, final, no completed flag', 'away_score'): {"'17'": 'all'},
    ('post, final, no completed flag', 'home_score'): {"'24'": 'all'},
    ('post, final, no completed flag', 'is_final'): {'True': 'all'},
    ('post, final, no completed flag', 'is_upcoming'): {'False': 'all'},
    ('post, final, no completed flag', 'status_text'): {"'Final'": 'all'},
    ('post, postponed', 'is_upcoming'): {'False': 'all'},
    ('post, postponed', 'status_text'): {"'Postponed'": 'all'},
    ('post, canceled', 'is_upcoming'): {'False': 'all'},
    ('post, canceled', 'status_text'): {"'Canceled'": 'all'},
    ('post, delayed, completed', 'is_upcoming'): {'False': 'all'},
    ('post, delayed, completed', 'status_text'): {"'Delayed'": 'all'},
    ('post, forfeit, completed', 'is_final'): {'True': 'all'},
    ('post, forfeit, completed', 'is_upcoming'): {'False': 'all'},
    ('post, forfeit, completed', 'status_text'): {"'Forfeit'": 'all'},
    ('scores int', 'away_score'): {"'3'": 'all'},
    ('scores int', 'home_score'): {"'21'": 'all'},
    ('scores int', 'is_final'): {'True': 'all'},
    ('scores int', 'is_upcoming'): {'False': 'all'},
    ('scores int', 'status_text'): {"'Final'": 'all'},
    ("scores '21.0'", 'away_score'): {"'3'": 'all'},
    ("scores '21.0'", 'home_score'): {"'21'": 'all'},
    ("scores '21.0'", 'is_final'): {'True': 'all'},
    ("scores '21.0'", 'is_upcoming'): {'False': 'all'},
    ("scores '21.0'", 'status_text'): {"'Final'": 'all'},
    ('scores dict', 'home_score'): {"'21'": 'all'},
    ('scores dict', 'is_final'): {'True': 'all'},
    ('scores dict', 'is_upcoming'): {'False': 'all'},
    ('scores dict', 'status_text'): {"'Final'": 'all'},
    ("scores None and ''", 'is_final'): {'True': 'all'},
    ("scores None and ''", 'is_upcoming'): {'False': 'all'},
    ("scores None and ''", 'status_text'): {"'Final'": 'all'},
    ('scores missing', 'is_final'): {'True': 'all'},
    ('scores missing', 'is_upcoming'): {'False': 'all'},
    ('scores missing', 'status_text'): {"'Final'": 'all'},
    ('records 0-0 and 0-0-0', 'away_record'): {"''": 'all'},
    ('records 0-0 and 0-0-0', 'home_record'): {"''": 'all'},
    ('records missing', 'away_record'): {"''": 'all'},
    ('records missing', 'home_record'): {"''": 'all'},
    ('records []', 'away_record'): {"''": 'all'},
    ('records []', 'home_record'): {"''": 'all'},
    ('record, team-schedule shape', 'away_record'): {"'7-0'": 'all'},
    ('record, team-schedule shape', 'home_record'): {"'7-0'": 'all'},
    ('no abbreviation', 'away_abbr'): {"'Bra'": 'all'},
    ('no abbreviation', 'away_logo_path'): {'<logo_dir>/BRA.png': 'afl baseball basketball football hockey lacrosse ufc', '<logo_dir>/BRA_2.png': 'nrl soccer'},
    ('no abbreviation', 'home_abbr'): {"'Alp'": 'all'},
    ('no abbreviation', 'home_logo_path'): {'<logo_dir>/ALP.png': 'afl baseball basketball football hockey lacrosse ufc', '<logo_dir>/ALP_1.png': 'nrl soccer'},
    ('colliding abbreviations', 'away_abbr'): {"'NEW'": 'all'},
    ('colliding abbreviations', 'away_logo_path'): {'<logo_dir>/NEW.png': 'afl baseball basketball football hockey lacrosse ufc', '<logo_dir>/NEW_2.png': 'nrl soccer'},
    ('colliding abbreviations', 'home_abbr'): {"'NEW'": 'all'},
    ('colliding abbreviations', 'home_logo_path'): {'<logo_dir>/NEW.png': 'afl baseball basketball football hockey lacrosse ufc', '<logo_dir>/NEW_1.png': 'nrl soccer'},
    ('logos array only', 'away_logo_url'): {"'https://a.espncdn.com/i/teamlogos/500/x.png'": 'all'},
    ('logos array only', 'home_logo_url'): {"'https://a.espncdn.com/i/teamlogos/500/x.png'": 'all'},
    ('no logos', 'away_logo_url'): {'None': 'all'},
    ('no logos', 'home_logo_url'): {'None': 'all'},
    ('one competitor', '<result>'): {'None': 'all'},
    ('no competitors', '<result>'): {'None': 'all'},
    ('no competitions', '<result>'): {'None': 'all'},
    ('no status', '<result>'): {'None': 'all'},
    ('broadcast object', 'broadcast'): {'"{\'market\': \'national\', \'names\': [\'ESPN\']}"': 'all'},
    ('broadcast missing', 'broadcast'): {"''": 'all'},
    ('no date', '<result>'): {'None': 'all'},
    ("date 'TBD'", 'game_date'): {"''": 'all'},
    ("date 'TBD'", 'game_time'): {"''": 'all'},
    ("date 'TBD'", 'start_time_utc'): {'None': 'all'},
    ('time TBD (timeValid false)', 'game_date'): {"'10/17'": 'all'},
    ('time TBD (timeValid false)', 'game_time'): {"'12:00AM'": 'all'},
    ('time TBD (timeValid false)', 'start_time_utc'): {'2026-10-17T04:00:00+00:00': 'all'},
    ('time TBD (timeValid false)', 'status_text'): {"'10/17 - TBD'": 'all'},
    ('date +10:00', 'game_date'): {"'10/13'": 'all'},
    ('date +10:00', 'game_time'): {"'5:40AM'": 'all'},
    ('date +10:00', 'start_time_utc'): {'2026-10-13T09:40:00+00:00': 'all'},
    ('late UTC, previous local day', 'game_time'): {"'11:30PM'": 'all'},
    ('late UTC, previous local day', 'start_time_utc'): {'2026-10-13T03:30:00+00:00': 'all'},
    ('DST ends, 05:30Z (1:30 EDT)', 'game_date'): {"'11/01'": 'all'},
    ('DST ends, 05:30Z (1:30 EDT)', 'game_time'): {"'1:30AM'": 'all'},
    ('DST ends, 05:30Z (1:30 EDT)', 'start_time_utc'): {'2026-11-01T05:30:00+00:00': 'all'},
    ('DST ends, 06:30Z (1:30 EST)', 'game_date'): {"'11/01'": 'all'},
    ('DST ends, 06:30Z (1:30 EST)', 'game_time'): {"'1:30AM'": 'all'},
    ('DST ends, 06:30Z (1:30 EST)', 'start_time_utc'): {'2026-11-01T06:30:00+00:00': 'all'},
    ('DST starts, 07:30Z', 'game_date'): {"'03/08'": 'all'},
    ('DST starts, 07:30Z', 'game_time'): {"'3:30AM'": 'all'},
    ('DST starts, 07:30Z', 'start_time_utc'): {'2026-03-08T07:30:00+00:00': 'all'},
    ('naive, repeated DST hour', 'game_date'): {"'10/31'": 'all'},
    ('naive, repeated DST hour', 'game_time'): {"'9:30PM'": 'all'},
    ('naive, repeated DST hour', 'start_time_utc'): {'2026-11-01T01:30:00+00:00': 'all'},
}

EXPECTED_FINAL = {
    ('pre', '<result>'): {'dict': 'all'},
    ('pre', 'away_abbr'): {"'BBB'": 'afl baseball basketball football hockey lacrosse nrl soccer'},
    ('pre', 'away_errors'): {"'1'": 'baseball'},
    ('pre', 'away_hits'): {"'7'": 'baseball'},
    ('pre', 'away_id'): {"'2'": 'afl baseball basketball football hockey lacrosse nrl soccer'},
    ('pre', 'away_linescore'): {"['1.0', '0.0']": 'baseball'},
    ('pre', 'away_logo_path'): {'<logo_dir>/BBB.png': 'afl baseball basketball football hockey lacrosse', '<logo_dir>/BBB_2.png': 'nrl soccer'},
    ('pre', 'away_logo_url'): {"'https://a.espncdn.com/i/teamlogos/bbb.png'": 'afl baseball basketball football hockey lacrosse nrl soccer'},
    ('pre', 'away_record'): {"'2-2'": 'afl baseball basketball football hockey lacrosse nrl soccer'},
    ('pre', 'away_score'): {"'0'": 'all'},
    ('pre', 'away_seed'): {'0': 'basketball'},
    ('pre', 'away_shots'): {'22': 'hockey', '30': 'lacrosse'},
    ('pre', 'away_team_color'): {'(0, 0, 0)': 'baseball', '(235, 235, 235)': 'hockey'},
    ('pre', 'away_timeouts'): {'0': 'football'},
    ('pre', 'balls'): {'0': 'baseball'},
    ('pre', 'bases_occupied'): {'[False, False, False]': 'baseball'},
    ('pre', 'broadcast'): {"'ESPN'": 'afl baseball basketball football hockey lacrosse nrl soccer'},
    ('pre', 'clock'): {"'0:00'": 'afl basketball football hockey lacrosse nrl soccer', "''": 'baseball ufc'},
    ('pre', 'comp_id'): {"'4011'": 'ufc'},
    ('pre', 'down_distance_text'): {"''": 'football'},
    ('pre', 'down_distance_text_long'): {"''": 'football'},
    ('pre', 'event_id'): {"'401'": 'ufc'},
    ('pre', 'favorite_teams'): {"['AAA']": 'afl baseball basketball football hockey lacrosse soccer', "['1']": 'nrl', '[]': 'ufc'},
    ('pre', 'fight_class'): {"'STD'": 'ufc'},
    ('pre', 'fighter1_country_url'): {"'https://a.espncdn.com/flags/aaa.png'": 'ufc'},
    ('pre', 'fighter1_id'): {"'1'": 'ufc'},
    ('pre', 'fighter1_image_path'): {'<logo_dir>/1.png': 'ufc'},
    ('pre', 'fighter1_image_url'): {"'https://a.espncdn.com/combiner/i?img=/i/headshots/mma/players/full/1.png'": 'ufc'},
    ('pre', 'fighter1_name'): {"'Alpha Fighter'": 'ufc'},
    ('pre', 'fighter1_name_short'): {"'A. Fighter'": 'ufc'},
    ('pre', 'fighter1_record'): {"'3-1'": 'ufc'},
    ('pre', 'fighter2_country_url'): {"'https://a.espncdn.com/flags/bbb.png'": 'ufc'},
    ('pre', 'fighter2_id'): {"'2'": 'ufc'},
    ('pre', 'fighter2_image_path'): {'<logo_dir>/2.png': 'ufc'},
    ('pre', 'fighter2_image_url'): {"'https://a.espncdn.com/combiner/i?img=/i/headshots/mma/players/full/2.png'": 'ufc'},
    ('pre', 'fighter2_name'): {"'Bravo Fighter'": 'ufc'},
    ('pre', 'fighter2_name_short'): {"'B. Fighter'": 'ufc'},
    ('pre', 'fighter2_record'): {"'2-2'": 'ufc'},
    ('pre', 'game_date'): {"'10/12'": 'afl baseball basketball football hockey lacrosse nrl soccer', "'<ordinal 2026-10-12 19:00 EDT>'": 'ufc'},
    ('pre', 'game_time'): {"'7:00PM'": 'all'},
    ('pre', 'has_count_data'): {'False': 'baseball'},
    ('pre', 'home_abbr'): {"'AAA'": 'afl baseball basketball football hockey lacrosse nrl soccer'},
    ('pre', 'home_errors'): {"'1'": 'baseball'},
    ('pre', 'home_hits'): {"'7'": 'baseball'},
    ('pre', 'home_id'): {"'1'": 'afl baseball basketball football hockey lacrosse nrl soccer'},
    ('pre', 'home_linescore'): {"['1.0', '0.0']": 'baseball'},
    ('pre', 'home_logo_path'): {'<logo_dir>/AAA.png': 'afl baseball basketball football hockey lacrosse', '<logo_dir>/AAA_1.png': 'nrl soccer'},
    ('pre', 'home_logo_url'): {"'https://a.espncdn.com/i/teamlogos/aaa.png'": 'afl baseball basketball football hockey lacrosse nrl soccer'},
    ('pre', 'home_record'): {"'3-1'": 'afl baseball basketball football hockey lacrosse nrl soccer'},
    ('pre', 'home_score'): {"'0'": 'all'},
    ('pre', 'home_seed'): {'0': 'basketball'},
    ('pre', 'home_shots'): {'22': 'hockey', '30': 'lacrosse'},
    ('pre', 'home_team_color'): {'(206, 16, 47)': 'baseball hockey'},
    ('pre', 'home_timeouts'): {'0': 'football'},
    ('pre', 'id'): {"'401'": 'afl baseball basketball football hockey lacrosse nrl soccer', "'4011'": 'ufc'},
    ('pre', 'inning'): {'1': 'baseball'},
    ('pre', 'inning_half'): {"'top'": 'baseball'},
    ('pre', 'is_final'): {'False': 'all'},
    ('pre', 'is_halftime'): {'False': 'all'},
    ('pre', 'is_live'): {'False': 'all'},
    ('pre', 'is_period_break'): {'False': 'all'},
    ('pre', 'is_redzone'): {'False': 'football'},
    ('pre', 'is_tournament'): {'False': 'basketball'},
    ('pre', 'is_upcoming'): {'True': 'all'},
    ('pre', 'is_within_window'): {'True': 'all'},
    ('pre', 'league'): {"'afl'": 'afl', "'3'": 'nrl', "'eng.1'": 'soccer'},
    ('pre', 'outs'): {'0': 'baseball'},
    ('pre', 'penalties'): {"''": 'hockey'},
    ('pre', 'period'): {'0': 'all'},
    ('pre', 'period_text'): {"'7:00PM'": 'afl basketball football hockey lacrosse nrl soccer', "''": 'ufc'},
    ('pre', 'possession'): {'None': 'football'},
    ('pre', 'possession_indicator'): {'None': 'football'},
    ('pre', 'power_play'): {'False': 'hockey'},
    ('pre', 'scoring_event'): {"''": 'football'},
    ('pre', 'series_summary'): {"''": 'baseball'},
    ('pre', 'start_time'): {"'2026-10-12T23:00Z'": 'baseball'},
    ('pre', 'start_time_utc'): {'2026-10-12T23:00:00+00:00': 'all'},
    ('pre', 'status'): {"'status_scheduled'": 'baseball'},
    ('pre', 'status_state'): {"'pre'": 'baseball'},
    ('pre', 'status_text'): {"'10/12 - 7:00 PM EDT'": 'all'},
    ('pre', 'strikes'): {'0': 'baseball'},
    ('pre', 'tournament_region'): {"''": 'basketball'},
    ('pre', 'tournament_round'): {"''": 'basketball'},
    ('pre, March 5', 'game_date'): {"'03/05'": 'afl baseball basketball football hockey lacrosse nrl soccer', "'<ordinal 2026-03-05 18:00 EST>'": 'ufc'},
    ('pre, March 5', 'game_time'): {"'6:00PM'": 'all'},
    ('pre, March 5', 'period_text'): {"'6:00PM'": 'afl basketball football hockey lacrosse nrl soccer'},
    ('pre, March 5', 'start_time'): {"'2026-03-05T23:00Z'": 'baseball'},
    ('pre, March 5', 'start_time_utc'): {'2026-03-05T23:00:00+00:00': 'all'},
    ('pre, March 5, short date format', 'game_date'): {"'3/5'": 'all'},
    ('pre, March 5, short date format', 'game_time'): {"'6:00PM'": 'all'},
    ('pre, March 5, short date format', 'period_text'): {"'6:00PM'": 'afl basketball football hockey lacrosse nrl soccer'},
    ('pre, March 5, short date format', 'start_time'): {"'2026-03-05T23:00Z'": 'baseball'},
    ('pre, March 5, short date format', 'start_time_utc'): {'2026-03-05T23:00:00+00:00': 'all'},
    ('in, 2nd period 5:32', 'away_score'): {"'7'": 'all'},
    ('in, 2nd period 5:32', 'away_timeouts'): {'1': 'football'},
    ('in, 2nd period 5:32', 'balls'): {'2': 'baseball'},
    ('in, 2nd period 5:32', 'bases_occupied'): {'[True, False, False]': 'baseball'},
    ('in, 2nd period 5:32', 'clock'): {"'5:32'": 'afl basketball football hockey lacrosse nrl soccer ufc'},
    ('in, 2nd period 5:32', 'down_distance_text'): {"'3rd & 4'": 'football'},
    ('in, 2nd period 5:32', 'down_distance_text_long'): {"'3rd & 4 at BBB 12'": 'football'},
    ('in, 2nd period 5:32', 'has_count_data'): {'True': 'baseball'},
    ('in, 2nd period 5:32', 'home_score'): {"'14'": 'all'},
    ('in, 2nd period 5:32', 'home_timeouts'): {'2': 'football'},
    ('in, 2nd period 5:32', 'inning'): {'2': 'baseball'},
    ('in, 2nd period 5:32', 'is_live'): {'True': 'all'},
    ('in, 2nd period 5:32', 'is_redzone'): {'True': 'football'},
    ('in, 2nd period 5:32', 'is_upcoming'): {'False': 'all'},
    ('in, 2nd period 5:32', 'outs'): {'1': 'baseball'},
    ('in, 2nd period 5:32', 'penalties'): {"'2 min'": 'hockey'},
    ('in, 2nd period 5:32', 'period'): {'2': 'afl basketball football hockey lacrosse nrl soccer ufc'},
    ('in, 2nd period 5:32', 'period_text'): {"'Q2 5:32'": 'afl', "'Q2'": 'basketball football lacrosse', "'P2'": 'hockey', "'2H 5:32'": 'nrl soccer', "'R2'": 'ufc'},
    ('in, 2nd period 5:32', 'possession'): {"'1'": 'football'},
    ('in, 2nd period 5:32', 'possession_indicator'): {"'home'": 'football'},
    ('in, 2nd period 5:32', 'power_play'): {'True': 'hockey'},
    ('in, 2nd period 5:32', 'status'): {"'status_in_progress'": 'baseball'},
    ('in, 2nd period 5:32', 'status_state'): {"'in'": 'baseball'},
    ('in, 2nd period 5:32', 'status_text'): {"'5:32 - 2nd'": 'all'},
    ('in, 2nd period 5:32', 'strikes'): {'1': 'baseball'},
    ('in, no clock', 'clock'): {"''": 'afl nrl soccer'},
    ('in, no clock', 'has_count_data'): {'True': 'baseball'},
    ('in, no clock', 'inning'): {'2': 'baseball'},
    ('in, no clock', 'is_live'): {'True': 'all'},
    ('in, no clock', 'is_upcoming'): {'False': 'all'},
    ('in, no clock', 'period'): {'2': 'afl basketball football hockey lacrosse nrl soccer ufc'},
    ('in, no clock', 'period_text'): {"'Q2'": 'afl basketball football lacrosse', "'P2'": 'hockey', "'2H'": 'nrl soccer', "'R2'": 'ufc'},
    ('in, no clock', 'status'): {"'status_in_progress'": 'baseball'},
    ('in, no clock', 'status_state'): {"'in'": 'baseball'},
    ('in, no clock', 'status_text'): {"'5:32 - 2nd'": 'all'},
    ('in, halftime', 'clock'): {"'0:00'": 'ufc'},
    ('in, halftime', 'has_count_data'): {'True': 'baseball'},
    ('in, halftime', 'inning'): {'2': 'baseball'},
    ('in, halftime', 'is_halftime'): {'True': 'afl baseball basketball football hockey lacrosse nrl soccer'},
    ('in, halftime', 'is_live'): {'True': 'all'},
    ('in, halftime', 'is_upcoming'): {'False': 'all'},
    ('in, halftime', 'period'): {'2': 'afl basketball football hockey lacrosse nrl soccer ufc'},
    ('in, halftime', 'period_text'): {"'HALF'": 'afl basketball football hockey lacrosse nrl soccer', "'R2'": 'ufc'},
    ('in, halftime', 'status'): {"'status_halftime'": 'baseball'},
    ('in, halftime', 'status_state'): {"'in'": 'baseball'},
    ('in, halftime', 'status_text'): {"'Halftime'": 'all'},
    ('state halftime', 'is_halftime'): {'True': 'afl baseball basketball football hockey lacrosse nrl soccer'},
    ('state halftime', 'is_upcoming'): {'False': 'all'},
    ('state halftime', 'period'): {'2': 'afl basketball football hockey lacrosse nrl soccer ufc'},
    ('state halftime', 'period_text'): {"'HALF'": 'afl basketball football hockey lacrosse nrl soccer', "'R2'": 'ufc'},
    ('state halftime', 'status'): {"'status_halftime'": 'baseball'},
    ('state halftime', 'status_state'): {"'halftime'": 'baseball'},
    ('state halftime', 'status_text'): {"'Halftime'": 'all'},
    ('in, end of period 1', 'clock'): {"'0:00'": 'ufc'},
    ('in, end of period 1', 'has_count_data'): {'True': 'baseball'},
    ('in, end of period 1', 'inning'): {'2': 'baseball'},
    ('in, end of period 1', 'is_live'): {'True': 'all'},
    ('in, end of period 1', 'is_period_break'): {'True': 'all'},
    ('in, end of period 1', 'is_upcoming'): {'False': 'all'},
    ('in, end of period 1', 'period'): {'1': 'afl basketball football hockey lacrosse nrl soccer ufc'},
    ('in, end of period 1', 'period_text'): {"'Q1 0:00'": 'afl', "'Q1'": 'basketball football lacrosse', "'P1'": 'hockey', "'1H 0:00'": 'nrl soccer', "'R1'": 'ufc'},
    ('in, end of period 1', 'status'): {"'status_end_period'": 'baseball'},
    ('in, end of period 1', 'status_state'): {"'in'": 'baseball'},
    ('in, end of period 1', 'status_text'): {"'End of 1st'": 'all'},
    ('in, period 5 (OT)', 'clock'): {"'2:00'": 'afl basketball football hockey lacrosse nrl soccer ufc'},
    ('in, period 5 (OT)', 'has_count_data'): {'True': 'baseball'},
    ('in, period 5 (OT)', 'inning'): {'5': 'baseball'},
    ('in, period 5 (OT)', 'is_live'): {'True': 'all'},
    ('in, period 5 (OT)', 'is_upcoming'): {'False': 'all'},
    ('in, period 5 (OT)', 'period'): {'5': 'afl basketball football hockey lacrosse nrl soccer ufc'},
    ('in, period 5 (OT)', 'period_text'): {"'OT1 2:00'": 'afl', "'OT1'": 'basketball football lacrosse', "'OT2'": 'hockey', "'ET 2:00'": 'nrl', "'PEN 2:00'": 'soccer', "'R5'": 'ufc'},
    ('in, period 5 (OT)', 'status'): {"'status_in_progress'": 'baseball'},
    ('in, period 5 (OT)', 'status_state'): {"'in'": 'baseball'},
    ('in, period 5 (OT)', 'status_text'): {"'OT 2:00'": 'all'},
    ('in, suspended', 'clock'): {"'0:00'": 'ufc'},
    ('in, suspended', 'has_count_data'): {'True': 'baseball'},
    ('in, suspended', 'inning'): {'2': 'baseball'},
    ('in, suspended', 'is_live'): {'True': 'ufc'},
    ('in, suspended', 'is_upcoming'): {'False': 'all'},
    ('in, suspended', 'period'): {'2': 'afl basketball football hockey lacrosse nrl soccer ufc'},
    ('in, suspended', 'period_text'): {"'Q2 0:00'": 'afl', "'Q2'": 'basketball football lacrosse', "'P2'": 'hockey', "'2H 0:00'": 'nrl soccer', "'R2'": 'ufc'},
    ('in, suspended', 'status'): {"'status_suspended'": 'baseball'},
    ('in, suspended', 'status_state'): {"'in'": 'baseball'},
    ('in, suspended', 'status_text'): {"'Suspended'": 'all'},
    ('post, final', 'away_score'): {"'17'": 'all'},
    ('post, final', 'clock'): {"'0:00'": 'ufc'},
    ('post, final', 'home_score'): {"'24'": 'all'},
    ('post, final', 'is_final'): {'True': 'all'},
    ('post, final', 'is_upcoming'): {'False': 'all'},
    ('post, final', 'period'): {'4': 'afl basketball football hockey lacrosse nrl soccer ufc'},
    ('post, final', 'period_text'): {"'Final'": 'afl basketball football lacrosse nrl', "'Final/OT'": 'hockey', "'F/ET'": 'soccer', "'R4'": 'ufc'},
    ('post, final', 'status'): {"'status_final'": 'baseball'},
    ('post, final', 'status_state'): {"'post'": 'baseball'},
    ('post, final', 'status_text'): {"'Final'": 'all'},
    ('post, final, period 5 (OT)', 'away_score'): {"'24'": 'all'},
    ('post, final, period 5 (OT)', 'clock'): {"'0:00'": 'ufc'},
    ('post, final, period 5 (OT)', 'home_score'): {"'25'": 'all'},
    ('post, final, period 5 (OT)', 'is_final'): {'True': 'all'},
    ('post, final, period 5 (OT)', 'is_upcoming'): {'False': 'all'},
    ('post, final, period 5 (OT)', 'period'): {'5': 'afl basketball football hockey lacrosse nrl soccer ufc'},
    ('post, final, period 5 (OT)', 'period_text'): {"'Final'": 'afl nrl', "'Final/OT'": 'basketball football hockey lacrosse', "'F/ET'": 'soccer', "'R5'": 'ufc'},
    ('post, final, period 5 (OT)', 'status'): {"'status_final'": 'baseball'},
    ('post, final, period 5 (OT)', 'status_state'): {"'post'": 'baseball'},
    ('post, final, period 5 (OT)', 'status_text'): {"'Final/OT'": 'all'},
    ('post, final, no completed flag', 'away_score'): {"'17'": 'all'},
    ('post, final, no completed flag', 'clock'): {"'0:00'": 'ufc'},
    ('post, final, no completed flag', 'home_score'): {"'24'": 'all'},
    ('post, final, no completed flag', 'is_final'): {'True': 'all'},
    ('post, final, no completed flag', 'is_upcoming'): {'False': 'all'},
    ('post, final, no completed flag', 'period'): {'4': 'afl basketball football hockey lacrosse nrl soccer ufc'},
    ('post, final, no completed flag', 'period_text'): {"'Final'": 'afl basketball football lacrosse nrl', "'Final/OT'": 'hockey', "'F/ET'": 'soccer', "'R4'": 'ufc'},
    ('post, final, no completed flag', 'status'): {"'status_final'": 'baseball'},
    ('post, final, no completed flag', 'status_state'): {"'post'": 'baseball'},
    ('post, final, no completed flag', 'status_text'): {"'Final'": 'all'},
    ('post, postponed', 'is_upcoming'): {'False': 'all'},
    ('post, postponed', 'period_text'): {"'Postponed'": 'afl basketball football hockey lacrosse nrl', "'PPD'": 'soccer'},
    ('post, postponed', 'status'): {"'status_postponed'": 'baseball'},
    ('post, postponed', 'status_state'): {"'post'": 'baseball'},
    ('post, postponed', 'status_text'): {"'Postponed'": 'all'},
    ('post, canceled', 'is_upcoming'): {'False': 'all'},
    ('post, canceled', 'period_text'): {"'Canceled'": 'afl basketball football hockey lacrosse nrl', "'CANC'": 'soccer'},
    ('post, canceled', 'status'): {"'status_canceled'": 'baseball'},
    ('post, canceled', 'status_state'): {"'post'": 'baseball'},
    ('post, canceled', 'status_text'): {"'Canceled'": 'all'},
    ('post, delayed, completed', 'is_upcoming'): {'False': 'all'},
    ('post, delayed, completed', 'period_text'): {"'Delayed'": 'afl basketball football hockey lacrosse nrl', "'DELAY'": 'soccer'},
    ('post, delayed, completed', 'status'): {"'status_delayed'": 'baseball'},
    ('post, delayed, completed', 'status_state'): {"'post'": 'baseball'},
    ('post, delayed, completed', 'status_text'): {"'Delayed'": 'all'},
    ('post, forfeit, completed', 'clock'): {"'0:00'": 'ufc'},
    ('post, forfeit, completed', 'is_final'): {'True': 'all'},
    ('post, forfeit, completed', 'is_upcoming'): {'False': 'all'},
    ('post, forfeit, completed', 'period_text'): {"'Final'": 'afl basketball football hockey lacrosse nrl soccer'},
    ('post, forfeit, completed', 'status'): {"'status_forfeit'": 'baseball'},
    ('post, forfeit, completed', 'status_state'): {"'post'": 'baseball'},
    ('post, forfeit, completed', 'status_text'): {"'Forfeit'": 'all'},
    ('scores int', 'away_score'): {"'3'": 'all'},
    ('scores int', 'clock'): {"'0:00'": 'ufc'},
    ('scores int', 'home_score'): {"'21'": 'all'},
    ('scores int', 'is_final'): {'True': 'all'},
    ('scores int', 'is_upcoming'): {'False': 'all'},
    ('scores int', 'period'): {'4': 'afl basketball football hockey lacrosse nrl soccer ufc'},
    ('scores int', 'period_text'): {"'Final'": 'afl basketball football lacrosse nrl', "'Final/OT'": 'hockey', "'F/ET'": 'soccer', "'R4'": 'ufc'},
    ('scores int', 'status'): {"'status_final'": 'baseball'},
    ('scores int', 'status_state'): {"'post'": 'baseball'},
    ('scores int', 'status_text'): {"'Final'": 'all'},
    ("scores '21.0'", 'away_score'): {"'3'": 'all'},
    ("scores '21.0'", 'clock'): {"'0:00'": 'ufc'},
    ("scores '21.0'", 'home_score'): {"'21'": 'all'},
    ("scores '21.0'", 'is_final'): {'True': 'all'},
    ("scores '21.0'", 'is_upcoming'): {'False': 'all'},
    ("scores '21.0'", 'period'): {'4': 'afl basketball football hockey lacrosse nrl soccer ufc'},
    ("scores '21.0'", 'period_text'): {"'Final'": 'afl basketball football lacrosse nrl', "'Final/OT'": 'hockey', "'F/ET'": 'soccer', "'R4'": 'ufc'},
    ("scores '21.0'", 'status'): {"'status_final'": 'baseball'},
    ("scores '21.0'", 'status_state'): {"'post'": 'baseball'},
    ("scores '21.0'", 'status_text'): {"'Final'": 'all'},
    ('scores dict', 'clock'): {"'0:00'": 'ufc'},
    ('scores dict', 'home_score'): {"'21'": 'all'},
    ('scores dict', 'is_final'): {'True': 'all'},
    ('scores dict', 'is_upcoming'): {'False': 'all'},
    ('scores dict', 'period'): {'4': 'afl basketball football hockey lacrosse nrl soccer ufc'},
    ('scores dict', 'period_text'): {"'Final'": 'afl basketball football lacrosse nrl', "'Final/OT'": 'hockey', "'F/ET'": 'soccer', "'R4'": 'ufc'},
    ('scores dict', 'status'): {"'status_final'": 'baseball'},
    ('scores dict', 'status_state'): {"'post'": 'baseball'},
    ('scores dict', 'status_text'): {"'Final'": 'all'},
    ("scores None and ''", 'clock'): {"'0:00'": 'ufc'},
    ("scores None and ''", 'is_final'): {'True': 'all'},
    ("scores None and ''", 'is_upcoming'): {'False': 'all'},
    ("scores None and ''", 'period'): {'4': 'afl basketball football hockey lacrosse nrl soccer ufc'},
    ("scores None and ''", 'period_text'): {"'Final'": 'afl basketball football lacrosse nrl', "'Final/OT'": 'hockey', "'F/ET'": 'soccer', "'R4'": 'ufc'},
    ("scores None and ''", 'status'): {"'status_final'": 'baseball'},
    ("scores None and ''", 'status_state'): {"'post'": 'baseball'},
    ("scores None and ''", 'status_text'): {"'Final'": 'all'},
    ('scores missing', 'clock'): {"'0:00'": 'ufc'},
    ('scores missing', 'is_final'): {'True': 'all'},
    ('scores missing', 'is_upcoming'): {'False': 'all'},
    ('scores missing', 'period'): {'4': 'afl basketball football hockey lacrosse nrl soccer ufc'},
    ('scores missing', 'period_text'): {"'Final'": 'afl basketball football lacrosse nrl', "'Final/OT'": 'hockey', "'F/ET'": 'soccer', "'R4'": 'ufc'},
    ('scores missing', 'status'): {"'status_final'": 'baseball'},
    ('scores missing', 'status_state'): {"'post'": 'baseball'},
    ('scores missing', 'status_text'): {"'Final'": 'all'},
    ('records 0-0 and 0-0-0', 'away_record'): {"''": 'afl baseball basketball football hockey lacrosse nrl soccer'},
    ('records 0-0 and 0-0-0', 'fighter1_record'): {"''": 'ufc'},
    ('records 0-0 and 0-0-0', 'fighter2_record'): {"''": 'ufc'},
    ('records 0-0 and 0-0-0', 'home_record'): {"''": 'afl baseball basketball football hockey lacrosse nrl soccer'},
    ('records missing', 'away_record'): {"''": 'afl baseball basketball football hockey lacrosse nrl soccer'},
    ('records missing', 'fighter1_record'): {"''": 'ufc'},
    ('records missing', 'fighter2_record'): {"''": 'ufc'},
    ('records missing', 'home_record'): {"''": 'afl baseball basketball football hockey lacrosse nrl soccer'},
    ('records []', 'away_record'): {"''": 'afl baseball basketball football hockey lacrosse nrl soccer'},
    ('records []', 'fighter1_record'): {"''": 'ufc'},
    ('records []', 'fighter2_record'): {"''": 'ufc'},
    ('records []', 'home_record'): {"''": 'afl baseball basketball football hockey lacrosse nrl soccer'},
    ('record, team-schedule shape', 'away_record'): {"'7-0'": 'afl baseball basketball football hockey lacrosse nrl soccer'},
    ('record, team-schedule shape', 'fighter1_record'): {"'7-0'": 'ufc'},
    ('record, team-schedule shape', 'fighter2_record'): {"'7-0'": 'ufc'},
    ('record, team-schedule shape', 'home_record'): {"'7-0'": 'afl baseball basketball football hockey lacrosse nrl soccer'},
    ('ranked, tournament', 'away_seed'): {'16': 'basketball'},
    ('ranked, tournament', 'fight_class'): {"'TRNMNT'": 'ufc'},
    ('ranked, tournament', 'home_seed'): {'1': 'basketball'},
    ('ranked, tournament', 'is_tournament'): {'True': 'basketball'},
    ('ranked, tournament', 'tournament_region'): {"'S'": 'basketball'},
    ('ranked, tournament', 'tournament_round'): {"'R64'": 'basketball'},
    ('no abbreviation', 'away_abbr'): {"'Bra'": 'afl baseball basketball football hockey lacrosse nrl soccer'},
    ('no abbreviation', 'away_logo_path'): {'<logo_dir>/BRA.png': 'afl baseball basketball football hockey lacrosse', '<logo_dir>/BRA_2.png': 'nrl soccer'},
    ('no abbreviation', 'home_abbr'): {"'Alp'": 'afl baseball basketball football hockey lacrosse nrl soccer'},
    ('no abbreviation', 'home_logo_path'): {'<logo_dir>/ALP.png': 'afl baseball basketball football hockey lacrosse', '<logo_dir>/ALP_1.png': 'nrl soccer'},
    ('colliding abbreviations', 'away_abbr'): {"'NEW'": 'afl baseball basketball football hockey lacrosse nrl soccer'},
    ('colliding abbreviations', 'away_logo_path'): {'<logo_dir>/NEW.png': 'afl baseball basketball football hockey lacrosse', '<logo_dir>/NEW_2.png': 'nrl soccer'},
    ('colliding abbreviations', 'home_abbr'): {"'NEW'": 'afl baseball basketball football hockey lacrosse nrl soccer'},
    ('colliding abbreviations', 'home_logo_path'): {'<logo_dir>/NEW.png': 'afl baseball basketball football hockey lacrosse', '<logo_dir>/NEW_1.png': 'nrl soccer'},
    ('logos array only', 'away_logo_url'): {"'https://a.espncdn.com/i/teamlogos/500/x.png'": 'afl baseball basketball football hockey lacrosse nrl soccer'},
    ('logos array only', 'home_logo_url'): {"'https://a.espncdn.com/i/teamlogos/500/x.png'": 'afl baseball basketball football hockey lacrosse nrl soccer'},
    ('no logos', 'away_logo_url'): {'None': 'afl baseball basketball football hockey lacrosse nrl soccer'},
    ('no logos', 'home_logo_url'): {'None': 'afl baseball basketball football hockey lacrosse nrl soccer'},
    ('no colours', 'away_team_color'): {'None': 'baseball hockey'},
    ('no colours', 'home_team_color'): {'None': 'baseball hockey'},
    ('competitor without id', 'fighter1_id'): {"''": 'ufc'},
    ('competitor without id', 'fighter1_image_path'): {'<logo_dir>/None.png': 'ufc'},
    ('competitor without id', 'fighter1_image_url'): {"'https://a.espncdn.com/combiner/i?img=/i/headshots/mma/players/full/None.png'": 'ufc'},
    ('one competitor', '<result>'): {'None': 'all'},
    ('no competitors', '<result>'): {'None': 'all'},
    ('no competitions', '<result>'): {'None': 'all'},
    ('no status', '<result>'): {'None': 'all'},
    ('broadcast object', 'broadcast'): {'"{\'market\': \'national\', \'names\': [\'ESPN\']}"': 'afl baseball basketball football hockey lacrosse nrl soccer'},
    ('broadcast missing', 'broadcast'): {"''": 'afl baseball basketball football hockey lacrosse nrl soccer'},
    ('no date', '<result>'): {'None': 'afl baseball basketball football hockey lacrosse nrl soccer'},
    ("date 'TBD'", 'game_date'): {"''": 'all'},
    ("date 'TBD'", 'game_time'): {"''": 'all'},
    ("date 'TBD'", 'period_text'): {"''": 'afl basketball football hockey lacrosse nrl soccer'},
    ("date 'TBD'", 'start_time'): {"'TBD'": 'baseball'},
    ("date 'TBD'", 'start_time_utc'): {'None': 'all'},
    ('time TBD (timeValid false)', 'game_date'): {"'10/17'": 'afl baseball basketball football hockey lacrosse nrl soccer', "'<ordinal 2026-10-17 00:00 EDT>'": 'ufc'},
    ('time TBD (timeValid false)', 'game_time'): {"'12:00AM'": 'all'},
    ('time TBD (timeValid false)', 'period_text'): {"'12:00AM'": 'afl basketball football hockey lacrosse nrl soccer'},
    ('time TBD (timeValid false)', 'start_time'): {"'2026-10-17T04:00Z'": 'baseball'},
    ('time TBD (timeValid false)', 'start_time_utc'): {'2026-10-17T04:00:00+00:00': 'all'},
    ('time TBD (timeValid false)', 'status_text'): {"'10/17 - TBD'": 'all'},
    ('date with seconds', 'start_time'): {"'2026-10-12T23:00:00Z'": 'baseball'},
    ('date +10:00', 'game_date'): {"'10/13'": 'afl baseball basketball football hockey lacrosse nrl soccer', "'<ordinal 2026-10-13 05:40 EDT>'": 'ufc'},
    ('date +10:00', 'game_time'): {"'5:40AM'": 'all'},
    ('date +10:00', 'period_text'): {"'5:40AM'": 'afl basketball football hockey lacrosse nrl soccer'},
    ('date +10:00', 'start_time'): {"'2026-10-13T19:40+10:00'": 'baseball'},
    ('date +10:00', 'start_time_utc'): {'2026-10-13T09:40:00+00:00': 'afl baseball basketball football hockey lacrosse nrl soccer', '2026-10-13T19:40:00+10:00': 'ufc'},
    ('date naive', 'start_time'): {"'2026-10-12T23:00:00'": 'baseball'},
    ('late UTC, previous local day', 'game_date'): {"'<ordinal 2026-10-12 23:30 EDT>'": 'ufc'},
    ('late UTC, previous local day', 'game_time'): {"'11:30PM'": 'all'},
    ('late UTC, previous local day', 'period_text'): {"'11:30PM'": 'afl basketball football hockey lacrosse nrl soccer'},
    ('late UTC, previous local day', 'start_time'): {"'2026-10-13T03:30Z'": 'baseball'},
    ('late UTC, previous local day', 'start_time_utc'): {'2026-10-13T03:30:00+00:00': 'all'},
    ('DST ends, 05:30Z (1:30 EDT)', 'game_date'): {"'11/01'": 'afl baseball basketball football hockey lacrosse nrl soccer', "'<ordinal 2026-11-01 01:30 EDT>'": 'ufc'},
    ('DST ends, 05:30Z (1:30 EDT)', 'game_time'): {"'1:30AM'": 'all'},
    ('DST ends, 05:30Z (1:30 EDT)', 'period_text'): {"'1:30AM'": 'afl basketball football hockey lacrosse nrl soccer'},
    ('DST ends, 05:30Z (1:30 EDT)', 'start_time'): {"'2026-11-01T05:30Z'": 'baseball'},
    ('DST ends, 05:30Z (1:30 EDT)', 'start_time_utc'): {'2026-11-01T05:30:00+00:00': 'all'},
    ('DST ends, 06:30Z (1:30 EST)', 'game_date'): {"'11/01'": 'afl baseball basketball football hockey lacrosse nrl soccer', "'<ordinal 2026-11-01 01:30 EST>'": 'ufc'},
    ('DST ends, 06:30Z (1:30 EST)', 'game_time'): {"'1:30AM'": 'all'},
    ('DST ends, 06:30Z (1:30 EST)', 'period_text'): {"'1:30AM'": 'afl basketball football hockey lacrosse nrl soccer'},
    ('DST ends, 06:30Z (1:30 EST)', 'start_time'): {"'2026-11-01T06:30Z'": 'baseball'},
    ('DST ends, 06:30Z (1:30 EST)', 'start_time_utc'): {'2026-11-01T06:30:00+00:00': 'all'},
    ('DST starts, 07:30Z', 'game_date'): {"'03/08'": 'afl baseball basketball football hockey lacrosse nrl soccer', "'<ordinal 2026-03-08 03:30 EDT>'": 'ufc'},
    ('DST starts, 07:30Z', 'game_time'): {"'3:30AM'": 'all'},
    ('DST starts, 07:30Z', 'period_text'): {"'3:30AM'": 'afl basketball football hockey lacrosse nrl soccer'},
    ('DST starts, 07:30Z', 'start_time'): {"'2026-03-08T07:30Z'": 'baseball'},
    ('DST starts, 07:30Z', 'start_time_utc'): {'2026-03-08T07:30:00+00:00': 'all'},
    ('naive, repeated DST hour', 'game_date'): {"'10/31'": 'afl baseball basketball football hockey lacrosse nrl soccer', "'<ordinal 2026-10-31 21:30 EDT>'": 'ufc'},
    ('naive, repeated DST hour', 'game_time'): {"'9:30PM'": 'all'},
    ('naive, repeated DST hour', 'period_text'): {"'9:30PM'": 'afl basketball football hockey lacrosse nrl soccer'},
    ('naive, repeated DST hour', 'start_time'): {"'2026-11-01T01:30:00'": 'baseball'},
    ('naive, repeated DST hour', 'start_time_utc'): {'2026-11-01T01:30:00+00:00': 'all'},
    ('bout date differs from card date', 'game_date'): {"'<ordinal 2026-10-12 22:00 EDT>'": 'ufc'},
    ('bout date differs from card date', 'game_time'): {"'10:00PM'": 'ufc'},
    ('bout date differs from card date', 'start_time_utc'): {'2026-10-13T02:00:00+00:00': 'ufc'},
}


def render(value, logo_dir):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, PurePath):
        try:
            return "<logo_dir>/" + Path(value).relative_to(logo_dir).as_posix()
        except ValueError:
            return Path(value).as_posix()
    return repr(value)


def as_cells(result, logo_dir):
    """{key: rendered value} for a details dict, or the outcome alone."""
    if isinstance(result, BaseException):
        return {"<result>": f"!{type(result).__name__}"}
    if result is None:
        return {"<result>": "None"}
    cells = {"<result>": "dict", **{k: render(v, logo_dir) for k, v in result.items()}}
    start = result.get("start_time_utc")
    if isinstance(start, datetime) and start.tzinfo is None:
        # Converted in the host's own zone (Python reads a naive time as
        # local): the same event shows a different time on every host.
        cells.update(game_time="<host zone>", game_date="<host zone>")
    return cells


def call(mgr, method, event):
    try:
        out = getattr(mgr, method)(event)
    except Exception as exc:                          # noqa: BLE001
        return exc
    return out[0] if method == METHODS[0] else out


def build_manager(plugin):
    mgr = build(plugin, "Recent", {"favorite_teams": ["AAA"]})
    mgr.config["timezone"] = TZ
    mgr.display_manager.format_date_with_ordinal.side_effect = (
        lambda dt: f"<ordinal {dt:%Y-%m-%d %H:%M %Z}>")
    return mgr


def method_identity(cls):
    return tuple((Path(fn.__code__.co_filename).name, fn.__qualname__)
                 for fn in (getattr(cls, m) for m in METHODS))


def league_managers_agree(plugin, chosen):
    """Yield a problem for every league manager whose two methods differ from ``chosen``'s."""
    want = method_identity(type(chosen))
    for path in sorted((REPO / "plugins" / f"{plugin}-scoreboard").glob("*_managers.py")):
        mod = load(plugin, path.name)
        for name, cls in inspect.getmembers(mod, inspect.isclass):
            if (cls.__module__ == mod.__name__
                    and any(name.endswith(f"{r}Manager") for r in ROLES)
                    and method_identity(cls) != want):
                yield f"{path.name}:{name} resolves {method_identity(cls)}, not {want}"


def extract(mgr, method, edit, row_config):
    """The cells ``method`` gives for one row's event, with the row's config applied."""
    saved = copy.deepcopy(mgr.config)
    mgr.config.update(row_config)
    event = base_event()
    if edit:
        edit(event)
    try:
        return as_cells(call(mgr, method, event), Path(mgr.logo_dir))
    finally:
        mgr.config.clear()
        mgr.config.update(saved)


def observe(managers, method):
    """One table as this checkout builds it: (row, key) -> {plugin: value}.

    BASE in full; any other row only where it differs from the plugin's BASE.
    """
    table = {}
    for plugin, mgr in managers.items():
        base = extract(mgr, method, *ROWS[BASE])
        for row, (edit, row_config) in ROWS.items():
            cells = extract(mgr, method, edit, row_config)
            if row != BASE and cells["<result>"] != "dict":
                cells = {"<result>": cells["<result>"]}
            elif row != BASE:
                cells = {k: cells.get(k, ABSENT) for k in sorted(set(base) | set(cells))
                         if cells.get(k, ABSENT) != base.get(k, ABSENT)}
            for key, value in cells.items():
                table.setdefault((row, key), {})[plugin] = value
    return table


def grouped(per_plugin):
    """{plugin: value} -> {value: "plugin plugin ..."}, ``all`` for all nine."""
    out = {}
    for plugin in SPORTS:
        if plugin in per_plugin:
            out.setdefault(per_plugin[plugin], []).append(plugin)
    return {v: "all" if len(ps) == len(SPORTS) else " ".join(ps) for v, ps in out.items()}


def ungrouped(by_value):
    """The inverse of ``grouped``."""
    return {p: v for v, ps in by_value.items()
            for p in (SPORTS if ps == "all" else ps.split())}


def print_table(name, table):
    print(f"{name} = {{")
    for key in sorted(table, key=lambda k: (list(ROWS).index(k[0]), k[1])):
        print(f"    {key!r}: {grouped(table[key])!r},")
    print("}\n")


def diff(name, expected, observed):
    problems = []
    for key in sorted(set(expected) | set(observed), key=str):
        want, got = ungrouped(expected.get(key, {})), observed.get(key, {})
        unlisted = ABSENT if key[0] == BASE else f"as in {BASE!r}"
        changed = [p for p in SPORTS if want.get(p, unlisted) != got.get(p, unlisted)]
        if changed:
            problems.append(f"{name} row {key[0]!r} key {key[1]!r}: "
                            + "; ".join(f"{p} expected {want.get(p, unlisted)}, "
                                        f"got {got.get(p, unlisted)}" for p in changed))
    return problems


def main() -> int:
    core = core_root()
    if core is None:
        print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
        return 2
    sys.path.insert(0, str(core))
    logging.disable(logging.CRITICAL)
    os.chdir(core)  # the managers resolve fonts against the core

    managers, problems = {}, []
    for plugin in SPORTS:
        try:
            managers[plugin] = build_manager(plugin)
            problems += [f"{plugin}: {p}" for p in league_managers_agree(plugin, managers[plugin])]
        except Exception as exc:                      # noqa: BLE001
            problems.append(f"{plugin}: building the manager raised "
                            f"{type(exc).__name__}: {exc}")
    if len(managers) < len(SPORTS):
        for p in problems:
            print(f"  [FAIL] {p}")
        return 1

    # football hands any badge not on disk to a background downloader.
    fetcher = type(managers["football"])._ensure_team_logos.__globals__["_LogoFetcher"]
    with patch.object(fetcher, "request"):
        common = observe(managers, METHODS[0])
        final = observe(managers, METHODS[1])
    if "--print" in sys.argv:
        print_table("EXPECTED_COMMON", common)
        print_table("EXPECTED_FINAL", final)
        return 0

    problems += diff("COMMON", EXPECTED_COMMON, common)
    problems += diff("FINAL", EXPECTED_FINAL, final)
    for p in problems:
        print(f"  [FAIL] {p}")
    if problems:
        return 1
    print(f"  [pass] both view-model methods of {len(SPORTS)} scoreboards over "
          f"{len(ROWS)} ESPN events ({len(common) + len(final)} row/key entries)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
