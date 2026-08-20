#!/usr/bin/env python3
"""Green odds labels must not overprint the time in the middle of the card.

Both odds labels are anchored to the edges of the top row, and the card centres
its time text on that same row. On a full-width panel there is room for all
three. On a Vegas game card there is not: six of these plugins pin the card to
128px regardless of panel width (`game_card_width: 128`), and at that size
"O/U: 60.5" runs from x=0 to x=54 while "8:00 PM" occupies 36..92 -- an 18px
overprint that leaves both unreadable.

Reproduced on a 512x64 rig by rendering the same upcoming game at both widths
with the rig's own config. The full-width render was clean; the 128px card was
not. Nothing was wrong with the odds themselves -- the spread value and the
favoured side were verified correct against ten live ESPN games.

Whether it bites depends on the configured font, which is why it survived: with
the default 4x6 detail font "O/U: 60.5" is 30px against a 32px budget and fits
by two pixels. The rig configures PressStart2P, which makes it 54px.

Each renderer now budgets a side against the widest time string the centre can
hold, measured in the font it will actually use, and drops the O/U -- the
longer and less useful of the two -- when it will not fit.

Run: <core-venv>/bin/python scripts/test_odds_centre_collision.py
"""

import importlib.util
import inspect
import logging
import sys
from pathlib import Path

from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parent.parent
failures = []

# The card width these plugins pin, and a full panel for the control case.
CARD_WIDTH = 128
PANEL_WIDTH = 512

ODDS = {
    "details": "X -38.5", "over_under": 60.5, "spread": -38.5,
    "home_team_odds": {"money_line": None, "spread_odds": None},
    "away_team_odds": {"money_line": None, "spread_odds": None},
}

# A wide detail font is what exposes the collision; PressStart2P is what the
# rig that hit this has configured.
CFG = {"customization": {"detail_text": {"font": "PressStart2P-Regular.ttf",
                                         "font_size": 6},
                         "time": {}}}


def check(label, ok):
    print(("  PASS  " if ok else "  FAIL  ") + label)
    if not ok:
        failures.append(label)


def _core():
    for candidate in (Path("/home/rackpi/projects/LEDMatrix"),
                      REPO.parent / "LEDMatrix"):
        if (candidate / "src" / "common" / "__init__.py").exists():
            return str(candidate)
    return ""


def load_renderer(plugin_dir):
    """Import one plugin's game_renderer, isolated from the previous one's.

    Every plugin ships its own game_renderer.py, so a module cached from the
    last plugin would be handed to the next -- the same collision the core
    solves with per-plugin namespace isolation. Same approach as
    scripts/test_schedule_window_plumbing.py: drop anything previously imported
    out of a plugin directory and keep only this plugin on the path.

    In-process rather than a subprocess per plugin: it is faster, and it does
    not hand a built command line to subprocess, which the static analysis
    flags on sight.
    """
    plugins_root = str(REPO / "plugins")
    for name, module in list(sys.modules.items()):
        origin = getattr(module, "__file__", None) or ""
        if origin.startswith(plugins_root):
            del sys.modules[name]
    sys.path[:] = [q for q in sys.path if not q.startswith(plugins_root)]
    for path in (str(plugin_dir), _core()):
        if path and path not in sys.path:
            sys.path.insert(0, path)
    spec = importlib.util.spec_from_file_location(
        f"gr_{plugin_dir.name.replace('-', '_')}",
        plugin_dir / "game_renderer.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.GameRenderer


def probe(plugin_dir):
    """Green-pixel counts for one plugin's odds, at card and panel width."""
    renderer_cls = load_renderer(plugin_dir)
    out = {}
    for width in (CARD_WIDTH, PANEL_WIDTH):
        renderer = renderer_cls(width, 64, CFG, {}, logging.getLogger("probe"))
        renderer.display_width = width
        img = Image.new("RGB", (width, 64))
        draw = ImageDraw.Draw(img)

        # Dispatch on parameter NAMES, not count: baseball's fourth parameter
        # is `top_span`, not `height`, and passing the width into it draws
        # nothing at all -- which reads as a defect when it is only a bad call.
        params = inspect.signature(renderer._draw_dynamic_odds).parameters
        kwargs = {}
        if "width" in params:
            kwargs["width"] = width
        if "height" in params:
            kwargs["height"] = 64
        renderer._draw_dynamic_odds(draw, ODDS, **kwargs)

        px = img.load()
        time_font = renderer.fonts.get("time", renderer.fonts["detail"])
        reserve = draw.textlength("12:00 PM", font=time_font)
        c0, c1 = int((width - reserve) / 2), int((width + reserve) / 2)

        def green(xs, pixels=px):
            return sum(1 for y in range(64) for x in xs
                       if pixels[x, y][1] > 150 and pixels[x, y][0] < 100
                       and pixels[x, y][2] < 100)

        out[width] = {"total": green(range(width)),
                      "centre": green(range(c0, c1 + 1))}
    return out


def main():
    if not _core():
        print("  SKIP  no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
        return 0

    print("no odds label may intrude on the centre of the row")
    renderers = sorted((REPO / "plugins").glob("*/game_renderer.py"))
    check(f"{len(renderers)} game renderers found", len(renderers) >= 6)

    for path in renderers:
        plugin = path.parent.name
        source = path.read_text(encoding="utf-8")
        if "_draw_dynamic_odds" not in source:
            continue
        if "_odds_would_hit_top_row" in source:
            # baseball-scoreboard already solves this, and better: rather than
            # dropping a label it measures the card's own top-row text and
            # steps the odds down a row when they would collide, keeping both.
            # Its answer puts the labels in the same columns, so the
            # column-based check below would fail a correct implementation.
            print(f"  SKIP  {plugin}: solves this by stepping down a row, not "
                  "by dropping a label")
            continue
        try:
            res = probe(path.parent)
        except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-except
            check(f"{plugin}: renders odds", False)
            print(f"        {type(exc).__name__}: {exc}")
            continue
        card, panel = res[CARD_WIDTH], res[PANEL_WIDTH]
        check(f"{plugin}: nothing green in the centre of a {CARD_WIDTH}px card "
              f"({card['centre']}px there)", card["centre"] == 0)
        check(f"{plugin}: a {CARD_WIDTH}px card still shows the spread "
              f"({card['total']}px green)", card["total"] > 0)
        check(f"{plugin}: a {PANEL_WIDTH}px panel still shows both labels "
              f"({panel['total']}px green)", panel["total"] > card["total"])

    print("\n%s" % ("FAILED: %d" % len(failures) if failures
                    else "All checks passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
