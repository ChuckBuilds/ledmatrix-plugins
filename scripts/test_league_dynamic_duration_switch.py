#!/usr/bin/env python3
"""A league's "Enable dynamic duration" switch must turn dynamic duration on.

Every scoreboard schema offers two switches: ``dynamic_duration.enabled``
("Enable dynamic duration for NFL games") and one per mode under
``dynamic_duration.modes.<live|recent|upcoming>.enabled``. All default to off,
and the core fills every schema default into the config before the plugin
sees it. ``supports_dynamic_duration`` checked the mode switch first and
returned it whenever it was present -- which, after the fill, is always -- so
the league switch was never read in eight plugins.

Now: the league switch turns every mode on, a mode switch turns on just that
mode, and with both off it is off. Each plugin runs in its own interpreter,
since every one of them is a module named ``manager``.

Run: LEDMATRIX_CORE=/path/to/LEDMatrix python scripts/test_league_dynamic_duration_switch.py
Exit 0 pass, 1 fail, 2 skip (no core checkout).
"""
import json
import os
import subprocess  # nosec B404
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUGINS = REPO / "plugins"

#: plugin -> (where its dynamic_duration block lives, a display mode to probe)
CASES = {
    "football-scoreboard": (["nfl"], "nfl_recent"),
    "hockey-scoreboard": (["nhl"], "nhl_recent"),
    "lacrosse-scoreboard": (["ncaa_mens"], "ncaa_mens_lacrosse_recent"),
    "basketball-scoreboard": (["nba"], "nba_recent"),
    "baseball-scoreboard": (["mlb"], "mlb_recent"),
    "soccer-scoreboard": (["leagues", "eng.1"], "soccer_eng.1_recent"),
    "afl-scoreboard": ([], "afl_recent"),
    "nrl-scoreboard": ([], "nrl_recent"),
}

PROBE = r'''
import json, logging, sys
from unittest.mock import MagicMock
sys.path.insert(0, sys.argv[1])
import manager as m
cls = next(o for o in vars(m).values() if isinstance(o, type)
           and hasattr(o, "supports_dynamic_duration") and o.__module__ == "manager")
path, league_key, cases = json.loads(sys.argv[2])
out = []
for league_on, mode_on in cases:
    block = {"enabled": league_on, "modes": {
        "live": {"enabled": False}, "recent": {"enabled": mode_on},
        "upcoming": {"enabled": False}}}
    config = {"enabled": True}
    node = config
    for step in path:
        node = node.setdefault(step, {})
    node.update({"enabled": True, "dynamic_duration": block})
    if not path:
        config["dynamic_duration"] = block
    p = cls.__new__(cls)
    p.config = config
    p.enabled = True
    p.is_enabled = True
    p.logger = logging.getLogger("probe")
    p._current_display_league = league_key
    p._current_display_mode_type = "recent"
    if hasattr(cls, "_get_league_config"):
        p._league_registry = {}
    try:
        got = p.supports_dynamic_duration()
    except TypeError:
        got = p.supports_dynamic_duration("recent")
    out.append(bool(got))
print(json.dumps(out))
'''


def find_core():
    for candidate in (os.environ.get("LEDMATRIX_CORE"), REPO.parent / "LEDMatrix"):
        if candidate and (Path(candidate) / "src" / "plugin_system").is_dir():
            return Path(candidate)
    return None


def main():
    core = find_core()
    if core is None:
        print("SKIP: no LEDMatrix core checkout (set LEDMATRIX_CORE)")
        return 2
    # (league switch, recent-mode switch) -> expected
    cases = [(False, False), (True, False), (False, True), (True, True)]
    expected = [False, True, True, True]
    env = dict(os.environ, PYTHONPATH=str(core), EMULATOR="true")
    failed = 0
    for plugin, (path, _mode) in CASES.items():
        league_key = path[-1] if path else plugin.split("-")[0]
        # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
        proc = subprocess.run(  # nosec B603 - list argv, no shell: this interpreter and repo paths
            [sys.executable, "-c", PROBE, str(PLUGINS / plugin),
             json.dumps([path, league_key, cases])],
            capture_output=True, text=True, cwd=str(core), env=env)
        try:
            got = json.loads(proc.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            print("FAIL  %s: probe did not run\n%s" % (plugin, proc.stderr[-1500:]))
            failed += 1
            continue
        ok = got == expected
        failed += not ok
        print("%s  %s: league switch alone %s dynamic duration%s"
              % ("PASS" if ok else "FAIL", plugin,
                 "enables" if got[1] else "does NOT enable",
                 "" if ok else "  (league/mode off/off, on/off, off/on, on/on -> %s)" % got))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
