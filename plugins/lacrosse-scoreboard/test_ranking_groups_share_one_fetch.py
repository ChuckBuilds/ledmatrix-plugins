#!/usr/bin/env python3
"""AP_TOP_5, AP_TOP_10 and AP_TOP_25 are one ranking list, not three.

All three patterns resolve from the same poll and differ only in how far down
it they slice. The cache was keyed by PATTERN, though, while the value stored
was the whole list -- so configuring two of them fetched the identical payload
twice, stored it twice, and expired it twice, for no difference in the result.

Seen on a real board: dynamic_teams_ncaa_fb_AP_TOP_10.json and
dynamic_teams_ncaa_fb_AP_TOP_25.json sat side by side in the cache, both
holding the same 25 teams.

Keyed by sport instead, so the poll is fetched once and every group slices the
same cached list.

Run: <core-venv>/bin/python plugins/lacrosse-scoreboard/test_ranking_groups_share_one_fetch.py
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
POLL = ["T%02d" % i for i in range(1, 26)]      # a 25-team poll


def check(case, passed, detail=""):
    results.append((case, passed))
    print("  [%s] %s%s" % ("pass" if passed else "FAIL", case,
                           "" if passed else "  <- " + str(detail)))


class Cache:
    """Just enough cache_manager, and it records what was written."""

    def __init__(self):
        self.store = {}
        self.writes = []

    def get(self, key, *a, **k):
        return self.store.get(key)

    def set(self, key, value, ttl=None, *a, **k):
        self.store[key] = value
        self.writes.append(key)


def main():
    os.chdir(str(CORE))
    from dynamic_team_resolver import DynamicTeamResolver

    patterns = [p for p in DynamicTeamResolver.DYNAMIC_PATTERNS]
    if len(patterns) < 2:
        print("SKIP: this plugin declares fewer than two dynamic patterns")
        return 2

    # Lineages cache differently: some take a cache_manager, some keep a
    # class-level dict. Build whichever this one wants instead of assuming.
    import inspect
    cache = Cache()
    if "cache_manager" in inspect.signature(DynamicTeamResolver.__init__).parameters:
        resolver = DynamicTeamResolver(cache_manager=cache)
        def keys():
            return set(cache.writes)
    else:
        resolver = DynamicTeamResolver()
        type(resolver)._rankings_cache = {}
        def keys():
            return set(type(resolver)._rankings_cache)

    fetches = []
    resolver._fetch_rankings = lambda sport: (fetches.append(sport) or list(POLL))

    resolved = {p: resolver.resolve_teams([p]) for p in patterns}

    # One poll PER SPORT, not one overall: hockey and lacrosse declare groups
    # for several sports at once, and those really are different polls. The
    # defect was several fetches of the SAME sport's poll.
    sports_declared = {DynamicTeamResolver.DYNAMIC_PATTERNS[p]["sport"] for p in patterns}
    check("each sport's poll is fetched exactly once",
          len(fetches) == len(sports_declared) and len(set(fetches)) == len(fetches),
          fetches)
    check("and cached under one key per sport",
          len(keys()) == len(sports_declared), sorted(keys()))
    check("the cache key does not name a pattern",
          not any(p in k for k in keys() for p in patterns), sorted(keys()))

    # The slicing still has to be right, or sharing the fetch bought nothing.
    for pattern, teams in resolved.items():
        want = DynamicTeamResolver.DYNAMIC_PATTERNS[pattern]["limit"]
        check("%s returns %d teams" % (pattern, want), len(teams) == want,
              "got %d" % len(teams))
        check("%s takes them from the top of the poll" % pattern,
              teams == POLL[:want], teams[:3])

    # A second resolver sharing an EXTERNAL cache must not refetch. Lineages
    # that keep a class-level dict pair it with a per-instance freshness stamp,
    # so a new instance refetches by construction -- not something this change
    # governs, so it is not asserted there.
    before = len(fetches)
    shared_cache = "cache_manager" in inspect.signature(
        DynamicTeamResolver.__init__).parameters
    second = DynamicTeamResolver(cache_manager=cache) if shared_cache \
        else DynamicTeamResolver()
    second._fetch_rankings = lambda sport: (fetches.append(sport) or list(POLL))
    again = {p: second.resolve_teams([p]) for p in patterns}
    if shared_cache:
        check("a later resolver reuses the cache", len(fetches) == before, fetches)
    check("and still resolves the same teams", again == resolved)

    failed = [c for c, ok in results if not ok]
    print("\n%d checks, %d failed" % (len(results), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
