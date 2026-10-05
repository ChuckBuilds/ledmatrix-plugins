#!/usr/bin/env python3
"""An incoming notification must post an on-demand request to the core.

The plugin stored the message with ``cache_manager.set(..., max_age=3600)``.
The core's ``CacheManager.set`` takes ``ttl``, never ``max_age``, so that call
raised TypeError, the handler's ``except`` logged it, and the following write
of ``display_on_demand_request`` never happened: notifications waited for the
plugin's turn in rotation instead of interrupting it, as the README promises.

The fake cache binds every call against the real core signature, so a keyword
the core does not accept fails here the way it fails on a Pi.

Run with the core on PYTHONPATH:
    PYTHONPATH=/path/to/LEDMatrix python <thisfile>
"""
import inspect
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
try:
    from src.cache_manager import CacheManager
except ImportError:
    print("SKIP: LEDMatrix core not on PYTHONPATH")
    sys.exit(2)
from manager import MQTTNotificationsPlugin  # noqa: E402

CORE_SET = inspect.signature(CacheManager.set)
failures = []


def check(label, ok):
    print(("PASS " if ok else "FAIL ") + label)
    if not ok:
        failures.append(label)


class SignatureCheckedCache:
    def __init__(self):
        self.store = {}

    def set(self, *args, **kwargs):
        bound = CORE_SET.bind(self, *args, **kwargs)  # TypeError like the core
        self.store[bound.arguments["key"]] = bound.arguments["data"]


p = object.__new__(MQTTNotificationsPlugin)
p.plugin_id = "mqtt-notifications"
p.default_duration = 10
p.logger = logging.getLogger("test-mqtt")
p.cache_manager = SignatureCheckedCache()

p._trigger_on_demand_display({"type": "text", "text": "Door open", "duration": 7})

request = p.cache_manager.store.get("display_on_demand_request")
check("the on-demand request reaches the cache", isinstance(request, dict))
if isinstance(request, dict):
    check("it asks the core to start this plugin's mode",
          request.get("action") == "start"
          and request.get("plugin_id") == "mqtt-notifications"
          and request.get("mode") == "mqtt_notification")
    check("the message's own duration is forwarded", request.get("duration") == 7)
check("the message is stored for display()",
      p.cache_manager.store.get("mqtt-notifications_current_message", {}).get("text") == "Door open")


# A core with BasePlugin.request_on_demand() takes the request in-process: it
# reaches the display within a frame, and nothing goes to the mailbox (read
# once a second, and going away). Without a display in this process (above,
# no plugin_manager) or on an older core, the mailbox, as before.
from src.plugin_system.plugin_manager import PluginManager  # noqa: E402

if not hasattr(PluginManager, "set_on_demand_handler"):
    print("SKIP-PART: this core has no BasePlugin.request_on_demand()")
else:
    seen = []
    manager = PluginManager.__new__(PluginManager)
    manager.logger = logging.getLogger("test-plugin-manager")
    manager.set_on_demand_handler(lambda request: seen.append(request) or True)
    p.cache_manager = SignatureCheckedCache()
    p.plugin_manager = manager
    p._trigger_on_demand_display({"type": "text", "text": "Door open", "duration": 7})
    check("with the core API, no mailbox write",
          "display_on_demand_request" not in p.cache_manager.store)
    check("the start reaches the display",
          len(seen) == 1 and seen[0]["action"] == "start"
          and seen[0]["plugin_id"] == "mqtt-notifications"
          and seen[0]["mode"] == "mqtt_notification" and seen[0]["duration"] == 7.0
          and seen[0]["source"] == "plugin")
    check("the message is still stored for display()",
          p.cache_manager.store.get("mqtt-notifications_current_message", {}).get("text")
          == "Door open")

    # A duration the API refuses (a string from the JSON) keeps the old path,
    # which parses it as it always has.
    seen.clear()
    p.cache_manager = SignatureCheckedCache()
    p._trigger_on_demand_display({"type": "text", "text": "Hi", "duration": "15"})
    check("a string duration falls back to the mailbox",
          not seen and p.cache_manager.store.get("display_on_demand_request", {})
          .get("duration") == "15")

print("%d failed" % len(failures))
sys.exit(1 if failures else 0)
