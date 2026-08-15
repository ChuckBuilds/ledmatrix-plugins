#!/usr/bin/env python3
"""
Tests that the partial schedule fetch covers the same span as the full one.

Reported by a user: Manchester United never appeared even though their next
fixture was 22 August, and with favourites turned off the board showed exactly
one Premier League game -- Arsenal v Coventry.

Reproduced against ESPN on 2026-08-14:

    -2w..+1w  20260731-20260821 ->  1 event   (COV @ ARS on the 21st)
    -2w..+4w  20260731-20260911 -> 30 events  (MAN @ HUL on the 22nd, ...)

_get_weeks_data() is the partial that serves the display until the background
fetch lands, and it ended a week earlier than _fetch_soccer_api_data(), the
fetch it substitutes for. Invisible in a league that plays daily; severe in one
that plays weekly, where a whole matchweek can sit in the gap. The Premier
League's opening matchweek was 21-24 August, so a +7d horizon caught the Friday
opener and hid the other nine fixtures.

Run: <core-venv>/bin/python plugins/soccer-scoreboard/test_schedule_horizon.py
"""

import ast
import sys
from datetime import datetime, timedelta
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))
for candidate in (Path("/home/rackpi/projects/LEDMatrix"),
                  plugin_dir.parents[2] / "LEDMatrix"):
    if (candidate / "src" / "plugin_system" / "base_plugin.py").exists():
        sys.path.insert(0, str(candidate))
        break

import sports  # noqa: E402

failures = []


def check(label, ok):
    print(("  PASS  " if ok else "  FAIL  ") + label)
    if not ok:
        failures.append(label)


def main():
    print("the partial fetch is not narrower than the fetch it stands in for")
    # The full fetch's span, read from soccer_managers so the two cannot drift
    # apart silently: that file is where the background fetch is built.
    managers_src = (plugin_dir / "soccer_managers.py").read_text(encoding="utf-8")
    tree = ast.parse(managers_src)
    full = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                 and n.name == "_fetch_soccer_api_data"), None)
    check("_fetch_soccer_api_data exists", full is not None)

    deltas = []
    for node in ast.walk(full):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "timedelta":
            for kw in node.keywords:
                if isinstance(kw.value, ast.Constant):
                    deltas.append((kw.arg, kw.value.value))
    full_days = max((v for unit, v in deltas if unit == "days"), default=None)
    check("its horizon is discoverable (%s)" % deltas, full_days is not None)

    forward = sports._SCHEDULE_WINDOW_FORWARD
    back = sports._SCHEDULE_WINDOW_BACK
    check("the partial's forward horizon is a timedelta",
          isinstance(forward, timedelta))
    if full_days is not None:
        check("partial forward (%dd) >= full forward (%dd)"
              % (forward.days, full_days), forward.days >= full_days)
        check("partial back (%dd) >= full back (%dd)"
              % (back.days, full_days), back.days >= full_days)

    print("\nthe reported fixture falls inside the horizon")
    # The user's case, as dates rather than a live API call so the test stays
    # deterministic: on 2026-08-14, Man Utd played on the 22nd.
    today = datetime(2026, 8, 14)
    fixture = datetime(2026, 8, 22)
    check("a fixture 8 days out is covered", today + forward >= fixture)
    check("...and was not, at the old +7d horizon",
          today + timedelta(days=7) < fixture)

    print("\nthe whole opening matchweek is covered, not just its first day")
    # 21-24 August. Catching only the Friday game is what produced
    # "the only game it's showing is Arsenal vs. Coventry".
    matchweek_end = datetime(2026, 8, 24)
    check("the matchweek's last day is inside the horizon",
          today + forward >= matchweek_end)

    print("\n_get_weeks_data uses the constants rather than its own numbers")
    src = (plugin_dir / "sports.py").read_text(encoding="utf-8")
    fn = next((n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef)
               and n.name == "_get_weeks_data"), None)
    check("_get_weeks_data exists", fn is not None)
    literal_deltas = [n for n in ast.walk(fn)
                      if isinstance(n, ast.Call)
                      and getattr(n.func, "id", "") == "timedelta"]
    check("no hard-coded window remains in it", not literal_deltas)
    names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    check("it references both constants",
          {"_SCHEDULE_WINDOW_BACK", "_SCHEDULE_WINDOW_FORWARD"} <= names)

    print("\n%s" % ("FAILED: %d" % len(failures) if failures
                    else "All checks passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
