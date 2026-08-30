#!/usr/bin/env python3
"""The possession football must be visible, on the panel, and on top of nothing.

The ball was a hardcoded 7x5 ellipse placed a fixed 3px from the down &
distance text, guarded only by `ball_x_center > 0` -- a test that a negative x
had not been computed, not a test that the ball fit anywhere in particular. So:

- On a 64px-wide panel the centred down & distance text reaches close enough to
  the corners that the ball landed on the timeout bars and the record text.
- The guard could not see the right-hand edge at all, so home possession pushed
  the ball off a narrow panel entirely, and off the adaptive 256x128 card.

The bottom row is now laid out against itself: the ball gets a reserved slot on
both sides of the text inside the space the timeout bars and records leave
free, so it never has to be clamped in practice, and the clamp is a backstop.

The ball's SIZE is deliberately untouched -- that was never the problem, and
every pixel it grew would cost down & distance detail the row cannot spare. The
sizes are asserted exactly, in both directions, so a later "make it bigger"
cannot quietly trade the yardage away for it.

Three code paths draw it and all three must hold -- football.py's classic
scorebug (default), GameRenderer's classic card (scroll mode), and
GameRenderer's adaptive card (layout_mode: "adaptive").

Each case is rendered twice: once to capture the box the ball occupies, once
with the ball suppressed. A non-black pixel of the second render inside that
box is something the ball would have hidden. Team logos are blanked -- the
scorebug draws its text over them deliberately, so they are not a collision.

Run: <core-venv>/bin/python plugins/football-scoreboard/test_possession_ball_has_room.py
"""

import itertools
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

# The safety harness's DEFAULT_TEST_SIZES: a spread of panel shapes, not a
# blessed list. 64x32 and 64x64 are where the free band is tightest.
SIZES = [(64, 32), (128, 32), (64, 64), (96, 48), (128, 64), (256, 32),
         (128, 96), (256, 128)]

# ESPN omits down & distance on kickoffs; the ball must still be drawn then.
DOWNS = [("3rd & 7", "3rd & 7 at KC 35"),
         ("4th & Goal", "4th & Goal at GB 3"),
         ("1st & 10", "1st & 10 at WSH 25"),
         ("", "")]

# The ball's size is deliberately unchanged by this fix -- it was never the
# problem, and every pixel it grew would be a pixel of down & distance the row
# had to give up. The classic paths draw a fixed 7x5; the adaptive card scales
# its radii with px() as it always has. Both are asserted exactly, so a future
# "let's make it bigger" cannot land silently.
CLASSIC_SIZE = (7, 5)


def check(case, passed):
    results.append((case, passed))
    if not passed:
        print("  [FAIL] %s" % case)


def main():
    os.chdir(str(CORE))
    from unittest.mock import Mock
    from PIL import Image
    import game_renderer as gr
    import football as fb

    drawn = []

    def _spy_text(cls):
        orig = cls._draw_text_with_outline

        def spy(self_, *a, **k):
            for v in a:
                if isinstance(v, str):
                    drawn.append(v)
                    break
            return orig(self_, *a, **k)
        cls._draw_text_with_outline = spy

    import sports
    _spy_text(gr.GameRenderer)
    _spy_text(sports.SportsCore)

    logos = str(plugin_dir / "assets" / "sports" / "nfl_logos")
    blank = lambda *a, **k: Image.new("RGBA", (1, 1), (0, 0, 0, 0))  # noqa: E731

    def game(poss, downs, records):
        return {
            "home_id": "1", "home_abbr": "KC",
            "home_logo_path": os.path.join(logos, "KC.png"),
            "away_id": "2", "away_abbr": "GB",
            "away_logo_path": os.path.join(logos, "GB.png"),
            "home_score": "21", "away_score": "17",
            "period_text": "Q3", "clock": "8:42",
            "is_live": True, "is_final": False, "is_upcoming": False,
            "down_distance_text": downs[0], "down_distance_text_long": downs[1],
            "possession_indicator": poss, "home_timeouts": 2, "away_timeouts": 3,
            "league": "nfl", "home_record": "10-5", "away_record": "8-7",
            "is_redzone": False, "scoring_event": "", "odds": {},
        }

    def capture(render, suppress):
        """Run *render* with the ball spied on. Returns (image, box)."""
        box = {}
        real = gr.draw_possession_football

        def spy(draw, b):
            box["b"] = b
            if not suppress:
                real(draw, b)

        # football.py imported the name, so rebind there too
        gr.draw_possession_football = spy
        fb.draw_possession_football = spy
        try:
            return render(), box.get("b")
        finally:
            gr.draw_possession_football = real
            fb.draw_possession_football = real

    def renderer_case(w, h, poss, downs, records, adaptive):
        cfg = {"layout_mode": "adaptive" if adaptive else "classic",
               "nfl": {"display_options": {"show_records": records,
                                           "show_ranking": False,
                                           "show_odds": False}}}

        def render():
            r = gr.GameRenderer(w, h, cfg)
            r._load_and_resize_logo = blank
            r._load_raw_logo = blank
            return r.render_game_card(game(poss, downs, records), "live").convert("RGB")
        return render

    def expected_size(w, h, path):
        """What the pre-fix code drew: a fixed 7x5 on the classic paths, and
        px()-scaled radii on the adaptive card."""
        if path != "adaptive card":
            return CLASSIC_SIZE
        ctx = gr.GameRenderer(w, h, {"layout_mode": "adaptive"})._ctx
        return (2 * ctx.px(3, minimum=2) + 1, 2 * ctx.px(2, minimum=1) + 1)

    class Harness(fb.FootballLive):
        def _fetch_data(self, *a, **kw):
            return None

    def plugin_case(w, h, poss, downs, records):
        def render():
            dm = Mock()
            dm.display_width, dm.display_height = w, h
            dm.width, dm.height = w, h
            dm.matrix = None
            dm.image = Image.new("RGB", (w, h), (0, 0, 0))
            dm.update_display = Mock()
            cache = Mock()
            cm = Mock()
            cm.load_config.return_value = {}
            cache.config_manager = cm
            cache.get = Mock(return_value=None)
            cache.set = Mock()
            cfg = {"enabled": True,
                   "nfl": {"enabled": True, "favorite_teams": [],
                           "display_options": {"show_records": records,
                                               "show_ranking": False,
                                               "show_odds": False}}}
            mgr = Harness(cfg, dm, cache, logging.getLogger("t"), "nfl")
            mgr.show_records, mgr.show_ranking = records, False
            mgr._load_and_resize_logo = blank
            mgr._draw_scorebug_layout(game(poss, downs, records))
            return dm.image.convert("RGB")
        return render

    for w, h in SIZES:
        for poss, downs, records in itertools.product(
                ("home", "away"), DOWNS, (True, False)):
            dd = downs[0] or "kickoff"
            for path, render in (
                ("classic scorebug", plugin_case(w, h, poss, downs, records)),
                ("scroll card", renderer_case(w, h, poss, downs, records, False)),
                ("adaptive card", renderer_case(w, h, poss, downs, records, True)),
            ):
                case = "%s %dx%d %s '%s' records=%s" % (path, w, h, poss, dd, records)
                _, box = capture(render, suppress=False)
                if box is None:
                    # Dropping the ball is legitimate: where the row cannot
                    # hold both, the down & distance wins. What must never
                    # happen is a ball drawn somewhere it does not belong.
                    continue
                x0, y0, x1, y1 = box
                on_panel = 0 <= x0 and 0 <= y0 and x1 < w and y1 < h
                check("%s -- ball is on the panel" % case, on_panel)
                if not on_panel:
                    continue
                size = (x1 - x0 + 1, y1 - y0 + 1)
                expect = expected_size(w, h, path)
                check("%s -- ball is %dx%d, the size it always was" % (case, *expect),
                      size == expect)

                without, _ = capture(render, suppress=True)
                px = without.load()
                hidden = [(x, y)
                          for y in range(y0, y1 + 1)
                          for x in range(x0, x1 + 1)
                          if px[x, y] != (0, 0, 0)]
                check("%s -- ball hides nothing else (%d px)" % (case, len(hidden)),
                      not hidden)

    check("the classic ball constant is still 7x5",
          gr.POSSESSION_BALL_SIZE == CLASSIC_SIZE)

    # The ball must never change the down & distance. Whatever the row shows
    # with no possession known is exactly what it must still show when a team
    # has the ball -- no shortened wording, no smaller rung, no truncation.
    # This is the property that broke when the ball was given reserved space.
    for w, h in SIZES:
        for path, mk in (("classic scorebug", plugin_case),
                         ("scroll card", lambda *a: renderer_case(*a, False)),
                         ("adaptive card", lambda *a: renderer_case(*a, True))):
            for records in (True, False):
                strings = {}
                for poss in (None, "home", "away"):
                    drawn.clear()
                    mk(w, h, poss, DOWNS[0], records)()
                    strings[poss] = [t for t in drawn if "&" in t]
                check("%s %dx%d records=%s -- down & distance was drawn at all"
                      % (path, w, h, records), bool(strings[None]))
                check("%s %dx%d records=%s -- ball does not change the wording"
                      % (path, w, h, records),
                      strings[None] == strings["home"] == strings["away"])

    check("the classic ball constant is still 7x5",
          gr.POSSESSION_BALL_SIZE == CLASSIC_SIZE)

    failed = [c for c, ok in results if not ok]
    print("%d checks, %s" % (len(results),
                             "%d FAILED" % len(failed) if failed else "all passed"))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
