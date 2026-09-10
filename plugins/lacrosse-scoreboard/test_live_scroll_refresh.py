#!/usr/bin/env python3
"""A live score reaches the scrolling strip without waiting for the cycle to end.

In scroll mode the games are rendered into one wide image and scrolled past the
panel. `_scroll_prepared` was set at prepare time and cleared only when
`is_complete()` fired, so a score changed mid-cycle stayed frozen in the pixels
until the marquee finished -- minutes, for a long game list. Restarting the
display forces a rebuild, which is the workaround users report finding.

Three things here are easy to get wrong and are each pinned:

  * The clock must NOT trigger a rebuild. It ticks every second, and a rebuild
    re-renders every card into one wide image (measured at 6536x64 for six
    games). status_text embeds the clock, so it is excluded for the same reason.
  * The rebuild must preserve scroll_position AND total_distance_scrolled.
    ScrollHelper.set_scrolling_image() resets both: without the first the
    marquee snaps back to the start, without the second the cycle restarts and
    a game that keeps scoring could stop the strip ever completing.
  * The fingerprint is a DENYLIST, not an allowlist. The first version of this
    fix listed fields to watch and omitted several the card draws.

Run: <core-venv>/bin/python plugins/lacrosse-scoreboard/test_live_scroll_refresh.py
"""

import os
import sys

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

from manager import LacrosseScoreboardPlugin as Plugin  # noqa: E402

FAILURES = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILURES.append(label)


def game(gid="1", home="2", away="1", **extra):
    """A live game dict. Only the fields this fix reasons about need to be real."""
    g = {"id": gid, "home_score": home, "away_score": away,
         "period": 3, "period_text": "3rd",
         "clock": "12:04", "status_text": "12:04 - 3rd",
         "is_final": False, "is_halftime": False,
         "home_abbr": "AAA", "away_abbr": "BBB"}
    g.update(extra)
    return g


class _Manager:
    def __init__(self, games=()):
        self.live_games = list(games)


class _Helper:
    """Stands in for ScrollHelper, including the reset that makes this hard."""

    def __init__(self):
        self.scroll_position = 0.0
        self.total_distance_scrolled = 0.0
        self.total_scroll_width = 1376
        self.scroll_complete = False

    def set_scrolling_image(self, width=1376):
        self.total_scroll_width = width
        self.scroll_position = 0.0            # <- the reset the fix works around
        self.total_distance_scrolled = 0.0
        self.scroll_complete = False


class _Stub:
    """Carries only what the fix touches."""

    LIVE_VOLATILE_FIELDS = Plugin.LIVE_VOLATILE_FIELDS
    LIVE_SCROLL_REBUILD_MIN_SECONDS = Plugin.LIVE_SCROLL_REBUILD_MIN_SECONDS
    _live_scroll_managers = Plugin._live_scroll_managers
    _live_scroll_fields = Plugin._live_scroll_fields
    _fingerprint_games = Plugin._fingerprint_games
    _live_scroll_fingerprint = Plugin._live_scroll_fingerprint
    _live_scroll_needs_rebuild = Plugin._live_scroll_needs_rebuild
    _note_live_scroll_built = Plugin._note_live_scroll_built
    _preserving_scroll_position = Plugin._preserving_scroll_position

    def __init__(self, games=(), helper=None, second_league_games=()):
        # The registry shape the multi-league scoreboards use; the single-league
        # ones are covered by the _get_manager branch exercised below.
        self._league_registry = {
            "primary": {"enabled": True, "managers": {"live": _Manager(games)}},
            "disabled": {"enabled": False,
                         "managers": {"live": _Manager(second_league_games)}},
        }
        self._live_scroll_fingerprints = {}
        self._live_scroll_rebuilt_at = {}
        self.logger = type("L", (), {"info": lambda *a, **k: None,
                                     "debug": lambda *a, **k: None})()
        self._helper = helper

        class _SM:
            def __init__(self, h): self._h = h
            def get_scroll_display(self, mode_type):
                return type("SD", (), {"scroll_helper": self._h})()

        self._scroll_manager = _SM(helper) if helper else None

    def _games(self):
        return self._league_registry["primary"]["managers"]["live"].live_games

    def _set(self, games):
        self._league_registry["primary"]["managers"]["live"].live_games = list(games)


KEY = "live"


def fresh(games=(), **kw):
    s = _Stub(games, **kw)
    # The third argument is a *fingerprint*, captured from the managers before
    # the render -- not the games list. Passing games here stored something that
    # could never compare equal, so everything looked like a change.
    s._note_live_scroll_built(KEY, "live", s._live_scroll_fingerprint())
    s._live_scroll_rebuilt_at[KEY] = 0.0        # past the rate-limit floor
    return s


print("manager discovery")
s = _Stub([game()])
check("finds the enabled league's live manager", len(s._live_scroll_managers()) == 1)
check("skips a disabled league",
      all(m.live_games == s._games() for m in s._live_scroll_managers()))


class _SingleLeague(_Stub):
    """The afl/nrl shape: no registry, a _get_manager accessor instead."""

    def __init__(self, games):
        super().__init__(games)
        self._league_registry = None
        self._mgr = _Manager(games)

    def _get_manager(self, mode):
        return self._mgr if mode == "live" else None


check("falls back to _get_manager for single-league plugins",
      len(_SingleLeague([game()])._live_scroll_managers()) == 1)


print("\nwhat counts as a change")
s = fresh([game()])
check("nothing changed -> no rebuild", not s._live_scroll_needs_rebuild(KEY, "live"))

s = fresh([game()])
s._set([game(clock="11:58", status_text="11:58 - 3rd")])
check("the clock ticking is NOT a rebuild", not s._live_scroll_needs_rebuild(KEY, "live"),
      "a rebuild re-renders every card; the clock moves every second")

for label, kw in [("a score", {"home": "3"}),
                  ("the period", {"period_text": "OT", "period": 4}),
                  ("going final", {"is_final": True}),
                  ("halftime", {"is_halftime": True}),
                  ("any other rendered field", {"situation": "power play"})]:
    s = fresh([game()])
    s._set([game(**kw)])
    check(f"{label} IS a rebuild", s._live_scroll_needs_rebuild(KEY, "live"))

s = fresh([game()])
s._set([game(), game(gid="2")])
check("a second game going live is a rebuild", s._live_scroll_needs_rebuild(KEY, "live"))


print("\nthe denylist is exactly the volatile fields")
check("clock is excluded", "clock" in Plugin.LIVE_VOLATILE_FIELDS)
check("status_text is excluded (it embeds the clock)",
      "status_text" in Plugin.LIVE_VOLATILE_FIELDS)
check("scores are NOT excluded", "home_score" not in Plugin.LIVE_VOLATILE_FIELDS)
# The bug the denylist exists to prevent: a rendered field silently unwatched.
s = fresh([game()])
s._set([game(some_new_field_a_card_draws="x")])
check("an unforeseen field still triggers a rebuild",
      s._live_scroll_needs_rebuild(KEY, "live"),
      "an allowlist would have missed this; that was the original bug")


print("\nfields the display pipeline adds must not look like a change")
# _collect_games_for_scroll() decorates each game with "league" and "status"
# *in place*, mutating the dicts the live manager holds; the next update()
# replaces them with undecorated ones. A fingerprint that counted those flipped
# on every update whether or not anything had changed -- an end-to-end
# simulation caught it rebuilding the strip on a bare clock tick.
s = fresh([game()])
s._set([dict(game(), league="nhl", status={"state": "in"})])
check("decoration alone is NOT a rebuild", not s._live_scroll_needs_rebuild(KEY, "live"),
      "league/status are added by the display pipeline, not the data source")
s = fresh([dict(game(), league="nhl", status={"state": "in"})])
s._set([game()])
check("losing the decoration is NOT a rebuild either",
      not s._live_scroll_needs_rebuild(KEY, "live"),
      "update() replaces decorated dicts with fresh undecorated ones")
s = fresh([dict(game(), league="nhl", status={"state": "in"})])
s._set([dict(game(home="9"), league="nhl", status={"state": "in"})])
check("a real change still shows through the decoration",
      s._live_scroll_needs_rebuild(KEY, "live"))


print("\nwhat must never trigger a rebuild")
s = fresh([game()])
check("recent mode is untouched", not s._live_scroll_needs_rebuild(KEY, "recent"))
check("upcoming mode is untouched", not s._live_scroll_needs_rebuild(KEY, "upcoming"))
check("no live games -> nothing to rebuild",
      not _Stub([])._live_scroll_needs_rebuild(KEY, "live"))
check("first build is not a 'change'",
      not _Stub([game()])._live_scroll_needs_rebuild(KEY, "live"))


print("\nrebuilds are rate limited")
s = _Stub([game()])
s._note_live_scroll_built(KEY, "live", s._live_scroll_fingerprint())      # stamps the clock
s._set([game(home="3")])
check("a change inside the floor is deferred",
      not s._live_scroll_needs_rebuild(KEY, "live"),
      "a large slate would otherwise rebuild a multi-thousand-pixel image ~1/sec")
s._live_scroll_rebuilt_at[KEY] = 0.0
check("and is not lost -- it fires once the floor passes",
      s._live_scroll_needs_rebuild(KEY, "live"))


print("\nthe marquee keeps its place across a rebuild")
helper = _Helper()
s = _Stub([game()], helper=helper)
helper.scroll_position = 812.0
helper.total_distance_scrolled = 812.0
with s._preserving_scroll_position("live", active=True):
    helper.set_scrolling_image()
check("scroll position is restored", helper.scroll_position == 812.0,
      f"{helper.scroll_position}")
check("cycle progress is restored", helper.total_distance_scrolled == 812.0,
      "otherwise a game that keeps scoring restarts the cycle forever")
check("not left marked complete", helper.scroll_complete is False)

helper = _Helper()
s = _Stub([game()], helper=helper)
helper.scroll_position = 1300.0
with s._preserving_scroll_position("live", active=True):
    helper.set_scrolling_image(width=1200)
check("position is clamped to a shorter strip", helper.scroll_position == 1199,
      f"{helper.scroll_position} (width 1200)")

helper = _Helper()
s = _Stub([game()], helper=helper)
helper.scroll_position = 500.0
with s._preserving_scroll_position("live", active=False):
    helper.set_scrolling_image()
check("a first build still starts at zero", helper.scroll_position == 0.0)

s = _Stub([game()], helper=None)
try:
    with s._preserving_scroll_position("live", active=True):
        pass
    check("no scroll manager is survivable", True)
except Exception as exc:
    check("no scroll manager is survivable", False, str(exc))


print("\n" + "=" * 62)
if FAILURES:
    print(f"{len(FAILURES)} check(s) failed: {FAILURES}")
    sys.exit(1)
print("All checks passed.")
