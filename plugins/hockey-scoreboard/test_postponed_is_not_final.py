#!/usr/bin/env python3
"""A postponed, cancelled or suspended game is not a result.

ESPN files those games under status.type.state "post" with both scores "0".
The extractor used `is_final = state == "post"` and hockey.py labelled every
"post" game "Final", so a postponed game reached the Recent screen as
"Final 0-0" -- through is_final, and again through the "final" in period_text
fallback Recent uses for games that look finished.

These checks pin:

  * a real final (completed, STATUS_FINAL) is final;
  * postponed / canceled / suspended are not, even if a feed marks one
    completed;
  * hockey's extractor does not label a postponed game "Final".

Run: <core-venv>/bin/python plugins/hockey-scoreboard/test_postponed_is_not_final.py
"""

import logging
import sys
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

try:
    import sports  # noqa: E402
    import hockey  # noqa: E402
except ImportError as exc:  # needs the LEDMatrix core on PYTHONPATH
    print("SKIP: cannot import the plugin modules (%s)" % exc)
    sys.exit(2)

failures = []


def check(name, ok, detail=None):
    if ok:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s%s" % (name, " -- %r" % (detail,) if detail is not None else ""))
        failures.append(name)


def _type(name, state="post", completed=True, short="Final"):
    return {"name": name, "state": state, "completed": completed,
            "shortDetail": short, "detail": short}


def _period_text(status_type, period=3):
    """Run hockey's extractor over one event with the common part stubbed."""
    status = {"type": status_type, "period": period, "displayClock": "0:00"}
    details = {
        "id": "1", "home_abbr": "TOR", "away_abbr": "MTL",
        "is_final": sports.SportsCore._status_is_final(status_type),
        "is_live": status_type.get("state") == "in",
        "is_upcoming": status_type.get("state") == "pre",
        "game_time": "7:00 PM",
    }
    probe_cls = type("HockeyProbe", (hockey.Hockey,), {
        "_fetch_data": lambda self: {},
        "_extract_game_details_common":
            lambda self, ev: (details, {}, {}, status, None),
    })
    probe = probe_cls.__new__(probe_cls)
    probe.logger = logging.getLogger("postponed_probe")
    event = {"competitions": [{"status": status}]}
    result = probe._extract_game_details(event)
    return (result or details).get("period_text")


def main():
    is_final = sports.SportsCore._status_is_final

    print("real finals")
    check("completed STATUS_FINAL is final", is_final(_type("STATUS_FINAL")))
    check("completed STATUS_FINAL (OT) is final",
          is_final(_type("STATUS_FINAL", short="Final/OT")))

    print("\nESPN 'post' games that are not results")
    for name, short in (("STATUS_POSTPONED", "Postponed"),
                        ("STATUS_CANCELED", "Canceled"),
                        ("STATUS_SUSPENDED", "Suspended")):
        check("%s with completed=False is not final" % name,
              not is_final(_type(name, completed=False, short=short)))
        check("%s is not final even if marked completed" % name,
              not is_final(_type(name, completed=True, short=short)))
    check("state post without the completed flag is not final",
          not is_final({"name": "STATUS_FINAL", "state": "post"}))
    check("live and scheduled games are not final",
          not is_final(_type("STATUS_IN_PROGRESS", state="in"))
          and not is_final(_type("STATUS_SCHEDULED", state="pre", completed=False)))
    check("garbage status does not raise", not is_final(None))

    print("\nhockey's period label")
    label = _period_text(_type("STATUS_POSTPONED", completed=False, short="Postponed"))
    check("a postponed game is not labelled Final",
          "final" not in str(label).lower(), label)
    label = _period_text(_type("STATUS_FINAL"))
    check("a real final is still labelled Final", label == "Final", label)
    label = _period_text(_type("STATUS_FINAL"), period=4)
    check("an overtime final is still Final/OT", label == "Final/OT", label)

    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
