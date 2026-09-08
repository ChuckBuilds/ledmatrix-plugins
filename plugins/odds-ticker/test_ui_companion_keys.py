#!/usr/bin/env python3
"""The schema must accept the companion key the web UI writes beside a
checkbox-group field.

Observed on a live rig: the Odds Ticker showed as **Degraded** in the web UI
with

    Config schema: Field 'leagues.nfl': Additional properties are not allowed
    ('favorite_teams_data' was unexpected); ... nba ... mlb ... nhl

Nothing in this repo or in the core writes that key by name. The web UI does,
structurally: a `checkbox-group` field is rendered with a hidden input named
``{{ full_key }}_data`` holding the selection as JSON
(``web_interface/templates/v3/partials/plugin_config.html``), and
``savePluginConfig`` walks the form by ``name``, so ``leagues.nfl
.favorite_teams_data`` is posted alongside ``leagues.nfl.favorite_teams`` and
saved. The array-of-objects widget already renders its inputs without a
``name`` for exactly this reason -- "rely solely on _data field to prevent key
leakage" -- but the checkbox group still leaks.

So the key lands in config.json every time a user picks teams in the UI, and
the four leagues that use the checkbox-group widget -- and only those four --
are the four named in the message. The other four leagues take plain text
input, get no hidden ``_data`` companion, and were never flagged.

The plugin never reads the key. It just has to tolerate it: every affected
config already contains it, so no core-side fix removes it retroactively.

Run: <core-venv>/bin/python plugins/odds-ticker/test_ui_companion_keys.py
"""

import json
import sys
from pathlib import Path

try:
    from jsonschema import Draft7Validator
except ImportError:
    print("SKIP: jsonschema not installed (it ships with the core venv)")
    sys.exit(2)

SCHEMA = json.loads(
    (Path(__file__).parent / "config_schema.json").read_text(encoding="utf-8")
)

# The leagues block exactly as it was read off the rig that reported Degraded.
BOARD_LEAGUES = {
    "nfl": {"enabled": True, "favorite_teams": ["TB"], "favorite_teams_data": ["TB"]},
    "nba": {"enabled": False, "favorite_teams": [], "favorite_teams_data": []},
    "mlb": {"enabled": True, "favorite_teams": ["TB"], "favorite_teams_data": ["TB"]},
    "nhl": {"enabled": True, "favorite_teams": ["TB"], "favorite_teams_data": ["TB"]},
    "milb": {"enabled": False, "favorite_teams": []},
    "ncaa_fb": {"enabled": True, "favorite_teams": ["UGA", "AUB"]},
    "ncaam_basketball": {
        "enabled": False,
        "favorite_teams": [],
        "show_seeds_in_tournament": False,
    },
    "ncaa_baseball": {"enabled": False, "favorite_teams": []},
}

failures = []


def check(label, condition):
    print("  %s %s" % ("PASS" if condition else "FAIL", label))
    if not condition:
        failures.append(label)


def errors_for(leagues):
    subschema = SCHEMA["properties"]["leagues"]
    return [
        "%s: %s" % (".".join(map(str, e.absolute_path)) or "<root>", e.message)
        for e in Draft7Validator(subschema).iter_errors(leagues)
    ]


def main():
    print("the schema itself is well-formed Draft-07")
    try:
        Draft7Validator.check_schema(SCHEMA)
        check("check_schema accepted it", True)
    except Exception as e:  # pragma: no cover - only on a broken edit
        check("check_schema accepted it (%s)" % e, False)

    print("\nthe config that was flagged on hardware now validates")
    errs = errors_for(BOARD_LEAGUES)
    check("no errors (got: %s)" % (errs or "none"), not errs)

    print("\nevery league carries the allowance, not just today's four")
    # The four flagged leagues are the four the UI renders as a checkbox group.
    # Should another league gain that widget, the same message would return, so
    # the allowance is uniform rather than aimed at the leagues that hurt.
    for name, league in SCHEMA["properties"]["leagues"]["properties"].items():
        allows = "^favorite_teams_data$" in (league.get("patternProperties") or {})
        check("leagues.%s permits favorite_teams_data" % name, allows)

    print("\nthe widget has submitted the key in more than one shape")
    # A hidden input's value is a string; whether it arrives parsed depends on
    # the save path, so the allowance is deliberately unconstrained.
    for shape in (["TB"], '["TB"]', [], ""):
        probe = {"nfl": {"enabled": True, "favorite_teams": ["TB"],
                         "favorite_teams_data": shape}}
        errs = errors_for(probe)
        check("%r accepted (got: %s)" % (shape, errs or "none"), not errs)

    print("\na real typo is still rejected -- this is not additionalProperties: true")
    for typo in ("favorite_team", "favorite_teams_dat", "favourite_teams_data",
                 "favorite_teams_data_extra"):
        probe = {"nfl": {"enabled": True, "favorite_teams": [], typo: []}}
        check("%r rejected" % typo, bool(errors_for(probe)))

    print("\nthe declared settings still validate as before")
    bad_enum = {"nfl": {"enabled": True, "favorite_teams": ["NOT_A_TEAM"]}}
    check("an unknown team abbreviation is rejected", bool(errors_for(bad_enum)))
    bad_type = {"nfl": {"enabled": "yes", "favorite_teams": []}}
    check("a non-boolean 'enabled' is rejected", bool(errors_for(bad_type)))

    print("\n%s" % ("FAILED: %d" % len(failures) if failures else "All checks passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
