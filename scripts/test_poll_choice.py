#!/usr/bin/env python3
"""A rank badge must read a POLL, in every copy that reads one.

    python3 scripts/test_poll_choice.py

## Why this exists

Two copied helpers ask ESPN's /rankings endpoint which teams are ranked, and
both used to take the first block in the response:

    ranking = data['rankings'][0]   # Use first ranking (usually AP)

"Usually" is the bug. That endpoint returns SEVERAL blocks and the first is not
promised to be a poll at all. Verified live:

    hockey/mens-college-hockey          [NCAA Tournament Seedings, USCHO Poll]
    hockey/womens-college-hockey        [NCAA Tournament Seedings, USCHO Poll]
    lacrosse/mens-college-lacrosse      [Inside Lacrosse Poll, Tournament Seedings]
    basketball/mens-college-basketball  [AP Top 25, Coaches Poll]
    football/college-football           [AP, AFCA Coaches, FCS, AFCA Div II]

So college hockey's badge drew a 16-team BRACKET SEED where a viewer expects a
poll position, and college football was FBS only by luck -- with the FCS poll
fronted, `AP_TOP_25` resolves to 25 FCS schools and installs them as FAVOURITE
teams, which are never filtered by quality or division.

`SportsCore._choose_poll` and `DynamicTeamResolver._choose_poll` keep ESPN's
own order among genuine top-division polls and step over the rest, so the block
ESPN fronts still wins whenever it is a real poll -- that is how the CFP
rankings take over from AP in November without a code change.

Checked behaviourally, so a copy that rewrites the loop still has to answer
correctly, plus a source check so no copy quietly reintroduces the index.

The sports.py half imports the plugin, which pulls in the LEDMatrix core; it
skips cleanly when the core is absent rather than reporting success without
having checked anything.
"""
import importlib.util
import logging
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUGINS = REPO / "plugins"

# The endpoint whose payload carries polls for more than one division.
COLLEGE_FOOTBALL = "football/college-football/rankings"

results = []


def check(case, passed, detail=""):
    results.append((case, passed))
    print("  [%s] %s%s" % ("pass" if passed else "FAIL", case,
                           "" if passed else "  <- " + str(detail)))


def _team(abbr):
    return {"team": {"abbreviation": abbr, "id": abbr}, "current": 1}


# Shaped like the live college football payload, fronted by the two blocks
# that must never win.
FCS_FIRST = [
    {"name": "FCS Coaches Poll", "type": "fcs", "ranks": [_team("MTST")]},
    {"name": "AFCA Division II Coaches Poll", "type": "afca",
     "ranks": [_team("FRST")]},
    {"name": "AP Top 25", "type": "ap", "ranks": [_team("OSU")]},
    {"name": "AFCA Coaches Poll", "type": "usa", "ranks": [_team("OSU")]},
]

# Shaped like the live college hockey payload: seedings first, poll second.
SEEDINGS_FIRST = [
    {"name": "NCAA Men's Hockey Tournament Seedings", "type": "tournament",
     "ranks": [_team("SEED1")]},
    {"name": "USCHO Men's Poll", "type": "USCHOMENSPOLL",
     "ranks": [_team("BC")]},
]


def _core_dir():
    for candidate in (os.environ.get("LEDMATRIX_CORE", ""),
                      str(REPO.parent / "LEDMatrix"),
                      str(Path.home() / "projects" / "LEDMatrix")):
        if candidate and (Path(candidate) / "assets" / "fonts").is_dir():
            return candidate
    return None


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


class _Standings:
    """Stands in for the plugin's data source, answering with a fixed payload."""

    def __init__(self, payload):
        self._payload = payload

    def fetch_standings(self, sport, league):
        return self._payload


class _Requests:
    """Stands in for a module's `requests`, answering with a fixed payload."""

    class exceptions:
        RequestException = Exception

    def __init__(self, payload):
        self._payload = payload

    def get(self, *args, **kwargs):
        return _Response(self._payload)


def _load(path, name, extra_path=None):
    """Import one plugin's module under a unique name.

    Every lineage ships these files under the SAME bare name, so they are
    loaded as `sports_<plugin>` with the plugin's own directory at the front
    of sys.path and the bare names purged first. Without that, each plugin
    after the first would silently be handed the previous one's modules --
    the exact collision the repo's own guard exists to catch, and it would
    make this file report a pass for code it never loaded.
    """
    for bare in ("sports", "dynamic_team_resolver", "logo_downloader",
                 "data_sources", "football", "base_odds_manager"):
        sys.modules.pop(bare, None)
    added = [p for p in (extra_path, str(path.parent)) if p]
    for entry in added:
        sys.path.insert(0, entry)
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        for entry in added:
            if entry in sys.path:
                sys.path.remove(entry)


def _resolver(module):
    """An instance without running __init__.

    The constructors differ across lineages -- some take a cache_manager,
    some take none -- and none of that matters to the poll choice.
    """
    obj = module.DynamicTeamResolver.__new__(module.DynamicTeamResolver)
    obj.logger = logging.getLogger("poll_choice_probe")
    obj.request_timeout = 5
    return obj


def _check_chooser(label, chooser):
    """The four answers every copy owes, whichever helper it lives in."""
    check("%s: tournament seedings are not a poll" % label,
          chooser(SEEDINGS_FIRST).get("name") == "USCHO Men's Poll",
          chooser(SEEDINGS_FIRST).get("name"))
    check("%s: lower-division polls are stepped over" % label,
          chooser(FCS_FIRST).get("name") == "AP Top 25",
          chooser(FCS_FIRST).get("name"))
    check("%s: ESPN's order is otherwise kept" % label,
          chooser(FCS_FIRST[3:] + FCS_FIRST[2:3]).get("name")
          == "AFCA Coaches Poll",
          chooser(FCS_FIRST[3:] + FCS_FIRST[2:3]).get("name"))
    check("%s: nothing usable is empty, not an error" % label,
          not chooser([]) and not chooser(None)
          and not chooser(SEEDINGS_FIRST[:1]))


def _check_resolvers():
    print("dynamic_team_resolver.py: AP_TOP_n slices a top-division poll")
    covered = []
    for path in sorted(PLUGINS.glob("*/dynamic_team_resolver.py")):
        text = path.read_text(encoding="utf-8")
        if COLLEGE_FOOTBALL not in text:
            continue
        pid = path.parent.name
        covered.append(pid)

        check("%s: does not take rankings[0] on trust" % pid,
              "data['rankings'][0]" not in text
              and 'data["rankings"][0]' not in text)

        module = _load(path, "dtr_%s" % pid.replace("-", "_"))
        resolver = _resolver(module)
        _check_chooser(pid, resolver._choose_poll)

        # End to end, which is what the user actually gets: the abbreviations
        # AP_TOP_n slices must come from the AP block, not the FCS one.
        original = getattr(module, "requests", None)
        module.requests = _Requests({"rankings": FCS_FIRST})
        try:
            teams = resolver._fetch_rankings("ncaa_fb")
        finally:
            if original is not None:
                module.requests = original
        check("%s: AP_TOP_n resolves to the AP teams, not the FCS ones" % pid,
              teams == ["OSU"], teams)
    print("  (%d copies: %s)" % (len(covered), ", ".join(covered)))
    return covered


def _check_sports(core):
    print()
    print("sports.py: the rank badge reads a poll, never a bracket seed")
    if not core:
        print("  SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
        return []
    covered = []
    for path in sorted(PLUGINS.glob("*/sports.py")):
        text = path.read_text(encoding="utf-8")
        if "def _fetch_team_rankings" not in text:
            continue
        pid = path.parent.name
        covered.append(pid)

        check("%s: does not take rankings[0] on trust" % pid,
              "rankings_data[0]" not in text
              and 'data["rankings"][0]' not in text)

        module = _load(path, "sports_%s" % pid.replace("-", "_"), core)
        # SportsCore is an ABC and the lineages do not declare the same
        # abstract methods, so the stubs are derived from the class rather
        # than named here. None of them is reached by the poll choice.
        base = module.SportsCore
        stubs = dict((name, lambda self, *a, **k: None)
                     for name in getattr(base, "__abstractmethods__", ()))
        probe_cls = type("PollProbe", (base,), stubs)
        probe = probe_cls.__new__(probe_cls)
        probe.logger = logging.getLogger("poll_choice_probe")
        probe.league = pid
        probe.sport = pid
        _check_chooser(pid, probe._choose_poll)

        # Through _fetch_team_rankings, not just the helper. Checking
        # _choose_poll alone passed against a copy whose call site still read
        # rankings[0] -- the helper was intact and simply unused, which is
        # precisely the state this guard exists to prevent.
        probe._team_rankings_cache = {}
        probe._ranked_team_ids = {}
        probe._rankings_cache_timestamp = 0
        probe._rankings_cache_duration = 3600
        probe.data_source = _Standings({"rankings": SEEDINGS_FIRST})
        table = probe._fetch_team_rankings()
        check("%s: the badge table is built from the poll" % pid,
              table == {"BC": 1}, table)
    print("  (%d copies: %s)" % (len(covered), ", ".join(covered)))
    return covered


def main():
    resolvers = _check_resolvers()
    sports = _check_sports(_core_dir())
    if not resolvers and not sports:
        print("SKIP: nothing to check; the layout changed")
        return 2

    print()
    failed = [name for name, passed in results if not passed]
    print("%d checks, %d failed" % (len(results), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
