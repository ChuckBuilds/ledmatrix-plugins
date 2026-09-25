#!/usr/bin/env python3
"""Game-activity pop-ups: a banner on the live scorebug for shots and penalties.

A 0-0 game shows nothing happening on the scorebug. With
nhl.display_options.show_game_activity on, the plays between goals pop up
along its bottom row -- "A. Matthews SHOT ON GOAL!  2nd 12:34" -- hold, and
fade out. The plays come from the ESPN per-game summary, polled for the game
on screen at the live update interval.

Covers:
  1. _activity_kind / _extract_activity: ESPN play types to pop-up kinds,
     goals and uncovered plays skipped, both name spellings offered.
  2. _queue_game_activity: the first poll is only a baseline, later polls
     queue only new plays of the wanted kinds, a rewritten feed re-baselines,
     a burst keeps the newest, and each pop-up carries its team's colour.
  3. update(): opt-in, NHL only, one poll per live interval, never two in
     flight, and only while the scorebug is being drawn where a pop-up can
     show -- pausing forgets the baselines, so coming back does not replay.
  4. Render through the real plugin: the setting reaches the live manager;
     with it off, or below 64 rows, not a pixel changes; above, only the
     bottom rows change, the text stays inside the panel, dims through the
     fade and is gone after the dwell, and another game's pop-up is dropped.
  5. The schema's defaults are the ones the code falls back to.

Run: <core-venv>/bin/python plugins/hockey-scoreboard/test_game_activity_popups.py
"""

import json
import logging
import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

REPO = Path(__file__).resolve().parents[2]
CORE = None
for _c in (os.environ.get("LEDMATRIX_CORE", ""),
           str(REPO.parent / "LEDMatrix"),
           str(Path.home() / "projects" / "LEDMatrix")):
    if _c and (Path(_c) / "assets" / "fonts").is_dir():
        CORE = Path(_c)
        break
if CORE is None:
    print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
    sys.exit(2)
sys.path.insert(0, str(CORE))
logging.disable(logging.CRITICAL)

results = []


def check(name, passed, detail=None):
    results.append((name, passed))
    print("  [%s] %s%s" % ("pass" if passed else "FAIL", name,
                           "" if passed or detail is None else " -- %r" % (detail,)))


# Shaped like ESPN NHL summary plays. Home is BOS (1), away is TOR (21).
def _play(play_id, type_text, name="Auston Matthews", short="A. Matthews",
          team="21", scoring=False, period="2nd", clock="12:34"):
    return {
        "id": play_id,
        "type": {"text": type_text, "abbreviation": type_text.lower().replace(" ", "-")},
        "scoringPlay": scoring,
        "team": {"id": team},
        "period": {"number": 2, "displayValue": period},
        "clock": {"displayValue": clock},
        "participants": [{"athlete": {"id": "9", "displayName": name,
                                      "shortName": short}}],
    }


GAME = {
    "id": "9", "home_id": "1", "away_id": "21", "home_abbr": "BOS",
    "away_abbr": "TOR", "home_logo_path": Path("BOS.png"),
    "away_logo_path": Path("TOR.png"), "home_score": "0", "away_score": "0",
    "period_text": "P2", "clock": "12:34", "home_shots": 11, "away_shots": 14,
    "power_play": False, "is_live": True,
    "home_team_color": (252, 181, 20), "away_team_color": (0, 88, 180),
}
TOR_BLUE = GAME["away_team_color"]

TALL = [(64, 64), (128, 64), (256, 64), (128, 96), (128, 128), (256, 128)]
SHORT = [(64, 32), (128, 32), (256, 32), (96, 48), (128, 48)]


class _Clock:
    """Pin time.time() so the fade is checked at exact points, not at
    whatever a slow runner happens to reach."""

    def __init__(self, now):
        self.now = now

    def __enter__(self):
        self._real = time.time
        time.time = lambda: self.now
        return self

    def __exit__(self, *exc):
        time.time = self._real


def main():
    os.chdir(str(CORE))
    from PIL import Image
    import hockey
    from hockey import (DEFAULT_ACTIVITY_KINDS, HockeyLive, _ACTIVITY_LABELS,
                        _activity_kind, _extract_activity)
    from manager import HockeyScoreboardPlugin

    logo = Image.new("RGBA", (16, 16), (0, 0, 200, 255))

    def live(w=128, h=64, display_options=None, customization=None):
        dm = MagicMock()
        dm.matrix = None
        dm.width, dm.height = w, h
        dm.image = Image.new("RGB", (w, h))
        opts = {"show_shots_on_goal": True, "show_game_activity": True}
        opts.update(display_options or {})
        cfg = {"enabled": True, "timezone": "UTC",
               "customization": {"game_activity": customization or {}},
               "nhl": {"enabled": True, "display_modes": {"live": True},
                       "display_options": opts},
               "ncaa_mens": {"enabled": False}, "ncaa_womens": {"enabled": False}}
        mgr = HockeyScoreboardPlugin("hockey-scoreboard", cfg, dm,
                                     MagicMock(), MagicMock()).nhl_live
        mgr._load_and_resize_logo = lambda *a, **k: logo
        return mgr, dm

    def render(mgr, dm, popup=None, at=1000.0, shown_at=1000.0, game=GAME):
        mgr._activity_queue.clear()
        mgr._activity_popup = None
        if popup is not None:
            mgr._activity_popup = dict(popup, shown_at=shown_at)
        with _Clock(at):
            mgr._draw_scorebug_layout(dict(game))
        return dm.image.copy()

    shot = dict(_extract_activity(_play("p2", "Shot")), game_id="9",
                team_abbr="TOR", team_color=TOR_BLUE)

    # --- 1. play parsing -----------------------------------------------------
    print("play parsing")
    kinds = {t: _activity_kind({"text": t}) for t in (
        "Shot", "Shot on Goal", "Blocked Shot", "Missed Shot", "Penalty",
        "Hit", "Faceoff", "Takeaway")}
    check("type text maps to the right kind", kinds == {
        "Shot": "shots", "Shot on Goal": "shots", "Blocked Shot": "blocked_shots",
        "Missed Shot": "missed_shots", "Penalty": "penalties", "Hit": "hits",
        "Faceoff": None, "Takeaway": None}, kinds)
    check("the abbreviation alone is enough",
          _activity_kind({"abbreviation": "blocked-shot"}) == "blocked_shots")
    check("no type, no kind", _activity_kind(None) is None and _activity_kind({}) is None)
    check("a goal is left to the celebration and the goal card",
          _extract_activity(_play("g", "Goal", scoring=True)) is None
          and _extract_activity(_play("g", "Shot", scoring=True)) is None)
    check("an uncovered play is skipped", _extract_activity(_play("f", "Faceoff")) is None)
    parsed = _extract_activity(_play("p1", "Shot"))
    check("a shot carries who, which team and when", parsed == {
        "play_id": "p1", "kind": "shots", "names": ["A. Matthews", "Matthews"],
        "team_id": "21", "period": "2nd", "clock": "12:34"}, parsed)
    check("a nameless play still parses, for the team to stand in",
          _extract_activity(dict(_play("p", "Penalty"), participants=[]))["names"] == [])
    check("every kind has a label", set(_ACTIVITY_LABELS) == {
        k for k, _ in hockey._ACTIVITY_KIND_WORDS})

    # --- 2. queueing -----------------------------------------------------------
    print("\nqueueing")
    mgr, _ = live()
    old = [_play("p1", "Shot"), _play("p2", "Penalty", team="1")]
    mgr._queue_game_activity(GAME, old)
    check("the first poll of a game only sets a baseline",
          len(mgr._activity_queue) == 0 and mgr._activity_seen.get("9") == "p2")
    new = old + [_play("p3", "Shot"), _play("p4", "Hit"),
                 _play("p5", "Goal", scoring=True), _play("p6", "Penalty", team="1")]
    mgr._queue_game_activity(GAME, new)
    queued = list(mgr._activity_queue)
    check("only new plays of the default kinds are queued",
          [a["play_id"] for a in queued] == ["p3", "p6"], [a["play_id"] for a in queued])
    check("each pop-up carries its team's abbreviation and colour",
          (queued[0]["team_abbr"], queued[0]["team_color"]) == ("TOR", TOR_BLUE)
          and (queued[1]["team_abbr"], queued[1]["team_color"]) == ("BOS", GAME["home_team_color"]))
    mgr._queue_game_activity(GAME, new)
    check("an unchanged feed queues nothing more", len(mgr._activity_queue) == 2)

    mgr, _ = live()
    mgr._queue_game_activity(GAME, old)
    mgr._queue_game_activity(GAME, [_play("x1", "Shot"), _play("x2", "Shot")])
    check("a rewritten feed re-baselines instead of replaying",
          len(mgr._activity_queue) == 0 and mgr._activity_seen["9"] == "x2")

    mgr, _ = live()
    mgr._queue_game_activity(GAME, old)
    burst = old + [_play("b%d" % i, "Shot") for i in range(6)]
    mgr._queue_game_activity(GAME, burst)
    check("a burst keeps the newest three",
          [a["play_id"] for a in mgr._activity_queue] == ["b3", "b4", "b5"])

    mgr, _ = live(customization={"event_types": ["hits"]})
    mgr._queue_game_activity(GAME, old)
    mgr._queue_game_activity(GAME, old + [_play("h1", "Hit"), _play("s1", "Shot")])
    check("event_types picks the kinds",
          [a["play_id"] for a in mgr._activity_queue] == ["h1"])

    mgr, _ = live(customization={"event_types": "hits"})
    mgr._queue_game_activity(GAME, old)
    mgr._queue_game_activity(GAME, old + [_play("h1", "Hit"), _play("s1", "Shot")])
    check("a hand-edited single string is one kind, not its letters",
          [a["play_id"] for a in mgr._activity_queue] == ["h1"])

    mgr, dm = live(128, 64)
    with _Clock(1234.0):
        render(mgr, dm, at=1234.0)
    check("drawing the scorebug records that pop-ups can show",
          mgr._activity_drawn_at == 1234.0)
    mgr, dm = live(128, 32)
    render(mgr, dm, at=1234.0)
    check("...but not on a panel too short for them", mgr._activity_drawn_at == 0.0)

    # --- 3. polling -------------------------------------------------------------
    print("\npolling")
    mgr, _ = live()
    check("the setting reaches the live manager", mgr.show_game_activity is True)
    off, _ = live(display_options={"show_game_activity": False})
    check("off unless asked for", off.show_game_activity is False)
    unset_mgr = HockeyScoreboardPlugin(
        "hockey-scoreboard",
        {"enabled": True, "timezone": "UTC", "nhl": {"enabled": True},
         "ncaa_mens": {"enabled": False}, "ncaa_womens": {"enabled": False}},
        MagicMock(width=128, height=64, matrix=None), MagicMock(), MagicMock()).nhl_live
    check("defaults to off when unset", unset_mgr.show_game_activity is False)

    def run_update(m):
        real = hockey.SportsLive.update
        hockey.SportsLive.update = lambda self: None
        try:
            HockeyLive.update(m)
        finally:
            hockey.SportsLive.update = real

    def polling_live(**kw):
        m, _ = live(**kw)
        m.test_mode = False
        m.current_game = dict(GAME)
        m.live_games = [dict(GAME)]
        m.update_interval = 30
        m._activity_drawn_at = 1000.0  # the scorebug is on screen
        fetched = []

        def fetch(game):  # the real one clears the flag in its finally
            fetched.append(game["id"])
            m._activity_inflight = False

        m._fetch_game_activity = fetch
        return m, fetched

    class _SyncThread:
        def __init__(self, target=None, args=(), daemon=None, **_):
            self._run = lambda: target(*args)

        def start(self):
            self._run()

    import threading
    real_thread = threading.Thread
    threading.Thread = _SyncThread
    try:
        m, fetched = polling_live()
        with _Clock(1000.0):
            run_update(m)
        check("a poll is made for the game on screen", fetched == ["9"], fetched)
        with _Clock(1010.0):
            run_update(m)
        check("no second poll inside the live interval", fetched == ["9"], fetched)
        with _Clock(1031.0):
            run_update(m)
        check("the next poll comes after it", fetched == ["9", "9"], fetched)

        m, fetched = polling_live()
        m._activity_inflight = True
        with _Clock(1000.0):
            run_update(m)
        check("never two polls in flight", fetched == [])

        m, fetched = polling_live(display_options={"show_game_activity": False})
        with _Clock(1000.0):
            run_update(m)
        check("no poll with the setting off", fetched == [])

        m, fetched = polling_live()
        m.espn_summary_sport_league = None
        with _Clock(1000.0):
            run_update(m)
        check("no poll for a league with no play data", fetched == [])

        m, fetched = polling_live()
        m.current_game = None
        with _Clock(1000.0):
            run_update(m)
        check("no poll with no game on screen", fetched == [])

        m, fetched = polling_live()
        m._activity_seen = {"9": "p1", "ended": "p7"}
        with _Clock(1000.0):
            run_update(m)
        check("baselines of games no longer live are pruned",
              set(m._activity_seen) == {"9"}, m._activity_seen)

        m, fetched = polling_live()
        m._activity_drawn_at = 0.0
        with _Clock(1000.0):
            run_update(m)
        check("no poll before the scorebug has been drawn", fetched == [])
        m._activity_seen = {"9": "p1"}
        m._activity_queue.append(dict(shot))
        m._activity_drawn_at = 900.0
        with _Clock(1000.0):
            run_update(m)
        check("off screen for a while: no poll, and baselines and queue forgotten",
              fetched == [] and m._activity_seen == {} and len(m._activity_queue) == 0)
        m._activity_drawn_at = 1000.0
        with _Clock(1000.0):
            run_update(m)
        check("back on screen: polling resumes", fetched == ["9"], fetched)

        def cannot_start(*a, **k):
            raise RuntimeError("can't start new thread")

        m, fetched = polling_live()
        threading.Thread = cannot_start
        with _Clock(1000.0):
            run_update(m)
        threading.Thread = _SyncThread
        check("a thread that cannot start leaves no stuck flag",
              fetched == [] and m._activity_inflight is False)

        # The real fetch, end to end through the queue, with ESPN stubbed.
        m, _ = live()
        m.test_mode = False
        m.current_game = dict(GAME)
        m.live_games = [dict(GAME)]
        feeds = iter([{"plays": old}, {"plays": old + [_play("p3", "Shot")]}])
        m.data_source = MagicMock()
        m.data_source.fetch_game_summary = lambda *a: next(feeds)
        m._activity_drawn_at = 1000.0
        with _Clock(1000.0):
            run_update(m)
        m._activity_drawn_at = 1100.0
        with _Clock(1100.0):
            run_update(m)
        check("the fetch feeds the queue and clears the in-flight flag",
              [a["play_id"] for a in m._activity_queue] == ["p3"]
              and m._activity_inflight is False)
    finally:
        threading.Thread = real_thread

    # --- 4. render ----------------------------------------------------------------
    print("\nrender")
    for (w, h) in SHORT:
        mgr, dm = live(w, h)
        plain = render(mgr, dm)
        with_popup = render(mgr, dm, shot)
        check("%dx%d: no row to spare, nothing drawn" % (w, h),
              plain.tobytes() == with_popup.tobytes())

    for (w, h) in TALL:
        mgr, dm = live(w, h)
        plain = render(mgr, dm)
        full = render(mgr, dm, shot, at=1000.0)
        diff = [(x, y) for y in range(h) for x in range(w)
                if plain.getpixel((x, y)) != full.getpixel((x, y))]
        top = min((y for _, y in diff), default=h)
        check("%dx%d: the banner draws" % (w, h), bool(diff))
        check("%dx%d: only the bottom rows change" % (w, h),
              top >= h - max(9, h // 6), top)
        edges = [full.getpixel((x, y)) for y in range(top, h) for x in (0, w - 1)]
        check("%dx%d: nothing drawn into the edge columns" % (w, h),
              all(p == (0, 0, 0) for p in edges))
        colors = {c for _, c in full.getcolors(w * h)}
        check("%dx%d: the label is in the team colour" % (w, h), TOR_BLUE in colors)

        # dwell 6, fade 3: full strength until 3s, half at 4.5s, gone at 6s.
        held = render(mgr, dm, shot, at=1002.9)
        half = render(mgr, dm, shot, at=1004.5)
        gone = render(mgr, dm, shot, at=1006.0)
        half_colors = {c for _, c in half.getcolors(w * h)}
        check("%dx%d: holds at full strength before the fade" % (w, h),
              held.tobytes() == full.tobytes())
        check("%dx%d: dims through the fade" % (w, h),
              TOR_BLUE not in half_colors
              and tuple(round(c * 0.5) for c in TOR_BLUE) in half_colors)
        check("%dx%d: gone after the dwell" % (w, h),
              gone.tobytes() == plain.tobytes() and mgr._activity_popup is None)

    mgr, dm = live(128, 64, display_options={"show_game_activity": False})
    plain = render(mgr, dm)
    check("setting off: not a pixel changes",
          render(mgr, dm, shot).tobytes() == plain.tobytes())

    mgr, dm = live(128, 64)
    plain = render(mgr, dm)
    mgr._activity_queue.extend([dict(shot, game_id="other"), dict(shot, play_id="q2")])
    with _Clock(1000.0):
        mgr._draw_scorebug_layout(dict(GAME))
    check("another game's pop-up is dropped, this game's shown",
          mgr._activity_popup is not None and mgr._activity_popup["play_id"] == "q2"
          and len(mgr._activity_queue) == 0)
    mgr._activity_queue.append(dict(shot, play_id="q3"))
    with _Clock(1003.0):
        mgr._draw_scorebug_layout(dict(GAME))
    check("the next waits for the current one's dwell",
          mgr._activity_popup["play_id"] == "q2" and len(mgr._activity_queue) == 1)
    with _Clock(1006.0):
        mgr._draw_scorebug_layout(dict(GAME))
    check("then takes its turn", mgr._activity_popup["play_id"] == "q3")

    mgr, dm = live(128, 64, customization={"use_team_colors": False})
    colors = {c for _, c in render(mgr, dm, shot).getcolors(128 * 64)}
    check("use_team_colors off: the accent colour instead",
          (255, 200, 0) in colors and TOR_BLUE not in colors)

    mgr, dm = live(64, 64)
    nameless = dict(shot, names=[], team_abbr="TOR")
    check("a nameless pop-up still draws, under the team",
          render(mgr, dm, nameless).tobytes() != render(mgr, dm).tobytes())

    mgr, dm = live(128, 64)
    mgr._layout_activity_banner = MagicMock(side_effect=RuntimeError("boom"))
    plain_mgr, plain_dm = live(128, 64)
    check("a failing pop-up leaves the scorebug whole",
          render(mgr, dm, shot).tobytes() == render(plain_mgr, plain_dm).tobytes())

    # --- 5. schema -------------------------------------------------------------
    print("\nschema")
    schema = json.loads((plugin_dir / "config_schema.json").read_text())
    block = schema["properties"]["customization"]["properties"]["game_activity"]["properties"]
    check("event_types offers every kind",
          set(block["event_types"]["items"]["enum"]) == set(_ACTIVITY_LABELS))
    check("event_types default matches the code",
          tuple(block["event_types"]["default"]) == DEFAULT_ACTIVITY_KINDS)
    code_defaults = {"dwell_seconds": 6, "fade_seconds": 3, "use_team_colors": True,
                     "accent_color": [255, 200, 0], "text_color": [255, 255, 255],
                     "time_color": [170, 170, 170]}
    check("the other defaults match the code",
          {k: block[k]["default"] for k in code_defaults} == code_defaults)
    nhl_opts = schema["properties"]["nhl"]["properties"]["display_options"]["properties"]
    check("show_game_activity defaults off",
          nhl_opts["show_game_activity"]["default"] is False)

    failed = [n for n, ok in results if not ok]
    print("\n%d passed, %d failed" % (len(results) - len(failed), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
