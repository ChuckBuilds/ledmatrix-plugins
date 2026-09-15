#!/usr/bin/env python3
"""The plugin leaves the shared background service alone and logs as itself.

Pins the drift-audit findings for this plugin:

1. __init__ created the process-wide background data service and never used
   it. The service is a singleton, so whichever plugin creates it first sizes
   the shared worker pool for everyone -- a side effect with no benefit here.
2. __init__ replaced BasePlugin's logger with the module logger, so log lines
   lost the plugin id.
3. Settings with no effect (win celebration, show_records, per-mode update
   intervals, background_service tuning) were declared and documented.

Run: LEDMATRIX_CORE=/path/to/LEDMatrix python plugins/cricket-scoreboard/test_no_background_service.py
Exit 0 pass, 2 skip, 1 fail.
"""

import json
import os
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))

_core = os.environ.get("LEDMATRIX_CORE", "")
for _candidate in (_core, str(PLUGIN_DIR.parents[2] / "LEDMatrix")):
    if _candidate and (Path(_candidate) / "src" / "plugin_system").is_dir():
        sys.path.insert(0, _candidate)
        break
else:
    print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
    sys.exit(2)

try:
    from PIL import Image
except ImportError as exc:
    print("SKIP: %s" % exc)
    sys.exit(2)

import src.background_data_service as bds  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s%s" % (name, (": " + detail) if detail else ""))
        failures.append(name)


class _Matrix:
    def __init__(self, w, h):
        self.width, self.height = w, h


class _Display:
    def __init__(self, w=128, h=32):
        self.matrix = _Matrix(w, h)
        self.image = Image.new("RGB", (w, h))

    def clear(self):
        self.image = Image.new("RGB", (self.matrix.width, self.matrix.height))

    def update_display(self):
        pass


class _Cache:
    def __init__(self):
        self.store = {}

    def get(self, key, max_age=None):
        return self.store.get(key)

    def set(self, key, value, ttl=None):
        self.store[key] = value


def main():
    calls = []
    real = bds.get_background_service

    def spy(*args, **kwargs):
        calls.append(kwargs)
        return real(*args, **kwargs)

    # Patch before the plugin module is imported so its import binds the spy.
    bds.get_background_service = spy
    try:
        import manager as m  # noqa: E402  # pylint: disable=import-outside-toplevel
        if getattr(m, "get_background_service", None) is real:
            m.get_background_service = spy
        plugin = m.CricketScoreboardPlugin(
            "cricket-scoreboard",
            {"enabled": True, "background_service": {"max_workers": 7}},
            _Display(), _Cache(), None)
    finally:
        bds.get_background_service = real

    print("\nshared background service")
    check("constructing the plugin does not create or resize the shared service",
          not calls, "get_background_service called with %r" % calls)

    print("\nlogger")
    check("keeps BasePlugin's per-plugin logger",
          plugin.logger is not m.logger and "cricket-scoreboard" in plugin.logger.name,
          "logger name %r" % plugin.logger.name)

    print("\ndead settings are deprecated, not removed")
    # Core's web save deep-merges over the stored section, so a key dropped
    # from the schema could never be cleared and would fail
    # additionalProperties on every load. Declared with no default so a fresh
    # config never gains them.
    schema = json.loads((PLUGIN_DIR / "config_schema.json").read_text(encoding="utf-8"))
    props = schema["properties"]
    bg = props.get("background_service", {}).get("properties", {})

    def deprecated(spec):
        # Core does not honour x-display yet, so the field still renders:
        # the title and description must tell the user it does nothing.
        return (spec.get("x-display") == "hidden" and spec.get("x-advanced") is True
                and "(deprecated)" in spec.get("title", "") and "default" not in spec
                and spec.get("description", "").startswith("Deprecated: ignored"))

    for key in ("celebration_enabled", "celebration_duration", "show_records",
                "recent_update_interval", "upcoming_update_interval"):
        check("%s declared deprecated" % key, deprecated(props.get(key, {})),
              "got %r" % props.get(key))
    for key in ("enabled", "max_workers", "max_retries", "priority"):
        check("background_service.%s declared deprecated" % key, deprecated(bg.get(key, {})),
              "got %r" % bg.get(key))
    check("request_timeout is still a live setting",
          "default" in bg.get("request_timeout", {}) and not deprecated(bg["request_timeout"]))
    import jsonschema
    stored = {"enabled": True, "celebration_enabled": False, "celebration_duration": 12,
              "show_records": True, "recent_update_interval": 600,
              "upcoming_update_interval": 900,
              "background_service": {"enabled": False, "max_workers": 4,
                                     "max_retries": 5, "priority": 1,
                                     "request_timeout": 30}}
    errors = list(jsonschema.Draft7Validator(schema).iter_errors(stored))
    check("a config still carrying the deprecated keys validates", not errors,
          "; ".join(e.message for e in errors))

    print("\n%s" % ("FAILED: %d" % len(failures) if failures else "All checks passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
