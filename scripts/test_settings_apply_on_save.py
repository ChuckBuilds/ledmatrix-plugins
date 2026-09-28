#!/usr/bin/env python3
"""A setting saved in the web UI must take effect without a restart.

The core applies a save by calling the plugin's ``on_config_change`` (see
core ``display_controller.py``, the per-plugin config-change callback); it
does not reload the plugin. ``BasePlugin.on_config_change`` only replaces
``self.config`` and ``self.enabled``, so any plugin that copies settings into
attributes in ``__init__`` -- nearly all of them -- ignored every save until
the service restarted, with nothing in the UI saying so.

For each plugin below this builds the real plugin with the core's test
mocks, saves a config that changes one setting, and checks the attribute the
plugin draws from moved. Each plugin runs in its own interpreter, since they
are all modules named ``manager``.

Run: LEDMATRIX_CORE=/path/to/LEDMatrix python scripts/test_settings_apply_on_save.py
Exit 0 pass, 1 fail, 2 skip (no core checkout).
"""
import json
import os
import subprocess  # nosec B404
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUGINS = REPO / "plugins"

#: plugin -> (base config, saved change, attribute path, expected value after save)
CASES = {
    "hello-world": ({"message": "Hello"}, {"message": "Changed"}, "message", "Changed"),
    "clock-simple": ({"time_format": "12h"}, {"time_format": "24h"}, "time_format", "24h"),
    "7-segment-clock": ({"is_24_hour_format": True}, {"is_24_hour_format": False},
                        "is_24_hour_format", False),
    "christmas-countdown": ({"text_color": [255, 0, 0]}, {"text_color": [0, 0, 255]},
                            "text_color", [0, 0, 255]),
    "youtube-stats": ({"channel_id": "UC1"}, {"channel_id": "UC2"}, "channel_id", "UC2"),
    "jellyfin-now-playing": ({}, {"jellyfin_url": "http://jf:8096"},
                             "jellyfin_url", "http://jf:8096"),
    "olympics": ({"top_countries_count": 5}, {"top_countries_count": 8},
                 "top_countries_count", 8),
    "calendar": ({"max_events": 3}, {"max_events": 5}, "max_events", 5),
    "ledmatrix-music": ({"preferred_source": "spotify", "polling_interval_seconds": 2},
                        {"polling_interval_seconds": 5}, "polling_interval", 5),
    "birdnet-go": ({"text": {"font_size": 8}}, {"text": {"font_size": 10}}, "font_size", 10),
    "ledmatrix-weather": ({"show_feels_like": True}, {"show_feels_like": False},
                          "show_feels_like", False),
    # enable_scrolling is what the core reads to choose the high-FPS loop.
    "text-display": ({"scroll": False}, {"scroll": True}, "enable_scrolling", True),
    # The renderer reads favorite_players from the config it was built with.
    "masters-tournament": ({"favorite_players": ["Scheffler"]},
                           {"favorite_players": ["McIlroy"]},
                           "renderer.config.favorite_players", ["McIlroy"]),
    # The scroll and Vegas cards read their config from the scroll manager.
    "afl-scoreboard": ({"scroll_card": {"vs_text": "VS"}}, {"scroll_card": {"vs_text": "@"}},
                       "_scroll_manager.config.scroll_card.vs_text", "@"),
    "nrl-scoreboard": ({"scroll_card": {"vs_text": "VS"}}, {"scroll_card": {"vs_text": "@"}},
                       "_scroll_manager.config.scroll_card.vs_text", "@"),
    # enabled: false, so the save does not start a real broker connection.
    "mqtt-notifications": ({"enabled": False, "mqtt": {"host": "broker-a"}},
                           {"mqtt": {"host": "broker-b"}}, "mqtt_host", "broker-b"),
}

PROBE = r'''
import json, sys
plugin_dir, base, change, attr = sys.argv[1], *map(json.loads, sys.argv[2:4]), sys.argv[4]
sys.path.insert(0, plugin_dir)
from src.plugin_system.testing.mocks import (
    MockCacheManager, MockDisplayManager, MockPluginManager)
import manager as m
if getattr(m, "GOOGLE_AVAILABLE", True) is False:
    print(json.dumps("SKIP: the Google client libraries are not installed"))
    raise SystemExit
cls = next(o for o in vars(m).values() if isinstance(o, type)
           and o.__module__ == "manager" and hasattr(o, "display"))
config = dict({"enabled": True}, **base)
plugin = cls(plugin_dir.replace("\\", "/").rsplit("/", 1)[-1], config,
             MockDisplayManager(), MockCacheManager(), MockPluginManager())
import functools
read = lambda: functools.reduce(
    lambda obj, name: obj.get(name) if isinstance(obj, dict) else getattr(obj, name),
    attr.split("."), plugin)
before = read()
plugin.on_config_change(dict(config, **change))
after = read()
norm = lambda v: list(v) if isinstance(v, tuple) else v
print(json.dumps([norm(before), norm(after)]))
'''


def find_core():
    for candidate in (os.environ.get("LEDMATRIX_CORE"), REPO.parent / "LEDMatrix"):
        if candidate and (Path(candidate) / "src" / "plugin_system").is_dir():
            return Path(candidate)
    return None


def main():
    core = find_core()
    if core is None:
        print("SKIP: no LEDMatrix core checkout (set LEDMATRIX_CORE)")
        return 2
    env = dict(os.environ, PYTHONPATH=str(core), EMULATOR="true")
    failed = 0
    for plugin, (base, change, attr, want) in CASES.items():
        # List argv, no shell: this interpreter and paths inside the repo.
        proc = subprocess.run(  # nosec B603  # nosemgrep
            [sys.executable, "-c", PROBE, str(PLUGINS / plugin),
             json.dumps(base), json.dumps(change), attr],
            capture_output=True, text=True, cwd=str(core), env=env)
        try:
            result = json.loads(proc.stdout.strip().splitlines()[-1])
            if isinstance(result, str) and result.startswith("SKIP"):
                print("SKIP  %s: %s" % (plugin, result[6:]))
                continue
            before, after = result
        except (ValueError, IndexError):
            print("FAIL  %s: probe did not run\n%s" % (plugin, proc.stderr[-1500:]))
            failed += 1
            continue
        ok = after == want and before != want
        failed += not ok
        print("%s  %s: saving %s applies without a restart%s"
              % ("PASS" if ok else "FAIL", plugin, attr,
                 "" if ok else " (before %r, after %r, want %r)" % (before, after, want)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
