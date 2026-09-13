#!/usr/bin/env python3
"""Regression checks for four drift fixes in the switch-mode scorebug path.

  * P-C5 -- a postponed/cancelled fixture is not a result. ESPN files it under
    state "post" with completed false and a 0-0 score; the extractor called
    that is_final, and the soccer extractor labelled it "Final", which also
    satisfied Recent's appears_finished check. Recent drew "Final 0-0".
  * P-M17 -- full-screen odds. With only an over/under (no favourite) the label
    was centred on the top row, straight through the league header / "Final"
    / live clock. It now anchors left and steps down a row when it would still
    collide. A home spread of 0.0 was also treated as missing.
  * P-M7 -- the decoded logo caches were unbounded dicts.
  * P-B3 -- scroll card with show_ranking and show_records both on: an
    unranked team showed nothing instead of its record.

Stand-ins built with __new__, no display hardware, no network.

Run: <core-venv>/bin/python plugins/soccer-scoreboard/test_not_played_and_odds_placement.py
"""

import logging
import os
import re
import sys
import tempfile
from collections import OrderedDict
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))
_core = os.environ.get("LEDMATRIX_CORE")
_candidates = [Path(_core)] if _core else []
_candidates.append(plugin_dir.parents[2] / "LEDMatrix")
for candidate in _candidates:
    if (candidate / "src" / "plugin_system" / "base_plugin.py").exists():
        sys.path.insert(0, str(candidate))
        break

try:
    from PIL import Image, ImageDraw, ImageFont
    import sports  # noqa: E402
    import game_renderer  # noqa: E402
except ImportError as exc:
    print("SKIP: cannot import the plugin (%s)" % exc)
    sys.exit(2)

logging.basicConfig(level=logging.CRITICAL)
failures = []


def check(name, ok, detail=None):
    print("  %s  %s%s" % ("PASS" if ok else "FAIL", name,
                          "" if ok or detail is None else " -- %r" % (detail,)))
    if not ok:
        failures.append(name)


def _captured_logger(name):
    """A logger whose records are kept, since the code under test catches its
    own exceptions and only logs them."""
    seen = []

    class _Capture(logging.Handler):
        def emit(self, record):
            seen.append(record.getMessage())

    log = logging.getLogger(name)
    log.handlers[:] = [_Capture()]
    log.setLevel(logging.DEBUG)
    log.propagate = False
    return log, seen


def _event(state, name, completed, home_score="0", away_score="0"):
    def side(home_away, abbr, tid, score):
        return {"id": tid, "homeAway": home_away, "score": score, "records": [],
                "team": {"id": tid, "abbreviation": abbr, "displayName": abbr,
                         "logos": [{"href": "http://x/%s.png" % abbr}]}}
    return {
        "id": "401",
        "date": "2026-09-12T14:00Z",
        "competitions": [{
            "status": {"period": 2, "displayClock": "90'",
                       "type": {"state": state, "name": name,
                                "completed": completed,
                                "shortDetail": name.replace("STATUS_", "").title()}},
            "competitors": [side("home", "ARS", "359", home_score),
                            side("away", "CHE", "363", away_score)],
        }],
    }


def extractor_checks():
    print("P-C5: not-played fixtures are not finals")
    try:
        import soccer_managers
    except ImportError as exc:
        check("import soccer_managers", False, exc)
        return

    cls = soccer_managers.SoccerRecentManager
    mgr = cls.__new__(cls)
    mgr.logger, seen = _captured_logger("extract_probe")
    mgr.logo_dir = Path(tempfile.gettempdir())
    mgr.league_key = mgr.league = "eng.1"
    mgr.sport_key = "soccer_eng.1"
    mgr.config = {}
    mgr.mode_config = {}
    mgr.favorite_teams = []

    def extract(ev):
        # Fill in any other collaborator the extractor reads, on demand and
        # bounded, rather than hardcoding this lineage's attribute list.
        for _ in range(30):
            seen.clear()
            result = mgr._extract_game_details(ev)
            if result is not None:
                return result
            names = [m.group(1) for msg in seen
                     for m in [re.search(r"has no attribute '(\w+)'", msg)] if m]
            if not names or hasattr(mgr, names[0]):
                errors = [s for s in seen if "rror" in s]
                if errors:
                    print("    extractor said: %s" % errors[-1])
                return None
            setattr(mgr, names[0], None)
        return None

    done = extract(_event("post", "STATUS_FULL_TIME", True, "2", "1"))
    check("a completed full-time result is extracted", done is not None)
    if done is None:
        return
    check("a completed full-time result is final", done["is_final"] is True)
    check("... and labelled Final", done["period_text"] == "Final", done["period_text"])

    for name, label in (("STATUS_POSTPONED", "PPD"), ("STATUS_CANCELED", "CANC"),
                        ("STATUS_ABANDONED", "ABD")):
        d = extract(_event("post", name, False))
        check("%s is not final" % name, d is not None and d["is_final"] is False,
              d and d["is_final"])
        check("%s is labelled %s, not Final" % (name, label),
              d is not None and d["period_text"] == label, d and d["period_text"])
        check("%s cannot pass Recent's 'final' in period_text check" % name,
              d is not None and "final" not in d["period_text"].lower())

    d = extract(_event("post", "STATUS_FINAL", False))
    check("state post without completed is not final",
          d is not None and d["is_final"] is False)
    d = extract(_event("post", "STATUS_FINAL_PEN", True, "1", "1"))
    check("a penalty-shootout result is still final",
          d is not None and d["is_final"] is True)


class _OddsProbe:
    """Just enough of SportsCore for _draw_dynamic_odds."""
    _odds_would_hit_top_row = sports.SportsCore._odds_would_hit_top_row
    _draw_dynamic_odds = sports.SportsCore._draw_dynamic_odds

    def __init__(self, drawn):
        font = ImageFont.load_default()
        self.fonts = {"detail": font, "odds": font}
        self.logger = logging.getLogger("odds_probe")
        self._drawn = drawn

    def _odds_color(self):
        return (0, 255, 0)

    def _draw_text_with_outline(self, draw, text, xy, font, fill=None):
        self._drawn.append((text, xy))


def odds_checks():
    print("\nP-M17: full-screen odds placement")
    width = 128
    draw = ImageDraw.Draw(Image.new("RGB", (width, 32)))

    def ou_positions(odds, **kw):
        drawn = []
        _OddsProbe(drawn)._draw_dynamic_odds(draw, odds, width, 32, **kw)
        return drawn, [xy for t, xy in drawn if t.startswith("O/U")]

    drawn, ou = ou_positions({"over_under": 2.5})
    check("an O/U with no favourite is drawn", len(ou) == 1, drawn)
    check("... anchored left, not centred", bool(ou) and ou[0][0] == 0, ou)
    check("... on the top row when nothing is in the way", bool(ou) and ou[0][1] == 0, ou)

    # A centred header wide enough to reach the left-anchored label.
    _, ou = ou_positions({"over_under": 2.5}, top_span=(20, 108))
    check("it steps down a row when it would hit the centred text",
          bool(ou) and ou[0][1] > 0, ou)
    _, ou = ou_positions({"over_under": 2.5}, top_span=(60, 68))
    check("it stays on the top row when the centred text is narrow",
          bool(ou) and ou[0][1] == 0, ou)

    drawn, _ = ou_positions({
        "spread": -1.5,
        "home_team_odds": {"spread_odds": 0.0},
        "away_team_odds": {"spread_odds": None},
    })
    texts = [t for t, _ in drawn]
    check("a home spread of 0.0 is a real line, not replaced by the top-level "
          "spread", "-1.5" not in texts, texts)

    drawn, ou = ou_positions({"spread": "PK", "over_under": 2.5,
                              "home_team_odds": {}, "away_team_odds": {}})
    check("a non-numeric top-level spread does not abort the odds", bool(ou), drawn)


def cache_checks():
    print("\nP-M7: logo caches are bounded")
    probe_cls = type("CacheProbe", (sports.SportsUpcoming,), {
        "_fetch_data": lambda s, *a, **k: None,
        "_extract_game_details": lambda s, *a, **k: None,
    })
    mgr = object.__new__(probe_cls)
    mgr._logo_cache = OrderedDict()
    mgr.logger, seen = _captured_logger("cache_probe")
    mgr.display_width, mgr.display_height = 64, 32
    cap = sports.SportsCore._LOGO_CACHE_MAX
    tmp = Path(tempfile.mkdtemp())
    total = cap + 10
    # One real file per abbreviation, so every load hits the local-file path
    # and never the download branch (no network in tests).
    for i in range(total):
        Image.new("RGBA", (8, 8), (255, 0, 0, 255)).save(tmp / ("T%d.png" % i))
    for i in range(total):
        logo = mgr._load_and_resize_logo("1", "T%d" % i, tmp / ("T%d.png" % i), None)
        if logo is None:
            check("logo T%d loads" % i, False, seen[-1:] or None)
            return
        if i == cap - 1:
            mgr._load_and_resize_logo("1", "T0", tmp / "T0.png", None)  # hit T0
    check("the manager cache never exceeds its cap",
          len(mgr._logo_cache) == cap, len(mgr._logo_cache))
    check("a recently hit logo survives eviction", "T0" in mgr._logo_cache)
    check("the least recently used logo is evicted", "T1" not in mgr._logo_cache)

    gr = game_renderer.GameRenderer.__new__(game_renderer.GameRenderer)
    gr._logo_cache = {}
    gcap = game_renderer.GameRenderer._LOGO_CACHE_MAX
    for i in range(gcap + 5):
        gr._remember_logo("k%d" % i, object())
    check("the shared scroll cache never exceeds its cap",
          len(gr._logo_cache) == gcap, len(gr._logo_cache))
    check("the oldest entries are the ones evicted",
          "k0" not in gr._logo_cache and "k%d" % (gcap + 4) in gr._logo_cache)


def ranking_checks():
    print("\nP-B3: ranking + records both on")
    gr = game_renderer.GameRenderer.__new__(game_renderer.GameRenderer)
    gr.show_ranking = True
    gr.show_records = True
    gr._team_rankings_cache = {"ARS": 3}
    check("a ranked team shows its rank", gr._get_team_display_text("ARS", "5-1-0") == "#3")
    check("an unranked team falls back to its record",
          gr._get_team_display_text("CHE", "4-2-0") == "4-2-0",
          gr._get_team_display_text("CHE", "4-2-0"))
    gr.show_records = False
    check("ranking only: an unranked team shows nothing",
          gr._get_team_display_text("CHE", "4-2-0") == "")


def main():
    extractor_checks()
    odds_checks()
    cache_checks()
    ranking_checks()
    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
