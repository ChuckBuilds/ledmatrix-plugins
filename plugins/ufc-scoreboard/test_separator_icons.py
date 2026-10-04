#!/usr/bin/env python3
"""Separator icon: the one this plugin ships loads, wherever the cwd is.

The loader only looked for assets/sports/ufc_logos/UFC.png relative to the
working directory -- the core install root on a Pi -- and the core has never
shipped that file. The plugin has always shipped its own copy next to this
script, so every install logged a warning on every load of the scroll display
and the Vegas ticker ran UFC's fights with no separator.

Builds the real ScrollDisplayManager from a scratch working directory, so the
result does not depend on what a core checkout has under assets/, and records
what it logs. Needs a core with src.common.sports_font_path (fight_renderer
imports it): LEDMATRIX_CORE, the working directory, or ../LEDMatrix next to
this repo; exits 2 without one.

Run: <core-venv>/bin/python plugins/ufc-scoreboard/test_separator_icons.py
"""

import logging
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

PLUGIN_DIR = Path(__file__).resolve().parent
CORE_ICON = Path("assets", "sports", "ufc_logos", "UFC.png")
BUNDLED_ICON = PLUGIN_DIR / CORE_ICON
#: Panel heights to build at: the separator is display_height - 4 tall.
HEIGHTS = (32, 64)


def core_checkout():
    for candidate in (os.environ.get("LEDMATRIX_CORE", ""), os.getcwd(),
                      str(PLUGIN_DIR.parents[2] / "LEDMatrix")):
        if candidate and (Path(candidate) / "src" / "common" / "sports_font_path.py").is_file():
            return Path(candidate)
    return None


class _Records(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)


def build(mod, height):
    """A ScrollDisplayManager at 128 x height, and what it logged."""
    logger = logging.getLogger("test_separator_icons.%d.%d" % (height, id(mod)))
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    handler = _Records()
    logger.handlers = [handler]
    display = SimpleNamespace(matrix=None, width=128, height=height)
    manager = mod.ScrollDisplayManager(display, {}, custom_logger=logger)
    warned = [r.getMessage() for r in handler.records
              if r.levelno >= logging.WARNING and "separator" in r.getMessage().lower()]
    return manager, warned


def main():
    core = core_checkout()
    if core is None:
        print("SKIP: no LEDMatrix core checkout with src.common.sports_font_path")
        return 2
    sys.path.insert(0, str(PLUGIN_DIR))
    sys.path.insert(1, str(core))

    import scroll_display as mod

    failures = []

    def check(name, cond, detail=""):
        print(("  PASS  " if cond else "  FAIL  ") + name
              + ("" if cond or not detail else ": " + detail))
        if not cond:
            failures.append(name)

    with Image.open(BUNDLED_ICON) as bundled:
        check("the bundled icon is a square RGBA PNG", bundled.mode == "RGBA"
              and bundled.width == bundled.height, "%s %s" % (bundled.mode, bundled.size))

    original_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as scratch:
        try:
            os.chdir(scratch)

            print("bundled icon, from a working directory with no assets/")
            for height in HEIGHTS:
                manager, warned = build(mod, height)
                icon = manager._separator_icons.get("ufc")
                check("%dpx panel: ufc separator loads" % height, icon is not None,
                      "not in %s" % sorted(manager._separator_icons))
                if icon is not None:
                    check("%dpx panel: separator is %dx%d" % (height, height - 4, height - 4),
                          icon.size == (height - 4, height - 4), "got %s" % (icon.size,))
                check("%dpx panel: nothing about separators logged above debug" % height,
                      not warned, repr(warned))

            print("a file at the core path overrides it")
            (Path(scratch) / CORE_ICON).parent.mkdir(parents=True)
            Image.new("RGBA", (40, 20), (0, 0, 255, 255)).save(Path(scratch) / CORE_ICON)
            manager, warned = build(mod, 32)
            icon = manager._separator_icons.get("ufc")
            check("override is the one loaded (2:1, so 56x28)",
                  icon is not None and icon.size == (56, 28),
                  "got %s" % (icon.size if icon is not None else None,))
            check("override: nothing about separators logged above debug",
                  not warned, repr(warned))
            (Path(scratch) / CORE_ICON).unlink()

            print("neither file present")
            cls = mod.ScrollDisplayManager
            original = cls.__dict__.get("BUNDLED_SEPARATOR_ICON")
            cls.BUNDLED_SEPARATOR_ICON = str(Path(scratch) / "missing.png")
            try:
                manager, warned = build(mod, 32)
            finally:
                if original is None:
                    del cls.BUNDLED_SEPARATOR_ICON
                else:
                    cls.BUNDLED_SEPARATOR_ICON = original
            check("no ufc separator", "ufc" not in manager._separator_icons)
            check("skipped quietly: nothing about separators logged above debug",
                  not warned, repr(warned))
        finally:
            os.chdir(original_cwd)

    if failures:
        print("\n%d failure(s)" % len(failures))
        return 1
    print("\nall passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
