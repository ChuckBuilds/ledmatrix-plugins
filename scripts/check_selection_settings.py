#!/usr/bin/env python3
"""Every settings block a sports schema declares must carry the selection keys.

    python3 scripts/check_selection_settings.py --all
    python3 scripts/check_selection_settings.py football-scoreboard

## Why this exists

The five favourite-selection settings are shared code copied into nine plugins,
and each plugin declares them once per league -- soccer alone has twelve blocks.
A block that misses one is not a crash and not a log line: the control is simply
absent from the web UI for that league, or present with no default, and the user
has no way to tell which. One such gap shipped exactly that way -- soccer's
custom_leagues block had four of the five, so a user-defined league could not
express what every built-in league could.

The check is deliberately structural rather than a fixed list of blocks: it
finds every properties-dict that declares a game limit, which is what a settings
block IS, so a league added later is covered without touching this file.

Ranges are checked too. They are the only thing standing between a hand-edited
config and a mode that renders nothing, and they have to agree across nine
copies or the same setting means different things in different plugins.
"""
import argparse
import json
import sys
from pathlib import Path

PLUGINS = Path(__file__).resolve().parents[1] / "plugins"

# A block that declares one of these is a game-selection settings block.
ANCHORS = ("upcoming_games_to_show", "recent_games_to_show")

# key -> (json type, minimum, maximum, allowed values or None)
REQUIRED = {
    "other_upcoming_games_to_show": ("integer", 0, 20, None),
    "other_recent_games_to_show": ("integer", 0, 20, None),
    "other_rotation_interval_seconds": ("integer", 0, 86400, None),
    "other_games_min_quality": ("string", None, None, {"any", "broadcast", "ranked"}),
    "other_games_divisions": ("array", None, None, {"fbs", "fcs", "other"}),
}


def _blocks(node, path="", in_row_editor=False):
    """Every settings block, and whether it lives inside a row editor.

    A block under an `x-columns` array (custom_leagues) is edited by
    array-table.js, whose coerceValue() has no array branch: it submits the raw
    text, so an array-typed setting arrives as "fbs" where the schema wants
    ["fbs"] and jsonschema rejects the whole save -- not just that field. Array
    settings are therefore not expressible there, and demanding one would be
    demanding a bug. Scalars are still required.
    """
    found = []
    if isinstance(node, dict):
        row_editor = in_row_editor or "x-columns" in node
        props = node.get("properties")
        if isinstance(props, dict) and any(a in props for a in ANCHORS):
            found.append((path or "<root>", props, row_editor))
        for key, value in node.items():
            found += _blocks(value, "%s/%s" % (path, key), row_editor)
    return found


def _settings_the_code_reads(plugin_id):
    """Which of the catalogue this plugin's own code actually consumes.

    Derived from sports.py rather than hardcoded, because the nine plugins do
    not have to be in lockstep: a setting can land in one lineage first and be
    ported later, and during that window the others are not broken -- they
    simply do not have it yet. Hardcoding the full list made this guard fail
    every plugin that had not been ported, which turns a staged rollout into a
    red build and teaches people to ignore the guard.

    A setting the code DOES read must still be reachable. That is the invariant
    worth enforcing, and it is the one that catches the real bug.
    """
    source = PLUGINS / plugin_id / "sports.py"
    if not source.exists():
        return {}
    text = source.read_text()
    return {key: spec for key, spec in REQUIRED.items() if '"%s"' % key in text}


def check_plugin(plugin_id):
    schema_path = PLUGINS / plugin_id / "config_schema.json"
    if not schema_path.exists():
        return []
    schema = json.loads(schema_path.read_text())
    required = _settings_the_code_reads(plugin_id)
    problems = []
    for where, props, row_editor in _blocks(schema):
        label = "%s %s" % (plugin_id, where.replace("/properties", "") or "<root>")
        for key, (want_type, low, high, allowed) in required.items():
            if row_editor and want_type == "array":
                continue          # see _blocks: the row editor cannot submit one
            node = props.get(key)
            if node is None:
                problems.append(
                    "%s: '%s' is missing. The block declares a game limit, so it "
                    "is a selection block, and a user configuring this league has "
                    "no way to reach that setting." % (label, key))
                continue
            if "default" not in node:
                problems.append(
                    "%s: '%s' has no default. The form renders it empty and the "
                    "code falls back to its own value, so the UI and the board "
                    "disagree about what is configured." % (label, key))
            if node.get("type") != want_type:
                problems.append("%s: '%s' is type %r, expected %r"
                                % (label, key, node.get("type"), want_type))
            for bound, want in (("minimum", low), ("maximum", high)):
                if want is not None and node.get(bound) != want:
                    problems.append("%s: '%s' %s is %r, expected %r"
                                    % (label, key, bound, node.get(bound), want))
            if allowed is not None:
                got = node.get("enum") or (node.get("items") or {}).get("enum")
                if set(got or ()) != allowed:
                    problems.append("%s: '%s' allows %s, expected %s"
                                    % (label, key, sorted(got or ()), sorted(allowed)))

        # The counts default to their own block's limit so an upgrade keeps the
        # games it was already showing. A larger default silently doubles the
        # card count -- and the dwell -- on somebody else's board.
        for other, own in (("other_upcoming_games_to_show", "upcoming_games_to_show"),
                           ("other_recent_games_to_show", "recent_games_to_show")):
            if other not in required:
                continue
            a = (props.get(other) or {}).get("default")
            b = (props.get(own) or {}).get("default")
            if isinstance(a, int) and isinstance(b, int) and a > b:
                problems.append(
                    "%s: '%s' defaults to %d, above this block's own '%s' of %d. "
                    "An upgrade would add more cards than the board showed before."
                    % (label, other, a, own, b))
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("plugin_ids", nargs="*")
    ap.add_argument("--all", action="store_true", help="Check every sports plugin")
    args = ap.parse_args()

    if args.all or not args.plugin_ids:
        ids = sorted(p.name for p in PLUGINS.iterdir()
                     if (p / "sports.py").exists() and (p / "config_schema.json").exists())
    else:
        ids = args.plugin_ids

    problems = [p for pid in ids for p in check_plugin(pid)]
    if not problems:
        blocks = sum(len(_blocks(json.loads((PLUGINS / i / "config_schema.json").read_text())))
                     for i in ids)   # noqa: E501 - count only
        print("OK: %d plugin(s), %d selection block(s); every setting each "
              "plugin's code reads is declared, with matching ranges."
              % (len(ids), blocks))
        return 0
    for problem in problems:
        print("  - %s" % problem)
    print("\n%d problem(s)." % len(problems))
    return 1


if __name__ == "__main__":
    sys.exit(main())
