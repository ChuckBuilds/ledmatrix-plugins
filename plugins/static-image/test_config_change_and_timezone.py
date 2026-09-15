#!/usr/bin/env python3
"""
Regression tests: a web-UI save keeps the image list, and schedules follow the
configured LEDMatrix timezone.

on_config_change used to re-read only image_config.images. The web UI's upload
widget writes the top-level `images` list, so every save emptied the list, and
once the rotation interval passed the panel showed "Image Error".
background_color, fit_to_display, preserve_aspect_ratio and
image_rotation_interval were not refreshed either.

Per-image schedules compared against naive datetime.now(), the Pi's system
zone, so a Pi on UTC with LEDMatrix set to a local zone ran every window hours
off.

Run: python plugins/static-image/test_config_change_and_timezone.py
Exit 0 pass, 2 skip (pytz missing), 1 fail.
"""

import logging
import sys
import time
import types
from datetime import datetime, timedelta
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))

try:
    import pytz
except ImportError:
    print("SKIP: pytz not installed")
    sys.exit(2)
from PIL import Image  # noqa: E402


def _stub_core():
    """Minimal BasePlugin mirroring the core's constructor and on_config_change."""
    class BasePlugin:
        def __init__(self, plugin_id, config, display_manager, cache_manager, plugin_manager):
            self.plugin_id = plugin_id
            self.config = config or {}
            self.display_manager = display_manager
            self.cache_manager = cache_manager
            self.plugin_manager = plugin_manager
            self.logger = logging.getLogger(f"test.{plugin_id}")
            self.enabled = self.config.get("enabled", True)

        def on_config_change(self, new_config):
            self.config = new_config or {}
            self.enabled = self.config.get("enabled", self.enabled)

        def on_enable(self):
            pass

        def validate_config(self):
            return True

    for name in ("src", "src.plugin_system"):
        sys.modules.setdefault(name, types.ModuleType(name))
    mod = types.ModuleType("src.plugin_system.base_plugin")
    mod.BasePlugin = BasePlugin
    sys.modules["src.plugin_system.base_plugin"] = mod


_stub_core()
from manager import StaticImagePlugin  # noqa: E402

results = []


def check(case, passed):
    results.append((case, passed))
    print(f"  [{'pass' if passed else 'FAIL'}] {case}")


class FakeDM:
    def __init__(self, w=64, h=32):
        self.matrix = types.SimpleNamespace(width=w, height=h)
        self.width, self.height = w, h
        self.image = Image.new("RGB", (w, h))
        self.frames = 0

    def clear(self):
        self.image = Image.new("RGB", (self.width, self.height))

    def update_display(self):
        self.frames += 1

    def draw_text(self, *a, **k):
        pass


def plugin_manager(tz_name=None):
    pm = types.SimpleNamespace()
    if tz_name:
        pm.config_manager = types.SimpleNamespace(get_timezone=lambda: tz_name)
    return pm


def far_zone():
    """A fixed-offset zone about 12 hours from this machine's system zone."""
    offset = datetime.now().astimezone().utcoffset().total_seconds() / 3600
    target = round(offset + 12)
    if target > 14:
        target -= 24
    return "Etc/GMT" if target == 0 else "Etc/GMT%+d" % (-target)  # Etc signs are inverted


FIXTURE = "test/fixtures/test-pattern.png"

# --- C2: a save keeps the top-level images list --------------------------
base_cfg = {
    "enabled": True,
    "images": [FIXTURE],
    "fit_to_display": True,
    "preserve_aspect_ratio": False,
    "background_color": [0, 0, 0],
    "image_rotation_interval": 15,
}
dm = FakeDM()
p = StaticImagePlugin("static-image", dict(base_cfg), dm, None, plugin_manager())
check("baseline: the top-level image loads", len(p.images_list) == 1 and p.image_loaded)

saved = dict(base_cfg, background_color=[10, 20, 30], fit_to_display=False,
             preserve_aspect_ratio=True, image_rotation_interval=42)
p.on_config_change(saved)
check("on_config_change keeps the top-level images list", len(p.images_list) == 1)
check("background_color is refreshed", p.background_color == (10, 20, 30))
check("fit_to_display is refreshed", p.fit_to_display is False)
check("preserve_aspect_ratio is refreshed", p.preserve_aspect_ratio is True)
check("image_rotation_interval is refreshed", p.image_rotation_interval == 42)

# After the rotation interval passes, the next frame must still draw the image.
p.current_image_start_time = time.time() - 1000
p.display()
check("display after the rotation interval still has an image", p.image_loaded
      and p.current_image is not None)

# --- M5: schedule windows use the configured LEDMatrix timezone ----------
tz_name = far_zone()
local = datetime.now(pytz.timezone(tz_name))
window = {
    "enabled": True,
    "mode": "time_range",
    "start_time": (local - timedelta(minutes=30)).strftime("%H:%M"),
    "end_time": (local + timedelta(minutes=30)).strftime("%H:%M"),
}
tz_plugin = StaticImagePlugin("static-image", dict(base_cfg), FakeDM(), None,
                              plugin_manager(tz_name))
check(f"a window open now in {tz_name} counts as scheduled",
      tz_plugin._is_image_scheduled({"path": FIXTURE, "schedule": window}) is True)

bad_tz = StaticImagePlugin("static-image", dict(base_cfg), FakeDM(), None,
                           plugin_manager("Not/AZone"))
try:
    outcome = bad_tz._is_image_scheduled({"path": FIXTURE, "schedule": window})
    check("an invalid timezone falls back to system time instead of raising",
          isinstance(outcome, bool))
except Exception as exc:  # noqa: BLE001
    check(f"an invalid timezone falls back to system time instead of raising ({exc})", False)

print()
failed = [case for case, passed in results if not passed]
print(f"{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
