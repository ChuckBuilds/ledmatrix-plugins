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


# Some plugins hold their interesting state in memory, put there by an event
# the renderer cannot produce -- an MQTT message, a webhook, a button press.
# No configuration reaches that state, so a documentation render would only
# ever show the idle frame. LEDMATRIX_DOCS_ATTRS names attributes to set on the
# plugin instance once the core's loader has built it, which is the same thing
# the event would have done, without the plugin knowing it is being rendered.
_ATTRS = os.environ.get("LEDMATRIX_DOCS_ATTRS")
if _ATTRS:
    import json as _json
    import sys as _sys

    _WANTED = _json.loads(_ATTRS)
    _TARGET = "src.plugin_system.plugin_loader"

    def _resolve(instance, path):
        """Walk a dotted path to the object that owns the final attribute.

        The sports scoreboards keep their per-mode state on sub-managers rather
        than on the plugin -- self._managers["live"].current_game -- so a shot
        that can only set top-level attributes cannot reach the game it wants
        to draw. A segment is tried as a mapping key first, then as an
        attribute, so both self._managers["live"] and self.live_manager work.
        """
        parts = path.split(".")
        target = instance
        for part in parts[:-1]:
            if hasattr(target, "get") and not hasattr(target, part):
                nxt = target.get(part)
            else:
                nxt = getattr(target, part, None)
                if nxt is None and hasattr(target, "get"):
                    nxt = target.get(part)
            if nxt is None:
                return None, None
            target = nxt
        return target, parts[-1]

    def _apply(instance):
        for name, value in _WANTED.items():
            if isinstance(value, list) and len(value) == 3 and all(
                    isinstance(v, int) for v in value):
                value = tuple(value)  # colours are tuples everywhere in the core
            owner, attr = _resolve(instance, name)
            if owner is None:
                continue  # the path does not exist on this plugin; leave it alone
            if hasattr(owner, "__setitem__") and not hasattr(owner, attr):
                owner[attr] = value
            else:
                setattr(owner, attr, value)
        return instance

    class _PatchingLoader:
        """Wraps the real loader so the module is patched right after it runs."""

        def __init__(self, inner):
            self._inner = inner

        def create_module(self, spec):
            return self._inner.create_module(spec)

        def exec_module(self, module):
            self._inner.exec_module(module)
            real = module.PluginLoader.load_plugin

            def load_plugin(self, *args, **kwargs):
                instance, mod = real(self, *args, **kwargs)
                return _apply(instance), mod

            module.PluginLoader.load_plugin = load_plugin

        def __getattr__(self, name):
            return getattr(self._inner, name)

    class _AttrFinder:
        """Hands back the real spec with its loader wrapped, once."""

        def find_spec(self, name, path=None, target=None):
            if name != _TARGET:
                return None
            index = _sys.meta_path.index(self)
            for finder in _sys.meta_path[index + 1:]:
                find = getattr(finder, "find_spec", None)
                spec = find(name, path, target) if find else None
                if spec is not None and spec.loader is not None:
                    spec.loader = _PatchingLoader(spec.loader)
                    return spec
            return None

    _sys.meta_path.insert(0, _AttrFinder())


# A plugin that shows the device hostname would otherwise bake whoever ran the
# renderer into the committed image, and --check would then fail for everyone
# else. Pinning it keeps the screenshot generic and reproducible.
_HOSTNAME = os.environ.get("LEDMATRIX_DOCS_HOSTNAME")
if _HOSTNAME:
    import socket as _socket

    _socket.gethostname = lambda: _HOSTNAME
    _socket.getfqdn = lambda *_a: _HOSTNAME
