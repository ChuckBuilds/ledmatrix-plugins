"""Serve recorded HTTP responses to a documentation render.

Some managers fetch straight from the network with no cache read, so the
renderer's ``--mock-data`` (which seeds the cache) cannot reach them. Without
this, those screens could only be documented with synthetic data or with a
one-off live capture that no later run could reproduce.

A replay file records real responses, so the render is both real data and
repeatable::

    {"matches": [
      {"url_contains": "baseball/mlb/scoreboard", "body": { ...ESPN JSON... }},
      {"url_contains": "/Images/Primary", "body_file": "poster.png",
       "content_type": "image/png"}
    ]}

``body`` is served as JSON; ``body_file`` names a file beside the replay file
and is served as raw bytes, for poster art, album covers and icons.

Only matching URLs are intercepted. Everything else -- logo downloads in
particular -- goes to the real network untouched.
"""

import json
import os


class _ReplayResponse:
    """The slice of requests.Response that plugin fetch paths actually use."""

    def __init__(self, payload, raw=None, content_type="application/json"):
        self._payload = payload
        self._raw = raw
        self.status_code = 200
        self.headers = {"content-type": content_type}
        self.encoding = "utf-8"

    def json(self, **_kwargs):
        if self._raw is not None:
            raise ValueError("replayed body is binary, not JSON")
        return self._payload

    @property
    def text(self):
        if self._raw is not None:
            return self._raw.decode("utf-8", "replace")
        return json.dumps(self._payload)

    @property
    def content(self):
        # Poster art, album covers and icons arrive as bytes, so a replayed
        # response has to be able to carry a file rather than only JSON.
        if self._raw is not None:
            return self._raw
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
    base = os.path.dirname(os.path.abspath(path))

    _MISS = object()

    def _match(url):
        for entry in matches:
            if entry.get("url_contains", "") not in url:
                continue
            body_file = entry.get("body_file")
            if body_file:
                with open(os.path.join(base, body_file), "rb") as handle:
                    return _ReplayResponse(
                        None, raw=handle.read(),
                        content_type=entry.get("content_type", "application/octet-stream"))
            return _ReplayResponse(entry.get("body"))
        return _MISS

    real_session_get = requests.Session.get
    real_get = requests.get

    def session_get(self, url, *args, **kwargs):
        response = _match(str(url))
        if response is _MISS:
            return real_session_get(self, url, *args, **kwargs)
        return response

    def plain_get(url, *args, **kwargs):
        response = _match(str(url))
        if response is _MISS:
            return real_get(url, *args, **kwargs)
        return response

    requests.Session.get = session_get
    requests.get = plain_get
