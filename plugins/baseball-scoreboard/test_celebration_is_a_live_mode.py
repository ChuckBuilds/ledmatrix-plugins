#!/usr/bin/env python3
"""
A win celebration must be selectable as a live mode.

A win fires as the game goes final, so by the time it is on screen the game has
already left the league's live list. has_live_content() said True (a celebration
is running) while get_live_modes() -- which only looked at live games -- said [],
so the display controller saw live content with no live mode of this league to
show for it. Football carried the fix; baseball did not.

Covers, for every league:
  1. A celebration with an empty live list -> get_live_modes() returns that
     league's live mode, and has_live_content() agrees.
  2. A celebration and a live game in the same league -> the mode appears once.
  3. A disabled league, or one with live priority off -> neither method reports
     the celebration.

Run: <core-venv>/bin/python plugins/baseball-scoreboard/test_celebration_is_a_live_mode.py
"""

import os
import sys

import pytest

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

from manager import BaseballScoreboardPlugin  # noqa: E402

LEAGUES = ("mlb", "milb", "ncaa_baseball")


class _QuietLogger:
    def _drop(self, *a, **k):
        pass

    debug = info = warning = error = _drop


class _Live:
    """Stands in for a league's live manager. Has no _is_game_really_over, so
    both methods skip that filter."""

    def __init__(self, games=(), celebrating=False):
        self.live_games = list(games)
        self.favorite_teams = []
        self.celebrating = celebrating

    def has_active_celebration(self):
        return self.celebrating


class _Stub:
    """Carries just the attributes the two methods read, with the real methods
    bound to it -- the full constructor needs a display manager."""

    get_live_modes = BaseballScoreboardPlugin.get_live_modes
    has_live_content = BaseballScoreboardPlugin.has_live_content
    _get_active_celebration_manager = BaseballScoreboardPlugin._get_active_celebration_manager

    def __init__(self, enabled=True, live_priority=True):
        self.logger = _QuietLogger()
        self.is_enabled = True
        self._league_registry = {}
        for league in LEAGUES:
            setattr(self, f"{league}_enabled", enabled)
            setattr(self, f"{league}_live_priority", live_priority)
            setattr(self, f"{league}_live", _Live())
            self._league_registry[league] = {
                "enabled": enabled, "live_priority": live_priority}
        self._last_live_content_log = 0.0
        self._last_live_content_state = None
        self._live_content_log_interval = 60.0

    def _get_league_manager_for_mode(self, league, mode):
        return getattr(self, f"{league}_live") if mode == "live" else None


def _game():
    return {"home_abbr": "ATL", "away_abbr": "PHI", "is_final": False, "is_live": True}


@pytest.mark.parametrize("league", LEAGUES)
def test_celebration_with_empty_live_list_is_a_live_mode(league):
    stub = _Stub()
    getattr(stub, f"{league}_live").celebrating = True

    assert stub.get_live_modes() == [f"{league}_live"]
    assert stub.has_live_content() is True


@pytest.mark.parametrize("league", LEAGUES)
def test_celebration_and_live_game_list_the_mode_once(league):
    stub = _Stub()
    live = getattr(stub, f"{league}_live")
    live.celebrating = True
    live.live_games.append(_game())

    assert stub.get_live_modes() == [f"{league}_live"]
    assert stub.has_live_content() is True


@pytest.mark.parametrize("league", LEAGUES)
@pytest.mark.parametrize("gate", ("enabled", "live_priority"))
def test_gated_off_league_does_not_report_its_celebration(league, gate):
    stub = _Stub(**{gate: False})
    getattr(stub, f"{league}_live").celebrating = True

    assert stub.get_live_modes() == []
    assert stub.has_live_content() is False


def test_only_the_celebrating_league_is_returned():
    stub = _Stub()
    stub.mlb_live.live_games.append(_game())
    stub.ncaa_baseball_live.celebrating = True

    assert stub.get_live_modes() == ["mlb_live", "ncaa_baseball_live"]


def test_no_celebration_and_no_games_is_not_live():
    stub = _Stub()

    assert stub.get_live_modes() == []
    assert stub.has_live_content() is False
