#!/usr/bin/env python3
"""Golden-image guard for the scroll/Vegas game card.

WHY THIS EXISTS
---------------
The plugin safety harness (core `scripts/check_plugin.py`) renders every
scoreboard in `switch` mode, so its output comes from the full-screen scorebug
in sports.py. `game_renderer.py` -- the scroll/Vegas card renderer -- is
imported but never called. Replacing `render_game_card`, `_draw_upcoming_center`,
`_center_gap_width` and `_logo_slot_width` with functions that raise leaves all
16 of hockey's harness renders passing and byte-identical to the clean tree.

Setting `*_display_mode: "scroll"` in a harness.json variant does not help: the
resulting renders come out byte-identical to the switch ones, so the mode never
reaches the card path from there either.

That gap is not theoretical. Two consolidations of game_renderer.py -- the
sports_card helpers and the geometry mixin -- were each reported "byte-identical
across 176 renders" while not one of those renders touched the file being
changed. B5 shipped four of eight scoreboards with scroll mode broken while
every gate was green, for the same reason.

WHAT IT DOES
------------
Drives GameRenderer directly, which is the real card path, and compares the
result to goldens committed next to each plugin. Any change to the rendered
card -- geometry, colour, font sizing, logo slot -- shows up here.

    python scripts/test_scroll_card_renders.py            # check
    python scripts/test_scroll_card_renders.py --update   # regenerate goldens

Exit 0 pass, 2 skip (no core / no assets), 1 fail.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

#: Three sizes, not all eight: the smallest panel where the centre gap and the
#: logo slot fight hardest, the common design size, and the largest chain.
SIZES = [(64, 32), (128, 64), (256, 128)]
TYPES = ["live", "recent", "upcoming"]

#: league key in config, logo directory, and two teams that have logo files.
PLUGINS = {
    "afl":        ("afl",          "afl_logos",    "GEEL", "COLL"),
    "baseball":   ("mlb",          "mlb_logos",    "NYY",  "BOS"),
    "basketball": ("nba",          "nba_logos",    "LAL",  "BOS"),
    "football":   ("nfl",          "nfl_logos",    "KC",   "PHI"),
    "hockey":     ("nhl",          "nhl_logos",    "BOS",  "TOR"),
    "lacrosse":   ("ncaa_lax_men", "ncaa_logos",   "SYR",  "ND"),
    "nrl":        ("nrl",          "nrl_logos",    "BRI",  "PEN"),
    "soccer":     ("eng.1",        "soccer_logos", "ARS",  "LIV"),
}

EXPECTED = len(PLUGINS) * len(SIZES) * len(TYPES)


def core_root():
    env = os.environ.get("LEDMATRIX_CORE")
    if env and (Path(env) / "src").is_dir():
        return Path(env)
    for cand in (REPO.parent / "LEDMatrix", Path.home() / "LEDMatrix"):
        if (cand / "src").is_dir():
            return cand
    return None


def build_game(kind, league, home, away, logo_dir):
    """One game, with every key any of the eight renderers reads."""
    hp, ap = logo_dir / f"{home}.png", logo_dir / f"{away}.png"
    game = {
        "home_abbr": home, "away_abbr": away,
        "home_team": home, "away_team": away,
        "home_id": "1", "away_id": "2",
        "home_score": "3", "away_score": "1",
        "home_record": "10-2", "away_record": "7-5",
        "league": league,
        "game_date": "Sep 19", "game_time": "7:00 PM",
        "start_time": "2026-09-19T23:00:00Z",
        "start_time_utc": "2026-09-19T23:00:00Z",
        "home_logo_path": str(hp) if hp.is_file() else None,
        "away_logo_path": str(ap) if ap.is_file() else None,
        "home_logo_url": None, "away_logo_url": None,
        "period_text": "P2", "clock": "12:34", "status_text": "P2 12:34",
        "status": {"type": {"state": "in"}},
        "is_live": kind == "live", "is_final": kind == "recent",
        "is_upcoming": kind == "upcoming",
        "is_halftime": False, "is_period_break": False, "is_tournament": False,
        "home_shots": "22", "away_shots": "18", "odds": None,
    }
    if kind == "upcoming":
        game.update(home_score="0", away_score="0", period_text="", clock="",
                    status_text="", is_live=False, status={"type": {"state": "pre"}})
    elif kind == "recent":
        game.update(period_text="Final", clock="", status_text="Final",
                    is_live=False, status={"type": {"state": "post"}})
    return game


def load_renderer(plugin):
    """Import this plugin's game_renderer.py under its own module name."""
    pdir = REPO / "plugins" / f"{plugin}-scoreboard"
    name = f"_cardguard_{plugin}"
    sys.modules.pop(name, None)
    sys.path.insert(0, str(pdir))
    try:
        spec = importlib.util.spec_from_file_location(name, pdir / "game_renderer.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod.GameRenderer
    finally:
        sys.path.remove(str(pdir))


def main(update: bool) -> int:
    core = core_root()
    if core is None:
        print("  [skip] no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
        return 2
    assets = core / "assets" / "sports"
    if not assets.is_dir():
        print(f"  [skip] no logo assets at {assets}")
        return 2

    sys.path.insert(0, str(core))
    # The plugins' default logo_dir values are RELATIVE ("assets/sports/..."),
    # so they only resolve with the core as the working directory. Anywhere
    # else silently renders logo-less cards that still compare clean.
    os.chdir(core)

    from PIL import Image  # noqa: E402  (needs core on sys.path first)

    covered = failed = written = 0   # covered counts cards ATTEMPTED
    problems = []

    for plugin, (league, logo_dirname, home, away) in sorted(PLUGINS.items()):
        pdir = REPO / "plugins" / f"{plugin}-scoreboard"
        if not (pdir / "game_renderer.py").is_file():
            problems.append(f"{plugin}: no game_renderer.py")
            failed += 1
            covered += len(SIZES) * len(TYPES)
            continue
        try:
            GameRenderer = load_renderer(plugin)
        except Exception as exc:                      # noqa: BLE001
            problems.append(f"{plugin}: import failed -- {type(exc).__name__}: {exc}")
            failed += 1
            covered += len(SIZES) * len(TYPES)
            continue

        logo_dir = assets / logo_dirname
        config = {
            league: {"enabled": True, "logo_dir": str(logo_dir)},
            "scroll_card": {}, "customization": {},
            "display": {"use_short_date_format": False},
        }
        golden_root = pdir / "test" / "golden-cards"

        for (w, h) in SIZES:
            for kind in TYPES:
                rel = f"{w}x{h}/{kind}.png"
                covered += 1
                try:
                    renderer = GameRenderer(w, h, config, logo_cache={})
                    img = renderer.render_game_card(
                        build_game(kind, league, home, away, logo_dir), kind
                    ).convert("RGB")
                except Exception as exc:              # noqa: BLE001
                    problems.append(f"{plugin} {rel}: render raised "
                                    f"{type(exc).__name__}: {exc}")
                    failed += 1
                    continue

                golden = golden_root / rel
                if update:
                    golden.parent.mkdir(parents=True, exist_ok=True)
                    img.save(golden, optimize=True)
                    written += 1
                    continue

                if not golden.is_file():
                    problems.append(f"{plugin} {rel}: no golden "
                                    f"(run with --update to create it)")
                    failed += 1
                elif Image.open(golden).convert("RGB").tobytes() != img.tobytes():
                    problems.append(f"{plugin} {rel}: differs from golden")
                    failed += 1

    if update:
        print(f"  wrote {written} golden card(s)")
        if written != EXPECTED:
            print(f"  [FAIL] wrote {written}, expected {EXPECTED}")
            return 1
        return 0

    # Assert the COUNT, not just the mismatch total. A comparison whose inputs
    # silently went missing reports zero differences and reads as a pass.
    if covered != EXPECTED:
        problems.append(f"covered {covered} card(s), expected {EXPECTED} "
                        f"-- the matrix or a plugin went missing")
        failed += 1

    for p in problems:
        print(f"  [FAIL] {p}")
    if failed:
        print(f"  {covered} cards covered, {failed} problem(s)")
        return 1
    print(f"  [pass] {covered} scroll/Vegas cards match their goldens")
    return 0


if __name__ == "__main__":
    sys.exit(main(update="--update" in sys.argv))
