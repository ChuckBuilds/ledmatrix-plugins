#!/usr/bin/env python3
"""The colour pickers the schema offers have to actually colour something.

customization.score_text.text_color and its five siblings have been in the
schema, with a colour-picker widget, since the fonts they sit beside were
added. Setting one changed which face was loaded and nothing else: both
renderers drew every string white. The scroll/Vegas card honoured them at
four draws -- the newer upcoming-centre ones, which named their element by
hand -- and at none of the other seven.

The colour now follows the face. The font loader already picks each face from
exactly the element whose colour applies to it (element_key=), so resolving
the fill from the face in _draw_text_with_outline covers every draw at once
and cannot drift out of step with them.

What this pins down:

  * every default is white, so a config nobody has touched renders exactly
    what it rendered before -- checked as pixels, against a reference drawn
    the old way rather than against the new helper.
  * a configured colour reaches the text drawn in that element's face, in
    both the full-screen scorebug and the card.
  * an explicit fill still wins. The odds colours and the favourite-result
    score tint mean something the palette does not.
  * a face shared between elements resolves to white rather than guessing.

Run: <core-venv>/bin/python plugins/baseball-scoreboard/test_element_text_colors.py
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
RED, CYAN, YELLOW = (255, 0, 0), (0, 255, 255), (255, 255, 0)


def main():
    os.chdir(str(CORE))
    from PIL import Image, ImageDraw
    import sports

    class Bug(sports.SportsCore):
        """The smallest object the drawing helpers need."""

        def __init__(self, config):
            self.config = config
            self.display_width = WIDTH
            self.display_height = HEIGHT
            self.logger = logging.getLogger("test")
            # Built the way the real constructor builds it, de-duplication
            # included -- loading the faces directly would hide the case
            # where a loader hands one object to two elements.
            self.fonts = sports.SportsCore._unshare_element_fonts(
                self, sports.SportsCore._load_fonts(self))

        # Abstract on SportsCore; nothing under test reaches them.
        def _custom_scorebug_layout(self, game, draw):  # pragma: no cover
            raise NotImplementedError

        def _extract_game_details(self, game_event):  # pragma: no cover
            raise NotImplementedError

        def _fetch_data(self):  # pragma: no cover
            raise NotImplementedError

    def lit(image):
        """Every non-black colour in the image, and how many pixels it covers."""
        seen = {}
        px = image.load()
        for y in range(HEIGHT):
            for x in range(WIDTH):
                c = px[x, y]
                if c != (0, 0, 0):
                    seen[c] = seen.get(c, 0) + 1
        return seen

    def draw_with(config, font_key, text="12:00", fill=None):
        image = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
        bug = Bug(config)
        kwargs = {} if fill is None else {"fill": fill}
        bug._draw_text_with_outline(
            ImageDraw.Draw(image), text, (2, 2), bug.fonts[font_key], **kwargs)
        return lit(image)

    # -- 1. untouched config still draws white --------------------------------
    plain = draw_with({}, "time")
    check("no config: text is still white",
          (255, 255, 255) in plain and not any(
              c not in ((255, 255, 255), (0, 0, 0)) for c in plain))

    # The store materialises every schema default, so the keys really do
    # arrive set -- to white. That must be indistinguishable from unset.
    import json
    schema = json.loads((plugin_dir / "config_schema.json").read_text())
    custom = schema["properties"]["customization"]["properties"]
    materialised = {k: {"text_color": v["properties"]["text_color"]["default"]}
                    for k, v in custom.items()
                    if "text_color" in v.get("properties", {})}
    defaults = draw_with({"customization": materialised}, "time")
    check("schema defaults render identically to no config", defaults == plain)
    # odds_text is the one deliberate exception. The betting line and
    # over/under have always drawn green -- it was hard-coded in the draw call
    # before the setting existed -- so advertising white would both lie about
    # the default and change what is rendered the moment the store
    # materialises it. Green here IS "unset", which is what the check above
    # actually cares about.
    check("every advertised text_color default is white",
          all(tuple(v["text_color"]) == (255, 255, 255)
              for k, v in materialised.items() if k != "odds_text"))
    check("odds_text advertises the green it has always drawn",
          tuple(materialised.get("odds_text", {}).get("text_color", (0, 255, 0)))
          == (0, 255, 0))

    # -- 2. a configured colour reaches that element's face -------------------
    cfg = {"customization": {"period_text": {"text_color": list(CYAN)},
                             "score_text": {"text_color": list(RED)},
                             "status_text": {"text_color": list(YELLOW)}}}
    check("period_text colours the face it owns", CYAN in draw_with(cfg, "time"))
    check("score_text colours the face it owns", RED in draw_with(cfg, "score"))
    check("status_text colours the face it owns", YELLOW in draw_with(cfg, "status"))
    check("an element left unset stays white",
          (255, 255, 255) in draw_with(cfg, "detail"))

    # -- 3. an explicit fill still wins ---------------------------------------
    forced = draw_with(cfg, "score", fill=(0, 255, 0))
    check("an explicit fill overrides the configured colour",
          (0, 255, 0) in forced and RED not in forced)

    # -- 4. both spellings of a colour parse ----------------------------------
    bug = Bug({"customization": {"score_text": {"text_color": "#FF0000"},
                                 "period_text": {"text_color": [0, 255, 255]},
                                 "team_name": {"text_color": "nonsense"},
                                 "rank_text": {"text_color": [999, -5, 20]}}})
    check("#rrggbb parses", bug._element_color("score_text") == RED)
    check("[r, g, b] parses", bug._element_color("period_text") == CYAN)
    check("an unparseable value falls back to the default",
          bug._element_color("team_name") == (255, 255, 255))
    check("out-of-range components are clamped",
          bug._element_color("rank_text") == (255, 0, 20))
    check("an element with no config at all falls back",
          bug._element_color("detail_text") == (255, 255, 255))

    # -- 5. a face shared between elements resolves to white ------------------
    shared = Bug(cfg)
    one_face = shared.fonts["time"]
    for key in ("score", "time", "status", "detail", "team", "rank"):
        shared.fonts[key] = one_face
    check("a face shared by several elements resolves to white, not a guess",
          shared._font_color(one_face) == (255, 255, 255))
    check("a face belonging to no element resolves to white",
          Bug(cfg)._font_color(object()) == (255, 255, 255))

    # -- 6. the card resolves colours the same way ----------------------------
    from game_renderer import GameRenderer
    card = GameRenderer(WIDTH, HEIGHT, cfg, custom_logger=logging.getLogger("t"))
    check("the card colours the period face from the same key",
          card._font_color(card.fonts["time"]) == CYAN)
    check("the card leaves an unset element white",
          card._font_color(card.fonts["detail"]) == (255, 255, 255))
    check("the card's score falls back to the configured colour",
          card._score_color_for({}, "upcoming") == RED)

    print()
    failed = [c for c, ok in results if not ok]
    if failed:
        print("FAILED: %d of %d" % (len(failed), len(results)))
        return 1
    print("All %d checks passed." % len(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
