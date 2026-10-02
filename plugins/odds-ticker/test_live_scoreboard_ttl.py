"""
odds-ticker: a cached scoreboard holding a live game is not served for hours.

The scoreboard cache TTL came from the request date versus the UTC date: 1h
for "yesterday", 12h for "tomorrow". ESPN's day follows US time, so an evening
game sits under one of those keys and its score and clock froze. A payload with
a live or imminent game now gets the live interval.

Run: LEDMATRIX_CORE=/path/to/LEDMatrix python plugins/odds-ticker/test_live_scoreboard_ttl.py
Exit: 0 pass, 1 fail, 2 skip (no core checkout).
"""

import os
import sys
from datetime import datetime, timedelta, timezone
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

from manager import OddsTickerPlugin  # noqa: E402

fn = OddsTickerPlugin._live_scoreboard_ttl
plugin = SimpleNamespace(live_game_update_interval=60)
now = datetime(2026, 10, 1, 1, 0, tzinfo=timezone.utc)


def ev(state, start):
    return {"status": {"type": {"state": state}}, "date": start.isoformat().replace("+00:00", "Z")}


cases = [
    ("live", {"events": [ev("post", now), ev("in", now)]}, 60),
    ("starting in 10m", {"events": [ev("pre", now + timedelta(minutes=10))]}, 60),
    ("starting in 5h", {"events": [ev("pre", now + timedelta(hours=5))]}, None),
    ("all final", {"events": [ev("post", now - timedelta(hours=3))]}, None),
    ("empty", {}, None),
]
bad = 0
for name, data, want in cases:
    got = fn(plugin, data, now)
    if got != want:
        bad += 1
        print(f"FAIL {name}: {got} != {want}")
print("FAIL" if bad else "PASS")
sys.exit(1 if bad else 0)
