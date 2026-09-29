#!/usr/bin/env python3
"""Behaviour of the scoreboard methods every copy agrees on, but nothing ran.

WHY THIS EXISTS
---------------
Some methods are identical in every scoreboard's ``sports.py`` or
``game_renderer.py``, and neither the safety harness nor the card goldens
(test_scroll_card_renders.py) reach them: the odds narrowing, the previous-day
lookback and the direct season fetch only run against a live feed, and most of
the ``sports_card`` delegations only matter with favourites or colours set.
A change to any copy -- including moving it into core -- would go unseen.

This calls each one, in every plugin that has it, with fixed inputs:

* ``SportsCore`` (all nine): ``_background_fetches_espn_ranges``,
  ``_needs_previous_day``, ``_wants_live_odds``, ``_fetch_season_directly``.
* ``GameRenderer`` (the eight with one): the ``sports_card`` delegations,
  each checked against the function it names.

    python scripts/test_sports_shared_methods.py

Exit 0 pass, 2 skip (no core checkout), 1 fail.
"""
from __future__ import annotations

import importlib.util
import logging
import os
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SPORTS = ["afl", "baseball", "basketball", "football", "hockey", "lacrosse",
          "nrl", "soccer", "ufc"]


def core_root():
    env = os.environ.get("LEDMATRIX_CORE")
    if env and (Path(env) / "src").is_dir():
        return Path(env)
    for cand in (REPO.parent / "LEDMatrix", Path.home() / "LEDMatrix"):
        if (cand / "src").is_dir():
            return cand
    return None


def load(plugin, filename):
    """Import one of this plugin's modules under a name of its own.

    Its bare-name siblings are dropped from sys.modules afterwards so the next
    plugin binds its own copies, as the core's loader isolates them.
    """
    pdir = REPO / "plugins" / f"{plugin}-scoreboard"
    name = f"_shared_methods_{plugin}_{Path(filename).stem}"
    before = set(sys.modules)
    sys.path.insert(0, str(pdir))
    try:
        spec = importlib.util.spec_from_file_location(name, pdir / filename)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.path.remove(str(pdir))
        for key in set(sys.modules) - before:
            if key != name and str(pdir) in (getattr(sys.modules[key], "__file__", None) or ""):
                del sys.modules[key]


def bare(cls):
    """An instance of ``cls`` with no __init__ run, abstract or not."""
    concrete = type(f"_Bare{cls.__name__}", (cls,), {})
    concrete.__abstractmethods__ = frozenset()
    obj = object.__new__(concrete)
    obj.logger = logging.getLogger("shared-methods")
    return obj


class _Response:
    status_code = 200
    content = None

    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


class _Session:
    def __init__(self, data=None, error=None):
        self.data, self.error, self.calls = data, error, []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, dict(params or {}), headers, timeout))
        if self.error:
            raise self.error
        return _Response(self.data)


class _Cache:
    def __init__(self):
        self.sets = []

    def set(self, key, data, **kwargs):
        self.sets.append((key, data, kwargs))


def check_sports_core(SportsCore):
    """Yield (what, ok) for the SportsCore methods."""
    core = bare(SportsCore)

    yield "no background service fetches ranges itself", \
        core._background_fetches_espn_ranges() is False
    core.background_service = type("S", (), {"handles_espn_date_ranges": True})()
    yield "a range-aware service fetches them", \
        core._background_fetches_espn_ranges() is True

    et = timezone(timedelta(hours=-5))
    core.live_games = []
    yield "before the cutoff the previous day is kept", \
        core._needs_previous_day(datetime(2026, 1, 15, 5, 59, tzinfo=et)) is True
    yield "after it, with nothing live, it is dropped", \
        core._needs_previous_day(datetime(2026, 1, 15, 6, 0, tzinfo=et)) is False
    core.live_games = [{"start_time_utc": datetime(2026, 1, 15, 3, 0, tzinfo=timezone.utc)}]
    yield "a live game from the previous day keeps it", \
        core._needs_previous_day(datetime(2026, 1, 15, 12, 0, tzinfo=et)) is True

    core._games_lock = threading.RLock()
    core.live_games = []
    yield "cold start asks for odds", core._wants_live_odds({"id": "a"}) is True
    core.live_games = [{"id": i} for i in "abcd"]
    core.current_game_index = 1
    core._rotation_schedule = []
    yield "odds for the game on screen and the next one only", \
        [core._wants_live_odds({"id": i}) for i in "abcd"] == [False, True, True, False]
    core._rotation_schedule = ["d", "c", "b", "a"]
    core.current_game_index = 3
    yield "the rotation schedule wraps", \
        [core._wants_live_odds({"id": i}) for i in "abcd"] == [True, False, False, True]

    core.session = _Session(data={"events": [1, 2]})
    core.headers = {"User-Agent": "x"}
    core.cache_manager = _Cache()
    data = core._fetch_season_directly("http://espn/sb", "20260115", "k", "2026 season")
    yield "a season fetch returns and caches the payload", (
        data == {"events": [1, 2]}
        and core.cache_manager.sets == [("k", data, {})]
        and core.session.calls == [("http://espn/sb", {"dates": "20260115", "limit": 500},
                                    {"User-Agent": "x"}, 30)])
    core.cache_manager = _Cache()
    core._fetch_season_directly("http://espn/sb", "20260115", "k", "2026 season", ttl=60)
    yield "a ttl is passed to the cache", core.cache_manager.sets[0][2] == {"ttl": 60}
    core.session = _Session(error=OSError("down"))
    core.cache_manager = _Cache()
    yield "a failed fetch returns None and caches nothing", (
        core._fetch_season_directly("http://espn/sb", "20260115", "k", "x") is None
        and core.cache_manager.sets == [])


def check_card_wrappers(GameRenderer, card):
    """Yield (what, ok): each delegation returns what its function returns."""
    config = {
        "timezone": "America/Chicago",
        "favorite_teams": ["BOS"],
        "scroll_card": {"vs_text": "@", "upcoming_center": "date_time",
                        "date_format": "weekday", "show_time": False},
        "customization": {
            "score_text": {"text_color": [9, 9, 9]},
            "favorite_result_colors": {"enabled": True, "win_color": [0, 200, 0]},
        },
        "use_24_hour_format": True,
    }
    r = GameRenderer(128, 32, config, logo_cache={})
    log = r.logger
    game = {"home_abbr": "BOS", "away_abbr": "NYY", "home_score": "3",
            "away_score": "1", "home_id": "1", "away_id": "2",
            "start_time_utc": "2026-09-19T23:00:00Z"}
    font = next(iter(r.fonts.values()))
    cases = {
        "_scroll_card_option": (r._scroll_card_option("vs_text", "VS"),
                                card.scroll_card_option(config, "vs_text", "VS")),
        "_vs_text": (r._vs_text(), card.vs_text(config)),
        "_upcoming_center_mode": (r._upcoming_center_mode(), card.upcoming_center_mode(config)),
        "_element_color": (r._element_color("score_text"),
                           card.element_color(config, "score_text", (255, 255, 255))),
        "_font_color": (r._font_color(font), card.font_color(config, r.fonts, font, (255, 255, 255))),
        "_coerce_rgb": (r._coerce_rgb([300, -1, "7"], (1, 2, 3)), (255, 0, 7)),
        "_side_is_favorite": (r._side_is_favorite(game, "home", {"BOS"}), True),
        "_side_score": (r._side_score(game, "home"), 3),
        "_favorite_result": (r._favorite_result(game), "win"),
        "_recent_score_color": (r._recent_score_color(game, (1, 1, 1)), (0, 200, 0)),
        "_score_color_for": ((r._score_color_for(game, "recent"), r._score_color_for(game, "live")),
                             ((0, 200, 0), card.element_color(config, "score_text"))),
        "_card_tzinfo": (str(r._card_tzinfo()), "America/Chicago"),
        "_weekday_for": (r._weekday_for(game), "Sat"),
        "_format_game_date": (r._format_game_date("2026-09-19", game),
                              card.format_game_date(config, log, "2026-09-19", game)),
        "_format_game_time": (r._format_game_time("7:00 PM"), card.format_game_time(config, "7:00 PM")),
        "_crisp_size": (r._crisp_size("PressStart2P-Regular.ttf", 9),
                        card.crisp_size("PressStart2P-Regular.ttf", 9,
                                        r._FONT_NAME_ALIASES, r._FONT_PIXEL_GRID)),
    }
    for name, (got, want) in cases.items():
        yield f"{name} -> {want!r} (got {got!r})", got == want
    fonts = {"a": font, "b": font}
    unshared = r._unshare_element_fonts(dict(fonts))
    yield "_unshare_element_fonts keeps the keys", set(unshared) == set(fonts)


def main() -> int:
    core = core_root()
    if core is None:
        print("  [skip] no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
        return 2
    sys.path.insert(0, str(core))
    logging.disable(logging.CRITICAL)
    os.chdir(core)  # the renderers' font paths are relative to the core

    from src.common import sports_card  # noqa: E402

    checked, problems = 0, []
    for plugin in SPORTS:
        suites = [("sports.py", lambda m: check_sports_core(m.SportsCore))]
        if (REPO / "plugins" / f"{plugin}-scoreboard" / "game_renderer.py").is_file():
            suites.append(("game_renderer.py",
                           lambda m: check_card_wrappers(m.GameRenderer, sports_card)))
        for filename, suite in suites:
            try:
                results = list(suite(load(plugin, filename)))
            except Exception as exc:                  # noqa: BLE001
                problems.append(f"{plugin} {filename}: raised {type(exc).__name__}: {exc}")
                continue
            checked += len(results)
            problems += [f"{plugin} {filename}: {what}" for what, ok in results if not ok]

    for p in problems:
        print(f"  [FAIL] {p}")
    if problems:
        return 1
    print(f"  [pass] {checked} checks across {len(SPORTS)} scoreboards")
    return 0


if __name__ == "__main__":
    sys.exit(main())
