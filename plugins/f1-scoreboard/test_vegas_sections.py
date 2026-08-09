#!/usr/bin/env python3
"""
Tests for which sections F1 contributes to the Vegas marquee.

Regression under test: get_vegas_content() used to concatenate every prepared
mode. Measured on a 512px panel that was 114 cards / 14,592px -- close to six
minutes of unbroken F1 at 50px/s, because what the plugin's own rotation shows
as eight separate screens the marquee splices into one block. It now emits only
the sections named in ``vegas.sections``, defaulting to the next race and the
last race's results.

The selection methods are exercised against a stand-in ``self`` rather than a
constructed plugin, so the test needs no display manager, no network and no
cache -- only that manager.py imports.

Run: <core-venv>/bin/python plugins/f1-scoreboard/test_vegas_sections.py
"""

import sys
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))
# The core provides BasePlugin, which manager.py imports at module scope.
for candidate in (Path("/home/rackpi/projects/LEDMatrix"),
                  plugin_dir.parents[2] / "LEDMatrix"):
    if (candidate / "src" / "plugin_system" / "base_plugin.py").exists():
        sys.path.insert(0, str(candidate))
        break

from manager import F1ScoreboardPlugin  # noqa: E402


class _Logger:
    def __init__(self):
        self.warnings = []

    def warning(self, msg, *args):
        self.warnings.append(msg % args if args else msg)


class _ScrollManager:
    """Stands in for ScrollDisplayManager, holding one marker per mode."""

    def __init__(self, modes):
        self._modes = modes

    def is_mode_prepared(self, mode_key):
        return mode_key in self._modes

    def get_vegas_items_for_mode(self, mode_key):
        return list(self._modes.get(mode_key, []))


class _Renderer:
    show_circuit_info = True

    def render_upcoming_race(self, race):
        return "upcoming:" + race["name"]

    def render_circuit_info_card(self, race):
        return "circuit:" + race["name"]


class _Plugin:
    """A stand-in ``self`` carrying only what the selection methods touch."""

    # The methods under test, bound to this stand-in.
    _VEGAS_SECTION_ORDER = F1ScoreboardPlugin._VEGAS_SECTION_ORDER
    _VEGAS_DEFAULT_SECTIONS = F1ScoreboardPlugin._VEGAS_DEFAULT_SECTIONS
    _VEGAS_SECTION_MODES = F1ScoreboardPlugin._VEGAS_SECTION_MODES
    _vegas_sections = F1ScoreboardPlugin._vegas_sections
    _vegas_section_images = F1ScoreboardPlugin._vegas_section_images
    get_vegas_content = F1ScoreboardPlugin.get_vegas_content

    def __init__(self, config=None, modes=None, upcoming=True, last_race=True):
        self.config = config or {}
        self.logger = _Logger()
        self._scroll_manager = _ScrollManager(modes or {})
        self._scroll_renderer = _Renderer()
        self._upcoming_race = {"name": "MONZA"} if upcoming else None
        self._vegas_last_race_cards = (
            ["last:result", "last:gaps"] if last_race else [])

    def _enrich_upcoming_with_countdown(self, race):
        return race


ALL_MODES = {
    "championship_leaders": ["leaders"],
    "championship_battle": ["battle:drv"],
    "constructor_battle": ["battle:con"],
    "driver_spotlight": ["spot:drv"],
    "team_spotlight": ["spot:team"],
    "driver_standings": ["drv:%d" % i for i in range(12)],
    "constructor_standings": ["con:%d" % i for i in range(11)],
    "recent_races": ["recent:%d" % i for i in range(7)],
    "qualifying": ["quali:%d" % i for i in range(24)],
    "practice": ["fp:%d" % i for i in range(33)],
    "sprint": ["sprint:%d" % i for i in range(21)],
    "calendar": ["cal:%d" % i for i in range(5)],
}

failures = []


def check(name, actual, expected):
    if actual == expected:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s\n          expected: %r\n          actual:   %r"
              % (name, expected, actual))
        failures.append(name)


def main():
    print("default is the next race and the last race's results")
    p = _Plugin(modes=ALL_MODES)
    check("default sections", p._vegas_sections(), ["upcoming", "last_race"])
    check("default content", p.get_vegas_content(),
          ["upcoming:MONZA", "circuit:MONZA", "last:result", "last:gaps"])
    check("everything else is left out", 4, len(p.get_vegas_content()))

    print("\nthe old behaviour is still reachable by naming every section")
    p = _Plugin(config={"vegas": {"sections": list(
        F1ScoreboardPlugin._VEGAS_SECTION_ORDER)}}, modes=ALL_MODES)
    everything = p.get_vegas_content()
    check("all sections emit", len(everything), 2 + 2 + sum(
        len(v) for v in ALL_MODES.values()))
    check("leaders still lead", everything[0], "leaders")

    print("\nemission follows _VEGAS_SECTION_ORDER, not the user's ordering")
    p = _Plugin(config={"vegas": {"sections": ["last_race", "upcoming"]}})
    check("reversed input, canonical output", p.get_vegas_content(),
          ["upcoming:MONZA", "circuit:MONZA", "last:result", "last:gaps"])

    print("\nsections with no data contribute nothing")
    p = _Plugin(config={"vegas": {"sections": ["upcoming", "last_race"]}},
                upcoming=False, last_race=False)
    check("no data at all -> None", p.get_vegas_content(), None)
    p = _Plugin(config={"vegas": {"sections": ["qualifying"]}}, modes={})
    check("unprepared mode -> None", p.get_vegas_content(), None)

    print("\ncircuit card follows the renderer's own toggle")
    p = _Plugin(config={"vegas": {"sections": ["upcoming"]}})
    p._scroll_renderer.show_circuit_info = False
    check("circuit card suppressed", p.get_vegas_content(), ["upcoming:MONZA"])

    print("\nlast_race is the most recent race, recent_races is all of them")
    p = _Plugin(config={"vegas": {"sections": ["last_race"]}}, modes=ALL_MODES)
    check("last_race", p.get_vegas_content(), ["last:result", "last:gaps"])
    p = _Plugin(config={"vegas": {"sections": ["recent_races"]}}, modes=ALL_MODES)
    check("recent_races", len(p.get_vegas_content()), 7)

    print("\nan empty list keeps F1 out of the marquee")
    p = _Plugin(config={"vegas": {"sections": []}}, modes=ALL_MODES)
    check("empty stays empty", p._vegas_sections(), [])
    check("empty -> None", p.get_vegas_content(), None)

    print("\nbad input degrades to something usable")
    p = _Plugin(config={"vegas": {"sections": ["upcoming", "bogus"]}})
    check("unknown name dropped", p._vegas_sections(), ["upcoming"])
    check("and warned about", len(p.logger.warnings), 1)

    p = _Plugin(config={"vegas": {"sections": ["nope", "also-nope"]}})
    check("nothing usable -> default", p._vegas_sections(),
          ["upcoming", "last_race"])

    p = _Plugin(config={"vegas": {"sections": "upcoming"}})
    check("a bare string is taken as one entry", p._vegas_sections(), ["upcoming"])

    p = _Plugin(config={"vegas": {"sections": 42}})
    check("a non-list -> default", p._vegas_sections(), ["upcoming", "last_race"])
    check("and warned about", len(p.logger.warnings), 1)

    p = _Plugin(config={"vegas": {"sections": ["  UPCOMING  "]}})
    check("case and whitespace tolerated", p._vegas_sections(), ["upcoming"])

    p = _Plugin(config={})
    check("no vegas block -> default", p._vegas_sections(),
          ["upcoming", "last_race"])

    # The schema forbids these, but config.json is hand-edited often enough that
    # the marquee's render path must not raise on them.
    for bad in (None, [], ["upcoming"], "upcoming", 7):
        p = _Plugin(config={"vegas": bad})
        check("vegas=%r -> default, no raise" % (bad,), p._vegas_sections(),
              ["upcoming", "last_race"])

    print("\nevery section in the order is resolvable")
    p = _Plugin(modes=ALL_MODES)
    unresolvable = [s for s in F1ScoreboardPlugin._VEGAS_SECTION_ORDER
                    if not p._vegas_section_images(s)]
    check("no dead section keys", unresolvable, [])

    print("\n%s" % ("FAILED: %d" % len(failures) if failures else "All checks passed"))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
