"""
odds-ticker: a cached scoreboard holding a live game is not served for hours.

The scoreboard cache TTL came from the request date versus the UTC date: 1h
for "yesterday", 12h for "tomorrow". ESPN's day follows US time, so an evening
game sits under one of those keys and its score and clock froze. A payload with
a live or imminent game now gets the live interval.

Pure logic; needs no core checkout.
Run: python plugins/odds-ticker/test_live_scoreboard_ttl.py
"""
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

src = (Path(__file__).resolve().parent / "manager.py").read_text(encoding="utf-8")
m = re.search(r"    def _live_scoreboard_ttl.*?\n(?=    def )", src, re.S)
assert m, "_live_scoreboard_ttl not found"
ns = {"datetime": datetime, "Dict": dict, "Any": object, "Optional": __import__("typing").Optional}
import textwrap
exec(textwrap.dedent(m.group(0)), ns)
fn = ns["_live_scoreboard_ttl"]


class P:
    live_game_update_interval = 60


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
    got = fn(P(), data, now)
    if got != want:
        bad += 1
        print(f"FAIL {name}: {got} != {want}")
print("FAIL" if bad else "PASS")
sys.exit(1 if bad else 0)
