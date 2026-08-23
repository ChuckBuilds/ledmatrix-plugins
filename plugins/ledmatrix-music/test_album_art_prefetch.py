"""Album art must be downloaded off the render thread.

display() runs on the render thread. It used to fetch album art inline
whenever the cached image was empty -- and the polling thread deliberately
emptied it on every track change. So each new track blocked the panel for the
length of an HTTP round trip.

The polling thread already knew the URL had changed; it just did not fetch.
Now it does, and display() only decodes and resizes.
"""
import ast
from pathlib import Path

SRC = (Path(__file__).resolve().parent / "manager.py").read_text(encoding="utf-8")
TREE = ast.parse(SRC)
FUNCS = {n.name: n for n in ast.walk(TREE) if isinstance(n, ast.FunctionDef)}

NET = ("requests.get", "requests.post", "urlopen")


def _reachable(start, limit=6):
    seen, frontier = set(), {start}
    for _ in range(limit):
        nxt = set()
        for f in frontier:
            node = FUNCS.get(f)
            if not node:
                continue
            for c in ast.walk(node):
                if isinstance(c, ast.Call):
                    nm = ast.unparse(c.func).split(".")[-1]
                    if nm in FUNCS and nm not in seen:
                        seen.add(nm)
                        nxt.add(nm)
        frontier = nxt
    return seen


def test_the_split_exists():
    """Network and rendering must be separable, or nothing below holds."""
    assert "_fetch_album_art_bytes" in FUNCS, "no network-only helper"
    assert "_render_album_art" in FUNCS, "no render-only helper"
    render = ast.unparse(FUNCS["_render_album_art"])
    assert not any(m in render for m in NET), \
        "_render_album_art performs network I/O; it runs on the render thread"


def test_render_helper_is_pure_cpu():
    """It takes bytes, not a URL -- so it cannot be given something to fetch."""
    args = [a.arg for a in FUNCS["_render_album_art"].args.args]
    assert "raw" in args and "url" not in args, f"unexpected signature: {args}"


def test_the_polling_threads_prefetch_on_a_track_change():
    """Both art-change sites must download, not just invalidate."""
    for fn in ("_process_ytm_data_update", "_poll_music_data"):
        assert fn in FUNCS, f"{fn} missing -- has the polling design changed?"
        body = ast.unparse(FUNCS[fn])
        if "new_album_art_url != old_album_art_url" not in body:
            continue
        assert "_prefetch_album_art" in body, (
            f"{fn} notices the album art changed but does not download it; "
            "display() would be left to fetch on the render thread")


def test_display_prefers_the_prefetched_bytes():
    body = ast.unparse(FUNCS["display"])
    assert "_render_album_art" in body, \
        "display() never renders from prefetched bytes"
    assert "_album_art_bytes_url" in body, (
        "display() does not check which URL the prefetched bytes belong to, so "
        "a stale image could be shown for a new track")


def test_display_keeps_an_inline_fallback():
    """First paint has nothing prefetched; the panel must not go blank."""
    body = ast.unparse(FUNCS["display"])
    assert "_fetch_and_resize_image" in body, (
        "the inline fallback was removed; before the poller catches up there "
        "would be no art at all")
