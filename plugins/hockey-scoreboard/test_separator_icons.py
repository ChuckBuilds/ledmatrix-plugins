#!/usr/bin/env python3
"""Separator icons: the ones the core ships load, the rest are skipped quietly.

The NCAA hockey separators named an ncaa_hockey.png the core has never
shipped; its NCAA hockey badge is ncaah.png. College slates scrolled
with no separator, and nothing logged it.

Builds the real ScrollDisplay with the working directory at a core checkout
(the icon paths are relative to it) and records what it logs. Needs a core
with src.common.sports_scroll (LEDMATRIX_CORE, the working directory, or
../LEDMatrix next to this repo); exits 2 without one.

Run: <core-venv>/bin/python plugins/hockey-scoreboard/test_separator_icons.py
"""

import logging
import os
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent

#: League keys that must get a separator: the core ships their icon.
LOADED = {"nhl", "ncaam_hockey", "ncaa_mens", "ncaaw_hockey", "ncaa_womens"}
#: League keys whose icon the core does not ship: no separator, no warning.
SKIPPED = {"ncaa"}


def core_checkout():
    for candidate in (os.environ.get("LEDMATRIX_CORE", ""), os.getcwd(),
                      str(PLUGIN_DIR.parents[2] / "LEDMatrix")):
        if candidate and (Path(candidate) / "src" / "common" / "sports_scroll.py").is_file():
            return Path(candidate)
    return None


class _Records(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)


def main():
    core = core_checkout()
    if core is None:
        print("SKIP: no LEDMatrix core checkout with src.common.sports_scroll")
        return 2
    sys.path.insert(0, str(PLUGIN_DIR))
    sys.path.insert(1, str(core))
    os.chdir(core)

    import test_core_scroll as helpers  # the constructor stubs live there

    logger = logging.getLogger("test_separator_icons")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    handler = _Records()
    logger.addHandler(handler)

    mod = helpers._fresh_scroll_display()
    kwargs = helpers._args_for(mod.ScrollDisplay)
    for name in ("custom_logger", "logger"):
        if name in kwargs:
            kwargs[name] = logger
    display = mod.ScrollDisplay(**kwargs)
    icons = display._separator_icons
    height = display.display_height - 4

    failures = []

    def check(name, cond, detail=""):
        print(("  PASS  " if cond else "  FAIL  ") + name
              + ("" if cond or not detail else ": " + detail))
        if not cond:
            failures.append(name)

    print("separator icons against %s" % core)
    for key in sorted(LOADED):
        icon = icons.get(key)
        check("%s separator loads" % key, icon is not None,
              "not in %s" % sorted(icons))
        if icon is not None:
            check("%s separator is %dpx tall" % (key, height), icon.height == height,
                  "got %d" % icon.height)
    for key in sorted(SKIPPED):
        check("%s has no separator" % key, key not in icons)
    warned = [r.getMessage() for r in handler.records
              if r.levelno >= logging.WARNING and "separator" in r.getMessage().lower()]
    check("nothing about separators is logged above debug", not warned, repr(warned))

    if failures:
        print("\n%d failure(s)" % len(failures))
        return 1
    print("\nall passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
