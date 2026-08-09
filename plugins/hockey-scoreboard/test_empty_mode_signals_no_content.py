#!/usr/bin/env python3
"""
Tests that a mode with no games reports "no content" instead of "displayed".

Regression under test: this plugin's bundled sports.py was a stale fork of the
core's, and its three display() methods had lost their return values -- the
base was even annotated ``-> None``. The manager's dispatcher treats a
non-boolean as success ("Result is None or other - assume success"), so every
mode reported content whether or not it had any.

The display controller skips a mode whose display() returns False. Reporting
success for an empty mode meant it was never skipped, so an out-of-season
league sat on a blank panel -- the no-games branch calls display_manager.clear()
-- for its entire display duration. Reported for NHL recent and live in August,
when those are empty while upcoming still has the preseason schedule.

The methods are exercised against a stand-in ``self`` rather than a constructed
manager, so the test needs no display hardware, no network and no cache.

Run: <core-venv>/bin/python plugins/hockey-scoreboard/test_empty_mode_signals_no_content.py
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
        self.sport_key = 'nhl'
        self._games_lock = threading.Lock()
        self.current_game_index = 0
        self.last_game_switch = 0.0
        self.game_display_duration = 1e9   # never switch mid-test
        self.last_warning_time = 0.0
        self.warning_cooldown = 1e9
        self._last_warning_time = 0.0
        self.draws = 0

    def _draw_scorebug_layout(self, game, force_clear=False):
        self.draws += 1
        self.display_manager.update_display()


GAME = {'id': 'g1', 'away_abbr': 'TB', 'home_abbr': 'BOS'}

# SportsLive has no display() of its own; it inherits SportsCore's, so covering
# SportsCore covers the live mode the bug was reported against.
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

    print("\n%s" % ("FAILED: %d" % len(failures) if failures else "All checks passed"))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
