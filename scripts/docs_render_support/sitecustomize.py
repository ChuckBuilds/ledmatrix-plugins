"""Freeze the clock for documentation renders.

Injected onto ``PYTHONPATH`` by ``scripts/render_docs_assets.py`` when a shot
declares ``freeze_time``. Python imports ``sitecustomize`` at interpreter
startup -- before the renderer imports anything -- so a plugin that does
``from datetime import datetime`` at module scope still picks up the frozen
class.

Without this, every README image of a clock, a countdown, or a "next game in
2h" screen would differ on each run, and the committed images could never be
verified against a re-render.
"""

import os

_ISO = os.environ.get("LEDMATRIX_DOCS_FREEZE_TIME")

if _ISO:
    import datetime as _datetime_module
    import time as _time_module

    _RealDateTime = _datetime_module.datetime
    _instant = _RealDateTime.fromisoformat(_ISO)
    if _instant.tzinfo is None:
        _instant = _instant.replace(tzinfo=_datetime_module.timezone.utc)
    _timestamp = _instant.timestamp()

    class _FrozenDateTime(_RealDateTime):
        """A datetime whose idea of "now" never moves."""

        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return _instant.astimezone().replace(tzinfo=None)
            return _instant.astimezone(tz)

        @classmethod
        def utcnow(cls):
            return _instant.astimezone(_datetime_module.timezone.utc).replace(tzinfo=None)

        @classmethod
        def today(cls):
            return cls.now()

    _datetime_module.datetime = _FrozenDateTime
    _time_module.time = lambda: _timestamp

# Recorded HTTP responses, for managers that fetch without reading the cache.
try:
    import _docs_http_replay

    _docs_http_replay.install()
except Exception:  # never let doc tooling break the render it is measuring
    pass


# A plugin that shows the device hostname would otherwise bake whoever ran the
# renderer into the committed image, and --check would then fail for everyone
# else. Pinning it keeps the screenshot generic and reproducible.
_HOSTNAME = os.environ.get("LEDMATRIX_DOCS_HOSTNAME")
if _HOSTNAME:
    import socket as _socket

    _socket.gethostname = lambda: _HOSTNAME
    _socket.getfqdn = lambda *_a: _HOSTNAME
