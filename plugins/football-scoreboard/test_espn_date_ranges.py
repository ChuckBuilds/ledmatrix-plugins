"""ESPN rejects scoreboard date ranges; the football boards must still load.

Since 2026-09-15 ESPN answers ``dates=YYYYMMDD-YYYYMMDD`` with
``400 Bad Request`` for every sport. On a Pi that meant NFLLiveManager,
NFLRecentManager, NFLUpcomingManager and the NCAAFB managers all logging
``400 Client Error`` and showing nothing: the live window
(yesterday-today), the lookback/lookahead window and the season schedule are
all ranges.

The fix has three parts, each pinned here against a fake ESPN that behaves
like the real one (ranges 400, days and months answer):

* ``fetch_espn_scoreboard`` (football_espn_dates.py) re-asks a rejected range
  as months plus edge days;
* ``SportsCore._get_weeks_data`` overrides the core mixin's copy, which has no
  such fallback on cores released before the fix;
* the season schedule is only handed to the core background service when that
  service says it can fetch ranges (``handles_espn_date_ranges``). An older
  core would pass the range to ESPN as-is, so the manager fetches it itself.

Run: <core-venv>/bin/python -m pytest plugins/football-scoreboard/test_espn_date_ranges.py
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
    import data_sources  # noqa: E402
    import football_espn_dates  # noqa: E402
    import nfl_managers  # noqa: E402
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
        if football_espn_dates.parse_espn_date_range(dates) is not None:
            return FakeResponse(400)
        return FakeResponse(200, {"events": [{"id": "game-" + dates}]})


class Cache:
    def __init__(self):
        self.store = {}

    def get(self, key, *args, **kwargs):
        return self.store.get(key)

    def set(self, key, value, ttl=None):
        self.store[key] = value

    def delete(self, key):
        self.store.pop(key, None)

    clear_cache = delete


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
    monkeypatch.setattr(football_espn_dates, "_ranges_rejected_until", 0.0)


def make_manager(service):
    manager = nfl_managers.NFLRecentManager.__new__(nfl_managers.NFLRecentManager)
    manager.logger = logging.getLogger("test_espn_date_ranges")
    manager.session = FakeESPN()
    manager.headers = {}
    manager.cache_manager = Cache()
    manager.background_service = service
    manager.background_enabled = service is not None
    manager.background_fetch_requests = {}
    manager.mode_config = {}
    manager.sport_key = "nfl"
    manager.sport = "football"
    manager.league = "nfl"
    manager.schedule_lookback_days = 1
    manager.schedule_lookahead_days = 1
    return manager


def test_the_background_service_is_trusted_only_when_it_says_so():
    assert make_manager(FixedCoreService())._background_fetches_espn_ranges()
    assert not make_manager(OldCoreService())._background_fetches_espn_ranges()
    assert not make_manager(None)._background_fetches_espn_ranges()


def test_on_an_older_core_the_season_is_fetched_here_in_chunks():
    service = OldCoreService()
    manager = make_manager(service)

    data = manager._fetch_nfl_api_data(use_cache=True)

    # Never handed to a service that would send the range to ESPN as-is.
    assert service.submitted == []
    sent = [call["dates"] for call in manager.session.calls]
    start, end = sent[0].split("-")  # {year}0801-{year+1}0301
    year = int(start[:4])
    # The chunks are fetched concurrently, so only the rejected range keeps a
    # fixed position; which chunk answers first is not significant.
    assert sorted(sent[1:]) == sorted([
        f"{year}08", f"{year}09", f"{year}10", f"{year}11", f"{year}12",
        f"{year + 1}01", f"{year + 1}02", end,
    ])
    assert all(call["limit"] <= football_espn_dates.ESPN_MAX_LIMIT for call in manager.session.calls)
    assert len(data["events"]) == 8
    cached = [value for key, value in manager.cache_manager.store.items() if "schedule" in key]
    assert cached and cached[0] is data


def test_on_a_fixed_core_the_season_goes_to_the_background_service():
    service = FixedCoreService()
    manager = make_manager(service)

    data = manager._fetch_nfl_api_data(use_cache=True)

    assert len(service.submitted) == 1
    assert "-" in service.submitted[0]["params"]["dates"]
    # Meanwhile the lookback/lookahead window is shown, recovered from chunks.
    assert data is not None and data["events"]


def test_with_no_background_service_the_season_is_fetched_here():
    manager = make_manager(None)
    data = manager._fetch_nfl_api_data(use_cache=True)
    assert data is not None and data["events"]


def test_the_lookback_window_recovers_from_a_rejected_range():
    manager = make_manager(FixedCoreService())
    data = manager._get_weeks_data()
    sent = [call["dates"] for call in manager.session.calls]
    assert "-" in sent[0]
    assert all("-" not in dates for dates in sent[1:])
    assert [event["id"] for event in data["events"]] == ["game-" + d for d in sent[1:]]


def test_todays_games_recover_from_a_rejected_range():
    # The lookback is only asked for while it can still hold a live game (see
    # _needs_previous_day), so force it on here: what this pins is the range
    # *recovery*, not when the range is requested.
    manager = make_manager(FixedCoreService())
    manager._needs_previous_day = lambda _now: True
    data = manager._fetch_todays_games()
    sent = [call["dates"] for call in manager.session.calls]
    assert len(sent) == 3  # the rejected range, then yesterday and today
    assert len(data["events"]) == 2


def test_todays_games_ask_only_for_today_once_yesterday_is_over():
    # Past the cutoff with nothing live from yesterday there is no range to be
    # rejected, so the whole recovery is skipped and one request does it. This
    # is the point of the narrowing: ESPN rejects ranges, so a two-day window
    # cost two requests on every live poll for a day that holds only finals.
    manager = make_manager(FixedCoreService())
    manager._needs_previous_day = lambda _now: False
    data = manager._fetch_todays_games()
    sent = [call["dates"] for call in manager.session.calls]
    assert len(sent) == 1
    assert "-" not in sent[0]           # a single date, not a range
    assert len(data["events"]) == 1


def test_espn_data_source_schedule_recovers_from_a_rejected_range():
    from datetime import date

    source = data_sources.ESPNDataSource(logging.getLogger("test_espn_date_ranges"))
    source.session = FakeESPN()
    events = source.fetch_schedule("football", "nfl", (date(2026, 9, 1), date(2026, 10, 1)))
    assert [event["id"] for event in events] == ["game-202609", "game-20261001"]
