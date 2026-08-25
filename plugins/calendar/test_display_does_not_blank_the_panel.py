#!/usr/bin/env python3
"""Rendering a frame must not blank the panel first.

Reported as the calendar "flashing/pulsing the event", and specific to this
plugin. It was not the display: _display_event() called
display_manager.clear() on every call, and the display controller calls
display() in a `while True:` loop. clear() does not merely reset the
in-memory buffer -- it calls Clear() on the offscreen AND current canvases,
writing black straight to the matrix. So every frame ran

    black panel -> render -> push -> black panel -> render -> push

which reads as a pulse at the render rate. The plugin already honoured the
contract at the top of display() ("if force_clear: clear()"), and the
controller passes force_clear=False in the steady state, so the guarded
clear correctly did nothing -- and then the unguarded one ran anyway.

Composing on a fresh in-memory image instead leaves the previous frame on
the panel until update_display() swaps the finished one in. It also restores
the core's dirty-frame tracking, which clear() defeats by resetting
_last_pushed_digest, forcing a full push every tick even when the pixels are
identical.

Run: <core-venv>/bin/python plugins/calendar/test_display_does_not_blank_the_panel.py
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


def main():
    os.chdir(str(CORE))
    from PIL import Image, ImageDraw
    import manager as cal

    calls = {"clear": 0, "update": 0}

    class FakeDM:
        """Counts the calls that reach the panel."""
        width, height = 128, 32

        def __init__(self):
            self.image = Image.new("RGB", (self.width, self.height))
            self.draw = ImageDraw.Draw(self.image)
            self.matrix = type("M", (), {"width": self.width, "height": self.height})()

        def clear(self):
            calls["clear"] += 1
            self.image = Image.new("RGB", (self.width, self.height))
            self.draw = ImageDraw.Draw(self.image)

        def update_display(self):
            calls["update"] += 1

        def get_text_width(self, text, font=None):
            return len(text) * 6

        def get_font_height(self, font=None):
            return 8

    plugin = cal.CalendarPlugin.__new__(cal.CalendarPlugin)
    plugin.display_manager = FakeDM()
    plugin.logger = logging.getLogger("test")
    plugin.datetime_font = None
    plugin.title_font = None
    plugin._load_fonts = lambda: None
    plugin.events = []

    print("the no-events frame does not blank the panel")
    calls["clear"] = calls["update"] = 0
    plugin._display_no_events()
    check("no clear() reached the panel (%d)" % calls["clear"], calls["clear"] == 0)
    check("the frame was still pushed (%d)" % calls["update"], calls["update"] == 1)

    print("\nthe error frame does not blank the panel")
    calls["clear"] = calls["update"] = 0
    plugin._display_error()
    check("no clear() reached the panel (%d)" % calls["clear"], calls["clear"] == 0)
    check("the frame was still pushed (%d)" % calls["update"], calls["update"] == 1)

    print("\nrepeated frames never blank the panel")
    # The actual report: display() runs in a loop, so one clear() per call is
    # one black frame per render tick.
    plugin.events = []
    calls["clear"] = calls["update"] = 0
    for _ in range(5):
        plugin.display(force_clear=False)
    check("five renders, zero clears (%d)" % calls["clear"], calls["clear"] == 0)
    check("five renders, five pushes (%d)" % calls["update"], calls["update"] == 5)

    print("\nforce_clear is still honoured")
    # A real mode change SHOULD blank: that is the one time the panel holding
    # the previous plugin's frame would be wrong.
    calls["clear"] = calls["update"] = 0
    plugin.display(force_clear=True)
    check("force_clear=True clears once (%d)" % calls["clear"], calls["clear"] == 1)

    failed = [c for c, ok in results if not ok]
    print("\n%d checks, %d failed" % (len(results), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
