#!/usr/bin/env python3
"""Scroll and Vegas cards must honour the same display options as the switch card.

The switch card resolves records, rankings, odds and the shots line from the
league's ``display_options`` block (manager.py). The scroll/Vegas renderer
read other keys:

* afl/nrl read only the root ``show_*`` keys, so a change made under
  ``display_options`` never reached a scrolling card.
* hockey/lacrosse read records and rankings from ``defaults`` only, never the
  league's block, and looked the league up by the game's tag -- which on the
  Vegas path is the ESPN sport key (``ncaam_hockey``), not a config key, so the
  NCAA leagues' shots and power-play settings were never read there either.

Each plugin runs in its own interpreter, since every one of them has a module
named ``game_renderer``.

Run: LEDMATRIX_CORE=/path/to/LEDMatrix python scripts/test_scroll_card_display_options.py
Exit 0 pass, 1 fail, 2 skip (no core checkout).
"""
import json
import os
import subprocess  # nosec B404
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUGINS = REPO / "plugins"

PROBE = r'''
import json, logging, sys
sys.path.insert(0, sys.argv[1])
from PIL import Image, ImageDraw
import game_renderer as gr
kind = sys.argv[2]
out = {}
log = logging.getLogger("probe")


def drawn(renderer, game):
    texts = []
    renderer._draw_text_with_outline = lambda d, text, *a, **k: texts.append(text)
    draw = ImageDraw.Draw(Image.new("RGBA", (128, 32)))
    renderer._draw_records_or_rankings(draw, game)
    return texts


def game(league):
    return {"league": league,
            "home_team": {"abbrev": "BC", "record": "10-2"},
            "away_team": {"abbrev": "BU", "record": "8-4"}}


if kind == "root":
    # A user who turned records on and odds off in display_options; the
    # root keys still hold what the web UI saved from the schema defaults.
    config = {"display_options": {"show_records": True, "show_odds": False},
              "show_records": False, "show_odds": True}
    r = gr.GameRenderer(128, 32, config, custom_logger=log)
    out["records on in display_options"] = r.show_records is True
    out["odds off in display_options"] = r.show_odds is False
    r = gr.GameRenderer(128, 32, {"show_records": True}, custom_logger=log)
    out["a root-only setting still applies"] = r.show_records is True
else:
    sport, shots_key = kind.split(":")
    config = {
        "defaults": {"show_records": False, "show_ranking": False, shots_key: False},
        "nhl": {"display_options": {"show_records": False}},
        "ncaa_mens": {"display_options": {"show_records": True, "show_ranking": False,
                                          shots_key: True}},
        "ncaa_womens": {"display_options": {"show_records": False, "show_ranking": False}},
    }
    r = gr.GameRenderer(128, 32, config, custom_logger=log)
    shots = getattr(r, "_" + shots_key)
    for league in ("ncaa_mens", "ncaam_" + sport):
        out["%s: league's records switch draws the record" % league] = \
            drawn(r, game(league)) == ["8-4", "10-2"]
        out["%s: league's shots switch is read" % league] = shots(league) is True
    config["defaults"]["show_records"] = True
    r = gr.GameRenderer(128, 32, config, custom_logger=log)
    out["ncaaw_%s: league's records off beats defaults on" % sport] = \
        drawn(r, game("ncaaw_" + sport)) == []
print(json.dumps(out))
'''

#: plugin -> probe kind
CASES = {
    "afl-scoreboard": "root",
    "nrl-scoreboard": "root",
    "hockey-scoreboard": "hockey:show_shots_on_goal",
    "lacrosse-scoreboard": "lacrosse:show_shots",
}


def find_core():
    for candidate in (os.environ.get("LEDMATRIX_CORE"), REPO.parent / "LEDMatrix"):
        if candidate and (Path(candidate) / "src" / "plugin_system").is_dir():
            return Path(candidate)
    return None


def main():
    core = find_core()
    if core is None:
        print("SKIP: no LEDMatrix core checkout (set LEDMATRIX_CORE)")
        return 2
    env = dict(os.environ, PYTHONPATH=str(core), EMULATOR="true")
    failed = 0
    for plugin, kind in CASES.items():
        # List argv, no shell: this interpreter and paths inside the repo.
        proc = subprocess.run(  # nosec B603  # nosemgrep
            [sys.executable, "-c", PROBE, str(PLUGINS / plugin), kind],
            capture_output=True, text=True, cwd=str(core), env=env)
        try:
            results = json.loads(proc.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            print("FAIL  %s: probe did not run\n%s" % (plugin, proc.stderr[-1500:]))
            failed += 1
            continue
        for label, ok in results.items():
            failed += not ok
            print("%s  %s: %s" % ("PASS" if ok else "FAIL", plugin, label))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
