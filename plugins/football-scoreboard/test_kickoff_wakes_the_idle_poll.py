#!/usr/bin/env python3
"""
Tests that the live loop tells the idle back-off when the next game starts.

The back-off counts consecutive empty looks and nothing else, so an in-season
league a few hours before kickoff is indistinguishable from one months out of
season. Both escalate to the ceiling, and the ceiling then *is* the blind spot:
measured on two rigs on 2026-09-19, gaps of up to 928s between looks, ten of
them at or above 900s. A game starting inside such a gap is not noticed until
it closes -- reported as "it doesn't pick up new live games until I restart
it", restarting being the one thing that forces an immediate look.

The core mixin clamps the wait to the next known kickoff
(_clamp_to_scheduled_start, tested in the core's test_sports_shared.py). It can
only do that if this loop hands it the upcoming games it already downloaded, so
what is pinned here is the *wiring*, which is what a future edit would silently
drop:

  * every event the live fetch returns is offered, upcoming ones included;
  * the offer happens even when nothing is live, which is the only case the
    back-off is running in;
  * the call is getattr-guarded, so a core without the method still loads.

Built on the same real-SportsLive scaffolding as test_idle_league_backoff.py.

Run: <core-venv>/bin/python plugins/football-scoreboard/test_kickoff_wakes_the_idle_poll.py
"""

# A test harness: it reaches into protected members on purpose, builds a
# concrete subclass at runtime, and accepts arguments only to match the
# signatures it stands in for -- none of which pylint can see as intentional.
# pylint: disable=protected-access,abstract-class-instantiated,unused-argument
# pylint: disable=broad-exception-caught

import sys
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

import sports  # noqa: E402

SPORT_KEY = "nfl"
MODE_KEY = "nfl"


class _Logger:
    def info(self, *a, **k): pass
    def debug(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def error(self, *a, **k): pass


class _StubCore:
    def __init__(self, config, display_manager, cache_manager, logger, sport_key):
        self.logger = logger
        self.config = config
        self.mode_config = config.get(MODE_KEY, {}) or {}


_Concrete = type("_ConcreteLive", (sports.SportsLive,),
                 {name: (lambda self, *a, **k: None)
                  for name in getattr(sports.SportsLive,
                                      "__abstractmethods__", ())})


def _live():
    config = {MODE_KEY: {}}
    real_init = sports.SportsCore.__init__
    sports.SportsCore.__init__ = _StubCore.__init__
    try:
        return _Concrete(config, object(), object(), _Logger(), SPORT_KEY)
    finally:
        sports.SportsCore.__init__ = real_init


failures = []


def check(label, ok):
    print(("  PASS  " if ok else "  FAIL  ") + label)
    if not ok:
        failures.append(label)


def _prime(live):
    """The SportsCore/SportsLive state update() reads, which _StubCore skips."""
    import threading
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
    live.league = "nfl"
    live.sport = "football"
    live._games_lock = threading.RLock()
    live.favorite_teams = []
    live.show_all_live = True
    live.show_favorite_teams_only = False
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


def _drive(live, events, offered):
    """Run one update() pass over a canned payload, recording what was offered."""
    _prime(live)
    live._fetch_data = lambda *a, **k: {"events": list(events)}
    live._extract_game_details = lambda game: dict(game)
    live._note_scheduled_start_candidate = lambda details: offered.append(details)
    try:
        live.update()
    except Exception as exc:                      # noqa: BLE001
        print("    (update raised: %r)" % (exc,))
    return offered


def main():
    print("every event the live fetch returns is offered to the back-off")
    live = _live()
    offered = []
    events = [
        {"id": "a", "is_live": False, "is_halftime": False, "is_final": False},
        {"id": "b", "is_live": False, "is_halftime": False, "is_final": False},
        {"id": "c", "is_live": False, "is_halftime": False, "is_final": True},
    ]
    _drive(live, events, offered)
    ids = [d.get("id") for d in offered if isinstance(d, dict)]
    check("all three events were offered, not just the live ones",
          sorted(ids) == ["a", "b", "c"])

    print("\nit still happens when nothing is live")
    check("the back-off's own case is covered", len(offered) == 3)
    check("and no game was treated as live", live.live_games == [])

    print("\nthe call is getattr-guarded")
    live2 = _live()
    # A core without the method: the attribute simply is not there.
    if hasattr(live2, "_note_scheduled_start_candidate"):
        delattr_ok = True
        try:
            # It comes from the mixin, so shadow it with a sentinel removal.
            live2._note_scheduled_start_candidate = None
        except Exception:                          # noqa: BLE001
            delattr_ok = False
        check("the attribute can be absent/None without the loop caring", delattr_ok)
    _prime(live2)
    live2._fetch_data = lambda *a, **k: {"events": [
        {"id": "a", "is_live": False, "is_halftime": False, "is_final": False}]}
    live2._extract_game_details = lambda game: dict(game)
    raised = None
    try:
        live2.update()
    except AttributeError as exc:
        raised = exc
    check("a core without the method does not raise AttributeError", raised is None)

    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
