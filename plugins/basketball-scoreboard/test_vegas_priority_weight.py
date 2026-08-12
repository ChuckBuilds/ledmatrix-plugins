#!/usr/bin/env python3
"""Tests how often this plugin asks to appear in the Vegas ticker.

With display.vegas_scroll.live_in_ticker set, the marquee keeps running
through a live game and a plugin can hold more than one slot per cycle. The
core already grants live_weight to anything reporting live content, so this
hook exists for the one thing the core cannot work out: it can see *that* a
game is live, not *whose*. Only the plugin knows a favorite is playing.

Run: <core-venv>/bin/python plugins/basketball-scoreboard/test_vegas_priority_weight.py
"""

import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))

import os  # noqa: E402
_core = os.environ.get('LEDMATRIX_CORE', '')
for _candidate in (_core, str(PLUGIN_DIR.parents[2] / 'LEDMatrix')):
    if _candidate and (Path(_candidate) / 'src' / 'plugin_system').is_dir():
        sys.path.insert(0, _candidate)
        break
else:
    print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
    sys.exit(2)

import manager as m  # noqa: E402  # pylint: disable=wrong-import-position

PLUGIN_CLASS = m.BasketballScoreboardPlugin
failures = []


def check(name, cond, detail=""):
    if cond:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s%s" % (name, (": " + detail) if detail else ""))
        failures.append(name)


class FakeLeague:
    """Stands in for one of the plugin's per-league live managers."""

    def __init__(self, live_games=None, favorite_teams=None):
        self.live_games = live_games or []
        self.favorite_teams = favorite_teams or []


def _plugin(live_priority=True, live_content=True, leagues=None, vegas=None):
    p = PLUGIN_CLASS.__new__(PLUGIN_CLASS)
    p.has_live_priority = lambda: live_priority
    p.has_live_content = lambda: live_content
    p.global_config = {'display': {'vegas_scroll': vegas or {}}}
    for i, league in enumerate(leagues or []):
        setattr(p, 'league_%d_live' % i, league)
    return p


def main():
    game = {'home_abbr': 'NYY', 'away_abbr': 'BOS'}

    print("nothing live means no opinion")
    check("no live content -> None",
          _plugin(live_content=False).get_vegas_priority_weight() is None)
    check("live priority off -> None",
          _plugin(live_priority=False).get_vegas_priority_weight() is None)

    print("\na live game with no favorite gets the ordinary live weight")
    p = _plugin(leagues=[FakeLeague([game], ['CHC'])],
                vegas={'live_weight': 3, 'favorite_live_weight': 5})
    check("returns live_weight", p.get_vegas_priority_weight() == 3,
          "got %r" % p.get_vegas_priority_weight())

    print("\na favorite playing gets the favorite weight")
    for side, abbr in (("home", "NYY"), ("away", "BOS")):
        p = _plugin(leagues=[FakeLeague([game], [abbr])],
                    vegas={'live_weight': 3, 'favorite_live_weight': 5})
        check("favorite on the %s side" % side,
              p.get_vegas_priority_weight() == 5,
              "got %r" % p.get_vegas_priority_weight())

    print("\nteam matching ignores case")
    p = _plugin(leagues=[FakeLeague([game], ['nyy'])],
                vegas={'favorite_live_weight': 5})
    check("lowercase favorite still matches", p.get_vegas_priority_weight() == 5)

    print("\nany of the plugin's leagues can supply the favorite")
    p = _plugin(leagues=[FakeLeague([], ['NYY']),
                         FakeLeague([game], ['NYY'])],
                vegas={'favorite_live_weight': 5})
    check("a later league is still found", p.get_vegas_priority_weight() == 5)

    print("\nsensible defaults when the config says nothing")
    p = _plugin(leagues=[FakeLeague([game], ['CHC'])])
    check("defaults to 3 for a live game", p.get_vegas_priority_weight() == 3)
    p = _plugin(leagues=[FakeLeague([game], ['NYY'])])
    check("defaults to 5 for a favorite", p.get_vegas_priority_weight() == 5)

    print("\nmalformed data never breaks the rotation")
    p = _plugin(leagues=[FakeLeague(['not-a-dict', None], ['NYY'])],
                vegas={'live_weight': 3})
    check("junk in live_games is skipped", p.get_vegas_priority_weight() == 3,
          "got %r" % p.get_vegas_priority_weight())
    p = _plugin(leagues=[FakeLeague([{'home_abbr': None}], ['NYY'])],
                vegas={'live_weight': 3})
    check("a missing abbreviation is not a match",
          p.get_vegas_priority_weight() == 3)

    broken = _plugin(leagues=[FakeLeague([game], ['NYY'])])
    broken.has_live_content = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    check("an exception yields None rather than propagating",
          broken.get_vegas_priority_weight() is None)

    print("\n%s" % ("FAILED: %d" % len(failures) if failures
                    else "All checks passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
