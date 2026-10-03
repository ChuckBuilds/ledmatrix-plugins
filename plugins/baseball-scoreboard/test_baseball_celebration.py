#!/usr/bin/env python3
"""Run, home-run and win celebrations for the baseball scoreboards.

Pins what arms a celebration (a celebratable team's run total going up, never a
first sighting, never a lower score), how a home run is told from a plain run,
the headlines, that the takeover renders on every panel size in all three
flavours and that its motion is a function of time, and that the plugin asks
the core for the high-FPS loop while one is on screen.

Run: <core-venv>/bin/python plugins/baseball-scoreboard/test_baseball_celebration.py
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
                 "away_id": "22", "home_id": "15",
                 "away_logo_path": None, "home_logo_path": None,
                 "away_score": str(away), "home_score": str(home)}, **extra)


def main():
    os.chdir(str(CORE))
    from PIL import Image
    import baseball
    import baseball_celebration as bc
    import sports

    class Frame:
        def __init__(self):
            self.image = None
            self.matrix = None
            self.updates = 0

        def clear(self):
            pass

        def update_display(self):
            self.updates += 1

    class Live(bc.BaseballCelebrationMixin, baseball.Baseball):
        def __init__(self, width=128, height=32, favorites=("PHI",), **cfg):
            self.config = {}
            self.mode_config = dict(cfg)
            self.favorite_teams = list(favorites)
            self.display_width, self.display_height = width, height
            self.logger = logging.getLogger("celebration-test")
            self._font_cache = {}
            self.fonts = sports.SportsCore._load_fonts(self)
            self.display_manager = Frame()
            self.live_games = []
            self.last_game_switch = 0
            self.current_game = None
            self.plays = None           # what ESPN's summary "returns"
            self._init_celebration()

        def _fetch_summary_plays(self, game_id):
            return self.plays

        def _fetch_data(self):  # pragma: no cover
            raise NotImplementedError

        def _load_and_resize_logo(self, team_id, abbr, path, url=None):
            colour = (200, 30, 40, 255) if abbr == "PHI" else (20, 40, 120, 255)
            size = self.display_height - 2
            image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            image.paste(Image.new("RGBA", (size - 6, size - 6), colour), (3, 3))
            return image

    homer = [{"type": {"type": "home-run"}, "scoringPlay": True, "text": "Harper homered"}]
    single = [{"type": {"type": "single"}, "scoringPlay": True, "text": "Turner singled"}]

    # -- telling a home run from a run -----------------------------------
    print("home run or run")
    check("home-run play type", bc.home_run_in_plays(homer) is True)
    check("a single that scored is a run", bc.home_run_in_plays(single) is False)
    check("'homered' in the text counts", bc.is_home_run_play({"text": "X homered to left"}))
    check("no plays is unknown, not a run", bc.home_run_in_plays([]) is None
          and bc.home_run_in_plays(None) is None)
    check("the newest scoring play wins, not the newest play",
          bc.home_run_in_plays(homer + [{"type": {"type": "strike-out"}, "text": "K"}]) is True)
    check("an older homer does not make a later single a homer",
          bc.home_run_in_plays(homer + single) is False)
    check("flagless feed falls back to the last substantive play",
          bc.home_run_in_plays([{"type": {"type": "home-run"}, "text": "x"}]) is True)

    # -- headlines --------------------------------------------------------
    print("\nheadlines")
    first = lambda options: options[0]  # noqa: E731
    check("run", bc.celebration_phrase("run", "PHI", 1, first) == "RUN SCORES!")
    check("several runs", bc.celebration_phrase("run", "PHI", 3) == "PHI +3!")
    check("home run", bc.celebration_phrase("homerun", "PHI", 1, first) == "HOME RUN!")
    check("2-run homer", bc.celebration_phrase("homerun", "PHI", 2) == "2-RUN HOMER!")
    check("3-run homer", bc.celebration_phrase("homerun", "PHI", 3) == "3-RUN HOMER!")
    check("grand slam", bc.celebration_phrase("homerun", "PHI", 4) == "GRAND SLAM!")
    check("win", bc.celebration_phrase("win", "PHI", 1) == "PHI WINS!")

    # -- arming -----------------------------------------------------------
    print("\narming")
    live = Live()
    live._check_for_score(game(0, 0))
    check("a first sighting never celebrates", live.active_celebration is None)
    live._check_for_score(game(1, 0))
    c = live.active_celebration
    check("a favourite's run is a run", c and c["kind"] == "run" and c["scored_side"] == "away"
          and c["motif"] == "run" and c["runs"] == 1, c and (c["kind"], c["runs"]))
    check("the scorebug is pinned to that game", live.current_game["id"] == "g1")

    live = Live()
    live._check_for_score(game(0, 0))
    live.plays = homer
    live._check_for_score(game(2, 0))
    c = live.active_celebration
    check("a 2-run homer", c and c["kind"] == "homerun" and c["runs"] == 2
          and c["phrase"] == "2-RUN HOMER!", c and (c["kind"], c["runs"], c["phrase"]))

    live = Live()
    live._check_for_score(game(0, 0))
    live._check_for_score(game(0, 1))
    check("the opponent's run is not celebrated by default",
          live.active_celebration is None)
    live = Live(celebrate_opponent_runs=True)
    live._check_for_score(game(0, 0))
    live._check_for_score(game(0, 1))
    check("...unless asked", live.active_celebration["scored_side"] == "home")

    live = Live(favorites=())
    live._check_for_score(game(0, 0))
    live._check_for_score(game(0, 1))
    check("no favourites: every run in a shown game", live.active_celebration is not None)

    live = Live()
    live._check_for_score(game(3, 0))
    live._check_for_score(game(2, 0))
    live._check_for_score(game(2, 0))
    check("a lower score re-bases and an unchanged one is quiet",
          live.active_celebration is None)

    live = Live(celebration_enabled=False)
    live._check_for_score(game(0, 0))
    live._check_for_score(game(1, 0))
    check("celebration_enabled=False arms nothing", live.active_celebration is None)

    live = Live(celebration_home_runs_only=True)
    live._check_for_score(game(0, 0))
    live._check_for_score(game(1, 0))
    check("home-runs-only skips a plain run", live.active_celebration is None)
    live.plays = homer
    live._check_for_score(game(2, 0))
    check("...and still takes a homer", live.active_celebration["kind"] == "homerun")

    live = Live()
    live.plays = None
    live._play_by_play_cache = {"g1": {"last_play_code": "HR"}}
    live._check_for_score(game(0, 0))
    live._check_for_score(game(1, 0))
    check("no summary: the at-bat cache's HR still counts",
          live.active_celebration["kind"] == "homerun")

    live = Live()
    live.live_games = [game(0, 0), game(0, 0, gid="g2")]
    live._check_scores_of_live_games()
    live.live_games = [game(1, 0), game(0, 0, gid="g2")]
    live._check_scores_of_live_games()
    check("every live game is checked, not only the one on screen",
          live.active_celebration["game"]["id"] == "g1")

    # -- wins -------------------------------------------------------------
    print("\nwins")
    live = Live()
    live._check_for_score(game(0, 0))
    live._check_for_win(game(4, 2))
    c = live.active_celebration
    check("a favourite's win", c and c["kind"] == "win" and c["motif"] == "win"
          and c["phrase"] == "PHI WINS!")
    live.active_celebration = None
    live._check_for_win(game(4, 2))
    check("only once per game", live.active_celebration is None)
    live = Live()
    live._check_for_win(game(4, 2))
    check("a game first seen final never celebrates", live.active_celebration is None)
    live = Live()
    live._check_for_score(game(0, 0))
    live._check_for_win(game(2, 4))
    check("an opponent's win is not celebrated", live.active_celebration is None)

    # -- display ----------------------------------------------------------
    print("\ndisplay")
    live = Live()
    check("nothing armed: display() does not take the panel",
          live._celebration_display(False) is False)
    live._check_for_score(game(0, 0))
    live._check_for_score(game(1, 0))
    check("armed: it takes the panel and presents a frame",
          live._celebration_display(False) is True
          and live.display_manager.image is not None
          and live.display_manager.updates == 1)
    live.active_celebration["started_at"] -= 100
    check("expired: it clears itself and gives the scorebug a full turn",
          live._celebration_display(False) is False
          and live.active_celebration is None and live.last_game_switch > 0)
    check("has_active_celebration follows the clock", live.has_active_celebration() is False)

    # -- rendering --------------------------------------------------------
    print("\nrendering")
    sizes = [(64, 32), (128, 32), (192, 32), (320, 32), (128, 64)]
    for width, height in sizes:
        frames = {}
        for kind, runs in (("run", 1), ("homerun", 1), ("homerun", 4), ("win", 1)):
            live = Live(width, height)
            live._start_celebration(game(2, 1), kind, "away", "PHI", 2, 1, runs)
            try:
                shots = []
                for t in (0.0, 1.0, 2.2, 4.0, 6.5):
                    live.active_celebration["started_at"] = time.time() - t
                    live._draw_celebration_layout(live.active_celebration)
                    shots.append(live.display_manager.image.copy())
                ok = all(s.size == (width, height) and s.mode == "RGB" for s in shots)
            except Exception as e:  # noqa: BLE001
                ok, shots = False, str(e)
            label = "%dx%d %s%s" % (width, height, kind, " x%d" % runs if runs > 1 else "")
            check(label + ": renders at every moment", ok, shots if not ok else None)
            frames[(kind, runs)] = shots
        run, hr = frames[("run", 1)], frames[("homerun", 1)]
        check("%dx%d: a run and a home run look different" % (width, height),
              run[1].tobytes() != hr[1].tobytes())
        check("%dx%d: the runner moves" % (width, height),
              run[1].tobytes() != run[2].tobytes())
        check("%dx%d: the fireworks move" % (width, height),
              hr[1].tobytes() != hr[2].tobytes())

    # -- one celebration, one headline ------------------------------------
    print("\nthe headline holds still")
    for kind in ("run", "homerun"):
        live = Live(128, 32)
        live._start_celebration(game(2, 1), kind, "away", "PHI", 3, 1, 1, before=(2, 1))
        phrase = live.active_celebration["phrase"]
        for t in (0.0, 0.5, 1.0, 2.0, 3.0, 5.0):
            live.active_celebration["started_at"] = time.time() - t
            live._draw_celebration_layout(live.active_celebration)
        check(kind + ": the phrase is chosen once, not per frame",
              live.active_celebration["phrase"] == phrase)

    # -- the plugin asks for high FPS -------------------------------------
    print("\nhigh FPS")
    import manager
    plugin = object.__new__(manager.BaseballScoreboardPlugin)
    plugin.logger = logging.getLogger("fps")
    plugin.enable_scrolling = False
    plugin.is_enabled = True
    plugin._league_registry = {"mlb": {"enabled": True}}
    celebrating = [False]

    class _Live:
        def has_active_celebration(self):
            return celebrating[0]

    plugin._get_league_manager_for_mode = lambda league, mode: _Live()
    check("quiet board: no high FPS", plugin.needs_high_fps is False)
    celebrating[0] = True
    check("celebrating: high FPS", plugin.needs_high_fps is True)
    check("...and it keeps the live mode on screen", plugin.has_live_content() is True)
    celebrating[0] = False
    plugin.enable_scrolling = True
    check("scrolling boards keep their behaviour", plugin.needs_high_fps is True)
    check("never raises on a bare instance",
          object.__new__(manager.BaseballScoreboardPlugin).needs_high_fps is False)

    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
