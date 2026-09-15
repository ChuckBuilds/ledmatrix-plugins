#!/usr/bin/env python3
"""
f1-scoreboard: round total, mode registration, rebuild cost, scroll settings.

Regressions under test:

1. ``total_rounds = len(self._calendar)``: the calendar holds one entry per
   upcoming *session* for at most calendar.max_events weekends, so the
   standings header read "Rd 17/10" and the title-battle cards 0 races left.
2. Core reads ``plugin.modes`` once. on_config_change rebuilt it from the
   enabled flags, so a mode turned on never appeared and one turned off kept
   its slot; now every manifest mode stays registered and display() declines
   the disabled ones.
3. ``_display_scroll_mode`` re-ran the full scroll build (12.46s on a Pi)
   whenever the requested mode was unprepared, and a mode with no data stays
   unprepared, so every rotation through it rebuilt everything.
4. ``scroll.scroll_speed`` / ``scroll.scroll_delay`` never reached the shared
   resolver (it does not look in a ``scroll`` block), and the frame hold it
   reports was never applied or released.
5. ``qualifying.show_gaps`` was declared and read by nothing.

Run: LEDMATRIX_CORE=/path/to/LEDMatrix python plugins/f1-scoreboard/test_rounds_modes_and_scroll.py
Exit: 0 pass, 1 fail, 2 skip (no core checkout).
"""

import json
import os
import sys
import time
from pathlib import Path

plugin_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(plugin_dir))
_core = os.environ.get("LEDMATRIX_CORE")
_candidates = [Path(_core)] if _core else []
_candidates.append(plugin_dir.parents[2] / "LEDMatrix")
for candidate in _candidates:
    if (candidate / "src" / "plugin_system" / "base_plugin.py").exists():
        sys.path.insert(0, str(candidate))
        break
else:
    print("SKIP: no LEDMatrix core checkout (set LEDMATRIX_CORE)")
    sys.exit(2)

from PIL import Image  # noqa: E402

import manager  # noqa: E402
from manager import F1ScoreboardPlugin  # noqa: E402
from scroll_display import ScrollDisplay  # noqa: E402
from f1_renderer import F1Renderer  # noqa: E402
from logo_downloader import F1LogoLoader  # noqa: E402

ALL_MODES = json.loads((plugin_dir / "manifest.json").read_text(encoding="utf-8"))["display_modes"]
failures = []


def check(label, ok):
    print(("  PASS  " if ok else "  FAIL  ") + label)
    if not ok:
        failures.append(label)


def _img(w=8):
    return Image.new("RGB", (w, 32), (10, 10, 10))


class _Logger:
    def __getattr__(self, name):
        return lambda *a, **k: None


class _DisplayManager:
    width, height = 128, 32
    matrix = None
    refresh_hz = 100.0

    def __init__(self):
        self.calls = []
        self.image = Image.new("RGB", (128, 32))

    def set_scrolling_state(self, is_scrolling, frame_hold=1):
        self.calls.append((is_scrolling, frame_hold))

    def update_display(self):
        pass


class _DataSource:
    def fetch_driver_standings(self):
        return [{"code": "NOR", "points": 300, "position": 1, "constructor_id": "mclaren"},
                {"code": "VER", "points": 250, "position": 2, "constructor_id": "red_bull"}]

    def calculate_pole_positions(self):
        return {}

    def get_championship_gaps(self, standings):
        return standings

    def apply_favorite_filter(self, entries, top_n, **kwargs):
        return entries[:top_n]

    def fetch_constructor_standings(self):
        return []

    def fetch_recent_races(self, count=3):
        return []

    def get_upcoming_race(self):
        return None

    def fetch_qualifying(self):
        return None

    def fetch_practice_results(self, name):
        return None

    def fetch_sprint_results(self):
        return None

    def get_calendar(self, **kwargs):
        # Ten upcoming session entries, as the real calendar returns.
        return [{"event_name": "GP%d" % i, "session_type": "Race"} for i in range(10)]

    def fetch_schedule(self, season=None):
        return [{"id": str(i), "sessions": []} for i in range(24)]

    def get_latest_round(self, season):
        return 17


class _Renderer:
    show_championship_leaders = False
    show_championship_battle = True
    show_constructor_battle = False
    show_driver_form = False
    show_standings_header = True
    show_circuit_info = False

    def __init__(self):
        self.headers = []
        self.battles = []

    def render_f1_separator(self):
        return _img(2)

    def render_standings_header(self, title, round_num=0, total_rounds=0, season=0):
        self.headers.append((title, round_num, total_rounds))
        return _img()

    def render_championship_battle_card(self, p1, p2, remaining_races=0, **kwargs):
        self.battles.append(remaining_races)
        return _img()

    def render_driver_standing(self, entry, **kwargs):
        return _img()

    def render_calendar_entry(self, entry):
        return _img()


class _ScrollManager:
    def __init__(self):
        self.prepared = {}

    def prepare_and_display(self, mode_key, cards, separator=None):
        self.prepared[mode_key] = list(cards)

    def is_mode_prepared(self, mode_key):
        return bool(self.prepared.get(mode_key))

    def display_frame(self, mode_key, force_clear=False):
        return False


def _plugin(renderer):
    p = F1ScoreboardPlugin.__new__(F1ScoreboardPlugin)
    p.config = {}
    p.logger = _Logger()
    p.enabled = True
    p.display_manager = _DisplayManager()
    p.cache_manager = None
    p.display_width, p.display_height = 128, 32
    p.favorite_driver = p.favorite_team = ""
    p._driver_standings, p._constructor_standings = [], []
    p._driver_battle_p1 = p._driver_battle_p2 = None
    p._constructor_battle_p1 = p._constructor_battle_p2 = None
    p._recent_races, p._upcoming_race, p._qualifying = [], None, None
    p._practice_results, p._sprint, p._calendar = {}, None, []
    p._scroll_content_sig, p._pole_positions, p._vegas_last_race_cards = None, {}, []
    p._is_live, p._live_session, p._is_race_weekend = False, "", False
    p._last_update, p._last_live_check, p._live_check_interval = 0, time.time(), 120
    p._update_interval = p._base_update_interval = 0
    p._current_display_mode = None
    p._season_rounds, p._built_modes = None, set()
    p.modes = p._build_enabled_modes()
    p._enabled_modes = p._build_enabled_modes()
    p.data_source = _DataSource()
    p._scroll_renderer = renderer
    p._scroll_manager = _ScrollManager()
    p._compute_race_gap_trend = lambda *a, **k: None
    p.logo_loader = None
    return p


print("round total")
renderer = _Renderer()
p = _plugin(renderer)
p.update()
totals = [h[2] for h in renderer.headers]
check("standings header counts the season's 24 events, not 10 calendar entries",
      bool(totals) and totals[-1] == 24)
check("battle card shows 7 races remaining after round 17", renderer.battles[-1:] == [7])

print("empty scroll mode does not rebuild everything")
calls = [0]
original = p._prepare_scroll_content


def _counting(force=False):
    calls[0] += 1
    return original(force=force)


p._prepare_scroll_content = _counting
for _ in range(3):
    p.display(display_mode="f1_recent_races")   # no recent races: empty mode
check("three rotations through an empty mode trigger no rebuild", calls[0] == 0)

print("modes toggled in config")
real_renderer, real_manager = manager.F1Renderer, manager.ScrollDisplayManager
try:
    manager.F1Renderer = lambda *a, **k: renderer
    manager.ScrollDisplayManager = lambda *a, **k: _ScrollManager()
    p._resolve_timezone = lambda *a, **k: "UTC"
    p.modes = list(ALL_MODES)                     # what core registered at load
    p.on_config_change({"calendar": {"enabled": False}})
    check("all manifest modes stay registered after disabling calendar",
          sorted(p.modes) == sorted(ALL_MODES))
    check("display('f1_calendar') declines while calendar is disabled",
          p.display(display_mode="f1_calendar") is False)
    p.on_config_change({})
    check("calendar displays again once re-enabled (no restart)",
          p.display(display_mode="f1_calendar") is True)
finally:
    manager.F1Renderer, manager.ScrollDisplayManager = real_renderer, real_manager

print("scroll block reaches the resolver; hold applied and released")
dm = _DisplayManager()
sd = ScrollDisplay(dm, {"scroll": {"scroll_speed": 1, "scroll_delay": 0.02}},
                   _Logger(), global_config={})
s = getattr(sd, "_scroll_settings", None)
check("scroll.scroll_speed/scroll_delay (1 / 0.02 = 50 px/s) is what was requested",
      s is not None and abs(s.requested_pixels_per_second - 50.0) < 0.01)
hold = s.frame_hold if s is not None else 1
sd.prepare_scroll_content([_img(400)])
sd.display_scroll_frame()
check(f"set_scrolling_state(True, frame_hold={hold}) while scrolling (hold > 1)",
      hold > 1 and (True, hold) in dm.calls)
dm.calls.clear()
sd.scroll_helper.is_scroll_complete = lambda: True
sd.is_scroll_complete()
check("released when the scroll completes", bool(dm.calls) and dm.calls[-1][0] is False)

print("qualifying.show_gaps")
os.chdir(plugin_dir)
seen = {}
r = F1Renderer(128, 32, {"qualifying": {"show_gaps": False}}, F1LogoLoader(), _Logger())
r._render_driver_row = lambda entry, **kwargs: seen.update(kwargs) or _img()
r.render_qualifying_entry({}, "Q3")
check("show_gaps=false drops the gap column (empty gap_key)", seen.get("gap_key") == "")

if failures:
    print(f"\n{len(failures)} failure(s)")
    sys.exit(1)
print("\nall passed")
sys.exit(0)
