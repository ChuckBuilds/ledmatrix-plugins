#!/usr/bin/env python3
"""PWHL specifics on top of the shared HockeyTech adapter.

test_hockeytech_leagues.py covers the adapter for both HockeyTech leagues.
These checks pin what is particular to the PWHL, or was found wrong after it
shipped:

  * the clock: HockeyTech sends "MM:SS", and core's game-over check only reads
    "0:00" as zero, so a decided game at the horn would otherwise stay "live";
  * Las Vegas is VEG in the 2026-27 preseason and VGS in the regular season:
    games and a favourite saved under either spelling both arrive as VGS;
  * crests ship with the plugin, one for every team the picker offers, and the
    feed's 50x50 thumbnail URL is asked for at full size;
  * celebrations: a favourite's goal and win, seen through real live polls,
    arm the takeover as they do for ESPN leagues;
  * settings: the block draws nothing the feed cannot back.

Run: <core-venv>/bin/python plugins/hockey-scoreboard/test_pwhl_feed.py
"""
import importlib.util
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

logging.disable(logging.CRITICAL)

try:
    from data_sources import HockeyTechDataSource  # noqa: E402
    from pwhl_managers import PWHL_LOGO_DIR  # noqa: E402
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


class FakeCache:
    def __init__(self):
        self.store = {}

    def get(self, key, max_age=300, memory_ttl=None):
        return self.store.get(key)

    def set(self, key, data, ttl=None):
        self.store[key] = data


def scorebar_game(game_id, when, status="4", home="MTL", away="TOR", home_id="3",
                  away_id="6", home_goals="3", away_goals="2", period="3", short="3",
                  clock="00:00", text="Final", intermission="0"):
    """A scorebar game with the fields the adapter reads (real key names)."""
    return {
        "ID": game_id, "GameDateISO8601": when.isoformat(), "GameStatus": status,
        "GameStatusString": text, "GameStatusStringLong": text, "Period": period,
        "PeriodNameShort": short, "GameClock": clock, "Intermission": intermission,
        "HomeID": home_id, "HomeCode": home, "HomeNickname": home, "HomeGoals": home_goals,
        "HomeLogo": "https://assets.leaguestat.com/pwhl/logos/50x50/%s.png" % home_id,
        "VisitorID": away_id, "VisitorCode": away, "VisitorNickname": away,
        "VisitorGoals": away_goals,
        "VisitorLogo": "https://assets.leaguestat.com/pwhl/logos/50x50/%s.png" % away_id,
    }


def plugin(favorites=()):
    spec = importlib.util.spec_from_file_location("manager", HERE / "manager.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    dm = MagicMock()
    dm.width, dm.height = 128, 32
    dm.matrix = MagicMock(width=128, height=32)
    config = {"enabled": True, "timezone": "UTC", "nhl": {"enabled": False},
              "pwhl": {"enabled": True, "teams": {"favorite_teams": list(favorites)}}}
    return mod.HockeyScoreboardPlugin("hockey-scoreboard", config, dm, FakeCache(), MagicMock())


def main():
    now = datetime.now(timezone(timedelta(hours=-5)))
    p = plugin(favorites=["MTL", "VEG"])
    recent, live = p.pwhl_recent, p.pwhl_live

    def details(**kw):
        when = kw.pop("when", now - timedelta(days=1))
        return recent._extract_game_details(
            HockeyTechDataSource.to_espn_event(scorebar_game("1", when, **kw)))

    print("the clock")
    playing = details(when=now, status="2", period="2", short="2", clock="07:12",
                      text="In Progress")
    check("a live clock reads M:SS", playing["clock"] == "7:12", playing["clock"])
    over = details(when=now, status="2", clock="00:00", text="In Progress")
    check("core's game-over check ends a decided game at 0:00 of the third",
          live._is_game_really_over(over), over)

    print("\nLas Vegas")
    vegas = details(away="VEG", away_id="12")
    check("a preseason VEG game arrives as VGS", vegas["away_abbr"] == "VGS", vegas)
    check("a favourite saved as VEG is read as VGS", "VGS" in recent.favorite_teams,
          recent.favorite_teams)

    print("\nlogos")
    final = details()
    check("the logo path points at the shipped folder",
          Path(final["home_logo_path"]) == PWHL_LOGO_DIR / "MTL.png", final["home_logo_path"])
    check("a missing crest is fetched at full size, not the 50x50 thumbnail",
          final["home_logo_url"] == "https://assets.leaguestat.com/pwhl/logos/3.png",
          final["home_logo_url"])
    with open(HERE / "config_schema.json", encoding="utf-8") as fh:
        block = json.load(fh)["properties"]["pwhl"]["properties"]
    picker = block["teams"]["properties"]["favorite_teams"]["items"]["enum"]
    missing = [c for c in picker if not (PWHL_LOGO_DIR / ("%s.png" % c)).is_file()]
    check("every team in the picker has a shipped crest (%d teams)" % len(picker),
          picker and not missing, missing)

    print("\ncelebrations")
    games = []
    live.data_source.fetch_scorebar = lambda *a, **k: games

    def poll(**kw):
        games[:] = [scorebar_game("20", now, **kw)]
        live.last_update = 0
        live.active_celebration = None
        live.update()
        return live.active_celebration

    in_play = dict(status="2", period="1", short="1", clock="12:00", text="In Progress")
    check("the first sighting of a live game sets a baseline, no celebration",
          poll(home_goals="0", away_goals="0", **in_play) is None)
    goal = poll(home_goals="1", away_goals="0", **in_play)
    check("the favourite's goal arms a goal celebration",
          goal and goal["kind"] == "goal" and goal["team_abbr"] == "MTL", goal)
    win = poll(home_goals="2", away_goals="1")
    check("the favourite winning arms a win celebration",
          win and win["kind"] == "win" and win["phrase"] == "MTL WINS!", win)

    print("\nsettings")
    drawn = {k for k, v in block["display_options"]["properties"].items()
             if v.get("x-display") != "hidden"}
    check("the only display option drawn is records (no odds, ranks, shots, "
          "power play, scorer card or pop-ups)", drawn == {"show_records"}, drawn)

    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
