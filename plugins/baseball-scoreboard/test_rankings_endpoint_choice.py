#!/usr/bin/env python3
"""College rankings must come from the endpoint that actually has them.

`fetch_standings` used to try /standings first and fall back to /rankings only
on a 404. College football answers /standings with **HTTP 200** and no
"rankings" key, so the fallback never fired and the poll was never fetched.

Nothing failed. `_fetch_team_rankings` just parsed a body with no rankings in
it, cached an empty table, and every consumer quietly did nothing: the AP rank
badge never appeared however `show_ranking` was set, and the "ranked" quality
filter passed every game because an empty table fails open.

Verified against the live API on 2026-08-27:

    football/college-football/standings -> 200, no "rankings" key
    football/college-football/rankings  -> 200, 3 ranking blocks
    football/nfl/standings              -> 200
    football/nfl/rankings               -> 404

So the endpoint has to be chosen by league, not discovered by error code.

Run: <core-venv>/bin/python plugins/baseball-scoreboard/test_rankings_endpoint_choice.py
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

results = []
POLL = {"rankings": [{"ranks": [{"current": 1}]}]}
STANDINGS = {"children": [{"standings": {"entries": []}}]}


def check(case, passed, detail=""):
    results.append((case, passed))
    print("  [%s] %s%s" % ("pass" if passed else "FAIL", case,
                           "" if passed else "  <- " + str(detail)))


class Response:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            err = requests.HTTPError("%s" % self.status_code)
            err.response = self
            raise err


class Session:
    """Answers like ESPN does: both endpoints 200 for college, /rankings 404
    for the professional leagues."""

    def __init__(self, college):
        self.college = college
        self.urls = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        if url.endswith("/rankings"):
            return Response(200, POLL) if self.college else Response(404, {})
        return Response(200, STANDINGS)


def main():
    os.chdir(str(CORE))
    import logging
    from data_sources import ESPNDataSource

    src = ESPNDataSource(logging.getLogger("endpoint_probe"))

    print("a college league must reach the poll")
    src.session = Session(college=True)
    data = src.fetch_standings("football", "college-football")
    check("the poll is returned", data.get("rankings") == POLL["rankings"], data)
    check("a poll-less 200 from /standings does not win",
          data is not STANDINGS and "children" not in data, list(data))
    check("/rankings was actually requested",
          any(u.endswith("/rankings") for u in src.session.urls), src.session.urls)

    print("\na professional league still gets its standings")
    src.session = Session(college=False)
    data = src.fetch_standings("football", "nfl")
    check("standings are returned", "children" in data, list(data))
    check("and /standings was tried first",
          src.session.urls and src.session.urls[0].endswith("/standings"),
          src.session.urls)

    print("\nncaa-style league names are treated as college too")
    src.session = Session(college=True)
    data = src.fetch_standings("basketball", "mens-college-basketball")
    check("poll returned for a college basketball league",
          data.get("rankings") == POLL["rankings"], list(data))

    print("\nnothing available anywhere is an empty dict, not a crash")

    class Dead(Session):
        def get(self, url, **kwargs):
            self.urls.append(url)
            return Response(404, {})

    src.session = Dead(college=True)
    check("returns {}", src.fetch_standings("football", "college-football") == {})

    print("\na 200 /rankings with no poll in it counts as a miss")

    class Empty(Session):
        def get(self, url, **kwargs):
            self.urls.append(url)
            if url.endswith("/rankings"):
                return Response(200, {"rankings": []})
            return Response(200, STANDINGS)

    src.session = Empty(college=True)
    data = src.fetch_standings("football", "college-football")
    check("falls through to standings", "children" in data, list(data))

    failed = [c for c, ok in results if not ok]
    print("\n%d checks, %d failed" % (len(results), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
