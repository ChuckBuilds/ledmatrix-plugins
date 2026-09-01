#!/usr/bin/env python3
"""Dynamic duration must count the list the display actually rotates.

    python3 scripts/test_cycle_duration_counts_real_games.py

## Why this exists

`get_cycle_duration` sizes a mode's slot from the number of cards it is about
to show. It used to ask the manager for them like this:

    elif mode_type == 'upcoming':
        games = getattr(manager, 'upcoming_games', [])

`SportsUpcoming.__init__` declared `self.upcoming_games = []` -- "Store all
fetched upcoming games initially" -- and then never assigned to it again; the
selected games go to `self.games_list`. Same for `SportsRecent.recent_games`.
So `total_games` was always 0, and every recent/upcoming cycle silently fell
through to the "no games yet" default of three games' worth instead of scaling
with the number of cards on the board. `live_games` IS populated, so live mode
was unaffected -- which is part of why this went unnoticed.

The attribute is gone now. This guard exists because the READ is the thing
that has to stay fixed: nine plugins ship a copy of this function, they had
already drifted into three different shapes for it (afl and nrl call the
helper, basketball/hockey/lacrosse inline the same logic, football and
baseball had the bug), and nothing else would catch a copy quietly going back.

The rule is deliberately loose about HOW: either call
`_get_games_from_manager`, which resolves it correctly for the scroll path
too, or reach for `games_list` first. What is banned is reading only the list
nothing fills.

Source-level on purpose. Driving the real function needs a constructed plugin,
and the plugin's own pytest file shows why that is not the check to rely on:
its assertions sit behind `if hasattr(plugin, "nfl_recent") and
plugin.nfl_recent`, and when the managers fail to build the whole block is
skipped and the test passes having verified nothing.
"""
import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUGINS = REPO / "plugins"

FUNCTION = "get_cycle_duration"
# The lists a manager declares but never fills.
DEAD = ("upcoming_games", "recent_games")
# Either of these means the caller found the real list.
GOOD = ("_get_games_from_manager", "games_list")

results = []


def check(case, passed, detail=""):
    results.append((case, passed))
    print("  [%s] %s%s" % ("pass" if passed else "FAIL", case,
                           "" if passed else "  <- " + str(detail)))


def _function_source(path):
    """The source of get_cycle_duration, or None if this file has none.

    Parsed rather than sliced with a regex: the nine copies indent it
    differently and some define it inside a class body that a brace-free
    text scan cannot bound.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        return ("<unparseable: %s>" % exc)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == FUNCTION:
            return ast.get_source_segment(
                path.read_text(encoding="utf-8"), node) or ""
    return None


def main():
    managers = sorted(PLUGINS.glob("*/manager.py"))
    if not managers:
        print("SKIP: no plugin manager.py found; the layout changed")
        return 2

    print("%s counts the list the display rotates" % FUNCTION)
    covered = []
    for path in managers:
        source = _function_source(path)
        if source is None:
            continue
        pid = path.parent.name
        covered.append(pid)

        if source.startswith("<unparseable"):
            check("%s: %s parses" % (pid, FUNCTION), False, source)
            continue

        reads_dead = [name for name in DEAD if name in source]
        finds_real = [name for name in GOOD if name in source]
        check("%s: does not size the cycle from a list nothing fills" % pid,
              not reads_dead or bool(finds_real),
              "reads %s and never reaches games_list" % ", ".join(reads_dead))

    print("  (%d copies: %s)" % (len(covered), ", ".join(covered)))

    # The attribute itself should stay gone, in every lineage. Declaring it
    # again is what made the read above look correct in the first place.
    print()
    print("the never-populated attributes stay gone")
    for path in sorted(PLUGINS.glob("*/sports.py")):
        text = path.read_text(encoding="utf-8")
        pid = path.parent.name
        for name in DEAD:
            declared = "self.%s = []" % name
            if declared not in text:
                continue
            # Only a declaration that is never assigned anywhere else is the
            # trap; a lineage that genuinely fills the list may keep it.
            assigned = text.count("self.%s = " % name) + text.count("self.%s.append" % name)
            check("%s: self.%s is filled if it is declared" % (pid, name),
                  assigned > 1,
                  "declared once and never populated")

    print()
    failed = [name for name, passed in results if not passed]
    print("%d checks, %d failed" % (len(results), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
