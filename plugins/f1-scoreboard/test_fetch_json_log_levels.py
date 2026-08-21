"""OpenF1 returns 404 for an empty result set, which is not an error.

A session that has not run yet has no laps, and OpenF1 answers that with
404 {"detail": "No results found."} instead of an empty list. Logging it at
ERROR filled the journal with ~60 spurious lines a day between race weekends.
"""
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

sys.path.insert(0, str(Path(__file__).parent))


def _fetcher():
    import f1_data
    f = f1_data.F1DataSource.__new__(f1_data.F1DataSource)
    f.session = MagicMock()
    return f


def _raise(status):
    resp = MagicMock()
    resp.status_code = status
    err = requests.HTTPError(f"{status} Client Error", response=resp)
    sess_resp = MagicMock()
    sess_resp.raise_for_status.side_effect = err
    return sess_resp


@pytest.mark.parametrize("status,expected_level", [
    (404, logging.DEBUG),   # "No results found." -- normal, not an error
    (500, logging.ERROR),
    (401, logging.ERROR),
    (403, logging.ERROR),
])
def test_http_error_log_level(caplog, status, expected_level):
    f = _fetcher()
    f.session.get.return_value = _raise(status)
    with caplog.at_level(logging.DEBUG):
        assert f._fetch_json("https://api.openf1.org/v1/laps") is None
    levels = [r.levelno for r in caplog.records if "openf1.org" in r.getMessage()]
    assert levels, "the failure was not logged at all"
    assert max(levels) == expected_level, (
        f"HTTP {status} logged at {logging.getLevelName(max(levels))}, "
        f"expected {logging.getLevelName(expected_level)}")


def test_connection_errors_still_log_at_error(caplog):
    """Only HTTP 404 is downgraded -- transport failures stay ERROR."""
    f = _fetcher()
    f.session.get.side_effect = requests.ConnectionError("no route to host")
    with caplog.at_level(logging.DEBUG):
        assert f._fetch_json("https://api.openf1.org/v1/sessions") is None
    assert any(r.levelno == logging.ERROR for r in caplog.records), \
        "a connection failure must still be an ERROR"
