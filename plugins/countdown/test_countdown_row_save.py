#!/usr/bin/env python3
"""Tests that a countdown row saves when its advanced sections were never opened.

`countdowns` uses the array-table editor, which keeps every non-column property
in a hidden input. An untouched row sends those back as null and a cleared one
as an empty string. `layout` and `style` were declared as strict "object", so
Draft-7 rejected both and the whole config save failed with HTTP 400 -- with
nothing to say which field was at fault.

The same defect was reported against soccer-scoreboard as "cannot add eng.2";
it is a property of the widget, not of any one plugin, so it lands wherever an
array-table row carries an object-typed property.

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
    print("a plain row saves")
    check("baseline row validates", _valid(_row()) is None, _valid(_row()) or "")

    print("\nand so does one whose advanced sections were never opened")
    for label, blank in (("null", None), ("empty string", "")):
        row = _row(**{k: blank for k in CONTAINERS})
        message = _valid(row)
        check("untouched layout/style save (%s)" % label, message is None,
              message or "")

    print("\na real object is still accepted")
    row = _row(layout={"image_x": 4}, style={"font_size": 8})
    check("populated sections validate", _valid(row) is None, _valid(row) or "")

    print("\nand a wrong shape is still rejected")
    # The relaxation is for the editor's blanks, not a licence for anything.
    check("a number is not a layout", _valid(_row(layout=17)) is not None)

    print("\nthe plugin survives what the schema now permits")
    # The schema was the only thing standing in the way: the normalizers
    # already coerce a non-mapping to {}. Assert that rather than restating
    # the schema, which the cases above already cover.
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
