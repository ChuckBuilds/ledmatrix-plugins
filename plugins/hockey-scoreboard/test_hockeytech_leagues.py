#!/usr/bin/env python3
"""OHL and PWHL: the HockeyTech feed reshaped into ESPN events, end to end.

ESPN does not carry either league (its scoreboard answers 400 for both), so
their managers read HockeyTech's public scorebar instead and adapt each game
to ESPN's event shape before anything else sees it. Two things are checked:

1. The adapter, against real scorebar samples saved 2026-10-07
   (test/fixtures/hockeytech_<league>_scorebar.json) plus hand-built live,
   intermission, unofficial-final and postponed games, which no sample had:
   state/name/completed agree with SportsCore._status_is_final, overtime and
   shootout periods use ESPN's numbering, records read W-L-OTL with shootout
   losses folded in, and the logo URL and abbreviation come through.
2. The plugin, constructed with OHL and PWHL enabled and the feed stubbed with
   those samples (dates moved into the window): it loads, Recent and Upcoming
   render a game, and a live game reaches the live mode and has_live_content.

No network: fetch_scorebar is replaced, and logos are written locally.

Run: <core-venv>/bin/python plugins/hockey-scoreboard/test_hockeytech_leagues.py
"""

import copy
import json
import logging
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

logging.disable(logging.CRITICAL)

try:
    from PIL import Image
    from data_sources import HockeyTechDataSource
    import sports
except ImportError as e:  # no core on the path
    print(f"SKIP: core modules unavailable ({e})")
    sys.exit(2)

FIXTURES = HERE / "test" / "fixtures"

failures = []


def check(name, ok, detail=None):
    if ok:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}" + ("" if detail is None else f"  -- {detail!r}"))
        failures.append(name)


def _games(league):
    with open(FIXTURES / f"hockeytech_{league}_scorebar.json", encoding="utf-8") as fh:
        return json.load(fh)["SiteKit"]["Scorebar"]


def _find(games, **want):
    return next(g for g in games
                if all(str(g.get(k)) == v for k, v in want.items()))


def _status(event):
    return event["competitions"][0]["status"]


def _side(event, home_away):
    return next(c for c in event["competitions"][0]["competitors"]
                if c["homeAway"] == home_away)


def check_adapter():
    print("the scorebar adapts to ESPN events")
    for league in ("ohl", "pwhl"):
        games = _games(league)
        events = [HockeyTechDataSource.to_espn_event(g) for g in games]
        check(f"{league}: every sample game adapts", all(events), len(events))

        final = _find(games, GameStatus="4", GameStatusStringLong="Final")
        ev = HockeyTechDataSource.to_espn_event(final)
        st = _status(ev)
        check(f"{league}: a final is post/STATUS_FINAL/completed",
              (st["type"]["state"], st["type"]["name"], st["type"]["completed"])
              == ("post", "STATUS_FINAL", True), st["type"])
        check(f"{league}: _status_is_final agrees",
              sports.SportsCore._status_is_final(st["type"]) is True)
        check(f"{league}: regulation final is period 3", st["period"] == 3, st["period"])
        home = _side(ev, "home")
        check(f"{league}: abbreviation from HomeCode",
              home["team"]["abbreviation"] == final["HomeCode"], home["team"])
        check(f"{league}: score from HomeGoals",
              home["score"] == str(int(final["HomeGoals"])), home["score"])
        check(f"{league}: logo URL from HomeLogo",
              home["team"]["logo"] == final["HomeLogo"]
              and "leaguestat.com" in home["team"]["logo"], home["team"]["logo"])
        otl = int(final["HomeOTLosses"]) + int(final["HomeShootoutLosses"])
        want = f"{int(final['HomeWins'])}-{int(final['HomeRegulationLosses'])}-{otl}"
        check(f"{league}: record is W-L-OTL", home["records"][0]["summary"] == want,
              (home["records"][0]["summary"], want))

        sched = _find(games, GameStatus="1")
        st = _status(HockeyTechDataSource.to_espn_event(sched))
        check(f"{league}: a scheduled game is pre/STATUS_SCHEDULED",
              (st["type"]["state"], st["type"]["name"], st["type"]["completed"])
              == ("pre", "STATUS_SCHEDULED", False), st["type"])
        check(f"{league}: its detail is the start time",
              st["type"]["shortDetail"] == sched["GameStatusStringLong"],
              st["type"]["shortDetail"])

    ohl = _games("ohl")
    st = _status(HockeyTechDataSource.to_espn_event(
        _find(ohl, GameStatusStringLong="Final OT")))
    check("ohl: Final OT is period 4", st["period"] == 4, st["period"])
    st = _status(HockeyTechDataSource.to_espn_event(
        _find(ohl, GameStatusStringLong="Final SO")))
    check("ohl: Final SO is period 5 (ESPN's shootout)", st["period"] == 5, st["period"])
    st = _status(HockeyTechDataSource.to_espn_event(
        _find(_games("pwhl"), GameStatusStringLong="Final 2nd OT")))
    check("pwhl: Final 2nd OT is period 5", st["period"] == 5, st["period"])

    print("\nstates no sample had: live, intermission, unofficial final, postponed")
    base = copy.deepcopy(_find(ohl, GameStatus="1"))
    live = dict(base, GameStatus="2", Period="2", PeriodNameShort="2",
                GameClock="12:34", Intermission="0", HomeGoals="3", VisitorGoals="1",
                GameStatusString="2nd", GameStatusStringLong="12:34 2nd")
    st = _status(HockeyTechDataSource.to_espn_event(live))
    check("in progress is in/STATUS_IN_PROGRESS",
          (st["type"]["state"], st["type"]["name"]) == ("in", "STATUS_IN_PROGRESS"),
          st["type"])
    check("clock and period carried", (st["displayClock"], st["period"]) == ("12:34", 2),
          (st["displayClock"], st["period"]))
    st = _status(HockeyTechDataSource.to_espn_event(dict(live, Intermission="1")))
    check("intermission is STATUS_END_PERIOD",
          (st["type"]["state"], st["type"]["name"]) == ("in", "STATUS_END_PERIOD"),
          st["type"])
    st = _status(HockeyTechDataSource.to_espn_event(dict(live, GameStatus="3")))
    check("unofficial final counts as final",
          sports.SportsCore._status_is_final(st["type"]) is True, st["type"])
    postponed = dict(base, GameStatus="1", GameStatusString="Postponed",
                     GameStatusStringLong="Postponed")
    st = _status(HockeyTechDataSource.to_espn_event(postponed))
    check("postponed is post but not a result",
          st["type"]["state"] == "post"
          and sports.SportsCore._status_is_final(st["type"]) is False, st["type"])
    as_ints = {k: (int(v) if isinstance(v, str) and v.isdigit() else v)
               for k, v in live.items()}
    ev = HockeyTechDataSource.to_espn_event(as_ints)
    check("integer fields (as PWHL has sent) adapt the same",
          ev is not None and _side(ev, "home")["score"] == "3"
          and _status(ev)["period"] == 2)


# --- end to end -------------------------------------------------------------

class _Cache:
    def __init__(self):
        self.store = {}

    def get(self, key, max_age=300, **_):
        return self.store.get(key)

    def set(self, key, data, ttl=None):
        self.store[key] = data

    def delete(self, key):
        self.store.pop(key, None)

    def clear_cache(self, key=None):
        self.store.pop(key, None)


class _Matrix:
    width, height = 128, 32


class _Display:
    def __init__(self):
        self.matrix = _Matrix()
        self.width, self.height = 128, 32
        self.image = Image.new("RGB", (128, 32))
        self.updates = 0

    def clear(self):
        self.image = Image.new("RGB", (128, 32))

    def update_display(self):
        self.updates += 1

    def format_date_with_ordinal(self, dt):
        return dt.strftime("%b %d")


def _shifted(league, live=False):
    """The sample games moved so finals fall in the last days and scheduled
    games in the next ones, wherever 'today' is when this runs."""
    now = datetime.now(timezone(timedelta(hours=-4)))
    out = []
    finals = scheduled = 0
    for g in _games(league):
        g = dict(g)
        if g["GameStatus"] == "4":
            finals += 1
            when = now - timedelta(days=finals)
        else:
            scheduled += 1
            when = now + timedelta(days=scheduled)
        g["GameDateISO8601"] = when.replace(microsecond=0).isoformat()
        out.append(g)
    if live:
        g = dict(out[-1], GameStatus="2", Period="2", PeriodNameShort="2",
                 GameClock="12:34", Intermission="0", HomeGoals="2", VisitorGoals="1",
                 GameDateISO8601=(now - timedelta(hours=1)).replace(microsecond=0).isoformat())
        g["ID"] = "live-" + str(g["ID"])
        out.append(g)
    return out


def check_plugin():
    print("\nthe plugin loads OHL and PWHL and renders them")
    import importlib.util

    logo_dir = Path(tempfile.mkdtemp(prefix="hockeytech-logos-"))
    requested = []

    def fake_download(sport_key, team_id, abbr, logo_path, logo_url=None, *a, **k):
        requested.append((sport_key, abbr, logo_url))
        Path(logo_path).parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (40, 40), (200, 30, 30, 255)).save(logo_path)
        return True

    sports.download_missing_logo = fake_download

    spec = importlib.util.spec_from_file_location("manager", HERE / "manager.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    config = {
        "enabled": True,
        "nhl": {"enabled": False}, "ncaa_mens": {"enabled": False},
        "ncaa_womens": {"enabled": False},
        "ohl": {"enabled": True, "display_options": {"show_records": True}},
        "pwhl": {"enabled": True},
    }
    from unittest.mock import MagicMock
    display = _Display()
    plugin = mod.HockeyScoreboardPlugin(
        "hockey-scoreboard", config, display, _Cache(), MagicMock())

    check("validate_config accepts an OHL/PWHL-only config",
          plugin.validate_config() is True)
    for league in ("ohl", "pwhl"):
        for mode in ("live", "recent", "upcoming"):
            mgr = getattr(plugin, f"{league}_{mode}", None)
            check(f"{league}_{mode} manager built", mgr is not None)
            if mgr is None:
                continue
            check(f"{league}_{mode} reads HockeyTech, not ESPN",
                  isinstance(mgr.data_source, HockeyTechDataSource))
            check(f"{league}_{mode} has odds off", mgr.show_odds is False)
            mgr.logo_dir = logo_dir
            mgr.data_source.fetch_scorebar = (
                lambda back, ahead, timeout=15, _l=league, _m=mode:
                _shifted(_l, live=(_m == "live")))
    check("modes registered in rotation",
          all(f"{lg}_{m}" in plugin.modes for lg in ("ohl", "pwhl")
              for m in ("recent", "upcoming", "live")), plugin.modes)

    plugin.update()

    for league in ("ohl", "pwhl"):
        for mode in ("recent", "upcoming"):
            mgr = getattr(plugin, f"{league}_{mode}")
            games = getattr(mgr, "games_list", None) or []
            check(f"{league}_{mode} has games", len(games) > 0, len(games))
            display.clear()
            result = plugin.display(display_mode=f"{league}_{mode}", force_clear=True)
            check(f"{league}_{mode} display() returns True", result is True, result)
            check(f"{league}_{mode} drew something", display.image.getbbox() is not None)
        recent = getattr(plugin, f"{league}_recent").games_list
        check(f"{league} recent games are finals",
              all(g.get("is_final") for g in recent), [g.get("period_text") for g in recent])
        check(f"{league} recent game carries its W-L-OTL record",
              any(g.get("home_record", "").count("-") == 2 for g in recent))

    check("logos asked for with the feed's URL",
          requested and all(url and "leaguestat.com" in url for _, _, url in requested),
          requested[:3])
    check("logos asked for under each league's sport key",
          {k for k, _, _ in requested} == {"ohl", "pwhl"}, {k for k, _, _ in requested})

    print("\na live game reaches the live mode")
    for league in ("ohl", "pwhl"):
        live_games = getattr(plugin, f"{league}_live").live_games
        check(f"{league}_live sees the in-progress game", len(live_games) == 1,
              len(live_games))
        check(f"{league} in get_live_modes", f"{league}_live" in plugin.get_live_modes(),
              plugin.get_live_modes())
        display.clear()
        result = plugin.display(display_mode=f"{league}_live", force_clear=True)
        check(f"{league}_live display() returns True", result is True, result)
    check("has_live_content is True", plugin.has_live_content() is True)

    vegas_games, vegas_leagues = plugin._collect_games_for_scroll()
    check("scroll/Vegas collect both leagues", vegas_leagues == ["ohl", "pwhl"],
          vegas_leagues)


def main():
    check_adapter()
    check_plugin()
    print("\n%s" % (f"FAILED: {len(failures)}" if failures else "All checks passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
