#!/usr/bin/env python3
"""The full-screen upcoming scorebug has its own date/time switches.

_upcoming_date_and_time_text feeds the full-screen (switch mode) scorebug, and
it read scroll_card.show_date / show_time -- the scroll and Vegas card
toggles. Turning the date off for the ticker blanked it on the scoreboard too.
football-scoreboard #342 gave the scorebug switch_show_date / switch_show_time,
defaulting on so an untouched panel keeps drawing both lines.

Run: <core-venv>/bin/python plugins/hockey-scoreboard/test_switch_show_date_time.py
"""

import json
import sys
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

try:
    import sports  # noqa: E402
except ImportError as exc:
    print("SKIP: cannot import sports.py (%s)" % exc)
    sys.exit(2)

failures = []


def check(name, ok, detail=None):
    if ok:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s%s" % (name, " -- %r" % (detail,) if detail is not None else ""))
        failures.append(name)


class _Scorebug:
    _upcoming_date_and_time_text = sports.SportsCore._upcoming_date_and_time_text
    _card_option = sports.SportsCore._card_option

    def __init__(self, scroll_card):
        self.config = {"scroll_card": scroll_card}

    def _format_game_date(self, game_date, game=None):
        return "DATE"

    def _format_game_time(self, game_time):
        return "TIME"


def _text(scroll_card):
    return _Scorebug(scroll_card)._upcoming_date_and_time_text("2026-10-07", "19:00")


def main():
    print("defaults")
    check("an empty block draws both", _text({}) == ("DATE", "TIME"), _text({}))

    print("\nscroll card toggles leave the scorebug alone")
    got = _text({"show_date": False, "show_time": False})
    check("show_date/show_time off still draws both", got == ("DATE", "TIME"), got)

    print("\nthe scorebug's own switches")
    got = _text({"switch_show_date": False})
    check("switch_show_date off hides only the date", got == ("", "TIME"), got)
    got = _text({"switch_show_time": False})
    check("switch_show_time off hides only the time", got == ("DATE", ""), got)

    print("\nthe schema offers them")
    schema = json.loads((plugin_dir / "config_schema.json").read_text(encoding="utf-8"))
    card = schema["properties"]["scroll_card"]["properties"]
    for key in ("switch_show_date", "switch_show_time"):
        check("%s declared, default true" % key,
              card.get(key, {}).get("default") is True, card.get(key))

    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
