#!/usr/bin/env python3
"""One league that fails to build must not take the other league down with it.

_initialize_managers used to translate BOTH leagues' configs up front, outside
the per-league try blocks. A config the translation could not handle -- the
classic case was a hand-edited other_games_divisions of null, which list()
turned into a TypeError -- raised past both blocks, so the women's league went
dark because of a typo in the men's settings. Each league now translates and
builds inside its own try, a failed league reads as None, and update() skips it.

The second half pins the other_games_divisions translation itself: it is
passed through raw, so the shared normaliser sees a string as one division
rather than list("fcs") == ['f', 'c', 's'], null as the default, and a
non-iterable as "no filter" instead of a TypeError.

Run: <core-venv>/bin/python plugins/lacrosse-scoreboard/test_league_init_is_isolated.py
Exit 0 pass, 2 skip, anything else fail.
"""

import logging
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

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

import manager as m  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print("  %s  %s%s" % ("PASS" if cond else "FAIL", name,
                          "" if cond else (": " + str(detail))))
    if not cond:
        failures.append(name)


class FakeManager:
    built = []

    def __init__(self, config, display_manager, cache_manager):
        self.config = config
        self.updates = 0
        FakeManager.built.append(self)

    def update(self):
        self.updates += 1


class Boom(Exception):
    pass


def _plugin(config):
    p = m.LacrosseScoreboardPlugin.__new__(m.LacrosseScoreboardPlugin)
    p.logger = logging.getLogger("lax_isolation_probe")
    p.logger.addHandler(logging.NullHandler())
    p.logger.propagate = False
    p.config = config
    p.display_manager = MagicMock()
    p.cache_manager = MagicMock()
    p.plugin_manager = MagicMock()
    p.is_enabled = True
    p.ncaa_mens_enabled = True
    p.ncaa_womens_enabled = True
    p._check_favorite_teams = lambda: None
    return p


def _adapt(p, league):
    """Run the real translation, filling in collaborators it reads on demand."""
    for _ in range(40):
        try:
            return p._adapt_config_for_manager(league)
        except AttributeError as exc:
            name = str(exc).rsplit("'", 2)[-2] if "'" in str(exc) else ""
            if not name or hasattr(p, name):
                raise
            setattr(p, name, MagicMock())
    raise RuntimeError("gave up filling in attributes")


def test_one_league_failure_leaves_the_other_built():
    names = ["NCAAMLacrosseLiveManager", "NCAAMLacrosseRecentManager",
             "NCAAMLacrosseUpcomingManager", "NCAAWLacrosseLiveManager",
             "NCAAWLacrosseRecentManager", "NCAAWLacrosseUpcomingManager"]
    saved = {n: getattr(m, n) for n in names}
    try:
        for n in names:
            setattr(m, n, FakeManager)
        p = _plugin({"ncaa_mens": {"enabled": True}, "ncaa_womens": {"enabled": True}})
        real_adapt = p._adapt_config_for_manager

        def adapt(league):
            if league == "ncaa_mens":
                raise Boom("unusable men's config")
            return {"stub": league}

        p._adapt_config_for_manager = adapt
        p._initialize_managers()
        check("men's managers are None after their translation raised",
              p.ncaa_mens_live is None and p.ncaa_mens_recent is None
              and p.ncaa_mens_upcoming is None)
        check("women's managers were still built",
              all(isinstance(getattr(p, "ncaa_womens_" + k), FakeManager)
                  for k in ("live", "recent", "upcoming")))
        try:
            p.update()
            ok, detail = True, ""
        except Exception as exc:  # pragma: no cover - the failure being guarded
            ok, detail = False, exc
        check("update() tolerates the None league", ok, detail)
        check("update() still refreshed the built league",
              p.ncaa_womens_live.updates == 1, p.ncaa_womens_live.updates)

        # A constructor raising mid-league (live built, recent fails) must not
        # leave a half-built league behind.
        p2 = _plugin({})
        p2._adapt_config_for_manager = lambda league: {}

        class Explodes(FakeManager):
            def __init__(self, *a, **k):
                raise Boom("recent manager failed")

        m.NCAAMLacrosseRecentManager = Explodes
        p2._initialize_managers()
        check("a half-built league is reset to None",
              p2.ncaa_mens_live is None and p2.ncaa_mens_recent is None)
        check("the other league is unaffected by that",
              isinstance(p2.ncaa_womens_recent, FakeManager))
        del real_adapt
    finally:
        for n, v in saved.items():
            setattr(m, n, v)


def test_other_games_divisions_pass_through():
    try:
        from src.common.sports_shared import SportsCoreSharedMixin
    except ImportError:
        print("  (core lacks sports_shared; skipping the normaliser half)")
        return
    normalise = SportsCoreSharedMixin._normalise_divisions
    # null falls back to the translation's default; a non-iterable used to
    # raise TypeError inside list() and leave the league unbuilt.
    for raw, want in (("fcs", ["fcs"]), (None, ["fbs"]), (5, []), (["d1"], ["d1"])):
        p = _plugin({"ncaa_mens": {"enabled": True,
                                   "filtering": {"other_games_divisions": raw}}})
        try:
            adapted = _adapt(p, "ncaa_mens")
        except Exception as exc:
            check("translation survives other_games_divisions=%r" % (raw,), False, exc)
            continue
        block = next((v for v in adapted.values()
                      if isinstance(v, dict) and "other_games_divisions" in v), {})
        got = normalise(block.get("other_games_divisions"))
        check("other_games_divisions=%r reaches the filter as %r" % (raw, want),
              got == want, got)


def test_odds_intervals_and_test_mode_are_forwarded():
    p = _plugin({"ncaa_mens": {"enabled": True, "test_mode": True,
                               "update_intervals": {"odds": 1234, "live_odds": 45}}})
    adapted = _adapt(p, "ncaa_mens")
    block = next((v for v in adapted.values()
                  if isinstance(v, dict) and "odds_update_interval" in v), {})
    check("update_intervals.odds reaches odds_update_interval",
          block.get("odds_update_interval") == 1234, block.get("odds_update_interval"))
    check("update_intervals.live_odds reaches live_odds_update_interval",
          block.get("live_odds_update_interval") == 45,
          block.get("live_odds_update_interval"))
    check("test_mode reaches the manager", block.get("test_mode") is True,
          block.get("test_mode"))


if __name__ == "__main__":
    test_one_league_failure_leaves_the_other_built()
    test_other_games_divisions_pass_through()
    test_odds_intervals_and_test_mode_are_forwarded()
    print("\n%d failure(s)" % len(failures))
    sys.exit(1 if failures else 0)
