#!/usr/bin/env python3
"""The scorer card: who just drove the run in.

Pins how a card is armed (a score going up on a live game, on its own baseline,
independent of the celebration), how the scoring play is read (the newest scoring
play that agrees with the scoreboard -- never a previous run's), what the card
says, when it appears (after the celebration, or straight away without one),
and that it fits every panel size.

Run: <core-venv>/bin/python plugins/baseball-scoreboard/test_baseball_scorer_card.py
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


def game(away=0, home=0, gid="g1", **extra):
    return dict({"id": gid, "away_abbr": "PHI", "home_abbr": "ATL",
                 "away_id": "22", "home_id": "15", "status_text": "Top 5th",
                 "away_logo_path": None, "home_logo_path": None,
                 "away_score": str(away), "home_score": str(home)}, **extra)


HOMER = {"type": {"type": "home-run"}, "scoringPlay": True, "awayScore": 3,
         "homeScore": 2, "text": "Bryce Harper homered to left (402 feet).",
         "participants": [{"type": "batter", "athlete": {"id": "111"}},
                          {"type": "pitcher", "athlete": {"id": "222"}}]}
EARLIER = {"type": {"type": "single"}, "scoringPlay": True, "awayScore": 2,
           "homeScore": 2, "text": "Turner singled, Schwarber scored.",
           "participants": [{"type": "batter", "athlete": {"id": "333"}}]}
ROSTERS = [{"team": {"id": "22", "abbreviation": "PHI"},
            "roster": [{"athlete": {"id": "111", "shortName": "B. Harper",
                                    "jersey": "3", "position": {"abbreviation": "DH"}}}]}]
BIO = {"display_name": "Bryce Harper", "jersey": "3", "position": "1B",
       "stat_pairs": [("AVG", ".285"), ("HR", "30"), ("RBI", "98")]}


def main():
    os.chdir(str(CORE))
    from PIL import Image
    import baseball
    import baseball_celebration as bc
    import baseball_scorer_card as sc
    import sports

    class Frame:
        def __init__(self, w, h):
            self.image = Image.new("RGB", (w, h))
            self.matrix = None
            self.updates = 0

        def clear(self):
            pass

        def update_display(self):
            self.updates += 1

    class Live(sc.BaseballScorerCardMixin, bc.BaseballCelebrationMixin, baseball.Baseball):
        def __init__(self, width=128, height=32, **cfg):
            self.config = {}
            self.mode_config = dict({"show_scorer_card": True}, **cfg)
            self.favorite_teams = ["PHI"]
            self.display_width, self.display_height = width, height
            self.logger = logging.getLogger("scorer-test")
            self._font_cache = {}
            self.fonts = sports.SportsCore._load_fonts(self)
            self.display_manager = Frame(width, height)
            self.live_games = []
            self.espn_summary_sport_league = ("baseball", "mlb")
            self._player_bio_cache = {}
            self._play_by_play_cache = {}
            self.resolved = []
            self.bio_fetches = []
            self._init_celebration()
            self._init_scorer_card()

        _format_card_stats = staticmethod(baseball.BaseballLive._format_card_stats)
        _player_card_team_color = baseball.BaseballLive._player_card_team_color

        def _fetch_data(self):  # pragma: no cover
            raise NotImplementedError

        def _fetch_player_bio(self, player_id):
            self.bio_fetches.append(player_id)
            self._player_bio_cache[player_id] = BIO

        def _prefetch_headshot(self, player_id, url):
            pass

        def _get_headshot_manager(self):
            return None

        def _resolve_scorer(self, g, side, runs):      # the thread part, stubbed
            self.resolved.append((g["id"], side, runs))

        def _load_and_resize_logo(self, i, abbr, path, url=None):
            return Image.new("RGBA", (self.display_height, self.display_height),
                             (180, 30, 40, 255))

    # -- reading the play --------------------------------------------------
    print("the scoring play")
    check("the batter's id", sc.batter_id_of(HOMER) == "111")
    check("a play with no batter has none", sc.batter_id_of({"participants": []}) is None)
    check("the newest scoring play",
          bc.latest_scoring_play([EARLIER, HOMER]) is HOMER)
    check("it agrees with the scoreboard",
          bc.latest_scoring_play([EARLIER, HOMER], (3, 2)) is HOMER)
    check("a summary one poll behind is unknown, not the previous run",
          bc.latest_scoring_play([EARLIER], (3, 2)) is None)
    check("...and so is a stale home run for a celebration's verdict",
          bc.home_run_in_plays([HOMER], (4, 2)) is None)
    check("no score to compare: the newest one", bc.latest_scoring_play([EARLIER]) is EARLIER)
    check("banner wording", [sc.card_label("homerun", 1), sc.card_label("homerun", 2),
                             sc.card_label("homerun", 4), sc.card_label("run", 1)]
          == ["HOME RUN", "2-RUN HOMER", "GRAND SLAM", "RUN SCORES"],
          [sc.card_label("homerun", 1), sc.card_label("homerun", 2),
           sc.card_label("homerun", 4), sc.card_label("run", 1)])

    # -- detecting a score ---------------------------------------------------
    print("\ndetecting")
    live = Live()
    live.live_games = [game(0, 0)]
    live._check_scorer_cards()
    check("a first sighting arms nothing", live.resolved == [])
    live.live_games = [game(1, 0)]
    live._check_scorer_cards()
    check("a run arms a lookup for the scoring side", live.resolved == [("g1", "away", 1)],
          live.resolved)
    live.live_games = [game(1, 0)]
    live._check_scorer_cards()
    check("an unchanged score is quiet", len(live.resolved) == 1)
    live.live_games = [game(0, 0)]
    live._check_scorer_cards()
    check("a lower score re-bases silently", len(live.resolved) == 1)

    live = Live(show_scorer_card=False)
    live.live_games = [game(0, 0)]
    live._check_scorer_cards()
    live.live_games = [game(1, 0)]
    live._check_scorer_cards()
    check("off by default: nothing is looked up", live.resolved == [])

    live = Live(scorer_card_favorites_only=True)
    live.live_games = [game(0, 0)]
    live._check_scorer_cards()
    live.live_games = [game(0, 1)]
    live._check_scorer_cards()
    check("favourites only skips the opponent's run", live.resolved == [])
    live.live_games = [game(1, 1)]
    live._check_scorer_cards()
    check("...and takes a favourite's", live.resolved == [("g1", "away", 1)])

    live = Live()
    live.espn_summary_sport_league = None
    live.live_games = [game(0, 0)]
    live._check_scorer_cards()
    live.live_games = [game(1, 0)]
    live._check_scorer_cards()
    check("MiLB (no summary): never looked up", live.resolved == [])

    live = Live()
    live.live_games = [game(1, 0)]
    live._check_scorer_cards()
    live.live_games = []
    live._check_scorer_cards()
    check("a game that left live play drops its baseline", live._scorer_baselines == {})

    # -- arming the card -----------------------------------------------------
    print("\narming")
    live = Live()
    now = time.time()
    live._arm_scorer_card(game(3, 2), "away", 1, HOMER, {"rosters": ROSTERS}, now, now + 6)
    card = live._scorer_card
    check("a home run card", card and card["kind"] == "homerun" and card["batter_id"] == "111"
          and card["team_abbr"] == "PHI")
    check("the roster supplies the vitals", card["info"].get("jersey") == "3")
    check("the bio was asked for", live.bio_fetches == ["111"])
    rows = live._scorer_rows(card, BIO)
    first = {k: v[0] for k, v in rows.items()}
    check("rows: banner with the inning, name, vitals, season line, the play",
          list(rows) == ["header", "name", "vitals", "stats", "play"]
          and first["header"] == "PHI HOME RUN  Top 5th" and first["name"] == "Bryce Harper"
          and first["vitals"] == "#3 1B" and first["stats"] == "AVG .285  HR 30  RBI 98"
          and first["play"].startswith("Bryce Harper homered"), first)
    check("a narrow panel gets shorter wordings to fall back on",
          rows["header"][-1] == "PHI HR" and rows["name"][-1] == "Harper"
          and rows["stats"][-1] == "AVG .285", rows)
    check("with no bio the roster still names him",
          live._scorer_rows(card, {})["name"][0] == "B. Harper")
    live._arm_scorer_card(game(3, 2), "away", 1, EARLIER, {"rosters": ROSTERS}, now, now + 6)
    check("a single that scored is a run card, with ESPN's words about the runner",
          live._scorer_card["kind"] == "run"
          and "Schwarber scored" in live._scorer_card["play_text"])

    # -- the window ------------------------------------------------------------
    print("\nwhen it shows")
    live = Live()
    check("no celebration: it can show straight away",
          abs(live._scorer_window("g1")[0] - time.time()) < 1.0)
    live._start_celebration(game(3, 2), "homerun", "away", "PHI", 3, 2, 1)
    start, until = live._scorer_window("g1")
    check("with a celebration for that game it waits for it to end",
          abs(start - (live.active_celebration["started_at"] + 8)) < 0.5
          and abs(until - start - 6) < 0.01, (start, until))
    check("a celebration for another game does not delay it",
          abs(live._scorer_window("other")[0] - time.time()) < 1.0)

    live = Live()
    t = time.time()
    live._arm_scorer_card(game(3, 2), "away", 1, HOMER, {"rosters": ROSTERS}, t + 5, t + 11)
    check("before its time it does not draw", live._maybe_draw_scorer_card(game()) is False)
    live._scorer_card["show_from"], live._scorer_card["show_until"] = t - 1, t + 5
    check("in its window it draws and presents",
          live._maybe_draw_scorer_card(game()) is True and live.display_manager.updates == 1)
    check("for another game it does not", live._maybe_draw_scorer_card(game(gid="x")) is False)
    live._scorer_card["show_until"] = t - 0.1
    check("expired: it clears itself", live._maybe_draw_scorer_card(game()) is False
          and live._scorer_card is None)
    live = Live(show_scorer_card=False)
    live._scorer_card = {"game_id": "g1", "show_from": 0, "show_until": time.time() + 9}
    check("switched off, a stray card never draws",
          live._maybe_draw_scorer_card(game()) is False)

    # -- every panel size --------------------------------------------------
    print("\nrendering")
    for width, height in [(64, 32), (96, 32), (128, 32), (192, 32), (256, 32),
                          (128, 48), (128, 64), (256, 64)]:
        live = Live(width, height)
        t = time.time()
        live._arm_scorer_card(game(3, 2), "away", 1, HOMER, {"rosters": ROSTERS}, t - 1, t + 6)
        live._scorer_card["game"]["away_team_color"] = (200, 30, 40)
        label = "%dx%d" % (width, height)
        try:
            live._draw_scorer_card(live._scorer_card)
            image = live.display_manager.image
            ok = image.size == (width, height) and image.getbbox() is not None
        except Exception as e:  # noqa: BLE001
            ok, image = False, str(e)
        check(label + ": renders and is not blank", ok, None if ok else image)
        if ok:
            lit_rows = [y for y in range(height) for x in range(width)
                        if image.getpixel((x, y)) != (0, 0, 0)]
            check(label + ": stays on the panel (rows %d-%d)" % (min(lit_rows), max(lit_rows)),
                  min(lit_rows) >= 0 and max(lit_rows) < height)
            rows_drawn = {y for y in lit_rows}
            check(label + ": uses the height it has", len(rows_drawn) >= min(8, height))

    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
