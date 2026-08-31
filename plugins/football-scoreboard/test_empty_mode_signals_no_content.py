#!/usr/bin/env python3
"""
Tests that a mode with no games reports "no content" instead of "displayed".

Companion to the same test in hockey-scoreboard, which was added after the bug
was found there. football-scoreboard ships its own fork of sports.py and had no
equivalent guard, so the same regression could land here unnoticed -- the forks
diverge and a fix in one lineage does not reach the other. The manager's dispatcher treats a
non-boolean as success ("Result is None or other - assume success"), so every
mode reported content whether or not it had any.

The display controller skips a mode whose display() returns False. Reporting
success for an empty mode meant it was never skipped, so an out-of-season
league sat on a blank panel -- the no-games branch calls display_manager.clear()
-- for its entire display duration. The NFL equivalent is the stretch before Week 1: recent and
live are empty while upcoming already carries the preseason schedule.

The methods are exercised against a stand-in ``self`` rather than a constructed
manager, so the test needs no display hardware, no network and no cache.

Run: <core-venv>/bin/python plugins/football-scoreboard/test_empty_mode_signals_no_content.py
"""

import sys
import threading
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

import sports  # noqa: E402


class _Logger:
    def warning(self, *a, **k): pass
    def info(self, *a, **k): pass
    def debug(self, *a, **k): pass
    def error(self, *a, **k): pass


class _DisplayManager:
    def __init__(self):
        self.clears = 0
        self.updates = 0

    def clear(self):
        self.clears += 1

    def update_display(self):
        self.updates += 1


class _Manager:
    """A stand-in ``self`` carrying only what display() touches."""

    def __init__(self, games, enabled=True):
        self.is_enabled = enabled
        self.games_list = list(games)
        self.current_game = games[0] if games else None
        self.display_manager = _DisplayManager()
        self.logger = _Logger()
        self.sport_key = 'nfl'
        self._games_lock = threading.Lock()
        self.current_game_index = 0
        self.last_game_switch = 0.0
        self.game_display_duration = 1e9   # never switch mid-test
        self.last_warning_time = 0.0
        self.warning_cooldown = 1e9
        self._last_warning_time = 0.0
        self.draws = 0
        # SportsLive.display() consults the celebration mixin before drawing.
        self.active_celebration = None
        self.celebration_end_time = 0.0

    def _draw_scorebug_layout(self, game, force_clear=False):
        self.draws += 1
        self.display_manager.update_display()

    # SportsUpcoming/Recent.display() re-cut the non-favourite slice before the
    # dwell check. The real method is bound rather than stubbed: with no
    # selection pools it returns False without touching anything else, which is
    # what an empty mode should do, and a no-op here would hide a regression
    # that made it raise.
    _rotate_other_games_on_display = sports.SportsCore._rotate_other_games_on_display
    _advance_other_games_if_due = sports.SportsCore._advance_other_games_if_due
    # Same reasoning: the display paths reset the dwell when the mode retakes
    # the panel, and this stand-in's last_game_switch of 0.0 is the "no game
    # shown yet" sentinel the real method leaves alone.
    _reset_dwell_on_reentry = sports.SportsCore._reset_dwell_on_reentry
    _DWELL_REENTRY_GAP_SECONDS = sports.SportsCore._DWELL_REENTRY_GAP_SECONDS

    # SportsLive.display() drives rotation through these before drawing; the
    # test pins one game, so they are no-ops.
    def _advance_live_game_if_due(self):
        pass

    def _get_live_game_duration(self, *a, **k):
        return 1e9


GAME = {'id': 'g1', 'away_abbr': 'KC', 'home_abbr': 'BUF'}

# Unlike hockey's fork, this one overrides display() on SportsLive. Its only
# paths that do not delegate are `return False` when disabled and `return True`
# for an active celebration; the no-games case falls through to
# `super().display(force_clear)`, so SportsCore below covers it. SportsLive is
# checked separately for the disabled path, because exercising super() needs a
# real subclass instance rather than this stand-in.
CASES = [
    ('SportsCore', sports.SportsCore.display),
    ('SportsUpcoming', sports.SportsUpcoming.display),
    ('SportsRecent', sports.SportsRecent.display),
]

failures = []


def check(name, actual, expected):
    if actual == expected:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s: expected %r, got %r" % (name, expected, actual))
        failures.append(name)


def main():
    print("an empty mode reports no content, so the controller can skip it")
    for label, display in CASES:
        mgr = _Manager([])
        result = display(mgr, force_clear=False)
        check("%s with no games returns False" % label, result, False)
        check("%s with no games draws nothing" % label, mgr.draws, 0)

    print("\nthe same is true when the manager is disabled")
    for label, display in CASES:
        mgr = _Manager([GAME], enabled=False)
        check("%s disabled returns False" % label, display(mgr), False)

    print("\na mode that does have a game still reports success")
    for label, display in CASES:
        mgr = _Manager([GAME])
        result = display(mgr, force_clear=False)
        check("%s with a game returns True" % label, result, True)
        check("%s with a game draws it" % label, mgr.draws, 1)

    print("\nthe result is a real bool, not something merely truthy")
    # The dispatcher branches on `result is True` / `result is False`, so a truthy
    # non-bool would fall through to the "assume success" path and reintroduce this.
    for label, display in CASES:
        check("%s empty -> bool" % label, type(display(_Manager([]))), bool)
        check("%s populated -> bool" % label,
              type(display(_Manager([GAME]))), bool)

    print("\nSportsLive's own early return")
    live_disabled = sports.SportsLive.display(_Manager([GAME], enabled=False))
    check("SportsLive disabled returns False", live_disabled, False)
    check("SportsLive disabled -> bool", type(live_disabled), bool)

    print("\n%s" % ("FAILED: %d" % len(failures) if failures else "All checks passed"))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
