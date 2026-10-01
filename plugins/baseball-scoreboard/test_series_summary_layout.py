#!/usr/bin/env python3
"""
The series summary shares the full-screen Recent card's bottom row.

show_series_summary drew ESPN's line ("Series tied 1-1") at the vertical centre
of the card, straight over the score, and the "Final/10" and date text around
it -- an unreadable pile on a real panel. The bottom row is the free one (it
carries the date), so the series now lives there: "date - series" when that
fits, the series alone when it does not, and a compact spelling ("Tied 1-1")
before the series is ever dropped. It is never drawn at the centre.

Run: <core-venv>/bin/python plugins/baseball-scoreboard/test_series_summary_layout.py
"""

# pylint: disable=protected-access,unused-argument,import-outside-toplevel

import logging
import os
import sys
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

REPO = Path(__file__).resolve().parents[2]
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

failures = []


def check(label, ok, detail=None):
    print(("  PASS  " if ok else "  FAIL  ") + label
          + ("" if ok or detail is None else "  -- %r" % (detail,)))
    if not ok:
        failures.append(label)


GAME = {"game_date": "9/28", "series_summary": "Series tied 1-1",
        "home_record": "91-68", "away_record": "80-79"}


def main():
    os.chdir(str(CORE))
    import baseball
    import sports

    class Bug(baseball.Baseball):
        def __init__(self, width, config=None, show_series=True,
                     show_records=False):
            self.config = config or {}
            self.display_width = width
            self.display_height = 32
            self.logger = logging.getLogger("test")
            self.show_series_summary = show_series
            self.show_records = show_records
            self.show_ranking = False
            self._font_cache = {}
            self.fonts = sports.SportsCore._load_fonts(self)

        def _fetch_data(self):  # pragma: no cover
            raise NotImplementedError

    compact = baseball.Baseball._compact_series_summary
    check("tied compacts", compact("Series tied 1-1") == "Tied 1-1",
          compact("Series tied 1-1"))
    check("leads compacts", compact("NYY leads series 2-1") == "NYY 2-1",
          compact("NYY leads series 2-1"))
    check("wins compacts", compact("NYY wins series 4-2") == "NYY W 4-2",
          compact("NYY wins series 4-2"))

    wide = Bug(192)
    text = wide._series_line(GAME)[0]
    check("192 wide: date and full series share the line",
          text == "9/28 - Series tied 1-1", text)
    text = Bug(128)._series_line(GAME)[0]
    check("128 wide: the full series alone beats a clipped date",
          text == "Series tied 1-1", text)

    off = Bug(128, show_series=False)
    check("setting off: date only", off._recent_date_text(GAME) == "9/28")
    check("no series from ESPN: date only",
          wide._recent_date_text(dict(GAME, series_summary="")) == "9/28")
    check("a series line takes over the row, so nothing else draws a date",
          wide._recent_date_text(GAME) == "")

    from PIL import Image, ImageDraw

    def score_rows(bug, game):
        """(top, bottom) rows the centred score occupies."""
        probe = ImageDraw.Draw(Image.new("L", (1, 1)))
        box = probe.textbbox((0, 0), "3-5", font=bug.fonts["score"])
        y = 16 - max(3, bug._score_font_size() // 2 - 1)
        return y + box[1], y + box[3]

    def lit(bug, game, width):
        image = Image.new("RGB", (width, 32), (0, 0, 0))
        bug._custom_scorebug_layout(game, ImageDraw.Draw(image))
        pixels = image.load()
        pts = [(x, y) for y in range(32) for x in range(width)
               if pixels[x, y] != (0, 0, 0)]
        return pts

    for width in (64, 96, 128, 192, 320):
        for records in (False, True):
            bug = Bug(width, show_records=records)
            for summary in ("Series tied 1-1", "NYY leads series 2-1",
                            "NYY wins series 4-2"):
                game = dict(GAME, series_summary=summary)
                text, font = bug._series_line(game)
                label = "w=%d records=%s %r" % (width, records, summary)
                avail = width
                if records:
                    avail -= 2 * (bug._text_width("91-68", bug.fonts["record"]) + 1)
                # 64 wide with both record corners on leaves no room between
                # them for any spelling; the line is still drawn, on the panel.
                if not (width == 64 and records):
                    check(label + ": %r fits its row" % text,
                          bug._text_width(text, font) <= avail)
                check(label + ": the plain date row is left to the series line",
                      bug._recent_date_text(game) == "")
                pts = lit(bug, game, width)
                room_top = score_rows(bug, game)[1]
                check(label + ": drawn on the panel, under the score",
                      pts and min(p[0] for p in pts) >= 0
                      and max(p[0] for p in pts) < width
                      and min(p[1] for p in pts) > room_top - 2
                      and max(p[1] for p in pts) <= 31,
                      (min(p[1] for p in pts), room_top) if pts else None)

    # A large time face (period_text.font_size) cannot sit under the score at
    # full size: it must step down rather than print over it. This is the
    # panel from the bug report, 5 x 64x32 with a big status face.
    big = Bug(320, config={"customization": {"period_text": {"font_size": 17}}})
    big_game = dict(GAME, series_summary="Series tied 1-1")
    check("a 17px time face really is large here", big.fonts["time"].size == 17,
          big.fonts["time"].size)
    top, bottom = score_rows(big, big_game)
    faces = big._series_fonts(big_game)
    check("a 17px time face is stepped down to one that leaves the score clear",
          faces[0].size < 17, [f.size for f in faces])
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    box = probe.textbbox((0, 0), "9/30 Final/10 Sg", font=faces[0])
    check("status row (from y=1) ends above the score", 1 + box[3] - box[1] <= top,
          (1 + box[3] - box[1], top))
    text, font = big._series_line(big_game)
    big.fonts["time"] = faces[0]   # as _draw_scorebug_layout swaps it in
    pts = lit(big, big_game, 320)
    check("the series row starts below the score (row %d vs %d)"
          % (min(p[1] for p in pts), bottom), min(p[1] for p in pts) > bottom - 1)

    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
