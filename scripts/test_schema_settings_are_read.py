#!/usr/bin/env python3
"""Every setting the config form draws must have something that reads it.

A schema property the code never reads is a control that does nothing: the
web UI draws it, the user changes it, the board ignores it. An audit in
2026-09 found 60 of them across 25 plugins and hid them
(``"x-display": "hidden"``) in #535 and #536.

Most of those were *read* and then lost -- a per-league interval every
manager overwrote, a flat FlightAware key the nested section always beat --
and no static check sees that; ``test_inert_settings_are_hidden.py`` pins the
scoreboard cases one by one. This guard catches the simplest form, which
needs no knowledge of the code: a property nothing names at all. Run against
the schemas before the audit it reports two (``season_cache_duration_seconds``
in hockey and lacrosse).

## What "read" means here

A visible property counts as read when its name appears as a quoted string
literal in the plugin's own Python (tests excluded) or in the core modules
plugins hand their config to: ``src/common/*`` (sports cards, scroll pacing),
``src/element_style.py`` (``customization.*``), ``base_plugin.py``,
``display_controller.py`` and ``plugin_manager.py`` (``display_duration``,
``live_priority``, ``vegas_mode``, ``dynamic_duration``, ``update_interval``).

That is deliberately a floor, not proof: a name can be read into a variable
nobody uses, and a common name (``enabled``) is always "found". It catches the
common case -- a property added to the schema and never wired -- and a key
read by a computed name has to be listed in ``DYNAMIC_READS`` below with the
line that reads it, where a reviewer can see and check it.

Properties are skipped when hidden (``x-display: hidden``, or under a hidden
parent) and when they are UI-only widgets that store nothing (``type: null``).

## When this fails

* Wire the setting, or
* hide it (``"x-display": "hidden"`` plus a ``HIDDEN:`` reason in its
  description, so saved configs keep validating), or
* if the code reads it through a computed name, add the pattern to
  ``DYNAMIC_READS`` with where it is read.

An entry in ``DYNAMIC_READS`` that no longer matches anything fails too, so
the list cannot quietly outlive the code it describes.

Run: LEDMATRIX_CORE=/path/to/LEDMatrix python scripts/test_schema_settings_are_read.py
Exit 0 pass, 1 fail, 2 skip (no core checkout).
"""
import fnmatch
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUGINS = REPO / "plugins"

#: Settings read through a computed name. plugin id ("*" = any) -> {dotted
#: path pattern (fnmatch; "[]" steps into array items): where it is read}.
DYNAMIC_READS = {
    "*": {
        "*mode_durations.*_mode_duration":
            'manager: mode_durations.get(f"{mode_type}_mode_duration")',
        "customization.favorite_result_colors.*_color":
            'core sports_card.favorite_result / sports_shared: f"{result}_color"',
    },
    "calendar": {
        "google_auth": "UI-only google-oauth widget; sign-in writes token.pickle",
    },
    "f1-scoreboard": {
        "customization.*_text":
            'f1_renderer: cfg.get(key + "_text") over header/position/detail/small',
    },
    "fantasy-blitz": {
        "positions.*": "manager: pos_cfg.get(p.lower(), True) over model.POSITIONS",
    },
    "static-image": {
        "images.[].schedule.days.*": "manager: days.get(day_name) over the weekday names",
    },
}

CORE_MODULES = (
    "src/common/*.py",
    "src/element_style.py",
    "src/plugin_system/base_plugin.py",
    "src/plugin_system/plugin_manager.py",
    "src/display_controller.py",
)


def find_core():
    for candidate in (os.environ.get("LEDMATRIX_CORE"), REPO.parent / "LEDMatrix"):
        if candidate and (Path(candidate) / "src" / "plugin_system").is_dir():
            return Path(candidate)
    return None


def plugin_source(plugin_dir):
    parts = []
    for path in sorted(plugin_dir.rglob("*.py")):
        rel = path.relative_to(plugin_dir).parts
        if path.name.startswith("test_") or "test" in rel[:-1] or "tests" in rel[:-1]:
            continue
        parts.append(path.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(parts)


def visible_leaves(node, path=""):
    """(dotted path, name) for every property the form draws."""
    for name, prop in (node.get("properties") or {}).items():
        if not isinstance(prop, dict) or prop.get("x-display") == "hidden":
            continue
        where = "%s.%s" % (path, name) if path else name
        if prop.get("type") != "null":
            yield where, name
        yield from visible_leaves(prop, where)
        if isinstance(prop.get("items"), dict):
            yield from visible_leaves(prop["items"], where + ".[]")


def literal(name):
    return re.compile(r"""['"]%s['"]""" % re.escape(name))


def unread(schema, code, core_code, patterns):
    """Visible paths with no literal reader and no DYNAMIC_READS entry, and
    the set of patterns that matched something."""
    missing, used = [], set()
    for where, name in visible_leaves(schema):
        rx = literal(name)
        if rx.search(code) or rx.search(core_code):
            continue
        hits = [p for p in patterns if fnmatch.fnmatchcase(where, p)]
        if hits:
            used.update(hits)
            continue
        missing.append(where)
    return missing, used


def self_test():
    """The detector itself: an unread key is caught, a read one is not."""
    schema = {"properties": {
        "wired": {"type": "boolean"},
        "never_read": {"type": "integer"},
        "gone": {"type": "integer", "x-display": "hidden"},
        "ui_only": {"type": "null"},
        "block": {"type": "object", "properties": {"inner_unread": {"type": "string"}}},
    }}
    code = "x = config.get('wired', True)\nblock = config.get('block')\n"
    missing, _ = unread(schema, code, "", {})
    return missing == ["never_read", "block.inner_unread"], missing


def main():
    ok, got = self_test()
    print(("PASS" if ok else "FAIL") + "  self-test: an unread key is reported, a read one is not")
    if not ok:
        print("        got %s" % got)
        return 1

    core = find_core()
    if core is None:
        print("SKIP: no LEDMatrix core checkout (set LEDMATRIX_CORE); "
              "core modules read many plugin settings")
        return 2
    core_code = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore")
        for pattern in CORE_MODULES for p in sorted(core.glob(pattern)))

    failures = 0
    used_by_plugin = {}
    for plugin_dir in sorted(p for p in PLUGINS.iterdir() if p.is_dir()):
        schema_path = plugin_dir / "config_schema.json"
        if not schema_path.exists():
            continue
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        patterns = dict(DYNAMIC_READS.get("*", {}))
        patterns.update(DYNAMIC_READS.get(plugin_dir.name, {}))
        missing, used = unread(schema, plugin_source(plugin_dir), core_code, patterns)
        used_by_plugin[plugin_dir.name] = used
        if missing:
            failures += 1
            print("FAIL  %s: %d visible setting(s) nothing reads" % (plugin_dir.name, len(missing)))
            for where in missing:
                print("        %s" % where)

    for plugin, patterns in DYNAMIC_READS.items():
        if plugin == "*":
            stale = [p for p in patterns
                     if not any(p in used for used in used_by_plugin.values())]
        else:
            stale = [p for p in patterns if p not in used_by_plugin.get(plugin, set())]
        for pattern in stale:
            failures += 1
            print("FAIL  DYNAMIC_READS[%r][%r] matches no unread visible setting; "
                  "remove it" % (plugin, pattern))

    if failures:
        print("\n%d problem(s). See this file's docstring for the three ways to fix one." % failures)
        return 1
    print("PASS  every visible setting in %d plugin schemas has a reader" % len(used_by_plugin))
    return 0


if __name__ == "__main__":
    sys.exit(main())
