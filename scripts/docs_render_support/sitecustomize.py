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

    # Held in a one-element list so advance() can move it without rebinding a
    # closure variable the classmethods below already captured.
    _offset = [0.0]

    def _current():
        return _instant + _datetime_module.timedelta(seconds=_offset[0])

    class _FrozenDateTime(_RealDateTime):
        """A datetime whose "now" only moves when advance() says so."""

        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return _current().astimezone().replace(tzinfo=None)
            return _current().astimezone(tz)

        @classmethod
        def utcnow(cls):
            return _current().astimezone(_datetime_module.timezone.utc).replace(tzinfo=None)

        @classmethod
        def today(cls):
            return cls.now()

    _datetime_module.datetime = _FrozenDateTime
    _time_module.time = lambda: _timestamp + _offset[0]

    def advance(seconds):
        """Move the frozen clock forward.

        Animation is usually driven by elapsed wall-clock time rather than by
        how many times display() was called, so stepping frames against a
        clock that never moves renders the same first frame forever. The
        documentation frame runner calls this between frames.
        """
        _offset[0] += float(seconds)

    # Published for the frame runner; harmless if nothing imports it.
    import builtins as _builtins
    _builtins.__ledmatrix_docs_advance_clock__ = advance

# Recorded HTTP responses, for managers that fetch without reading the cache.
try:
    import _docs_http_replay

    _docs_http_replay.install()
except Exception:  # never let doc tooling break the render it is measuring
    pass
