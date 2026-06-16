#!/usr/bin/env python3
"""
Regression test: ledmatrix-elections applies config edits live.

Before this fix the plugin had no on_config_change override, so the base
BasePlugin only swapped self.config: the state/filter settings, the providers
and race store, and the scroll speed all kept their startup values until a
display restart. This test fails against the base behavior and passes once the
plugin re-derives state on config change.

Run with the core venv from within a LEDMatrix tree, or set LEDMATRIX_CORE:
    LEDMATRIX_CORE=/path/to/LEDMatrix .venv/bin/python \
        plugins/ledmatrix-elections/test_config_reload.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

_core = os.environ.get("LEDMATRIX_CORE")
if _core and _core not in sys.path:
    sys.path.insert(0, _core)

from manager import ElectionPlugin  # noqa: E402

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


def _make_plugin(config):
    return ElectionPlugin(
        "ledmatrix-elections",
        config,
        display_manager=object(),
        cache_manager=object(),
        plugin_manager=object(),
    )


def test_on_config_change_applies_live():
    print("[ledmatrix-elections on_config_change]")
    plugin = _make_plugin(
        {
            "state": "CA",
            "only_my_state": True,
            "update_interval": 60,
            "scroll_speed": 1.0,
        }
    )
    check(plugin.state == "CA", "initial state derived")
    providers_before = plugin.providers
    store_before = plugin.store

    # Prime runtime state so we can confirm it is reset on change.
    plugin._last_update = 999999.0

    plugin.on_config_change(
        {
            "state": "WA",
            "only_my_state": False,
            "update_interval": 30,
            "scroll_speed": 2.0,
            "test_mode": True,
        }
    )

    check(plugin.state == "WA", "state updated live")
    check(plugin.only_my_state is False, "only_my_state updated live")
    check(plugin.update_interval == 30, "update_interval updated live")
    check(plugin.test_mode is True, "test_mode updated live")
    check(plugin.scroll_speed == 2.0, "scroll_speed updated live")
    check(plugin.providers is not providers_before, "providers rebuilt for new state")
    check(plugin.store is not store_before, "race store rebuilt")
    check(plugin._last_update == 0.0, "update timer reset so it re-fetches")


if __name__ == "__main__":
    test_on_config_change_applies_live()
    print(f"\n{_passed} passed, {_failed} failed")
    sys.exit(1 if _failed else 0)
