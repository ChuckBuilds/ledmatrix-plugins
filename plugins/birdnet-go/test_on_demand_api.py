#!/usr/bin/env python3
"""A detection takes the screen through the core's in-process API when the
core has one, and through the file mailbox otherwise.

BasePlugin.request_on_demand() reaches the display within a frame; the
``display_on_demand_request`` mailbox is read once a second and is going
away. The plugin writes the mailbox on a core without the method, and when
it answers None (no display in this process, e.g. the web interface).

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
from manager import BirdNetGoPlugin, DETECTION_MODE  # noqa: E402

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
    p = object.__new__(BirdNetGoPlugin)
    p.plugin_id = "birdnet-go"
    p.logger = logging.getLogger("test-birdnet-go")
    p.cache_manager = Cache()
    p.plugin_manager = plugin_manager
    p.interrupt_duration = 12.0
    p._on_demand_until = 0.0
    return p


DETECTION = {"common_name": "American Robin"}

# No display in this process, or a core without the API: the mailbox.
p = make(None)
p._trigger_on_demand(DETECTION)
request = p.cache_manager.store.get("display_on_demand_request")
check("without a display to ask, the start goes to the mailbox",
      isinstance(request, dict) and request.get("action") == "start"
      and request.get("plugin_id") == "birdnet-go"
      and request.get("mode") == DETECTION_MODE and request.get("duration") == 12.0)
check("the interrupt window is set", p._on_demand_until > 0)

seen = []
manager = display_process_manager(seen)
if manager is None:
    print("SKIP-PART: this core has no BasePlugin.request_on_demand()")
else:
    p = make(manager)
    p._trigger_on_demand(DETECTION)
    check("with the core API, no mailbox write",
          "display_on_demand_request" not in p.cache_manager.store)
    check("the start reaches the display",
          len(seen) == 1 and seen[0]["action"] == "start"
          and seen[0]["plugin_id"] == "birdnet-go" and seen[0]["mode"] == DETECTION_MODE
          and seen[0]["duration"] == 12.0 and seen[0]["pinned"] is False
          and seen[0]["source"] == "plugin")
    check("the interrupt window is set", p._on_demand_until > 0)

    # A display whose queue is full answers None: the mailbox again.
    manager.set_on_demand_handler(lambda request: False)
    p = make(manager)
    p._trigger_on_demand(DETECTION)
    check("a refused request falls back to the mailbox",
          (p.cache_manager.store.get("display_on_demand_request") or {}).get("action")
          == "start")

print("%d failed" % len(failures))
sys.exit(1 if failures else 0)
