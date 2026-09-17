#!/usr/bin/env python3
"""
Regression test: FlightAware's paid API follows flightaware.enabled, and the
legacy flat API key still works.

H5 -- the enrichment factory built the paid FlightAwareEnrichment whenever
enrichment_provider was "flightaware" and a key was saved, ignoring
flightaware.enabled. Switching "Enable paid FlightAware API calls" off kept
every tracked-flight lookup billing.

M9 -- _normalize_flightaware_config copied every nested flightaware.* value
over its flat key. The core merges schema defaults into every config, so the
nested api_key ("") always replaced a flightaware_api_key saved under the old
flat name (the README's config_secrets.json example), and FlightAware was
silently off.

Configs here are built the way the core builds them: schema defaults merged
under the user's values.

Run with the core venv, LEDMATRIX_CORE pointing at a LEDMatrix checkout:
    LEDMATRIX_CORE=/path/to/LEDMatrix .venv/bin/python \
        plugins/ledmatrix-flights/test_flightaware_gating.py
"""

import copy
import json
import logging
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

_core = os.environ.get("LEDMATRIX_CORE")
if _core and _core not in sys.path:
    sys.path.insert(0, _core)

for _stale in ("manager", "data_model", "renderer", "enrichment",
               "enrichment.flightaware"):
    sys.modules.pop(_stale, None)

try:
    from manager import FlightTrackerPlugin  # noqa: E402
    from enrichment import create_enrichment_provider  # noqa: E402
    from enrichment.flightaware import FlightAwareEnrichment  # noqa: E402
except ImportError as e:
    print(f"SKIP: plugin does not import without the core on the path ({e})")
    sys.exit(2)

logging.basicConfig(level=logging.CRITICAL)

_passed = 0
_failed = 0


def check(cond, msg):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS: {msg}")
    else:
        _failed += 1
        print(f"  FAIL: {msg}")


class _Matrix:
    width = 128
    height = 64


class _DisplayManager:
    matrix = _Matrix()


class _CacheManager:
    def __init__(self, cache_dir):
        self.cache_dir = cache_dir


def _defaults(node):
    """Schema defaults as the core's generate_default_config builds them."""
    out = {}
    for key, prop in node.get("properties", {}).items():
        if "default" in prop:
            out[key] = copy.deepcopy(prop["default"])
        elif prop.get("type") == "object" and "properties" in prop:
            out[key] = _defaults(prop)
    return out


def _merge(base, over):
    merged = copy.deepcopy(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


with open(os.path.join(HERE, "config_schema.json"), encoding="utf-8") as _f:
    SCHEMA_DEFAULTS = _defaults(json.load(_f))

BASE = {
    "data_source": "skyaware",
    "skyaware_url": "http://127.0.0.1:1/data/aircraft.json",
    "center_latitude": 27.95,
    "center_longitude": -82.45,
    "enrichment_provider": "flightaware",
}


def _config(user):
    return _merge(SCHEMA_DEFAULTS, _merge(BASE, user))


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def _plugin(user):
    return FlightTrackerPlugin(
        "ledmatrix-flights",
        _config(user),
        display_manager=_DisplayManager(),
        cache_manager=_CacheManager(tempfile.mkdtemp()),
        plugin_manager=object(),
    )


def test_disabled_means_no_paid_provider():
    print("[H5] flightaware.enabled false -> no FlightAware calls")
    p = _plugin({"flightaware": {"api_key": "KEY", "enabled": False}})
    check(not isinstance(p._enrichment, FlightAwareEnrichment),
          "key saved + provider flightaware + enabled false builds a free provider")
    check(p.flight_plan_enabled is False, "flight plans off")

    p = _plugin({"flightaware": {"api_key": "KEY", "enabled": True}})
    check(isinstance(p._enrichment, FlightAwareEnrichment),
          "enabled true + key builds FlightAwareEnrichment")

    p.on_config_change(_config({"flightaware": {"api_key": "KEY", "enabled": False}}))
    check(not isinstance(p._enrichment, FlightAwareEnrichment),
          "switching enabled off live drops the paid provider")

    direct = create_enrichment_provider(
        {"enrichment_provider": "flightaware", "flightaware_api_key": "KEY"})
    check(not isinstance(direct, FlightAwareEnrichment),
          "factory without flight_plan_enabled does not build the paid provider")


def test_legacy_flat_key_is_used():
    print("[M9] legacy flightaware_api_key works when the nested key is blank")
    p = _plugin({"flightaware_api_key": "LEGACY", "flightaware": {"enabled": True}})
    check(p.flightaware_api_key == "LEGACY", "flat key survives the default nested api_key")
    check(p.config.get("flightaware_api_key") == "LEGACY", "flat key left in place for enrichment")
    check(isinstance(p._enrichment, FlightAwareEnrichment)
          and p._enrichment.api_key == "LEGACY",
          "FlightAwareEnrichment gets the legacy key")

    p = _plugin({"flightaware_api_key": "LEGACY",
                 "flightaware": {"api_key": "NESTED", "enabled": True}})
    check(p.flightaware_api_key == "NESTED", "a set nested key wins over the flat one")

    p = _plugin({"flightaware": {"enabled": True, "daily_api_budget": 30}})
    check(p.daily_api_budget == 30, "nested tuning values are used")


def test_legacy_enable_flag_does_not_start_billing():
    print("[M9] legacy flight_plan_enabled alone does not enable paid calls")
    capture = _Capture()
    root = logging.getLogger()
    root.addHandler(capture)
    old_level = root.level
    root.setLevel(logging.WARNING)
    try:
        p = _plugin({"flightaware_api_key": "LEGACY", "flight_plan_enabled": True})
    finally:
        root.removeHandler(capture)
        root.setLevel(old_level)
    check(p.flight_plan_enabled is False, "flight_plan_enabled true with flightaware.enabled false stays off")
    check(not isinstance(p._enrichment, FlightAwareEnrichment), "no paid provider")
    check(p.config.get("flight_plan_enabled") is False, "flat key normalized to the resolved value")
    check(any("flight_plan_enabled" in m for m in capture.messages),
          "the ignored legacy flag is logged")


def main():
    test_disabled_means_no_paid_provider()
    test_legacy_flat_key_is_used()
    test_legacy_enable_flag_does_not_start_billing()
    print(f"\n{_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
