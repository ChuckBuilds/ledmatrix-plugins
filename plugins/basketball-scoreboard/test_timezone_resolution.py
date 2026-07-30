#!/usr/bin/env python3
"""
Tests for basketball_timezone.resolve_timezone_name -- the resolution order that
decides which zone game start times are rendered in.

Regression under test: the plugin used to read the global timezone only from
``cache_manager.config_manager``. On cores that hang ``config_manager`` off the
plugin manager instead, that lookup found nothing and every start time was
drawn in UTC, while plugins that check ``plugin_manager`` first (clock-simple,
geochron) showed the correct local time on the same device.

Run: <core-venv>/bin/python plugins/basketball-scoreboard/test_timezone_resolution.py
"""

import sys
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

import basketball_timezone  # noqa: E402
from basketball_timezone import resolve_timezone, resolve_timezone_name  # noqa: E402


class _ConfigManager:
    """Core ConfigManager stand-in exposing get_timezone()."""

    def __init__(self, timezone=None):
        self._timezone = timezone

    def get_timezone(self):
        return self._timezone


class _LegacyConfigManager:
    """Older core: no get_timezone(), only load_config()."""

    def __init__(self, timezone=None):
        self._timezone = timezone

    def load_config(self):
        return {"timezone": self._timezone}


class _CountingConfigManager:
    """Records how many times the core was asked for the timezone."""

    def __init__(self, timezone=None):
        self._timezone = timezone
        self.calls = 0

    def get_timezone(self):
        self.calls += 1
        return self._timezone


class _BrokenConfigManager:
    """Core whose get_timezone() blows up -- must not take the plugin down."""

    def get_timezone(self):
        raise RuntimeError("config not loaded")


class _Holder:
    """Stands in for a plugin_manager / cache_manager."""

    def __init__(self, config_manager=None):
        if config_manager is not None:
            self.config_manager = config_manager


# Kept so tests that stub system-zone detection can restore it, and so the
# results don't depend on the machine the suite runs on.
_real_system_timezone_name = basketball_timezone.system_timezone_name


def test_plugin_config_override_wins():
    name = resolve_timezone_name(
        config={"timezone": "America/Denver"},
        plugin_manager=_Holder(_ConfigManager("America/New_York")),
        cache_manager=_Holder(_ConfigManager("Europe/London")),
    )
    assert name == "America/Denver", name
    print("✓ explicit plugin-level timezone wins")


def test_lower_priority_sources_are_not_evaluated():
    """_get_timezone() runs per event; once a candidate resolves, the
    remaining sources must not be touched."""
    plugin_cm = _CountingConfigManager("America/New_York")
    cache_cm = _CountingConfigManager("Europe/London")
    system_calls = []

    basketball_timezone.system_timezone_name = lambda: system_calls.append(1) or None
    try:
        name = resolve_timezone_name(
            config={"timezone": "America/Chicago"},
            plugin_manager=_Holder(plugin_cm),
            cache_manager=_Holder(cache_cm),
        )
    finally:
        basketball_timezone.system_timezone_name = _real_system_timezone_name

    assert name == "America/Chicago", name
    assert plugin_cm.calls == 0, plugin_cm.calls
    assert cache_cm.calls == 0, cache_cm.calls
    assert system_calls == [], system_calls
    print("✓ resolution stops at the first valid source")


def test_plugin_manager_config_manager_is_consulted():
    """The regression: cache_manager has no config_manager at all."""
    name = resolve_timezone_name(
        config={},
        plugin_manager=_Holder(_ConfigManager("America/Chicago")),
        cache_manager=_Holder(),
    )
    assert name == "America/Chicago", name
    print("✓ global timezone read from plugin_manager.config_manager")


def test_cache_manager_config_manager_fallback():
    name = resolve_timezone_name(
        config={},
        plugin_manager=_Holder(),
        cache_manager=_Holder(_ConfigManager("America/Chicago")),
    )
    assert name == "America/Chicago", name
    print("✓ global timezone read from cache_manager.config_manager")


def test_legacy_load_config_fallback():
    name = resolve_timezone_name(
        config={},
        plugin_manager=_Holder(_LegacyConfigManager("America/Chicago")),
        cache_manager=_Holder(),
    )
    assert name == "America/Chicago", name
    print("✓ global timezone read from legacy load_config()")


def test_raising_config_manager_falls_through():
    name = resolve_timezone_name(
        config={},
        plugin_manager=_Holder(_BrokenConfigManager()),
        cache_manager=_Holder(_ConfigManager("America/Chicago")),
    )
    assert name == "America/Chicago", name
    print("✓ a raising get_timezone() falls through instead of propagating")


def test_blank_and_invalid_values_are_skipped():
    name = resolve_timezone_name(
        config={"timezone": "   "},
        plugin_manager=_Holder(_ConfigManager("Not/AZone")),
        cache_manager=_Holder(_ConfigManager("America/Chicago")),
    )
    assert name == "America/Chicago", name
    print("✓ blank and invalid timezone values are skipped")


def test_system_timezone_backstop():
    basketball_timezone.system_timezone_name = lambda: "America/Chicago"
    try:
        name = resolve_timezone_name(config={}, plugin_manager=_Holder(), cache_manager=_Holder())
    finally:
        basketball_timezone.system_timezone_name = _real_system_timezone_name
    assert name == "America/Chicago", name
    print("✓ system timezone used when no config_manager is reachable")


def test_utc_last_resort():
    basketball_timezone.system_timezone_name = lambda: None
    try:
        name = resolve_timezone_name(config={}, plugin_manager=None, cache_manager=None)
    finally:
        basketball_timezone.system_timezone_name = _real_system_timezone_name
    assert name == "UTC", name
    print("✓ falls back to UTC when every source is unavailable")


def test_resolve_timezone_returns_tzinfo_and_converts():
    from datetime import datetime

    import pytz

    tz = resolve_timezone(config={"timezone": "America/Chicago"})
    # 2026-07-28 23:45Z is a 6:45pm CDT start -- the symptom this fixes:
    # a Central-time event rendering as 11:45PM.
    utc_start = datetime(2026, 7, 28, 23, 45, tzinfo=pytz.UTC)
    local = utc_start.astimezone(tz)
    assert local.strftime("%I:%M%p").lstrip("0") == "6:45PM", local
    print("✓ resolve_timezone() converts a UTC start time to local")


def test_system_timezone_name_is_a_string_or_none():
    value = _real_system_timezone_name()
    assert value is None or isinstance(value, str), value
    print(f"✓ system_timezone_name() -> {value!r}")


def main():
    tests = [
        test_plugin_config_override_wins,
        test_lower_priority_sources_are_not_evaluated,
        test_plugin_manager_config_manager_is_consulted,
        test_cache_manager_config_manager_fallback,
        test_legacy_load_config_fallback,
        test_raising_config_manager_falls_through,
        test_blank_and_invalid_values_are_skipped,
        test_system_timezone_backstop,
        test_utc_last_resort,
        test_resolve_timezone_returns_tzinfo_and_converts,
        test_system_timezone_name_is_a_string_or_none,
    ]
    for test in tests:
        test()
    print(f"\nAll {len(tests)} timezone resolution tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
