#!/usr/bin/env python3
"""Switching screens never puts a black frame on the panel.

User report: with one favourite team the board occasionally flashed black,
"like it was intending to switch to team #2 but there wasn't one so it
loaded back to team 1". display_manager.clear() writes black straight to the
matrix; the scoreboard called it before drawing whenever force_clear was set
-- on a mode change, a block boundary, or a >5 s gap between display() calls
(a slow update() holding the plugin lock) -- and from every empty mode the
controller tried on its way past. See
scripts/test_scoreboards_never_blank_the_panel.py for the full story.

These drive the real display() methods against a display manager that
records what reaches the panel, and fail if any of it is black.

Run: <core-venv>/bin/python plugins/football-scoreboard/test_switching_never_flashes_black.py
"""

import sys
import threading
import time
import types
from pathlib import Path

from PIL import Image

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

import sports  # noqa: E402

W, H = 64, 32
CARD = (200, 40, 40)


class _Logger:
    def warning(self, *a, **k): pass
    def info(self, *a, **k): pass
    def debug(self, *a, **k): pass
    def error(self, *a, **k): pass


class _Panel:
    """A display manager that records every frame the panel shows.

    clear() behaves like the core's: the buffer AND the matrix go black.
    """

    def __init__(self):
        self.image = Image.new("RGB", (W, H), CARD)
        self.shown = []

    def clear(self):
        self.image = Image.new("RGB", (W, H), (0, 0, 0))
        self.shown.append("black")

    def update_display(self):
        self.shown.append(
            "black" if self.image.convert("RGB").getbbox() is None else "frame")


def _draw(self, game, force_clear=False):
    """Stand-in for the real scorebug: like every real draw path it builds a
    full frame and assigns it, then pushes it. (The real draw paths' own
    clear is caught by scripts/test_scoreboards_never_blank_the_panel.py;
    this file pins what display() itself does around them.)"""
    self.display_manager.image = Image.new("RGB", (W, H), CARD)
    self.display_manager.update_display()


def _concrete(cls):
    return type("Concrete" + cls.__name__, (cls,), {
        "_extract_game_details": lambda self, *a, **k: None,
        "_fetch_data": lambda self, *a, **k: None,
    })


def _manager(cls, games):
    m = object.__new__(_concrete(cls))
    m.display_manager = _Panel()
    m.logger = _Logger()
    m.is_enabled = True
    m.games_list = list(games)
    m.current_game = games[0] if games else None
    m.current_game_index = 0
    m.game_display_duration = 15
    m.last_game_switch = time.time()
    m.last_warning_time = 0
    m.warning_cooldown = 300
    m._games_lock = threading.RLock()
    m._last_display_call_monotonic = 0.0
    m.sport_key = "nfl"
    m._rotate_other_games_on_display = lambda: False
    m._draw_scorebug_layout = types.MethodType(_draw, m)
    return m


GAME = {"id": "g1", "away_abbr": "DAL", "home_abbr": "KC"}

failures = []


def check(name, ok, detail=None):
    if ok:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s%s" % (name, " -- %r" % (detail,) if detail is not None else ""))
        failures.append(name)


def main():
    for label, cls in (("recent", sports.SportsRecent), ("upcoming", sports.SportsUpcoming)):
        print(f"\n{label}: one game, the mode retakes the panel (force_clear)")
        m = _manager(cls, [GAME])
        m.display(force_clear=True)
        check(f"{label}: no black frame on a forced redraw",
              "black" not in m.display_manager.shown, m.display_manager.shown)
        check(f"{label}: a forced redraw shows the card",
              "frame" in m.display_manager.shown, m.display_manager.shown)

        print(f"{label}: one game, display() resumes after a slow update()")
        m = _manager(cls, [GAME])
        m.display()
        m.display_manager.shown.clear()
        m._last_display_call_monotonic = time.monotonic() - 8.0  # update() held the lock
        m.display()
        check(f"{label}: no black frame after a >5 s gap",
              "black" not in m.display_manager.shown, m.display_manager.shown)
        check(f"{label}: the card is redrawn", "frame" in m.display_manager.shown)

        print(f"{label}: an empty mode the controller tries on its way past")
        m = _manager(cls, [])
        result = m.display(force_clear=True)
        check(f"{label}: an empty mode reports no content", result is False, result)
        check(f"{label}: an empty mode leaves the panel alone",
              m.display_manager.shown == [], m.display_manager.shown)
        m.display_manager.shown.clear()
        m.display(force_clear=False)
        check(f"{label}: an empty mode leaves the panel alone without force_clear too",
              m.display_manager.shown == [], m.display_manager.shown)

    print("\nlive/core: no current game")
    m = _manager(sports.SportsRecent, [])
    m.current_game = None
    result = sports.SportsCore.display(m, force_clear=True)
    check("core: no game reports no content", result is False, result)
    check("core: no game leaves the panel alone",
          m.display_manager.shown == [], m.display_manager.shown)

    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
