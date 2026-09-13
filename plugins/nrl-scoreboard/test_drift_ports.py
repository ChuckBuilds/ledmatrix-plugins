#!/usr/bin/env python3
"""Fixes ported from sibling scoreboards, each pinned by the behaviour it fixed.

Every one of these had already been fixed in another scoreboard's copy and was
missing here (the 2026-09 drift audit). They are small and unrelated, so one
file holds them, one section per fix:

  * C5   postponed/cancelled fixtures are not "final" (Recent showed "Final 0-0")
  * logo NRL abbreviations collide (NEW, CAN): logos are per team id, and the
         old <ABBR>.png still loads until the per-team file exists
  * M7   decoded logo caches are bounded
  * M17  full-screen odds step off the top-row text; 0.0 spread is real
  * M13  "Logo Error" is drawn on the image that is displayed
  * M3   a mode retaking the panel gives its card a full dwell
  * M4   rotated-in games get odds off the display path
  * B1   a cached no-odds marker is a cache hit
  * B3   rankings+records: an unranked team shows its record
  * OVF  a config Infinity does not crash window clamping
  * M12  other_games_divisions is passed through raw; test_mode is forwarded
  * A1   Vegas rebuilds its own slate when the games change, without update()

Run: <core-venv>/bin/python plugins/nrl-scoreboard/test_drift_ports.py
"""

import logging
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

plugin_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(plugin_dir))

REPO = plugin_dir.parents[1]
CORE = None
for _c in (os.environ.get("LEDMATRIX_CORE", ""),
           str(REPO.parent / "LEDMatrix"),
           str(Path.home() / "projects" / "LEDMatrix")):
    if _c and (Path(_c) / "assets" / "fonts").is_dir():
        CORE = Path(_c)
        break
if CORE is None:
    print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
    sys.exit(2)
sys.path.insert(0, str(CORE))
logging.disable(logging.CRITICAL)

results = []


def check(case, passed, detail=""):
    results.append((case, bool(passed)))
    print("  [%s] %s%s" % ("pass" if passed else "FAIL", case,
                           "" if passed else "  <- " + str(detail)))


LOG = logging.getLogger("drift_ports")


def main():
    os.chdir(str(CORE))
    from unittest.mock import MagicMock
    from PIL import Image, ImageDraw
    import sports
    import game_renderer as gr
    import nrl_managers
    import base_odds_manager

    class Core(sports.SportsCore):
        def __init__(self, config=None, width=64, height=32):
            self.config = config or {}
            self.mode_config = {}
            self.display_width = width
            self.display_height = height
            self.logger = LOG
            self.fonts = sports.SportsCore._load_fonts(self)

        def _custom_scorebug_layout(self, game, draw):  # pragma: no cover
            raise NotImplementedError

        def _extract_game_details(self, game_event):  # pragma: no cover
            raise NotImplementedError

        def _fetch_data(self):  # pragma: no cover
            raise NotImplementedError

    # -- C5 ---------------------------------------------------------------
    print("C5: only a completed game is final")
    done = sports.SportsCore._is_completed_status
    check("STATUS_FINAL, completed -> final",
          done({"state": "post", "completed": True, "name": "STATUS_FINAL"}))
    check("STATUS_POSTPONED (post, not completed) -> not final",
          not done({"state": "post", "completed": False, "name": "STATUS_POSTPONED"}))
    check("STATUS_CANCELED even if marked completed -> not final",
          not done({"state": "post", "completed": True, "name": "STATUS_CANCELED"}))
    check("in progress -> not final",
          not done({"state": "in", "completed": False, "name": "STATUS_IN_PROGRESS"}))

    base_cls = next(c for c in vars(nrl_managers).values()
                    if isinstance(c, type) and c.__module__ == "nrl_managers"
                    and "_extract_game_details" in vars(c))
    # Abstract (no _fetch_data); only the extractor is under test.
    mgr_cls = type("Probe", (base_cls,), {})
    mgr_cls.__abstractmethods__ = frozenset()
    mgr = mgr_cls.__new__(mgr_cls)
    mgr.logger = LOG
    mgr.league_key = "3"
    status = {"type": {"state": "post", "name": "STATUS_POSTPONED",
                       "shortDetail": "Postponed", "completed": False}, "period": 0}
    common = {"id": "9", "home_abbr": "MEL", "away_abbr": "PAR", "game_time": "",
              "is_live": False, "is_upcoming": False,
              "is_final": sports.SportsCore._is_completed_status(status["type"])}
    mgr._extract_game_details_common = lambda ev: (
        dict(common), {"id": "1"}, {"id": "2"}, status, None)
    try:
        details = mgr._extract_game_details({})
    except Exception as exc:  # pragma: no cover
        details = {"period_text": "raised %r" % exc}
    period_text = (details or {}).get("period_text", "")
    check("a postponed fixture's label does not say Final (Recent admits 'final')",
          "final" not in period_text.lower() and period_text, period_text)

    # -- logo per team id -------------------------------------------------
    print("\nlogo: one file and one cache entry per team")
    warriors = sports._team_logo_filename("NEW", "4337")
    knights = sports._team_logo_filename("NEW", "4338")
    check("same abbreviation, different ids -> different files",
          warriors != knights, (warriors, knights))
    check("no id -> the legacy <ABBR>.png", sports._team_logo_filename("NEW") == "NEW.png")
    check("cache keys differ by id",
          sports._team_logo_key("NEW", "4337") != sports._team_logo_key("NEW", "4338"))

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        Image.new("RGBA", (16, 16), (255, 0, 0, 255)).save(tmp / "NEW.png")
        r = gr.GameRenderer.__new__(gr.GameRenderer)
        r.display_width, r.display_height, r.config = 128, 32, {}
        r.logger, r._logo_cache = LOG, {}
        legacy = r._load_and_resize_logo("4337", "NEW", tmp / warriors)
        check("scroll card: per-team file missing -> the legacy file still loads",
              legacy is not None)
        Image.new("RGBA", (16, 16), (0, 0, 255, 255)).save(tmp / knights)
        own = r._load_and_resize_logo("4338", "NEW", tmp / knights)
        check("scroll card: the other NEW club gets its own logo, not the cached one",
              own is not None and own is not legacy
              and own.convert("RGB").getpixel((own.width // 2, own.height // 2)) == (0, 0, 255))

        # -- M7: bounded ---------------------------------------------------
        print("\nM7: decoded logo caches are bounded")
        r._LOGO_CACHE_MAX = 3
        for i in range(6):
            Image.new("RGBA", (8, 8), (0, 255, 0, 255)).save(tmp / ("T%d_%d.png" % (i, i)))
            r._load_and_resize_logo(str(i), "T%d" % i, tmp / ("T%d_%d.png" % (i, i)))
        check("renderer cache holds at most _LOGO_CACHE_MAX", len(r._logo_cache) <= 3,
              len(r._logo_cache))
    check("sports.py cache is an LRU with a cap",
          isinstance(sports.SportsCore._LOGO_CACHE_MAX, int)
          and "OrderedDict()" in (plugin_dir / "sports.py").read_text(encoding="utf-8"))

    # -- M17 ----------------------------------------------------------------
    print("\nM17: full-screen odds keep off the top row")
    bug = Core()
    drawn = []
    bug._draw_text_with_outline = lambda d, t, xy, f, fill=None, **k: drawn.append((t, xy))
    draw = ImageDraw.Draw(Image.new("RGB", (64, 32)))
    bug._draw_dynamic_odds(draw, {"over_under": 38.5}, 64, 32)
    check("O/U alone, nothing centred: drawn on row 0",
          drawn and drawn[0][1][1] == 0, drawn)
    ou_width = draw.textlength("O/U: 38.5", font=bug.fonts.get("odds") or bug.fonts["detail"])
    drawn.clear()
    bug._draw_dynamic_odds(draw, {"over_under": 38.5}, 64, 32,
                           top_span=(ou_width - 4, ou_width + 10))
    check("O/U colliding with the top-row text: stepped down a row",
          drawn and drawn[0][1][1] > 0, drawn)
    check("and never centred through it", drawn and drawn[0][1][0] == 0, drawn)
    drawn.clear()
    bug._draw_dynamic_odds(draw, {"spread": -2.5,
                                  "home_team_odds": {"spread_odds": 0.0},
                                  "away_team_odds": {"spread_odds": 0.0}}, 64, 32)
    check("a pick'em home spread of 0.0 is not replaced by the top-level spread",
          not any("-2.5" in t for t, _ in drawn), drawn)

    # -- M13 ----------------------------------------------------------------
    print("\nM13: Logo Error is drawn on the displayed image")
    src = (plugin_dir / "sports.py").read_text(encoding="utf-8")
    check("no draw on a throwaway convert() copy",
          "ImageDraw.Draw(main_img.convert(" not in src)
    check("every Logo Error site displays the image it drew on",
          src.count("self.display_manager.image = error_img") == src.count('"Logo Error"'))

    # -- M3 -----------------------------------------------------------------
    print("\nM3: dwell resets when the mode retakes the panel")
    dwell = Core()
    dwell.last_game_switch = 1.0
    check("first frame after a gap resets the dwell", dwell._reset_dwell_on_reentry()
          and dwell.last_game_switch > 1.0)
    before = dwell.last_game_switch
    check("the next frame, moments later, does not",
          not dwell._reset_dwell_on_reentry() and dwell.last_game_switch == before)
    dwell._last_display_call_monotonic = time.monotonic() - 120
    check("a minute-long absence resets it again", dwell._reset_dwell_on_reentry())
    check("Upcoming trims to schedule_lookahead_days", "upcoming_cutoff" in src)

    # -- M4 -----------------------------------------------------------------
    print("\nM4: rotated-in games get odds")
    rot = Core()
    rot.show_odds, rot.sport, rot.league, rot.sport_key = True, "rugby-league", "3", "nrl"
    rot.odds_manager = MagicMock()
    rot.odds_manager.get_odds.return_value = {"over_under": 40.5}
    games = [{"id": "a"}, {"id": "b", "odds": {"over_under": 1}}]
    rot._attach_odds_to_rotated_games(games)
    deadline = time.time() + 3
    while "odds" not in games[0] and time.time() < deadline:
        time.sleep(0.02)
    check("the game without odds got them", games[0].get("odds") == {"over_under": 40.5})
    check("the game that had odds was not re-asked",
          rot.odds_manager.get_odds.call_count == 1, rot.odds_manager.get_odds.call_count)

    # -- B1 -----------------------------------------------------------------
    print("\nB1: a cached no-odds marker is a cache hit")
    om = base_odds_manager.BaseOddsManager.__new__(base_odds_manager.BaseOddsManager)
    om.logger, om.update_interval, om.request_timeout = LOG, 3600, 5
    om.base_url = "http://example.invalid"
    om.cache_manager = MagicMock()
    om.cache_manager.get.return_value = {"no_odds": True}
    real_get = base_odds_manager.requests.get
    base_odds_manager.requests.get = MagicMock(side_effect=AssertionError("fetched"))
    try:
        got = om.get_odds("rugby-league", "3", "123")
        fetched = base_odds_manager.requests.get.called
    finally:
        base_odds_manager.requests.get = real_get
    check("returns None", got is None, got)
    check("and does not ask ESPN again", not fetched)

    # -- B3 -----------------------------------------------------------------
    print("\nB3: rankings and records both on")
    rr = gr.GameRenderer.__new__(gr.GameRenderer)
    rr.show_ranking = rr.show_records = True
    rr._team_rankings_cache = {"MEL": 1}
    check("a ranked team shows its rank", rr._get_team_display_text("MEL", "5-1") == "#1")
    check("an unranked team shows its record", rr._get_team_display_text("PAR", "3-3") == "3-3")

    # -- OVF ----------------------------------------------------------------
    print("\nOVF: Infinity in config")
    check("_clamp_window(inf) falls back",
          sports._clamp_window(float("inf"), 7) == 7)
    ovf = Core()
    ovf.mode_config = {"other_rotation_interval_seconds": float("inf")}
    try:
        value = ovf._setting_int("other_rotation_interval_seconds", 1800, 60, 86400)
        check("_setting_int(inf) falls back", value == 1800, value)
    except OverflowError as exc:
        check("_setting_int(inf) falls back", False, exc)
    except TypeError:
        # Signature differs; the source check below still pins the catch.
        check("_setting_int catches OverflowError",
              "except (TypeError, ValueError, OverflowError)" in src)

    # -- manager.py ---------------------------------------------------------
    import manager as plugin_manager
    cls = next(o for o in vars(plugin_manager).values()
               if isinstance(o, type) and "_adapt_config_for_manager" in vars(o))

    print("\nM12 / test_mode: the adapter")

    def adapt(config):
        obj = cls.__new__(cls)
        obj.logger = LOG
        obj.config = config
        for _ in range(40):
            try:
                return obj._adapt_config_for_manager()
            except AttributeError as exc:
                name = str(exc).rsplit("'", 2)[-2] if "'" in str(exc) else ""
                if not name or hasattr(obj, name):
                    raise
                setattr(obj, name, MagicMock())
        raise RuntimeError("gave up")

    def block(adapted):
        return next(v for v in adapted.values()
                    if isinstance(v, dict) and "other_games_divisions" in v)

    try:
        got = block(adapt({"other_games_divisions": "fbs"}))["other_games_divisions"]
        check("a string is passed through, not split into letters", got == "fbs", got)
        check("and sports.py reads it as one division",
              sports.SportsCore._normalise_divisions(got) == ["fbs"])
        got = block(adapt({"other_games_divisions": None}))["other_games_divisions"]
        check("null does not raise inside the adapter", got is None, got)
        check("test_mode reaches the managers",
              block(adapt({"test_mode": True})).get("test_mode") is True)
    except Exception as exc:
        check("the adapter survives odd values", False, "%s: %s" % (type(exc).__name__, exc))

    print("\nA1: Vegas")
    plugin = cls.__new__(cls)
    plugin.logger = LOG
    slate = [{"id": "1", "home_score": "0", "away_score": "0", "status": {"state": "in"}}]
    builds = []
    store = {}

    class Scroll:
        def prepare_content(self, games, key, leagues, rankings):
            builds.append(key)
            store[key] = [Image.new("RGB", (10, 32))]
            return True

        def get_vegas_content_items_for(self, key):
            return list(store.get(key, []))

        def get_all_vegas_content_items(self):  # pragma: no cover
            raise AssertionError("read the union")

    plugin._scroll_manager = Scroll()
    plugin._collect_games_for_scroll = lambda mode_type=None, **k: ([dict(g) for g in slate], ["3"])
    plugin._get_rankings_cache = lambda: {}
    plugin._ensure_manager_updated = MagicMock(side_effect=AssertionError("update on render path"))
    first = plugin.get_vegas_content()
    check("first call builds the mixed slate", first and builds == ["mixed"], builds)
    plugin.get_vegas_content()
    check("unchanged games do not rebuild", builds == ["mixed"], builds)
    slate[0]["home_score"] = "6"
    plugin.get_vegas_content()
    check("a score change rebuilds", len(builds) == 2, builds)
    check("no update() on the render path", not plugin._ensure_manager_updated.called)

    failed = [c for c, ok in results if not ok]
    print("\n%d checks, %d failed" % (len(results), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
