#!/usr/bin/env python3
"""The sign takes and gives back the screen through the core's in-process
API when the core has one, and through the file mailbox otherwise.

BasePlugin.request_on_demand() / end_on_demand() reach the display within a
frame; the ``display_on_demand_request`` mailbox is read once a second and
is going away. The plugin writes the mailbox on a core without the methods,
and when they answer None (no display in this process, e.g. the web
interface).

Run with the core on PYTHONPATH:
    PYTHONPATH=/path/to/LEDMatrix python <thisfile>
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
try:
    from src.plugin_system.plugin_manager import PluginManager
except ImportError:
    print("SKIP: LEDMatrix core not on PYTHONPATH")
    sys.exit(2)
from manager import OnAirPlugin  # noqa: E402

failures = []


def check(label, ok):
    print(("PASS " if ok else "FAIL ") + label)
    if not ok:
        failures.append(label)


class Cache:
    def __init__(self):
        self.store = {}

    def set(self, key, data, ttl=None):
        self.store[key] = data


def display_process_manager(seen):
    """The core's PluginManager as the display wires it; None on a core
    without the in-process API."""
    if not hasattr(PluginManager, "set_on_demand_handler"):
        return None
    manager = PluginManager.__new__(PluginManager)
    manager.logger = logging.getLogger("test-plugin-manager")
    manager.set_on_demand_handler(lambda request: seen.append(request) or True)
    return manager


def make(plugin_manager):
    p = object.__new__(OnAirPlugin)
    p.plugin_id = "on-air"
    p.logger = logging.getLogger("test-on-air")
    p.cache_manager = Cache()
    p.plugin_manager = plugin_manager
    return p


def mailbox(p):
    return p.cache_manager.store.get("display_on_demand_request") or {}


# No display in this process, or a core without the API: the mailbox.
p = make(None)
p._trigger_display(True)
check("without a display to ask, ON goes to the mailbox",
      mailbox(p).get("action") == "start" and mailbox(p).get("mode") == "on_air"
      and mailbox(p).get("pinned") is True and mailbox(p).get("duration") is None)
p._trigger_display(False)
check("and OFF too", mailbox(p).get("action") == "stop"
      and mailbox(p).get("plugin_id") == "on-air")

seen = []
manager = display_process_manager(seen)
if manager is None:
    print("SKIP-PART: this core has no BasePlugin.request_on_demand()")
else:
    p = make(manager)
    p._trigger_display(True)
    p._trigger_display(False)
    check("with the core API, no mailbox write",
          "display_on_demand_request" not in p.cache_manager.store)
    check("ON pins the sign's mode, with no time limit",
          len(seen) == 2 and seen[0]["action"] == "start"
          and seen[0]["plugin_id"] == "on-air" and seen[0]["mode"] == "on_air"
          and seen[0]["pinned"] is True and seen[0]["duration"] is None
          and seen[0]["source"] == "plugin")
    check("OFF gives the screen back (the plugin's own session only)",
          len(seen) == 2 and seen[1]["action"] == "stop"
          and seen[1]["plugin_id"] == "on-air" and seen[1]["source"] == "plugin")

    # A display whose queue is full answers None: the mailbox again.
    manager.set_on_demand_handler(lambda request: False)
    p = make(manager)
    p._trigger_display(True)
    check("a refused ON falls back to the mailbox", mailbox(p).get("action") == "start")
    p._trigger_display(False)
    check("a refused OFF falls back to the mailbox", mailbox(p).get("action") == "stop")

print("%d failed" % len(failures))
sys.exit(1 if failures else 0)
