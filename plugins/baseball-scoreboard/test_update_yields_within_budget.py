#!/usr/bin/env python3
"""
Regression test: update() must return under its own steam, inside the slot
the core grants it.

At startup the display controller hands each plugin whatever is left of a
shared deadline, so the slot shrinks as it works down the list. On a live
256x64 rig baseball's slot was 15.4s and 15.96s on consecutive boots, while
this plugin waited 25s on its parallel managers -- a wait it could never
finish, so the core killed the call and logged an ERROR, and the plugin's own
"which managers are slow" branch never ran.

Run: <core-venv>/bin/python plugins/baseball-scoreboard/test_update_yields_within_budget.py
"""

import os
import re
import sys
import time

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

MANAGER_SRC = open(os.path.join(PLUGIN_DIR, "manager.py"), encoding="utf-8").read()

# The smallest per-plugin slot actually observed at startup on hardware.
OBSERVED_SMALLEST_SLOT_SECONDS = 15.4


def _wait_constant():
    m = re.search(r"^_MANAGER_UPDATE_WAIT_SECONDS\s*=\s*([0-9.]+)", MANAGER_SRC, re.M)
    assert m, "expected a module-level _MANAGER_UPDATE_WAIT_SECONDS"
    return float(m.group(1))


def test_wait_fits_inside_the_cores_startup_slot():
    wait = _wait_constant()
    assert wait < OBSERVED_SMALLEST_SLOT_SECONDS, (
        f"update() waits {wait}s but the smallest startup slot measured on a rig "
        f"was {OBSERVED_SMALLEST_SLOT_SECONDS}s -- the core would kill the call "
        f"and log an ERROR before this plugin could return"
    )
    # Headroom, not a hair's breadth: the slot shrinks with however many
    # plugins were updated first, so it is smaller on a busier board.
    assert wait <= OBSERVED_SMALLEST_SLOT_SECONDS * 0.75, (
        f"{wait}s leaves too little headroom under a {OBSERVED_SMALLEST_SLOT_SECONDS}s slot"
    )
    print("test_wait_fits_inside_the_cores_startup_slot: PASS")


def test_the_wait_is_not_hardcoded_at_the_call_site():
    """The old bug was a bare 25 in as_completed(). Keeping the number in one
    named place is what makes it reviewable against the core's budget."""
    assert "as_completed(futures, timeout=_MANAGER_UPDATE_WAIT_SECONDS)" in MANAGER_SRC, \
        "as_completed should use the named constant"
    assert "timeout=25" not in MANAGER_SRC, "the old 25s wait is still present"
    print("test_the_wait_is_not_hardcoded_at_the_call_site: PASS")


def test_slow_managers_are_left_running_not_cancelled():
    """Returning early must not abandon work: a manager already running keeps
    running and populates its cache, which is why yielding costs nothing."""
    from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError

    finished = []

    def slow():
        time.sleep(0.6)
        finished.append(True)

    executor = ThreadPoolExecutor(max_workers=2)
    try:
        futures = {executor.submit(slow): "slow"}
        try:
            for f in as_completed(futures, timeout=0.1):
                f.result()
            raise AssertionError("expected the wait to time out")
        except TimeoutError:
            pass
        still = [n for f, n in futures.items() if not f.done()]
        assert still == ["slow"], still
    finally:
        # Exactly what update() does on the way out.
        executor.shutdown(wait=False, cancel_futures=True)
    time.sleep(1.0)
    assert finished == [True], (
        "a manager that had already started was cancelled -- yielding early "
        "would then lose work, which is not the case in update()"
    )
    print("test_slow_managers_are_left_running_not_cancelled: PASS")


def test_timeout_branch_names_the_slow_managers():
    assert "still_running" in MANAGER_SRC
    assert "leaving to finish in the background" in MANAGER_SRC, \
        "the warning should say the work continues, not that it was lost"
    print("test_timeout_branch_names_the_slow_managers: PASS")


if __name__ == "__main__":
    print("update-budget tests")
    print("=" * 60)
    tests = [
        test_wait_fits_inside_the_cores_startup_slot,
        test_the_wait_is_not_hardcoded_at_the_call_site,
        test_slow_managers_are_left_running_not_cancelled,
        test_timeout_branch_names_the_slow_managers,
    ]
    failures = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failures += 1
            print(f"{t.__name__}: FAIL -- {e}")
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"{t.__name__}: ERROR -- {e}")
    print("=" * 60)
    print("ALL TESTS PASSED" if failures == 0 else f"{failures} TEST(S) FAILED")
    sys.exit(1 if failures else 0)
