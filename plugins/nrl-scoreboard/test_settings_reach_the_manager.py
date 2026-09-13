#!/usr/bin/env python3
"""A setting the user can change must actually reach the code that reads it.

Managers do not read the plugin config. `_adapt_config_for_manager` translates
it into the shape the managers expect, and that translation is an explicit
whitelist -- every key is named. A key missing from it is not a crash and not a
log line: the setting appears in the web UI, the user changes it, saves, and
nothing happens. The code silently keeps its own default.

That is exactly what happened to the five settings added for favourite
prioritisation. All five were declared in the schema, rendered in the UI,
read by sports.py -- and never passed through the translation, so every one of
them was inert. Nothing failed, which is what makes this class of bug worth a
test of its own rather than trusting review.

The check is deliberately blunt: set a value that is NOT the default, run the
real translation, and assert the value arrives. A test using default values
would pass against a translation that dropped the key entirely.

Run: <core-venv>/bin/python plugins/nrl-scoreboard/test_settings_reach_the_manager.py
"""

import os
import sys
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

REPO = Path(__file__).resolve().parents[2]
CORE = None
for _c in (os.environ.get("LEDMATRIX_CORE", ""),
           str(REPO.parent / "LEDMatrix"),
           str(Path.home() / "projects" / "LEDMatrix")):
    if _c and (Path(_c) / "assets" / "fonts").is_dir():
        CORE = Path(_c)
        break
if CORE is None:
    print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
    sys.exit(2)
sys.path.insert(0, str(CORE))

results = []

# Keys the schema declares that deliberately do NOT go through the manager
# translation, each with where it is consumed instead. Anything else the schema
# offers must arrive -- the probe list is built from the schema, so a setting
# added there without being forwarded fails here instead of shipping inert.
ALLOWLIST = {
    "display_modes": "reshaped to per-mode booleans; *_display_mode is read by "
                     "manager.py _parse_display_mode_settings",
    "scroll_settings": "read from the plugin config by scroll_display.py",
    "display_duration": "read by manager.py and the core, not the league managers",
    "game_display_duration": "read by manager.py, not the league managers",
    "dynamic_duration": "read by manager.py's dynamic-duration support",
    "mode_durations": "read by manager.py's per-mode cycle durations",
}
# Objects whose leaves are flattened into the manager block by the translation.
CONTAINERS = ("game_limits", "filtering", "display_options")
# Values that must be valid to survive the translation's own resolution.
SPECIAL = {"timezone": "Australia/Sydney"}


def _probe_value(key, node):
    """A value for ``node`` that is valid for its schema and differs from its default."""
    if key in SPECIAL:
        return SPECIAL[key]
    default = node.get("default")
    kind = node.get("type")
    if isinstance(kind, list):
        kind = next((k for k in kind if k != "null"), None)
    if "enum" in node:
        others = [v for v in node["enum"] if v != default]
        return others[0] if others else default
    if kind == "boolean":
        return not bool(default)
    if kind in ("integer", "number"):
        low = node.get("minimum", 0)
        high = node.get("maximum", 10 ** 6)
        base = default if isinstance(default, (int, float)) else low
        value = base + 7 if base + 7 <= high else base - 1
        if value < low:
            value = low if low != default else high
        return int(value) if kind == "integer" else value + 0.5
    if kind == "array":
        items = node.get("items") or {}
        pool = [v for v in items.get("enum", []) if v not in (default or [])]
        return [pool[0] if pool else "probe-%s" % key]
    if kind == "object":
        return {k: _probe_value(k, v) for k, v in (node.get("properties") or {}).items()
                if isinstance(v, dict)}
    return "probe-%s" % key


def _build_probe():
    import json as _json
    schema = _json.load(open(plugin_dir / "config_schema.json", encoding="utf-8"))
    props = schema.get("properties") or {}
    probe = {}
    for key, node in props.items():
        if key in ALLOWLIST or not isinstance(node, dict):
            continue
        if key in CONTAINERS:
            for leaf, leaf_node in (node.get("properties") or {}).items():
                probe.setdefault(leaf, _probe_value(leaf, leaf_node))
            continue
        probe[key] = _probe_value(key, node)
    return probe


PROBE = _build_probe()


def check(case, passed, detail=""):
    results.append((case, passed))
    print("  [%s] %s%s" % ("pass" if passed else "FAIL", case,
                           "" if passed else "  <- " + str(detail)))


def main():
    os.chdir(str(CORE))
    import manager as plugin_manager

    cls = None
    for name in dir(plugin_manager):
        obj = getattr(plugin_manager, name)
        if isinstance(obj, type) and hasattr(obj, "_adapt_config_for_manager"):
            cls = obj
            break
    if cls is None:
        print("SKIP: no class with _adapt_config_for_manager in this plugin")
        return 2

    import logging
    from unittest.mock import MagicMock
    obj = cls.__new__(cls)
    obj.logger = logging.getLogger("adapt_probe")
    # The translation reads a few collaborators while building its dict.
    for attr in ("cache_manager", "display_manager", "plugin_manager",
                 "config_manager", "font_manager"):
        setattr(obj, attr, MagicMock())

    # The schema puts these settings in different places per plugin -- some in
    # game_limits, some in filtering, some at the league root. Offer all three
    # so this one fixture works for whichever lineage it is copied into.
    league_block = {
        "enabled": True,
        "favorite_teams": ["UGA"],
        "game_limits": dict(PROBE),
        "filtering": dict(PROBE),
    }
    league_block.update(PROBE)

    # League names come from the plugin's own schema rather than a hardcoded
    # list: these nine plugins disagree about what a league is called, and a
    # guessed name that matches nothing reports a clean SKIP having checked
    # nothing at all.
    import json as _json
    schema = _json.load(open(plugin_dir / "config_schema.json"))
    leagues = [
        name for name, node in (schema.get("properties") or {}).items()
        if isinstance(node, dict) and isinstance(node.get("properties"), dict)
        and any(k in node["properties"] for k in
                ("game_limits", "favorite_teams", "filtering", "display_modes"))
    ]
    # Soccer keeps its leagues under config["leagues"][key] rather than at the
    # top level, and names them "eng.1" style, so schema scanning finds none.
    for extra in (schema.get("properties", {}).get("leagues", {}) or {}).get("properties", {}):
        if extra not in leagues:
            leagues.append(extra)
    if not leagues:
        leagues = ["eng.1", ""]   # a nested-league guess, then no-league at all

    import inspect
    takes_league = len(inspect.signature(cls._adapt_config_for_manager).parameters) > 1

    def adapt(league):
        """Call the real translation, filling in collaborators as it asks.

        Each lineage reads a different set of attributes off the plugin while
        building its dict. Rather than hardcode one plugin's list, supply what
        is missing on demand -- bounded, so a genuine error still surfaces.
        """
        for _ in range(40):
            try:
                return obj._adapt_config_for_manager(league) if takes_league \
                    else obj._adapt_config_for_manager()
            except AttributeError as exc:
                name = str(exc).rsplit("'", 2)[-2] if "'" in str(exc) else ""
                if not name or hasattr(obj, name):
                    raise
                setattr(obj, name, MagicMock())
        raise RuntimeError("gave up filling in attributes")

    errors = []
    # Each lineage reads its league config from a different place. Try the
    # shapes rather than assuming one; assuming produced a clean SKIP that had
    # verified nothing.
    shapes = []
    if not takes_league:
        # Single-league plugins read self.config directly; nesting the block
        # under a league name would hide it from them entirely.
        shapes.append(("", lambda b: dict(b)))
    else:
        for league in leagues:
            if not league:
                continue
            shapes.append((league, lambda b, l=league: {l: b}))
            shapes.append((league, lambda b, l=league: {"leagues": {l: b}}))
        shapes.append(("eng.1", lambda b: {"leagues": {"eng.1": b}}))

    # Try every shape and keep the one that fits best. Stopping at the first
    # shape that merely PRODUCED a block is wrong: feeding the config in the
    # wrong shape still yields a block, just one full of defaults -- which
    # looks exactly like the bug this test exists to catch.
    best, best_league, best_build, best_score = None, None, None, -1
    best_adapted = None
    for league, build in shapes:
        obj.config = build(league_block)
        try:
            adapted = adapt(league)
        except Exception as exc:
            errors.append("%s: %s: %s" % (league or "<none>", type(exc).__name__, exc))
            continue
        if not isinstance(adapted, dict):
            continue
        for value in adapted.values():
            if not isinstance(value, dict) or not any(k in value for k in PROBE):
                continue
            score = sum(1 for k, want in PROBE.items() if value.get(k) == want)
            if score > best_score:
                best, best_league, best_build, best_score = value, league, build, score
                best_adapted = adapted
        if best_score == len(PROBE):
            break

    if best is None:
        print("FAILED: the translation never produced a usable block.")
        for e in errors:
            print("   ", e)
        return 1

    print("  league: %s" % (best_league or "<single>"))
    for key, want in PROBE.items():
        # Root keys (timezone, customization, scroll_card, the schedule window)
        # land beside the league block rather than in it.
        got = best[key] if key in best else (best_adapted or {}).get(key)
        check("%s reaches the manager (%r)" % (key, want), got == want,
              "got %r" % (got,))

    # A location the schema OFFERS has to be a location that works. Two of
    # these plugins declare the same keys twice -- at the root of the config
    # and inside game_limits -- and the web UI renders both, so whichever one
    # the user fills in is the one that has to arrive. Each adapter read one of
    # the two, which left the other in the same state as a key missing from the
    # translation entirely: accepted, saved, ignored. Plugins that declare them
    # in one place are checked for that one place.
    block_props = {}
    props = (schema.get("properties") or {})
    if not takes_league:
        block_props = props
    else:
        node = props.get(best_league) or \
            ((props.get("leagues") or {}).get("properties") or {}).get(best_league) or {}
        block_props = node.get("properties") or {}
    # Not just game_limits: hockey and lacrosse declare the same keys under
    # filtering. Take whichever sub-block a plugin's own schema uses rather
    # than naming one and reporting "nothing to check" for the rest.
    places = []
    if any(k in block_props for k in PROBE):
        places.append((None, block_props))
    for name, node in sorted(block_props.items()):
        if name not in CONTAINERS:
            continue   # e.g. background_service.enabled is not the root enabled
        sub = (node or {}).get("properties") if isinstance(node, dict) else None
        if isinstance(sub, dict) and any(k in sub for k in PROBE):
            places.append((name, sub))
    if not places:
        print("  (the schema declares none of these keys on this block; "
              "the location check has nothing to check)")

    for where, declared_in in places:
        only = {"enabled": True, "favorite_teams": ["UGA"]}
        if where is None:
            only.update(PROBE)
        else:
            only[where] = dict(PROBE)
        obj.config = best_build(only)
        try:
            adapted = adapt(best_league)
        except Exception as exc:
            check("the translation survives a %s-only config"
                  % (where or "root"), False, "%s: %s" % (type(exc).__name__, exc))
            continue
        landed, landed_score = {}, -1
        for value in (adapted or {}).values():
            if not isinstance(value, dict) or not any(k in value for k in PROBE):
                continue
            score = sum(1 for k, want in PROBE.items() if value.get(k) == want)
            if score > landed_score:
                landed, landed_score = value, score
        for key in [k for k in PROBE if k in declared_in]:
            check("%s survives a config that only sets it in %s"
                  % (key, where or "the config root"),
                  (landed[key] if key in landed else (adapted or {}).get(key)) == PROBE[key],
                  "got %r" % (landed.get(key, (adapted or {}).get(key)),))

    failed = [c for c, ok in results if not ok]
    print("\n%d checks, %d failed" % (len(results), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
