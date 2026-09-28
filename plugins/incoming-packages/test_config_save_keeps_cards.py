#!/usr/bin/env python3
"""
Regression test: saving settings in the web UI must not blank the panel.

on_config_change re-runs __init__, which leaves the plugin "never fetched", and
display() draws "Loading..." until update() runs. The core schedules that
update() one update_interval after the last one (600 s by default), so every
save showed "Loading..." for up to ten minutes. The cached snapshot is now
reused, with no network on the web thread.

Run: python plugins/incoming-packages/test_config_save_keeps_cards.py
Exit 0 pass, 1 fail.
"""

import logging
import sys
import types
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))

from PIL import Image  # noqa: E402


def _stub_core():
    """Minimal BasePlugin mirroring the core's constructor."""
    class BasePlugin:
        def __init__(self, plugin_id, config, display_manager, cache_manager, plugin_manager):
            self.plugin_id = plugin_id
            self.config = config or {}
            self.display_manager = display_manager
            self.cache_manager = cache_manager
            self.plugin_manager = plugin_manager
            self.logger = logging.getLogger(f"test.{plugin_id}")
            self.enabled = self.config.get("enabled", True)

        def on_config_change(self, new_config):
            self.config = new_config or {}
            self.enabled = self.config.get("enabled", self.enabled)

        def validate_config(self):
            return True

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


class FakeDM:
    def __init__(self, w=128, h=32):
        self.width, self.height = w, h
        self.image = None

    def clear(self):
        self.image = Image.new("RGB", (self.width, self.height))

    def update_display(self):
        pass


class DictCache:
    def __init__(self):
        self.store = {}

    def get(self, key, max_age=300):
        return self.store.get(key)

    def set(self, key, data, ttl=None):
        self.store[key] = data


def counting(plugin, calls):
    real = plugin.provider.fetch
    plugin.provider.fetch = lambda: calls.append(1) or real()


config = {"enabled": True, "provider": "mock", "rotation_interval": 6}
cache = DictCache()
p = IncomingPackagesPlugin("incoming-packages", dict(config), FakeDM(), cache,
                           types.SimpleNamespace())
p.update()
cards_before = len(p._cards)
check("the mock provider yields cards", cards_before > 0)

drawn = []
p._render_static = lambda text, *a, **k: drawn.append(text)
p.on_config_change({**config, "rotation_interval": 9})
calls = []
counting(p, calls)
p._render_static = lambda text, *a, **k: drawn.append(text)
p.display()
check("the panel does not fall back to 'Loading...' after a save", "Loading..." not in drawn)
check("the cached cards are shown straight away", len(p._cards) == cards_before)
check("the save itself fetched nothing", calls == [])
check("the new setting took effect", p.rotation_interval == 9.0)

p.update()
check("the next update() still refreshes", calls == [] and p._last_fetch > 0)

# With nothing cached there is nothing to show: "Loading..." is right.
q = IncomingPackagesPlugin("incoming-packages", dict(config), FakeDM(), DictCache(),
                           types.SimpleNamespace())
q.on_config_change(dict(config))
shown = []
q._render_static = lambda text, *a, **k: shown.append(text)
q.display()
check("with an empty cache it still says 'Loading...'", shown == ["Loading..."])

print()
failed = [case for case, passed in results if not passed]
print(f"{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
