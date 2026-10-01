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
    text = wide._recent_date_text(GAME)
    check("192 wide: date and full series share the line",
          text == "9/28 - Series tied 1-1", text)
    text = Bug(128)._recent_date_text(GAME)
    check("128 wide: the full series alone beats a clipped date",
          text == "Series tied 1-1", text)

    off = Bug(128, show_series=False)
    check("setting off: date only", off._recent_date_text(GAME) == "9/28")
    check("no series from ESPN: date only",
          wide._recent_date_text(dict(GAME, series_summary="")) == "9/28")

    from PIL import Image, ImageDraw

    for width in (64, 96, 128, 192):
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
                # The row it lands on holds the series and nothing at the
                # centre: the old code drew it over the score.
                image = Image.new("RGB", (width, 32), (0, 0, 0))
                draw = ImageDraw.Draw(image)
                if font is not bug.fonts["time"]:
                    check(label + ": date row is cleared for the small font",
                          bug._recent_date_text(game) == "")
                    bug._custom_scorebug_layout(game, draw)
                    pixels = image.load()
                    rows = [y for y in range(32) for x in range(width)
                            if pixels[x, y] != (0, 0, 0)]
                    cols = [x for y in range(32) for x in range(width)
                            if pixels[x, y] != (0, 0, 0)]
                    check(label + ": small-font line is on the bottom edge",
                          rows and min(rows) >= 32 - 8 and max(rows) == 31,
                          (min(rows), max(rows)) if rows else None)
                    check(label + ": and inside the panel",
                          cols and min(cols) >= 0 and max(cols) < width)
                else:
                    check(label + ": time-font line is the date row's text",
                          bug._recent_date_text(game) == text)
                    bug._custom_scorebug_layout(game, draw)
                    check(label + ": hook draws nothing extra",
                          not image.getbbox())

    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
