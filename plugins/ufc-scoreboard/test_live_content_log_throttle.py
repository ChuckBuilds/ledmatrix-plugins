#!/usr/bin/env python3
"""
Regression tests for has_live_content() log throttling.

has_live_content() is called from the display path, which in Vegas mode runs
once per frame. UFC threw away the throttle whenever a fight was live: the
summary at the bottom was guarded by `should_log and not ufc_live`, but a
*second* INFO line sat inside the `if live_games:` block above it with no guard
at all. Because every earlier throttle fix looked at the guard, that call
survived them all and logged on every frame for the duration of a live card.

Covers:
  1. An unchanged live answer logs once, not once per call.
  2. A changed answer (count or boolean) logs immediately.
  3. An unchanged answer is re-logged after the throttle interval.
  4. False results are throttled the same way (the old behavior, preserved).

Run: <core-venv>/bin/python plugins/ufc-scoreboard/test_live_content_log_throttle.py
"""

import os
import sys

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

from manager import UFCScoreboardPlugin  # noqa: E402


class _RecordingLogger:
    def __init__(self):
        self.info_lines = []

    def info(self, msg, *a, **k):
        self.info_lines.append(msg)

    def debug(self, msg, *a, **k):
        pass

    warning = error = debug


class _LiveSource:
    """Stands in for a UFCLiveManager."""

    def __init__(self, fights, favorite_fighters=None):
        self.live_games = fights
        self.favorite_fighters = favorite_fighters or []


class _Stub:
    """Carries just the attributes has_live_content() reads, with the real
    method bound to it -- the full constructor needs a display manager."""

    has_live_content = UFCScoreboardPlugin.has_live_content

    def __init__(self, fights=(), favorite_fighters=None):
        self.logger = _RecordingLogger()
        self.is_enabled = True

        self.ufc_enabled = True
        self.ufc_live_priority = True
        self.ufc_live = _LiveSource(list(fights), favorite_fighters)

        self._last_live_content_log = 0.0
        self._last_live_content_state = None
        self._live_content_log_interval = 60.0


def _fight(one, two):
    return {"fighter1_name": one, "fighter2_name": two, "is_final": False}


def test_unchanged_live_answer_logs_once():
    stub = _Stub(fights=[_fight("Jones", "Miocic"), _fight("Adesanya", "Pereira")])

    for _ in range(200):
        assert stub.has_live_content() is True

    assert len(stub.logger.info_lines) == 1, (
        f"expected 1 log line for 200 identical calls, got {len(stub.logger.info_lines)}"
    )
    assert "live_games=2" in stub.logger.info_lines[0], stub.logger.info_lines[0]


def test_changed_answer_logs_immediately():
    stub = _Stub(fights=[_fight("Jones", "Miocic")])

    for _ in range(50):
        stub.has_live_content()
    assert len(stub.logger.info_lines) == 1

    # A second bout goes live -- the count changed, so it logs without waiting.
    stub.ufc_live.live_games.append(_fight("Adesanya", "Pereira"))
    stub.has_live_content()
    assert len(stub.logger.info_lines) == 2, stub.logger.info_lines
    assert "live_games=2" in stub.logger.info_lines[1]

    # The card ends -- the boolean flipped, so it logs again.
    stub.ufc_live.live_games.clear()
    assert stub.has_live_content() is False
    assert len(stub.logger.info_lines) == 3, stub.logger.info_lines
    assert "returning False" in stub.logger.info_lines[2]


def test_unchanged_answer_relogs_after_interval():
    stub = _Stub(fights=[_fight("Jones", "Miocic")])

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
    assert "live_games=0" in stub.logger.info_lines[0], stub.logger.info_lines[0]


def test_a_live_card_without_a_favorite_still_throttles():
    """The regression that shipped: favorites configured, none of them fighting.

    ufc_live is False but live_games is non-empty, which is exactly the state
    that used to reach the unguarded INFO inside `if live_games:`.
    """
    stub = _Stub(fights=[_fight("Jones", "Miocic")], favorite_fighters=["volkanovski"])

    for _ in range(200):
        assert stub.has_live_content() is False

    assert len(stub.logger.info_lines) == 1, (
        f"a live card with no favorite logged {len(stub.logger.info_lines)} times "
        "in 200 calls; this is the unguarded branch that caused the bug"
    )


if __name__ == "__main__":
    print("has_live_content() log throttle regression tests")
    print("=" * 55)
    failures = []
    for t in (
        test_unchanged_live_answer_logs_once,
        test_changed_answer_logs_immediately,
        test_unchanged_answer_relogs_after_interval,
        test_false_results_are_throttled,
        test_a_live_card_without_a_favorite_still_throttles,
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
