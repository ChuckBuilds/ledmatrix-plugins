#!/usr/bin/env python3
"""
Regression test for saving a custom league (e.g. the English Championship,
'eng.2') from the web UI.

Adding any custom league used to fail with HTTP 400 on save. The web UI's
array-table editor keeps every non-column property of a row in a hidden text
input, so an empty input comes back as null and a list property comes back as
the comma-separated string the user typed. The schema declared those properties
as strict "array"/"object"/"number", so the core's Draft-7 validation rejected
the whole config and blocked the save — regardless of which league code was
entered.

This test rebuilds the exact payload that array-table.js produces for a new row
and asserts (a) it validates against config_schema.json and (b) the plugin
normalizes the nulls/strings back into the shapes the managers expect.

Run: <core-venv>/bin/python plugins/soccer-scoreboard/test_custom_league_config.py
"""

import importlib.util
import json
import re
import sys
import types
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))


def _stub_core_src():
    """Stub the core ``src.*`` modules the plugin imports at load time."""
    def mod(name, **attrs):
        m = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        sys.modules.setdefault(name, m)
        return m

    mod("src")
    mod("src.common")
    mod("src.plugin_system")
    mod("src.logo_downloader", LogoDownloader=object, download_missing_logo=lambda *a, **k: None)
    mod("src.common.scroll_helper", ScrollHelper=object)
    mod("src.plugin_system.base_plugin", BasePlugin=None, VegasDisplayMode=object)
    mod("src.background_data_service", get_background_service=lambda *a, **k: None)


_stub_core_src()

import logging  # noqa: E402

from manager import SoccerScoreboardPlugin  # noqa: E402

SCHEMA = json.loads((plugin_dir / "config_schema.json").read_text())
CUSTOM = SCHEMA["properties"]["custom_leagues"]

results = []


def check(name, passed):
    results.append((name, passed))
    print(f"{'PASS' if passed else 'FAIL'}: {name}")


# =============================================================================
# Simulate the web UI's array-table widget
#
# createAdvancedCell() renders every non-column property as a hidden input whose
# value is String(default) (so [] -> "", undefined -> "", {} -> "[object
# Object]"), and getValue() reads it back through coerceValue(), which maps ""
# to null. Reproducing that here is what makes this a real regression test for
# the save path rather than a hand-written payload.
# =============================================================================


def js_string(value):
    """JavaScript String(value) for the values the widget stores."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ",".join(str(v) for v in value)
    if isinstance(value, dict):
        return "[object Object]"
    return str(value)


def coerce_value(text, type_hint):
    """array-table.js coerceValue()."""
    if text == "":
        return None
    if type_hint == "integer":
        return int(text)
    if type_hint == "number":
        return float(text)
    if type_hint == "boolean":
        return text in ("true", "1")
    return text


def prop_type(prop_schema):
    """The widget's `Array.isArray(type) ? type.find(t => t !== 'null')` rule."""
    declared = prop_schema.get("type")
    if isinstance(declared, list):
        return next((t for t in declared if t != "null"), "string")
    return declared or "string"


def widget_row(typed_values):
    """Build the row object array-table.js submits for one custom league."""
    columns = CUSTOM["x-columns"]
    props = CUSTOM["items"]["properties"]
    row = {}

    # Visible column cells: user-typed value, else the schema default.
    for column in columns:
        col_schema = props[column]
        col_type = prop_type(col_schema)
        default = col_schema.get("default", False if col_type == "boolean" else "")
        row[column] = typed_values.get(column, default)

    # Hidden advanced cell: one flat input per non-column property, one level of
    # nesting deep, round-tripped through String() and coerceValue().
    for name, prop_schema in props.items():
        if name in columns:
            continue
        declared = prop_type(prop_schema)
        if declared == "object" and "properties" in prop_schema:
            for sub_name, sub_schema in prop_schema["properties"].items():
                value = typed_values.get(name, {}).get(sub_name, sub_schema.get("default"))
                row.setdefault(name, {})[sub_name] = coerce_value(
                    js_string(value), prop_type(sub_schema)
                )
        else:
            value = typed_values.get(name, prop_schema.get("default"))
            row[name] = coerce_value(js_string(value), declared)

    return row


def schema_errors(config):
    from jsonschema import Draft7Validator

    return [
        f"{'.'.join(str(p) for p in e.path)}: {e.message}"
        for e in Draft7Validator(SCHEMA).iter_errors(config)
    ]


HAVE_JSONSCHEMA = importlib.util.find_spec("jsonschema") is not None
if not HAVE_JSONSCHEMA:  # pragma: no cover - CI installs it with the core
    print("SKIP: jsonschema not installed - schema validation cases skipped")

# --- Case 1: a freshly added Championship row saves ------------------------
championship = widget_row({"name": "Championship", "league_code": "eng.2"})
if HAVE_JSONSCHEMA:
    errors = schema_errors({"enabled": True, "custom_leagues": [championship]})
    check(f"new custom league row validates (errors: {errors})", errors == [])

    # --- Case 2: favorite/exclude teams typed in the row editor ------------
    with_teams = widget_row({
        "name": "Championship",
        "league_code": "eng.2",
        "favorite_teams": "IPS, NOR",
        "exclude_teams": "SOU",
    })
    errors = schema_errors({"enabled": True, "custom_leagues": [with_teams]})
    check(f"comma-separated team lists validate (errors: {errors})", errors == [])

    # --- Case 3: a cleared advanced number is not a save blocker ----------
    cleared = widget_row({"name": "Championship", "league_code": "eng.2"})
    cleared["live_game_duration"] = None
    cleared["game_limits"]["recent_games_to_show"] = None
    cleared["priority"] = None
    errors = schema_errors({"enabled": True, "custom_leagues": [cleared]})
    check(f"cleared numeric fields validate (errors: {errors})", errors == [])

    # --- Case 4: name and league_code are still required ------------------
    errors = schema_errors({"enabled": True, "custom_leagues": [{"league_code": "eng.2"}]})
    check("missing name still rejected", any("name" in e for e in errors))

# --- Case 5: league_code pattern accepts real ESPN codes ------------------
pattern = re.compile(CUSTOM["items"]["properties"]["league_code"]["pattern"])
for code in ("eng.2", "eng.3", "eng.fa", "eng.league_cup", "mex.1",
             "uefa.champions", "conmebol.libertadores", "usa.ncaa.m.1"):
    check(f"league_code pattern accepts {code}", pattern.match(code) is not None)
for code in ("eng2", "ENG.2", "eng.2 ", "english championship", ""):
    check(f"league_code pattern rejects {code!r}", pattern.match(code) is None)


# =============================================================================
# Normalization: what the plugin does with the payload once it is saved
# =============================================================================


def make_plugin(custom_leagues):
    instance = SoccerScoreboardPlugin.__new__(SoccerScoreboardPlugin)
    instance.logger = logging.getLogger("test-soccer-custom-leagues")
    instance.config = {"enabled": True, "custom_leagues": custom_leagues}
    instance.display_manager = None
    instance.cache_manager = None
    instance.plugin_manager = None
    return instance


plugin = make_plugin([widget_row({
    "name": "Championship",
    "league_code": " ENG.2 ",
    "favorite_teams": "IPS, NOR",
    "exclude_teams": "SOU",
})])
plugin._normalize_custom_leagues()
league = plugin.config["custom_leagues"][0]

check("league_code trimmed and lowercased", league["league_code"] == "eng.2")
check("favorite_teams split into a list", league["favorite_teams"] == ["IPS", "NOR"])
check("exclude_teams split into a list", league["exclude_teams"] == ["SOU"])
check("null modes dropped so defaults apply",
      league.get("dynamic_duration", {}).get("modes", {}) == {})
check("null max_duration_seconds dropped",
      "max_duration_seconds" not in league.get("dynamic_duration", {}))
check("defaults survive normalization", league["live_game_duration"] == 20)

# Values the widget never nulls out must be untouched.
check("display_modes preserved", league["display_modes"]["live"] is True)
check("priority preserved", league["priority"] == 50)

# A row with everything cleared falls back to defaults instead of crashing.
cleared_row = widget_row({"name": "Championship", "league_code": "eng.2"})
cleared_row["favorite_teams"] = None
cleared_row["exclude_teams"] = None
cleared_row["display_modes"] = None
cleared_row["game_limits"] = None
cleared_row["filtering"] = None
cleared_row["dynamic_duration"] = None
plugin = make_plugin([cleared_row, "not-a-dict"])
plugin._normalize_custom_leagues()
check("malformed entries dropped", len(plugin.config["custom_leagues"]) == 1)
cleared_league = plugin.config["custom_leagues"][0]
check("null containers dropped",
      not any(k in cleared_league for k in
              ("favorite_teams", "display_modes", "game_limits", "filtering",
               "dynamic_duration")))

adapted = plugin._adapt_config_for_custom_league(cleared_league)["soccer_eng.2_scoreboard"]
check("adapter falls back to empty favorites", adapted["favorite_teams"] == [])
check("adapter falls back to default durations", adapted["live_game_duration"] == 20)
check("adapter enables all display modes by default",
      adapted["display_modes"]["soccer_eng.2_live"] is True)

# supports_dynamic_duration() reads dynamic_duration/modes with .get() chains and
# used to hit AttributeError when either arrived as null.
plugin._league_registry = {"eng.2": {"is_custom": True, "enabled": True}}
plugin._custom_league_map = {"eng.2": cleared_league}
plugin.is_enabled = True
plugin._current_display_league = "eng.2"
plugin._current_display_mode_type = "live"
check("supports_dynamic_duration survives a cleared row",
      plugin.supports_dynamic_duration() is False)
check("get_dynamic_duration_cap survives a cleared row",
      plugin.get_dynamic_duration_cap() is None)

print()
failed = [case for case, passed in results if not passed]
print(f"{len(results) - len(failed)}/{len(results)} passed")
if failed:
    for case in failed:
        print(f"  FAILED: {case}")
    sys.exit(1)
