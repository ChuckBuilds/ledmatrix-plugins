#!/usr/bin/env python3
"""The matchup separator has to reach the full-screen scoreboard too.

scroll_card held the separator, the date format and the time format, and only
game_renderer.py read it -- so a user who set the separator to "@" got it on
the scroll ticker and on the Vegas ticker and never on the full-screen
scoreboard, which drew a hardcoded "Next Game" over a hardcoded 12h time.

The block now drives every display mode. What this pins down:

  * the default render is byte-identical to the old one. That is the whole
    reason switch_upcoming_center exists: upcoming_center defaults to "vs",
    this display has always drawn the date and time stacked, and honouring
    the shared key directly would have flipped every existing panel on
    update. Compared against a literal reference drawing, not against the
    implementation's own helpers, so it fails if the layout drifts.
  * "vs" draws the configured separator in the middle, empty draws nothing,
    and the date and time move to the top and bottom rows.
  * "inherit" follows upcoming_center.
  * time_format/date_format/show_*/swap_date_time reach this display.

Renders into a bare Image rather than through the display manager: the point
is the pixels _draw_upcoming_center_switch puts down, and going through
SportsUpcoming.display() would drag in ESPN fetches for no added coverage.

Run: <core-venv>/bin/python plugins/hockey-scoreboard/test_switch_upcoming_center.py
"""

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

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

results = []


def check(case, passed):
    results.append((case, passed))
    print("  [%s] %s" % ("pass" if passed else "FAIL", case))


WIDTH, HEIGHT = 64, 32
# What this plugin's scorebug passes the helper, and the layout element its
# schema advertises for the date. Basketball drives both rows off a single
# "status" element and has no date/time keys, so its copy differs here.
CENTER_KWARGS = {}
DATE_ELEMENT = "date"
GAME = {
    "game_date": "9/19",
    "game_time": "7:05PM",
    # A Friday, so the "weekday" date format has something to find.
    "start_time_utc": "2025-09-19T23:05:00+00:00",
}


def main():
    os.chdir(str(CORE))
    from PIL import Image, ImageDraw
    import sports

    class Bug(sports.SportsCore):
        """The smallest object _draw_upcoming_center_switch needs."""

        def __init__(self, config):
            self.config = config
            self.display_width = WIDTH
            self.display_height = HEIGHT
            self.logger = logging.getLogger("test")
            self.fonts = sports.SportsCore._load_fonts(self)

        def _get_timezone(self):
            import pytz
            return pytz.UTC

        # Abstract on SportsCore; nothing under test reaches them.
        def _custom_scorebug_layout(self, game, draw):  # pragma: no cover
            raise NotImplementedError

        def _extract_game_details(self, game_event):  # pragma: no cover
            raise NotImplementedError

        def _fetch_data(self):  # pragma: no cover
            raise NotImplementedError

    def render(config):
        """Pixels drawn by the helper, plus its keep-the-header answer."""
        image = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
        bug = Bug(config)
        keep_header = bug._draw_upcoming_center_switch(
            ImageDraw.Draw(image), GAME, HEIGHT // 2,
            GAME["game_date"], GAME["game_time"], **CENTER_KWARGS)
        return image, keep_header

    def lit_rows(image):
        pixels = image.load()
        return {y for y in range(HEIGHT)
                for x in range(WIDTH) if pixels[x, y] != (0, 0, 0)}

    # -- 1. the default render still matches the layout this display shipped --
    # Reference drawn from the literal old code, not from the new helpers.
    reference = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    ref_bug = Bug({})
    ref_draw = ImageDraw.Draw(reference)
    center_y = HEIGHT // 2
    date_width = ref_draw.textlength(GAME["game_date"], font=ref_bug.fonts["time"])
    date_x = (WIDTH - date_width) // 2
    date_y = center_y - 7
    ref_bug._draw_text_with_outline(
        ref_draw, GAME["game_date"], (date_x, date_y), ref_bug.fonts["time"])
    time_width = ref_draw.textlength(GAME["game_time"], font=ref_bug.fonts["time"])
    time_x = (WIDTH - time_width) // 2
    ref_bug._draw_text_with_outline(
        ref_draw, GAME["game_time"], (time_x, date_y + 9), ref_bug.fonts["time"])

    default_img, keep_header = render({})
    check("no config: render is identical to the pre-change layout",
          list(default_img.getdata()) == list(reference.getdata()))
    check("no config: the \"Next Game\" header is still drawn", keep_header is True)

    # The store writes schema defaults into config, so the shared key really
    # does arrive set to "vs". It must not reach this display on its own.
    shared_default, _ = render({"scroll_card": {"upcoming_center": "vs",
                                                "vs_text": "VS"}})
    check("upcoming_center alone does not change the full-screen layout",
          list(shared_default.getdata()) == list(reference.getdata()))

    # -- 2. "vs" draws the configured separator --
    at_img, at_header = render({"scroll_card": {"switch_upcoming_center": "vs",
                                                "vs_text": "@"}})
    at_only = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    at_draw = ImageDraw.Draw(at_only)
    at_bug = Bug({})
    at_width = at_draw.textlength("@", font=at_bug.fonts["score"])
    at_bug._draw_text_with_outline(
        at_draw, "@", ((WIDTH - at_width) // 2, center_y - 3), at_bug.fonts["score"])
    separator_rows = lit_rows(at_only)
    check("vs: the separator is drawn in the middle",
          separator_rows and separator_rows <= lit_rows(at_img))
    check("vs: the header slot is given up to the date/time", at_header is False)

    middle_band = set(range(center_y - 6, center_y + 7))
    edge_rows = lit_rows(at_img) - separator_rows
    check("vs: the date and time move out to the top and bottom rows",
          bool(edge_rows) and not (edge_rows & (middle_band - separator_rows)))

    blank_img, _ = render({"scroll_card": {"switch_upcoming_center": "vs",
                                           "vs_text": ""}})
    check("vs: an empty separator draws nothing in the middle",
          not (lit_rows(blank_img) & separator_rows))

    # -- 3. "none" leaves the middle clear --
    none_img, none_header = render({"scroll_card": {"switch_upcoming_center": "none"}})
    check("none: nothing is drawn in the middle",
          not (lit_rows(none_img) & separator_rows))
    check("none: the date and time are still drawn",
          bool(lit_rows(none_img)) and none_header is False)

    # -- 4. "inherit" follows the shared key --
    inherit_vs, _ = render({"scroll_card": {"switch_upcoming_center": "inherit",
                                            "upcoming_center": "vs",
                                            "vs_text": "@"}})
    check("inherit: follows upcoming_center = vs",
          list(inherit_vs.getdata()) == list(at_img.getdata()))
    inherit_stack, _ = render({"scroll_card": {"switch_upcoming_center": "inherit",
                                               "upcoming_center": "date_time"}})
    check("inherit: follows upcoming_center = date_time",
          list(inherit_stack.getdata()) == list(reference.getdata()))
    junk, junk_header = render({"scroll_card": {"switch_upcoming_center": "nonsense"}})
    check("an unknown value falls back to the stacked date and time",
          list(junk.getdata()) == list(reference.getdata()) and junk_header is True)

    # -- 5. the formatting keys reach this display --
    bug = Bug({"scroll_card": {"time_format": "24h"}})
    check("time_format: 24h converts the time",
          bug._format_game_time("7:05PM") == "19:05")
    check("time_format: unset leaves the 12h string alone",
          Bug({})._format_game_time("7:05PM") == "7:05PM")
    check("date_format: unset leaves the m/d string alone, so no panel restyles",
          Bug({})._format_game_date("9/19", GAME) == "9/19")
    check("date_format: abbrev rewrites the date",
          Bug({"scroll_card": {"date_format": "abbrev"}})
          ._format_game_date("9/19", GAME) == "Sep 19")
    check("date_format: weekday uses the game's start time",
          Bug({"scroll_card": {"date_format": "weekday"}})
          ._format_game_date("9/19", GAME) == "Fri Sep 19")
    check("date_format: day_first rewrites the date",
          Bug({"scroll_card": {"date_format": "day_first"}})
          ._format_game_date("9/19", GAME) == "19 Sep")

    no_time, _ = render({"scroll_card": {"show_time": False}})
    check("show_time: false drops the time and leaves the date where it was",
          lit_rows(no_time) and lit_rows(no_time) < lit_rows(default_img))
    no_date, _ = render({"scroll_card": {"show_date": False}})
    check("show_date: false drops the date and leaves the time where it was",
          lit_rows(no_date) and lit_rows(no_date) < lit_rows(default_img))
    check("show_date and show_time together cover the default render",
          lit_rows(no_time) | lit_rows(no_date) == lit_rows(default_img))

    swapped, _ = render({"scroll_card": {"swap_date_time": True}})
    check("swap_date_time: puts the time on top",
          list(swapped.getdata()) != list(default_img.getdata()))

    # -- 6. the layout offsets the schema advertises still move things --
    nudged, _ = render(
        {"customization": {"layout": {DATE_ELEMENT: {"y_offset": 3}}}})
    check("a date y_offset still moves the whole stack, as it always has",
          lit_rows(nudged) == {y + 3 for y in lit_rows(default_img)})

    # -- 7. the block actually reaches this display at runtime --
    # The per-league managers are handed a config rebuilt key by key, not the
    # plugin config, so a setting that is not named there is silently dropped:
    # the separator reached the ticker and never the scoreboard. Pinned here
    # because every check above talks to the helper directly and so cannot
    # see the plumbing.
    import manager as plugin_manager
    check("scroll_card is forwarded to the per-league managers",
          "scroll_card" in plugin_manager._ROOT_CONFIG_KEYS)

    print()
    failed = [c for c, ok in results if not ok]
    if failed:
        print("FAILED: %d of %d" % (len(failed), len(results)))
        return 1
    print("All %d checks passed." % len(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
