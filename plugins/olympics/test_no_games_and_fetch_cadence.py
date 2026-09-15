#!/usr/bin/env python3
"""The countdown after the Games table runs out, closing day, and fetch cadence.

Pins the drift-audit findings for this plugin:

1. Past the last Games in OLYMPIC_GAMES the fetcher reports opening_date=None.
   The countdown then raised on None: display() drew "Display Error" and
   get_vegas_content(), which has no try, let the exception reach the core.
   The table's own comment promises a skipped screen instead.
2. Closing day was treated as over at midnight UTC, so the Games dropped their
   last day.
3. The medals page was scraped on every update even when no Games were on.
4. display() ran update() -- a scrape of up to 15 s -- on the render loop for
   its first frame.
5. medal_cycle_duration and live_priority were read but not declared, so the
   web UI stripped them; the notification settings did nothing.

Run: LEDMATRIX_CORE=/path/to/LEDMatrix python plugins/olympics/test_no_games_and_fetch_cadence.py
Exit 0 pass, 2 skip, 1 fail.
"""

import json
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))

_core = os.environ.get("LEDMATRIX_CORE", "")
for _candidate in (_core, str(PLUGIN_DIR.parents[2] / "LEDMatrix")):
    if _candidate and (Path(_candidate) / "src" / "plugin_system").is_dir():
        sys.path.insert(0, _candidate)
        break
else:
    print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
    sys.exit(2)

try:
    from PIL import Image, ImageDraw
except ImportError as exc:
    print("SKIP: %s" % exc)
    sys.exit(2)

import manager as m  # noqa: E402
from data import olympics_api  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s%s" % (name, (": " + detail) if detail else ""))
        failures.append(name)


class FakeDisplay:
    def __init__(self, w=128, h=32):
        self.width, self.height, self.matrix = w, h, None
        self.regular_font = self.small_font = self.extra_small_font = None
        self.clear()
        self.drawn_text = []

    def clear(self):
        self.image = Image.new("RGB", (self.width, self.height))
        self.draw = ImageDraw.Draw(self.image)

    def update_display(self):
        pass

    def draw_text(self, text, **kwargs):
        self.drawn_text.append(text)


def at(when):
    """Pin olympics_api's clock."""
    olympics_api._utcnow = lambda: when


def fetcher_with_counters():
    fetcher = olympics_api.OlympicsDataFetcher({})
    calls = {"medals": 0, "schedule": 0, "results": 0}

    def counted(name):
        def fn(*args, **kwargs):
            calls[name] += 1
            return []
        return fn

    fetcher.fetch_medal_counts = counted("medals")
    fetcher.fetch_schedule = counted("schedule")
    fetcher.fetch_results = counted("results")
    return fetcher, calls


def api_checks():
    real_now = olympics_api._utcnow
    try:
        print("\nclosing day is part of the Games")
        at(datetime(2026, 2, 22, 12, 0))
        fetcher, _ = fetcher_with_counters()
        data = fetcher.get_olympics_data()
        check("noon UTC on closing day is still Milano Cortina 2026",
              data.games_name == "Milano Cortina 2026", "got %r" % data.games_name)
        check("... and the Games are active", data.is_active is True)

        print("\nno medal scraping between Games")
        at(datetime(2026, 9, 15, 12, 0))
        fetcher, calls = fetcher_with_counters()
        data = fetcher.get_olympics_data()
        check("the Games are not active in September 2026", data.is_active is False)
        check("the medals page is not fetched when no Games are on",
              calls["medals"] == 0, "fetch_medal_counts calls=%d" % calls["medals"])
    finally:
        olympics_api._utcnow = real_now


def plugin_checks():
    real_now = olympics_api._utcnow
    dm = FakeDisplay()
    plugin = m.OlympicsPlugin("olympics", {"enabled": True}, dm, None, None)

    print("\npast the last known Games the screen is skipped")
    try:
        at(datetime(2029, 1, 1, 12, 0))
        fetcher, _ = fetcher_with_counters()
        plugin.olympics_data = fetcher.get_olympics_data()
    finally:
        olympics_api._utcnow = real_now
    check("the fetcher reports no opening date", plugin.olympics_data.opening_date is None)
    plugin.last_update_time = time.time()  # keep the Vegas path from refetching
    dm.drawn_text.clear()
    result = plugin.display()
    check("display() returns False", result is False, "got %r" % (result,))
    check("... and draws no error text", "Display Error" not in dm.drawn_text,
          "drew %r" % dm.drawn_text)
    try:
        vegas = plugin.get_vegas_content()
        check("get_vegas_content() returns None", vegas is None, "got %r" % (vegas,))
    except Exception as exc:  # pylint: disable=broad-except
        check("get_vegas_content() returns None", False, "raised %r" % exc)

    print("\nfirst paint does not fetch on the render loop")
    plugin2 = m.OlympicsPlugin("olympics", {"enabled": True}, FakeDisplay(), None, None)
    inline = []
    started = threading.Event()

    def fake_update():
        inline.append(threading.current_thread() is threading.main_thread())
        started.set()

    plugin2.update = fake_update
    result = plugin2.display()
    started.wait(2)
    check("display() with no data does not call update() inline",
          inline and not any(inline), "inline calls=%r" % inline)
    check("... and gives up the slot", result is False, "got %r" % (result,))

    print("\nschema matches what the code reads")
    schema = json.loads((PLUGIN_DIR / "config_schema.json").read_text(encoding="utf-8"))
    props = schema["properties"]
    for key in ("medal_cycle_duration", "live_priority"):
        check("declares %s" % key, key in props)
    # Deprecated, not removed: core's web save deep-merges over the stored
    # section, so a key dropped from the schema could never be cleared and
    # would fail additionalProperties on every load. Declared with no default
    # so a fresh config never gains them.
    for key in ("notifications_enabled", "favorite_countries", "webhooks"):
        spec = props.get(key, {})
        check("%s still declared (old configs validate)" % key, key in props)
        check("%s marked deprecated and hidden, no default" % key,
              spec.get("x-display") == "hidden" and "default" not in spec
              and spec.get("description", "").startswith("Deprecated: ignored"),
              "got %r" % spec)
    import jsonschema
    stored = {"enabled": True, "notifications_enabled": True,
              "favorite_countries": ["USA"],
              "webhooks": [{"url": "https://example.com/h"}]}
    errors = list(jsonschema.Draft7Validator(schema).iter_errors(stored))
    check("a config still carrying the deprecated keys validates", not errors,
          "; ".join(e.message for e in errors))
    src = (PLUGIN_DIR / "manager.py").read_text(encoding="utf-8")
    check("manager.py does not read the deprecated keys",
          not any(k in src for k in ("notifications_enabled", "favorite_countries", "webhooks")))


def main():
    api_checks()
    plugin_checks()
    print("\n%s" % ("FAILED: %d" % len(failures) if failures else "All checks passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
