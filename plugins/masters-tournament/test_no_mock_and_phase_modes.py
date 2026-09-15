#!/usr/bin/env python3
"""Real data or nothing, every mode registered, nothing fetched while drawing.

Pins the drift-audit findings for this plugin:

1. The hard-coded mock leaderboard ("Scottie Scheffler -12 Thru 15") was
   cached and returned as real whenever ESPN served another PGA event or the
   fetch failed. It now appears only with mock_data enabled.
2. The fallback for a failed fetch read the ttl'd leaderboard entry. Since core
   3.3.0 a stored ttl overrides the reader's max_age, so that entry read back
   empty once it expired and the fallback became the mock. The fake cache below
   implements the 3.3.0 rule so the stale path is exercised as it runs on a Pi.
3. The core reads plugin.modes once, at registration, so a phase-built list
   froze whatever phase the Pi started in. Every manifest mode is registered
   now and display() returns False for the out-of-phase ones.
4. The countdown fetched tournament meta from display(), and showed 0 days
   ("NOW") all off-season when the cached start date was last April's.
5. Headshots downloaded inside the render path on a cache miss.
6. display_modes.<key>.duration was documented but only live_action's was read.

Run: LEDMATRIX_CORE=/path/to/LEDMatrix python plugins/masters-tournament/test_no_mock_and_phase_modes.py
Exit 0 pass, 2 skip, 1 fail.
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))

_core = os.environ.get("LEDMATRIX_CORE", "")
for _candidate in (_core, str(PLUGIN_DIR.parents[2] / "LEDMatrix")):
    if _candidate and (Path(_candidate) / "src" / "plugin_system").is_dir():
        sys.path.insert(0, _candidate)
        break
else:
    print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
    sys.exit(2)

try:
    from PIL import Image
    import requests  # noqa: F401
except ImportError as exc:
    print("SKIP: %s" % exc)
    sys.exit(2)

import masters_data  # noqa: E402
import logo_loader  # noqa: E402
import manager as m  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s%s" % (name, (": " + detail) if detail else ""))
        failures.append(name)


class FakeCache:
    """CacheManager with core 3.3.0 read semantics: a stored ttl wins."""

    def __init__(self):
        self.store = {}
        self.now = time.time()

    def set(self, key, data, ttl=None):
        rec = {"data": data, "ts": self.now}
        if ttl is not None:
            rec["ttl"] = ttl
        self.store[key] = rec

    def get(self, key, max_age=300):
        rec = self.store.get(key)
        if rec is None:
            return None
        limit = rec["ttl"] if "ttl" in rec else max_age
        return rec["data"] if self.now - rec["ts"] <= limit else None


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%MZ")


def _payload(name):
    now = datetime.now(timezone.utc)
    return {"events": [{
        "name": name,
        "date": _iso(now - timedelta(days=1)),
        "endDate": _iso(now + timedelta(days=2)),
        "competitions": [{
            "status": {"type": {"state": "in"}, "period": 2},
            "competitors": [{
                "athlete": {"displayName": "Real Player", "id": "999001"},
                "status": {"position": {"displayName": "1"}, "thru": 5},
                "score": {"displayValue": "-3", "value": -3},
                "linescores": [],
            }],
        }],
    }]}


class Net:
    """Swappable stand-in for requests.get that counts calls."""

    def __init__(self):
        self.calls = 0
        self.payload = None

    def __call__(self, *args, **kwargs):
        self.calls += 1
        if self.payload is None:
            raise masters_data.requests.exceptions.ConnectionError("offline")
        return FakeResponse(self.payload)


def _names(board):
    return [p.get("player") for p in board or []]


def data_source_checks():
    print("\nmock data only when mock_data is on")
    net = Net()
    masters_data.requests.get = net

    cache = FakeCache()
    src = masters_data.MastersDataSource(cache, {"mock_data": False})
    net.payload = _payload("RBC Heritage")
    board = src.fetch_leaderboard()
    check("another PGA event yields no leaderboard, not the mock",
          board == [], "got %r" % _names(board)[:3])

    cache = FakeCache()
    src = masters_data.MastersDataSource(cache, {"mock_data": False})
    net.payload = None
    board = src.fetch_leaderboard()
    check("a failed fetch with nothing cached yields no leaderboard",
          board == [], "got %r" % _names(board)[:3])

    cache = FakeCache()
    src = masters_data.MastersDataSource(cache, {"mock_data": True})
    check("mock_data: true still serves the mock field",
          "Scottie Scheffler" in _names(src.fetch_leaderboard()))

    print("\nstale fallback returns the last real leaderboard")
    cache = FakeCache()
    src = masters_data.MastersDataSource(cache, {"mock_data": False})
    net.payload = _payload("Masters Tournament")
    first = src.fetch_leaderboard()
    check("a Masters payload parses", _names(first) == ["Real Player"],
          "got %r" % _names(first))
    # Past every ttl the first write could have used (30 s live, 3600 s when
    # no meta was cached yet) but well inside a day.
    cache.now += 4000
    net.payload = None        # ESPN hiccup
    board = src.fetch_leaderboard()
    check("an ESPN failure after the ttl lapses falls back to the real field",
          _names(board) == ["Real Player"], "got %r" % _names(board)[:3])
    cache.now += 2 * 86400
    board = src.fetch_leaderboard()
    check("the fallback copy does not live for ever",
          board == [], "got %r" % _names(board)[:3])


class FakeDisplay:
    def __init__(self, w=128, h=32):
        self.width, self.height, self.matrix = w, h, None
        self.image = Image.new("RGB", (w, h))

    def update_display(self):
        pass

    def clear(self):
        self.image = Image.new("RGB", (self.width, self.height))


def plugin_checks():
    net = Net()
    masters_data.requests.get = net
    img_net = Net()
    logo_loader.requests.get = img_net

    manifest = json.loads((PLUGIN_DIR / "manifest.json").read_text(encoding="utf-8"))
    config = {
        "enabled": True, "mock_data": False, "display_duration": 20,
        "display_modes": {"leaderboard": {"duration": 42}},
    }
    # Pin the phase to off-season whatever today's date is.
    off_season = datetime(2026, 9, 15, 16, 0, tzinfo=timezone.utc)
    real_phase = m.get_detailed_phase
    m.get_detailed_phase = lambda date=None, **kw: real_phase(date=off_season, **kw)
    try:
        plugin = m.MastersTournamentPlugin(
            "masters-tournament", config, FakeDisplay(), FakeCache(), None)

        print("\nevery manifest mode is registered")
        check("plugin.modes is the manifest's display_modes",
              list(plugin.modes) == manifest["display_modes"],
              "got %r" % list(plugin.modes))

        print("\nout-of-phase modes skip")
        plugin._tournament_meta = None
        check("masters_schedule (tournament-week only) returns False off-season",
              plugin.display(display_mode="masters_schedule") is False)
        check("masters_fun_facts draws off-season",
              plugin.display(display_mode="masters_fun_facts") is True)
    finally:
        m.get_detailed_phase = real_phase

    print("\ncountdown draws without fetching and ignores last year's date")
    calls = []
    plugin.data_source.fetch_tournament_meta = lambda: calls.append(1) or None
    seen = {}
    real_render = plugin.renderer.render_countdown

    def spy(days, hours, minutes, **kw):
        seen["days"] = days
        return real_render(days, hours, minutes, **kw)

    plugin.renderer.render_countdown = spy
    net.calls = 0
    plugin._tournament_meta = None
    plugin._display_countdown(False)
    check("no tournament-meta fetch from display()", not calls and net.calls == 0,
          "fetch_tournament_meta calls=%d, http calls=%d" % (len(calls), net.calls))
    plugin._tournament_meta = {
        "start_date": datetime.now(timezone.utc) - timedelta(days=150),
        "end_date": datetime.now(timezone.utc) - timedelta(days=147),
    }
    plugin._display_countdown(False)
    check("a past start date counts down to the next Masters, not NOW",
          seen.get("days", 0) > 0, "days=%r" % seen.get("days"))

    print("\nheadshots are not downloaded while drawing")
    img_net.calls = 0
    plugin.logo_loader.get_player_headshot(
        "no_such_player_for_test", "https://a.espncdn.com/i/headshots/golf/players/full/0.png")
    check("get_player_headshot makes no HTTP request", img_net.calls == 0,
          "http calls=%d" % img_net.calls)

    print("\nper-mode duration settings are honoured")
    plugin._current_display_mode = "masters_leaderboard"
    check("display_modes.leaderboard.duration drives the leaderboard slot",
          plugin.get_display_duration() == 42.0, "got %r" % plugin.get_display_duration())
    plugin._current_display_mode = "masters_past_champions"
    check("an unset duration uses its schema default (20)",
          plugin.get_display_duration() == 20.0, "got %r" % plugin.get_display_duration())
    plugin._current_display_mode = "masters_fun_facts"
    check("a mode without a duration setting uses display_duration",
          plugin.get_display_duration() == 20.0, "got %r" % plugin.get_display_duration())


def main():
    data_source_checks()
    plugin_checks()
    print("\n%s" % ("FAILED: %d" % len(failures) if failures else "All checks passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
