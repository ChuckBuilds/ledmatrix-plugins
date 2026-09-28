#!/usr/bin/env python3
"""The fonts the schema configures are the fonts the scorebug draws with.

config_schema.json declares customization fonts as repo-relative paths
("assets/fonts/tom-thumb.bdf", "assets/fonts/4x6-font.ttf"), which is how
fight_renderer reads them. SportsCore._load_custom_font_from_element_config
read the same keys as bare filenames and joined them onto assets/fonts, so it
looked for "assets/fonts/assets/fonts/tom-thumb.bdf", logged "Font file not
found", and drew fighter names, odds and records in PressStart2P instead.

Runs from a temporary directory so a cwd-relative path cannot pass by luck.

Run: LEDMATRIX_CORE=<core> <core-venv>/bin/python plugins/ufc-scoreboard/test_configured_font_paths_load.py
"""

import json
import logging
import os
import sys
import tempfile
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))
_core = os.environ.get("LEDMATRIX_CORE", "")
for _candidate in (_core, str(PLUGIN_DIR.parents[2] / "LEDMatrix")):
    if _candidate and (Path(_candidate) / "src" / "plugin_system").is_dir():
        CORE = Path(_candidate)
        sys.path.insert(0, _candidate)
        break
else:
    print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
    sys.exit(2)

from src.plugin_system.testing import (  # noqa: E402
    MockCacheManager, MockDisplayManager, MockPluginManager)
from manager import UFCScoreboardPlugin  # noqa: E402

FAILURES = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILURES.append(label)


class _Records(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def face(font):
    """The file a loaded font came from ('' for PIL's built-in default)."""
    return os.path.basename(getattr(font, "path", "") or "")


schema = json.loads((PLUGIN_DIR / "config_schema.json").read_text(encoding="utf-8"))
custom = schema["properties"]["customization"]["properties"]
defaults = {
    element: {key: node["default"] for key, node in block.get("properties", {}).items()
              if "default" in node}
    for element, block in custom.items() if element != "layout"
}
check("the schema configures fonts as repo-relative paths",
      defaults["status_text"]["font"] == "assets/fonts/tom-thumb.bdf"
      and defaults["detail_text"]["font"] == "assets/fonts/4x6-font.ttf",
      {k: v.get("font") for k, v in defaults.items()})

records = _Records()
logging.getLogger().addHandler(records)
logging.getLogger().setLevel(logging.DEBUG)

original_cwd = os.getcwd()
with tempfile.TemporaryDirectory() as tmp:
    os.chdir(tmp)
    try:
        config = {"enabled": True, "customization": defaults,
                  "ufc": {"enabled": True}}
        plugin = UFCScoreboardPlugin("ufc-scoreboard", config, MockDisplayManager(128, 32),
                                     MockCacheManager(), MockPluginManager())
        mgr = plugin.ufc_recent
        check("the recent manager was built", mgr is not None)

        print("\nschema defaults load the configured face")
        check("no doubled assets/fonts path was looked up",
              not any("assets/fonts/assets/fonts" in m.replace("\\", "/")
                      for m in records.messages),
              [m for m in records.messages if "Font file not found" in m])
        check("status uses tom-thumb.bdf", face(mgr.fonts["status"]) == "tom-thumb.bdf",
              face(mgr.fonts["status"]))
        check("detail uses 4x6-font.ttf", face(mgr.fonts["detail"]) == "4x6-font.ttf",
              face(mgr.fonts["detail"]))
        check("record uses 4x6-font.ttf", face(mgr.fonts["record"]) == "4x6-font.ttf",
              face(mgr.fonts["record"]))
        check("an element the schema leaves unset keeps PressStart2P",
              face(mgr.fonts["score"]) == "PressStart2P-Regular.ttf",
              face(mgr.fonts["score"]))

        print("\nevery spelling of a font value")
        load = mgr._load_custom_font_from_element_config
        check("a repo-relative path loads that face",
              face(load({"font": "assets/fonts/4x6-font.ttf", "font_size": 7})) == "4x6-font.ttf")
        check("a bare filename still loads from assets/fonts",
              face(load({"font": "4x6-font.ttf", "font_size": 7})) == "4x6-font.ttf")
        absolute = str(CORE / "assets" / "fonts" / "4x6-font.ttf")
        loaded = load({"font": absolute, "font_size": 7})
        check("an absolute path is used as given",
              os.path.normcase(getattr(loaded, "path", "")) == os.path.normcase(absolute),
              getattr(loaded, "path", ""))
        check("an unknown font still falls back to PressStart2P",
              face(load({"font": "assets/fonts/no-such-font.ttf", "font_size": 8}))
              == "PressStart2P-Regular.ttf")
    finally:
        os.chdir(original_cwd)
        logging.getLogger().removeHandler(records)

print()
if FAILURES:
    print(f"{len(FAILURES)} check(s) failed")
    sys.exit(1)
print("all checks passed")
