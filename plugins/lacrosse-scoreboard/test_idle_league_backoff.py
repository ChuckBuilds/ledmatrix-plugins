#!/usr/bin/env python3
"""
Tests that a league with nothing on stops polling on a live cadence.

Regression under test: the live gate decided its interval like this --

    has_recently_checked = self.last_update > 0 and time_since_last_update < 300
    if live_games:             interval = live_update_interval
    elif has_recently_checked: interval = no_data_interval
    else:                      interval = live_update_interval

Once 300s had elapsed, has_recently_checked became False, the interval fell
back to live_update_interval, and it fetched. no_data_interval could therefore
never delay anything past 300s whatever it was set to -- the setting was
inert. Measured on a live rig in mid-August: NHLLiveManager fetched 0 games 22
times in 2 hours, every ~5.5 minutes, around the clock, for a league whose
season had not started. Roughly 264 wasted requests a day, per league.

The interval now comes from an explicit streak of empty looks, which escalates
and is capped, and which any live game resets.

Second regression under test: the two interval settings were read from
``self.mode_config`` -- the per-league ``{sport_key}_scoreboard`` block -- while
the schema declares them (and the web UI writes them) at the config *root*. The
saved value was therefore never seen and every user silently kept the default.
An earlier version of this test could not catch that, because it set
``no_data_interval`` on a stand-in object by hand and so never ran the lookup.
It now builds a real ``SportsLive`` and asserts on what its ``__init__``
resolved.

Only ``SportsCore.__init__`` is stubbed -- it pulls in logo downloading, fonts
and an ESPN data source, none of which this test needs -- so the lookup lines
themselves run for real. The stub's fidelity is asserted against the real
``SportsCore`` source below, so it cannot drift out of sync unnoticed.

Run: <core-venv>/bin/python plugins/lacrosse-scoreboard/test_idle_league_backoff.py
"""

# A test harness: it reaches into protected members on purpose and builds a
# concrete subclass at runtime, neither of which pylint can see as intentional.
# pylint: disable=protected-access,abstract-class-instantiated,unused-argument
import ast
import sys
from pathlib import Path

plugin_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(plugin_dir))
for candidate in (Path("/home/rackpi/projects/LEDMatrix"),
                  plugin_dir.parents[2] / "LEDMatrix"):
    if (candidate / "src" / "plugin_system" / "base_plugin.py").exists():
        sys.path.insert(0, str(candidate))
        break

import sports  # noqa: E402

failures = []


def check(label, ok):
    print(("  PASS  " if ok else "  FAIL  ") + label)
    if not ok:
        failures.append(label)


class _Logger:
    def info(self, *a, **k):
        pass


SPORT_KEY = "test"


def _core_init():
    core_src = (plugin_dir / "sports.py").read_text(encoding="utf-8")
    core = next(c for c in ast.walk(ast.parse(core_src))
                if isinstance(c, ast.ClassDef) and c.name == "SportsCore")
    return core_src, next(m for m in core.body
                          if isinstance(m, ast.FunctionDef) and m.name == "__init__")


def _derive_mode_key():
    """Build the per-league key exactly as this plugin's SportsCore does.

    Not hardcoded: most plugins use f"{sport_key}_scoreboard" but ufc-scoreboard
    uses the bare sport_key. Hardcoding one of them made the stub test fiction
    on the other -- which the fidelity check below caught. Reading the real
    expression out of the source keeps every plugin honest.
    """
    _, init = _core_init()
    for node in ast.walk(init):
        if (isinstance(node, ast.Assign)
                and any(getattr(t, "attr", None) == "mode_config"
                        for t in node.targets)
                and isinstance(node.value, ast.Call) and node.value.args):
            arg = node.value.args[0]
            return _resolve_key(arg), ast.unparse(arg)
    raise AssertionError("SportsCore no longer assigns self.mode_config")


def _resolve_key(node):
    """Evaluate the key expression by hand -- deliberately not with eval().

    Only the two shapes that actually occur are supported; anything else is a
    hard error rather than a guess, so a future rewrite of that line surfaces
    here instead of silently producing a key nothing is stored under.
    """
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name) and node.id == "sport_key":
        return SPORT_KEY
    if isinstance(node, ast.JoinedStr):
        return "".join(_resolve_key(part) for part in node.values)
    if isinstance(node, ast.FormattedValue):
        return _resolve_key(node.value)
    raise AssertionError(
        "unsupported mode_config key expression: %s" % ast.unparse(node))


MODE_KEY, _MODE_KEY_EXPR = _derive_mode_key()


def _assert_stub_is_faithful():
    """The stub below stands in for SportsCore.__init__; prove it still matches.

    It has to reproduce exactly the two assignments the lookup under test
    depends on. If SportsCore ever changes where config or mode_config come
    from, this fails loudly rather than letting the stub quietly test fiction.
    """
    _, init = _core_init()
    assigns = {}
    for node in ast.walk(init):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if getattr(target, "attr", None) in ("config", "mode_config"):
                    assigns[target.attr] = node.value

    # The stub is only faithful if SportsCore still (a) keeps the handed-in
    # config verbatim as self.config -- if it ever stored a sub-dict, "root"
    # would mean something different -- and (b) derives mode_config as a
    # lookup *within* that same config. The key itself is read from source
    # above, so it needs no assertion; these two shapes do.
    raw = assigns.get("config")
    check("SportsCore still keeps the handed-in config verbatim as self.config",
          isinstance(raw, ast.Name) and raw.id == "config")

    mode = assigns.get("mode_config")
    check("mode_config is still a lookup inside that same config",
          isinstance(mode, ast.Call)
          and isinstance(mode.func, ast.Attribute)
          and mode.func.attr == "get"
          and isinstance(mode.func.value, ast.Name)
          and mode.func.value.id == "config")


class _StubCore:
    """Exactly the two SportsCore assignments the lookup under test reads."""
    # pylint: disable=too-few-public-methods

    def __init__(self, config, display_manager, cache_manager, logger, sport_key):
        self.logger = logger
        self.config = config
        self.mode_config = config.get(MODE_KEY, {}) or {}


# SportsLive may carry abstract methods from SportsCore; fill them in so it can
# be constructed. They are never called here.
_Concrete = type("_ConcreteLive", (sports.SportsLive,),
                 {name: (lambda self, *a, **k: None)
                  for name in getattr(sports.SportsLive,
                                      "__abstractmethods__", ())})


def _live(root=None, league=None):
    """A real SportsLive built from a real config dict.

    root/league place the settings at the config root and in the per-league
    block respectively, which is the whole point: the test can now tell those
    two locations apart.
    """
    config = dict(root or {})
    config[MODE_KEY] = dict(league or {})
    real_init = sports.SportsCore.__init__
    sports.SportsCore.__init__ = _StubCore.__init__
    try:
        return _Concrete(config, object(), object(), _Logger(), SPORT_KEY)
    finally:
        sports.SportsCore.__init__ = real_init


def _Live(base=300, ceiling=900):
    """The old signature, now backed by a real config round-trip."""
    return _live(root={"no_data_interval_seconds": base,
                       "live_idle_max_interval_seconds": ceiling})


def main():
    print("the settings are read from where they are actually written")
    _assert_stub_is_faithful()

    at_root = _live(root={"no_data_interval_seconds": 600,
                          "live_idle_max_interval_seconds": 1200})
    check("a root value is honoured (the schema declares them at the root)",
          at_root.no_data_interval == 600)
    check("...including the ceiling", at_root.live_idle_max_interval == 1200)

    defaults = _live()
    check("absent anywhere falls back to the default",
          defaults.no_data_interval == 300)

    legacy = _live(league={"no_data_interval_seconds": 600})
    check("a hand-placed per-league value still works",
          legacy.no_data_interval == 600)

    both = _live(root={"no_data_interval_seconds": 600},
                 league={"no_data_interval_seconds": 45})
    check("the root wins over a stale per-league value",
          both.no_data_interval == 600)

    junk = _live(root={"no_data_interval_seconds": "soon",
                       "live_idle_max_interval_seconds": float("inf")})
    check("garbage at the root falls back rather than raising",
          junk.no_data_interval == 300)
    check("an infinite ceiling falls back too",
          junk.live_idle_max_interval == sports._DEFAULT_LIVE_IDLE_MAX_SECONDS)

    print("\nthe wait grows the longer nothing is found")
    live = _Live()
    check("first look uses the base interval",
          live._idle_live_interval() == 300)

    for _ in range(sports._IDLE_SHORT_STREAK):
        live._note_live_fetch(False)
    check("after a short streak it is longer (%ds)" % live._idle_live_interval(),
          live._idle_live_interval() > 300)

    short_wait = live._idle_live_interval()
    for _ in range(sports._IDLE_LONG_STREAK):
        live._note_live_fetch(False)
    long_wait = live._idle_live_interval()
    # Against short_wait, not against itself: comparing the value to a second
    # call of the same method with the same state can never fail, so the
    # monotonicity it is meant to protect went untested.
    check("after a long streak it is longer still (%ds vs %ds)"
          % (long_wait, short_wait), long_wait > short_wait)
    check("and never exceeds the ceiling", long_wait <= 900)

    for _ in range(500):
        live._note_live_fetch(False)
    check("a very long streak stays at the ceiling, not beyond",
          live._idle_live_interval() == 900)

    print("\na live game resets it immediately")
    live._note_live_fetch(True)
    check("the streak is cleared", live._empty_live_streak == 0)
    check("and the base interval is back",
          live._idle_live_interval() == 300)

    print("\nthe saving is real, and bounded")
    idle = _Live()
    for _ in range(500):
        idle._note_live_fetch(False)
    per_day = 86400 / idle._idle_live_interval()
    check("an out-of-season league polls far less (%d/day vs 288)" % per_day,
          per_day < 288 / 2)
    check("...but still often enough to notice a season starting (<= 1h)",
          idle._idle_live_interval() <= 3600)

    print("\nthe ceiling is configurable")
    tight = _Live(ceiling=300)
    for _ in range(500):
        tight._note_live_fetch(False)
    check("a lower ceiling is honoured", tight._idle_live_interval() == 300)
    loose = _Live(ceiling=3600)
    for _ in range(500):
        loose._note_live_fetch(False)
    check("a higher ceiling is honoured", loose._idle_live_interval() == 1800)

    print("\nintervals from config are clamped, never trusted raw")
    check("a sane value is used", sports._clamp_seconds(120, 300) == 120)
    check("absent falls back", sports._clamp_seconds(None, 300) == 300)
    check("nonsense falls back", sports._clamp_seconds("soon", 300) == 300)
    check("zero is clamped up", sports._clamp_seconds(0, 300) >= 5)
    check("a week is clamped down", sports._clamp_seconds(604800, 300) <= 86400)

    print("\nthe old recency-based logic is gone")
    src = (plugin_dir / "sports.py").read_text(encoding="utf-8")
    check("has_recently_checked no longer decides the interval",
          "has_recently_checked" not in src)

    tree = ast.parse(src)
    live_cls = next(c for c in ast.walk(tree)
                    if isinstance(c, ast.ClassDef) and c.name == "SportsLive")
    upd = next(m for m in live_cls.body
               if isinstance(m, ast.FunctionDef) and m.name == "update")
    idle_calls = [n for n in ast.walk(upd) if isinstance(n, ast.Call)
                  and getattr(n.func, "attr", None) == "_idle_live_interval"]
    note_calls = [n for n in ast.walk(upd) if isinstance(n, ast.Call)
                  and getattr(n.func, "attr", None) == "_note_live_fetch"]
    check("update() takes its idle interval from the back-off", len(idle_calls) == 1)
    check("update() records each look's outcome", len(note_calls) == 1)

    print("\n%s" % ("FAILED: %d" % len(failures) if failures
                    else "All checks passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
