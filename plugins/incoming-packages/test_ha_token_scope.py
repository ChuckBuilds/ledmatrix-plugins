#!/usr/bin/env python3
"""
Regression test: the Home Assistant token only goes to Home Assistant.

Package images come from two places: camera snapshots, which Home Assistant
serves and which need its bearer token, and the USPS image_url sensor, which
can name any host. Every image request carried the token, so a sensor pointing
off-box was handed a long-lived Home Assistant credential.

Run: python plugins/incoming-packages/test_ha_token_scope.py
Exit 0 pass, 1 fail.
"""

import sys
import types
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))


def _stub_core():
    class BasePlugin:
        def __init__(self, *a, **k):
            pass

    for name in ("src", "src.plugin_system"):
        sys.modules.setdefault(name, types.ModuleType(name))
    mod = types.ModuleType("src.plugin_system.base_plugin")
    mod.BasePlugin = BasePlugin
    sys.modules["src.plugin_system.base_plugin"] = mod


_stub_core()
from manager import IncomingPackagesPlugin  # noqa: E402

results = []


def check(case, passed):
    results.append((case, passed))
    print(f"  [{'pass' if passed else 'FAIL'}] {case}")


p = object.__new__(IncomingPackagesPlugin)
p.provider_name = "homeassistant"
p.config = {"ha_token": "secret-token", "ha_base_url": "http://homeassistant.local:8123"}  # nosec B105 - test fixture

auth = {"Authorization": "Bearer secret-token"}
check("a Home Assistant camera URL gets the token",
      p._image_headers("http://homeassistant.local:8123/api/camera_proxy/camera.usps") == auth)
check("the host comparison ignores case",
      p._image_headers("http://HomeAssistant.local:8123/api/x") == auth)
check("an off-box image_url gets no token",
      p._image_headers("https://informeddelivery.example.com/mail.gif") == {})
check("the same host on another port gets no token",
      p._image_headers("http://homeassistant.local:9999/x.gif") == {})
check("https where Home Assistant is http gets no token",
      p._image_headers("https://homeassistant.local:8123/x.gif") == {})
p.config = {"ha_token": "secret-token", "ha_base_url": ""}  # nosec B105 - test fixture
check("with no base URL nothing gets the token", p._image_headers("http://anything/x") == {})
p.provider_name = "aftership"
check("other providers never send it", p._image_headers("http://homeassistant.local:8123/x") == {})

print()
failed = [case for case, passed in results if not passed]
print(f"{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
