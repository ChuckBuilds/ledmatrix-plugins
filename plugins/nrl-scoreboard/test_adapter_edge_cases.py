#!/usr/bin/env python3
"""show_records / show_ranking / show_odds resolve with the right precedence.

The schema declares each toggle twice, at the config root and inside
display_options, and the web UI saves schema defaults into both blocks. The
adapter read display_options first and used the root only when the key was
absent, which after a save it never is, so a display_options value still at
its default silently overrode a root toggle the user had changed.

Precedence, ported from afl-scoreboard (PR #485, test_adapter_edge_cases.py):
a changed display_options value, then the root value, then the default.

test_settings_reach_the_manager.py proves each key arrives; this pins the cases
a key-by-key probe cannot express.

Run: <core-venv>/bin/python plugins/nrl-scoreboard/test_adapter_edge_cases.py
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

failures = []


def check(name, ok, detail=None):
    if ok:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s%s" % (name, " -- %r" % (detail,) if detail is not None else ""))
        failures.append(name)


def adapt(config):
    plugin = m.NrlScoreboardPlugin.__new__(m.NrlScoreboardPlugin)
    plugin.logger = logging.getLogger("adapter_probe")
    plugin.cache_manager = MagicMock()
    plugin.plugin_manager = MagicMock()
    plugin.config = config
    return plugin._adapt_config_for_manager()["nrl_scoreboard"]


def main():
    print("a changed display_options value wins over the root duplicates")
    block = adapt({
        "show_records": False, "show_ranking": False, "show_odds": True,
        "display_options": {"show_records": True, "show_ranking": True,
                            "show_odds": False},
    })
    check("show_records", block["show_records"] is True, block["show_records"])
    check("show_ranking", block["show_ranking"] is True, block["show_ranking"])
    check("show_odds", block["show_odds"] is False, block["show_odds"])

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

    print("\ndefaults")
    block = adapt({"display_options": {}})
    check("nothing set anywhere: schema defaults",
          (block["show_records"], block["show_ranking"], block["show_odds"])
          == (False, False, True),
          (block["show_records"], block["show_ranking"], block["show_odds"]))
    block = adapt({"show_records": False, "show_ranking": False, "show_odds": True,
                   "display_options": {"show_records": False, "show_ranking": False,
                                       "show_odds": True}})
    check("both blocks at their defaults: schema defaults",
          (block["show_records"], block["show_ranking"], block["show_odds"])
          == (False, False, True))
    block = adapt({"display_options": None})
    check("a null display_options does not break the translation",
          block["show_odds"] is True, block["show_odds"])

    print("\nroot keys still work alone")
    block = adapt({"show_records": True, "show_odds": False})
    check("root show_records", block["show_records"] is True)
    check("root show_odds", block["show_odds"] is False)

    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
