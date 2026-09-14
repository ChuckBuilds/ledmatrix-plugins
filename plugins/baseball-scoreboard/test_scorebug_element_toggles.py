#!/usr/bin/env python3
"""The live scorebug honours display_options.show_innings/bases/outs/count,
and scroll/Vegas result cards show "Final/10" like the full-screen Recent.

Toggles. baseball.py has read show_innings, show_outs, show_bases and
show_count into attributes since the plugin was written, but nothing drew on
them, the manager adapter never forwarded them and the schema never offered
them. Each is now declared per league, forwarded, and honoured by all three
places that draw those elements:

  * BaseballLive._draw_scorebug_layout (the classic live scorebug),
  * BaseballLive._draw_traditional_scoreboard_screen (its At Bat panel and
    batting-half arrow),
  * GameRenderer._render_live_game (the scroll and Vegas live card).

Each test draws the real method with the element on and off and requires the
two images to differ, so a toggle that is read but not drawn on fails. A
hidden element keeps its geometry, and "FINAL" is a status, not the inning, so
show_innings does not hide it.

Final/N. The scroll/Vegas recent card hard-coded "Final", dropping extra
innings ("Final/10") and MiLB's 7-inning doubleheaders ("Final/7"), which the
full-screen Recent scorebug has shown since the drift audit. The card now uses
the same rule: the game's status_text when it fits between the logos.

Run: <core-venv>/bin/python plugins/baseball-scoreboard/test_scorebug_element_toggles.py
"""

import logging
import os
import sys
from pathlib import Path

plugin_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(plugin_dir))

REPO = plugin_dir.parents[1]
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

from PIL import Image, ImageChops, ImageDraw, ImageFont  # noqa: E402

TOGGLES = ("show_innings", "show_bases", "show_outs", "show_count")

results = []


def check(case, passed, detail=""):
    results.append((case, bool(passed)))
    print("  [%s] %s%s" % ("pass" if passed else "FAIL", case,
                           "" if passed else "  <- " + str(detail)))


def differs(a, b):
    return ImageChops.difference(a.convert("RGB"), b.convert("RGB")).getbbox() is not None


def has_color(img, rgb):
    return any(color == rgb for _count, color in img.convert("RGB").getcolors(1 << 20))


class _ErrorLog(logging.Handler):
    def __init__(self):
        super().__init__(logging.ERROR)
        self.records = []

    def emit(self, record):
        self.records.append(record.getMessage())


def _logger(name):
    log = logging.getLogger(name)
    log.propagate = False
    log.handlers[:] = []
    errors = _ErrorLog()
    log.addHandler(errors)
    return log, errors


def _logo(size=16):
    return Image.new("RGBA", (size, size), (200, 0, 0, 255))


def _live_game(**extra):
    game = {
        "id": "401", "league": "mlb",
        "home_id": "1", "home_abbr": "HOM", "home_logo_path": "h.png", "home_logo_url": None,
        "away_id": "2", "away_abbr": "AWY", "away_logo_path": "a.png", "away_logo_url": None,
        "home_score": "3", "away_score": "2",
        "is_live": True, "is_final": False,
        "inning": 5, "inning_half": "bottom",
        "bases_occupied": [True, False, True], "outs": 2, "balls": 3, "strikes": 1,
        "has_count_data": True,
        "away_linescore": ["0", "1", "0", "1"], "home_linescore": ["2", "0", "1", "0"],
        "away_hits": "5", "home_hits": "7", "away_errors": "0", "home_errors": "1",
    }
    game.update(extra)
    return game


# --- the classic live scorebug and the traditional scoreboard --------------

def _make_live(width, height):
    from baseball import BaseballLive

    class _Live(BaseballLive):
        def _extract_game_details(self, game_event):
            return None

        def _fetch_data(self):
            return None

    class _DisplayManager:
        def __init__(self):
            self.image = Image.new("RGB", (width, height))
            self.font = ImageFont.load_default()
            self.calendar_font = None
            self.draw = None

        def get_text_width(self, text, font):
            return 4 * len(text)

        def _draw_bdf_text(self, text, x, y, color=(255, 255, 255), font=None):
            self.draw.rectangle((x, y, x + 4 * len(text), y + 6), fill=color)

        def update_display(self):
            pass

    live = object.__new__(_Live)
    live.display_width, live.display_height = width, height
    live.display_manager = _DisplayManager()
    live.config = {}
    live.favorite_teams = []
    live.last_count_log_time = 0.0
    live.count_log_interval = 10 ** 9
    live._count_font_face = object()
    font = ImageFont.load_default()
    live.fonts = {k: font for k in ("score", "time", "team", "status", "detail", "rank", "odds")}
    live._load_and_resize_logo = lambda *a, **k: _logo()
    live._load_custom_font_from_element_config = lambda cfg, default_size=6: font
    live._maybe_draw_at_bat_info_screen = lambda game, force_clear=False: False
    live._maybe_draw_player_card_screen = lambda game, force_clear=False: False
    live._maybe_draw_traditional_scoreboard_screen = lambda game, force_clear=False: False
    live.logger, live._errors = _logger("toggle_probe_live_%dx%d" % (width, height))
    return live


def _draw(method, width, height, game, **toggles):
    live = _make_live(width, height)
    for key, value in toggles.items():
        setattr(live, key, value)
    getattr(live, method)(game)
    return live.display_manager.image.copy(), live._errors.records


def test_classic_live_scorebug():
    print("classic live scorebug (BaseballLive._draw_scorebug_layout)")
    method = "_draw_scorebug_layout"
    base, errors = _draw(method, 128, 64, _live_game(), **dict.fromkeys(TOGGLES, True))
    check("draws without logging an error", not errors, errors)
    unset, _ = _draw(method, 128, 64, _live_game())
    check("unset toggles draw exactly what all-on draws", not differs(base, unset))
    for key in TOGGLES:
        off, errors = _draw(method, 128, 64, _live_game(), **{key: False})
        check("%s=False removes something from the panel" % key,
              differs(base, off) and not errors, errors)
    final = _live_game(is_final=True)
    shown, _ = _draw(method, 128, 64, final, show_innings=True)
    hidden, _ = _draw(method, 128, 64, final, show_innings=False)
    check("show_innings=False still shows FINAL", not differs(shown, hidden))
    no_count = _live_game(has_count_data=False)
    a, _ = _draw(method, 128, 64, no_count, show_count=True, show_outs=True)
    b, _ = _draw(method, 128, 64, no_count, show_count=False, show_outs=False)
    check("with no count data (NCAA) the count and outs toggles change nothing",
          not differs(a, b))


def test_traditional_scoreboard():
    print("\ntraditional scoreboard (BaseballLive._draw_traditional_scoreboard_screen)")
    method = "_draw_traditional_scoreboard_screen"
    game = _live_game()
    base, errors = _draw(method, 128, 64, game, **dict.fromkeys(TOGGLES, True))
    check("draws without logging an error", not errors, errors)
    check("the At Bat panel is on screen to begin with",
          has_color(base, (255, 140, 0)))
    singles = {}
    for key in ("show_count", "show_outs", "show_innings"):
        singles[key], _ = _draw(method, 128, 64, game, **{key: False})
        check("%s=False changes the screen" % key, differs(base, singles[key]))
    both, _ = _draw(method, 128, 64, game, show_count=False, show_outs=False)
    check("count and outs both off also drop the rest of the At Bat column",
          differs(both, singles["show_count"]) and differs(both, singles["show_outs"]))
    bases_off, _ = _draw(method, 128, 64, game, show_bases=False)
    check("show_bases=False changes nothing (this screen has no diamond)",
          not differs(base, bases_off))


# --- the scroll / Vegas card ------------------------------------------------

def _renderer(width, height, config):
    from game_renderer import GameRenderer
    log, errors = _logger("toggle_probe_renderer")
    renderer = GameRenderer(width, height, config, custom_logger=log)
    renderer._load_and_resize_logo = lambda league, abbr: _logo()
    return renderer, errors


def _card(game, game_type, width=128, height=64, config=None):
    renderer, errors = _renderer(width, height, config or {})
    return renderer.render_game_card(game, game_type), errors.records


def test_scroll_live_card():
    print("\nscroll/Vegas live card (GameRenderer._render_live_game)")
    game = _live_game()
    on = {"mlb": {"display_options": dict.fromkeys(TOGGLES, True)}}
    base, errors = _card(game, "live", config=on)
    check("renders without logging an error", not errors, errors)
    unset, _ = _card(game, "live", config={})
    check("no display_options draws exactly what all-on draws", not differs(base, unset))
    for key in TOGGLES:
        cfg = {"mlb": {"display_options": {key: False}}}
        off, errors = _card(game, "live", config=cfg)
        check("%s=False removes something from the card" % key,
              differs(base, off) and not errors, errors)
    other_league, _ = _card(game, "live", config={
        "milb": {"display_options": dict.fromkeys(TOGGLES, False)}})
    check("a different league's toggles do not touch this game",
          not differs(base, other_league))
    final = _live_game(is_final=True)
    shown, _ = _card(final, "live", config={"mlb": {"display_options": {"show_innings": True}}})
    hidden, _ = _card(final, "live", config={"mlb": {"display_options": {"show_innings": False}}})
    check("show_innings=False still shows FINAL", not differs(shown, hidden))


def test_scroll_recent_card_final_n():
    print("\nscroll/Vegas recent card: Final/N")
    renderer, _ = _renderer(128, 32, {})
    draw = ImageDraw.Draw(Image.new("RGB", (128, 32)))
    logo = _logo(20)
    wide = dict(away_logo=logo, away_x=0, home_logo=logo, home_x=108)

    def pick(game, **placement):
        spot = dict(wide, **placement)
        return renderer._final_status_text(draw, game, spot["away_logo"], spot["away_x"],
                                           spot["home_logo"], spot["home_x"])

    check("extra innings: Final/10", pick({"status_text": "Final/10"}) == "Final/10",
          pick({"status_text": "Final/10"}))
    check("MiLB doubleheader: Final/7", pick({"status_text": "Final/7"}) == "Final/7")
    check("a nine-inning game stays Final", pick({"status_text": "Final"}) == "Final")
    check("no status text: Final", pick({}) == "Final")
    check("no room between the logos: plain Final",
          pick({"status_text": "Final/10"}, home_x=20) == "Final",
          pick({"status_text": "Final/10"}, home_x=20))
    # A 40-wide away logo whose right 30 pixels are transparent, 90 pixels
    # from the home logo: 80 visible pixels of gap, but only 50 if the padding
    # counted. "Final/10" needs more than 50 and less than 80 in the time font.
    padded = Image.new("RGBA", (40, 20), (0, 0, 0, 0))
    padded.paste(Image.new("RGBA", (10, 20), (200, 0, 0, 255)), (0, 0))
    solid = Image.new("RGBA", (40, 20), (200, 0, 0, 255))
    width = draw.textlength("Final/10", font=renderer.fonts['time'])
    check("sanity: the probe gap brackets the text width", 50 < width <= 80, width)
    check("transparent logo padding does not count as occupied",
          pick({"status_text": "Final/10"}, away_logo=padded, home_x=90) == "Final/10",
          pick({"status_text": "Final/10"}, away_logo=padded, home_x=90))
    check("an opaque logo of the same size does",
          pick({"status_text": "Final/10"}, away_logo=solid, home_x=90) == "Final")

    game = {"league": "mlb", "home_abbr": "HOM", "away_abbr": "AWY",
            "home_score": "4", "away_score": "3", "is_final": True}
    plain, errors = _card(dict(game, status_text="Final"), "recent", 128, 32)
    extra, errors2 = _card(dict(game, status_text="Final/10"), "recent", 128, 32)
    check("the rendered card shows the extra-innings text",
          differs(plain, extra) and not errors and not errors2, errors + errors2)


def main():
    os.chdir(str(CORE))
    for test in (test_classic_live_scorebug, test_traditional_scoreboard,
                 test_scroll_live_card, test_scroll_recent_card_final_n):
        try:
            test()
        except Exception as exc:  # a crash is a failure, not a skip
            check("%s runs" % test.__name__, False, "%s: %s" % (type(exc).__name__, exc))
    failed = [c for c, ok in results if not ok]
    print("\n%d checks, %d failed" % (len(results), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
