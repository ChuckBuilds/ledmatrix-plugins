"""ESPN rejects scoreboard date ranges; the hockey boards must still load.

Since 2026-09-15 ESPN answers ``dates=YYYYMMDD-YYYYMMDD`` with
``400 Bad Request`` for every sport. The hockey managers differ from football's
in one way that matters here: they always submitted the season to the core's
background service, with no synchronous branch. On a core released before the
range fix that service sends the range to ESPN as-is, so the season could never
load. They now fetch it themselves, in chunks, unless the service advertises
``handles_espn_date_ranges``.

Run: <core-venv>/bin/python -m pytest plugins/hockey-scoreboard/test_espn_date_ranges.py
"""

# pylint: disable=protected-access
import logging
import os
import sys
from pathlib import Path

import pytest

plugin_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(plugin_dir))
_core = os.environ.get("LEDMATRIX_CORE")
for _candidate in ([Path(_core)] if _core else []) + [plugin_dir.parents[2] / "LEDMatrix"]:
    if (_candidate / "src" / "plugin_system" / "base_plugin.py").exists():
        sys.path.insert(0, str(_candidate))
        break

try:
    import hockey_espn_dates  # noqa: E402
    import nhl_managers  # noqa: E402
except ModuleNotFoundError as exc:
    # Skip only for a missing core checkout; a missing plugin module is a failure.
    if not (exc.name or "").startswith("src"):
        raise
    pytest.skip(f"LEDMatrix core not importable: {exc}", allow_module_level=True)


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"events": []}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.exceptions.HTTPError(
                f"{self.status_code} Client Error: Bad Request"
            )


class FakeESPN:
    """Answers like ESPN since 2026-09-15: ranges 400, days and months 200."""

    def __init__(self):
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        params = dict(params or {})
        self.calls.append(params)
        dates = str(params.get("dates", ""))
        if hockey_espn_dates.parse_espn_date_range(dates) is not None:
            return FakeResponse(400)
        return FakeResponse(200, {"events": [{"id": "game-" + dates}]})


class Cache:
    def __init__(self):
        self.store = {}

    def get(self, key, *args, **kwargs):
        return self.store.get(key)

    def set(self, key, value, ttl=None):
        self.store[key] = value

    def clear_cache(self, key=None):
        self.store.pop(key, None)


class OldCoreService:
    """A background service from a core released before the range fix."""

    def __init__(self):
        self.submitted = []

    def submit_fetch_request(self, **kwargs):
        self.submitted.append(kwargs)
        return "req-1"


class FixedCoreService(OldCoreService):
    handles_espn_date_ranges = True


@pytest.fixture(autouse=True)
def forget_rejected_ranges(monkeypatch):
    # The rejected-range memo is process-wide; each test starts clean.
    monkeypatch.setattr(hockey_espn_dates, "_ranges_rejected_until", 0.0)


def make_manager(service):
    manager = nhl_managers.NHLRecentManager.__new__(nhl_managers.NHLRecentManager)
    manager.logger = logging.getLogger("test_espn_date_ranges")
    manager.session = FakeESPN()
    manager.headers = {}
    manager.cache_manager = Cache()
    manager.background_service = service
    manager.background_enabled = service is not None
    manager.background_fetch_requests = {}
    manager.mode_config = {}
    manager.sport_key = "nhl"
    manager.sport = "hockey"
    manager.league = "nhl"
    manager.schedule_lookback_days = 1
    manager.schedule_lookahead_days = 1
    return manager


@pytest.mark.parametrize("service", [OldCoreService(), None], ids=["older core", "no service"])
def test_the_window_is_fetched_here_when_the_service_cannot_fetch_ranges(service):
    manager = make_manager(service)

    data = manager._fetch_nhl_api_data(use_cache=True)

    if service is not None:
        assert service.submitted == []
    sent = [call["dates"] for call in manager.session.calls]
    # Only the lookback/lookahead window is asked for, never the season: the
    # whole NHL season was 18MB of JSON, parsed with the GIL held on every
    # read, for games Recent and Upcoming then filtered out.
    expected, window = manager._schedule_window()
    assert sent[0] == expected
    start, end = hockey_espn_dates.parse_espn_date_range(expected)
    chunks = hockey_espn_dates.espn_date_chunks(start, end)
    # The chunks are fetched concurrently, so only the rejected range keeps a
    # fixed position; which chunk answers first is not significant.
    assert sorted(sent[1:]) == sorted(chunks)
    assert len(data["events"]) == len(chunks)
    assert manager.cache_manager.store[f"nhl_schedule_{window}"] is data


def test_the_window_is_the_configured_lookback_and_lookahead():
    from datetime import datetime, timedelta, timezone
    manager = make_manager(None)
    manager.schedule_lookback_days, manager.schedule_lookahead_days = 14, 7
    dates, window = manager._schedule_window()
    now = datetime.now(timezone.utc)
    assert dates == "%s-%s" % ((now - timedelta(days=14)).strftime("%Y%m%d"),
                               (now + timedelta(days=7)).strftime("%Y%m%d"))
    assert window == "window_14_7"


def test_on_a_fixed_core_the_season_goes_to_the_background_service():
    service = FixedCoreService()
    manager = make_manager(service)

    data = manager._fetch_nhl_api_data(use_cache=True)

    assert len(service.submitted) == 1
    # Meanwhile the lookback/lookahead window is shown, recovered from chunks.
    assert data is not None and data["events"]


def test_todays_games_recover_from_a_rejected_range():
    # The lookback is only asked for while it can still hold a live game (see
    # _needs_previous_day), so force it on here: what this pins is the range
    # *recovery*, not when the range is requested.
    manager = make_manager(FixedCoreService())
    manager._needs_previous_day = lambda _now: True
    data = manager._fetch_todays_games()
    assert len(data["events"]) == 2


def test_todays_games_ask_only_for_today_once_yesterday_is_over():
    # Past the cutoff with nothing live from yesterday there is no range to be
    # rejected, so one request does it -- which is the point of the narrowing.
    manager = make_manager(FixedCoreService())
    manager._needs_previous_day = lambda _now: False
    data = manager._fetch_todays_games()
    assert len(data["events"]) == 1
