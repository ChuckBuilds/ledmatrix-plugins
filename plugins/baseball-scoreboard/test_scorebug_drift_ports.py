#!/usr/bin/env python3
"""Full-screen scorebug fixes ported from sibling scoreboards.

Pins four behaviours of sports.py that the scroll card or football already had:

  * M13 -- "Logo Error" is drawn onto the image that is shown. The old code
    drew on one convert("RGB") copy and displayed a second, fresh one, so a
    missing logo put a black panel up instead of the message.
  * M17 -- full-screen odds never overprint the centred top-row text
    ("Next Game", "Final"). An O/U with no favoured side was centred at y=0,
    straight through it. It now anchors left and steps down a row when it
    would still collide. A home spread of 0.0 is a real line, not "missing",
    and a non-numeric top-level spread no longer raises when negated.
  * M1 -- the full-screen upcoming date/time follow scroll_card.switch_show_date
    and switch_show_time, not the scroll card's show_date/show_time.
  * M18 -- layout offsets saved under the schema's names ("status", "record")
    reach the draw code, which asks for "status_text" and "records".

Run: <core-venv>/bin/python plugins/baseball-scoreboard/test_scorebug_drift_ports.py
"""

import logging
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

REPO = Path(__file__).resolve().parents[2]
CORE = None
for _c in (os.environ.get("LEDMATRIX_CORE", ""),
           str(REPO.parent / "LEDMatrix"),
           str(Path.home() / "projects" / "LEDMatrix")):
    if _c and (Path(_c) / "src" / "common" / "sports_shared.py").is_file():
        CORE = Path(_c)
        break
if CORE is None:
    print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
    sys.exit(2)
sys.path.insert(0, str(CORE))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

import sports  # noqa: E402

failures = []


def check(name, ok, detail=None):
    if ok:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s%s" % (name, " -- %r" % (detail,) if detail is not None else ""))
        failures.append(name)


def _probe(cls, width=64, height=32, config=None):
    stubs = dict((name, lambda self, *a, **k: None)
                 for name in getattr(cls, "__abstractmethods__", ()))
    probe_cls = type("Probe" + cls.__name__, (cls,), stubs)
    obj = probe_cls.__new__(probe_cls)
    obj.logger = MagicMock(spec=logging.Logger)
    obj.config = config or {}
    obj.display_width = width
    obj.display_height = height
    font = ImageFont.load_default()
    obj.fonts = {k: font for k in ("odds", "detail", "status", "time", "score", "team", "rank")}
    return obj


def test_logo_error_is_visible():
    print("M13: a failed logo shows 'Logo Error', not a black panel")
    for cls in (sports.SportsUpcoming, sports.SportsRecent):
        obj = _probe(cls)
        obj.display_manager = MagicMock()
        obj.display_manager.matrix = None
        obj._load_and_resize_logo = lambda *a, **k: None

        def fake_text(draw, text, position, font, fill=None, outline_color=(0, 0, 0)):
            # Stand-in for the real outlined text: a solid block is enough to
            # tell whether the draw landed on the image that is displayed.
            draw.rectangle((position[0], position[1], position[0] + 10,
                            position[1] + 5), fill=(255, 255, 255))
        obj._draw_text_with_outline = fake_text
        game = {"id": "g", "home_id": "1", "away_id": "2", "home_abbr": "AAA",
                "away_abbr": "BBB", "home_logo_path": Path("x.png"),
                "away_logo_path": Path("y.png")}
        obj._draw_scorebug_layout(game, force_clear=False)
        shown = obj.display_manager.image
        lit = isinstance(shown, Image.Image) and shown.getbbox() is not None
        check("%s: the displayed image carries the error text" % cls.__name__,
              lit, shown)


def _capture_odds(width, odds, top_span):
    obj = _probe(sports.SportsUpcoming, width=width)
    drawn = []
    obj._draw_text_with_outline = (
        lambda draw, text, pos, font, fill=None, outline_color=(0, 0, 0):
        drawn.append((text, pos)))
    draw = ImageDraw.Draw(Image.new("RGB", (width, 32)))
    obj._draw_dynamic_odds(draw, odds, width, 32, top_span=top_span)
    return obj, drawn, draw


def test_odds_stay_off_the_top_row_text():
    print("\nM17: full-screen odds and the centred top-row text")
    ou_only = {"over_under": 8.5, "home_team_odds": {}, "away_team_odds": {}}
    font = ImageFont.load_default()

    # A wide panel: nothing to collide with, so the O/U sits on the top row --
    # but at the left edge, not centred.
    obj, drawn, draw = _capture_odds(256, ou_only, top_span=(110, 146))
    check("O/U with no favourite is drawn", len(drawn) == 1, drawn)
    if drawn:
        (_text, (x, y)), = drawn
        check("O/U with no favourite anchors left instead of centring",
              x == 0, x)
        check("O/U stays on the top row when it clears the header", y == 0, y)

    # A narrow panel where "Next Game" spans most of the row.
    header = "Next Game"
    tmp = ImageDraw.Draw(Image.new("RGB", (64, 32)))
    w = tmp.textlength(header, font=font)
    span = (int((64 - w) // 2), int((64 - w) // 2 + w))
    obj, drawn, draw = _capture_odds(64, ou_only, top_span=span)
    if drawn:
        (_text, (x, y)), = drawn
        ou_w = draw.textlength("O/U: 8.5", font=font)
        text_bottom = draw.textbbox((0, 0), header, font=font)[3]
        overlaps_x = x < span[1] + 1 and x + ou_w > span[0] - 1
        check("colliding O/U steps below the header row",
              not overlaps_x or y >= text_bottom, (x, y, span))
    else:
        check("colliding O/U is still drawn", False, drawn)

    # Home spread 0.0 is a pick'em line and must not be replaced.
    obj, drawn, _ = _capture_odds(256, {
        "spread": -1.5,
        "home_team_odds": {"spread_odds": 0.0},
        "away_team_odds": {},
    }, top_span=None)
    texts = [t for t, _ in drawn]
    check("a home spread of 0.0 is not overwritten by the top-level spread",
          "-1.5" not in texts, texts)

    # A non-numeric top-level spread must not raise while negating it.
    obj, drawn, _ = _capture_odds(256, {
        "spread": "PK", "over_under": 7.0,
        "home_team_odds": {}, "away_team_odds": {},
    }, top_span=None)
    check("a non-numeric top-level spread does not raise",
          not obj.logger.error.called, obj.logger.error.call_args)
    check("the O/U still draws beside a non-numeric spread",
          any(t.startswith("O/U") for t, _ in drawn), drawn)


def test_switch_show_date_time():
    print("\nM1: the full-screen upcoming date/time use the switch_* toggles")
    obj = _probe(sports.SportsUpcoming)
    obj._format_game_date = lambda date, game=None: "D:" + date
    obj._format_game_time = lambda t: "T:" + t

    obj.config = {"scroll_card": {"show_date": False, "show_time": False}}
    date_text, time_text = obj._upcoming_date_and_time_text("9/19", "7:05PM")
    check("scroll-card show_date/show_time no longer blank the scorebug",
          (date_text, time_text) == ("D:9/19", "T:7:05PM"), (date_text, time_text))

    obj.config = {"scroll_card": {"switch_show_date": False, "switch_show_time": True}}
    date_text, time_text = obj._upcoming_date_and_time_text("9/19", "7:05PM")
    check("switch_show_date=false blanks only the date",
          (date_text, time_text) == ("", "T:7:05PM"), (date_text, time_text))


def test_layout_aliases():
    print("\nM18: layout offsets saved under the schema's element names apply")
    obj = _probe(sports.SportsRecent, config={"customization": {"layout": {
        "status": {"x_offset": 3, "y_offset": -1},
        "record": {"y_offset": -2, "away_x_offset": 4},
    }}})
    check("status.x_offset reaches status_text",
          obj._get_layout_offset("status_text", "x_offset") == 3)
    check("record.y_offset reaches records",
          obj._get_layout_offset("records", "y_offset") == -2)
    check("record.away_x_offset reaches records",
          obj._get_layout_offset("records", "away_x_offset") == 4)

    obj.config = {"customization": {"layout": {
        "records": {"y_offset": 5}, "record": {"y_offset": -2}}}}
    check("the code's own spelling wins when both are present",
          obj._get_layout_offset("records", "y_offset") == 5)
    check("an unset element still returns the default",
          obj._get_layout_offset("score", "x_offset", 0) == 0)


def main():
    test_logo_error_is_visible()
    test_odds_stay_off_the_top_row_text()
    test_switch_show_date_time()
    test_layout_aliases()
    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
