#!/usr/bin/env python3
"""AP_TOP_n must resolve from the TOP division's poll, in every copy.

    python3 scripts/test_dynamic_poll_choice.py

## Why this exists

`DynamicTeamResolver` is copied into several plugins, and four of them map a
college football rankings endpoint. Every copy used to take
`data['rankings'][0]` -- "Use first ranking (usually AP)".

"Usually" is the bug. ESPN answers that endpoint with FOUR blocks: AP Top 25,
the AFCA Coaches Poll, the FCS Coaches Poll and the AFCA Division II Coaches
Poll. AP leads today, so the resolver was FBS by luck rather than by choice.
Nothing in the payload promises that order and ESPN demonstrably changes it,
adding the CFP rankings in November.

The consequence is worse here than for the ranked-game filter it was fixed
alongside. A lower-division poll leading makes `AP_TOP_25` resolve to 25 FCS
schools and installs them as the user's FAVOURITE teams -- and favourites are
never filtered by quality or division, so every one of those games reaches the
panel. The user asked for the AP Top 25 and got the FCS Coaches Poll.

Checked behaviourally rather than by reading the source, so a copy that
rewrites the loop still has to answer correctly, plus a source check so no copy
quietly reintroduces the index.
"""
import importlib.util
import logging
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


# Deliberately fronted by the two polls that must never win.
FCS_FIRST = [
    {"name": "FCS Coaches Poll", "type": "fcs", "ranks": [_team("MTST")]},
    {"name": "AFCA Division II Coaches Poll", "type": "afca",
     "ranks": [_team("FRST")]},
    {"name": "AP Top 25", "type": "ap", "ranks": [_team("OSU")]},
    {"name": "AFCA Coaches Poll", "type": "usa", "ranks": [_team("OSU")]},
]


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


class _Requests:
    """Stands in for the module's `requests`, answering with a fixed payload."""

    class exceptions:
        RequestException = Exception

    def __init__(self, payload):
        self._payload = payload

    def get(self, *args, **kwargs):
        return _Response(self._payload)


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    # Under a unique name each: four plugins ship this file, and importing
    # them all as "dynamic_team_resolver" would hand every check the first
    # one loaded -- the exact collision the repo's own guard exists to catch.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _resolver(module):
    """An instance without running __init__.

    The constructors differ across lineages -- some take a cache_manager,
    some take none -- and none of that matters to the poll choice.
    """
    obj = module.DynamicTeamResolver.__new__(module.DynamicTeamResolver)
    obj.logger = logging.getLogger("poll_choice_probe")
    obj.request_timeout = 5
    return obj


def main():
    sources = sorted(PLUGINS.glob("*/dynamic_team_resolver.py"))
    if not sources:
        print("SKIP: no dynamic_team_resolver.py found; the layout changed")
        return 2

    covered = []
    for path in sources:
        text = path.read_text(encoding="utf-8")
        if COLLEGE_FOOTBALL not in text:
            continue
        covered.append(path)
        pid = path.parent.name

        check("%s: no copy takes rankings[0] on trust" % pid,
              "data['rankings'][0]" not in text
              and 'data["rankings"][0]' not in text)

        module = _load(path, "dtr_%s" % pid.replace("-", "_"))
        resolver = _resolver(module)

        chosen = resolver._choose_poll(FCS_FIRST)
        check("%s: the FCS and Division II polls are stepped over" % pid,
              chosen.get("name") == "AP Top 25", chosen.get("name"))

        # ESPN's own order is otherwise kept, so the block it fronts among
        # top-division polls still wins -- that is how the CFP rankings take
        # over from AP in November without a code change.
        reordered = [FCS_FIRST[3], FCS_FIRST[2]]
        check("%s: ESPN's order is otherwise kept" % pid,
              resolver._choose_poll(reordered).get("name") == "AFCA Coaches Poll",
              resolver._choose_poll(reordered).get("name"))

        check("%s: nothing but lower divisions yields no poll" % pid,
              not resolver._choose_poll(FCS_FIRST[:2]))
        check("%s: an empty payload is not an error" % pid,
              not resolver._choose_poll([]) and not resolver._choose_poll(None))

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

    if not covered:
        print("SKIP: no copy maps the college football rankings endpoint")
        return 2

    print()
    print("%d copies checked: %s"
          % (len(covered), ", ".join(p.parent.name for p in covered)))
    failed = [name for name, passed in results if not passed]
    print("%d checks, %d failed" % (len(results), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
