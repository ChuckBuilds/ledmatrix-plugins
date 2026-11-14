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

# ── Parcel: a settings save must not reset the 20-requests-an-hour deadline ──
# A failed fetch caches nothing, so a save right after one found nothing to fall
# back on and fetched again at once, inside the provider's minimum interval.
from incoming_packages_sources import MockProvider, ProviderError  # noqa: E402

PARCEL = {"enabled": True, "provider": "parcel", "parcel_api_key": "k1",  # nosec B105 - test fixture
          "update_interval": 600}


def parcel_plugin(cache=None):
    plug = IncomingPackagesPlugin("incoming-packages", dict(PARCEL), FakeDM(),
                                  cache or DictCache(), types.SimpleNamespace())
    return plug


def fail_with(plug, calls, message="Parcel rate limit"):
    def boom():
        calls.append(1)
        raise ProviderError(message)
    plug.provider.fetch = boom


def succeed_with(plug, calls):
    plug.provider.fetch = lambda: calls.append(1) or MockProvider({}, None).fetch()


# 1. rate-limited, nothing cached, then a save: no second request, error stays up
r = parcel_plugin()
c1 = []
fail_with(r, c1)
r.update()
check("(parcel) the failed first fetch shows the error", r._error == "Parcel rate limit" and c1 == [1])
r.on_config_change({**PARCEL, "rotation_interval": 9})
c2 = []
fail_with(r, c2)
r.update()
check("(parcel) a save right after a failed fetch does not fetch again", c2 == [])
shown = []
r._render_static = lambda text, *a, **k: shown.append(text)
r.display()
check("(parcel) ...and the error card stays up rather than 'Loading...'",
      shown == ["Parcel rate limit"])
check("(parcel) ...and the new setting still took effect", r.rotation_interval == 9.0)

# 2. once the interval has passed, the next update() fetches as usual
r._last_fetch -= 601
r.update()
check("(parcel) after the interval the next update() fetches", c2 == [1])

# 3. a changed key is a fix, so it retries straight away
s = parcel_plugin()
c3 = []
fail_with(s, c3, "Update Parcel key")
s.update()
s.on_config_change({**PARCEL, "parcel_api_key": "k2"})  # nosec B105 - test fixture
c4 = []
fail_with(s, c4)
s.update()
check("(parcel) a changed key retries immediately", c4 == [1])

# 4. stale cards survive the save too (cache expired, last fetch failed)
t_cache = DictCache()
t = parcel_plugin(t_cache)
c5 = []
succeed_with(t, c5)
t.update()
t_cache.store.clear()                       # the cached snapshot has expired
t._last_fetch -= 601
fail_with(t, c5)
t.update()
check("(parcel) setup: failed refresh keeps the cards, flagged stale", t._stale and len(t._cards) > 0)
t.on_config_change({**PARCEL, "rotation_interval": 9})
c6 = []
fail_with(t, c6)
t.update()
check("(parcel) a save keeps the stale cards and does not refetch",
      c6 == [] and t._stale and len(t._cards) > 0)

# 5. a save that shows the cached snapshot keeps the deadline too: if the cache
# entry is then evicted or unreadable, update() must not fetch inside the interval
u_cache = DictCache()
u = parcel_plugin(u_cache)
c9 = []
succeed_with(u, c9)
u.update()
u.on_config_change({**PARCEL, "rotation_interval": 9})
check("(parcel) setup: the save showed the cached snapshot", len(u._cards) > 0 and u._has_fetched)
u_cache.store.clear()                       # evicted / unreadable after the save
c10 = []
fail_with(u, c10)
u.update()
check("(parcel) a cache miss after a cached save does not fetch inside the interval", c10 == [])
check("(parcel) ...and the cards stay up", len(u._cards) > 0 and u._error is None)
u._last_fetch -= 601
u.update()
check("(parcel) once the interval has passed it fetches again", c10 == [1])

v_cache = DictCache()
v = parcel_plugin(v_cache)
succeed_with(v, [])
v.update()
v.on_config_change({**PARCEL, "parcel_api_key": "k2"})  # nosec B105 - test fixture
v_cache.store.clear()
c11 = []
fail_with(v, c11)
v.update()
check("(parcel) with a changed key the cached path does not hold the deadline", c11 == [1])

# 6. other providers are unchanged: a save still refreshes on the next update()
m = IncomingPackagesPlugin("incoming-packages", {"enabled": True, "provider": "aftership",
                           "api_key": "x"}, FakeDM(), DictCache(), types.SimpleNamespace())  # nosec B105
c7 = []
fail_with(m, c7, "AfterShip down")
m.update()
m.on_config_change({"enabled": True, "provider": "aftership", "api_key": "x"})  # nosec B105
c8 = []
fail_with(m, c8, "AfterShip down")
m.update()
check("(aftership) behaviour is unchanged: a save still refetches", c8 == [1])

print()
failed = [case for case, passed in results if not passed]
print(f"{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
