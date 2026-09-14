#!/usr/bin/env python3
"""Scroll/Vegas card renderer: rank-or-record text, and a bounded logo cache.

1. With show_ranking and show_records both on, an unranked team drew nothing:
   the ranking branch returned '' before records were considered. Most college
   teams are unranked, so most cards lost their records. basketball-scoreboard
   falls back to the record (fd99364); this pins the same rule.

2. The decoded-logo cache was an unbounded dict shared by every renderer the
   scroll display builds. Keys carry the card size, and a college rotation
   reaches hundreds of teams, so it only ever grew (core #559). It is now
   capped, evicting the least recently used entry.

Run: <core-venv>/bin/python plugins/hockey-scoreboard/test_renderer_records_and_logo_cache.py
"""

import logging
import sys
import tempfile
from collections import OrderedDict
from pathlib import Path

from PIL import Image

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

try:
    import game_renderer  # noqa: E402
except ImportError as exc:
    print("SKIP: cannot import game_renderer.py (%s)" % exc)
    sys.exit(2)

GameRenderer = game_renderer.GameRenderer
failures = []


def check(name, ok, detail=None):
    if ok:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s%s" % (name, " -- %r" % (detail,) if detail is not None else ""))
        failures.append(name)


def _renderer(show_ranking, show_records):
    r = object.__new__(GameRenderer)
    r.show_ranking = show_ranking
    r.show_records = show_records
    r._team_rankings_cache = {"BU": 3}
    return r


def main():
    # This plugin's GameRenderer._get_team_display_text(abbr, record) takes two
    # arguments; a static checker resolves the name to a sibling plugin's
    # three-argument renderer and reports a missing show_records.
    # pylint: disable=no-value-for-parameter
    print("rank or record")
    both = _renderer(True, True)
    check("ranked team shows its rank", both._get_team_display_text("BU", "20-4") == "#3")
    check("unranked team falls back to its record",
          both._get_team_display_text("UNH", "10-12") == "10-12",
          both._get_team_display_text("UNH", "10-12"))
    rank_only = _renderer(True, False)
    check("ranking only: unranked team shows nothing",
          rank_only._get_team_display_text("UNH", "10-12") == "")
    records_only = _renderer(False, True)
    check("records only: record shown",
          records_only._get_team_display_text("BU", "20-4") == "20-4")

    print("\nlogo cache is bounded")
    with tempfile.TemporaryDirectory() as tmp:
        logo = Path(tmp) / "logo.png"
        Image.new("RGBA", (40, 40), (255, 0, 0, 255)).save(logo)
        r = object.__new__(GameRenderer)
        r.display_width, r.display_height = 128, 32
        r.logger = logging.getLogger("logo_cache_probe")
        r.logo_dirs = {}
        r._logo_cache = OrderedDict()
        cap = GameRenderer._LOGO_CACHE_MAX
        first = r._load_and_resize_logo("T0", logo, "ncaam_hockey")
        for i in range(1, cap * 3):
            r._load_and_resize_logo("T%d" % i, logo, "ncaam_hockey")
            # Keep T0 in use: least recently used, not first inserted, goes.
            r._load_and_resize_logo("T0", logo, "ncaam_hockey")
        check("cache never exceeds the cap", len(r._logo_cache) <= cap, len(r._logo_cache))
        check("a logo in constant use survives eviction",
              any(k.startswith("ncaam_hockey_T0_") for k in r._logo_cache))
        check("an old unused logo was evicted",
              not any(k.startswith("ncaam_hockey_T1_") for k in r._logo_cache))
        check("a cache hit returns the decoded logo", first is not None)

        plain = object.__new__(GameRenderer)
        plain.display_width, plain.display_height = 128, 32
        plain.logger = r.logger
        plain.logo_dirs = {}
        plain._logo_cache = {}  # what the core scroll display hands in
        for i in range(cap * 2):
            plain._load_and_resize_logo("P%d" % i, logo, "nhl")
        check("a plain dict handed in is bounded too",
              len(plain._logo_cache) <= cap, len(plain._logo_cache))

    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
