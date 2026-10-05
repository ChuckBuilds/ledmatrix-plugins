#!/usr/bin/env python3
"""
Tests that the live loop offers the idle back-off only the kickoffs it would show.

The core mixin clamps the idle back-off to the next known kickoff and then
holds the live cadence for a quarter of an hour after it
(_clamp_to_scheduled_start / _note_scheduled_start_candidate, tested in the
core's test_sports_shared.py). It learns the kickoffs from this loop, which
offers the games the live fetch already downloaded. What is pinned here is
which games it offers:

  * every game the board would show once it is live -- a favourites-only
    board offers only its favourites' bouts (ufc's live filter has no
    excluded list). Each kickoff holds the poll at live cadence for 15
    minutes, so offering games the board then filters out kept a
    favourites-only board polling the whole scoreboard all day on a busy
    slate (football-scoreboard 3.18.7 found it; this is the same rule);
  * a board that shows every live game is unchanged: it offers every game,
    upcoming ones included, even when nothing is live;
  * the call is getattr-guarded, so a core without the method still loads.

Built on the same real-SportsLive scaffolding as football-scoreboard's
test_kickoff_wakes_the_idle_poll.py.

Run: <core-venv>/bin/python plugins/ufc-scoreboard/test_kickoff_offer_follows_the_live_filter.py
"""

# A test harness: it reaches into protected members on purpose, builds a
# concrete subclass at runtime, and accepts arguments only to match the
# signatures it stands in for -- none of which pylint can see as intentional.
# pylint: disable=protected-access,abstract-class-instantiated,unused-argument
# pylint: disable=broad-exception-caught

import os
import sys
import threading
from pathlib import Path

plugin_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(plugin_dir))
_core = os.environ.get("LEDMATRIX_CORE")
if _core and (Path(_core) / "src").is_dir():
    sys.path.insert(0, _core)

try:
    import sports  # noqa: E402
except ImportError as exc:  # no core checkout on the path
    print("SKIP: cannot import sports.py without a LEDMatrix core (%s)" % exc)
    sys.exit(2)

SPORT_KEY = "ufc"
#: The keys a game's two sides are matched on by this plugin's live filter.
HOME, AWAY = "home_abbr", "away_abbr"
FAV, FAV_OPP, OTHER_H, OTHER_A = ("JONES", "MIOCIC", "ADESANYA", "PEREIRA")
#: The abbreviation each side shows, where it is not the key itself.
ABBR = {}


class _Logger:
    def info(self, *a, **k): pass
    def debug(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def error(self, *a, **k): pass
    def exception(self, *a, **k): pass


class _StubCore:
    def __init__(self, config, display_manager, cache_manager, logger, sport_key):
        self.logger = logger
        self.config = config
        self.mode_config = {}


_Concrete = type("_ConcreteLive", (sports.SportsLive,),
                 {name: (lambda self, *a, **k: None)
                  for name in getattr(sports.SportsLive,
                                      "__abstractmethods__", ())})


def _live():
    real_init = sports.SportsCore.__init__
    sports.SportsCore.__init__ = _StubCore.__init__
    try:
        return _Concrete({}, object(), object(), _Logger(), SPORT_KEY)
    finally:
        sports.SportsCore.__init__ = real_init


failures = []


def check(label, ok):
    print(("  PASS  " if ok else "  FAIL  ") + label)
    if not ok:
        failures.append(label)


def _prime(live):
    """The SportsCore/SportsLive state update() reads, which _StubCore skips."""
    live.is_enabled = True
    live.live_games = []
    live.last_update = 0
    live.show_ranking = False
    live.test_mode = False
    live.no_data_interval = 300
    live.update_interval = 30
    live.live_idle_max_interval = 900
    live._empty_live_streak = 0
    live.sport_key = SPORT_KEY
    live.league = SPORT_KEY
    live.sport = SPORT_KEY
    live._games_lock = threading.RLock()
    live.favorite_teams = []
    live.exclude_teams = []
    live.show_all_live = True
    live.show_favorite_teams_only = False
    live.tournament_mode = False
    live.show_odds = False
    live._rotation_schedule = []
    live.current_game_index = 0
    live.current_game = None
    live.last_game_switch = 0
    live.game_update_timestamps = {}
    live.last_log_time = 0
    live.log_interval = 300
    live.stale_game_timeout = 600
    live._check_for_score = lambda *a, **k: None
    return live


def _drive(events, **settings):
    """Run one update() pass over a canned payload; return the offered ids."""
    live = _prime(_live())
    for name, value in settings.items():
        setattr(live, name, value)
    offered = []
    live._fetch_data = lambda *a, **k: {"events": list(events)}
    live._extract_game_details = lambda game: dict(game)
    live._note_scheduled_start_candidate = lambda details: offered.append(details)
    try:
        live.update()
    except Exception as exc:                      # noqa: BLE001
        print("    (update raised: %r)" % (exc,))
    return sorted(d.get("id") for d in offered if isinstance(d, dict)), live


def _game(gid, home, away, **extra):
    game = {"id": gid, HOME: home, AWAY: away, "home_abbr": ABBR.get(home, home),
            "away_abbr": ABBR.get(away, away), "is_live": False, "is_halftime": False,
            "is_final": False}
    game.update(extra)
    return game


def main():
    games = [_game("fav", FAV, FAV_OPP), _game("other", OTHER_H, OTHER_A)]

    print("a board showing every live game offers every game")
    ids, live = _drive(games)
    check("show_all_live offers every game, upcoming ones included",
          ids == ["fav", "other"])
    check("and no game was treated as live", live.live_games == [])
    ids, _ = _drive(games, favorite_teams=[FAV], show_all_live=True,
                    show_favorite_teams_only=True)
    check("show_all_live still offers every game with favourites set",
          ids == ["fav", "other"])
    ids, _ = _drive(games, favorite_teams=[FAV], show_all_live=False,
                    show_favorite_teams_only=False)
    check("favourites-only off offers every game", ids == ["fav", "other"])
    ids, _ = _drive(games, favorite_teams=[], show_all_live=False,
                    show_favorite_teams_only=True)
    check("favourites-only with no favourites offers every game",
          ids == ["fav", "other"])

    print("\na favourites-only board offers only its favourites' games")
    ids, _ = _drive(games, favorite_teams=[FAV], show_all_live=False,
                    show_favorite_teams_only=True)
    check("only the favourite's game was offered (%s)" % ids, ids == ["fav"])
    print("\nthe call is getattr-guarded")
    live2 = _prime(_live())
    live2._note_scheduled_start_candidate = None
    live2._fetch_data = lambda *a, **k: {"events": [games[0]]}
    live2._extract_game_details = lambda game: dict(game)
    raised = None
    try:
        live2.update()
    except Exception as exc:                      # noqa: BLE001
        raised = exc
    check("a core without the method does not raise (%r)" % (raised,), raised is None)

    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
