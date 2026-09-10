#!/usr/bin/env python3
"""A live score reaches the scrolling strip without waiting for the cycle to end.

Reported: "the football plugin with live games only updates the live game in
progress if I restart the display."

In scroll mode the games are rendered into one wide image and scrolled past the
panel. `_scroll_prepared[scroll_key]` was set at prepare time and cleared only
when `is_complete()` fired, so a touchdown scored mid-cycle stayed frozen in the
pixels until the marquee finished -- minutes, for a long game list. Restarting
the display forces a rebuild, which is exactly the workaround the reporter
found.

The rebuild is the easy half. The hard half is that
ScrollHelper.set_scrolling_image() resets scroll_position and
total_distance_scrolled, so a naive rebuild snaps the marquee back to the start
and restarts the cycle -- worse than the stale score. Both counters are saved
and restored.

And the clock is deliberately *not* part of the trigger: it ticks every second,
and rebuilding on it would re-render every card ~60 times a minute to move two
glyphs.

Run: <core-venv>/bin/python plugins/football-scoreboard/test_live_scroll_refresh.py
"""

import os
import sys

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

from manager import FootballScoreboardPlugin  # noqa: E402

FAILURES = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILURES.append(label)


def game(gid="401872656", home="7", away="3", period_text="4th", clock="0:44",
         halftime=False, final=False, down="1st & 10", possession="home",
         redzone=False, scoring_event="", timeouts=3, period_break=False):
    """Mirrors the fields game_renderer's live card actually reads."""
    return {"id": gid, "home_score": home, "away_score": away,
            "period_text": period_text, "clock": clock,
            "status_text": f"{clock} - {period_text}",   # note: embeds the clock
            "is_halftime": halftime, "is_final": final,
            "is_period_break": period_break,
            "down_distance_text": down, "possession_indicator": possession,
            "is_redzone": redzone, "scoring_event": scoring_event,
            "home_timeouts": timeouts, "away_timeouts": timeouts,
            "home_abbr": "SEA", "away_abbr": "NE"}


class _LiveManager:
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
    """Only what the fingerprint / preserve helpers touch."""

    LIVE_SCROLL_REBUILD_MIN_SECONDS = FootballScoreboardPlugin.LIVE_SCROLL_REBUILD_MIN_SECONDS
    _live_scroll_fields = FootballScoreboardPlugin._live_scroll_fields
    _fingerprint_games = FootballScoreboardPlugin._fingerprint_games
    _live_scroll_fingerprint = FootballScoreboardPlugin._live_scroll_fingerprint
    _live_scroll_needs_rebuild = FootballScoreboardPlugin._live_scroll_needs_rebuild
    _note_live_scroll_built = FootballScoreboardPlugin._note_live_scroll_built
    _preserving_scroll_position = FootballScoreboardPlugin._preserving_scroll_position

    def __init__(self, nfl=(), ncaa=(), helper=None):
        self.nfl_enabled = True
        self.ncaa_fb_enabled = True
        self.nfl_live = _LiveManager(nfl)
        self.ncaa_fb_live = _LiveManager(ncaa)
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


KEY = "football_live_live"

print("what counts as a change")
s = _Stub(nfl=[game()])
s._note_live_scroll_built(KEY, "live", s.nfl_live.live_games)
s._live_scroll_rebuilt_at[KEY] = 0.0
check("nothing changed -> no rebuild", not s._live_scroll_needs_rebuild(KEY, "live"))

s.nfl_live.live_games = [game(clock="0:38")]
check("the clock ticking is NOT a rebuild", not s._live_scroll_needs_rebuild(KEY, "live"),
      "rebuilding per second would re-render every card ~60x/min")

s.nfl_live.live_games = [game(home="14")]
check("a touchdown IS a rebuild", s._live_scroll_needs_rebuild(KEY, "live"))

s = _Stub(nfl=[game()]); s._note_live_scroll_built(KEY, "live", s.nfl_live.live_games)
s._live_scroll_rebuilt_at[KEY] = 0.0
s.nfl_live.live_games = [game(period_text="OT")]
check("period change is a rebuild", s._live_scroll_needs_rebuild(KEY, "live"))

s = _Stub(nfl=[game()]); s._note_live_scroll_built(KEY, "live", s.nfl_live.live_games)
s._live_scroll_rebuilt_at[KEY] = 0.0
s.nfl_live.live_games = [game(halftime=True)]
check("halftime is a rebuild", s._live_scroll_needs_rebuild(KEY, "live"))

s = _Stub(nfl=[game()]); s._note_live_scroll_built(KEY, "live", s.nfl_live.live_games)
s._live_scroll_rebuilt_at[KEY] = 0.0
s.nfl_live.live_games = [game(), game(gid="999", home="0", away="0")]
check("a second game going live is a rebuild", s._live_scroll_needs_rebuild(KEY, "live"))


# --- the fields the first version of this fix missed entirely ---
# It keyed on `period`, which game_renderer never reads (it draws period_text),
# and ignored everything below. Each of these is drawn on the live card, so a
# change the strip does not rebuild for is a change the viewer sees go stale.
for label, kwargs in [
    ("down and distance", {"down": "3rd & 2"}),
    ("possession change", {"possession": "away"}),
    ("entering the red zone", {"redzone": True}),
    ("a TOUCHDOWN banner", {"scoring_event": "TOUCHDOWN"}),
    ("a timeout being used", {"timeouts": 2}),
    ("a period break", {"period_break": True}),
]:
    st = _Stub(nfl=[game()])
    st._note_live_scroll_built(KEY, "live", st.nfl_live.live_games)
    st._live_scroll_rebuilt_at[KEY] = 0.0          # past the rate limit
    st.nfl_live.live_games = [game(**kwargs)]
    check(f"{label} is a rebuild", st._live_scroll_needs_rebuild(KEY, "live"))

# status_text embeds the clock ("0:44 - 4th"), so keying on it would smuggle the
# clock back in and rebuild every second.
st = _Stub(nfl=[game(clock="0:44")])
st._note_live_scroll_built(KEY, "live", st.nfl_live.live_games)
st._live_scroll_rebuilt_at[KEY] = 0.0
st.nfl_live.live_games = [game(clock="0:38")]      # status_text changes with it
check("status_text changing with the clock is NOT a rebuild",
      not st._live_scroll_needs_rebuild(KEY, "live"),
      "status_text is '0:44 - 4th'; keying on it undoes the clock exclusion")


print("\nrebuilds are rate limited")
st = _Stub(nfl=[game()])
st._note_live_scroll_built(KEY, "live", st.nfl_live.live_games)   # stamps the clock
st.nfl_live.live_games = [game(home="14")]
check("a change inside the floor is deferred",
      not st._live_scroll_needs_rebuild(KEY, "live"),
      "a 6536x64 image x50 NCAA games x a play every 30s would rebuild ~1/sec")
st._live_scroll_rebuilt_at[KEY] = 0.0
check("and is not lost -- it fires once the floor passes",
      st._live_scroll_needs_rebuild(KEY, "live"))


print("\nwhat must never trigger a rebuild")
s = _Stub(nfl=[game()]); s._note_live_scroll_built(KEY, "live", s.nfl_live.live_games)
s._live_scroll_rebuilt_at[KEY] = 0.0
check("recent mode is untouched", not s._live_scroll_needs_rebuild(KEY, "recent"))
check("upcoming mode is untouched", not s._live_scroll_needs_rebuild(KEY, "upcoming"))

s = _Stub(nfl=[])
check("no live games -> nothing to rebuild", not s._live_scroll_needs_rebuild(KEY, "live"))

# The first build must not be treated as a change, or every cycle would think
# it needs the preserve path and restore a position from the previous strip.
s = _Stub(nfl=[game()])
check("first build is not a 'change'", not s._live_scroll_needs_rebuild(KEY, "live"))


print("\nper-league scroll fingerprints stay separate")
s = _Stub(nfl=[game()], ncaa=[game(gid="ncaa1")])
s._note_live_scroll_built("live", "live", s.nfl_live.live_games, "nfl")
s._live_scroll_rebuilt_at["live"] = 0.0
s.ncaa_fb_live.live_games = [game(gid="ncaa1", home="21")]
check("an NCAA score does not rebuild the NFL strip",
      not s._live_scroll_needs_rebuild("live", "live", "nfl"))
s.nfl_live.live_games = [game(home="28")]
check("an NFL score does rebuild the NFL strip",
      s._live_scroll_needs_rebuild("live", "live", "nfl"))


print("\nthe marquee keeps its place across a rebuild")
helper = _Helper()
s = _Stub(nfl=[game()], helper=helper)
helper.scroll_position = 812.0
helper.total_distance_scrolled = 812.0

with s._preserving_scroll_position("live", active=True):
    helper.set_scrolling_image()          # what prepare_and_display does

check("scroll position is restored", helper.scroll_position == 812.0,
      f"{helper.scroll_position}")
check("cycle progress is restored", helper.total_distance_scrolled == 812.0,
      "otherwise a game that keeps scoring restarts the cycle forever")
check("not left marked complete", helper.scroll_complete is False)

# A score gaining a digit makes its card wider or narrower.
helper = _Helper()
s = _Stub(nfl=[game()], helper=helper)
helper.scroll_position = 1300.0
helper.total_distance_scrolled = 1300.0
with s._preserving_scroll_position("live", active=True):
    helper.set_scrolling_image(width=1200)   # strip shrank
check("position is clamped to a shorter strip", helper.scroll_position == 1199,
      f"{helper.scroll_position} (width 1200)")

# A first build must start at zero, not inherit a position.
helper = _Helper()
s = _Stub(nfl=[game()], helper=helper)
helper.scroll_position = 500.0
with s._preserving_scroll_position("live", active=False):
    helper.set_scrolling_image()
check("a first build still starts at zero", helper.scroll_position == 0.0,
      f"{helper.scroll_position}")

# No scroll manager at all must not raise.
s = _Stub(nfl=[game()], helper=None)
try:
    with s._preserving_scroll_position("live", active=True):
        pass
    check("no scroll manager is survivable", True)
except Exception as exc:
    check("no scroll manager is survivable", False, str(exc))


# ---------------------------------------------------------------------------
# The helpers behaving correctly is not the claim that matters. The claim is
# that _display_scroll_mode() actually rebuilds mid-cycle. Drive it.
print("\nthe wiring: _display_scroll_mode rebuilds mid-cycle")

from unittest.mock import MagicMock  # noqa: E402


def _wired(score="7"):
    p = FootballScoreboardPlugin.__new__(FootballScoreboardPlugin)
    p.nfl_enabled = True
    p.ncaa_fb_enabled = True
    p.nfl_live = _LiveManager([game(home=score)])
    p.ncaa_fb_live = _LiveManager()
    p._live_scroll_fingerprints = {}
    p._live_scroll_rebuilt_at = {}
    p._scroll_prepared = {}
    p._scroll_active = {}
    p.logger = MagicMock()
    p.nfl_live_priority = True
    p.ncaa_fb_live_priority = False

    helper = _Helper()
    sm = MagicMock()
    sm.prepare_and_display.return_value = True
    sm.display_frame.return_value = True
    sm.is_complete.return_value = False          # mid-cycle, deliberately
    sm.get_scroll_display.return_value = type("SD", (), {"scroll_helper": helper})()
    p._scroll_manager = sm

    p._ensure_manager_updated = lambda m: None
    p._get_manager_for_league_mode = lambda l, m: object()
    p.has_live_content = lambda: True
    p._collect_games_for_scroll = lambda mt, lp: ([game(home=score)], ["nfl"])
    p._get_rankings_cache = lambda: {}
    return p, sm, helper


# First pass builds the strip.
plugin, sm, helper = _wired(score="7")
plugin._display_scroll_mode("football_live", "live", False)
builds_after_first = sm.prepare_and_display.call_count
check("first pass builds the strip", builds_after_first == 1, f"{builds_after_first}")

# Second pass, nothing changed, mid-cycle: must NOT rebuild.
plugin._display_scroll_mode("football_live", "live", False)
check("no change mid-cycle -> no rebuild",
      sm.prepare_and_display.call_count == 1,
      f"{sm.prepare_and_display.call_count} builds")

# A touchdown lands. This is the reported bug: pre-fix the strip stayed frozen
# until is_complete() fired, which is mocked False here on purpose.
helper.scroll_position = 640.0
helper.total_distance_scrolled = 640.0
plugin._live_scroll_rebuilt_at["football_live_live"] = 0.0   # past the rate limit
plugin.nfl_live.live_games = [game(home="14")]
plugin._collect_games_for_scroll = lambda mt, lp: ([game(home="14")], ["nfl"])
plugin._display_scroll_mode("football_live", "live", False)

check("a touchdown rebuilds the strip mid-cycle",
      sm.prepare_and_display.call_count == 2,
      f"{sm.prepare_and_display.call_count} builds; pre-fix this stayed at 1 "
      "until the cycle ended")
check("and the marquee did not jump back to the start",
      helper.scroll_position == 640.0, f"{helper.scroll_position}")

# The clock ticking must not rebuild.
before = sm.prepare_and_display.call_count
plugin._live_scroll_rebuilt_at["football_live_live"] = 0.0   # rule out the rate limit
plugin.nfl_live.live_games = [game(home="14", clock="0:12")]
plugin._display_scroll_mode("football_live", "live", False)
check("the clock ticking still does not rebuild",
      sm.prepare_and_display.call_count == before,
      f"{sm.prepare_and_display.call_count} vs {before}")

print("\n" + "=" * 62)
if FAILURES:
    print(f"{len(FAILURES)} check(s) failed: {FAILURES}")
    sys.exit(1)
print("All checks passed.")
