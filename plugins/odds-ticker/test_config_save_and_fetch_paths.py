#!/usr/bin/env python3
"""
odds-ticker: live config save, render-path network, odds fetch policy, and the
drift-audit copies of fixes that never reached this plugin.

Regressions under test (one check group each):

- A failed import of an unrelated optional core module replaced ScrollHelper
  with an empty stub (one try around four imports).
- BaseOddsManager.__init__ overwrote the plugin logger with a core module
  logger, so the plugin id was lost from every line.
- ``display_manager.matrix.width`` raised when matrix is None (hardware init
  failed), so the plugin could not load.
- on_config_change re-applied speed through legacy setters that cleared the
  resolver's whole-pixel step, ignored league changes, and skipped
  BasePlugin.on_config_change (enabled went stale).
- get_display_duration() fetched games and rebuilt the strip on the render
  path whenever no strip existed.
- get_odds used a bare requests.get with a 30s timeout and no failure cooldown.
- ``if http_err.response`` is False for a 404 Response, so the 404 branch never
  ran and a missing date was logged as an error.
- Two collection stops still compared against max_games_per_league, so
  show_odds_only stopped after the display limit.
- A .bdf face never retried at its native size.
- "No odds data" is 96px and ran off a 64px panel.

Run: LEDMATRIX_CORE=/path/to/LEDMatrix python plugins/odds-ticker/test_config_save_and_fetch_paths.py
Exit: 0 pass, 1 fail, 2 skip (no core checkout).
"""

import copy
import importlib.util
import logging
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

import requests  # noqa: E402

failures = []


def check(label, ok):
    print(("  PASS  " if ok else "  FAIL  ") + label)
    if not ok:
        failures.append(label)


print("optional imports are guarded separately")
_blocked = "src.dynamic_team_resolver"
_saved = sys.modules.get(_blocked, "absent")
sys.modules[_blocked] = None  # makes `from src.dynamic_team_resolver import ...` raise ImportError
try:
    spec = importlib.util.spec_from_file_location("odds_ticker_probe", plugin_dir / "manager.py")
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    from src.common.scroll_helper import ScrollHelper as _RealScrollHelper
    check("an unrelated failed import leaves the real ScrollHelper in place",
          probe.ScrollHelper is _RealScrollHelper)
finally:
    if _saved == "absent":
        del sys.modules[_blocked]
    else:
        sys.modules[_blocked] = _saved

import manager  # noqa: E402
from manager import OddsTickerPlugin  # noqa: E402

manager.get_background_service = lambda *a, **k: None  # no worker pool in a test


class _DisplayManager:
    refresh_hz = 100.0

    def __init__(self, width=128, height=32, with_matrix=True):
        self.width, self.height = width, height
        self.matrix = SimpleNamespace(width=width, height=height) if with_matrix else None
        self.image = None
        self.calls = []

    def set_scrolling_state(self, is_scrolling, frame_hold=1):
        self.calls.append((is_scrolling, frame_hold))

    def update_display(self):
        pass

    def defer_update(self, fn, priority=0):
        pass

    def is_currently_scrolling(self):
        return False


class _Cache:
    def __init__(self, data=None):
        self.data = data or {}

    def get(self, key, max_age=None):
        return self.data.get(key)

    def set(self, key, value, ttl=None):
        pass

    def get_with_auto_strategy(self, key):
        return None


CONFIG = {
    "enabled": True,
    "display_options": {"scroll_speed": 1.0, "scroll_delay": 0.02},
    "leagues": {"nfl": {"enabled": True}},
}


def _plugin(width=128, with_matrix=True, cache=None):
    return OddsTickerPlugin("odds-ticker", copy.deepcopy(CONFIG),
                            _DisplayManager(width, 32, with_matrix),
                            cache or _Cache(), None)


print("construction")
try:
    _plugin(with_matrix=False)
    ok = True
except AttributeError:
    ok = False
check("loads when display_manager.matrix is None", ok)

p = _plugin()
check("the plugin logger survives BaseOddsManager.__init__",
      p.logger is not logging.getLogger("src.base_odds_manager"))

print("config save")
new = copy.deepcopy(CONFIG)
new["display_options"]["scroll_speed"] = 2.0          # 2 / 0.02 = 100 px/s
new["leagues"]["nba"] = {"enabled": True}
new["enabled"] = False
p.on_config_change(new)
s = p._scroll_settings
check("a save re-runs the resolver (100 px/s requested)",
      s is not None and abs(s.requested_pixels_per_second - 100.0) < 0.01)
check("the helper keeps the resolver's whole-pixel step after a save",
      getattr(p.scroll_helper, "fixed_pixels_per_frame", None) is not None)
check("a league enabled on save is fetched", "nba" in p.enabled_leagues)
check("BasePlugin.on_config_change ran (enabled follows the save)", p.enabled is False)

print("save during a fetch")
p = _plugin()
p.last_update = 0
p._create_ticker_image = lambda: None


def _fetch_while_saving():
    p.on_config_change(copy.deepcopy(CONFIG))   # a web-UI save lands mid-fetch
    return []


p._fetch_upcoming_games = _fetch_while_saving
p._perform_update()
check("a save that lands mid-fetch leaves the refresh due (last_update not stamped)",
      p.last_update == 0)
refetches = []
p._fetch_upcoming_games = lambda: refetches.append(1) or []
p._perform_update()
check("the next update fetches again, and stamps last_update",
      refetches == [1] and p.last_update > 0)

print("fonts reload on save")
p = _plugin()
new = copy.deepcopy(CONFIG)
new["customization"] = {"team_text": {"font": "5x7.bdf", "font_size": 8}}
p.on_config_change(new)
check("customization.team_text applies on save (5x7.bdf loaded)",
      str(getattr(p.team_font, "path", "")).endswith("5x7.bdf"))

print("no data")
p = _plugin()
p._pump_background = lambda *a, **k: None
placeholders = []
p._display_fallback_message = lambda: placeholders.append(1)
result = p.display()
check("display() returns False with no games, so the rotation moves on", result is False)
check("the placeholder is still drawn for callers that ignore the result", placeholders == [1])

print("render path")
p = _plugin()
fetches = []
p._fetch_upcoming_games = lambda: fetches.append(1) or []
p.total_scroll_width = 0
p.get_display_duration()
check("get_display_duration() with no strip does not fetch", not fetches)

print("odds fetch")
p = _plugin()


class _Session:
    def __init__(self):
        self.timeouts = []

    def get(self, url, timeout=None):
        self.timeouts.append(timeout)
        raise requests.exceptions.ConnectionError("ESPN unreachable")


bare = []
real_get = manager.requests.get
try:
    manager.requests.get = lambda *a, **k: bare.append(k.get("timeout")) or (_ for _ in ()).throw(
        requests.exceptions.ConnectionError("ESPN unreachable"))
    p.session = _Session()
    p.get_odds("football", "nfl", "1")
    p.get_odds("football", "nfl", "2")
finally:
    manager.requests.get = real_get
check("odds go through the identifying session, not a bare requests.get",
      len(p.session.timeouts) >= 1 and not bare)
check("a failure holds off the next game's request (one request for two games)",
      len(p.session.timeouts) + len(bare) == 1)
check("odds requests use core's 5s timeout", p.session.timeouts[:1] == [5])


class _Recorder:
    def __init__(self):
        self.records = []

    def __getattr__(self, level):
        return lambda msg, *a, **k: self.records.append((level, str(msg) % a if a else str(msg)))


print("schedule fetch")
p = _plugin()
p._attach_odds_to_candidates = lambda games, league_config: None
p.future_fetch_days = 0
recorder = _Recorder()
response = requests.Response()
response.status_code = 404
real_logger = manager.logger
try:
    manager.logger = recorder
    manager.requests.get = lambda *a, **k: (_ for _ in ()).throw(
        requests.exceptions.HTTPError("404", response=response))
    p._fetch_league_games({"sport": "football", "league": "nfl"},
                          datetime.now(timezone.utc), "nfl")
finally:
    manager.requests.get = real_get
    manager.logger = real_logger
levels = [lvl for lvl, msg in recorder.records if "on " in msg and ("404" in msg or "HTTP error" in msg)]
check("an ESPN 404 takes the 404 branch (debug), not the generic HTTP error",
      "debug" in levels and "error" not in levels)

now = datetime.now(timezone.utc)
dates = [(now - timedelta(days=1) + timedelta(days=i)).strftime("%Y%m%d") for i in range(3)]
data = {}
for league in ("eng.1", "esp.1"):
    for date in dates:
        data[f"scoreboard_data_soccer_{league}_{date}"] = {"events": [{
            "id": f"{league}-{date}",
            "date": (now + timedelta(hours=1)).isoformat(),
            "status": {"type": {"name": "STATUS_SCHEDULED", "state": "pre"}},
            "competitions": [{"competitors": [
                {"homeAway": "home", "team": {"id": "1", "abbreviation": "AAA", "name": "A"}},
                {"homeAway": "away", "team": {"id": "2", "abbreviation": "BBB", "name": "B"}},
            ]}],
        }]}
p = _plugin(cache=_Cache(data))
p._attach_odds_to_candidates = lambda games, league_config: None
p.future_fetch_days, p.max_games_per_league = 1, 1
p.show_odds_only, p.show_favorite_teams_only = True, False
games = p._fetch_league_games({"sport": "soccer", "leagues": ["eng.1", "esp.1"],
                               "favorite_teams": []}, now, "soccer")
check("show_odds_only keeps collecting to the candidate window (3), not the display limit (1)",
      len(games) == 3)

print("fonts and fallback")
p = _plugin()
font = p._load_custom_font_from_element_config({"font": "5x7.bdf", "font_size": 8})
check("5x7.bdf at size 8 loads at its native size instead of the default face",
      str(getattr(font, "path", "")).endswith("5x7.bdf"))

p = _plugin(width=64)
drawn = []
p._draw_text_with_outline = lambda draw, text, position, font, **kw: drawn.append(
    (text, position[0], draw.textlength(text, font=font)))
p._display_fallback_message()
fits = bool(drawn) and all(x >= 0 and x + w <= 64 for _, x, w in drawn)
check("the fallback message fits a 64px panel (drawn from x >= 0 to x + width <= 64)"
      + (f" [{drawn[0][0]!r} at x={drawn[0][1]}, {drawn[0][2]:.0f}px]" if drawn else ""), fits)

if failures:
    print(f"\n{len(failures)} failure(s)")
    sys.exit(1)
print("\nall passed")
sys.exit(0)
