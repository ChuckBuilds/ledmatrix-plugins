#!/usr/bin/env python3
"""A fighter with no ESPN headshot costs one request per backoff, not one per frame.

The switch cards loaded headshots in display() and cached only successes. A 404
-- about 9% of the fighters on a current ESPN card have no headshot -- fell to
an except that logged ERROR with a traceback and returned None, and nothing was
recorded, so every rendered frame re-requested the image from the render
thread, logged two more ERROR lines, and drew the text "Image Error" in place of
the whole fight.

Now:
  * display() never touches the network: _load_and_resize_headshot reads the
    in-memory cache and disk only;
  * update() fetches what the held fights are missing, and a failure is
    negative-cached with a doubling backoff shared by all three managers;
  * the card is drawn without the missing headshot -- names, result, clock --
    instead of "Image Error".

Run: <core-venv>/bin/python plugins/ufc-scoreboard/test_missing_headshot_is_not_refetched.py
"""

import io
import logging
import os
import sys
import tempfile
from collections import OrderedDict
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))
CORE = None
_core = os.environ.get("LEDMATRIX_CORE", "")
for _candidate in (_core, str(PLUGIN_DIR.parents[2] / "LEDMatrix")):
    if _candidate and (Path(_candidate) / "src" / "plugin_system").is_dir():
        CORE = Path(_candidate)
        sys.path.insert(0, _candidate)
        break
else:
    print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
    sys.exit(2)

from PIL import Image, ImageFont  # noqa: E402

import mma  # noqa: E402
from ufc_managers import UFCLiveManager, UFCRecentManager, UFCUpcomingManager  # noqa: E402

FAILURES = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILURES.append(label)


class _Response:
    def __init__(self, status, content=b"", content_type="image/png"):
        self.status_code = status
        self.content = content
        self.headers = {"content-type": content_type}

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.exceptions.HTTPError(f"{self.status_code} Client Error")


class _Session:
    def __init__(self, response):
        self.response = response
        self.gets = 0

    def get(self, *a, **k):
        self.gets += 1
        return self.response


class _Display:
    def __init__(self, width=128, height=32):
        self.image = Image.new("RGB", (width, height))
        self.updates = 0

    def update_display(self):
        self.updates += 1


class _Records(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


def font(name, size):
    try:
        return ImageFont.truetype(str(CORE / "assets" / "fonts" / name), size)
    except OSError:
        return ImageFont.load_default()


def reset_backoff():
    for name in ("_headshot_failures", "_headshot_inflight"):
        state = getattr(mma, name, None)
        if state is not None:
            state.clear()


def manager(cls, session, logo_dir):
    m = cls.__new__(cls)
    m.logger = logging.getLogger(f"headshot_probe.{cls.__name__}")
    m.logger.setLevel(logging.DEBUG)
    m.config = {}
    m.mode_config = {}
    m.display_width, m.display_height = 128, 32
    m.display_manager = _Display()
    m.session = session
    m.headers = {}
    m._logo_cache = OrderedDict()
    m.logo_dir = logo_dir
    m.show_records = False
    m.show_odds = False
    big = font("PressStart2P-Regular.ttf", 8)
    small = font("4x6-font.ttf", 6)
    m.fonts = {"status": small, "score": big, "time": big, "detail": small,
               "team": big, "record": small}
    m.drawn = []
    m._draw_text_with_outline = (
        lambda draw, text, pos, font, fill=None, outline_color=None: m.drawn.append(text))
    return m


def fight(logo_dir, a="1001", b="1002"):
    return {
        "id": "f1", "fighter1_id": a, "fighter1_name": "Alpha One",
        "fighter1_name_short": "A. One",
        "fighter1_image_path": logo_dir / f"{a}.png",
        "fighter1_image_url": f"https://example.invalid/{a}.png",
        "fighter2_id": b, "fighter2_name": "Bravo Two", "fighter2_name_short": "B. Two",
        "fighter2_image_path": logo_dir / f"{b}.png",
        "fighter2_image_url": f"https://example.invalid/{b}.png",
        "status_text": "KO R1", "period_text": "Final", "fight_class": "LW",
        "clock": "1:00", "period": 1, "home_score": "0", "away_score": "0",
        "game_date": "Sat", "game_time": "8PM", "is_live": False, "is_final": True,
        "fighter1_record": "", "fighter2_record": "",
    }


tmp = Path(tempfile.mkdtemp())
records = _Records()
logging.getLogger("headshot_probe").addHandler(records)
logging.getLogger("headshot_probe").propagate = False

print("display() never downloads")
reset_backoff()
session = _Session(_Response(404, content_type="text/html"))
m = manager(UFCRecentManager, session, tmp)
for _ in range(5):
    m._draw_scorebug_layout(fight(tmp))
check("five frames with missing headshots make no request", session.gets == 0,
      f"GETs={session.gets}")
errors = [r for r in records.records if r.levelno >= logging.ERROR]
check("and log no ERROR", not errors, f"{[r.getMessage() for r in errors][:2]}")

print("\nthe card is drawn without the headshot, not replaced by 'Image Error'")
for cls, expect in ((UFCRecentManager, "KO R1"), (UFCLiveManager, None),
                    (UFCUpcomingManager, "A. One")):
    reset_backoff()
    mm = manager(cls, _Session(_Response(404)), tmp)
    mm._draw_scorebug_layout(fight(tmp))
    check(f"{cls.__name__}: no 'Image Error' card", "Image Error" not in mm.drawn,
          f"drawn={mm.drawn}")
    check(f"{cls.__name__}: the fight's text is still drawn",
          len(mm.drawn) >= 2 and (expect is None or expect in mm.drawn), f"drawn={mm.drawn}")
    check(f"{cls.__name__}: the frame reaches the panel", mm.display_manager.updates == 1)

print("\nupdate() fetches what is missing, once per backoff")
reset_backoff()
fetch = getattr(m, "_fetch_missing_headshots", None)
check("the update path has a headshot prefetch", callable(fetch))
check("the managers' update() runs it",
      "_fetch_missing_headshots" in (getattr(UFCRecentManager.update, "__code__", None)
                                     or type("", (), {"co_names": ()})).co_names)
if callable(fetch):
    records.records.clear()
    session = _Session(_Response(404, content_type="text/html"))
    m = manager(UFCRecentManager, session, tmp)
    m.games_list = [fight(tmp)]
    m._fetch_missing_headshots(now=1000.0)
    check("first update requests each missing fighter once", session.gets == 2,
          f"GETs={session.gets}")
    for _ in range(10):
        m._fetch_missing_headshots(now=1000.0 + 60)
    check("inside the backoff nothing is requested again", session.gets == 2,
          f"GETs={session.gets}")
    warnings = [r for r in records.records if r.levelno == logging.WARNING]
    check("a 404 is one WARNING per fighter, without a traceback",
          len(warnings) == 2 and all(r.exc_info is None for r in warnings),
          f"{[r.getMessage() for r in warnings]}")
    first_retry = mma._headshot_failures["1001"][1]
    m._fetch_missing_headshots(now=first_retry + 1)
    check("after the backoff it is tried again", session.gets == 4, f"GETs={session.gets}")
    second_retry = mma._headshot_failures["1001"][1]
    check("and the backoff grows",
          (second_retry - (first_retry + 1)) == 2 * (first_retry - 1000.0),
          f"{first_retry} -> {second_retry}")

    other = manager(UFCUpcomingManager, session, tmp)
    other.games_list = [fight(tmp)]
    other._fetch_missing_headshots(now=first_retry + 2)
    check("the backoff is shared across managers", session.gets == 4, f"GETs={session.gets}")

    print("\na good download lands on disk and is drawn")
    reset_backoff()
    buf = io.BytesIO()
    Image.new("RGBA", (60, 60), (200, 30, 30, 255)).save(buf, "PNG")
    session = _Session(_Response(200, buf.getvalue()))
    good_dir = tmp / "good"
    m = manager(UFCRecentManager, session, good_dir)
    m.games_list = [fight(good_dir, "2001", "2002")]
    m._fetch_missing_headshots(now=5000.0)
    check("both headshots written", (good_dir / "2001.png").exists()
          and (good_dir / "2002.png").exists())
    check("no temp files left behind", not list(good_dir.glob(".*.tmp")))
    m._fetch_missing_headshots(now=5001.0)
    check("a headshot already on disk is not requested again", session.gets == 2,
          f"GETs={session.gets}")
    img = m._load_and_resize_headshot("2001", "Alpha", good_dir / "2001.png", None)
    check("display() loads it from disk", img is not None)

    print("\na corrupt file is removed and retried later, not re-decoded per frame")
    reset_backoff()
    bad = tmp / "bad"
    bad.mkdir()
    (bad / "3001.png").write_bytes(b"<html>not an image</html>")
    m = manager(UFCRecentManager, _Session(_Response(404)), bad)
    check("unreadable file gives None", m._load_and_resize_headshot(
        "3001", "Charlie", bad / "3001.png", None) is None)
    check("and is deleted so update() can replace it", not (bad / "3001.png").exists())
    check("with a backoff recorded", "3001" in mma._headshot_failures)

print("\n" + "=" * 60)
if FAILURES:
    print(f"{len(FAILURES)} check(s) failed: {FAILURES}")
    sys.exit(1)
print("All checks passed.")
