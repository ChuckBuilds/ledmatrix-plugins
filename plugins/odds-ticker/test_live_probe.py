"""
odds-ticker: a game going live between full refreshes is noticed.

With no live game known, a full refresh waits base_update_interval (an hour by
default). The check meant to cover that gap read the scoreboard_data_* cache,
but only this plugin's full refresh writes those keys, the read used the
default 5-minute max_age, and the key's date was UTC -- so it missed for most
of the hour, and a hit repeated what games_data already knew. It also ran on
the render thread (display() asks for the update interval).

Now update() asks ESPN directly, rate limited, and _has_live_games() reads
attributes only.

Run: LEDMATRIX_CORE=/path/to/LEDMatrix python plugins/odds-ticker/test_live_probe.py
Exit: 0 pass, 1 fail, 2 skip (no core checkout).
"""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

plugin_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(plugin_dir))
_core = os.environ.get("LEDMATRIX_CORE")
_candidates = [Path(_core)] if _core else []
_candidates.append(plugin_dir.parents[2] / "LEDMatrix")
core_dir = None
for candidate in _candidates:
    if (candidate / "src" / "plugin_system" / "base_plugin.py").exists():
        sys.path.insert(0, str(candidate))
        core_dir = candidate
        break
if core_dir is None:
    print("SKIP: no LEDMatrix core checkout (set LEDMATRIX_CORE)")
    sys.exit(2)
os.chdir(core_dir)  # fonts resolve as assets/fonts/..., as on a Pi

import requests  # noqa: E402

import manager  # noqa: E402

failures = []


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + ("" if ok or not detail else "  -- " + detail))
    if not ok:
        failures.append(label)


class _DisplayManager:
    refresh_hz = 100.0

    def __init__(self):
        self.width, self.height = 128, 32
        self.matrix = SimpleNamespace(width=128, height=32)
        self.image = None

    def set_scrolling_state(self, *a, **k):
        pass

    def update_display(self):
        pass

    def defer_update(self, fn, priority=0):
        pass

    def is_currently_scrolling(self):
        return False


class _Cache:
    def __init__(self):
        self.reads = []

    def get(self, key, max_age=None):
        self.reads.append(key)
        return None

    def set(self, key, value, ttl=None):
        pass

    def get_with_auto_strategy(self, key):
        return None


class _Response:
    def __init__(self, state):
        self.state = state

    def raise_for_status(self):
        pass

    def json(self):
        return {"events": [{"status": {"type": {"state": self.state}}}]}


requested = []
reply = {"state": "in", "fail": False}


def fake_get(url, **kwargs):
    requested.append(url)
    if reply["fail"]:
        raise requests.ConnectionError("offline")
    return _Response(reply["state"])


manager.requests.get = fake_get


def plugin():
    cache = _Cache()
    p = manager.OddsTickerPlugin(
        "odds-ticker",
        {"enabled": True, "update_interval": 3600,  # a legacy root key
         "leagues": {"nfl": {"enabled": True}}},
        _DisplayManager(), cache, None)
    p._perform_update = lambda *a, **k: None  # the full refresh is not under test
    return p, cache


print("the render-thread check reads attributes only")
p, cache = plugin()
p._has_live_games()
check("_has_live_games() does not read the cache", cache.reads == [], str(cache.reads))

print("update() notices a game that went live")
p, cache = plugin()
p.update()
check("update() asks the NFL scoreboard", any("/football/nfl/scoreboard" in u for u in requested),
      str(requested))
check("a game in progress is reported live", p._has_live_games() is True)
check("so the next full refresh comes at the live interval",
      p._compute_update_interval() == p.live_game_update_interval)

print("the check is rate limited")
before = len(requested)
p.update()
check("a second update() inside five minutes makes no request", len(requested) == before)

print("a failed request is not a crash and not live")
p, cache = plugin()
reply["fail"] = True
p.update()
check("an unreachable ESPN reads as no live game", p._has_live_games() is False)
reply["fail"] = False

print("update() is scheduled often enough to run the check")
check("get_update_interval() is at most 60 s despite a legacy root update_interval",
      getattr(p, "get_update_interval", lambda: None)() == 60.0)

print(f"\n{len(failures)} failed")
sys.exit(1 if failures else 0)
