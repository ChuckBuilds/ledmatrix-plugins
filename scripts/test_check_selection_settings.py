#!/usr/bin/env python3
"""check_selection_settings must pass on this repo, and fail on a real gap.

Two halves, and both matter. The first runs the checker over the plugins as they
actually are, which is what puts it in CI at all -- the workflow runs
scripts/test_*.py, not scripts/check_*.py. The second feeds it a schema with a
known hole, because a checker that cannot fail is indistinguishable from one
that passes, and this repo has been bitten by exactly that: a guard that had
been silently non-functional for as long as it had been "passing".
"""
import copy
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_selection_settings as checker

REPO = Path(__file__).resolve().parents[1]
results = []


def check(case, passed, detail=""):
    results.append((case, passed))
    print("  [%s] %s%s" % ("pass" if passed else "FAIL", case,
                           "" if passed else "  <- " + str(detail)))


def with_plugins(tmp, plugin_id, schema):
    """Run the checker against a single synthetic plugin."""
    d = Path(tmp) / plugin_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "sports.py").write_text("# stand-in\n")
    (d / "config_schema.json").write_text(json.dumps(schema))
    original = checker.PLUGINS
    checker.PLUGINS = Path(tmp)
    try:
        return checker.check_plugin(plugin_id)
    finally:
        checker.PLUGINS = original


def main():
    print("the repo itself passes")
    real = [p for pid in sorted(x.name for x in (REPO / "plugins").iterdir()
                                if (x / "sports.py").exists()
                                and (x / "config_schema.json").exists())
            for p in checker.check_plugin(pid)]
    check("every sports plugin declares the five settings", not real, real)

    good = json.loads((REPO / "plugins" / "football-scoreboard"
                       / "config_schema.json").read_text())

    print("\nand a real gap is caught")
    with tempfile.TemporaryDirectory() as tmp:
        s = copy.deepcopy(good)
        block = s["properties"]["ncaa_fb"]["properties"]["game_limits"]["properties"]
        del block["other_games_divisions"]
        found = with_plugins(tmp, "probe", s)
        check("a missing setting is reported",
              any("other_games_divisions" in p and "missing" in p for p in found), found)

        s = copy.deepcopy(good)
        block = s["properties"]["ncaa_fb"]["properties"]["game_limits"]["properties"]
        del block["other_games_min_quality"]["default"]
        found = with_plugins(tmp, "probe", s)
        check("a setting with no default is reported",
              any("no default" in p for p in found), found)

        s = copy.deepcopy(good)
        block = s["properties"]["ncaa_fb"]["properties"]["game_limits"]["properties"]
        block["other_rotation_interval_seconds"]["maximum"] = 99
        found = with_plugins(tmp, "probe", s)
        check("a range that disagrees with its siblings is reported",
              any("maximum" in p for p in found), found)

        s = copy.deepcopy(good)
        block = s["properties"]["ncaa_fb"]["properties"]["game_limits"]["properties"]
        block["other_upcoming_games_to_show"]["default"] = 20
        found = with_plugins(tmp, "probe", s)
        check("a default above the block's own limit is reported",
              any("above this block's own" in p for p in found), found)

        s = copy.deepcopy(good)
        block = s["properties"]["ncaa_fb"]["properties"]["game_limits"]["properties"]
        block["other_games_divisions"]["items"]["enum"] = ["fbs"]
        found = with_plugins(tmp, "probe", s)
        check("a truncated enum is reported", any("allows" in p for p in found), found)

        # A schema with no game limits at all is not a selection schema, and
        # must not be reported -- most plugins in this repo are not sports.
        found = with_plugins(tmp, "probe", {"properties": {"enabled": {"type": "boolean"}}})
        check("a non-sports schema is left alone", not found, found)

        # A block inside a row editor cannot hold an array setting:
        # array-table.js submits "fbs" where the schema wants ["fbs"], and
        # jsonschema then rejects the entire save. Requiring one there would be
        # requiring a bug -- soccer's custom_leagues is the real instance.
        row_block = {
            "properties": {
                "custom_leagues": {
                    "type": "array",
                    "x-columns": ["name"],
                    "items": {"properties": {"game_limits": {
                        "properties": dict(
                            good["properties"]["eng.1"]["properties"]["game_limits"]["properties"]
                            if "eng.1" in good.get("properties", {}) else {})}}},
                }
            }
        }
        gl = row_block["properties"]["custom_leagues"]["items"]["properties"]["game_limits"]
        gl["properties"] = json.loads(json.dumps(
            good["properties"]["ncaa_fb"]["properties"]["game_limits"]["properties"]))
        gl["properties"].pop("other_games_divisions", None)
        found = with_plugins(tmp, "probe", row_block)
        check("an array setting is not demanded inside a row editor",
              not any("other_games_divisions" in p for p in found), found)
        gl["properties"].pop("other_games_min_quality")
        found = with_plugins(tmp, "probe", row_block)
        check("but a scalar setting still is",
              any("other_games_min_quality" in p for p in found), found)

    failed = [c for c, ok in results if not ok]
    print("\n%d checks, %d failed" % (len(results), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
