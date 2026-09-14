#!/usr/bin/env python3
"""favorite_weight: favourites always make the cut and repeat in the strip.

Regression under test: with show_favorite_teams_only off, favourite teams did
nothing. Each league showed its soonest max_games_per_league games, so on a
board following UF the Gators' Saturday game never reached the ticker while
five Thursday and Friday games did, and games_per_favorite_team was inert.

The selection and ordering methods run against a stand-in ``self``; the strip
composition runs with per-game rendering and the scroll helper stubbed, since
what is under test is which cards go in and how often each is rendered.

Run: <core-venv>/bin/python plugins/odds-ticker/test_favorite_weight.py
"""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))
_core = os.environ.get("LEDMATRIX_CORE")
_candidates = [Path(_core)] if _core else []
_candidates.append(plugin_dir.parents[2] / "LEDMatrix")
for candidate in _candidates:
    if (candidate / "src" / "plugin_system" / "base_plugin.py").exists():
        sys.path.insert(0, str(candidate))
        break

from manager import OddsTickerPlugin  # noqa: E402

failures = []


def check(label, ok):
    print(("  PASS  " if ok else "  FAIL  ") + label)
    if not ok:
        failures.append(label)


BASE = datetime(2026, 9, 17, 12, 0, 0)


def game(gid, hours, home="X", away="Y", league="ncaa_fb"):
    return {"id": gid, "home_team": home, "away_team": away, "league": league,
            "start_time": BASE + timedelta(hours=hours)}


class _Ticker:
    _select_games = OddsTickerPlugin._select_games
    _favorite_quota = staticmethod(OddsTickerPlugin._favorite_quota)
    _is_favorite_game = OddsTickerPlugin._is_favorite_game
    _weighted_ticker_order = OddsTickerPlugin._weighted_ticker_order
    _create_ticker_image = OddsTickerPlugin._create_ticker_image

    def __init__(self, weight=1, per_favorite=1, favorites=("UF",), max_games=5):
        self.favorite_weight = weight
        self.games_per_favorite_team = per_favorite
        self.max_games_per_league = max_games
        self.show_favorite_teams_only = False
        self.league_configs = {"ncaa_fb": {"favorite_teams": list(favorites)}}


def slate():
    # Eight games; UF's is the seventh soonest, so a plain cut of five misses it.
    games = [game("g%d" % i, i) for i in range(8)]
    games[6] = game("uf", 6, home="UF", away="FSU")
    return games


def cyclic_repeats(order):
    return any(order[i] == order[(i + 1) % len(order)] for i in range(len(order)))


def main():
    cfg = {"favorite_teams": ["UF"]}

    print("weight 1 keeps the old cut exactly")
    t = _Ticker(weight=1)
    picked = [g["id"] for g in t._select_games(slate(), cfg)]
    check("the five soonest, favourite or not (%s)" % picked,
          picked == ["g0", "g1", "g2", "g3", "g4"])
    check("strip order is one pass", t._weighted_ticker_order(slate()) == list(range(8)))

    print("\nweight above 1 guarantees the favourite a slot")
    t = _Ticker(weight=2)
    picked = t._select_games(slate(), cfg)
    ids = [g["id"] for g in picked]
    check("UF's game is in (%s)" % ids, "uf" in ids)
    check("still five games", len(picked) == 5)
    check("the rest are the soonest others", ids[:4] == ["g0", "g1", "g2", "g3"])
    check("returned in start order",
          [g["start_time"] for g in picked] == sorted(g["start_time"] for g in picked))

    print("\ngames_per_favorite_team bounds the guarantee")
    many = [game("tb%d" % i, 10 + i, home="TB") for i in range(6)] + \
           [game("o%d" % i, i) for i in range(6)]
    t = _Ticker(weight=3, per_favorite=1, favorites=("TB",))
    ids = [g["id"] for g in t._select_games(many, {"favorite_teams": ["TB"]})]
    check("one guaranteed TB game, four soonest others (%s)" % ids,
          ids == ["o0", "o1", "o2", "o3", "tb0"])
    t = _Ticker(weight=3, per_favorite=2, favorites=("TB",))
    ids = [g["id"] for g in t._select_games(many, {"favorite_teams": ["TB"]})]
    check("two with games_per_favorite_team=2 (%s)" % ids,
          ids.count("tb0") == 1 and ids.count("tb1") == 1 and len(ids) == 5)

    print("\nno favourites configured means the plain cut")
    t = _Ticker(weight=4, favorites=())
    ids = [g["id"] for g in t._select_games(slate(), {"favorite_teams": []})]
    check("five soonest", ids == ["g0", "g1", "g2", "g3", "g4"])

    print("\nthe strip repeats favourites, spread around the loop")
    t = _Ticker(weight=2)
    games = t._select_games(slate(), cfg)
    order = t._weighted_ticker_order(games)
    uf = [i for i, g in enumerate(games) if g["id"] == "uf"][0]
    check("UF appears twice (%s)" % order, order.count(uf) == 2)
    check("every other game appears once",
          all(order.count(i) == 1 for i in range(len(games)) if i != uf))
    check("never back to back, including across the seam", not cyclic_repeats(order))
    check("the others keep their order",
          [i for i in order if i != uf] == [i for i in range(len(games)) if i != uf])
    t = _Ticker(weight=3)
    order = t._weighted_ticker_order(games)
    check("weight 3 -> three turns, still spread (%s)" % order,
          order.count(uf) == 3 and not cyclic_repeats(order))

    print("\na favourite of another league is not boosted")
    t = _Ticker(weight=3)
    other = [game("a", 0), game("b", 1, home="UF", league="nhl"), game("c", 2)]
    check("UF in the NHL is not the Gators", t._weighted_ticker_order(other) == [0, 1, 2])

    print("\nthe composed strip renders each game once and places it per weight")

    class _Scroll:
        total_scroll_width = 0
        cached_image = cached_array = None

        def create_scrolling_image(self, content_items, item_gap, element_gap):
            self.items = content_items
            width = 64 + sum(i.width for i in content_items) + item_gap * len(content_items)
            return Image.new("RGB", (width, 32))

        def get_dynamic_duration(self):
            return 30

        def clear_cache(self):
            pass

    class _Matrix:
        width, height = 64, 32

    class _Display:
        matrix = _Matrix()

    t = _Ticker(weight=2)
    t.games_data = t._select_games(slate(), cfg)
    t.scroll_helper = _Scroll()
    t.display_manager = _Display()
    rendered = []

    def render(g):
        rendered.append(g["id"])
        return Image.new("RGB", (10 + len(rendered), 32))

    t._create_game_display = render
    t._create_ticker_image()
    check("five distinct renders for six cards (%s)" % rendered,
          sorted(rendered) == sorted(g["id"] for g in t.games_data) and len(rendered) == 5)
    check("six cards in the strip", len(t.scroll_helper.items) == 6)
    uf_image = t.scroll_helper.items[t._weighted_ticker_order(t.games_data).index(
        [i for i, g in enumerate(t.games_data) if g["id"] == "uf"][0])]
    check("both UF cards are the one UF render",
          sum(1 for img in t.scroll_helper.items if img is uf_image) == 2)
    check("games_data itself is not duplicated", len(t.games_data) == 5)

    print("\n%s" % ("FAILED: %d" % len(failures) if failures else "All checks passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
