"""display() must not do blocking work on the render thread.

display() runs on the shared display loop. Anything it waits on freezes the
whole rotation -- every plugin, not just this one -- so three separate habits
are pinned here, each of which shipped at some point and each of which was
visible on hardware as a stuttering marquee:

1. Reaching the network inline. _perform_update() calls _fetch_league_games
   and, below it, _fetch_team_rankings, both blocking HTTP.
2. Waiting on a worker thread. Both the data refresh and the scroll-strip
   rebuild were written as `Thread(...).start()` immediately followed by
   `queue.get(timeout=N)` -- a blocking call wearing a thread as a disguise.
   Measured on hardware: single frames of 1.0s, 2.2s and 4.8s against a 10.00ms
   median, with the queue timeouts as ceilings.
3. Re-requesting a deferred refresh every frame. last_update was written only
   inside _perform_update(), so between deferring the work and the work
   landing, the interval stayed elapsed and display() queued another ESPN
   refresh on every frame -- observed firing every 8ms at 100fps.
"""
import ast
from pathlib import Path

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


def _parents(root):
    out = {}
    for node in ast.walk(root):
        for child in ast.iter_child_nodes(node):
            out[child] = node
    return out


def test_perform_update_really_does_reach_the_network():
    """Pin the premise: if this stops being true the guard below is pointless."""
    net = [f for f in _reachable("_perform_update")
           if any(m in ast.unparse(FUNCS[f]) for m in NET_MARKERS)]
    assert net, ("_perform_update no longer reaches any HTTP call; this test file "
                 "exists because it did -- re-check before deleting the guard")


def test_display_does_not_call_perform_update_unguarded():
    """Every inline call must be the fallback for a core without defer_update.

    This used to require an is_currently_scrolling() guard. That was weaker
    than it looked: the flag is False on the first frame of a display cycle,
    which is exactly when the update interval is most likely to have elapsed,
    so the blocking fetch could still land on the render thread. Deferral is
    correct whether or not the marquee happens to be moving at that instant.
    """
    display = FUNCS.get("display")
    assert display is not None, "display() not found"
    parents = _parents(display)

    unguarded = []
    for node in ast.walk(display):
        if not (isinstance(node, ast.Call)
                and ast.unparse(node.func).endswith("_perform_update")):
            continue
        cur, guarded = node, False
        while cur in parents:
            cur = parents[cur]
            if isinstance(cur, ast.Lambda):
                guarded = True  # handed to defer_update, not called here
                break
            if isinstance(cur, ast.If) and "defer_update" in ast.unparse(cur.test):
                guarded = True  # the fallback for a core that cannot defer
                break
        if not guarded:
            unguarded.append(node.lineno)

    assert not unguarded, (
        f"_perform_update() is called at line(s) {unguarded} in display() without "
        "being deferred -- that runs a blocking ESPN fetch on the render thread "
        "and stalls the marquee")


def test_display_defers_through_the_display_manager():
    body = ast.unparse(FUNCS["display"])
    assert "defer_update" in body, (
        "display() no longer defers the refresh; update() does, and display() runs "
        "on the render thread, so it needs the deferral more, not less")
    assert "_deferred_refresh" in body, (
        "display() must schedule the refresh through _deferred_refresh, which "
        "clears the pending flag once the work is done")
    assert "preserve_scroll=True" in ast.unparse(FUNCS["_deferred_refresh"]), (
        "the deferred call must keep preserve_scroll, or the ticker jumps back "
        "when the update lands")


def test_display_never_waits_on_a_worker_thread():
    """No blocking get(timeout=...) in display() itself.

    Scoped to display()'s own body on purpose. The fetch chain below
    _perform_update legitimately passes timeouts to requests.get, and it is
    reached only through defer_update -- off the render thread. What must never
    come back is a wait written directly into the frame path.
    """
    offenders = []
    for name in ["display"]:
        node = FUNCS.get(name)
        if node is None:
            continue
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            if not ast.unparse(call.func).endswith(".get"):
                continue
            if any(kw.arg == "timeout" for kw in call.keywords):
                offenders.append(f"{name}:{call.lineno}")

    assert not offenders, (
        f"blocking get(timeout=...) in display() at {offenders} -- "
        "start the work and collect it on a later frame instead; waiting here "
        "freezes every plugin in the rotation, not just this one")


def test_the_background_pump_does_not_block():
    pump = FUNCS.get("_pump_background")
    assert pump is not None, "_pump_background() not found"
    body = ast.unparse(pump)
    assert "get_nowait" in body, "the pump must collect without waiting"
    assert "min_interval" in body, (
        "the pump must throttle restarts, or work that keeps failing is "
        "respawned once per frame")


def test_display_does_not_requeue_the_refresh_every_frame():
    """The request is throttled; last_update keeps meaning "the data landed".

    display() tests self.last_update to decide a refresh is due, but that
    field is written inside _perform_update -- when the fetch completes. The
    work is deferred, so between requesting it and it landing the interval
    stayed elapsed and display() queued another refresh every frame: 6,661 in
    80 minutes on hardware.

    Stamping last_update in display() would cure the flood and break the
    refresh, because it is the same field _perform_update tests on entry --
    the call display() just scheduled would arrive and no-op. Hence a
    separate marker for the request.
    """
    display = FUNCS["display"]

    stamps = [n.lineno for n in ast.walk(display)
              if isinstance(n, ast.Assign)
              and any(ast.unparse(t) == "self.last_update" for t in n.targets)]
    assert not stamps, (
        f"display() assigns self.last_update at line(s) {stamps} -- that is the "
        "field _perform_update tests on entry, so the refresh display() just "
        "scheduled would arrive and do nothing")

    guards = [n for n in ast.walk(display)
              if isinstance(n, ast.If) and "_deferred_refresh" in ast.unparse(n)]
    assert guards, "display() no longer schedules the refresh at all"
    assert any("_refresh_pending" in ast.unparse(n.test) for n in guards), (
        "the refresh request is not throttled -- display() will queue another "
        "one on every frame until the deferred call lands")


def test_a_dropped_refresh_cannot_wedge_the_branch_shut():
    """core drops deferred work on a TTL and evicts it when the queue is full."""
    display = ast.unparse(FUNCS["display"])
    assert "_refresh_requested_at" in display, (
        "nothing ages out a pending request; if core drops the deferred call, "
        "display() would never ask for another refresh")
    assert "finally" in ast.unparse(FUNCS["_deferred_refresh"]), (
        "the pending flag must clear even when the refresh raises, or one "
        "failure stops display() asking again")

def test_ticker_strip_is_published_only_once_it_is_finished():
    """The rebuild runs on a worker thread, so a half-built strip is visible.

    _create_ticker_image used to bind self.ticker_image to the strip and *then*
    draw the separator bars into it and rebuild cached_array. That was safe only
    while display() blocked until the rebuild finished. It no longer does, and
    display() gates on ticker_image being set.
    """
    fn = FUNCS.get("_create_ticker_image")
    assert fn is not None, "_create_ticker_image() not found"

    publishes = [n.lineno for n in ast.walk(fn)
                 if isinstance(n, ast.Assign)
                 and any(ast.unparse(t) == "self.ticker_image" for t in n.targets)
                 and not (isinstance(n.value, ast.Constant) and n.value.value is None)]
    caches = [n.lineno for n in ast.walk(fn)
              if isinstance(n, ast.Assign)
              and any(ast.unparse(t) == "self.scroll_helper.cached_array"
                      for t in n.targets)]

    assert publishes, "the strip is never published"
    assert caches, "cached_array is never rebuilt"
    assert min(publishes) > max(caches), (
        "self.ticker_image is published before cached_array is rebuilt -- the "
        "render thread can pick up a strip that is still missing its separator "
        "bars. Build into a local and publish last.")


if __name__ == "__main__":
    import sys
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS %s" % name)
            except AssertionError as exc:
                failed += 1
                print("FAIL %s\n     %s" % (name, exc))
    sys.exit(1 if failed else 0)
