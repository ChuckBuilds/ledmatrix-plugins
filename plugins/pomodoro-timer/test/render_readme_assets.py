"""Regenerate the images in ../assets/ that the README uses.

Every panel in those sheets is real plugin output: rendered through the core's
bounds-checking display manager at the true panel size, then scaled up with
nearest-neighbour so the pixels stay pixels. Nothing is a mockup, and nothing is
touched up afterwards — so if the display changes, rerun this rather than
editing the PNGs.

Needs a LEDMatrix (core) checkout for the harness:

    python plugins/pomodoro-timer/test/render_readme_assets.py --core /path/to/LEDMatrix

The core path also comes from $LEDMATRIX_CORE, and defaults to a sibling
checkout of this repo.
"""
import argparse
import os
import sys
from pathlib import Path

PDIR = Path(__file__).resolve().parent.parent
OUT = PDIR / "assets"

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--core", default=os.environ.get("LEDMATRIX_CORE"),
                    help="path to a LEDMatrix (core) checkout")
args = parser.parse_args()
core = Path(args.core) if args.core else PDIR.parents[1].parent / "LEDMatrix"
if not (core / "src" / "plugin_system").is_dir():
    sys.exit(f"no LEDMatrix core checkout at {core} — pass --core")

sys.path.insert(0, str(core))
os.environ["EMULATOR"] = "true"

from PIL import Image, ImageDraw, ImageFont  # noqa: E402
from src.plugin_system.testing.loading import load_manifest  # noqa: E402
from src.plugin_system.testing.harness import (  # noqa: E402
    _instantiate, load_config_defaults)
from src.plugin_system.testing.bounds_display_manager import (  # noqa: E402
    BoundsCheckingDisplayManager)

OUT.mkdir(parents=True, exist_ok=True)
MANIFEST = load_manifest(PDIR)
BASE = {"enabled": True, **load_config_defaults(PDIR)}
# The pip for the session you are in blinks once a second; hold it lit so the
# sheets come out the same every run.
BASE["pulse_active_pip"] = False

FONT_DIRS = ["/usr/share/fonts/truetype/dejavu", "/Library/Fonts",
             "/usr/share/fonts/TTF"]


def _font(name: str, size: int):
    for directory in FONT_DIRS:
        path = Path(directory) / name
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


F_NAME = _font("DejaVuSans-Bold.ttf", 15)
F_CAPTION = _font("DejaVuSans.ttf", 13)

CARD = (18, 18, 22)
FG = (228, 228, 234)
DIM = (146, 146, 158)
EDGE = (58, 58, 68)
PAD = 24


def render(width: int, height: int, setup=None, burn: float = 0.4, **overrides):
    """One frame of the plugin at a real panel size, with the phase `burn` of
    the way through so the burndown indicator has something to show."""
    display = BoundsCheckingDisplayManager(width=width, height=height,
                                           overflow_extent=(width, height))
    plugin = _instantiate("pomodoro-timer", MANIFEST, PDIR,
                          {**BASE, **overrides}, {}, display)
    if setup:
        setup(plugin)
    with plugin.state_lock:
        if plugin.deadline is not None:
            plugin.deadline -= plugin.phase_total * burn
        else:
            plugin.remaining = max(1.0, plugin.remaining - plugin.phase_total * burn)
    plugin.display()
    assert display.check_overflow() is None, f"overflow at {width}x{height}"
    return display.get_image()


def scaled(image, factor: int):
    return image.resize((image.width * factor, image.height * factor), Image.NEAREST)


def paste_panel(sheet, image, x: int, y: int) -> None:
    """Drop a panel onto the card inside a hairline edge — the panel background
    is black and the card is nearly black, so it needs the outline to read."""
    ImageDraw.Draw(sheet).rectangle(
        [x - 1, y - 1, x + image.width, y + image.height], outline=EDGE)
    sheet.paste(image, (x, y))


def save(sheet, path: Path) -> None:
    """Write the sheet, dropping to a palette when the whole card fits in 256
    colours — these are flat-colour images, so that is lossless and roughly
    halves the file."""
    colours = sheet.getcolors(1 << 24)
    if colours and len(colours) <= 256:
        sheet = sheet.quantize(colors=len(colours), method=Image.MEDIANCUT)
    sheet.save(path, optimize=True)
    print(path.name, f"{path.stat().st_size // 1024}K")


def caption(draw, x: int, y: int, name: str, text: str, width: int) -> int:
    """Name with its one-line explanation under it, both asserted to fit inside
    the column so a longer caption can't silently run into the next one."""
    for font, string, colour, dy in ((F_NAME, name, FG, 0),
                                     (F_CAPTION, text, DIM, 20)):
        assert draw.textlength(string, font=font) <= width, f"{string!r} overflows"
        draw.text((x, y + dy), string, font=font, fill=colour)
    return 42


# ── The states worth showing ───────────────────────────────────────────────────

def command(cmd: str, payload=None):
    return lambda plugin: plugin._apply_command(cmd, payload or {})


def paused(plugin) -> None:
    plugin._apply_command("START", {})
    plugin._apply_command("PAUSE", {})


def long_break(plugin) -> None:
    with plugin.state_lock:
        plugin.completed_sessions, plugin.cycle_position = 3, 3
    plugin._apply_command("LONG_BREAK", {})


def working_on(task: str, position: int = 2):
    def setup(plugin) -> None:
        plugin._apply_command("START", {})
        with plugin.state_lock:
            plugin.task = task
            plugin.completed_sessions = plugin.cycle_position = position
    return setup


WORK = working_on("WRITE SPEC")


def grid(path: Path, cells, scale: int = 3, panel=(128, 32), columns: int = 2) -> None:
    """A card of captioned panels, laid out left to right, top to bottom."""
    pw, ph = panel[0] * scale, panel[1] * scale
    gap_x, cell_h = 28, ph + 42 + 30
    rows = -(-len(cells) // columns)
    sheet = Image.new("RGB", (PAD * 2 + pw * columns + gap_x * (columns - 1),
                              PAD * 2 + rows * cell_h - 30), CARD)
    draw = ImageDraw.Draw(sheet)
    for index, (name, text, setup, burn, extra) in enumerate(cells):
        x = PAD + (index % columns) * (pw + gap_x)
        y = PAD + (index // columns) * cell_h
        y += caption(draw, x, y, name, text, pw)
        paste_panel(sheet, scaled(render(*panel, setup, burn, **extra), scale), x, y)
    save(sheet, path)


def main() -> None:
    # The hero: a work session on a 128x64 panel.
    image = scaled(render(128, 64, WORK), 6)
    sheet = Image.new("RGB", (image.width + PAD * 2, image.height + PAD * 2), CARD)
    paste_panel(sheet, image, PAD, PAD)
    save(sheet, OUT / "hero.png")

    grid(OUT / "phases.png", [
        ("Idle", "nothing running — the next work length, in full", None, 0.0, {}),
        ("Work", "a focus session, part-way through", command("START"), 0.4, {}),
        ("Paused", "held where it was; the ring stops draining", paused, 0.4, {}),
        ("Short break", "the breather between sessions",
         command("SHORT_BREAK"), 0.4, {}),
        ("Long break", "three sessions banked, one to go", long_break, 0.4, {}),
        ("With a task", "a task name takes the label row", WORK, 0.4, {}),
    ])

    grid(OUT / "options.png", [
        ("Burndown: perimeter", "the default — a ring that drains clockwise",
         WORK, 0.4, {"progress_style": "perimeter"}),
        ("Burndown: bar", "an emptying bar along the bottom edge",
         WORK, 0.4, {"progress_style": "bar"}),
        ("Burndown: segments", "blocks that go out one at a time",
         WORK, 0.4, {"progress_style": "segments"}),
        ("Burndown: none", "no indicator at all",
         WORK, 0.4, {"progress_style": "none"}),
        ("Unlit segments on", "the clock-radio look, at some cost to legibility",
         WORK, 0.4, {"show_ghost_segments": True}),
        ("Pixel digits", "the display font instead of drawn segments",
         WORK, 0.4, {"digit_style": "pixel"}),
        ("Calm theme", "warm terracotta, sage and soft indigo",
         WORK, 0.4, {"color_theme": "calm"}),
        ("Paused: desaturate", "the phase's own hue drained, instead of amber",
         paused, 0.4, {"paused_style": "desaturate"}),
    ])

    # One work session on every panel size, all at the same scale, so the sheet
    # shows how much room each shape really has.
    scale = 3
    tiles = [(f"{w}×{h}", scaled(render(w, h, WORK), scale))
             for w, h in ((64, 32), (128, 32), (128, 64), (256, 32))]
    sheet = Image.new(
        "RGB", (PAD * 2 + max(i.width for _, i in tiles),
                PAD * 2 + sum(i.height + 40 for _, i in tiles) - 18), CARD)
    draw = ImageDraw.Draw(sheet)
    y = PAD
    for label, image in tiles:
        draw.text((PAD, y), label, font=F_NAME, fill=DIM)
        y += 22
        paste_panel(sheet, image, PAD, y)
        y += image.height + 18
    save(sheet, OUT / "sizes.png")


if __name__ == "__main__":
    main()
