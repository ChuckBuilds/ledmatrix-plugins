#!/usr/bin/env python3
"""Game-activity pop-ups for the live baseball scorebug.

The plays below are shaped like ESPN's real summary for PHI @ ATL on 2026-09-30:
one row per pitch plus a "play-result" row for how each at-bat ended, with runs
flagged ``scoringPlay``. Pins what becomes a pop-up (results, not pitches; never
a run), the wording ladder, the poll/queue rules (a first poll only records
where the feed is; a poll that loses its place re-baselines), and that the
banner fits every panel size and fades.

Run: <core-venv>/bin/python plugins/baseball-scoreboard/test_baseball_activity.py
"""

# pylint: disable=protected-access,unused-argument,import-outside-toplevel

import logging
import os
import sys
import time
from pathlib import Path

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

failures = []


def check(label, ok, detail=None):
    print(("  PASS  " if ok else "  FAIL  ") + label
          + ("" if ok or detail is None else "  -- %r" % (detail,)))
    if not ok:
        failures.append(label)


_n = [0]


def play(text, ptype="play-result", half="Top", inning=1, team="22", scoring=False, **extra):
    _n[0] += 1
    return dict({"id": "p%04d" % _n[0], "text": text, "type": {"type": ptype},
                 "period": {"type": half, "number": inning, "displayValue": "x"},
                 "team": {"id": team}, "scoringPlay": scoring}, **extra)


def main():
    os.chdir(str(CORE))
    from PIL import Image
    import baseball
    import baseball_activity as ba
    import baseball_celebration as bc
    import sports

    # -- what becomes a pop-up -------------------------------------------
    print("what becomes a pop-up")
    act = ba.extract_activity
    check("a pitch row is not one", act(play("Pitch 2 : Ball In Play", ptype="double")) is None)
    check("a ball is not one", act(play("Pitch 1 : Ball 1", ptype="ball")) is None)
    check("an inning marker is not one",
          act(play("Top of the 1st inning", ptype="start-inning")) is None)
    check("a run never is (the celebration owns it)",
          act(play("Harper singled to left, Turner scored.", scoring=True)) is None)
    check("a home run never is",
          act(play("Schwarber homered to right center (447 feet).", scoring=True)) is None)
    a = act(play("Turner doubled to center.", half="Top", inning=1))
    check("a double", a and a["kind"] == "hit" and a["names"][0] == "Turner"
          and a["labels"] == ["DOUBLE!", "2B"] and a["stamps"] == ["Top 1st", "T1"], a)
    a = act(play("Bohm singled to left, Harper to third.", half="Bottom", inning=3))
    check("a single that moved a runner, bottom half",
          a and a["labels"][0] == "SINGLE!" and a["stamps"][0] == "Bot 3rd", a)
    a = act(play("Dubon reached on infield single to shortstop, Albies to second."))
    check("an infield single is a hit", a and a["kind"] == "hit" and a["names"][0] == "Dubon", a)
    a = act(play("Marsh struck out swinging."))
    check("a strikeout", a and a["kind"] == "strikeout" and a["labels"][1] == "K", a)
    a = act(play("Baldwin struck out looking, Acuña Jr. stole second."))
    check("a strikeout that also had a steal is about the batter",
          a and a["kind"] == "strikeout" and a["names"][0] == "Baldwin", a)
    a = act(play("Acuña Jr. stole third.", ptype="stolen-base", half="Bottom"))
    check("a steal keeps the full stop in 'Jr.' and says which base",
          a and a["kind"] == "steal" and a["names"] == ["Acuna Jr."]
          and a["labels"][0] == "STEALS 3RD", a)
    a = act(play("Acuña Jr. walked."))
    check("a walk", a and a["kind"] == "walk" and a["labels"] == ["WALKS", "BB"], a)
    a = act(play("Acuña Jr. intentionally walked."))
    check("an intentional walk", a and a["labels"][1] == "IBB", a)
    a = act(play("McFarlane relieved Sánchez", half="Bottom", inning=7))
    check("a pitching change names the pitcher coming in",
          a and a["kind"] == "pitching_change" and a["names"][0] == "McFarlane", a)
    a = act(play("Harris II grounded into double play, first to catcher to first."))
    check("a double play; a suffix is not a surname",
          a and a["kind"] == "double_play" and a["names"] == ["Harris II"], a)
    a = act(play("Schwarber grounded out to second, Turner to third."))
    check("an out", a and a["kind"] == "out", a)
    a = act(play("Stott grounded into fielder's choice to pitcher, Bohm to second."))
    check("a fielder's choice is an out", a and a["kind"] == "out" and a["labels"][1] == "FC", a)
    a = act(play("Kim hit sacrifice bunt, Murphy to second."))
    check("a sacrifice", a and a["kind"] == "sacrifice", a)
    for text in ("De La Cruz hit for Marsh", "Hill ran for Sosa", "Harper at first base.",
                 "Hill in right field."):
        check("lineup bookkeeping is not one: %r" % text, act(play(text)) is None)
    check("two-word and long names: a surname fallback",
          act(play("Ke'Bryan Hayes singled to left."))["names"] == ["Ke'Bryan Hayes", "Hayes"])
    check("accents are folded: the small face has no n-tilde",
          act(play("Sánchez singled."))["names"][0] == "Sanchez")
    check("not a play at all", act({}) is None and act(None) is None)

    # -- stamps ---------------------------------------------------------------
    print("\ninnings")
    check("ordinals", [ba.inning_stamps(play("x", half="Top", inning=n))[0]
                       for n in (1, 2, 3, 4, 11, 12, 13, 21)]
          == ["Top 1st", "Top 2nd", "Top 3rd", "Top 4th", "Top 11th", "Top 12th",
              "Top 13th", "Top 21st"])
    check("11th, 12th and 13th are not 11st", ba.inning_stamps(
        play("x", half="Top", inning=11))[0] == "Top 11th")
    check("no inning, no stamp", ba.inning_stamps({}) == [])

    # -- detail levels ------------------------------------------------------------
    print("\ndetail levels")
    check("default is highlights", ba.wanted_kinds(None) == ba.DETAIL_KINDS["highlights"]
          and ba.wanted_kinds("bogus") == ba.DETAIL_KINDS["highlights"])
    check("hits_and_steals is the smallest", ba.wanted_kinds("hits_and_steals")
          == {"hit", "steal"})
    check("everything adds outs and sacrifices",
          {"out", "sacrifice"} <= ba.wanted_kinds("everything")
          and "out" not in ba.wanted_kinds("highlights"))

    # -- the host ------------------------------------------------------------------
    class Frame:
        def __init__(self, w, h):
            self.image = Image.new("RGB", (w, h))
            self.matrix = None

        def clear(self):
            pass

        def update_display(self):
            pass

    class Live(ba.BaseballActivityMixin, bc.BaseballCelebrationMixin, baseball.Baseball):
        def __init__(self, width=128, height=32, **cfg):
            self.config = {}
            self.mode_config = dict({"show_game_activity": True}, **cfg)
            self.display_width, self.display_height = width, height
            self.logger = logging.getLogger("activity-test")
            self._font_cache = {}
            self.fonts = sports.SportsCore._load_fonts(self)
            self.display_manager = Frame(width, height)
            self.live_games = []
            self.current_game = None
            self.update_interval = 30
            self.espn_summary_sport_league = ("baseball", "mlb")
            self.summary = {"plays": []}
            self._init_celebration()
            self._init_game_activity()

        def _fetch_data(self):  # pragma: no cover
            raise NotImplementedError

        def _fetch_summary(self, game_id, timeout=None):
            return self.summary

    game = {"id": "g1", "away_id": "22", "home_id": "15", "away_abbr": "PHI",
            "home_abbr": "ATL", "away_team_color": (200, 30, 40)}

    # -- the queue -------------------------------------------------------------------
    print("\nthe queue")
    live = Live()
    base = [play("Marsh struck out swinging."), play("Turner doubled to center.")]
    live._queue_game_activity(game, base)
    check("the first poll only records where the feed is", len(live._activity_queue) == 0
          and live._activity_seen["g1"] == base[-1]["id"])
    new = [play("Harper singled to left."), play("Pitch 1 : Ball 1", ptype="ball"),
           play("Bohm walked.")]
    live._queue_game_activity(game, base + new)
    q = list(live._activity_queue)
    check("the next poll queues the new results, not the pitches",
          [x["kind"] for x in q] == ["hit", "walk"], [x["kind"] for x in q])
    check("each carries its game and the acting team",
          q[0]["game_id"] == "g1" and q[0]["team_abbr"] == "PHI"
          and tuple(q[0]["team_color"]) == (200, 30, 40), q[0])

    live = Live(game_activity_detail="hits_and_steals")
    live._queue_game_activity(game, base)
    live._queue_game_activity(game, base + [play("Marsh struck out swinging."),
                                            play("Harper singled to left.")])
    check("the detail level filters", [x["kind"] for x in live._activity_queue] == ["hit"])

    live = Live()
    live._queue_game_activity(game, base)
    live._queue_game_activity(game, [play("Harper singled to left.")])
    check("a poll that cannot find its place re-baselines instead of replaying",
          len(live._activity_queue) == 0)

    live = Live()
    live._queue_game_activity(game, base)
    burst = [play("%s singled." % n) for n in ("Aa", "Bb", "Cc", "Dd", "Ee")]
    live._queue_game_activity(game, base + burst)
    check("a burst keeps the newest three",
          [x["names"][0] for x in live._activity_queue] == ["Cc", "Dd", "Ee"])

    live = Live()
    live._queue_game_activity(game, base)
    same = play("Acuña Jr. stole third.", ptype="stolen-base")
    again = dict(play("Acuña Jr. stole third."), period=dict(same["period"]))
    live._queue_game_activity(game, base + [same, again])
    check("the same sentence on two rows pops up once", len(live._activity_queue) == 1)

    # -- the popup -----------------------------------------------------------------
    print("\nthe pop-up")
    live = Live()
    live._activity_queue.extend([
        {"game_id": "other", "kind": "hit", "names": ["X"], "labels": ["SINGLE!", "1B"],
         "stamps": [], "team_abbr": "", "team_color": None},
        {"game_id": "g1", "kind": "hit", "names": ["Harper"], "labels": ["SINGLE!", "1B"],
         "stamps": ["Top 8th", "T8"], "team_abbr": "PHI", "team_color": None}])
    popup = live._current_activity_popup(game, 6.0)
    check("a pop-up for a game the rotation left is dropped, not shown late",
          popup and popup["game_id"] == "g1")
    check("it holds for its dwell", live._current_activity_popup(game, 6.0) is popup)
    popup["shown_at"] -= 7
    check("and is gone after it", live._current_activity_popup(game, 6.0) is None)

    # -- polling -------------------------------------------------------------------
    print("\npolling")
    live = Live()
    live.current_game = game
    live._poll_game_activity()
    check("not drawn recently: no poll, state cleared", live._activity_inflight is False
          and live._activity_last_poll == 0.0)
    live._activity_drawn_at = time.time()
    live.summary = {"plays": base}
    live._poll_game_activity()
    for _ in range(100):
        if not live._activity_inflight:
            break
        time.sleep(0.02)
    check("drawn recently: it polls and records the baseline",
          live._activity_seen.get("g1") == base[-1]["id"])
    stamp = live._activity_last_poll
    live._poll_game_activity()
    check("and not again inside the interval", live._activity_last_poll == stamp)
    live._activity_inflight = True
    live._activity_last_poll = 0
    live._poll_game_activity()
    check("never two at once", live._activity_last_poll == 0)

    # -- drawing ---------------------------------------------------------------------
    print("\ndrawing")
    popup_fields = {"game_id": "g1", "kind": "hit", "names": ["Acuña Jr.", "Jr."],
                    "labels": ["INTENTIONAL WALK", "IBB"], "stamps": ["Bot 11th", "B11"],
                    "team_abbr": "ATL", "team_color": (206, 17, 65)}
    for width, height in [(64, 32), (96, 32), (128, 32), (192, 32), (256, 32), (128, 64),
                          (256, 64)]:
        live = Live(width, height)
        live._activity_queue.append(dict(popup_fields))
        scorebug = Image.new("RGB", (width, height), (10, 10, 30))
        out = live._with_activity_popup(scorebug, game)
        label = "%dx%d" % (width, height)
        check(label + ": same size", out.size == (width, height))
        top = height - max(9, height // 6)
        rows = [y for y in range(height) for x in range(width)
                if out.getpixel((x, y)) != scorebug.getpixel((x, y))]
        check(label + ": only the bottom rows change",
              rows and min(rows) >= top - 1, (min(rows), top) if rows else None)
        cols = [x for y in range(height) for x in range(width)
                if out.getpixel((x, y)) not in ((0, 0, 0), (10, 10, 30))]
        check(label + ": text stays inside the width", cols and min(cols) >= 0
              and max(cols) < width)

    live = Live(128, 24)
    live._activity_queue.append(dict(popup_fields))
    scorebug = Image.new("RGB", (128, 24), (10, 10, 30))
    check("a panel under 32px tall is left alone",
          live._with_activity_popup(scorebug, game).tobytes() == scorebug.tobytes())
    live = Live(show_game_activity=False)
    live._activity_queue.append(dict(popup_fields))
    scorebug = Image.new("RGB", (128, 32), (10, 10, 30))
    check("switched off, nothing is drawn",
          live._with_activity_popup(scorebug, game).tobytes() == scorebug.tobytes())

    live = Live(128, 32)
    live._activity_queue.append(dict(popup_fields))
    scorebug = Image.new("RGB", (128, 32), (10, 10, 30))
    full = live._with_activity_popup(scorebug, game)
    brightest = lambda im: max(max(im.getpixel((x, y))) for y in range(26, 32)  # noqa: E731
                               for x in range(128))
    live._activity_popup["shown_at"] -= 5.0          # 1s left of a 6s dwell, 3s fade
    dim = live._with_activity_popup(scorebug, game)
    check("it fades: a banner near the end of its dwell is dimmer",
          brightest(dim) < brightest(full), (brightest(full), brightest(dim)))
    live._activity_popup["shown_at"] -= 5.0
    gone = live._with_activity_popup(scorebug, game)
    check("and the scorebug's own bottom row returns once it has gone",
          gone.tobytes() == scorebug.tobytes())

    live = Live(128, 32)
    live._activity_queue.append(dict(popup_fields))
    first = live._with_activity_popup(scorebug, game)
    second = live._with_activity_popup(scorebug, game)
    check("steady between frames while it holds", first.tobytes() == second.tobytes())

    # -- real ESPN rows ---------------------------------------------------------------
    print("\nreal feed")
    fixture = Path(os.environ.get("TMP", "")) / "sum.json"
    if fixture.exists():
        import json
        plays = json.load(open(fixture, encoding="utf-8"))["plays"]
        kinds = {}
        for p in plays:
            a = act(p)
            if a:
                kinds[a["kind"]] = kinds.get(a["kind"], 0) + 1
        check("a real game yields every kind of highlight", {"hit", "strikeout", "walk", "steal",
              "pitching_change", "double_play", "out"} <= set(kinds), kinds)
        check("none of its 7 runs came through", not any(
            act(p) for p in plays if p.get("scoringPlay")))
    else:
        print("  (no downloaded ESPN summary at $TMP/sum.json; skipping the live-feed check)")

    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
