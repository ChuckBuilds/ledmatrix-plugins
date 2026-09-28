#!/usr/bin/env python3
"""A league's scroll_settings apply to that league's scrolling strip.

Every scoreboard schema offers scroll_settings per league (nfl and ncaa_fb,
nba and wnba, ...). The strip resolved them by walking a ladder of league
keys, and when asked without a league the walk stopped at the first key --
whose block always exists, since the core fills in schema defaults. So:

* football, basketball and baseball read only nfl / nba / mlb's gap,
  separators and card width, whichever league the strip showed;
* in all five, the core configured the helper's speed and dynamic duration
  the same way, once, from the first league.

A strip now uses the settings of the league it shows, and re-applies the
speed when that league changes. Each plugin runs in its own interpreter,
since each has a module named ``scroll_display``.

Run: LEDMATRIX_CORE=/path/to/LEDMatrix python scripts/test_scroll_settings_follow_league.py
Exit 0 pass, 1 fail, 2 skip (no core checkout).
"""
import json
import os
import subprocess  # nosec B404
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUGINS = REPO / "plugins"

#: plugin -> (first league on the ladder, another league)
CASES = {
    "football-scoreboard": ("nfl", "ncaa_fb"),
    "hockey-scoreboard": ("nhl", "ncaa_mens"),
    "lacrosse-scoreboard": ("ncaa_mens", "ncaa_womens"),
    "basketball-scoreboard": ("nba", "wnba"),
    "baseball-scoreboard": ("mlb", "milb"),
}

PROBE = r'''
import json, logging, sys
sys.path.insert(0, sys.argv[1])
first, other = sys.argv[2], sys.argv[3]
from src.plugin_system.testing.visual_display_manager import VisualTestDisplayManager
from scroll_display import ScrollDisplayManager
logging.disable(logging.CRITICAL)
config = {
    first: {"scroll_settings": {"gap_between_games": 10, "scroll_speed": 40}},
    other: {"scroll_settings": {"gap_between_games": 70, "scroll_speed": 90}},
}
manager = ScrollDisplayManager(VisualTestDisplayManager(128, 32), config, logging.getLogger("probe"))
strip = manager.get_scroll_display("recent")
requested = []
resolve = strip._resolve_pixels_per_second
strip._resolve_pixels_per_second = lambda s: requested.append(s.get("scroll_speed")) or resolve(s)
try:
    strip.prepare_scroll_content([{"id": "1"}], "recent", [other], {})
except Exception:
    pass  # the stand-in game need not render; the settings are chosen first
print(json.dumps({"gap": strip._get_scroll_settings().get("gap_between_games"),
                  "speed": requested[-1] if requested else None}))
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
    for plugin, (first, other) in CASES.items():
        # List argv, no shell: this interpreter and paths inside the repo.
        proc = subprocess.run(  # nosec B603  # nosemgrep
            [sys.executable, "-c", PROBE, str(PLUGINS / plugin), first, other],
            capture_output=True, text=True, cwd=str(core), env=env)
        try:
            got = json.loads(proc.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            print("FAIL  %s: probe did not run\n%s" % (plugin, proc.stderr[-1500:]))
            failed += 1
            continue
        for label, ok in (("the %s strip uses %s's gap" % (other, other), got["gap"] == 70),
                          ("the %s strip scrolls at %s's speed" % (other, other), got["speed"] == 90)):
            failed += not ok
            print("%s  %s: %s%s" % ("PASS" if ok else "FAIL", plugin, label,
                                    "" if ok else "  (got %s)" % got))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
