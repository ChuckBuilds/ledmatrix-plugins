#!/usr/bin/env python3
"""
Regression test: a freshly enabled plugin loads and says what to set.

validate_config() returned False while the channel ID or API key was empty,
and the core puts a plugin that fails it in the ERROR state without loading
it -- so a new install showed nothing on the panel, only "configuration
validation failed" in the log. The setup message display() draws for that
case was also one line, 144 px wide in the 8 px font: clipped at both edges
of a 64- or 128-wide panel.

Run: LEDMATRIX_CORE=/path/to/LEDMatrix python plugins/youtube-stats/test_loads_before_setup.py
Exit 0 pass, 2 skip, 1 fail.
"""

import logging
import os
import socket
import sys
import types
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))

_core = os.environ.get("LEDMATRIX_CORE", "")
for _candidate in (_core, str(PLUGIN_DIR.parents[2] / "LEDMatrix")):
    if _candidate and (Path(_candidate) / "src" / "plugin_system").is_dir():
        sys.path.insert(0, _candidate)
        break
else:
    print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
    sys.exit(2)

try:
    from src.plugin_system.testing import (
        MockCacheManager, MockPluginManager, VisualTestDisplayManager,
    )
except ImportError as exc:
    print("SKIP: core imports unavailable (%s)" % exc)
    sys.exit(2)


def _no_network(*_args, **_kwargs):
    raise OSError("network disabled in this test")


socket.socket.connect = _no_network
logging.disable(logging.CRITICAL)
# The font is resolved relative to the core checkout, as on a Pi.
os.chdir(_candidate)

from manager import YouTubeStatsPlugin  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s%s" % (name, (": " + detail) if detail else ""))
        failures.append(name)


for config, label in (({"enabled": True}, "nothing set"),
                      ({"enabled": True, "api_key": "k"}, "key set, no channel")):  # nosec B105
    for width, height in ((64, 32), (128, 32)):
        display = VisualTestDisplayManager(width, height)
        display.matrix = types.SimpleNamespace(width=width, height=height)
        plugin = YouTubeStatsPlugin("youtube-stats", config, display,
                                    MockCacheManager(), MockPluginManager())
        check("%s, %dx%d: validate_config lets it load" % (label, width, height),
              plugin.validate_config() is True)
        plugin.update()  # records what is missing; no request is made
        plugin.display(force_clear=True)
        box = display.image.getbbox()
        check("%s, %dx%d: the setup message is drawn inside the panel" % (label, width, height),
              box is not None and box[0] > 0 and box[2] < width, "bbox %s" % (box,))

print("%d failed" % len(failures))
sys.exit(1 if failures else 0)
