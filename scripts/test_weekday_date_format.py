#!/usr/bin/env python3
"""Every scoreboard that offers date_format "weekday" must actually render it.

`scroll_card.date_format` is an enum in each scoreboard's config_schema.json,
and "weekday" is one of the documented choices ('weekday "Fri Sep 19"'). Seven
of the eight game_renderer.py copies reached for `datetime`, `timezone` and
`ZoneInfo` without importing any of them, so selecting that option raised
NameError -- and neither helper's except clause catches NameError:

    _weekday_for   except (ValueError, TypeError)
    _card_tzinfo   except (KeyError, ValueError, TypeError, OSError)

so it propagated out of the render instead of falling back. Only
hockey-scoreboard had the imports, which is why the bug survived: the harness
and the goldens all render the default "abbrev" format and never touch the
weekday branch.

A linter would catch the missing name, but the thing worth guarding is the
behaviour: the option is offered, so it has to work. Each plugin is exercised
in its own subprocess because every copy is imported as the bare module name
`game_renderer` and they would otherwise shadow one another.

Run: <core-venv>/bin/python scripts/test_weekday_date_format.py
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

CORE = None
for _c in (os.environ.get("LEDMATRIX_CORE", ""),
           str(REPO.parent / "LEDMatrix"),
           str(Path.home() / "projects" / "LEDMatrix")):
    if _c and (Path(_c) / "assets" / "fonts").is_dir():
        CORE = Path(_c)
        break
if CORE is None:
    print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
    sys.exit(2)

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

# 01:00 UTC on the Tuesday is still 21:00 on the Monday in New York, so a
# result of "Tue" means _card_tzinfo() was skipped or silently fell back to
# UTC. That distinction is the only thing separating a working timezone
# conversion from one that merely does not crash.
PROBE = r'''
import os, sys, logging
CORE, PLUGIN = sys.argv[1], sys.argv[2]
sys.path.insert(0, CORE); sys.path.insert(0, os.path.join(CORE, "src"))
sys.path.insert(0, PLUGIN)
os.chdir(CORE); logging.disable(logging.CRITICAL)
import json
import game_renderer as gr

# Windows has no system tz database; without the tzdata package ZoneInfo
# raises and the renderer correctly falls back to UTC. That is an environment
# limitation, not a defect, so report it and let the caller skip that check.
try:
    from zoneinfo import ZoneInfo as _ZI
    _ZI("America/New_York")
    tz_available = True
except Exception:
    tz_available = False

game = {"game_date": "10/12", "start_time_utc": "2026-10-13T01:00:00Z"}
out = {"tz_available": tz_available}
try:
    r = gr.GameRenderer(128, 64, {"scroll_card": {"date_format": "weekday"},
                                  "timezone": "America/New_York"})
    out["weekday"] = r._format_game_date(game["game_date"], game)
except Exception as e:
    out["weekday_error"] = "%s: %s" % (type(e).__name__, e)
try:
    r = gr.GameRenderer(128, 64, {"scroll_card": {"date_format": "weekday"},
                                  "timezone": "Not/AZone"})
    out["bad_tz"] = r._format_game_date(game["game_date"], game)
except Exception as e:
    out["bad_tz_error"] = "%s: %s" % (type(e).__name__, e)
try:
    r = gr.GameRenderer(128, 64, {})
    out["default"] = r._format_game_date(game["game_date"], game)
except Exception as e:
    out["default_error"] = "%s: %s" % (type(e).__name__, e)
print(json.dumps(out))
'''

results = []
skipped_tz = []


def check(case, passed):
    results.append((case, passed))
    if not passed:
        print("  [FAIL] %s" % case)


def offers_weekday(plugin_dir):
    schema = plugin_dir / "config_schema.json"
    if not schema.is_file():
        return False
    try:
        return '"weekday"' in schema.read_text(encoding="utf-8")
    except OSError:
        return False


def main():
    targets = sorted(p.parent for p in REPO.glob("plugins/*/game_renderer.py")
                     if offers_weekday(p.parent))
    if not targets:
        print("SKIP: no plugin offers date_format weekday")
        sys.exit(2)

    for plugin in targets:
        name = plugin.name
        proc = subprocess.run([sys.executable, "-c", PROBE, str(CORE), str(plugin)],
                              capture_output=True, text=True)
        stdout = proc.stdout.strip().splitlines()
        if proc.returncode != 0 or not stdout:
            check("%s -- weekday probe ran" % name, False)
            print("        %s" % (proc.stderr.strip().splitlines()[-1:] or ["no output"])[0])
            continue
        try:
            out = json.loads(stdout[-1])
        except ValueError:
            check("%s -- weekday probe returned JSON" % name, False)
            continue

        err = out.get("weekday_error")
        check("%s -- date_format 'weekday' does not raise%s"
              % (name, " (%s)" % err if err else ""), not err)
        if not err:
            value = out["weekday"]
            check("%s -- 'weekday' renders a weekday, got %r" % (name, value),
                  bool(re.match(r"^(%s)\s" % "|".join(WEEKDAYS), value)))
            # UTC would say Tue; New York says Mon
            if out.get("tz_available"):
                check("%s -- the configured timezone is applied, got %r" % (name, value),
                      value.startswith("Mon"))
            else:
                skipped_tz.append(name)

        bad = out.get("bad_tz_error")
        check("%s -- an unusable timezone falls back instead of raising%s"
              % (name, " (%s)" % bad if bad else ""), not bad)

        dflt = out.get("default_error")
        check("%s -- the default date format still works%s"
              % (name, " (%s)" % dflt if dflt else ""), not dflt)

    if skipped_tz:
        print("  note: no tz database in this environment (pip install tzdata) -- "
              "timezone-conversion check skipped for %d plugin(s)" % len(skipped_tz))

    failed = [c for c, ok in results if not ok]
    print("%d checks across %d plugins, %s"
          % (len(results), len(targets),
             "%d FAILED" % len(failed) if failed else "all passed"))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
