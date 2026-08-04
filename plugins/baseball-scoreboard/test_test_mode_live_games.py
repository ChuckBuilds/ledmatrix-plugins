#!/usr/bin/env python3
"""
Regression test for SportsLive.update() test-mode handling.

In test mode the live manager seeds a simulated live game (self.live_games).
The bug: update() ignored test_mode and always called _fetch_data(), which
rebuilds live_games from the real (empty) API response — wiping the seeded
game on the first tick, so has_live_content() returned False and the live
view / live-priority never engaged.

The fix short-circuits to _test_mode_update() (and returns) when test_mode is
set, so the seeded game survives. This test verifies that control flow without
needing a display/cache manager.
"""

import contextlib
import os
import sys
import logging

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

from sports import SportsLive  # noqa: E402


class _ConcreteLive(SportsLive):
    """Minimal concrete SportsLive so we can instantiate without the full
    manager stack. The methods update() calls are replaced per-test."""

    def _extract_game_details(self, game):  # abstract in SportsCore
        return None

    def _fetch_data(self):  # abstract in SportsCore
        return None

    def _test_mode_update(self):  # abstract in SportsLive
        return None


def _make_live(test_mode: bool):
    """Build a bare SportsLive with only the attributes update() touches."""
    live = object.__new__(_ConcreteLive)
    live.is_enabled = True
    live.test_mode = test_mode
    live.live_games = [
        {"id": "t1", "home_abbr": "SEA", "away_abbr": "HOU",
         "is_live": True, "is_final": False}
    ]
    live.no_data_interval = 300
    live.update_interval = 30
    live.last_update = 0  # 0 → force an update on this call
    live.show_ranking = False
    live.sport_key = "mlb"
    live.logger = logging.getLogger("test_test_mode")
    return live


def test_test_mode_short_circuits_fetch():
    """test_mode=True must call _test_mode_update(), NOT _fetch_data(), and keep the game."""
    live = _make_live(test_mode=True)
    called = {"fetch": False, "test_update": False}

    class _StopAfterTestUpdate(Exception):
        pass

    def fake_fetch():
        called["fetch"] = True
        live.live_games = []  # reproduce the original overwrite
        return {"events": []}

    def fake_test_update():
        called["test_update"] = True
        # Stop update() right after the short-circuit branch is taken, so we
        # don't run downstream code that touches attributes a bare instance
        # lacks. Catching only this sentinel lets any *unexpected* error surface.
        raise _StopAfterTestUpdate()

    live._fetch_data = fake_fetch
    live._test_mode_update = fake_test_update

    # Guard update() on two expected exits, and only those, so an unrelated
    # failure still surfaces:
    #   _StopAfterTestUpdate - the fixed path; fake_test_update raises it to stop
    #     update() right after the short-circuit branch is taken.
    #   AttributeError       - the buggy path; it enters the live fetch and trips
    #     over attributes a bare instance doesn't have.
    # The invariants below assert the real behaviour either way. Suppressing only
    # AttributeError (as this did) meant the sentinel escaped uncaught and the
    # test died before reaching a single assertion.
    with contextlib.suppress(AttributeError, _StopAfterTestUpdate):
        live.update()

    assert called["test_update"], "expected _test_mode_update() to run in test mode"
    assert not called["fetch"], "_fetch_data() must NOT run in test mode (it wipes the seeded game)"
    assert len(live.live_games) == 1, f"seeded live game must survive, got {len(live.live_games)}"
    print("✓ test_mode short-circuits to _test_mode_update and preserves live_games")


def test_live_mode_still_fetches():
    """test_mode=False must reach _fetch_data() (real data path is unchanged)."""
    live = _make_live(test_mode=False)
    live.live_games = []
    called = {"fetch": False}

    class _StopAfterFetch(Exception):
        pass

    def fake_fetch():
        called["fetch"] = True
        raise _StopAfterFetch()  # we only care that the fetch path is reached

    live._fetch_data = fake_fetch
    try:
        live.update()
    except _StopAfterFetch:
        pass

    assert called["fetch"], "live mode (test_mode=False) must call _fetch_data()"
    print("✓ live mode still calls _fetch_data()")


if __name__ == "__main__":
    print("SportsLive test_mode regression test")
    print("=" * 44)
    ok = True
    for t in (test_test_mode_short_circuits_fetch, test_live_mode_still_fetches):
        try:
            t()
        except AssertionError as e:
            ok = False
            print(f"✗ {t.__name__}: {e}")
    print("=" * 44)
    print("PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)
