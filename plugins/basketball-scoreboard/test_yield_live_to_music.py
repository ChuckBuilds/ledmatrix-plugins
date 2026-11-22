#!/usr/bin/env python3
"""yield_live_to_music: a live game steps aside while the music plugin plays.

Run: <core-venv>/bin/python plugins/basketball-scoreboard/test_yield_live_to_music.py
"""

import sys
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

from manager import BasketballScoreboardPlugin  # noqa: E402

results = []


def check(name, passed):
    results.append((name, passed))
    print(f"{'PASS' if passed else 'FAIL'}: {name}")


class FakeMusic:
    def __init__(self, playing=True, priority=True, enabled=True, boom=False):
        self.playing, self.priority, self.enabled, self.boom = playing, priority, enabled, boom

    def has_live_priority(self):
        return self.priority

    def has_live_content(self):
        if self.boom:
            raise RuntimeError("boom")
        return self.playing


class FakePM:
    def __init__(self, plugins):
        self.plugins = plugins

    def get_plugin(self, plugin_id):
        return self.plugins.get(plugin_id)


def make(yield_on=True, plugins=None, pm=True):
    p = BasketballScoreboardPlugin.__new__(BasketballScoreboardPlugin)
    p.config = {"yield_live_to_music": yield_on}
    p.plugin_manager = FakePM(plugins or {}) if pm else None
    return p


check("music playing -> yield", make(plugins={"ledmatrix-music": FakeMusic()})._music_is_playing())
check("legacy 'music' id is found", make(plugins={"music": FakeMusic()})._music_is_playing())
check("setting off -> never yield",
      not make(yield_on=False, plugins={"ledmatrix-music": FakeMusic()})._music_is_playing())
check("music paused -> no yield",
      not make(plugins={"ledmatrix-music": FakeMusic(playing=False)})._music_is_playing())
check("music without live priority -> no yield",
      not make(plugins={"ledmatrix-music": FakeMusic(priority=False)})._music_is_playing())
check("music plugin disabled -> no yield",
      not make(plugins={"ledmatrix-music": FakeMusic(enabled=False)})._music_is_playing())
check("no music plugin -> no yield", not make(plugins={})._music_is_playing())
check("no plugin manager -> no yield", not make(pm=False)._music_is_playing())
check("music plugin error -> no yield",
      not make(plugins={"ledmatrix-music": FakeMusic(boom=True)})._music_is_playing())

p = make(plugins={"ledmatrix-music": FakeMusic()})
p.is_enabled = True
check("has_live_content() is False while music plays", p.has_live_content() is False)

failed = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
