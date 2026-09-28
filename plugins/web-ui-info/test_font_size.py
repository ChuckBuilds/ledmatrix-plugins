#!/usr/bin/env python3
"""On a Pi the address must render in the same font size as every preview.

A Pi installs the plugin at <core>/plugin-repos/web-ui-info, so the loader's
first branch finds <core>/assets/fonts/4x6-font.ttf and used to load it at
size 6. The test harness runs from this monorepo, misses that path, and falls
through to the size-7 branch -- so the goldens showed 7 while the panel drew
a size at which the 4x6 face is not crisp (it is crisp at multiples of 7).

This rebuilds the Pi layout in a temp directory and checks the loaded size.

Run with the core on PYTHONPATH:
    PYTHONPATH=/path/to/LEDMatrix python test_font_size.py
Exit 0 pass, 1 fail, 2 skip.
"""
import importlib.util
import logging
import os
import shutil
import sys
import tempfile
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent

try:
    from src.plugin_system.testing.mocks import (
        MockCacheManager, MockDisplayManager, MockPluginManager)
except ImportError as exc:
    print("SKIP: %s" % exc)
    sys.exit(2)

core_font = next((Path(p) / "assets" / "fonts" / "4x6-font.ttf" for p in sys.path
                  if (Path(p or ".") / "assets" / "fonts" / "4x6-font.ttf").is_file()), None)
if core_font is None:
    print("SKIP: no core checkout with assets/fonts/4x6-font.ttf on PYTHONPATH")
    sys.exit(2)

with tempfile.TemporaryDirectory() as root:
    fonts = Path(root) / "assets" / "fonts"
    fonts.mkdir(parents=True)
    shutil.copy(core_font, fonts / core_font.name)
    plugin_dir = Path(root) / "plugin-repos" / "web-ui-info"
    plugin_dir.mkdir(parents=True)
    shutil.copy(HERE / "manager.py", plugin_dir / "manager.py")

    # Run from a directory with no assets/, so the font can only come from
    # the Pi-layout branch.
    os.chdir(root + "/plugin-repos")
    spec = importlib.util.spec_from_file_location("web_ui_info_probe", plugin_dir / "manager.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    display = MockDisplayManager(128, 32)
    display.matrix = types.SimpleNamespace(width=128, height=32)
    plugin = module.WebUIInfoPlugin(
        "web-ui-info", {"enabled": True}, display,
        MockCacheManager(), MockPluginManager())
    plugin.logger = logging.getLogger("test-web-ui-info")
    plugin.display()
    size = getattr(getattr(plugin, "_font_small", None), "size", None)
    os.chdir(HERE)

ok = size == 7
print("%s the Pi install loads 4x6-font at size 7 (got %s)" % ("PASS" if ok else "FAIL", size))
sys.exit(0 if ok else 1)
