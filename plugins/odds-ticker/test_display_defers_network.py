"""display() must not perform the ESPN fetch on the render thread.

_perform_update() reaches the network -- _fetch_league_games, and below it
_fetch_team_rankings, both make blocking HTTP calls. display() runs on the
render thread, so calling it inline stalls the marquee for the length of the
round trip.

update() already guards against this: it checks is_currently_scrolling() and
hands the work to display_manager.defer_update(). display() called
_perform_update() directly, which defeated that guard -- the refresh simply
moved onto the one thread it must not block.
"""
import ast
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SRC = (HERE / "manager.py").read_text(encoding="utf-8")
TREE = ast.parse(SRC)

FUNCS = {n.name: n for n in ast.walk(TREE) if isinstance(n, ast.FunctionDef)}
NET_MARKERS = ("requests.get", "requests.post", "self.session.get", "urlopen")


def _reachable(start, limit=5):
    """Same-module functions reachable from `start`."""
    seen, frontier = set(), {start}
    for _ in range(limit):
        nxt = set()
        for fn in frontier:
            node = FUNCS.get(fn)
            if not node:
                continue
            for c in ast.walk(node):
                if isinstance(c, ast.Call):
                    name = ast.unparse(c.func).split(".")[-1]
                    if name in FUNCS and name not in seen:
                        seen.add(name)
                        nxt.add(name)
        frontier = nxt
    return seen


def test_perform_update_really_does_reach_the_network():
    """Pin the premise: if this stops being true the guard below is pointless."""
    net = [f for f in _reachable("_perform_update")
           if any(m in ast.unparse(FUNCS[f]) for m in NET_MARKERS)]
    assert net, ("_perform_update no longer reaches any HTTP call; this test file "
                 "exists because it did -- re-check before deleting the guard")


def test_display_does_not_call_perform_update_unguarded():
    """The inline call must sit in the else of a scrolling check."""
    display = FUNCS.get("display")
    assert display is not None, "display() not found"

    # every call to _perform_update inside display(), with its enclosing ifs
    parents = {}
    for node in ast.walk(display):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    unguarded = []
    for node in ast.walk(display):
        if not (isinstance(node, ast.Call)
                and ast.unparse(node.func).endswith("_perform_update")):
            continue
        # walk up looking for an `if` whose test mentions scrolling
        cur, guarded = node, False
        while cur in parents:
            cur = parents[cur]
            if isinstance(cur, ast.If) and "is_currently_scrolling" in ast.unparse(cur.test):
                guarded = True
                break
        if not guarded:
            unguarded.append(node.lineno)

    assert not unguarded, (
        f"_perform_update() is called at line(s) {unguarded} in display() without a "
        "is_currently_scrolling() guard -- that runs a blocking ESPN fetch on the "
        "render thread and stalls the marquee")


def test_display_defers_through_the_display_manager():
    body = ast.unparse(FUNCS["display"])
    assert "defer_update" in body, (
        "display() no longer defers the refresh; update() does, and display() runs "
        "on the render thread, so it needs the deferral more, not less")
    assert "preserve_scroll=True" in body, (
        "the deferred call must keep preserve_scroll, or the ticker jumps back "
        "when the update lands")
