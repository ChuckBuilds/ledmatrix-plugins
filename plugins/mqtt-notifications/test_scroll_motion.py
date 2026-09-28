#!/usr/bin/env python3
"""Scrolling text moves smoothly and resumes where it left off.

* The plugin never asked for the core's fast display loop, so display() ran
  once a second and the pixels-per-second scroll advanced in 30px jumps.
  needs_high_fps now follows the scroll setting.
* The scroll clock was only reset at start-up, so the first frame after the
  screen had been away (rotation, or a new message) advanced by the whole
  time it was hidden -- a jump to an arbitrary point in the text.

Run with the core on PYTHONPATH:
    PYTHONPATH=/path/to/LEDMatrix python test_scroll_motion.py
Exit 0 pass, 1 fail, 2 skip.
"""
import logging
import os
import sys
import time
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# The plugin refuses to construct without paho; give it an inert stand-in.
_client_mod = types.ModuleType("paho.mqtt.client")


class _Client:
    def __init__(self, *a, **k):
        pass

    def __getattr__(self, name):
        return lambda *a, **k: None


_client_mod.Client = _Client
_client_mod.CallbackAPIVersion = types.SimpleNamespace(VERSION1=1)
for _name, _mod in (("paho", types.ModuleType("paho")),
                    ("paho.mqtt", types.ModuleType("paho.mqtt")),
                    ("paho.mqtt.client", _client_mod)):
    sys.modules[_name] = _mod
sys.modules["paho"].mqtt = sys.modules["paho.mqtt"]
sys.modules["paho.mqtt"].client = _client_mod

try:
    from src.plugin_system.testing.mocks import (
        MockCacheManager, MockDisplayManager, MockPluginManager)
    import manager
except ImportError as exc:
    print("SKIP: %s" % exc)
    sys.exit(2)

logging.disable(logging.CRITICAL)
failures = []


def check(label, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + label + ("" if ok or not detail else "  -- " + detail))
    if not ok:
        failures.append(label)


def plugin(scroll=True):
    dm = MockDisplayManager(128, 32)
    dm.matrix = types.SimpleNamespace(width=128, height=32)
    p = manager.MQTTNotificationsPlugin(
        "mqtt-notifications", {"enabled": True, "text": {"scroll": scroll}},
        dm, MockCacheManager(), MockPluginManager())
    p.current_message = {"content": {"text": "A notification long enough to scroll off a panel"}}
    return p


check("with scrolling on, the fast display loop is requested",
      getattr(plugin(True), "needs_high_fps", None) is True)
check("with scrolling off, it is not",
      getattr(plugin(False), "needs_high_fps", None) is False)

p = plugin(True)
p.display()
p.scroll_pos = 40.0
p.last_update_time = time.time() - 600  # the screen was away for ten minutes
p.display()
check("the first frame after ten minutes away resumes where it was",
      abs(p.scroll_pos - 40.0) < 1.0, "scroll_pos %.1f" % p.scroll_pos)

p.last_update_time = time.time() - 0.5
p.display()
check("a normal frame still advances (about scroll_speed / 2 px in 0.5 s)",
      10.0 <= p.scroll_pos - 40.0 <= 20.0, "moved %.1f" % (p.scroll_pos - 40.0))

print("%d failed" % len(failures))
sys.exit(1 if failures else 0)
