#!/usr/bin/env python3
"""background_service timeout, retries and priority reach the managers.

basketball-scoreboard and soccer-scoreboard declare a root background_service
block (request_timeout, max_retries, priority) in their schemas. The config
adapters handed every league manager fixed values (30, 3, 2) instead, so the
settings did nothing. The managers read them from mode_config's
background_service, so that is what is checked here, for a built-in league
and, in soccer, a custom one.

Each plugin runs in its own interpreter, since each has a module named
``manager``.

Run: LEDMATRIX_CORE=/path/to/LEDMatrix python scripts/test_background_service_settings.py
Exit 0 pass, 1 fail, 2 skip (no core checkout).
"""
import json
import os
import subprocess  # nosec B404
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUGINS = REPO / "plugins"

PROBE = r'''
import json, logging, sys
sys.path.insert(0, sys.argv[1])
logging.disable(logging.CRITICAL)
from src.plugin_system.testing.mocks import MockCacheManager
import manager as m
cls = next(o for o in vars(m).values() if isinstance(o, type)
           and o.__module__ == "manager" and hasattr(o, "_adapt_config_for_manager"))
p = object.__new__(cls)
p.logger = logging.getLogger("probe")
p.cache_manager = MockCacheManager()
p.plugin_manager = None
bg = {"request_timeout": 12, "max_retries": 5, "priority": 4}
out = {}
if sys.argv[2] == "basketball":
    p.config = {"background_service": bg, "nba": {"enabled": True}}
    blocks = {"nba": p._adapt_config_for_manager("nba")}
else:
    p.config = {"background_service": bg, "leagues": {"eng.1": {"enabled": True}}}
    blocks = {"eng.1": p._adapt_config_for_manager("eng.1"),
              "custom league": p._adapt_config_for_custom_league(
                  {"league_code": "xyz", "name": "X", "enabled": True})}
for name, adapted in blocks.items():
    got = [v.get("background_service") for v in adapted.values() if isinstance(v, dict)]
    out[name] = bg in got
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
    env = dict(os.environ, PYTHONPATH=str(core), EMULATOR="true")
    failed = 0
    for plugin, kind in (("basketball-scoreboard", "basketball"), ("soccer-scoreboard", "soccer")):
        # List argv, no shell: this interpreter and paths inside the repo.
        proc = subprocess.run(  # nosec B603  # nosemgrep
            [sys.executable, "-c", PROBE, str(PLUGINS / plugin), kind],
            capture_output=True, text=True, cwd=str(core), env=env)
        try:
            results = json.loads(proc.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            print("FAIL  %s: probe did not run\n%s" % (plugin, proc.stderr[-1500:]))
            failed += 1
            continue
        for league, ok in results.items():
            failed += not ok
            print("%s  %s: the %s manager gets the configured background_service"
                  % ("PASS" if ok else "FAIL", plugin, league))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
