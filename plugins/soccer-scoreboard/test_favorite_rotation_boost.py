#!/usr/bin/env python3
"""favorite_rotation_boost: favourites get extra turns in switch mode.

Recent and upcoming cards rotated through games_list one after another, so a
favourite's game got exactly the screen time of any other card no matter how
the favourites were configured -- the only favourite weight in the plugin
applied to live games.

SportsCore._next_switch_index runs against a stand-in ``self`` carrying only
what it reads. The display loops call it under _games_lock in place of
``(current_game_index + 1) % len(games_list)``.

Run: <core-venv>/bin/python plugins/<plugin>/test_favorite_rotation_boost.py
"""

import os
import sys
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))
_core = os.environ.get("LEDMATRIX_CORE")
_candidates = [Path(_core)] if _core else []
_candidates.append(plugin_dir.parents[2] / "LEDMatrix")
for candidate in _candidates:
    if (candidate / "src" / "plugin_system" / "base_plugin.py").exists():
        sys.path.insert(0, str(candidate))
        break

from sports import SportsCore  # noqa: E402

failures = []


def check(label, ok):
    print(("  PASS  " if ok else "  FAIL  ") + label)
    if not ok:
        failures.append(label)


def game(gid, home="X", away="Y"):
    return {"id": gid, "home_abbr": home, "away_abbr": away}


class _Switch:
    _next_switch_index = SportsCore._next_switch_index
    _spread_weighted_order = staticmethod(SportsCore._spread_weighted_order)

    def __init__(self, games, boost, favorites=("UF",)):
        self.games_list = games
        self.favorite_teams = list(favorites)
        self.favorite_rotation_boost = boost
        self.current_game_index = 0

    def _is_favorite_game(self, g):
        return g["home_abbr"] in self.favorite_teams or g["away_abbr"] in self.favorite_teams

    def walk(self, steps):
        shown = []
        for _ in range(steps):
            self.current_game_index = self._next_switch_index()
            shown.append(self.games_list[self.current_game_index]["id"])
        return shown


def back_to_back(cycle):
    return any(cycle[i] == cycle[(i + 1) % len(cycle)] for i in range(len(cycle)))


def main():
    print("boost 1 is the old rotation")
    s = _Switch([game("a"), game("b", "UF"), game("c")], boost=1)
    check("plain wrap-around order", s.walk(6) == ["b", "c", "a", "b", "c", "a"])

    print("\na boost with no favourite on the board changes nothing")
    s = _Switch([game("a"), game("b"), game("c")], boost=3)
    check("plain order", s.walk(3) == ["b", "c", "a"])

    print("\nboost 2 gives the favourite two turns, spread out")
    s = _Switch([game("a"), game("uf", "UF"), game("c"), game("d")], boost=2)
    cycle = s.walk(5)
    check("five cards per cycle (%s)" % cycle, sorted(cycle) == ["a", "c", "d", "uf", "uf"])
    check("never back to back, including the wrap (3 other cards leave room)",
          not back_to_back(cycle))
    check("the next cycle repeats it", s.walk(5) == cycle)
    others = [gid for gid in cycle if gid != "uf"]
    check("the other cards keep schedule order", others in (["c", "d", "a"], ["a", "c", "d"], ["d", "a", "c"]))

    print("\na favourite at the end of the list wraps its extra turn")
    order = SportsCore._spread_weighted_order([1, 1, 1, 2])
    check("four entries, index 3 twice (%s)" % order, sorted(order) == [0, 1, 2, 3, 3])
    check("not back to back", not back_to_back(order))
    check("equal weights are plain order", SportsCore._spread_weighted_order([1, 1, 1]) == [0, 1, 2])

    print("\nboost 3 with two favourites")
    s = _Switch([game("a", "UF"), game("b"), game("c", "FSU"), game("d"), game("e")],
                boost=3, favorites=("UF", "FSU"))
    cycle = s.walk(9)
    check("3 + 1 + 3 + 1 + 1 cards (%s)" % cycle,
          cycle.count("a") == 3 and cycle.count("c") == 3 and len(cycle) == 9)

    print("\na boost above the other cards keeps the ratio, not the spacing")
    # No cyclic order can separate 3 turns among 2 other cards; the ratio wins.
    for weights, expected in (([3, 1, 1], [0, 1, 0, 2, 0]),
                              ([1, 3, 1], [0, 1, 1, 2, 1]),
                              ([5, 1], None),
                              ([2, 1], None)):
        order = SportsCore._spread_weighted_order(weights)
        counts = [order.count(i) for i in range(len(weights))]
        check("%s -> each index gets its weight in turns (%s)" % (weights, order),
              counts == weights and len(order) == sum(weights))
        if expected is not None:
            check("%s -> %s" % (weights, expected), order == expected)
    s = _Switch([game("uf", "UF"), game("b")], boost=5)
    cycle = s.walk(6)
    check("boost 5 with one other card: 5 + 1 per cycle (%s)" % cycle,
          cycle.count("uf") == 5 and cycle.count("b") == 1)

    print("\nthe walk resumes from the card on screen after a re-cut")
    s = _Switch([game("a"), game("uf", "UF"), game("c"), game("d")], boost=2)
    s.walk(2)                                   # on screen: whichever card step 2 showed
    on_screen = s.games_list[s.current_game_index]["id"]
    recut = [game("z"), game("a"), game("uf", "UF"), game("c"), game("d")]
    s.games_list = recut
    s.current_game_index = [g["id"] for g in recut].index(on_screen)
    after = s.walk(1)[0]
    fresh = _Switch(recut, boost=2)
    fresh.current_game_index = s.games_list.index(recut[[g["id"] for g in recut].index(on_screen)])
    order = [recut[i]["id"] for i in SportsCore._spread_weighted_order(
        [2 if g["home_abbr"] == "UF" else 1 for g in recut])]
    expected = order[(order.index(on_screen) + 1) % len(order)]
    check("advances to the card after %s in the new order (%s == %s)" % (on_screen, after, expected),
          after == expected)

    print("\nupdate() resetting the index is followed")
    s = _Switch([game("a"), game("uf", "UF"), game("c"), game("d")], boost=2)
    s.walk(3)
    s.current_game_index = 0
    check("continues after index 0", s.walk(1)[0] == "uf")

    print("\na single card stays put")
    s = _Switch([game("uf", "UF")], boost=5)
    check("index 0", s.walk(3) == ["uf", "uf", "uf"])

    print("\n%s" % ("FAILED: %d" % len(failures) if failures else "All checks passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
