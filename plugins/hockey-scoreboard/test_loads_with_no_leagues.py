#!/usr/bin/env python3
"""With no league enabled the plugin must load, and every mode must skip.

validate_config() used to return False when no league was switched on, which
load_plugin() treats as a hard failure -- so a plugin the user had just
enabled never loaded at all. Loading it instead is only safe if its modes then
decline to render: the display controller skips a mode whose display()
returns False, and treats anything else, None included, as "content shown",
holding a blank panel for the mode's full duration.

Run: <core-venv>/bin/python plugins/hockey-scoreboard/test_loads_with_no_leagues.py
"""
import importlib.util
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

logging.disable(logging.CRITICAL)

NO_LEAGUES = {"enabled": True, "nhl": {"enabled": False},
              "ncaa_mens": {"enabled": False}, "ncaa_womens": {"enabled": False}}


def _plugin():
    spec = importlib.util.spec_from_file_location("manager", HERE / "manager.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    dm = MagicMock()
    dm.width, dm.height = 128, 32
    dm.matrix = MagicMock(width=128, height=32)
    return mod.HockeyScoreboardPlugin(
        "hockey-scoreboard", NO_LEAGUES, dm, MagicMock(), MagicMock())


def main() -> int:
    failures = []
    p = _plugin()

    if p.validate_config() is not True:
        failures.append("validate_config() rejected a no-leagues config, so the "
                        "plugin would not load at all")
    else:
        print("  PASS  loads with no leagues enabled")

    for mode in ("nhl_recent", "nhl_upcoming", "nhl_live",
                 "ncaa_mens_recent", "hockey_recent"):
        result = p.display(display_mode=mode)
        if result is not False:
            failures.append(
                f"display({mode!r}) returned {result!r}; the controller only "
                "skips on False, so this holds a blank panel for the whole "
                "mode duration")
        else:
            print(f"  PASS  {mode} declines to render")

    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nAll checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
