#!/usr/bin/env python3
"""Config shapes the manager translation has to survive and resolve correctly.

test_settings_reach_the_manager.py proves each schema key arrives. This pins
the cases a key-by-key probe cannot express:

  * a changed display_options value wins over the older root duplicates
    (the adapter read only the root, and checked a plural show_rankings the
    schema never declared, so the web UI's own toggles were ignored), but a
    display_options value still at its schema default does not override a
    changed root value -- the root was the only toggle that worked up to
    1.24.1, and the web UI saves defaults into both blocks;
  * a legacy root show_rankings still works when nothing else is set;
  * other_games_divisions as a hand-edited string or null: list("fbs") was
    ['f','b','s'], filtering out every non-favourite game, and list(None)
    raised inside the translation, leaving the plugin with no managers;
  * test_mode reaches the managers.

Run: <core-venv>/bin/python plugins/afl-scoreboard/test_adapter_edge_cases.py
"""

import logging
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))

_core = os.environ.get('LEDMATRIX_CORE', '')
for _candidate in (_core, str(PLUGIN_DIR.parents[2] / 'LEDMatrix')):
    if _candidate and (Path(_candidate) / 'src' / 'plugin_system').is_dir():
        sys.path.insert(0, _candidate)
        break
else:
    if not any((Path(p) / 'src' / 'plugin_system').is_dir() for p in sys.path if p):
        print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
        sys.exit(2)

import manager as m  # noqa: E402
import sports  # noqa: E402

failures = []


def check(name, ok, detail=None):
    if ok:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s%s" % (name, " -- %r" % (detail,) if detail is not None else ""))
        failures.append(name)


def adapt(config):
    plugin = m.AflScoreboardPlugin.__new__(m.AflScoreboardPlugin)
    plugin.logger = logging.getLogger("adapter_probe")
    plugin.cache_manager = MagicMock()
    plugin.plugin_manager = MagicMock()
    plugin.config = config
    return plugin._adapt_config_for_manager()["afl_scoreboard"]


def main():
    print("a changed display_options value wins over the root duplicates")
    block = adapt({
        "show_records": False, "show_ranking": False, "show_odds": True,
        "display_options": {"show_records": True, "show_ranking": True,
                            "show_odds": True},
    })
    check("show_records", block["show_records"] is True, block["show_records"])
    check("show_ranking", block["show_ranking"] is True, block["show_ranking"])
    check("show_odds", block["show_odds"] is True, block["show_odds"])

    print("\na saved default in display_options does not undo a root setting")
    block = adapt({
        "show_records": True, "show_ranking": True, "show_odds": False,
        "display_options": {"show_records": False, "show_ranking": False,
                            "show_odds": True},
    })
    check("root show_records true survives a default display_options false",
          block["show_records"] is True, block["show_records"])
    check("root show_ranking true survives a default display_options false",
          block["show_ranking"] is True, block["show_ranking"])
    check("root show_odds false survives a default display_options true",
          block["show_odds"] is False, block["show_odds"])
    block = adapt({"display_options": {}})
    check("nothing set anywhere: schema defaults",
          (block["show_records"], block["show_ranking"], block["show_odds"])
          == (False, False, True))

    block = adapt({"show_odds": True, "display_options": {"show_odds": False}})
    check("an explicit display_options false is not overridden by the root",
          block["show_odds"] is False, block["show_odds"])

    print("\nroot keys still work alone")
    block = adapt({"show_records": True, "show_rankings": True})
    check("root show_records", block["show_records"] is True)
    check("legacy plural show_rankings", block["show_ranking"] is True)

    print("\nother_games_divisions")
    for label, raw, want in (("a string", "fcs", ["fcs"]),
                             ("null", None, []),
                             ("a list", ["fbs"], ["fbs"])):
        try:
            block = adapt({"game_limits": {"other_games_divisions": raw}})
        except Exception as exc:  # the bug: TypeError out of list(None)
            check("%s does not break the translation" % label, False, exc)
            continue
        got = sports.SportsCore._normalise_divisions(block["other_games_divisions"])
        check("%s resolves to %r" % (label, want), got == want, got)

    print("\ntest_mode")
    check("forwarded when set", adapt({"test_mode": True})["test_mode"] is True)
    check("off by default", adapt({})["test_mode"] is False)

    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
