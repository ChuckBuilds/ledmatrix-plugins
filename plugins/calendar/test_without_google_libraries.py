#!/usr/bin/env python3
"""
Regression test: without the Google client libraries the plugin degrades
instead of raising.

__init__ returned early when the libraries were missing, before it set
self.service and self.events, so update(), display() and get_info() -- which
the web UI calls to list plugins -- raised AttributeError on every call.

Run: LEDMATRIX_CORE=/path/to/LEDMatrix python plugins/calendar/test_without_google_libraries.py
Exit 0 pass, 1 fail, 2 skip.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    import manager  # noqa: E402
    from src.plugin_system.testing.mocks import (  # noqa: E402
        MockCacheManager, MockDisplayManager, MockPluginManager)
except ImportError as exc:
    print(f"SKIP: {exc}")
    sys.exit(2)

results = []


def check(case, passed, detail=""):
    results.append((case, passed))
    print(f"  [{'pass' if passed else 'FAIL'}] {case}" + (f"  <- {detail}" if detail and not passed else ""))


manager.GOOGLE_AVAILABLE = False
cls = next(o for o in vars(manager).values() if isinstance(o, type)
           and o.__module__ == "manager" and hasattr(o, "display"))
plugin = cls("calendar", {"enabled": True}, MockDisplayManager(), MockCacheManager(),
             MockPluginManager())
check("the plugin disables itself", plugin.enabled is False)
try:
    plugin.update()
    info = plugin.get_info()
    ok, detail = True, ""
except AttributeError as exc:
    ok, detail = False, str(exc)
check("update() and get_info() do not raise", ok, detail)
check("get_info() reports no events and no service",
      ok and info.get("events_loaded") == 0 and info.get("service_available") is False, ok and info)

print()
failed = [c for c, ok in results if not ok]
print(f"{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
