#!/usr/bin/env python3
"""
Tests that unchanged F1 data does not re-render the scroll images.

Regression under test: update() called _prepare_scroll_content()
unconditionally, which re-rendered all twelve scroll modes every refresh.
Measured on a Pi that was 12.46s, one image of which was 11250x64px. Outside a
race weekend the refreshed data is byte-identical to the previous one, so
nearly all of it rebuilt images that were already correct. Plugin updates run
on a worker thread, but the render loop shares the interpreter, and the
marquee stalled for up to half a second at a time.

The signature is what makes the skip safe, so most of this file is about it:
a field left out means the panel keeps showing stale content, which is a worse
failure than the cost it saves. Every input is mutated in turn and required to
move the hash.

The methods are exercised against a stand-in ``self`` rather than a
constructed plugin, so the test needs no display manager, no network and no
cache -- only that manager.py imports.

Run: <core-venv>/bin/python plugins/f1-scoreboard/test_scroll_rebuild_skip.py
"""

import sys
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))
for candidate in (Path("/home/rackpi/projects/LEDMatrix"),
                  plugin_dir.parents[2] / "LEDMatrix"):
    if (candidate / "src" / "plugin_system" / "base_plugin.py").exists():
        sys.path.insert(0, str(candidate))
        break

from manager import F1ScoreboardPlugin  # noqa: E402

failures = []


def check(label, ok):
    print(("  PASS  " if ok else "  FAIL  ") + label)
    if not ok:
        failures.append(label)


class _Renderer:
    show_championship_leaders = True
    show_championship_battle = True
    show_constructor_battle = True
    show_driver_form = True
    show_standings_header = True
    show_circuit_info = True


class _Logger:
    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass


class _Plugin:
    """A stand-in ``self`` carrying only what the signature touches."""

    _scroll_content_signature = F1ScoreboardPlugin._scroll_content_signature

    def __init__(self):
        self.config = {"recent_races": {"number_of_races": 3}}
        self.logger = _Logger()
        self._scroll_renderer = _Renderer()
        self._is_live = False
        self._live_session = None
        self._driver_standings = [{"code": "VER", "points": 100}]
        self._constructor_standings = [{"constructor_id": "rb", "points": 200}]
        self._driver_battle_p1 = {"code": "VER"}
        self._driver_battle_p2 = {"code": "NOR"}
        self._constructor_battle_p1 = {"constructor_id": "rb"}
        self._constructor_battle_p2 = {"constructor_id": "mcl"}
        self._recent_races = [{"name": "Monza", "all_results": []}]
        self._upcoming_race = {"name": "Spa"}
        self._qualifying = {"race_name": "Monza"}
        self._practice_results = {"FP1": {"results": []}}
        self._sprint = {"race_name": "Monza", "results": []}
        self._calendar = [{"name": "Spa"}]
        self.favorite_driver = "VER"
        self.favorite_team = "rb"


# Every field the signature must cover, with a mutation that changes it.
# Keep this list in step with _scroll_content_signature: an input that is
# rendered but absent here is exactly the bug this file exists to catch.
MUTATIONS = [
    ("_is_live", lambda p: setattr(p, "_is_live", True)),
    ("_live_session", lambda p: setattr(p, "_live_session", "RACE")),
    ("_driver_standings",
     lambda p: p._driver_standings.__setitem__(0, {"code": "VER", "points": 125})),
    ("_constructor_standings",
     lambda p: p._constructor_standings.__setitem__(
         0, {"constructor_id": "rb", "points": 250})),
    ("_driver_battle_p1", lambda p: setattr(p, "_driver_battle_p1", {"code": "HAM"})),
    ("_driver_battle_p2", lambda p: setattr(p, "_driver_battle_p2", {"code": "LEC"})),
    ("_constructor_battle_p1",
     lambda p: setattr(p, "_constructor_battle_p1", {"constructor_id": "fer"})),
    ("_constructor_battle_p2",
     lambda p: setattr(p, "_constructor_battle_p2", {"constructor_id": "mer"})),
    ("_recent_races",
     lambda p: p._recent_races.append({"name": "Spa", "all_results": []})),
    ("_upcoming_race", lambda p: setattr(p, "_upcoming_race", {"name": "Monaco"})),
    ("_qualifying", lambda p: setattr(p, "_qualifying", {"race_name": "Spa"})),
    ("_practice_results",
     lambda p: p._practice_results.__setitem__("FP2", {"results": []})),
    ("_sprint",
     lambda p: setattr(p, "_sprint", {"race_name": "Spa", "results": []})),
    ("_calendar", lambda p: p._calendar.append({"name": "Monaco"})),
    ("favorite_driver", lambda p: setattr(p, "favorite_driver", "NOR")),
    ("favorite_team", lambda p: setattr(p, "favorite_team", "mcl")),
    ("renderer show_ flag",
     lambda p: setattr(p._scroll_renderer, "show_driver_form", False)),
    ("recent_races config",
     lambda p: p.config.__setitem__("recent_races", {"number_of_races": 5})),
]


def main():
    print("the signature is stable for identical data")
    a, b = _Plugin(), _Plugin()
    check("two identical states hash the same",
          a._scroll_content_signature() == b._scroll_content_signature())
    check("the same state hashes the same twice",
          a._scroll_content_signature() == a._scroll_content_signature())

    print("\nevery rendered input moves the signature")
    for name, mutate in MUTATIONS:
        plugin = _Plugin()
        before = plugin._scroll_content_signature()
        mutate(plugin)
        after = plugin._scroll_content_signature()
        check("%s is covered" % name, before != after)

    print("\nthe skip and its escape hatch")

    class _BodyRan(Exception):
        """Raised from the first renderer call past the guard."""

    class _TripRenderer(_Renderer):
        def render_f1_separator(self):
            raise _BodyRan()

    class _Guarded(_Plugin):
        # The real method, so the guard under test is the shipped one rather
        # than a copy of it.
        _prepare_scroll_content = F1ScoreboardPlugin._prepare_scroll_content

        def __init__(self):
            super().__init__()
            self._scroll_content_sig = None
            self._scroll_renderer = _TripRenderer()

    def rebuilt(plugin, force=False):
        """True if the body past the guard ran.

        The body's first statement renders the separator, which trips. Nothing
        beyond that point needs a display manager because nothing beyond it
        runs.
        """
        try:
            plugin._prepare_scroll_content(force=force)
        except _BodyRan:
            return True
        return False

    plugin = _Guarded()
    check("the first build runs", rebuilt(plugin) is True)
    check("unchanged data does not rebuild", rebuilt(plugin) is False)
    check("still does not rebuild on a third pass", rebuilt(plugin) is False)

    plugin._driver_standings[0]["points"] = 999
    check("changed data rebuilds", rebuilt(plugin) is True)
    check("and then settles again", rebuilt(plugin) is False)

    check("force=True rebuilds despite a matching signature",
          rebuilt(plugin, force=True) is True)

    print("\n%s" % ("FAILED: %d" % len(failures) if failures
                    else "All checks passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
