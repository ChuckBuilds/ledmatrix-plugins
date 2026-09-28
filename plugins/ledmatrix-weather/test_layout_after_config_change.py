#!/usr/bin/env python3
"""A web-UI save must not blank the current, hourly and daily screens.

on_config_change invalidates the layout by setting ``_layout_cache = None``.
``_get_layout`` used to test ``hasattr(self, '_layout_cache')``, which is still
true for an attribute holding None, so it returned None; every renderer then
indexed it, raised TypeError after clearing the panel, and the three screens
stayed black until the service restarted.

Run with the core venv from a LEDMatrix checkout so manager's imports resolve:
    LEDMatrix/.venv/bin/python <thisfile>
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(__file__))
from manager import WeatherPlugin  # noqa: E402

failures = []


def check(label, ok):
    print(("PASS " if ok else "FAIL ") + label)
    if not ok:
        failures.append(label)


def _plugin(width, height):
    p = object.__new__(WeatherPlugin)
    p.display_manager = SimpleNamespace(matrix=SimpleNamespace(width=width, height=height))
    return p


p = _plugin(128, 32)
first = p._get_layout()
check("first call computes a layout", isinstance(first, dict) and "current_icon_size" in first)
check("second call returns the cached layout", p._get_layout() is first)

# What on_config_change does.
p._layout_cache = None
again = p._get_layout()
check("a None cache is recomputed, not returned", isinstance(again, dict))
check("the recomputed layout matches the original", again == first)

# A resize between saves must be picked up by the recompute.
p.display_manager.matrix.height = 64
p._layout_cache = None
tall = p._get_layout()
check("the recompute uses the current panel size",
      tall["current_icon_size"] > first["current_icon_size"])

print("%d checks, %d failed" % (5, len(failures)))
sys.exit(1 if failures else 0)
