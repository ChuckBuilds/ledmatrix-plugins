#!/usr/bin/env python3
"""A postponed or cancelled game is not a final.

ESPN files STATUS_POSTPONED / STATUS_CANCELED / STATUS_SUSPENDED under state
"post" with a score of 0, and the extractor set ``is_final`` from the state
alone. The game then qualified for Recent and was drawn as "Final" with a
0-0 score. These checks pin:

  * only a completed, genuinely played game counts as final;
  * a payload without the ``completed`` flag is still judged on state and name;
  * basketball's period text for such a game is ESPN's own label, not "Final";
  * the shared extractor actually uses the check.

Run: <core-venv>/bin/python plugins/basketball-scoreboard/test_postponed_games_are_not_final.py
"""

import inspect
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


def status(state, name, completed=None, short=""):
    stype = {"state": state, "name": name, "shortDetail": short}
    if completed is not None:
        stype["completed"] = completed
    return {"type": stype, "period": 0, "displayClock": "0:00"}


def main():
    os.chdir(str(CORE))
    import sports
    import basketball

    final = sports._status_is_final
    check("a completed final is final",
          final(status("post", "STATUS_FINAL", completed=True)))
    check("a final without the completed flag is still final",
          final(status("post", "STATUS_FINAL")))
    for name in ("STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_SUSPENDED"):
        check("%s is not final" % name,
              not final(status("post", name, completed=False)))
        check("%s is not final even without the completed flag" % name,
              not final(status("post", name)))
    check("completed: false is not final",
          not final(status("post", "STATUS_FINAL", completed=False)))
    check("a live game is not final", not final(status("in", "STATUS_IN_PROGRESS")))
    check("garbage is not final", not final(None) and not final({"type": None}))

    source = inspect.getsource(sports.SportsCore._extract_game_details_common)
    check("the shared extractor derives is_final from _status_is_final",
          '"is_final": _status_is_final(status)' in source)

    class Stub(basketball.Basketball):
        def __init__(self, st):
            self.logger = logging.getLogger("test")
            self._st = st

        def _extract_game_details_common(self, game_event):
            details = {"id": "1", "home_abbr": "BOS", "away_abbr": "NY",
                       "is_live": False, "is_upcoming": False,
                       "is_final": sports._status_is_final(self._st)}
            return details, {}, {}, self._st, None

        # Abstract on the base classes; nothing under test reaches them.
        def _fetch_data(self):  # pragma: no cover
            raise NotImplementedError

        def _custom_scorebug_layout(self, game, draw):  # pragma: no cover
            raise NotImplementedError

    postponed = Stub(status("post", "STATUS_POSTPONED", completed=False,
                            short="Postponed"))._extract_game_details({})
    check("a postponed game is extracted as not final",
          postponed is not None and postponed["is_final"] is False)
    check("its period text is ESPN's label, not Final",
          postponed is not None and postponed["period_text"] == "Postponed")
    check("so the recent list's 'appears finished' fallback does not catch it",
          postponed is not None and "final" not in postponed["period_text"].lower()
          and postponed["period"] < 4)

    played = Stub(status("post", "STATUS_FINAL", completed=True,
                         short="Final"))._extract_game_details({})
    check("a played game still reads Final",
          played is not None and played["is_final"] and played["period_text"] == "Final")

    failed = [c for c, ok in results if not ok]
    print("\n%d checks, %d failed" % (len(results), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
