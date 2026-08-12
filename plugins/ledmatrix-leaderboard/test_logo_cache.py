#!/usr/bin/env python3
"""Tests that logos are decoded and resized once, not once per rebuild.

Preparing a logo is expensive twice over: Image.open defers the PNG decode to
first access, so the decode lands inside _prepare_logo's convert(), and a
LANCZOS resize follows it. A rebuild did that for every team, every time, for
files that had not changed.

That mattered because leaderboard scroll content is generated on the render
thread -- the plugin adapter's capture path needs the shared canvas, so it
cannot be prepared in the background. Measured on a live rig, a rebuild froze
the Vegas scroll for 3.2 seconds; 25 logos alone accounted for 276ms of it,
and a real board carries far more.

Run: python3 plugins/ledmatrix-leaderboard/test_logo_cache.py
"""

import sys
import time
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))

try:
    from PIL import Image
except ImportError:
    print("SKIP: Pillow not installed")
    sys.exit(2)

import image_renderer as ir  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s%s" % (name, (": " + detail) if detail else ""))
        failures.append(name)


def _renderer():
    r = ir.ImageRenderer.__new__(ir.ImageRenderer)
    r.logger = type("L", (), {m: (lambda *a, **k: None) for m in
                              ("debug", "info", "warning", "error", "exception")})()
    r.crisp_logos = True
    r._logo_cache = {}
    return r


def _png(path, size=(32, 32), colour=(255, 0, 0, 255)):
    Image.new('RGBA', size, colour).save(path)
    return str(path)


def main():
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    r = _renderer()
    p = _png(tmp / 'AAA.png')

    print("a logo is loaded once, however many rebuilds ask for it")
    loads = {'n': 0}

    def load():
        loads['n'] += 1
        return Image.open(p)

    first = r._cached_prepared_logo(p, 20, 20, load)
    for _ in range(24):
        r._cached_prepared_logo(p, 20, 20, load)
    check("loaded exactly once", loads['n'] == 1, "%d loads" % loads['n'])
    check("and returns a real image", first is not None)
    check("the same one each time",
          r._cached_prepared_logo(p, 20, 20, load) is first)

    print("\ndifferent target sizes are different entries")
    small = r._cached_prepared_logo(p, 10, 10, load)
    check("a second size reloads", loads['n'] == 2, "%d loads" % loads['n'])
    check("and is actually a different size",
          small is not None and first is not None
          and small.size != first.size, "%r vs %r" % (small.size, first.size))

    print("\na logo replaced on disk is picked up, not served stale")
    # The downloader backfills missing logos, so a path can gain new content.
    time.sleep(0.01)
    Image.new('RGBA', (48, 48), (0, 0, 255, 255)).save(p)
    import os
    os.utime(p, (time.time() + 5, time.time() + 5))   # ensure a distinct mtime
    before = loads['n']
    r._cached_prepared_logo(p, 20, 20, load)
    check("reloaded after the file changed", loads['n'] == before + 1,
          "%d -> %d" % (before, loads['n']))

    print("\na missing logo is not cached as missing")
    # Otherwise a logo downloaded a moment later stays invisible until restart.
    missing = str(tmp / 'ZZZ.png')
    misses = {'n': 0}

    def load_missing():
        misses['n'] += 1
        return None

    check("absent logo prepares to None",
          r._cached_prepared_logo(missing, 20, 20, load_missing) is None)
    r._cached_prepared_logo(missing, 20, 20, load_missing)
    check("and is retried rather than remembered", misses['n'] == 2,
          "%d attempts" % misses['n'])

    _png(tmp / 'ZZZ.png')
    check("so it appears once it exists",
          r._cached_prepared_logo(missing, 20, 20,
                                  lambda: Image.open(missing)) is not None)

    print("\nthe cache cannot grow without bound")
    r2 = _renderer()
    r2._LOGO_CACHE_MAX = 8
    for i in range(20):
        q = _png(tmp / ('T%02d.png' % i))
        r2._cached_prepared_logo(q, 20, 20, lambda q=q: Image.open(q))
    check("stays within its ceiling", len(r2._logo_cache) <= 8,
          "%d entries" % len(r2._logo_cache))

    print("\nthe saving is real, not theoretical")
    r3 = _renderer()
    paths = [_png(tmp / ('B%02d.png' % i)) for i in range(25)]
    for q in paths:                       # warm the OS page cache: be fair
        r3._prepare_logo(Image.open(q), 20, 20)
    t = time.perf_counter()
    for q in paths:
        r3._prepare_logo(Image.open(q), 20, 20)
    uncached = time.perf_counter() - t
    for q in paths:
        r3._cached_prepared_logo(q, 20, 20, lambda q=q: Image.open(q))
    t = time.perf_counter()
    for q in paths:
        r3._cached_prepared_logo(q, 20, 20, lambda q=q: Image.open(q))
    warm = time.perf_counter() - t
    check("a warm rebuild is far cheaper", warm * 10 < uncached,
          "%.2fms cached vs %.2fms uncached" % (warm * 1e3, uncached * 1e3))

    print("\na missing team logo is not downloaded from the render path")
    # _get_team_logo runs from layout construction on the render thread; a
    # network call there would block the Vegas scroll. Downloading is
    # update()'s job (download_missing_logos), not the renderer's.
    calls = {'n': 0}
    ir.download_missing_logo = lambda *a, **k: calls.__setitem__('n', calls['n'] + 1) or True
    r4 = _renderer()
    result = r4._get_team_logo('NOPE', str(tmp))  # no NOPE.png on disk
    check("returns None for a missing local file", result is None)
    check("without ever invoking the downloader", calls['n'] == 0, "%d calls" % calls['n'])

    print("\nupdate()'s backfill downloads missing logos and a later render sees them")
    downloaded = {'n': 0}

    def fake_download(league, team_id, team_abbr, logo_path, session):
        downloaded['n'] += 1
        _png(logo_path)  # simulate the downloader writing the file
        return True

    ir.download_missing_logo = fake_download
    r5 = _renderer()
    leaderboard_data = [{
        'league': 'nfl',
        'league_config': {'logo_dir': str(tmp)},
        'teams': [{'id': '1', 'abbreviation': 'BFL'}],
    }]
    bfl_path = tmp / 'BFL.png'
    check("logo does not exist yet", not bfl_path.exists())
    r5.download_missing_logos(leaderboard_data)
    check("update()'s backfill invoked the downloader once", downloaded['n'] == 1,
          "%d calls" % downloaded['n'])
    check("and the file now exists locally", bfl_path.exists())
    check("so a later render finds it without downloading",
          r5._get_team_logo('BFL', str(tmp)) is not None)
    check("still without the render path calling the downloader",
          downloaded['n'] == 1, "%d calls" % downloaded['n'])

    print("\n%s" % ("FAILED: %d" % len(failures) if failures
                    else "All checks passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
