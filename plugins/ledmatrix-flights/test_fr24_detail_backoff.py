#!/usr/bin/env python3
"""FR24 detail lookups must back off when FR24 answers 429.

Regression: on a Pi 4 the journal filled with

    FR24 detail fetch failed for 42a7ab6b: 429 Client Error: Too Many Requests

several times a minute. A refused lookup was dropped from the queue, then
re-queued on the next enrichment pass (nothing was cached), so the plugin
asked again every cycle, three lookups at a time, about 0.2 s apart, and each
refusal logged its own warning. Now the clickhandler lookups share a throttle:
one at a time at least a second apart, a pause that doubles on each 429 (or
honours Retry-After), and lookups held back by it stay queued.

    python plugins/ledmatrix-flights/test_fr24_detail_backoff.py
"""
import logging
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from manager import FlightTrackerPlugin  # noqa: E402
from fetcher import _RemoteThrottle  # noqa: E402

failures = []


def check(label, ok):
    print(("PASS " if ok else "FAIL ") + label)
    if not ok:
        failures.append(label)


def _fail_loudly(fn):
    """Under pytest, fail the test when one of its checks failed."""
    def wrapper():
        before = len(failures)
        fn()
        assert len(failures) == before, failures[before:]
    wrapper.__name__ = fn.__name__
    return wrapper


def plugin():
    p = object.__new__(FlightTrackerPlugin)
    p.logger = logging.getLogger("test-flights")
    p.fr24_detail_cache = {}
    p.fr24_detail_cache_ttl = 12 * 3600
    p._fr24_headers = {}
    p._fr24_detail_throttle = _RemoteThrottle("FR24 detail", min_interval=1.0)
    p.aircraft_data = {"a%d" % i: {"fr24_id": "f%d" % i} for i in range(5)}
    p.pending_fr24_details = {"f%d" % i: "a%d" % i for i in range(5)}
    return p


def response(status, headers=None):
    r = mock.Mock()
    r.status_code = status
    r.headers = headers or {}
    r.json.side_effect = lambda: {"identification": {}}
    r.raise_for_status.return_value = None
    return r


@_fail_loudly
def test_a_429_pauses_lookups_and_keeps_the_queue():
    p = plugin()
    clock = [1000.0]
    with mock.patch("fetcher.time.monotonic", side_effect=lambda: clock[0]), \
            mock.patch("manager.requests.get", return_value=response(429)) as get, \
            mock.patch.object(p.logger, "warning") as warning:
        p._background_fetch_fr24_details()
        check("a 429 stops the batch after one request (%d made)" % get.call_count,
              get.call_count == 1)
        check("the lookups not yet tried stay queued (%d)" % len(p.pending_fr24_details),
              len(p.pending_fr24_details) == 4)
        check("one warning per pause, not per flight (%d)" % warning.call_count,
              warning.call_count == 1)

        clock[0] += 1.5          # past the pacing floor, inside the 2 s pause
        p._background_fetch_fr24_details()
        check("nothing is asked while paused", get.call_count == 1)

        clock[0] += 1.0          # pause over; refused again: the pause doubles
        p._background_fetch_fr24_details()
        clock[0] += 3.0
        p._background_fetch_fr24_details()
        check("a second 429 doubles the pause (%d requests)" % get.call_count,
              get.call_count == 2)


@_fail_loudly
def test_retry_after_is_honoured():
    p = plugin()
    clock = [1000.0]
    with mock.patch("fetcher.time.monotonic", side_effect=lambda: clock[0]), \
            mock.patch("manager.requests.get",
                       return_value=response(429, {"Retry-After": "60"})) as get:
        p._background_fetch_fr24_details()
        clock[0] += 59
        p._background_fetch_fr24_details()
        check("no request before Retry-After elapses", get.call_count == 1)


@_fail_loudly
def test_success_paces_one_lookup_per_second():
    p = plugin()
    clock = [1000.0]
    with mock.patch("fetcher.time.monotonic", side_effect=lambda: clock[0]), \
            mock.patch("manager.requests.get", return_value=response(200)) as get:
        p._background_fetch_fr24_details()
        check("lookups are spaced, not fired back to back (%d)" % get.call_count,
              get.call_count == 1)
        clock[0] += 1.0
        p._background_fetch_fr24_details()
        check("the next one goes out a cycle later", get.call_count == 2)
        check("the detail is cached", "f0" in p.fr24_detail_cache)


if __name__ == "__main__":
    for test in (test_a_429_pauses_lookups_and_keeps_the_queue, test_retry_after_is_honoured,
                 test_success_paces_one_lookup_per_second):
        try:
            test()
        except AssertionError:
            pass
    print("%d failed" % len(failures))
    sys.exit(1 if failures else 0)
