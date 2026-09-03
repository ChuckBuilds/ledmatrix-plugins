"""Serve recorded HTTP responses to a documentation render.

Some managers fetch straight from the network with no cache read, so the
renderer's ``--mock-data`` (which seeds the cache) cannot reach them. Without
this, those screens could only be documented with synthetic data or with a
one-off live capture that no later run could reproduce.

A replay file records real responses, so the render is both real data and
repeatable::

    {"matches": [
      {"url_contains": "baseball/mlb/scoreboard", "body": { ...ESPN JSON... }}
    ]}

An entry may also carry ``params_contain``, for an API that puts several
endpoints behind one URL and tells them apart by query string::

    {"url_contains": "datagetter",
     "params_contain": {"product": "water_level"},
     "body": { ... }}

Entries are tried in order and the first whose URL *and* params both match
wins, so put the more specific entries first.

Only matching URLs are intercepted. Everything else -- logo downloads in
particular -- goes to the real network untouched.
"""

import json
import os


class _ReplayResponse:
    """The slice of requests.Response that plugin fetch paths actually use."""

    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200
        self.headers = {"content-type": "application/json"}
        self.encoding = "utf-8"

    def json(self, **_kwargs):
        return self._payload

    @property
    def text(self):
        return json.dumps(self._payload)

    @property
    def content(self):
        return self.text.encode("utf-8")

    def raise_for_status(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def install():
    """Patch requests so recorded URLs are served locally. No-op if unset."""
    path = os.environ.get("LEDMATRIX_DOCS_HTTP_REPLAY")
    if not path:
        return
    try:
        import requests
    except ImportError:
        return

    with open(path, "r", encoding="utf-8") as handle:
        matches = json.load(handle).get("matches", [])
    if not matches:
        return

    _MISS = object()

    def _match(url, params):
        params = params or {}
        for entry in matches:
            if entry.get("url_contains", "") not in url:
                continue
            wanted = entry.get("params_contain") or {}
            if any(str(params.get(key)) != str(value) for key, value in wanted.items()):
                continue
            return entry.get("body")
        return _MISS

    real_session_get = requests.Session.get
    real_get = requests.get

    def session_get(self, url, *args, **kwargs):
        body = _match(str(url), kwargs.get("params"))
        if body is _MISS:
            return real_session_get(self, url, *args, **kwargs)
        return _ReplayResponse(body)

    def plain_get(url, *args, **kwargs):
        body = _match(str(url), kwargs.get("params"))
        if body is _MISS:
            return real_get(url, *args, **kwargs)
        return _ReplayResponse(body)

    requests.Session.get = session_get
    requests.get = plain_get
