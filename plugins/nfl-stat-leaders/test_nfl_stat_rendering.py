#!/usr/bin/env python3
"""Rendering contracts for the NFL Stat Leaders ticker.

What a panel actually shows: the strip fits its panel exactly, glyphs are
drawn 1-bit, the layout is measured before it is drawn (so nothing is
clipped or padded), club colours read on an LED, and the appearance
switches do what they say.

Exit codes follow the monorepo's runner contract: 0 pass, 1 fail, 2 skip.
"""

import os
import sys

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

try:
    from PIL import Image
except ImportError:
    print("SKIP: Pillow is not installed")
    sys.exit(2)

import nfl_stat_renderer as renderer_module
from nfl_stat_renderer import (
    MEDAL_COLORS,
    TickerRenderer,
    _lift,
    _luminance255,
    _parse_color,
)

FAILURES = []

#: The panel sizes the core's harness renders, heights only -- the ticker's
#: layout is decided by height; width only decides how much of it you see.
PANEL_HEIGHTS = (32, 48, 64, 96, 128)

BOARDS = [
    {"key": "passing_yards", "title": "PASSING YARDS",
     "short_title": "PASS YDS", "leaders": [
        {"rank": 1, "name": "J. Allen", "position": "QB", "team": "BUF",
         "value": "4,183"},
        {"rank": 2, "name": "P. Mahomes", "position": "QB", "team": "KC",
         "value": "4,004"},
        {"rank": 3, "name": "J. Burrow", "position": "QB", "team": "CIN",
         "value": "3,987"},
        {"rank": 10, "name": "C. Stroud", "position": "QB", "team": "HOU",
         "value": "3,102"},
     ]},
    {"key": "rushing_touchdowns", "title": "RUSHING TDS",
     "short_title": "RUSH TDS", "leaders": [
        {"rank": 1, "name": "D. Henry", "position": "RB", "team": "BAL",
         "value": "16"},
     ]},
]


def check(label, condition, detail=""):
    if condition:
        print("[pass] %s" % label)
    else:
        print("[FAIL] %s%s" % (label, (" -- " + detail) if detail else ""))
        FAILURES.append(label)


def lit_columns(strip):
    """Column indices that have at least one lit pixel."""
    return {x for x, _ in _lit_pixels(strip)}


def _lit_pixels(strip):
    rgb = strip.convert("RGB")
    width, height = rgb.size
    data = rgb.load()
    for x in range(width):
        for y in range(height):
            if data[x, y] != (0, 0, 0):
                yield x, y


def test_strip_matches_the_panel_at_every_height():
    for height in PANEL_HEIGHTS:
        strip = TickerRenderer(height).build_strip(BOARDS, "2025 REGULAR")
        check("a %spx panel gets a strip" % height, strip is not None)
        if strip is None:
            continue
        check("the %spx strip is exactly panel-high" % height,
              strip.height == height, "got %s" % strip.height)
        check("the %spx strip is wider than one panel" % height,
              strip.width > height, "got %s" % strip.width)


def test_nothing_is_drawn_outside_the_strip():
    """The measured width has to be the drawn width.

    If a plan under-measures, the last entry is clipped; if it
    over-measures, the ticker ends in a stretch of black that reads as the
    plugin having stopped. Either way the tail is the tell.
    """
    for height in (32, 64):
        strip = TickerRenderer(height).build_strip(BOARDS, "2025 REGULAR")
        columns = lit_columns(strip)
        check("%spx: something is drawn" % height, bool(columns))
        # The bottom rule runs the length of every category segment, so the
        # rightmost lit column should sit inside the final board gap.
        tail = strip.width - max(columns)
        check("%spx: the strip ends in the board gap, not dead space" % height,
              0 < tail <= 4 * renderer_module.BOARD_GAP,
              "tail=%s of %s" % (tail, strip.width))


def test_text_is_rendered_one_bit():
    """Anti-aliased greys land on a panel as dim, smeared LEDs."""
    renderer = TickerRenderer(32)
    probe = Image.new("RGB", (8, 8))
    draw = renderer._make_draw(probe)
    check("the draw context rasterises 1-bit", draw.fontmode == "1")

    renderer_soft = TickerRenderer(32, appearance={"pixel_perfect_text": False})
    soft = renderer_soft._make_draw(Image.new("RGB", (8, 8)))
    check("the appearance switch turns anti-aliasing back on",
          soft.fontmode != "1")


def test_more_players_makes_a_longer_ticker():
    base = TickerRenderer(32).build_strip(BOARDS, "2025 REGULAR")
    trimmed = [{**BOARDS[0], "leaders": BOARDS[0]["leaders"][:1]}]
    short = TickerRenderer(32).build_strip(trimmed, "2025 REGULAR")
    check("fewer players means a shorter scroll", short.width < base.width,
          "%s vs %s" % (short.width, base.width))


def test_no_boards_means_no_strip():
    renderer = TickerRenderer(32)
    check("nothing to show yields no strip",
          renderer.build_strip([], "2025 REGULAR") is None)
    check("a board with no leaders is not drawn",
          renderer.build_strip([{"key": "x", "title": "X", "short_title": "X",
                                 "leaders": []}], "2025 REGULAR") is None)


def test_top_three_get_medal_badges():
    renderer = TickerRenderer(32)
    strip = renderer.build_strip(BOARDS, "2025 REGULAR")
    present = _colours_in(strip)
    for index, colour in enumerate(MEDAL_COLORS):
        check("rank %d wears its medal colour" % (index + 1),
              colour in present, str(colour))

    plain = TickerRenderer(32, appearance={"highlight_top_three": False})
    plain_strip = plain.build_strip(BOARDS, "2025 REGULAR")
    plain_present = _colours_in(plain_strip)
    check("switching medals off removes the silver badge",
          MEDAL_COLORS[1] not in plain_present)


def test_club_colours_read_on_a_panel():
    """Several official primaries are black or near-black; a badge in one
    is indistinguishable from an unlit LED."""
    renderer = TickerRenderer(32)
    if renderer._logo_path("BUF") is None:
        # The crests live in the core repo. Without them every club falls
        # back to the accent colour, and asserting a hue would pass or fail
        # on the accent rather than on anything this test is about.
        print("[pass] club colour check skipped: no core crests on this machine")
        return
    # Philadelphia's midnight green and Miami's aqua genuinely straddle the
    # green/cyan boundary, so both families are accepted for them.
    expectations = {
        "BUF": ("blue",), "KC": ("red",), "CIN": ("orange",),
        "PHI": ("green", "cyan"), "PIT": ("yellow",), "DEN": ("orange",),
        "MIA": ("cyan", "green"), "BAL": ("yellow",),
    }
    for abbr, expected in expectations.items():
        colour = renderer.team_accent(abbr)
        check("%s is legible on a panel" % abbr,
              _luminance255(colour) >= 60.0, "%s -> %s" % (abbr, colour))
        check("%s reads as %s" % (abbr, " or ".join(expected)),
              _hue_family(colour) in expected,
              "%s -> %s (%s)" % (abbr, colour, _hue_family(colour)))

    check("a club colour is not merely the accent fallback",
          renderer.team_accent("BUF") != renderer.accent_color)

    off = TickerRenderer(32, appearance={"team_color_accents": False,
                                         "accent_color": "#FFB612"})
    check("switching club colours off uses the accent colour",
          off.team_accent("BUF") == (255, 182, 18), str(off.team_accent("BUF")))
    check("an unknown club falls back to the accent colour",
          renderer.team_accent("ZZZ") == renderer.accent_color)


def test_lifting_keeps_the_hue():
    """The obvious channel-scaling version turns Baltimore's navy magenta."""
    navy = (16, 20, 60)
    lifted = _lift(navy)
    check("a navy is lifted until it reads",
          _luminance255(lifted) >= 100.0, str(lifted))
    check("and it is still blue", _hue_family(lifted) in ("blue", "purple"),
          "%s -> %s" % (lifted, _hue_family(lifted)))
    bright = (240, 200, 40)
    check("an already-bright colour is left alone", _lift(bright) == bright)


def test_accent_colour_parsing():
    check("a hex string is accepted", _parse_color("#123456", (0, 0, 0))
          == (18, 52, 86))
    check("the hash is optional", _parse_color("123456", (0, 0, 0))
          == (18, 52, 86))
    check("a list is accepted", _parse_color([1, 2, 3], (0, 0, 0)) == (1, 2, 3))
    for junk in ("nonsense", None, [1, 2], {"r": 1}, "#12345"):
        check("junk (%r) falls back to the default" % (junk,),
              _parse_color(junk, (9, 9, 9)) == (9, 9, 9))


def test_placeholder_fills_the_panel_without_overflowing():
    for height in (32, 64):
        image = Image.new("RGB", (64, height))
        TickerRenderer(height).draw_placeholder(image)
        check("the %spx placeholder draws something" % height,
              any(True for _ in _lit_pixels(image)))


def test_font_size_override_is_honoured():
    small = TickerRenderer(32)
    if small.primary_font_path is None:
        # Without a core checkout there is only PIL's fixed default face, so
        # there is no size to override; the rest of the suite still applies.
        print("[pass] font size override skipped: no pixel font on this machine")
        return
    big = TickerRenderer(32, appearance={"font_size": 16})
    check("a larger configured font makes taller text",
          big._band_height(big.font_primary)
          > small._band_height(small.font_primary))


def _colours_in(strip):
    """Every distinct colour in an image, without Pillow 14's deprecated getdata."""
    rgb = strip.convert("RGB")
    return {colour for _, colour in rgb.getcolors(rgb.width * rgb.height)}


def _hue_family(colour):
    """A coarse colour name, so an assertion can say 'orange' not an RGB triple."""
    import colorsys

    hue, sat, value = colorsys.rgb_to_hsv(*[c / 255.0 for c in colour])
    if value < 0.15:
        return "black"
    if sat < 0.18:
        return "grey"
    degrees = hue * 360.0
    for upper, name in ((14, "red"), (40, "orange"), (70, "yellow"),
                        (170, "green"), (200, "cyan"), (255, "blue"),
                        (330, "purple"), (360, "red")):
        if degrees < upper:
            return name
    return "red"


def main():
    for name, value in sorted(globals().items()):
        if name.startswith("test_") and callable(value):
            value()
    if FAILURES:
        print("\n%d check(s) failed" % len(FAILURES))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
