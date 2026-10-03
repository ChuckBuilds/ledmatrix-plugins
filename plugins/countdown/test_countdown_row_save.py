#!/usr/bin/env python3
"""Tests that a countdown row saves, and keeps, its layout and style sections.

`countdowns` uses the array-table editor. It builds the advanced sections
(`layout`, `style`) as nested form inputs -- `countdowns.0.layout.image_width`
and so on -- but only when the schema declares the property as a plain
"object". Declared as a union (`["object", "string", "null"]`, which 3.x
briefly did so a blank row would validate), the settings page falls through to
a single hidden input holding Python's repr of the stored dict. The save
parses that as an object and gets `{}`: every size, position and colour
override was wiped on every save, and the modal's edits had no input to land
in. That was the "image size settings don't save" report.

A row the user never expanded still saves: the nested inputs carry the schema
defaults, so nothing is blank, and the server coerces any blank container to {}.

Run: <core-venv>/bin/python plugins/countdown/test_countdown_row_save.py
"""

import json
import os
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent

try:
    import jsonschema
except ImportError:
    print("SKIP: jsonschema not installed")
    sys.exit(2)

SCHEMA = json.loads((PLUGIN_DIR / "config_schema.json").read_text(encoding="utf-8"))
ITEM = SCHEMA["properties"]["countdowns"]["items"]
CONTAINERS = ("layout", "style")

failures = []


def check(name, cond, detail=""):
    if cond:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s%s" % (name, (": " + detail) if detail else ""))
        failures.append(name)



def _plugin_class():
    """The plugin class, or None when the core is not importable here."""
    import importlib.util
    core = os.environ.get("LEDMATRIX_CORE", "")
    for candidate in (core, str(PLUGIN_DIR.parents[2] / "LEDMatrix")):
        if candidate and (Path(candidate) / "src" / "plugin_system").is_dir():
            sys.path.insert(0, candidate)
            break
    sys.path.insert(0, str(PLUGIN_DIR))
    try:
        spec = importlib.util.spec_from_file_location(
            "countdown_manager", PLUGIN_DIR / "manager.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception:
        return None
    name = json.loads((PLUGIN_DIR / "manifest.json").read_text(
        encoding="utf-8"))["class_name"]
    cls = getattr(module, name, None)
    return cls.__new__(cls) if cls else None


def _row(**over):
    """A row with only the fields the editor's visible columns collect."""
    row = {"name": "Holiday", "target_date": "2026-12-25"}
    row.update(over)
    return row


def _valid(row):
    try:
        jsonschema.validate(row, ITEM)
        return None
    except jsonschema.ValidationError as e:
        return e.message


def main():
    print("the sections are plain objects, so the editor builds real inputs")
    for key in CONTAINERS:
        prop = ITEM["properties"][key]
        check("%s is declared as a plain object" % key, prop.get("type") == "object",
              repr(prop.get("type")))
        check("%s declares its fields" % key, bool(prop.get("properties")))

    print("\na plain row saves")
    check("baseline row validates", _valid(_row()) is None, _valid(_row()) or "")

    print("\nand so does what the editor posts for a row nobody expanded")
    # Every nested input at its schema default; a blank number box comes back
    # from the server as null, which the nullable fields accept.
    untouched = {}
    for key in CONTAINERS:
        untouched[key] = {
            name: (sub.get("default") if "default" in sub else None)
            for name, sub in ITEM["properties"][key]["properties"].items()
        }
    message = _valid(_row(**untouched))
    check("untouched layout/style validate", message is None, message or "")

    print("\na real object is still accepted")
    row = _row(layout={"image_x": 4, "image_width": 64, "image_height": 32},
               style={"font_size": 8})
    check("populated sections validate", _valid(row) is None, _valid(row) or "")

    print("\nand a wrong shape is still rejected")
    check("a number is not a layout", _valid(_row(layout=17)) is not None)

    print("\nthe plugin survives a hand-edited config")
    # Blank, null or junk in a config file must not take the plugin down.
    plugin = _plugin_class()
    if plugin is None:
        print("  SKIP  manager not importable without a core checkout")
    else:
        for blank in (None, "", 17):
            layout = plugin._normalize_layout(blank)
            style = plugin._normalize_style(blank)
            check("layout(%r) yields a mapping" % blank, isinstance(layout, dict))
            check("style(%r) yields a mapping" % blank, isinstance(style, dict))

    print("\n%s" % ("FAILED: %d" % len(failures) if failures
                    else "All checks passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
