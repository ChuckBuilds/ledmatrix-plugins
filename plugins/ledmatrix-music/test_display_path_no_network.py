#!/usr/bin/env python3
"""display() must not touch the network, and art downloads must not hold locks.

display() runs on the core's render thread. Three things could still block it:

1. An inline album-art download (requests.get, timeout 5) whenever the poller
   had not prefetched the cover -- first paint, or any failed download.
2. activate_music_display(), called from display(), connecting the YTM client
   with connect_client(timeout=10) -- up to 15 s.
3. The poller downloading art *while holding track_info_lock*, which display()
   takes every frame, so the render thread waited on the lock for the download.

Also checks that update() backfills the art (so dropping the inline fallback
does not leave the placeholder up forever), and that the prefetched bytes/URL
pair is only ever written and read under its lock.

Run: LEDMATRIX_CORE=/path/to/LEDMatrix <core-venv>/bin/python \
         plugins/ledmatrix-music/test_display_path_no_network.py
Exit: 0 pass, 1 fail, 2 skip.
"""

import ast
import io
import logging
import os
import sys
import threading
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))
_core = os.environ.get("LEDMATRIX_CORE")
if _core and _core not in sys.path:
    sys.path.insert(0, _core)
sys.modules.pop("manager", None)

try:
    from PIL import Image
    from src.plugin_system.testing import (
        MockCacheManager, MockPluginManager, VisualTestDisplayManager,
    )
    import manager as music_manager
except ImportError as e:
    print(f"SKIP: needs the LEDMatrix core and plugin requirements ({e})")
    sys.exit(2)

logging.basicConfig(level=logging.CRITICAL)

ART_URL = "http://art.invalid/cover.png"
PLACEHOLDER_FILL = (10, 10, 10)

# The manager module's real `time`, saved while a test swaps in a stub.
music_manager_time_module = None


def _png_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (200, 30, 30)).save(buf, format="PNG")
    return buf.getvalue()


class _Response:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        pass


class _FakeRequests:
    """Stands in for manager.requests; records calls and the calling thread."""

    exceptions = music_manager.requests.exceptions

    def __init__(self, on_get=None):
        self.calls = []
        self.on_get = on_get

    def get(self, url, timeout=None, **kw):
        self.calls.append((url, threading.current_thread().name))
        if self.on_get:
            self.on_get()
        return _Response(_png_bytes())


class _FakeYTM:
    def __init__(self, connected=False, track=None):
        self.is_connected = connected
        self.connect_calls = 0
        self._track = track

    def connect_client(self, timeout=10):
        self.connect_calls += 1
        return False

    def get_current_track(self):
        return self._track if self.is_connected else None


class _AliveThread:
    def is_alive(self):
        return True


def _plugin():
    dm = VisualTestDisplayManager(128, 32)
    cfg = {"enabled": False, "preferred_source": "spotify"}
    p = music_manager.MusicPlugin("ledmatrix-music", cfg, dm,
                                  MockCacheManager(), MockPluginManager())
    p.current_track_info = {
        "source": "Spotify", "title": "A Song", "artist": "An Artist",
        "album": "An Album", "album_art_url": ART_URL,
        "duration_ms": 200000, "progress_ms": 1000, "is_playing": True,
    }
    return p


FAILURES = []


def check(cond, msg):
    """Record and raise, so pytest collection fails too (not just the script)."""
    print(f"  {'PASS' if cond else 'FAIL'}: {msg}")
    if not cond:
        FAILURES.append(msg)
        raise AssertionError(msg)


def test_display_does_not_download_art():
    p = _plugin()
    p.is_music_display_active = True
    fake = _FakeRequests()
    music_manager.requests = fake
    p.display(force_clear=True)
    check(fake.calls == [],
          f"display() with un-prefetched art made no HTTP request (calls: {fake.calls})")


def test_display_does_not_connect_ytm():
    p = _plugin()
    p.preferred_source = "ytm"
    p.ytm = _FakeYTM(connected=False)
    music_manager.requests = _FakeRequests()
    p.display(force_clear=True)
    check(p.ytm.connect_calls == 0,
          f"display() did not call ytm.connect_client ({p.ytm.connect_calls} call(s))")
    check(p.is_music_display_active,
          "display() still marks the display active, so the poller connects YTM")


def test_update_backfills_art_and_display_then_draws_it():
    p = _plugin()
    p.enabled = True
    p.poll_thread = _AliveThread()  # don't start the real poller
    fake = _FakeRequests()
    music_manager.requests = fake
    p.update()
    check(p._album_art_bytes_url == ART_URL,
          "update() downloads the current track's art when it is missing")
    p.is_music_display_active = True
    p.display(force_clear=True)
    px = p.display_manager.image.getpixel((1, 1))
    check(px != PLACEHOLDER_FILL,
          f"display() then draws the downloaded cover, not the placeholder (pixel {px})")


def test_poller_downloads_outside_track_info_lock():
    p = _plugin()
    p.enabled = True
    p.preferred_source = "ytm"
    ytm_data = {
        "video": {"title": "New Song", "author": "New Artist",
                  "thumbnails": [{"url": ART_URL}], "durationSeconds": 200},
        "player": {"trackState": 1, "videoProgress": 1, "adPlaying": False},
    }
    p.ytm = _FakeYTM(connected=True, track=ytm_data)
    p.current_track_info = None

    held_during_download = []

    def probe():
        got = p.track_info_lock.acquire(timeout=0.2)
        if got:
            p.track_info_lock.release()
        held_during_download.append(not got)

    fake = _FakeRequests(on_get=probe)
    music_manager.requests = fake

    real_sleep = music_manager.time.sleep

    class _Time:
        def __getattr__(self, name):
            return getattr(music_manager_time_module, name)

        @staticmethod
        def sleep(_s):
            p.stop_event.set()

    global music_manager_time_module
    music_manager_time_module = music_manager.time
    music_manager.time = _Time()
    try:
        p._poll_music_data()  # one iteration; sleep() stops the loop
    finally:
        music_manager.time = music_manager_time_module
    check(len(fake.calls) == 1,
          f"one poll cycle downloaded the new track's art once ({len(fake.calls)} call(s))")
    check(held_during_download == [False],
          "the download ran without holding track_info_lock "
          f"(held: {held_during_download})")
    _ = real_sleep


def _in_lock(stack):
    return any(isinstance(n, ast.With) and
               any("_album_art_lock" in ast.unparse(i.context_expr) for i in n.items)
               for n in stack)


def test_bytes_url_pair_is_locked():
    tree = ast.parse((PLUGIN_DIR / "manager.py").read_text(encoding="utf-8"))
    attrs = {"_album_art_bytes", "_album_art_bytes_url"}
    bad = []

    def visit(node, stack, func):
        for child in ast.iter_child_nodes(node):
            f = child.name if isinstance(child, ast.FunctionDef) else func
            if (isinstance(child, ast.Attribute) and child.attr in attrs
                    and isinstance(child.value, ast.Name) and child.value.id == "self"
                    and f != "__init__" and not _in_lock(stack)):
                kind = "write" if isinstance(child.ctx, ast.Store) else "read"
                bad.append(f"{f}:{child.lineno} {kind} self.{child.attr}")
            visit(child, stack + [child], f)

    visit(tree, [], None)
    check(not bad, "every read/write of the prefetched bytes/URL pair outside "
                   f"__init__ holds _album_art_lock (unlocked: {bad})")


if __name__ == "__main__":
    real_requests = music_manager.requests
    for t in (test_display_does_not_download_art,
              test_display_does_not_connect_ytm,
              test_update_backfills_art_and_display_then_draws_it,
              test_poller_downloads_outside_track_info_lock,
              test_bytes_url_pair_is_locked):
        print(f"[{t.__name__}]")
        try:
            t()
        except Exception as e:  # a crash is a failure, not a skip
            FAILURES.append(f"{t.__name__} raised {e!r}")
            print(f"  FAIL: raised {e!r}")
        finally:
            music_manager.requests = real_requests
    print(f"\n{len(FAILURES)} failure(s)")
    sys.exit(1 if FAILURES else 0)
