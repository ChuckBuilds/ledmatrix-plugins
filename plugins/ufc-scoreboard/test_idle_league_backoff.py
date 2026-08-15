#!/usr/bin/env python3
"""
Tests that a league with nothing on stops polling on a live cadence.

Regression under test: the live gate decided its interval like this --

    has_recently_checked = self.last_update > 0 and time_since_last_update < 300
    if live_games:             interval = live_update_interval
    elif has_recently_checked: interval = no_data_interval
    else:                      interval = live_update_interval

Once 300s had elapsed, has_recently_checked became False, the interval fell
back to live_update_interval, and it fetched. no_data_interval could therefore
never delay anything past 300s whatever it was set to -- the setting was
inert. Measured on a live rig in mid-August: NHLLiveManager fetched 0 games 22
times in 2 hours, every ~5.5 minutes, around the clock, for a league whose
season had not started. Roughly 264 wasted requests a day, per league.

The interval now comes from an explicit streak of empty looks, which escalates
and is capped, and which any live game resets.

The methods are exercised against a stand-in ``self``, so the test needs no
display hardware, no network and no cache.

Run: <core-venv>/bin/python plugins/ufc-scoreboard/test_idle_league_backoff.py
"""

import ast
import sys
from pathlib import Path

plugin_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(plugin_dir))
for candidate in (Path("/home/rackpi/projects/LEDMatrix"),
                  plugin_dir.parents[2] / "LEDMatrix"):
    if (candidate / "src" / "plugin_system" / "base_plugin.py").exists():
        sys.path.insert(0, str(candidate))
        break

import sports  # noqa: E402

failures = []


def check(label, ok):
    print(("  PASS  " if ok else "  FAIL  ") + label)
    if not ok:
        failures.append(label)


class _Logger:
    def info(self, *a, **k):
        pass


class _Live:
    _idle_live_interval = sports.SportsLive._idle_live_interval
    _note_live_fetch = sports.SportsLive._note_live_fetch

    def __init__(self, base=300, ceiling=900):
        self.no_data_interval = base
        self.live_idle_max_interval = ceiling
        self._empty_live_streak = 0
        self.logger = _Logger()


def main():
    print("the wait grows the longer nothing is found")
    live = _Live()
    check("first look uses the base interval",
          live._idle_live_interval() == 300)

    for _ in range(sports._IDLE_SHORT_STREAK):
        live._note_live_fetch(False)
    check("after a short streak it is longer (%ds)" % live._idle_live_interval(),
          live._idle_live_interval() > 300)

    for _ in range(sports._IDLE_LONG_STREAK):
        live._note_live_fetch(False)
    long_wait = live._idle_live_interval()
    check("after a long streak it is longer still (%ds)" % long_wait,
          long_wait >= live._idle_live_interval())
    check("and never exceeds the ceiling", long_wait <= 900)

    for _ in range(500):
        live._note_live_fetch(False)
    check("a very long streak stays at the ceiling, not beyond",
          live._idle_live_interval() == 900)

    print("\na live game resets it immediately")
    live._note_live_fetch(True)
    check("the streak is cleared", live._empty_live_streak == 0)
    check("and the base interval is back",
          live._idle_live_interval() == 300)

    print("\nthe saving is real, and bounded")
    idle = _Live()
    for _ in range(500):
        idle._note_live_fetch(False)
    per_day = 86400 / idle._idle_live_interval()
    check("an out-of-season league polls far less (%d/day vs 288)" % per_day,
          per_day < 288 / 2)
    check("...but still often enough to notice a season starting (<= 1h)",
          idle._idle_live_interval() <= 3600)

    print("\nthe ceiling is configurable")
    tight = _Live(ceiling=300)
    for _ in range(500):
        tight._note_live_fetch(False)
    check("a lower ceiling is honoured", tight._idle_live_interval() == 300)
    loose = _Live(ceiling=3600)
    for _ in range(500):
        loose._note_live_fetch(False)
    check("a higher ceiling is honoured", loose._idle_live_interval() == 1800)

    print("\nintervals from config are clamped, never trusted raw")
    check("a sane value is used", sports._clamp_seconds(120, 300) == 120)
    check("absent falls back", sports._clamp_seconds(None, 300) == 300)
    check("nonsense falls back", sports._clamp_seconds("soon", 300) == 300)
    check("zero is clamped up", sports._clamp_seconds(0, 300) >= 5)
    check("a week is clamped down", sports._clamp_seconds(604800, 300) <= 86400)

    print("\nthe old recency-based logic is gone")
    src = (plugin_dir / "sports.py").read_text(encoding="utf-8")
    check("has_recently_checked no longer decides the interval",
          "has_recently_checked" not in src)

    tree = ast.parse(src)
    live_cls = next(c for c in ast.walk(tree)
                    if isinstance(c, ast.ClassDef) and c.name == "SportsLive")
    upd = next(m for m in live_cls.body
               if isinstance(m, ast.FunctionDef) and m.name == "update")
    idle_calls = [n for n in ast.walk(upd) if isinstance(n, ast.Call)
                  and getattr(n.func, "attr", None) == "_idle_live_interval"]
    note_calls = [n for n in ast.walk(upd) if isinstance(n, ast.Call)
                  and getattr(n.func, "attr", None) == "_note_live_fetch"]
    check("update() takes its idle interval from the back-off", len(idle_calls) == 1)
    check("update() records each look's outcome", len(note_calls) == 1)

    print("\n%s" % ("FAILED: %d" % len(failures) if failures
                    else "All checks passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
