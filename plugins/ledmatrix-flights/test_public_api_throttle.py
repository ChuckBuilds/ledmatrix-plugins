"""Free public feeds must be paced, and must go quiet when refused.

The display polls every update_interval -- 5s by default, 2s while following
a live flight -- and every poll went straight out to whichever public feed was
configured. adsb.lol started answering 429, and each refusal came back through
`logger.exception`, so a full traceback was written for a condition that is
neither exceptional nor the caller's to fix:

    ERROR - fetcher - [Flight Tracker] adsblol fetch failed
    Traceback (most recent call last):
      ...
    requests.exceptions.HTTPError: 429 Client Error: Too Many Requests

A fixed floor would not have prevented it. The refusals were observed at
roughly one request every five seconds, so whatever allowance is being
enforced is not a requests-per-second the client can compute in advance. The
floor keeps ordinary polling reasonable; the backoff is what responds to being
told no.

SkyAware is exempt: it reads a receiver on the user's own LAN.
"""
import sys
import time
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))

fetcher = pytest.importorskip("fetcher")


def _response(status=200, payload=None, headers=None):
    r = Mock()
    r.status_code = status
    r.headers = headers or {}
    r.json.return_value = payload if payload is not None else {"ac": []}
    r.raise_for_status.return_value = None
    return r


class TestThrottle:
    def test_first_request_is_allowed(self):
        t = fetcher._RemoteThrottle("x", min_interval=5.0)
        assert not t.should_skip()

    def test_a_second_request_inside_the_floor_is_skipped(self):
        t = fetcher._RemoteThrottle("x", min_interval=5.0)
        t.note_success()
        assert t.should_skip()

    def test_a_refusal_backs_off_further_than_the_floor(self):
        t = fetcher._RemoteThrottle("x", min_interval=5.0)
        wait = t.note_rate_limited()
        assert wait >= 10.0, f"backed off only {wait}s, no more than a normal gap"

    def test_repeated_refusals_escalate(self):
        t = fetcher._RemoteThrottle("x", min_interval=5.0)
        first = t.note_rate_limited()
        second = t.note_rate_limited()
        assert second > first, "backoff does not escalate; a stuck limit is re-hit forever"

    def test_backoff_is_capped(self):
        t = fetcher._RemoteThrottle("x", min_interval=5.0)
        waits = [t.note_rate_limited() for _ in range(20)]
        assert max(waits) <= fetcher._MAX_BACKOFF_SECONDS

    def test_success_clears_the_penalty(self):
        t = fetcher._RemoteThrottle("x", min_interval=5.0)
        t.note_rate_limited()
        t.note_rate_limited()
        t.note_success()
        assert t.note_rate_limited() == pytest.approx(10.0), \
            "penalty survived a success, so one bad patch punishes the rest of the session"

    def test_a_plain_error_does_not_escalate(self):
        # A timeout or a 500 is not a refusal.
        t = fetcher._RemoteThrottle("x", min_interval=5.0)
        t.note_error()
        t.note_error()
        assert t.note_rate_limited() == pytest.approx(10.0)


class TestRetryAfter:
    def test_a_numeric_header_is_honoured(self):
        assert fetcher._retry_after_seconds(_response(429, headers={"Retry-After": "42"})) == 42.0

    def test_a_missing_header_yields_none(self):
        assert fetcher._retry_after_seconds(_response(429)) is None

    def test_an_http_date_is_ignored_rather_than_crashing(self):
        r = _response(429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})
        assert fetcher._retry_after_seconds(r) is None

    def test_an_absurd_header_is_capped(self):
        r = _response(429, headers={"Retry-After": "999999"})
        assert fetcher._retry_after_seconds(r) == fetcher._MAX_BACKOFF_SECONDS


class TestFetchersPaceThemselves:
    def _fetchers(self):
        return [
            ("adsblol", fetcher.AdsbNetFetcher(provider="adsblol")),
            ("opensky", fetcher.OpenSkyFetcher()),
            ("fr24", fetcher.FR24Fetcher()),
        ]

    def test_public_fetchers_have_a_throttle(self):
        for name, f in self._fetchers():
            assert hasattr(f, "_throttle"), f"{name} has no throttle"

    def test_the_local_receiver_is_not_throttled(self):
        # SkyAware is the user's own hardware on their own LAN.
        f = fetcher.SkyAwareFetcher("http://192.168.0.2/skyaware/data/aircraft.json",
                                    cache_manager=None)
        assert not hasattr(f, "_throttle"), \
            "SkyAware is local; pacing it only makes the display staler"

    def test_a_429_does_not_raise_and_returns_no_data(self):
        for name, f in self._fetchers():
            with patch.object(fetcher.requests, "get", return_value=_response(429)):
                out = f.fetch(27.95, -82.46, 20, {})
            assert out is None, f"{name} returned data for a 429"

    def test_the_second_poll_after_a_429_does_not_reach_the_network(self):
        for name, f in self._fetchers():
            with patch.object(fetcher.requests, "get", return_value=_response(429)):
                f.fetch(27.95, -82.46, 20, {})
            with patch.object(fetcher.requests, "get") as g:
                f.fetch(27.95, -82.46, 20, {})
                assert g.call_count == 0, \
                    f"{name} kept polling through its own backoff"

    def test_a_successful_poll_still_paces_the_next_one(self):
        f = fetcher.AdsbNetFetcher(provider="adsblol")
        with patch.object(fetcher.requests, "get", return_value=_response(200, {"ac": []})):
            f.fetch(27.95, -82.46, 20, {})
        with patch.object(fetcher.requests, "get") as g:
            f.fetch(27.95, -82.46, 20, {})
            assert g.call_count == 0, "no floor between successful polls"
