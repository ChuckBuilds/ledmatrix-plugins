"""ledmatrix-flights: a throttle skip is not "no data received", and a real
outage warns once per 5 minutes, not once per update tick.

Run: pytest plugins/ledmatrix-flights/test_no_data_logging.py
"""
import sys
import types
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import pytest  # noqa: E402

try:
    import manager as flights  # noqa: E402
except ImportError:  # pragma: no cover
    pytest.skip("LEDMatrix core not on PYTHONPATH", allow_module_level=True)


def plugin_stub(fetcher):
    stub = types.SimpleNamespace(_fetcher=fetcher, data_source="adsblol", logger=mock.Mock(),
                                 NO_DATA_WARN_EVERY_S=flights.FlightTrackerPlugin.NO_DATA_WARN_EVERY_S)
    stub._note_no_data = types.MethodType(flights.FlightTrackerPlugin._note_no_data, stub)
    return stub


def test_throttle_skip_is_debug_only():
    stub = plugin_stub(types.SimpleNamespace(last_skipped=True))
    for _ in range(20):
        stub._note_no_data()
    stub.logger.warning.assert_not_called()


def test_real_outage_warns_once_per_window():
    stub = plugin_stub(types.SimpleNamespace(last_skipped=False))
    clock = [1000.0]
    with mock.patch.object(flights.time, "time", lambda: clock[0]):
        for _ in range(60):            # five minutes of 5 s ticks
            stub._note_no_data()
            clock[0] += 5
        assert stub.logger.warning.call_count == 1
        clock[0] += 1
        stub._note_no_data()
        assert stub.logger.warning.call_count == 2


def test_fetchers_flag_throttle_skips():
    import fetcher
    f = fetcher.AdsbNetFetcher.__new__(fetcher.AdsbNetFetcher)
    f._throttle = types.SimpleNamespace(should_skip=lambda: True)
    f.max_nm, f.provider = 250, "adsblol"
    assert f.fetch(0.0, 0.0, 10, {}) is None and f.last_skipped is True
