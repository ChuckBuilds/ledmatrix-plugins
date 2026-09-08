#!/usr/bin/env python3
"""check_ui_companion_keys must pass on this repo, and fail on a real gap.

Two halves. The first runs the checker over the plugins as they actually are --
that is what puts it in CI at all, since the workflow globs scripts/test_*.py
rather than scripts/check_*.py. The second feeds it schemas with known holes,
because a checker that cannot fail is indistinguishable from one that passes.

The defect this guards against was found on a live rig, not in review: nine
checkbox-group fields across eight plugins declared `additionalProperties:
false` on the object that also held the field, so the first user to touch that
control saved a config their own web UI then reported as Degraded.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_ui_companion_keys as checker

results = []


def check(case, passed, detail=""):
    results.append((case, passed))
    print("  [%s] %s%s" % ("pass" if passed else "FAIL", case,
                           "" if passed else "  <- " + str(detail)))


def with_plugin(tmp, schema):
    """Run the checker against a single synthetic plugin."""
    d = Path(tmp) / "probe"
    d.mkdir(parents=True, exist_ok=True)
    (d / "config_schema.json").write_text(json.dumps(schema), encoding="utf-8")
    original = checker.PLUGINS
    checker.PLUGINS = Path(tmp)
    try:
        return checker.check_plugin("probe")
    finally:
        checker.PLUGINS = original


FIELD = {"type": "array", "x-widget": "checkbox-group",
         "items": {"type": "string", "enum": ["a", "b"]}}
ALLOWANCE = {"^picks_data$": {"$comment": "Written by the web UI."}}


def main():
    print("the repo as it stands")
    problems = [p for pid in sorted(x.name for x in checker.PLUGINS.iterdir()
                                    if (x / "config_schema.json").exists())
                for p in checker.check_plugin(pid)]
    check("no plugin rejects the companion key its own UI writes",
          not problems, problems)

    with tempfile.TemporaryDirectory() as tmp:
        print("\na strict object holding a checkbox group")
        strict = {"type": "object", "properties": {"picks": FIELD},
                  "additionalProperties": False}
        found = with_plugin(tmp, strict)
        check("is flagged without the allowance",
              any("picks" in p for p in found), found)

        allowed = dict(strict, patternProperties=ALLOWANCE)
        check("is clean with it", not with_plugin(tmp, allowed))

        wrong = dict(strict, patternProperties={
            "^other_data$": {"$comment": "someone else's field"}})
        found = with_plugin(tmp, wrong)
        check("is still flagged when the allowance names another field",
              bool(found), found)

        print("\nwhat the checker must not flag")
        check("an object that already tolerates unknown keys",
              not with_plugin(tmp, {"type": "object",
                                    "properties": {"picks": FIELD}}))
        check("a field that is not a checkbox group",
              not with_plugin(tmp, {"type": "object", "additionalProperties": False,
                                    "properties": {"picks": {"type": "array"}}}))

        print("\nthe companion key is a sibling, so only the immediate parent counts")
        nested = {"type": "object", "additionalProperties": False,
                  "properties": {"feeds": {"type": "object",
                                           "additionalProperties": False,
                                           "properties": {"picks": FIELD}}}}
        found = with_plugin(tmp, nested)
        check("a nested strict parent is flagged, by its dotted path",
              any("feeds.picks" in p for p in found), found)

        nested["properties"]["feeds"]["patternProperties"] = ALLOWANCE
        check("and clean once that parent -- not the root -- allows it",
              not with_plugin(tmp, nested))

        loose_child = {"type": "object", "additionalProperties": False,
                       "properties": {"feeds": {"type": "object",
                                                "properties": {"picks": FIELD}}}}
        check("a strict grandparent alone is not a problem",
              not with_plugin(tmp, loose_child))

    failed = [c for c, ok in results if not ok]
    print("\n%d checks, %d failed" % (len(results), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
