#!/usr/bin/env python3
"""One league failing to initialise must not take the others down.

_initialize_managers built all four leagues inside a single try. A league
whose manager raised skipped every league after it and left its own
attributes unset, so update() -- which reads self.<league>_live directly --
raised AttributeError on every tick for the rest of the process. These checks
pin, with the manager classes swapped for stand-ins:

  * a league whose constructor raises gets None for all three managers;
  * the leagues after it are still built;
  * update() skips the failed league and still updates the others.

Run: <core-venv>/bin/python plugins/basketball-scoreboard/test_one_failing_league_keeps_the_rest.py
"""

import os
import sys
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

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

results = []


def check(case, passed):
    results.append((case, passed))
    print("  [%s] %s" % ("pass" if passed else "FAIL", case))


updated = []


class _Broken:
    def __init__(self, *a, **k):
        raise ValueError("bad config value")


def _working(label):
    class _Mgr:
        def __init__(self, *a, **k):
            self.label = label

        def update(self):
            updated.append(self.label)
    return _Mgr


def main():
    os.chdir(str(CORE))
    import manager as plugin_manager

    # NBA is first in the build order, so under the old single try it took
    # every other league with it.
    plugin_manager.NBALiveManager = _Broken
    plugin_manager.NBARecentManager = _working("nba-recent")
    plugin_manager.NBAUpcomingManager = _working("nba-upcoming")
    plugin_manager.WNBALiveManager = _working("wnba-live")
    plugin_manager.WNBARecentManager = _working("wnba-recent")
    plugin_manager.WNBAUpcomingManager = _working("wnba-upcoming")

    cls = plugin_manager.BasketballScoreboardPlugin
    plugin = cls.__new__(cls)
    plugin.logger = logging.getLogger("test")
    plugin.display_manager = None
    plugin.cache_manager = None
    plugin.nba_enabled = True
    plugin.wnba_enabled = True
    plugin.ncaam_enabled = False
    plugin.ncaaw_enabled = False
    plugin._adapt_config_for_manager = lambda league: {}

    plugin._initialize_managers()
    check("the failed league's managers are all None",
          all(getattr(plugin, "nba_%s" % m, "unset") is None
              for m in ("live", "recent", "upcoming")))
    check("the league after it is still built",
          all(getattr(plugin, "wnba_%s" % m, None) is not None
              for m in ("live", "recent", "upcoming")))

    plugin.is_enabled = True
    plugin._check_favorite_teams = lambda: None
    try:
        plugin.update()
        raised = None
    except Exception as exc:  # pragma: no cover - the regression
        raised = exc
    check("update() does not raise with a failed league", raised is None)
    check("update() still updates the working league",
          sorted(updated) == ["wnba-live", "wnba-recent", "wnba-upcoming"])

    failed = [c for c, ok in results if not ok]
    print("\n%d checks, %d failed" % (len(results), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
