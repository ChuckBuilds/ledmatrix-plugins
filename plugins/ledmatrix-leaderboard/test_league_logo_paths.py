#!/usr/bin/env python3
"""League logos: named as the core ships them, and a miss warned about once.

The Pi's filesystem is case-sensitive. league_config named ``nfl.png``,
``mlb.png``, ``nhl.png`` and ``nba.png`` while the core ships ``NFL.png`` and
friends (its lowercase copies went in core 3.3.0, #506), so on a Pi those
leagues drew a blank logo column -- and because a missing file is never
cached, the warning came back on every rebuild. A Windows checkout found the
files regardless, which is why nobody saw it off the Pi.

The path check compares against os.listdir(), not os.path.exists(), so it
fails on a case-insensitive filesystem too. It needs a core checkout
(LEDMATRIX_CORE, the working directory, or ../LEDMatrix next to this repo)
and is skipped without one; the warning check runs anywhere.

Run: python3 plugins/ledmatrix-leaderboard/test_league_logo_paths.py
"""

import logging
import os
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))

try:
    from PIL import Image  # noqa: F401
except ImportError:
    print("SKIP: Pillow not installed")
    sys.exit(2)

import image_renderer as ir  # noqa: E402
from league_config import LeagueConfig  # noqa: E402

#: Leagues the core has no logo for. The path stays a drop-in: a file added
#: there is drawn. Anything else must name a file the core ships.
UNSHIPPED_LEAGUE_LOGOS = {"ncaa_baseball"}

failures = []


def check(name, cond, detail=""):
    if cond:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s%s" % (name, (": " + detail) if detail else ""))
        failures.append(name)


def core_checkout():
    for candidate in (os.environ.get("LEDMATRIX_CORE", ""), os.getcwd(),
                      str(PLUGIN_DIR.parents[2] / "LEDMatrix")):
        if candidate and (Path(candidate) / "assets" / "sports").is_dir():
            return Path(candidate)
    return None


def shipped_exactly(root, rel):
    """True only when every path component matches an entry's exact case."""
    current = root
    for part in rel.split("/"):
        try:
            if part not in os.listdir(current):
                return False
        except OSError:
            return False
        current = current / part
    return True


class _Records(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)


def test_missing_logo_warns_once_per_path():
    print("missing league logo is warned about once, not every rebuild")
    logger = logging.getLogger("test_league_logo_paths")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    handler = _Records()
    logger.addHandler(handler)
    try:
        renderer = ir.ImageRenderer(32, logger)
        data = [
            {"league": "nfl", "league_config": {"league_logo": "no/such/nfl.png"}, "teams": []},
            {"league": "mlb", "league_config": {"league_logo": "no/such/mlb.png"}, "teams": []},
        ]
        for _ in range(3):  # three rebuilds
            renderer._build_layout(data)
    finally:
        logger.removeHandler(handler)

    warnings = [r.getMessage() for r in handler.records
                if r.levelno >= logging.WARNING and "League logo" in r.getMessage()]
    check("one warning per missing path across three rebuilds", len(warnings) == 2,
          "got %d: %r" % (len(warnings), warnings))
    check("each warning names its path",
          any("no/such/nfl.png" in w for w in warnings)
          and any("no/such/mlb.png" in w for w in warnings), repr(warnings))
    later = [r for r in handler.records
             if r.levelno == logging.DEBUG and "still missing" in r.getMessage()]
    check("later misses drop to debug", len(later) == 4, "got %d" % len(later))


def test_league_logos_are_shipped_with_exact_case(core):
    print("every league logo names a file the core ships, spelled exactly")
    leagues = LeagueConfig({}, logging.getLogger("test_league_logo_paths")).league_configs
    for key, league in sorted(leagues.items()):
        path = league.get("league_logo")
        if key in UNSHIPPED_LEAGUE_LOGOS:
            continue
        check("%s: %s" % (key, path), bool(path) and shipped_exactly(core, path),
              "not in %s with this exact case" % core)
    check("the unshipped list names real leagues",
          UNSHIPPED_LEAGUE_LOGOS <= set(leagues), repr(UNSHIPPED_LEAGUE_LOGOS - set(leagues)))
    march = ir.ImageRenderer.MARCH_MADNESS_LOGO_PATH
    check("March Madness: %s" % march, shipped_exactly(core, march))


def main():
    test_missing_logo_warns_once_per_path()
    core = core_checkout()
    if core is None:
        print("  SKIP  league logo paths: no LEDMatrix core checkout")
    else:
        test_league_logos_are_shipped_with_exact_case(core)

    if failures:
        print("\n%d failure(s)" % len(failures))
        return 1
    print("\nall passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
