#!/usr/bin/env python3
"""
Tests the date on a finished game, on both displays that show one.

Two gaps, opposite in kind.

The full-screen (switch) Recent scoreboard has drawn a date along its bottom
edge since it was written, but it drew ``game_date`` raw -- the "9/23" that
_extract_game_details emits -- so it was the one date on the board that ignored
every date-format setting. A panel configured for "Sep 19" read "Sep 19" on its
upcoming screen and "9/23" here. There was also no way to turn it off.

The scroll and Vegas Recent card drew no date at all. Five of the eight sibling
scoreboards (afl, basketball, football, nrl, soccer) already draw one there, so
this closes a drift gap -- but their placement does not transfer. They centre
the recent score vertically and put the date on the free bottom edge; this card
puts the score at ``display_height - 14``, so the free strip is *above* it. And
where depends on the panel: a 64px card has a clear strip between the status
row and the score, a 24px one does not. ``auto`` measures rather than guesses.

Baseball is now the only lineage where this date is both formatted and
optional; the other five draw ``game_date`` raw and unconditionally.

These checks pin:

  * the full-screen date is unchanged on an untouched config (switch_date_format
    defaults to "numeric", which returns the raw text), and follows the setting
    once it is changed;
  * switch_recent_show_date defaults on -- turning it off is the new part, not
    turning it on -- and clears the row when off;
  * the scroll card draws no date by default, so no existing panel changes;
  * recent_show_date draws one, formatted by the scroll key date_format;
  * 'auto' takes its own row where one fits and the top line where it does not;
  * an explicit 'own_row' with no room draws nothing rather than overprinting
    the score;
  * 'top_line' spends the status row, and the odds avoidance span follows it
    there rather than still measuring "Final".

Run: <core-venv>/bin/python plugins/baseball-scoreboard/test_recent_game_date.py
"""

# A test harness: it reaches into protected members on purpose and builds
# stand-in objects whose signatures exist only to match what they replace.
# pylint: disable=protected-access,unused-argument,broad-exception-caught

import logging
import sys
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

from PIL import Image  # noqa: E402

from game_renderer import GameRenderer  # noqa: E402
import sports  # noqa: E402

GAME = {
    "league": "mlb", "home_abbr": "NYY", "away_abbr": "TB",
    "home_score": "9", "away_score": "2", "game_date": "9/23",
    "status_text": "Final", "home_record": "91-68", "away_record": "80-79",
}

failures = []


def check(label, ok, detail=None):
    print(("  PASS  " if ok else "  FAIL  ") + label
          + ("" if ok or detail is None else "  -- %r" % (detail,)))
    if not ok:
        failures.append(label)


# --- the scroll / Vegas card ------------------------------------------------

def _renderer(height, scroll_card, customization=None, width=128):
    config = {"scroll_card": dict(scroll_card)}
    if customization:
        config["customization"] = customization
    renderer = GameRenderer(width, height, config,
                            custom_logger=logging.getLogger("recent_date_probe"))
    renderer._load_and_resize_logo = lambda league, abbr: Image.new(
        "RGBA", (height, height), (40, 90, 200, 255))
    return renderer


def _card(height, scroll_card, customization=None, width=128):
    return _renderer(height, scroll_card, customization, width).render_game_card(
        dict(GAME), "recent")


def differs(a, b):
    return a.tobytes() != b.tobytes()


def test_scroll_card_default():
    print("the scroll/Vegas card is unchanged until the date is asked for")
    for height in (32, 64):
        off = _card(height, {})
        also_off = _card(height, {"recent_show_date": False})
        check("h=%d: the default draws no date" % height, not differs(off, also_off))
        on = _card(height, {"recent_show_date": True})
        check("h=%d: recent_show_date=True changes the card" % height,
              differs(off, on))


def test_scroll_card_text_and_format():
    print("\nthe card's date follows the scroll date_format")
    r = _renderer(64, {"recent_show_date": True, "date_format": "abbrev"})
    check("abbrev reads 'Sep 23'", r._recent_date_text(GAME) == "Sep 23",
          r._recent_date_text(GAME))
    r = _renderer(64, {"recent_show_date": True, "date_format": "numeric"})
    check("numeric keeps '9/23'", r._recent_date_text(GAME) == "9/23",
          r._recent_date_text(GAME))
    r = _renderer(64, {"recent_show_date": True, "date_format": "day_first"})
    check("day_first reads '23 Sep'", r._recent_date_text(GAME) == "23 Sep",
          r._recent_date_text(GAME))
    r = _renderer(64, {"date_format": "abbrev"})
    check("and nothing at all while the toggle is off",
          r._recent_date_text(GAME) == "")
    r = _renderer(64, {"recent_show_date": True})
    check("a game with no date yields no text",
          r._recent_date_text({"league": "mlb"}) == "")


def test_placement_is_measured():
    print("\n'auto' measures the card rather than assuming a panel size")
    cases = [
        (64, None, "own_row", "64px has a clear strip above the score"),
        (32, None, "own_row", "32px still fits a 6px line between the two rows"),
        (32, {"period_text": {"font_size": 16}}, "top_line",
         "a 16px status face eats the strip"),
        (24, None, "top_line", "a 24px panel has no strip at all"),
    ]
    for height, customization, expected, why in cases:
        r = _renderer(height, {"recent_show_date": True}, customization)
        got = r._recent_date_placement("Sep 23", r._recent_date_row_top())
        check("h=%d: auto -> %s (%s)" % (height, expected, why),
              got == expected, got)


def test_explicit_placement():
    print("\nan explicit position is honoured, and never overprints the score")
    r = _renderer(64, {"recent_show_date": True, "recent_date_position": "top_line"})
    check("top_line on a tall panel stays on the top line",
          r._recent_date_placement("Sep 23", r._recent_date_row_top()) == "top_line")
    r = _renderer(24, {"recent_show_date": True, "recent_date_position": "own_row"})
    check("own_row with no room draws nothing rather than over the score",
          r._recent_date_placement("Sep 23", r._recent_date_row_top()) == "")
    top_line = _card(64, {"recent_show_date": True, "recent_date_position": "top_line"})
    own_row = _card(64, {"recent_show_date": True, "recent_date_position": "own_row"})
    check("the two positions render differently", differs(top_line, own_row))


def test_top_line_replaces_the_status():
    print("\n'top_line' spends the FINAL row, and the odds span follows it")
    plain = _card(64, {})
    top_line = _card(64, {"recent_show_date": True,
                          "recent_date_position": "top_line"})
    check("the top row changed", differs(plain, top_line))

    # The odds are placed around whatever is on the top row. Measuring the span
    # from "Final" while drawing "Sep 23" there would let the two collide.
    r = _renderer(64, {"recent_show_date": True,
                       "recent_date_position": "top_line",
                       "date_format": "abbrev"})
    spans = []
    real = r._top_row_span
    r._top_row_span = lambda draw, text, font, *a, **k: (
        spans.append(text) or real(draw, text, font, *a, **k))
    game = dict(GAME)
    game["odds"] = {"home_team_odds": {"money_line": -150},
                    "away_team_odds": {"money_line": 130},
                    "spread": -1.5, "over_under": 8.5}
    r.render_game_card(game, "recent")
    check("the span is measured from the date now on that row",
          spans == ["Sep 23"], spans)


def test_bottom_edge_is_unchanged():
    print("\nthe date never pushes anything off the bottom edge")
    for height in (32, 64):
        rows = []
        for scroll_card in ({}, {"recent_show_date": True},
                            {"recent_show_date": True,
                             "recent_date_position": "top_line"}):
            image = _card(height, scroll_card).convert("L")
            pixels = image.load()
            rows.append(max((y for y in range(height)
                             for x in range(image.width) if pixels[x, y] > 8),
                            default=-1))
        check("h=%d: the lowest lit row is the same in all three" % height,
              len(set(rows)) == 1 and rows[0] == height - 1, rows)


# --- the full-screen (switch) scorebug --------------------------------------

class _Switch:
    """The two SportsCore helpers the full-screen Recent date goes through."""

    _recent_date_text = sports.SportsCore._recent_date_text
    _format_game_date = sports.SportsCore._format_game_date
    _switch_date_format = sports.SportsCore._switch_date_format
    _card_option = sports.SportsCore._card_option
    _weekday_for = sports.SportsCore._weekday_for
    _MONTH_ABBR = sports.SportsCore._MONTH_ABBR
    _WEEKDAY_ABBR = sports.SportsCore._WEEKDAY_ABBR

    def __init__(self, scroll_card=None):
        self.config = {"scroll_card": dict(scroll_card or {})}
        self.logger = logging.getLogger("recent_date_switch")


def test_switch_date():
    print("\nthe full-screen Recent date: same row, now formatted and optional")
    check("an untouched config renders exactly what it rendered before",
          _Switch()._recent_date_text(GAME) == "9/23")
    check("switch_date_format=abbrev finally reaches this screen",
          _Switch({"switch_date_format": "abbrev"})._recent_date_text(GAME)
          == "Sep 23")
    check("'inherit' follows the scroll setting",
          _Switch({"switch_date_format": "inherit",
                   "date_format": "day_first"})._recent_date_text(GAME)
          == "23 Sep")
    check("switch_recent_show_date defaults on",
          _Switch()._recent_date_text(GAME) != "")
    check("and turning it off clears the row -- which was not possible before",
          _Switch({"switch_recent_show_date": False})._recent_date_text(GAME) == "")
    check("the scroll-card toggle does not reach this screen",
          _Switch({"recent_show_date": False})._recent_date_text(GAME) == "9/23")
    check("a game with no date yields no text",
          _Switch()._recent_date_text({}) == "")
    check("and neither does None", _Switch()._recent_date_text(None) == "")


def main():
    test_scroll_card_default()
    test_scroll_card_text_and_format()
    test_placement_is_measured()
    test_explicit_placement()
    test_top_line_replaces_the_status()
    test_bottom_edge_is_unchanged()
    test_switch_date()

    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
