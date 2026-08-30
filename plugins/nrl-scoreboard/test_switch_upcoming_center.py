#!/usr/bin/env python3
"""The matchup separator has to reach the full-screen scoreboard too.

scroll_card held the separator, the date format and the time format, and only
game_renderer.py read it -- so a user who set the separator to "@" got it on
the scroll ticker and on the Vegas ticker and never on the full-screen
scoreboard, which drew a hardcoded "Next Game" over a hardcoded 12h time.

The block now drives every display mode. What this pins down:

  * the default render is byte-identical to the old one -- including under
    the config a real install materialises, which is the case that actually
    matters and the one the first cut of this test missed: the core merges
    schema defaults in recursively, so every key always arrives set and
    "the user has not touched this" is not a state the code can observe.
    Compared against a literal reference drawing, not against the
    implementation's own helpers, so it fails if the layout drifts.
  * the two keys that exist because the displays disagree about a default --
    switch_upcoming_center (the cards say "vs", this has always stacked the
    date and time) and switch_date_format (the cards say "Sep 19", this has
    always said "9/19") -- hold this display to what it already drew, and
    take "inherit" to opt into the scroll and Vegas setting.
  * "vs" draws the configured separator in the middle, empty draws nothing,
    and the date and time move out to the top and bottom rows, keeping the
    face they are drawn in -- the mode changes placement, not type.
  * vs_text, time_format, show_date/show_time and swap_date_time are shared
    outright, and do reach this display.

Renders into a bare Image rather than through the display manager: the point
is the pixels _draw_upcoming_center_switch puts down, and going through
SportsUpcoming.display() would drag in ESPN fetches for no added coverage.

Run: <core-venv>/bin/python plugins/nrl-scoreboard/test_switch_upcoming_center.py
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

    # -- 4b. the config a REAL INSTALL hands the plugin --
    # The decisive case, and the one the first cut of this test missed by
    # only ever passing configs a human would type. The core merges schema
    # defaults into the config on every load, recursively, so every key in
    # the block arrives set -- "the user did not touch it" is not a state
    # this code ever sees. Rendering under those exact defaults is the only
    # honest check that an untouched panel is unchanged.
    import json as _json
    schema = _json.loads(
        (plugin_dir / "config_schema.json").read_text())["properties"]["scroll_card"]
    materialised = {k: v["default"] for k, v in schema["properties"].items()
                    if "default" in v}
    real_install, real_header = render({"scroll_card": materialised})
    check("a real install's materialised defaults render the old layout",
          list(real_install.getdata()) == list(reference.getdata()))
    check("a real install still draws the header", real_header is True)
    check("the block's own default for the full-screen date is the historic one",
          materialised.get("switch_date_format") == "numeric")
    # date_format's default is "abbrev" and the scroll card renders it, so
    # reading the shared key here would have restyled 9/19 to Sep 19 on every
    # existing panel. Pinned as a rendered pixel comparison above and as the
    # formatter's answer here.
    check("the scroll card's date_format does not reach this display on its own",
          Bug({"scroll_card": {"date_format": "abbrev"}})
          ._format_game_date("9/19", GAME) == "9/19")
    check("switch_date_format: inherit follows the scroll card",
          Bug({"scroll_card": {"switch_date_format": "inherit",
                               "date_format": "abbrev"}})
          ._format_game_date("9/19", GAME) == "Sep 19")

    # -- 5. the formatting keys reach this display --
    bug = Bug({"scroll_card": {"time_format": "24h"}})
    check("time_format: 24h converts the time",
          bug._format_game_time("7:05PM") == "19:05")
    check("time_format: unset leaves the 12h string alone",
          Bug({})._format_game_time("7:05PM") == "7:05PM")
    check("switch_date_format: unset leaves the m/d string alone",
          Bug({})._format_game_date("9/19", GAME) == "9/19")
    check("switch_date_format: abbrev rewrites the date",
          Bug({"scroll_card": {"switch_date_format": "abbrev"}})
          ._format_game_date("9/19", GAME) == "Sep 19")
    check("switch_date_format: weekday uses the game's start time",
          Bug({"scroll_card": {"switch_date_format": "weekday"}})
          ._format_game_date("9/19", GAME) == "Fri Sep 19")
    check("switch_date_format: day_first rewrites the date",
          Bug({"scroll_card": {"switch_date_format": "day_first"}})
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

    # Changing the centre mode moves the two lines; it does not restyle them.
    # Both rows keep this scorebug's own "time" face wherever they land, in
    # every mode -- the smaller "detail" face is a floor for text that cannot
    # fit the panel at all, not a per-row style.
    #
    # Measured against what each face would actually produce, rather than
    # against "does it fit": clipping means an overflowing string simply stops
    # being drawn, so a width bound alone can never tell the two faces apart.
    def _ink_width(image, y0, y1):
        """Horizontal extent of lit pixels in a band, 0 if the band is dark."""
        pixels = image.load()
        xs = [x for y in range(max(0, y0), min(HEIGHT, y1))
              for x in range(WIDTH) if pixels[x, y] != (0, 0, 0)]
        return (max(xs) - min(xs) + 1) if xs else 0

    probe = ImageDraw.Draw(Image.new("RGB", (4, 4)))
    time_font = at_bug.fonts["time"]
    detail_font = at_bug.fonts.get("detail") or time_font

    def _closer_to_time_face(ink, text):
        t = probe.textlength(text, font=time_font)
        d = probe.textlength(text, font=detail_font)
        if t == d:
            return True          # the plugin sets both faces the same size
        return abs(ink - (t + 2)) < abs(ink - (d + 2))

    # A date that fits: it must be drawn in the same face the stacked layout
    # uses, whichever row the mode and swap_date_time put it on.
    short_date = Bug({})._format_game_date(GAME["game_date"], GAME)
    fits_cfg = {"switch_upcoming_center": "vs", "vs_text": "@"}
    plain, _ = render({"scroll_card": fits_cfg})
    flipped, _ = render({"scroll_card": dict(fits_cfg, swap_date_time=True)})
    check("vs: a date that fits keeps the scorebug's own face on the bottom row",
          _closer_to_time_face(_ink_width(plain, HEIGHT - 10, HEIGHT), short_date))
    check("vs + swap: the same date keeps that face on the top row",
          _closer_to_time_face(_ink_width(flipped, 0, 10), short_date))

    # A date that cannot fit at all drops to the smaller face rather than
    # running off both edges. Only the weekday format is long enough to.
    long_date = Bug({"scroll_card": {"switch_date_format": "weekday"}}) \
        ._format_game_date(GAME["game_date"], GAME)
    if probe.textlength(long_date, font=time_font) + 2 <= WIDTH:
        check("SKIPPED: even the longest date fits this plugin's face", True)
    elif probe.textlength(long_date, font=time_font) == probe.textlength(long_date, font=detail_font):
        check("SKIPPED: this plugin's detail and time faces are the same size", True)
    else:
        over, _ = render({"scroll_card": {"switch_upcoming_center": "vs",
                                          "vs_text": "@",
                                          "switch_date_format": "weekday"}})
        ink = _ink_width(over, HEIGHT - 10, HEIGHT)
        detail_w = probe.textlength(long_date, font=detail_font)
        # Asserted as the property, not as "nearer to one face than the
        # other": text drawn too wide is clipped to the panel, and a clipped
        # 80px string measures 62px -- equidistant from both candidates, so a
        # nearest-match check ties and silently passes. What has to hold is
        # that the date fits with room to spare and measures like the small
        # face, which the unfixed code cannot do.
        check("a date too wide for the face falls back to the smaller one",
              ink and ink <= detail_w + 4 and ink < WIDTH - 2)

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
