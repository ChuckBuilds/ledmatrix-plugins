#!/usr/bin/env python3
"""
Regression test: switching units does not show old-unit heights.

The daily high/low and hourly payloads were cached under a station-only key,
and a payload for today was served as-is. After switching imperial -> metric
the feet values were drawn with an "m" label until the next day's fetch (the
live reading, likewise, for up to six minutes). Payloads now carry their units
and an entry in other units is never served, not even as outage fallback.

Run: python plugins/tide-display/test_units_in_cache.py
Exit 0 pass, 1 fail, 2 skip.
"""

import logging
import sys
import types
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))

try:
    from manager import TidePlugin  # noqa: E402
except ImportError:
    for name in ("src", "src.plugin_system"):
        sys.modules.setdefault(name, types.ModuleType(name))
    mod = types.ModuleType("src.plugin_system.base_plugin")
    mod.BasePlugin = type("BasePlugin", (), {"__init__": lambda self, *a, **k: None})
    sys.modules["src.plugin_system.base_plugin"] = mod
    try:
        from manager import TidePlugin  # noqa: E402
    except ImportError as exc:
        print(f"SKIP: {exc}")
        sys.exit(2)

results = []


def check(case, passed, detail=""):
    results.append((case, passed))
    print(f"  [{'pass' if passed else 'FAIL'}] {case}" + (f"  <- {detail}" if detail and not passed else ""))


class DictCache:
    def __init__(self):
        self.store = {}

    def get(self, key, max_age=None):
        return self.store.get(key)

    def set(self, key, data, ttl=None):
        self.store[key] = data


p = object.__new__(TidePlugin)
p.logger = logging.getLogger("test-tide")
p.cache_manager = DictCache()
p.STALE_MAX_DAYS = getattr(TidePlugin, "STALE_MAX_DAYS", 3)

calls = []


def fetch(u):
    calls.append(u)
    return [{"h": 3.2 if u == "english" else 0.98}]


today = "20260928"
feet = p._load_daily("k", today, "hilo", fetch, "english")
check("a cold cache fetches", calls == ["english"] and feet[0]["h"] == 3.2)
p._load_daily("k", today, "hilo", fetch, "english")
check("the same units reuse today's entry", calls == ["english"])
metres = p._load_daily("k", today, "hilo", fetch, "metric")
check("switching units fetches again instead of serving feet as metres",
      calls == ["english", "metric"] and metres[0]["h"] == 0.98, calls)

p.cache_manager.store["k"] = {"date": today, "units": "english", "data": [{"h": 3.2}]}
failing = p._load_daily("k", today, "hilo", lambda u: None, "metric")
check("an outage never serves another unit's heights", failing is None, failing)

p.cache_manager.store["k"] = {"date": "20260927", "units": "metric", "data": [{"h": 0.9}]}
stale = p._load_daily("k", today, "hilo", lambda u: None, "metric")
check("an outage still serves yesterday's heights in the right units",
      stale == [{"h": 0.9}], stale)

print()
failed = [c for c, ok in results if not ok]
print(f"{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
