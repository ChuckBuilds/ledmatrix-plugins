#!/usr/bin/env python3
"""
Tests that the MiLB level selector actually reaches the manager.

``BaseMiLBManager`` has read ``mode_config["sport_ids"]`` since it was written
-- which levels of the minors to fetch from the MLB Stats API (AAA=11, AA=12,
High-A=13, Single-A=14). But ``_adapt_config_for_manager`` is a whitelist, and
it never carried the key, so nothing a user could write in config.json ever
arrived. That is also why config_schema.json had never declared it: a setting
that cannot take effect looks like one that does not exist.

The translation now forwards it, which introduces the usual whitelist hazard --
``league_config.get("sport_ids")`` puts a literal ``None`` in the dict when the
key is absent, and ``mode_config.get("sport_ids", DEFAULT)`` returns that None
rather than the default, because the key *is* present. So the reader coerces
rather than trusting the shape.

These checks pin:

  * the key survives the translation, unmangled;
  * absent, empty, or unusable input falls back to all four levels -- a MiLB
    board with no levels selected fetches nothing and reads as broken;
  * the web UI's string form ("11") is accepted, since form values post as text;
  * an unknown id is dropped rather than passed to the API;
  * a real selection comes through in order, without duplicates;
  * the schema declares it, so it can be reached from the config form at all.

Run: <core-venv>/bin/python plugins/baseball-scoreboard/test_milb_sport_ids.py
"""

# A test harness: it reaches into protected members on purpose and calls
# unbound methods against stand-in objects.
# pylint: disable=protected-access,unused-argument,broad-exception-caught

import json
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

import manager as manager_module  # noqa: E402
from milb_managers import BaseMiLBManager, DEFAULT_MILB_SPORT_IDS  # noqa: E402

ALL_LEVELS = [11, 12, 13, 14]
failures = []


def check(label, ok, detail=None):
    print(("  PASS  " if ok else "  FAIL  ") + label
          + ("" if ok or detail is None else "  -- %r" % (detail,)))
    if not ok:
        failures.append(label)


def _plugin(config):
    """The real plugin, built without __init__ -- same shape the sibling
    manager-drift tests use, which is what keeps this honest about the
    translation rather than about a hand-written copy of it."""
    cls = manager_module.BaseballScoreboardPlugin
    obj = cls.__new__(cls)
    obj.config = config
    obj.logger = logging.getLogger("milb_sport_ids_probe")
    obj.display_manager = MagicMock()
    obj.cache_manager = MagicMock()
    obj.plugin_manager = MagicMock()
    obj.timezone_str = "America/Chicago"
    return obj


def adapted(league_config, league="milb"):
    plugin = _plugin({league: league_config})
    return plugin._adapt_config_for_manager(league)["%s_scoreboard" % league]


def test_the_key_survives_the_translation():
    print("the selection reaches the manager's config at all")
    check("a chosen pair comes through unmangled",
          adapted({"sport_ids": [11, 12]}).get("sport_ids") == [11, 12],
          adapted({"sport_ids": [11, 12]}).get("sport_ids"))
    check("an absent key is still present in the adapted dict (as None), "
          "which is why the reader coerces",
          "sport_ids" in adapted({}))


def test_the_reader_coerces():
    print("\nanything that would mean 'no levels' falls back to all four")
    normalise = BaseMiLBManager._normalise_sport_ids
    for label, raw in (("unset (None)", None),
                       ("every box cleared", []),
                       ("a hand-edited empty string", ""),
                       ("garbage", {"nope": 1}),
                       ("only unknown ids", [99, 1234])):
        check("%s -> all four" % label, normalise(raw) == ALL_LEVELS,
              normalise(raw))

    print("\n...and a real selection is honoured")
    check("a chosen pair", normalise([11, 12]) == [11, 12], normalise([11, 12]))
    check("order is the user's, not the default's",
          normalise([14, 11]) == [14, 11], normalise([14, 11]))
    check("the web UI's string form is accepted",
          normalise(["11", " 12 "]) == [11, 12], normalise(["11", " 12 "]))
    check("a bare scalar is accepted", normalise(11) == [11], normalise(11))
    check("duplicates collapse", normalise([11, 11, 12]) == [11, 12],
          normalise([11, 11, 12]))
    check("an unknown id is dropped, not sent to the API",
          normalise([11, 99]) == [11], normalise([11, 99]))
    check("the fallback matches the module default",
          normalise(None) == list(DEFAULT_MILB_SPORT_IDS))


def test_the_schema_declares_it():
    print("\nthe config form can reach it")
    schema = json.loads((plugin_dir / "config_schema.json").read_text("utf-8"))
    milb = schema["properties"]["milb"]["properties"]
    check("milb.sport_ids is declared", "sport_ids" in milb)
    if "sport_ids" not in milb:
        return
    prop = milb["sport_ids"]
    check("it offers exactly the four levels the code knows",
          prop.get("items", {}).get("enum") == ALL_LEVELS,
          prop.get("items", {}).get("enum"))
    check("its default matches the code's fallback",
          prop.get("default") == ALL_LEVELS, prop.get("default"))
    check("every level is labelled for the form",
          set(prop.get("x-options", {}).get("labels", {}))
          == {"11", "12", "13", "14"},
          prop.get("x-options"))
    check("it is not hidden", prop.get("x-display") != "hidden")
    check("the other two leagues do not offer it (they are not MiLB)",
          all("sport_ids" not in schema["properties"][lg]["properties"]
              for lg in ("mlb", "ncaa_baseball")))


def main():
    test_the_key_survives_the_translation()
    test_the_reader_coerces()
    test_the_schema_declares_it()

    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
