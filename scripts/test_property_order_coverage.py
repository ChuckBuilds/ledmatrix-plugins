#!/usr/bin/env python3
"""A setting missing from x-propertyOrder cannot be configured at all.

The web UI's config form iterates ``x-propertyOrder`` and nothing else:

    {% set property_order = schema['x-propertyOrder']
                            if 'x-propertyOrder' in schema
                            else schema.properties.keys()|list %}
    {% for key in property_order %}
        {% if key in schema.properties %}

A property declared in the schema but absent from that list is therefore
never rendered -- no field, no error, no hint that the setting exists. The
value still validates on save and the plugin still reads it, so the only way
to set one was to hand-edit config.json on the device.

Twenty-six settings across seven plugins were in that state, including
ledmatrix-flights' ``flightaware_api_key`` -- marked ``x-secret: true`` for
masking, yet impossible to enter -- and the two idle-poll intervals whose
plumbing had just been fixed so they would finally take effect. Twenty-two of
the twenty-six carried ``x-advanced: true``: nobody flags a field "advanced"
meaning "invisible", so these were omissions, not deliberate hiding. There is
no supported way to hide a property, and no schema in the repo attempts one.

Note the asymmetry that hid this: the client-side renderer in app-shell.js
appends unlisted properties instead of dropping them, so the same schema can
look fine there and be unreachable in the server-rendered form.

Run: <core-venv>/bin/python scripts/test_property_order_coverage.py
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
failures = []


def check(label, ok):
    print(("  PASS  " if ok else "  FAIL  ") + label)
    if not ok:
        failures.append(label)


def unlisted(node, path=()):
    """Every (location, property) a config form would silently skip."""
    out = []
    if not isinstance(node, dict):
        return out
    props = node.get("properties")
    if isinstance(props, dict):
        order = node.get("x-propertyOrder")
        if isinstance(order, list):
            for key in props:
                if key not in order:
                    out.append((".".join(path) or "(root)", key))
        for key, value in props.items():
            out += unlisted(value, path + (key,))
    items = node.get("items")
    if isinstance(items, dict):
        out += unlisted(items, path + ("[]",))
    return out


def main():
    print("every declared setting must be reachable in the config form")
    offenders = []
    schemas = sorted((REPO / "plugins").glob("*/config_schema.json"))
    for path in schemas:
        plugin = path.parent.name
        missing = unlisted(json.load(path.open(encoding="utf-8")))
        if missing:
            offenders.append((plugin, missing))
    for plugin, missing in offenders:
        for loc, key in missing:
            print(f"        {plugin}: {loc}.{key}")
    check(f"{len(schemas)} schemas, none hiding a declared setting "
          f"({sum(len(m) for _, m in offenders)} hidden)", not offenders)

    print("\nthe form really does drop what the order omits")
    # Not a claim about the template -- render it and look.
    core = None
    for candidate in (Path("/home/rackpi/projects/LEDMatrix"),
                      REPO.parent / "LEDMatrix"):
        if (candidate / "web_interface" / "templates" / "v3" / "partials"
                / "plugin_config.html").exists():
            core = candidate
            break
    if core is None:
        print("  SKIP  no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
    else:
        import re
        from jinja2 import DictLoader, Environment
        source = (core / "web_interface" / "templates" / "v3" / "partials"
                  / "plugin_config.html").read_text(encoding="utf-8")
        match = re.search(
            r"(\{%\s*set property_order = schema\['x-propertyOrder'\].*?"
            r"\{%\s*endfor\s*%\})", source, re.S)
        check("the ordering loop is still in the shipped template", bool(match))
        if match:
            # The loop only sorts keys into tiers, so append an emitter to see
            # which keys it actually considered.
            block = match.group(1) + "|{{ tiers.basic }}{{ tiers.advanced }}|"
            env = Environment(loader=DictLoader({'f': block}), autoescape=True)
            schema = {'properties': {'shown': {'type': 'string'},
                                     'hidden': {'type': 'string'}},
                      'x-propertyOrder': ['shown']}
            tiers = env.get_template('f').render(schema=schema).split('|')[1]
            check("a listed property reaches the form (%s)" % tiers.strip(),
                  'shown' in tiers)
            check("a property absent from the order is dropped entirely",
                  'hidden' not in tiers)

    print("\n%s" % ("FAILED: %d" % len(failures) if failures
                    else "All checks passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
