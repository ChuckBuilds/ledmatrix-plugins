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


def _raise(status, body=None):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = body if body is not None else {}
    err = requests.HTTPError(f"{status} Client Error", response=resp)
    sess_resp = MagicMock()
    sess_resp.raise_for_status.side_effect = err
    return sess_resp


OPENF1 = "https://api.openf1.org/v1/laps"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/racing/f1/scoreboard"
JOLPI = "https://api.jolpi.ca/ergast/f1/2026/drivers"
NO_RESULTS = {"detail": "No results found."}


@pytest.mark.parametrize("status,body,expected_level", [
    (404, NO_RESULTS, logging.DEBUG),   # OpenF1's "no rows matched" -- normal
    (404, {}, logging.ERROR),           # a 404 OpenF1 did not explain
    (500, None, logging.ERROR),
    (401, None, logging.ERROR),
    (403, None, logging.ERROR),
])
def test_openf1_http_error_log_level(caplog, status, body, expected_level):
    f = _fetcher()
    f.session.get.return_value = _raise(status, body)
    with caplog.at_level(logging.DEBUG):
        assert f._fetch_json(OPENF1) is None
    levels = [r.levelno for r in caplog.records if "openf1.org" in r.getMessage()]
    assert levels, "the failure was not logged at all"
    assert max(levels) == expected_level, (
        f"HTTP {status} body={body!r} logged at "
        f"{logging.getLevelName(max(levels))}, expected "
        f"{logging.getLevelName(expected_level)}")


@pytest.mark.parametrize("url", [ESPN, JOLPI])
def test_a_404_from_another_host_is_still_an_error(caplog, url):
    """_fetch_json is shared with ESPN and Jolpi.

    Only OpenF1 uses 404 to mean "empty result set". For the others a 404 is a
    genuinely missing resource and must keep its ERROR signal -- even if the
    body happens to look like OpenF1's, which is why the host is checked too.
    """
    f = _fetcher()
    f.session.get.return_value = _raise(404, NO_RESULTS)
    with caplog.at_level(logging.DEBUG):
        assert f._fetch_json(url) is None
    assert any(r.levelno == logging.ERROR for r in caplog.records), (
        f"a 404 from {url} was downgraded; only OpenF1 empty results should be")


def test_an_unreadable_openf1_404_body_is_an_error(caplog):
    """A 404 whose body will not parse is not a known empty result."""
    f = _fetcher()
    resp = MagicMock()
    resp.status_code = 404
    resp.json.side_effect = ValueError("not json")
    sess_resp = MagicMock()
    sess_resp.raise_for_status.side_effect = requests.HTTPError("404", response=resp)
    f.session.get.return_value = sess_resp
    with caplog.at_level(logging.DEBUG):
        assert f._fetch_json(OPENF1) is None
    assert any(r.levelno == logging.ERROR for r in caplog.records)


def test_connection_errors_still_log_at_error(caplog):
    """Only HTTP 404 is downgraded -- transport failures stay ERROR."""
    f = _fetcher()
    f.session.get.side_effect = requests.ConnectionError("no route to host")
    with caplog.at_level(logging.DEBUG):
        assert f._fetch_json(OPENF1) is None
    assert any(r.levelno == logging.ERROR for r in caplog.records), \
        "a connection failure must still be an ERROR"
