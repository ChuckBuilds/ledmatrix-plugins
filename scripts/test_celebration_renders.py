#!/usr/bin/env python3
"""Golden-image guard for the score/win celebration takeover.

WHY THIS EXISTS
---------------
Five scoreboards -- afl, football, hockey, nrl and soccer -- draw the same
full-screen takeover when a team scores or wins: a team-colour backdrop read
off the crest, per-score scenery, confetti, the headline and a breathing
score. The safety harness never reaches it (a celebration needs a live score
to change), and only football, hockey and soccer carried goldens for it, each
through its own test and at a few sizes.

This drives every copy of the drawing code the same way, with fixed inputs,
and compares each frame to goldens committed next to the plugin. Any change
to the takeover -- palette, scenery, confetti, text placement -- shows up
here, in every plugin that draws it.

WHAT IS FIXED
-------------
* The crests are drawn here rather than read from logo files, which differ
  between checkouts (see test_scroll_card_renders.py).
* The fonts are the core's own, at fixed sizes, not each plugin's font
  settings: those are not part of the takeover. They are loaded with core's
  ``font_layout.load_truetype``, which pins Pillow's Basic layout engine:
  with Raqm (Linux wheels have it, Windows ones do not) the 4x6 face's
  fractional advances land differently, and the 64-wide frames, whose
  headline falls back to that face, differed between platforms.
* The clock: ``time.time`` is patched for the whole render, so the flash, the
  breathing digits and the confetti fall land on the same frame every run.
  Patching the ``time`` module rather than one plugin's global keeps this
  honest if the drawing code moves to another module.
* The confetti is already seeded from the game and the phrase.

What each plugin does to *arm* a celebration (which scores count, the
phrase, the scenery) is its own and is tested beside the plugin; this only
draws a celebration it is handed.

    python scripts/test_celebration_renders.py            # check
    python scripts/test_celebration_renders.py --update   # regenerate goldens

Exit 0 pass, 2 skip (no core checkout), 1 fail.
"""
from __future__ import annotations

import importlib.util
import logging
import os
import sys
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent

#: The safety harness's eight default sizes.
SIZES = [(64, 32), (128, 32), (64, 64), (96, 48),
         (128, 64), (256, 32), (128, 96), (256, 128)]

#: The scenery each plugin paints behind a score (its _start_celebration).
PLUGINS = {
    "afl": "score",
    "football": "touchdown",
    "hockey": "net",
    "nrl": "score",
    "soccer": "score",
}

#: Every motif _draw_celebration_motif knows, drawn by every copy at 128x32.
MOTIFS = ["score", "kick", "touchdown", "net", "win"]

#: name -> overrides of the base celebration below, drawn at 128x32 only.
VARIANTS = {
    "opening_hit": {"elapsed": 0.3},
    "settling": {"elapsed": 7.2},
    "no_team_colors": {"team_colors": False},
    "no_confetti": {"confetti": False},
    "silver_crest": {"scorer": "SIL"},
    "home_scores": {"scored_side": "home"},
}

EXPECTED = len(PLUGINS) * (len(SIZES) * 2 + len(MOTIFS) + len(VARIANTS))


def core_root():
    env = os.environ.get("LEDMATRIX_CORE")
    if env and (Path(env) / "src").is_dir():
        return Path(env)
    for cand in (REPO.parent / "LEDMatrix", Path.home() / "LEDMatrix"):
        if (cand / "src").is_dir():
            return cand
    return None


def crest(abbr):
    """A 64px two-colour crest, the kinds _logo_palette has to tell apart:
    a saturated one, a dark one with a bright band, and a silver one."""
    from PIL import Image, ImageDraw

    body, band = {
        "RED": ((200, 16, 46), (255, 255, 255)),   # vivid
        "NAV": ((12, 35, 64), (255, 184, 28)),     # dark primary, gold band
        "SIL": ((165, 172, 175), (0, 0, 0)),       # no vivid colour at all
    }[abbr]
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.polygon([(6, 4), (58, 4), (58, 34), (32, 60), (6, 34)], fill=body + (255,))
    draw.rectangle([(6, 22), (58, 32)], fill=band + (255,))
    return img


def load_sports(plugin):
    """Import this plugin's sports.py under its own module name.

    Its bare-name siblings (data_sources, dynamic_team_resolver, ...) are
    dropped from sys.modules afterwards so the next plugin binds its own.
    """
    pdir = REPO / "plugins" / f"{plugin}-scoreboard"
    name = f"_celebration_guard_{plugin}"
    before = set(sys.modules)
    sys.path.insert(0, str(pdir))
    try:
        spec = importlib.util.spec_from_file_location(name, pdir / "sports.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.path.remove(str(pdir))
        for key in set(sys.modules) - before:
            if str(pdir) in (getattr(sys.modules[key], "__file__", None) or ""):
                if key != name:
                    del sys.modules[key]


def render(sports, width, height, motif, kind="score", scored_side="away",
           scorer="RED", elapsed=2.0, team_colors=True, confetti=True):
    """One frame of the takeover, drawn by this plugin's SportsLive."""
    from PIL import Image
    from src.common.font_layout import load_truetype

    class _Matrix:
        pass

    class _DisplayManager:
        def __init__(self):
            self.matrix = _Matrix()
            self.matrix.width, self.matrix.height = width, height
            self.image = Image.new("RGB", (width, height))

        def clear(self):
            self.image = Image.new("RGB", (width, height))

        def update_display(self):
            pass

    live_cls = type("_Live", (sports.SportsLive,), {})
    live_cls.__abstractmethods__ = frozenset()
    live = object.__new__(live_cls)
    live.display_manager = _DisplayManager()
    live.display_width, live.display_height = width, height
    live.logger = logging.getLogger("celebration-guard")
    live.celebration_duration = 8
    live.celebration_team_colors = team_colors
    live.celebration_confetti = confetti
    press = os.path.join("assets", "fonts", "PressStart2P-Regular.ttf")
    live.fonts = {
        "time": load_truetype(press, 8),
        "status": load_truetype(os.path.join("assets", "fonts", "4x6-font.ttf"), 6),
        # Tall panels scale the score up (#338); 16px is what they reach.
        "score": load_truetype(press, 16 if height >= 48 else 10),
    }

    def load_logo(team_id, abbr, path, url=None):
        logo = crest(abbr)
        logo.thumbnail((height, height), Image.Resampling.LANCZOS)
        return logo

    live._load_and_resize_logo = load_logo

    other = "RED" if scorer == "NAV" else "NAV"
    away, home = (scorer, other) if scored_side == "away" else (other, scorer)
    phrase = f"{scorer} WINS!" if kind == "win" else f"{scorer} SCORES!"
    celebration = {
        "kind": kind,
        "motif": motif,
        "game": {"id": "401", "away_abbr": away, "home_abbr": home,
                 "away_id": "1", "home_id": "2"},
        "scored_side": scored_side,
        "team_abbr": scorer,
        "away_score": 3, "home_score": 2,
        "started_at": 1000.0,
        "phrase": phrase,
    }
    with mock.patch("time.time", return_value=1000.0 + elapsed):
        live._draw_celebration_layout(celebration, force_clear=True)
    return live.display_manager.image.convert("RGB")


def frames(plugin_motif):
    """(relative path, render kwargs) for every golden of one plugin."""
    for (w, h) in SIZES:
        yield f"{w}x{h}/score.png", dict(width=w, height=h, motif=plugin_motif)
        yield f"{w}x{h}/win.png", dict(width=w, height=h, motif="win", kind="win",
                                        scorer="NAV")
    for motif in MOTIFS:
        yield f"128x32/motif_{motif}.png", dict(width=128, height=32, motif=motif)
    for name, overrides in VARIANTS.items():
        yield f"128x32/{name}.png", dict(width=128, height=32, motif=plugin_motif,
                                         **overrides)


def main(update: bool) -> int:
    core = core_root()
    if core is None:
        print("  [skip] no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
        return 2

    sys.path.insert(0, str(core))
    logging.disable(logging.ERROR)
    # The fonts above are relative to the core, as the plugins' own are.
    os.chdir(core)

    from PIL import Image  # noqa: E402  (needs core on sys.path first)

    covered = failed = written = 0
    problems = []
    for plugin, motif in sorted(PLUGINS.items()):
        try:
            sports = load_sports(plugin)
        except Exception as exc:                      # noqa: BLE001
            problems.append(f"{plugin}: import failed -- {type(exc).__name__}: {exc}")
            failed += 1
            continue
        golden_root = REPO / "plugins" / f"{plugin}-scoreboard" / "test" / "golden-celebration"
        for rel, kwargs in frames(motif):
            covered += 1
            try:
                img = render(sports, **kwargs)
            except Exception as exc:                  # noqa: BLE001
                problems.append(f"{plugin} {rel}: render raised "
                                f"{type(exc).__name__}: {exc}")
                failed += 1
                continue
            golden = golden_root / rel
            if update:
                golden.parent.mkdir(parents=True, exist_ok=True)
                img.save(golden, optimize=True)
                written += 1
            elif not golden.is_file():
                problems.append(f"{plugin} {rel}: no golden (run with --update)")
                failed += 1
            elif Image.open(golden).convert("RGB").tobytes() != img.tobytes():
                problems.append(f"{plugin} {rel}: differs from golden")
                failed += 1

    if update:
        print(f"  wrote {written} golden frame(s)")
        return 0 if written == EXPECTED and not problems else 1

    # Assert the COUNT: a comparison whose inputs went missing reports no
    # differences and would read as a pass.
    if covered != EXPECTED:
        problems.append(f"covered {covered} frame(s), expected {EXPECTED}")
        failed += 1
    for p in problems:
        print(f"  [FAIL] {p}")
    if failed:
        print(f"  {covered} frames covered, {failed} problem(s)")
        return 1
    print(f"  [pass] {covered} celebration frames match their goldens")
    return 0


if __name__ == "__main__":
    sys.exit(main(update="--update" in sys.argv))
