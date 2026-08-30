#!/usr/bin/env python3
"""Odds must be requested for the games shown, not for the whole schedule.

The upcoming-games loop fetched odds for every game it collected, then the
caller sorted that list and kept upcoming_games_to_show of them (10 by
default). The comment on the loop already claimed odds were fetched "only for
games that will be displayed", but the filter it referred to applies only when
show_favorite_teams_only is set AND favourites are configured. Neither is the
default, so in the usual case nothing narrowed it.

Measured on a live rig running the college-football league, from its own logs:

    Found 946 total upcoming games in data
    Found 946 upcoming games after filtering
    No favorites configured: showing 1 total upcoming games

946 separate ESPN odds requests to put one game on the panel. Each is its own
HTTP call from a Pi that is also driving the display, and the odds cache only
absorbs repeats of the *same* event, so a wide schedule never benefits.

This is the same defect odds-ticker had and fixed -- see
plugins/odds-ticker/test_odds_candidate_scope.py, written after a rig made
1,281 ESPN requests in twenty minutes for a ticker showing five games. All nine
scoreboards carried it in the upcoming path.

Checked structurally, per plugin: the fetch must come after the trim, and must
iterate the selected list rather than the collected one.

Run: <core-venv>/bin/python scripts/test_odds_fetch_scope.py
"""

import ast
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
failures = []


def check(label, ok):
    print(("  PASS  " if ok else "  FAIL  ") + label)
    if not ok:
        failures.append(label)


def main():
    print("odds are requested only for the games that survived selection")
    paths = sorted((REPO / "plugins").glob("*/sports.py"))
    check("the scoreboard plugins were found", len(paths) >= 9)

    for path in paths:
        plugin = path.parent.name
        src = path.read_text(encoding="utf-8")
        if "_fetch_odds" not in src:
            continue

        # The trim is whatever bounds the list before odds are fetched over it.
        # Originally a slice; a plugin whose two selection branches were merged
        # bounds it inside the selection helper instead, passing the same limit.
        # Either shape is fine -- what must stay true is that the fetch comes
        # after it and iterates the selected list, which the checks below
        # enforce. Accepting only the slice would have failed a refactor that
        # kept the invariant, and the pressure then is to weaken the guard.
        trim = max(src.find("[:self.upcoming_games_to_show]"),
                   src.find("processed_games, 0, self.upcoming_games_to_show"))
        if trim == -1:
            check(f"{plugin}: bounds the list before fetching odds over it", False)
            continue

        # Every _fetch_odds call in the upcoming path must sit after the trim.
        scoped = re.search(
            r"if self\.show_odds:\s*\n\s*for game in team_games:\s*\n\s*self\._fetch_odds\(game\)",
            src)
        check(f"{plugin}: fetches odds over the selected list",
              bool(scoped) and scoped.start() > trim)

        # And the collecting loop must no longer fetch per collected game.
        collected = re.search(
            r"favorite_games_found \+= 1\s*\n\s*if self\.show_odds:\s*\n\s*self\._fetch_odds\(game\)",
            src)
        check(f"{plugin}: no longer fetches while collecting", collected is None)

    print("\nthe file still parses and the call is inside update-side code")
    for path in paths:
        plugin = path.parent.name
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            check(f"{plugin}: parses", False)
            print(f"        {exc}")
            continue
        enclosing = [
            fn.name for fn in ast.walk(tree)
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
            and any(isinstance(n, ast.Call)
                    and getattr(n.func, "attr", None) == "_fetch_odds"
                    for n in ast.walk(fn))
        ]
        check(f"{plugin}: _fetch_odds is still called from {', '.join(sorted(set(enclosing))) or 'nowhere'}",
              bool(enclosing))

    print("\n%s" % ("FAILED: %d" % len(failures) if failures
                    else "All checks passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
