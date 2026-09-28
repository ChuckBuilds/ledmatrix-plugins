#!/usr/bin/env python3
"""A setting declared at the root AND in a nested block must be heard from both.

afl-scoreboard and nrl-scoreboard declare the game limits and
``show_favorite_teams_only`` twice: at the root (on the main settings page)
and inside ``game_limits`` / ``filtering`` (advanced). The adapter preferred
the nested copy whenever it was present -- and the core fills every schema
default into the config, so it was always present. A user who set "Recent
games to show" to 3 on the main page saved it and kept seeing 1.

This runs the plugin's real ``_adapt_config_for_manager`` on a config filled
the way the core fills it (``schema_manager.prepare_plugin_config``), so the
default fill that caused the bug is the core's own.

Run: LEDMATRIX_CORE=/path/to/LEDMatrix python scripts/test_root_settings_reach_managers.py
Exit 0 pass, 1 fail, 2 skip (no core checkout).
"""
import json
import os
import subprocess  # nosec B404
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUGINS = REPO / "plugins"

#: plugin -> the manager_config key its settings land under
PLUGINS_UNDER_TEST = {"afl-scoreboard": "afl_scoreboard", "nrl-scoreboard": "nrl_scoreboard"}

#: (label, user config as saved, manager key, expected)
CASES = [
    ("root recent_games_to_show is heard", {"recent_games_to_show": 3},
     "recent_games_to_show", 3),
    ("root upcoming_games_to_show is heard", {"upcoming_games_to_show": 4},
     "upcoming_games_to_show", 4),
    ("root show_favorite_teams_only is heard", {"show_favorite_teams_only": False},
     "show_favorite_teams_only", False),
    ("root favorite_rotation_boost is heard", {"favorite_rotation_boost": 3},
     "favorite_rotation_boost", 3),
    ("a changed game_limits value still wins",
     {"recent_games_to_show": 3, "game_limits": {"recent_games_to_show": 5}},
     "recent_games_to_show", 5),
    ("a changed filtering value still wins",
     {"show_favorite_teams_only": True, "filtering": {"show_favorite_teams_only": False}},
     "show_favorite_teams_only", False),
    ("untouched, the schema default applies", {}, "recent_games_to_show", 1),
]

PROBE = r'''
import json, logging, sys
from unittest.mock import MagicMock
plugin_dir, key, cases = sys.argv[1], sys.argv[2], json.loads(sys.argv[3])
sys.path.insert(0, plugin_dir)
from src.plugin_system.schema_manager import extract_schema_defaults, prepare_plugin_config
import manager as m
schema = json.load(open(plugin_dir + "/config_schema.json", encoding="utf-8"))
defaults = extract_schema_defaults(schema)
cls = next(o for o in vars(m).values() if isinstance(o, type)
           and hasattr(o, "_adapt_config_for_manager") and o.__module__ == "manager")
out = []
for saved, want_key in cases:
    p = cls.__new__(cls)
    p.config = prepare_plugin_config(json.loads(json.dumps(saved)), schema, defaults)
    p.logger = logging.getLogger("probe")
    for attr in ("cache_manager", "display_manager", "plugin_manager"):
        setattr(p, attr, MagicMock())
    adapted = None
    for _ in range(40):
        try:
            adapted = p._adapt_config_for_manager()
            break
        except AttributeError as exc:
            name = str(exc).rsplit("'", 2)[-2] if "'" in str(exc) else ""
            if not name or hasattr(p, name):
                raise
            setattr(p, name, MagicMock())
    out.append(adapted[key].get(want_key))
print(json.dumps(out))
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
    for plugin, key in PLUGINS_UNDER_TEST.items():
        # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
        proc = subprocess.run(  # nosec B603 - list argv, no shell: this interpreter and repo paths
            [sys.executable, "-c", PROBE, str(PLUGINS / plugin), key,
             json.dumps([(saved, want_key) for _l, saved, want_key, _w in CASES])],
            capture_output=True, text=True, cwd=str(core), env=env)
        try:
            got = json.loads(proc.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            print("FAIL  %s: probe did not run\n%s" % (plugin, proc.stderr[-1500:]))
            failed += 1
            continue
        for (label, _saved, _k, want), value in zip(CASES, got):
            ok = value == want
            failed += not ok
            print("%s  %s: %s%s" % ("PASS" if ok else "FAIL", plugin, label,
                                    "" if ok else " (got %r, want %r)" % (value, want)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
