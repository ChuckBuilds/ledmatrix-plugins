#!/usr/bin/env python3
"""Tests how often this plugin asks to appear in the Vegas ticker.

With display.vegas_scroll.live_in_ticker set, the marquee keeps running through
a live game and a plugin can hold more than one slot per cycle. The core grants
live_weight to anything reporting live content on its own, so this hook exists
for the one thing the core cannot work out: it sees *that* a game is live, not
*whose*.

The fixtures below use THIS plugin's real data contract -- live_games on a
manager, favorites in favorite_teams, and identifiers in `home_abbr`/`away_abbr`. An earlier version
of these tests used one assumed shape for all ten scoreboards, so four plugins
whose live data is shaped differently passed while never actually matching a
favorite.

Run: <core-venv>/bin/python plugins/baseball-scoreboard/test_vegas_priority_weight.py
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

PLUGIN_CLASS = m.BaseballScoreboardPlugin
GAMES_ATTR = "live_games"
FAVS_ATTR = "favorite_teams"
failures = []


def check(name, cond, detail=""):
    if cond:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s%s" % (name, (": " + detail) if detail else ""))
        failures.append(name)


class FakeManager:
    """One of this plugin's per-league live managers, in its real shape."""

    def __init__(self, games=None, favorites=None, celebrating=None):
        setattr(self, GAMES_ATTR, games or [])
        setattr(self, FAVS_ATTR, favorites or [])
        if celebrating is not None:
            self.active_celebration = {"game": celebrating, "started_at": 0}


def _game(**kw):
    """A live game/fight as this plugin's data source produces it."""
    return {"home_abbr": kw.get("home", "NYY"), "away_abbr": kw.get("away", "BOS")}


def _plugin(live_priority=True, live_content=True, managers=None, vegas=None,
            nested=False):
    p = PLUGIN_CLASS.__new__(PLUGIN_CLASS)
    p.has_live_priority = lambda: live_priority
    p.has_live_content = lambda: live_content
    p.global_config = {'display': {'vegas_scroll': vegas or {}}}
    managers = managers or []
    if nested:
        # nrl and afl keep their managers in a dict, not as plain attributes.
        p._managers = {'live_%d' % i: mgr for i, mgr in enumerate(managers)}
    else:
        for i, mgr in enumerate(managers):
            setattr(p, 'league_%d_live' % i, mgr)
    return p


NESTED = False
FAVORITE = 'NYY'
OTHER = 'CHC'


def main():
    print("nothing live means no opinion")
    check("no live content -> None",
          _plugin(live_content=False).get_vegas_priority_weight() is None)
    check("live priority off -> None",
          _plugin(live_priority=False).get_vegas_priority_weight() is None)

    print("\na live game with no favorite gets the ordinary live weight")
    p = _plugin(managers=[FakeManager([_game()], [OTHER])], nested=NESTED,
                vegas={'live_weight': 3, 'favorite_live_weight': 5})
    check("returns live_weight", p.get_vegas_priority_weight() == 3,
          "got %r" % p.get_vegas_priority_weight())

    print("\na favorite in the game gets the favorite weight")
    p = _plugin(managers=[FakeManager([_game()], [FAVORITE])], nested=NESTED,
                vegas={'live_weight': 3, 'favorite_live_weight': 5})
    check("returns favorite_live_weight", p.get_vegas_priority_weight() == 5,
          "got %r" % p.get_vegas_priority_weight())

    print("\nmatching ignores case and surrounding space")
    p = _plugin(managers=[FakeManager([_game()], ["  " + FAVORITE.upper() + " "])],
                nested=NESTED, vegas={'favorite_live_weight': 5})
    check("still matches", p.get_vegas_priority_weight() == 5,
          "got %r" % p.get_vegas_priority_weight())

    print("\nany of this plugin's managers can supply the favorite")
    p = _plugin(managers=[FakeManager([], [FAVORITE]),
                          FakeManager([_game()], [FAVORITE])],
                nested=NESTED, vegas={'favorite_live_weight': 5})
    check("a later manager is still found", p.get_vegas_priority_weight() == 5)

    print("\nsensible defaults when the config says nothing")
    check("defaults to 3 for a live game",
          _plugin(managers=[FakeManager([_game()], [OTHER])],
                  nested=NESTED).get_vegas_priority_weight() == 3)
    check("defaults to 5 for a favorite",
          _plugin(managers=[FakeManager([_game()], [FAVORITE])],
                  nested=NESTED).get_vegas_priority_weight() == 5)

    print("\nmalformed data never breaks the rotation")
    p = _plugin(managers=[FakeManager(['not-a-dict', None], [FAVORITE])],
                nested=NESTED, vegas={'live_weight': 3})
    check("junk in the game list is skipped",
          p.get_vegas_priority_weight() == 3,
          "got %r" % p.get_vegas_priority_weight())

    broken = _plugin(managers=[FakeManager([_game()], [FAVORITE])], nested=NESTED)
    broken.has_live_content = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    check("an exception yields None rather than propagating",
          broken.get_vegas_priority_weight() is None)

    print("\n%s" % ("FAILED: %d" % len(failures) if failures
                    else "All checks passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
