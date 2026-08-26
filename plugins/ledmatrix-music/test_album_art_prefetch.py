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


def _prefetch_branch():
    """The body of the `elif` that renders already-downloaded bytes.

    Located by its test (which checks _album_art_bytes_url), not by walking for
    any if-statement that mentions the call -- an outer If's body contains the
    inline-fallback arm too, and matching that made this pass on the very bug
    it exists to catch.
    """
    for node in ast.walk(FUNCS["display"]):
        if not isinstance(node, ast.If):
            continue
        if "_album_art_bytes_url" in ast.unparse(node.test):
            return " ".join(ast.unparse(s) for s in node.body)
    return None


def test_the_prefetched_image_is_actually_published():
    """Decoding it is not enough -- the branch has to hand it to the panel.

    The prefetch branch called _render_album_art() and dropped the result on
    the floor: neither image_to_render_this_cycle nor self.album_art_image was
    assigned, so display() fell through to the placeholder rectangle. Only the
    inline fallback published its image, and that branch runs almost never --
    the poller prefetches on every track change, so the prefetch branch wins
    the race essentially every time. Result: the cover never appeared, with no
    error logged anywhere, because nothing had failed.
    """
    branch = _prefetch_branch()
    assert branch, "no elif in display() keys off _album_art_bytes_url"
    assert "image_to_render_this_cycle" in branch, (
        "the prefetch branch decodes the art but never assigns "
        "image_to_render_this_cycle, so the panel draws the empty placeholder")
    assert "self.album_art_image" in branch, (
        "the prefetch branch does not cache the decoded image, so it is "
        "re-decoded on every frame")


def test_the_prefetched_image_is_guarded_against_a_track_change():
    """The track can change while the bytes are being decoded."""
    branch = _prefetch_branch()
    assert "track_info_lock" in branch, (
        "the prefetch branch publishes without taking track_info_lock; the "
        "inline fallback does, and the same race applies here")


def test_display_keeps_an_inline_fallback():
    """First paint has nothing prefetched; the panel must not go blank."""
    body = ast.unparse(FUNCS["display"])
    assert "_fetch_and_resize_image" in body, (
        "the inline fallback was removed; before the poller catches up there "
        "would be no art at all")
