#!/usr/bin/env python3
"""A strict object holding a checkbox-group field must permit its `_data` twin.

    python3 scripts/check_ui_companion_keys.py
    python3 scripts/check_ui_companion_keys.py news f1-scoreboard

## Why this exists

The web UI renders a field marked `"x-widget": "checkbox-group"` with a hidden
input whose *name* is `{{ full_key }}_data` -- not `{{ full_key }}` as every
other widget's hidden input is (core:
`web_interface/templates/v3/partials/plugin_config.html`). `savePluginConfig`
walks the form by `name` (core: `web_interface/static/v3/js/app-shell.js`), so
saving that page writes `<field>_data` into config.json beside `<field>`.

No plugin reads the key. But if the object that declares the field also sets
`"additionalProperties": false`, the core's soft schema check
(`src/plugin_system/plugin_manager.py::_validate_config_schema_soft`) rejects
it, and the web UI shows

    Degraded: Config schema: Field '<parent>': Additional properties are not
    allowed ('<field>_data' was unexpected)

on a config its own UI had just written. Odds Ticker shipped that way and it
was reported off a live rig; eight more fields across seven plugins carried the
identical latent defect, waiting for the first user to touch that control.

The fix is per-parent `patternProperties`, never
`"additionalProperties": true` -- a typo in a hand-edited config must still be
caught. This guard is structural, so a checkbox-group added tomorrow is covered
without touching this file.
"""
import argparse
import json
import sys
from pathlib import Path

PLUGINS = Path(__file__).resolve().parents[1] / "plugins"

WIDGET = "checkbox-group"


def _offenders(node, path=""):
    """Every checkbox-group field whose own object rejects its `_data` twin.

    Only the immediate parent matters: the companion key is written as a
    sibling of the field, so a strict grandparent never sees it.
    """
    found = []
    if isinstance(node, dict):
        props = node.get("properties")
        if isinstance(props, dict):
            for name, field in props.items():
                if not isinstance(field, dict):
                    continue
                if field.get("x-widget") != WIDGET:
                    continue
                if node.get("additionalProperties") is not False:
                    continue  # unknown keys already tolerated here
                pattern = "^%s_data$" % name
                allowed = pattern in (node.get("patternProperties") or {})
                if not allowed:
                    found.append(("%s%s" % (path, name), pattern))
        for key, value in node.items():
            if key == "properties" and isinstance(value, dict):
                for name, field in value.items():
                    found += _offenders(field, "%s%s." % (path, name))
            elif isinstance(value, dict):
                found += _offenders(value, path)
    return found


def _fields(node):
    """Count of checkbox-group fields, offending or not, for the summary."""
    total = 0
    if isinstance(node, dict):
        props = node.get("properties")
        if isinstance(props, dict):
            total += sum(1 for f in props.values()
                         if isinstance(f, dict) and f.get("x-widget") == WIDGET)
        for value in node.values():
            if isinstance(value, dict):
                total += _fields(value)
    return total


def check_plugin(plugin_id):
    schema_path = PLUGINS / plugin_id / "config_schema.json"
    if not schema_path.exists():
        return []
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return [
        "%s: '%s' is a %s field, but its object sets additionalProperties: "
        "false without patternProperties %r -- saving that page in the web UI "
        "marks the plugin Degraded" % (plugin_id, field, WIDGET, pattern)
        for field, pattern in _offenders(schema)
    ]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("plugin_ids", nargs="*")
    args = ap.parse_args()

    if args.plugin_ids:
        ids = args.plugin_ids
        unknown = [i for i in ids
                   if not (PLUGINS / i / "config_schema.json").exists()]
        if unknown:
            print("Unknown plugin id(s): %s" % ", ".join(sorted(unknown)),
                  file=sys.stderr)
            return 2
    else:
        ids = sorted(p.name for p in PLUGINS.iterdir()
                     if (p / "config_schema.json").exists())

    problems = [p for pid in ids for p in check_plugin(pid)]
    if not problems:
        fields = sum(
            _fields(json.loads((PLUGINS / i / "config_schema.json").read_text(encoding="utf-8")))
            for i in ids)
        print("OK: %d plugin(s), %d %s field(s); every strict parent permits "
              "the companion key the web UI writes." % (len(ids), fields, WIDGET))
        return 0
    for problem in problems:
        print("  - %s" % problem)
    print("\n%d problem(s)." % len(problems))
    return 1


if __name__ == "__main__":
    sys.exit(main())
