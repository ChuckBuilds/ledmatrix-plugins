#!/usr/bin/env python3
"""
Regression tests for has_live_content() log throttling.

has_live_content() is called from the display path, which in Vegas mode runs
once per frame. The per-league INFO lines had no throttle at all, and the final
summary skipped its throttle whenever the answer was True, so a device with live
games logged on nearly every call -- measured at 13,871 lines/minute on a 512x64
panel with nine live MLB games, which was 98% of the journal.

Covers:
  1. An unchanged live answer logs once, not once per call.
  2. A changed answer (count or boolean) logs immediately.
  3. An unchanged answer is re-logged after the throttle interval.
  4. False results are throttled the same way (the old behavior, preserved).

Run: <core-venv>/bin/python plugins/baseball-scoreboard/test_live_content_log_throttle.py
"""

import os
import sys

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

from manager import BaseballScoreboardPlugin  # noqa: E402


class _RecordingLogger:
    def __init__(self):
        self.info_lines = []

    def info(self, msg, *a, **k):
        self.info_lines.append(msg)

    def debug(self, msg, *a, **k):
        pass

    warning = error = debug


class _LiveSource:
    """Stands in for an MLBLiveManager. Deliberately has no
    _is_game_really_over, so has_live_content() skips that filter."""

    def __init__(self, games, favorite_teams=None):
        self.live_games = games
        self.favorite_teams = favorite_teams or []


class _Stub:
    """Carries just the attributes has_live_content() reads, with the real
    method bound to it -- the full constructor needs a display manager."""

    has_live_content = BaseballScoreboardPlugin.has_live_content

    def __init__(self, mlb_games=(), milb_games=(), ncaa_games=()):
        self.logger = _RecordingLogger()
        self.is_enabled = True

        self.mlb_enabled = True
        self.mlb_live_priority = True
        self.mlb_live = _LiveSource(list(mlb_games))

        self.milb_enabled = True
        self.milb_live_priority = True
        self.milb_live = _LiveSource(list(milb_games))

        self.ncaa_baseball_enabled = True
        self.ncaa_baseball_live_priority = True
        self.ncaa_baseball_live = _LiveSource(list(ncaa_games))

        self._last_live_content_log = 0.0
        self._last_live_content_state = None
        self._live_content_log_interval = 60.0


def _game(home, away):
    return {"home_abbr": home, "away_abbr": away, "is_final": False, "is_live": True}


def test_unchanged_live_answer_logs_once():
    stub = _Stub(mlb_games=[_game("PIT", "CIN"), _game("NYY", "BOS")])

    for _ in range(200):
        assert stub.has_live_content() is True

    assert len(stub.logger.info_lines) == 1, (
        f"expected 1 log line for 200 identical calls, got {len(stub.logger.info_lines)}"
    )
    assert "MLB=2" in stub.logger.info_lines[0], stub.logger.info_lines[0]


def test_changed_answer_logs_immediately():
    stub = _Stub(mlb_games=[_game("PIT", "CIN")])

    for _ in range(50):
        stub.has_live_content()
    assert len(stub.logger.info_lines) == 1

    # A second game starts -- the count changed, so it logs without waiting.
    stub.mlb_live.live_games.append(_game("NYY", "BOS"))
    stub.has_live_content()
    assert len(stub.logger.info_lines) == 2, stub.logger.info_lines
    assert "MLB=2" in stub.logger.info_lines[1]

    # Every game ends -- the boolean flipped, so it logs again.
    stub.mlb_live.live_games.clear()
    assert stub.has_live_content() is False
    assert len(stub.logger.info_lines) == 3, stub.logger.info_lines
    assert "returning False" in stub.logger.info_lines[2]


def test_unchanged_answer_relogs_after_interval():
    stub = _Stub(mlb_games=[_game("PIT", "CIN")])

    stub.has_live_content()
    assert len(stub.logger.info_lines) == 1

    for _ in range(50):
        stub.has_live_content()
    assert len(stub.logger.info_lines) == 1

    # Pretend the interval elapsed: a steady state stays visible in the log.
    stub._last_live_content_log -= stub._live_content_log_interval + 1
    stub.has_live_content()
    assert len(stub.logger.info_lines) == 2, stub.logger.info_lines


def test_false_results_are_throttled():
    stub = _Stub()

    for _ in range(200):
        assert stub.has_live_content() is False

    assert len(stub.logger.info_lines) == 1, (
        f"expected 1 log line for 200 False calls, got {len(stub.logger.info_lines)}"
    )
    assert "live games: none" in stub.logger.info_lines[0], stub.logger.info_lines[0]


if __name__ == "__main__":
    print("has_live_content() log throttle regression tests")
    print("=" * 55)
    failures = []
    for t in (
        test_unchanged_live_answer_logs_once,
        test_changed_answer_logs_immediately,
        test_unchanged_answer_relogs_after_interval,
        test_false_results_are_throttled,
    ):
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failures.append(t.__name__)
            print(f"FAIL {t.__name__}: {e}")
    print("=" * 55)
    if failures:
        print(f"{len(failures)} test(s) failed: {failures}")
        sys.exit(1)
    print("All tests passed.")
