#!/usr/bin/env python3
"""
Race cards for every recent_races.top_finishers value.

``race["results"]`` holds the top finishers, then the favorite driver
appended when they finished outside them. The podium card drew results[:3]
and the favorite card looked only at results[3], which is right only for the
default of 3:

* below 3, the appended favorite took a podium column (P1, P2, then P10);
* above 3, a favorite in P5 or lower never got their card.

The card builder runs against a stand-in ``self``; the renderer records what
it was asked to draw.

Run: <core-venv>/bin/python plugins/f1-scoreboard/test_race_cards_follow_top_finishers.py
"""

import os
import sys
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

from manager import F1ScoreboardPlugin  # noqa: E402

FIELD = [{"position": i, "code": "D%02d" % i} for i in range(1, 21)]


class _Renderer:
    def __init__(self):
        self.podium = None
        self.favorite = None

    def render_race_result(self, race):
        # The real card draws at most the first three.
        self.podium = [r["code"] for r in race["results"]][:3]
        return "podium"

    def render_favorite_race_card(self, race, result):
        self.favorite = result["code"]
        return "favorite"


class _Plugin:
    _build_race_cards = F1ScoreboardPlugin._build_race_cards

    def __init__(self, top, favorite):
        self.config = {"recent_races": {"top_finishers": top, "show_gap_chart": False,
                                        "show_points_haul": False}}
        self.favorite_driver = favorite
        self._scroll_renderer = _Renderer()


def cards_for(top, favorite_position):
    favorite = "D%02d" % favorite_position
    results = FIELD[:top]
    if all(r["code"] != favorite for r in results):  # always_show_favorite
        results = results + [FIELD[favorite_position - 1]]
    plugin = _Plugin(top, favorite)
    plugin._build_race_cards({"race_name": "Test GP", "results": results})
    return plugin._scroll_renderer


failures = []


def check(label, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else "  -- " + detail))
    if not ok:
        failures.append(label)


r = cards_for(3, 10)
check("default: podium P1-P3, favorite card for P10",
      r.podium == ["D01", "D02", "D03"] and r.favorite == "D10", "%s / %s" % (r.podium, r.favorite))

r = cards_for(2, 10)
check("top 2: the favorite does not take a podium column",
      r.podium == ["D01", "D02"], str(r.podium))
check("top 2: the favorite gets their card", r.favorite == "D10", str(r.favorite))

r = cards_for(5, 5)
check("top 5: a favorite in P5 gets their card", r.favorite == "D05", str(r.favorite))
check("top 5: the podium card still shows three", r.podium == ["D01", "D02", "D03"], str(r.podium))

r = cards_for(5, 2)
check("a favorite on the podium gets no extra card", r.favorite is None, str(r.favorite))

print("%d failed" % len(failures))
sys.exit(1 if failures else 0)
