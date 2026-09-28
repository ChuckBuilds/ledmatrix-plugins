#!/usr/bin/env python3
"""
Regression tests: race-weekend data arrives when it happens, not a day later.

1. update() speeds itself up on a race weekend, but the core only called it
   at the static update_interval (an hour) -- there was no
   get_update_interval hook -- so the live check and faster refresh never ran.
2. The latest completed round was read from a 24-hour persistent cache before
   the API, so after a race the round, and everything keyed by it, lagged up
   to a day. It is now fetched when the one-hour memo expires, with the
   persistent copy kept as the offline fallback.
3. The recent-races list was cached under a key without the round (and an
   empty list from a failed fetch was cached for a day too).
4. Qualifying used the latest *completed* round, so Saturday's qualifying for
   the next race did not appear until after Sunday's race.
5. The render path looked the round up through get_latest_round, which can
   fetch; it now uses a value stored by update().

Run: python plugins/f1-scoreboard/test_race_weekend_freshness.py
Exit 0 pass, 1 fail, 2 skip.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    import f1_data  # noqa: E402
except ImportError as exc:
    print(f"SKIP: {exc}")
    sys.exit(2)

results = []


def check(case, passed, detail=""):
    results.append((case, passed))
    print(f"  [{'pass' if passed else 'FAIL'}] {case}" + (f"  <- {detail}" if detail and not passed else ""))


class DictCache:
    def __init__(self):
        self.store = {}

    def get(self, key, max_age=None):
        return self.store.get(key)

    def set(self, key, data, ttl=None):
        self.store[key] = data


def standings(round_num):
    return {"MRData": {"StandingsTable": {"StandingsLists": [{"round": str(round_num)}]}}}


def source(api):
    ds = f1_data.F1DataSource(cache_manager=DictCache())
    ds.requests = []

    def fetch(url, params=None, timeout=30):
        ds.requests.append(url)
        return api(url)
    ds._fetch_json = fetch
    return ds


# --- 2. latest round: the API first, the persistent copy only offline -------
ds = source(lambda url: standings(15) if "driverStandings" in url else None)
ds.cache_manager.store["f1_latest_round_2026"] = 14  # yesterday's answer
check("a fresh lookup asks the API instead of the day-old copy",
      ds._get_latest_round(2026) == 15, ds._get_latest_round(2026))
check("and remembers the new round for the render path",
      ds.cached_latest_round(2026) == 15)
offline = source(lambda url: None)
offline.cache_manager.store["f1_latest_round_2026"] = 14
check("offline, the persistent copy still answers", offline._get_latest_round(2026) == 14)
fresh = source(lambda url: None)
check("cached_latest_round never touches the network",
      fresh.cached_latest_round(2026) == 0 and fresh.requests == [])

# --- 3. recent races keyed by round; failures not cached --------------------
ds = source(lambda url: standings(15) if "driverStandings" in url else None)
ds.fetch_race_results = lambda season, r: {"round": r}
ds.fetch_recent_races(season=2026, count=2)
check("the recent-races cache key names the round",
      any(k.endswith("_r15") for k in ds.cache_manager.store if k.startswith("f1_recent_races")),
      sorted(ds.cache_manager.store))
empty = source(lambda url: standings(15) if "driverStandings" in url else None)
empty.fetch_race_results = lambda season, r: None
empty.fetch_recent_races(season=2026, count=2)
check("an empty list from a failed fetch is not cached",
      not any(k.startswith("f1_recent_races") for k in empty.cache_manager.store))

# --- 4. qualifying looks one round ahead ------------------------------------
def api(url):
    if "driverStandings" in url:
        return standings(15)
    if "/16/qualifying" in url:
        return {"MRData": {"RaceTable": {"Races": [{
            "round": "16", "raceName": "Next GP", "QualifyingResults": [{
                "position": "1", "Driver": {"code": "VER"}, "Constructor": {}}]}]}}}
    if "/15/qualifying" in url:
        return {"MRData": {"RaceTable": {"Races": [{
            "round": "15", "raceName": "Last GP", "QualifyingResults": [{
                "position": "1", "Driver": {"code": "NOR"}, "Constructor": {}}]}]}}}
    return None


ds = source(api)
q = ds.fetch_qualifying(season=2026)
check("Saturday's qualifying for the next race is shown",
      q is not None and str(q.get("round")) == "16", q and q.get("round"))
ds = source(lambda url: api(url) if "/16/" not in url else None)
q = ds.fetch_qualifying(season=2026)
check("before it runs, the last completed round's qualifying is shown",
      q is not None and str(q.get("round")) == "15", q and q.get("round"))

# --- 1. the update-interval hook -------------------------------------------
try:
    from manager import F1ScoreboardPlugin  # noqa: E402
except ImportError:
    print("  (manager needs the LEDMatrix core; hook checks skipped)")
else:
    p = object.__new__(F1ScoreboardPlugin)
    p._live_check_interval, p._is_live, p._is_race_weekend = 120, False, False
    check("off a race weekend the static interval applies", p.get_update_interval() is None)
    p._is_race_weekend = True
    check("on a race weekend update() is called every live check",
          p.get_update_interval() == 120.0)

print()
failed = [c for c, ok in results if not ok]
print(f"{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
