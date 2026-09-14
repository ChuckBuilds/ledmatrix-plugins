#!/usr/bin/env python3
"""Full-screen scorebug fixes ported from sibling scoreboards.

  * Postponed / cancelled / suspended games are not "final" (they arrive from
    ESPN as state "post" with a 0-0 score and rendered as "Final 0-0").
  * The "Logo Error" fallback draws on the image that is pasted -- it drew on
    a discarded convert("RGB") copy, so a failed logo showed a black panel.
  * Odds with no favourite no longer centre the O/U on top of the centred
    status text, and step down a row when a label would still overlap it; a
    0.0 home spread is a real line, and a non-numeric top-level spread cannot
    knock the odds off the card.
  * The decoded logo cache is bounded (core #559).
  * The scroll card shows an unranked team's record when both ranking and
    records are enabled.

Run: <core-venv>/bin/python plugins/lacrosse-scoreboard/test_scorebug_drift_fixes.py
Exit 0 pass, 2 skip, anything else fail.
"""

import logging
import os
import sys
import tempfile
from collections import OrderedDict
from pathlib import Path
from unittest.mock import MagicMock

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))

_core = os.environ.get("LEDMATRIX_CORE", "")
for _candidate in (_core, str(PLUGIN_DIR.parents[2] / "LEDMatrix")):
    if _candidate and (Path(_candidate) / "src" / "common").is_dir():
        sys.path.insert(0, _candidate)
        break
else:
    print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
    sys.exit(2)

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

import sports  # noqa: E402
import lacrosse  # noqa: E402
import game_renderer  # noqa: E402

#: SportsCore leaves the data hooks abstract; the drawing code under test
#: never calls them.
_Core = type("CoreProbe", (sports.SportsCore,), {
    "_fetch_data": lambda self: None,
    "_extract_game_details": lambda self, event: None,
})

failures = []
LOG = logging.getLogger("lax_scorebug_probe")
LOG.addHandler(logging.NullHandler())
LOG.propagate = False


def check(name, cond, detail=""):
    print("  %s  %s%s" % ("PASS" if cond else "FAIL", name,
                          "" if cond else (": " + str(detail))))
    if not cond:
        failures.append(name)


def _status(state, name, completed):
    t = {"state": state, "name": name, "shortDetail": name.split("_")[-1].title()}
    if completed is not None:
        t["completed"] = completed
    return {"type": t}


def test_postponed_is_not_final():
    f = sports._is_completed_final
    check("STATUS_FINAL completed is final", f(_status("post", "STATUS_FINAL", True)))
    check("a payload without 'completed' is judged on state/name",
          f(_status("post", "STATUS_FINAL", None)))
    for name in ("STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_SUSPENDED"):
        check("%s (completed=False) is not final" % name,
              not f(_status("post", name, False)))
        check("%s is not final even without 'completed'" % name,
              not f(_status("post", name, None)))
    check("a live game is not final", not f(_status("in", "STATUS_IN_PROGRESS", False)))


class _FakeDisplay:
    def __init__(self, w, h):
        self.image = Image.new("RGB", (w, h), (0, 0, 0))
        self.updates = 0

    def update_display(self):
        self.updates += 1


def test_logo_error_is_visible():
    # LacrosseLive leaves _fetch_data abstract (the league managers supply it).
    cls = type("LogoErrorProbe", (lacrosse.LacrosseLive,),
               {"_fetch_data": lambda self: None})
    obj = cls.__new__(cls)
    obj.logger = LOG
    obj.display_width, obj.display_height = 64, 32
    obj.display_manager = _FakeDisplay(64, 32)
    obj.fonts = {"status": ImageFont.load_default()}
    obj._load_and_resize_logo = lambda *a, **k: None
    game = {"id": "1", "home_id": "1", "away_id": "2", "home_abbr": "AAA",
            "away_abbr": "BBB", "home_logo_path": Path("x.png"),
            "away_logo_path": Path("y.png")}
    try:
        obj._draw_scorebug_layout(game)
    except Exception as exc:
        check("live scorebug survives missing logos", False, exc)
        return
    lit = obj.display_manager.image.getbbox()
    check("the 'Logo Error' text reaches the panel (not a black image)",
          lit is not None, lit)


class _Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, draw, text, position, font, fill=None, **kw):
        self.calls.append((text, position))


def _odds_obj(width=64):
    obj = _Core.__new__(_Core)
    obj.logger = LOG
    obj.display_width, obj.display_height = width, 32
    font = ImageFont.load_default()
    obj.fonts = {"odds": font, "detail": font, "time": font}
    obj._get_layout_offset = lambda element, axis, default=0: 0
    obj._draw_text_with_outline = _Recorder()
    return obj


def test_odds_placement():
    img = Image.new("RGBA", (192, 48))
    draw = ImageDraw.Draw(img)

    obj = _odds_obj(192)
    obj._draw_dynamic_odds(draw, {"over_under": 12.5}, 192, 48)
    calls = obj._draw_text_with_outline.calls
    check("O/U with no favourite is drawn", len(calls) == 1, calls)
    if calls:
        check("O/U with no favourite is anchored left, not centred",
              calls[0][1][0] == 0, calls[0][1])
        check("with nothing to avoid it stays on the top row",
              calls[0][1][1] == 0, calls[0][1])

    obj = _odds_obj(64)
    status_span = obj._odds_top_row_span(draw, "Final", obj.fonts["time"])
    obj._draw_dynamic_odds(draw, {"over_under": 12.5}, 64, 32, top_span=status_span)
    calls = obj._draw_text_with_outline.calls
    check("O/U overlapping the centred status steps down a row",
          calls and calls[0][1][1] > 0, calls)

    obj = _odds_obj(192)
    far = (90, 100)
    obj._draw_dynamic_odds(draw, {"home_team_odds": {"spread_odds": -1.5},
                                  "over_under": 12.5}, 192, 48, top_span=far)
    ys = {c[1][1] for c in obj._draw_text_with_outline.calls}
    check("labels clear of the status keep the top row", ys == {0}, ys)

    obj = _odds_obj(192)
    obj._draw_dynamic_odds(draw, {"spread": -2.5, "home_team_odds": {"spread_odds": 0.0},
                                  "away_team_odds": {"spread_odds": 0.0}}, 192, 48)
    texts = [c[0] for c in obj._draw_text_with_outline.calls]
    check("a 0.0 home spread is a pick'em, not replaced by the top-level spread",
          "-2.5" not in texts, texts)

    obj = _odds_obj(192)
    obj.logger = MagicMock()
    obj._draw_dynamic_odds(draw, {"spread": "PK", "over_under": 9.5}, 192, 48)
    texts = [c[0] for c in obj._draw_text_with_outline.calls]
    check("a non-numeric top-level spread does not drop the O/U",
          "O/U: 9.5" in texts, texts)
    check("... and logs no error", not obj.logger.error.called
          and not obj.logger.exception.called)


def test_logo_cache_is_bounded():
    cap = sports.SportsCore._LOGO_CACHE_MAX
    # ignore_cleanup_errors: _load_and_resize_logo's Image.open keeps the file
    # handle until GC, and Windows refuses to delete an open file.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        tmpdir = Path(tmp)
        obj = _Core.__new__(_Core)
        obj.logger = LOG
        obj.display_width, obj.display_height = 64, 32
        obj.sport_key = "ncaam_lacrosse"
        obj._logo_cache = OrderedDict()
        obj._scorebug_centre_gap = lambda: 0
        n = cap + 10
        for i in range(n):
            abbr = "T%03d" % i
            Image.new("RGBA", (8, 8), (255, 0, 0, 255)).save(tmpdir / ("%s.png" % abbr))
        for i in range(n):
            abbr = "T%03d" % i
            obj._load_and_resize_logo(str(i), abbr, tmpdir / ("%s.png" % abbr), None)
            if i == 0:
                first = abbr
            # Keep the first logo hot so LRU (not FIFO) is what is tested.
            obj._load_and_resize_logo("0", first, tmpdir / ("%s.png" % first), None)
        check("SportsCore logo cache is capped at %d" % cap,
              len(obj._logo_cache) == cap, len(obj._logo_cache))
        check("a recently used logo survives eviction", first in obj._logo_cache)
        check("the least recently used logo was evicted", "T001" not in obj._logo_cache)

        gr = object.__new__(game_renderer.GameRenderer)
        gr.logger = LOG
        gr.display_width, gr.display_height = 64, 32
        gr._logo_cache = {}
        gr.logo_dirs = {}
        gr._logo_cache_key = lambda key: key
        gr._logo_slot_width = lambda: 32
        for i in range(gr._LOGO_CACHE_MAX + 5):
            abbr = "T%03d" % (i % n)
            path = tmpdir / ("%s.png" % abbr)
            gr._load_and_resize_logo("R%03d" % i, path, "ncaa_mens")  # pylint: disable=too-many-function-args
        check("GameRenderer logo cache is capped at %d" % gr._LOGO_CACHE_MAX,
              len(gr._logo_cache) == gr._LOGO_CACHE_MAX, len(gr._logo_cache))


def test_unranked_team_shows_record_with_both_toggles():
    gr = object.__new__(game_renderer.GameRenderer)
    gr.show_ranking = True
    gr.show_records = True
    gr._team_rankings_cache = {"DUKE": 3}
    check("ranked team shows its rank", gr._get_team_display_text("DUKE", "9-1") == "#3")  # pylint: disable=no-value-for-parameter
    check("unranked team falls back to its record",
          gr._get_team_display_text("UVA", "7-3") == "7-3",  # pylint: disable=no-value-for-parameter
          gr._get_team_display_text("UVA", "7-3"))  # pylint: disable=no-value-for-parameter
    gr.show_records = False
    check("ranking only: unranked team shows nothing",
          gr._get_team_display_text("UVA", "7-3") == "")  # pylint: disable=no-value-for-parameter


if __name__ == "__main__":
    test_postponed_is_not_final()
    test_logo_error_is_visible()
    test_odds_placement()
    test_logo_cache_is_bounded()
    test_unranked_team_shows_record_with_both_toggles()
    print("\n%d failure(s)" % len(failures))
    sys.exit(1 if failures else 0)
