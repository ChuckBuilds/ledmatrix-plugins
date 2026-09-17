#!/usr/bin/env python3
"""
Regression test: the artist and album rows use their schema-default font.

The schema's default for customization.artist_text / album_text is 5x7.bdf at
7px. _load_custom_fonts passed classic_font='PressStart2P-Regular.ttf',
classic_size=7 to the core's element-style resolver, which uses the classic
font whenever the configured font equals the schema default. Every default
config therefore drew artist and album in Press Start 2P at 7px, off that
face's 8px grid, and choosing 5x7.bdf in the web UI changed nothing.

Run from a LEDMatrix checkout (needs src.* and assets/fonts):
    cd /path/to/LEDMatrix
    python /path/to/ledmatrix-music/test_default_fonts_on_grid.py
Exit 0 pass, 2 skip, 1 fail.
"""

import copy
import json
import logging
import os
import sys

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)
_core = os.environ.get("LEDMATRIX_CORE")
if _core and _core not in sys.path:
    sys.path.insert(0, _core)

try:
    from manager import STYLE_AVAILABLE, MusicPlugin  # noqa: E402
    from src.plugin_system.testing import (  # noqa: E402
        MockCacheManager, MockPluginManager, VisualTestDisplayManager,
    )
except ImportError as exc:
    print(f"SKIP: core not importable ({exc})")
    sys.exit(2)

if not STYLE_AVAILABLE:
    print("SKIP: core without src.element_style; the legacy loader is not affected")
    sys.exit(2)

logging.disable(logging.CRITICAL)

failures = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ((": " + detail) if detail and not cond else ""))
    if not cond:
        failures.append(name)


def _schema_customization():
    """customization as the core's default merge writes it into config.json."""
    with open(os.path.join(PLUGIN_DIR, "config_schema.json"), encoding="utf-8") as f:
        schema = json.load(f)
    out = {}
    for element, node in schema["properties"]["customization"]["properties"].items():
        out[element] = {k: v["default"] for k, v in node["properties"].items() if "default" in v}
    return out


def _plugin(customization):
    cfg = {"enabled": False, "preferred_source": "spotify", "customization": customization}
    return MusicPlugin("ledmatrix-music", cfg, VisualTestDisplayManager(128, 32),
                       MockCacheManager(), MockPluginManager())


def _is_press_start(font):
    getname = getattr(font, "getname", None)
    return bool(getname) and "Press Start" in getname()[0]


def _describe(font):
    getname = getattr(font, "getname", None)
    if getname:
        return f"{getname()[0]} {getattr(font, 'size', '?')}px"
    return f"{type(font).__name__} {getattr(font, 'family_name', '')!r}"


defaults = _schema_customization()
check("schema defaults are 5x7.bdf for artist and album",
      defaults["artist_text"].get("font") == "5x7.bdf"
      and defaults["album_text"].get("font") == "5x7.bdf")

print("schema-default customization")
p = _plugin(copy.deepcopy(defaults))
for attr in ("artist_font", "album_font"):
    font = getattr(p, attr)
    check(f"{attr} is the 5x7 bitmap face, not Press Start 2P",
          font is not None and not _is_press_start(font) and hasattr(font, "family_name"),
          _describe(font))
check("title_font stays Press Start 2P at its 8px grid",
      _is_press_start(p.title_font) and getattr(p.title_font, "size", None) == 8,
      _describe(p.title_font))

print("user picks Press Start 2P for the artist row")
custom = copy.deepcopy(defaults)
custom["artist_text"]["font"] = "PressStart2P-Regular.ttf"
custom["artist_text"]["font_size"] = 8
p = _plugin(custom)
check("an explicit choice still wins", _is_press_start(p.artist_font), _describe(p.artist_font))
check("album row keeps its default", not _is_press_start(p.album_font), _describe(p.album_font))

if failures:
    print(f"\n{len(failures)} failure(s)")
    sys.exit(1)
print("\nall passed")
sys.exit(0)
