#!/usr/bin/env python3
"""The "no favorites" log must not fire when favorites ARE configured.

Reported as "why am I not seeing the upcoming NCAA games when I have NCAA
Football Upcoming set to 3 games?". The limit was working: the board was
showing 3 upcoming games. They were the next 3 in all of college football
rather than the user's teams, because show_favorite_teams_only was off --
having favourites is not enough, the only-flag has to be on too.

What made that hard to see was the log. In sequence, from a real board:

    Favorite teams: ['UGA', 'AU']
    Found 12 favorite team upcoming games
    No favorites configured: showing 3 total upcoming games

Twelve favourite games found, then told there are no favourites. The branch
means "not favourites-ONLY", and it now says so, naming the teams and the
setting to change.

Since then that branch also stopped ignoring favourites altogether -- it shows
them first and tops up with other games -- so the message reports the split and
points at other_upcoming_games_to_show. See test_favorites_are_prioritised.py
for the selection itself; this file only guards the wording.

This drives SportsUpcoming.update() and reads what it logged, rather than
inspecting the source: the wording is the whole point of the change, so the
test has to observe the wording that actually reaches a user's journal.

Run: <core-venv>/bin/python plugins/football-scoreboard/test_favorites_log_says_which_case.py
"""

import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

REPO = Path(__file__).resolve().parents[2]
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
sys.path.insert(0, str(CORE))

results = []


def check(case, passed):
    results.append((case, passed))
    print("  [%s] %s" % ("pass" if passed else "FAIL", case))


def _run(sports, favorites, only_flag):
    """Drive one update() and return everything it logged."""
    messages = []

    probe_cls = type("Probe", (sports.SportsUpcoming,), {
        "_fetch_data": lambda s: {"events": [{"id": f"g{i}"} for i in range(5)]},
        "_extract_game_details": lambda s, ev: {
            "id": ev["id"], "away_abbr": "AAA", "home_abbr": "BBB",
            "start_time_utc": datetime.now(timezone.utc) + timedelta(days=1),
            "is_final": False, "is_live": False, "is_upcoming": True},
        "_fetch_team_rankings": lambda s: None,
    })
    obj = probe_cls.__new__(probe_cls)

    log = logging.getLogger("favorites_probe")
    log.handlers = []
    log.setLevel(logging.INFO)
    log.propagate = False

    class Capture(logging.Handler):
        def emit(self, record):
            messages.append(record.getMessage())

    log.addHandler(Capture())

    obj.logger = log
    obj.is_enabled = True
    obj.last_update = 0
    obj.update_interval = 0
    obj.show_ranking = False
    obj.favorite_teams = favorites
    obj.show_favorite_teams_only = only_flag
    obj.upcoming_games_to_show = 3
    obj.other_upcoming_games_to_show = 3
    # This probe builds the object with __new__, so every attribute __init__
    # would have set has to be supplied here. Miss one and update() raises
    # inside its own try/except, the log line never appears, and the failure
    # reads as "the wording changed" rather than "the object was incomplete".
    obj.other_rotation_interval_seconds = 0
    obj._other_window_start = 0
    obj._other_window_rotated_at = 0.0
    obj.games_list = []
    obj.current_game = None

    sports.SportsUpcoming.update(obj)
    return messages


def main():
    os.chdir(str(CORE))
    import sports

    print("favourites set, only-flag OFF: says so, and names the setting")
    msgs = _run(sports, ["UGA", "AUB"], False)
    joined = "\n".join(msgs)
    check("does NOT claim there are no favourites",
          "No favorites configured" not in joined)
    check("names the configured teams", "UGA" in joined and "AUB" in joined)
    check("names the setting to change",
          "other_upcoming_games_to_show" in joined)
    check("reports the favourite/other split",
          "favorite and" in joined and "other upcoming games" in joined)

    print("\nno favourites at all: the original message still applies")
    msgs = _run(sports, [], False)
    joined = "\n".join(msgs)
    check("says no favourites are configured",
          "No favorites configured" in joined)
    check("does not mention the only-flag", "show_favorite_teams_only" not in joined)

    print("\nfavourites set, only-flag ON: neither message, it filters instead")
    msgs = _run(sports, ["UGA"], True)
    joined = "\n".join(msgs)
    check("no schedule-view message at all",
          "No favorites configured" not in joined
          and "other upcoming games" not in joined)

    failed = [c for c, ok in results if not ok]
    print("\n%d checks, %d failed" % (len(results), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
