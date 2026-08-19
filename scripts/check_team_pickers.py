#!/usr/bin/env python3
"""
Check (or regenerate) the team pickers in plugin config schemas against ESPN.

A ``favorite_teams`` picker is a hand-maintained copy of a league's roster, and
rosters change: a club is renamed, relocated, or added. When the copy drifts the
failure is invisible in the worst way — the picker simply does not offer a team
that exists, or offers a code that no longer matches anything, and the user gets
an empty screen with no error. odds-ticker's NHL list had both problems at once:
it still listed ``UTA`` under the club's former name, and omitted the Seattle
Kraken entirely so they could not be selected at all.

Two kinds of difference, treated differently:

* **enum** — which codes exist. A mismatch here is a bug, so it fails.
* **labels** — the display names. ESPN's own text is sometimes worse than the
  hand-written label ("LA Clippers" against "Los Angeles Clippers"), so a
  mismatch only warns and is never rewritten unless asked for.

Usage::

    python scripts/check_team_pickers.py              # check, non-zero on drift
    python scripts/check_team_pickers.py --apply      # rewrite the enums
    python scripts/check_team_pickers.py --apply --labels
"""

import argparse
import json
import os
import sys
import urllib.request

TEAMS_URL = "https://site.api.espn.com/apis/site/v2/sports/{path}/teams?limit=1000"

# ESPN sport/league path for each league key a picker may be keyed by. A picker
# whose league key is not listed here is reported as unknown rather than skipped
# silently, so adding a new league cannot quietly opt out of the check.
LEAGUE_PATHS = {
    "nfl": "football/nfl",
    "ncaa_fb": "football/college-football",
    "nba": "basketball/nba",
    "wnba": "basketball/wnba",
    "ncaam": "basketball/mens-college-basketball",
    "ncaaw": "basketball/womens-college-basketball",
    "mlb": "baseball/mlb",
    "ncaa_baseball": "baseball/college-baseball",
    "nhl": "hockey/nhl",
    "ncaa_mens": "hockey/mens-college-hockey",
    "ncaa_womens": "hockey/womens-college-hockey",
    "afl": "australian-football/afl",
    "nrl": "rugby-league/3",
}

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def fetch_teams(path):
    """ESPN's {abbreviation: display name}. ``limit=1000`` is not optional here:
    the default page size truncates the NCAA rosters to about half."""
    url = TEAMS_URL.format(path=path)
    # The league path is interpolated into the URL, so pin the scheme rather
    # than trusting the result: urlopen would honour file:// or a custom scheme
    # if a path ever arrived from somewhere less trustworthy than the table above.
    if not url.startswith("https://"):
        raise ValueError("refusing to fetch a non-HTTPS URL: {!r}".format(url))
    # nosec B310 - the scheme is pinned to https by the check above; B310 is a
    # syntactic blacklist rule and fires on the call regardless of the guard.
    with urllib.request.urlopen(url, timeout=45) as response:  # nosec B310
        payload = json.load(response)
    entries = payload["sports"][0]["leagues"][0]["teams"]
    return {
        t["team"]["abbreviation"]: t["team"]["displayName"]
        for t in entries if t.get("team", {}).get("abbreviation")
    }


def find_pickers(schema):
    """Yield (league_key, node) for each favorite_teams checkbox-group."""
    def walk(node, trail):
        if isinstance(node, dict):
            if (node.get("x-widget") == "checkbox-group"
                    and trail and trail[-1] == "favorite_teams"):
                # Usually .../<league>/properties/favorite_teams, but hockey
                # and lacrosse group theirs one level deeper, under
                # .../<league>/properties/teams/properties/favorite_teams.
                # Taking a fixed offset reported that as league "teams", so
                # walk back to the nearest segment that names a league.
                league = next(
                    (part for part in reversed(trail) if part in LEAGUE_PATHS),
                    trail[-3] if len(trail) >= 3 else None)
                yield league, node
            for key, value in node.items():
                for hit in walk(value, trail + [key]):
                    yield hit
        elif isinstance(node, list):
            for value in node:
                for hit in walk(value, trail):
                    yield hit

    for league, node in walk(schema, []):
        yield league, node


def enum_of(node):
    items = node.get("items") or {}
    return items.get("enum") if "enum" in items else node.get("enum")


def set_enum(node, values):
    items = node.get("items")
    if isinstance(items, dict) and "enum" in items:
        items["enum"] = values
    else:
        node["enum"] = values


def rewrite(path, mutate):
    """Rewrite a schema in place, preserving its existing escaping style.

    Reformatting a whole schema to fix three lines buries the change in hundreds
    of lines of churn, so keep ``ensure_ascii`` as the file already had it.
    """
    with open(path, "r", encoding="utf-8") as fh:
        raw = fh.read()
    schema = json.loads(raw)
    mutate(schema)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(schema, fh, indent=2, ensure_ascii="\\u" in raw)
        fh.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="rewrite the enums to match ESPN")
    parser.add_argument("--labels", action="store_true",
                        help="with --apply, also overwrite labels with ESPN's text")
    parser.add_argument("--plugin", help="check only this plugin id")
    args = parser.parse_args()

    plugins_dir = os.path.join(ROOT, "plugins")
    schemas = []
    for plugin in sorted(os.listdir(plugins_dir)):
        if args.plugin and plugin != args.plugin:
            continue
        path = os.path.join(plugins_dir, plugin, "config_schema.json")
        if os.path.exists(path):
            schemas.append((plugin, path))

    rosters = {}
    problems = []
    warnings = []
    # Problems that --apply can never fix (an unknown league key has no roster
    # to regenerate the enum from), tracked separately so they cannot be
    # silently dropped from --apply's output just because they never made it
    # into `pending`.
    unresolved = []
    checked = 0
    pending = {}

    for plugin, path in schemas:
        with open(path, encoding="utf-8") as fh:
            schema = json.load(fh)

        for league, node in find_pickers(schema):
            enum = enum_of(node)
            if enum is None:
                continue
            checked += 1
            where = "{}: {}".format(plugin, league)

            espn_path = LEAGUE_PATHS.get(league)
            if not espn_path:
                msg = "{} - unknown league key; add it to LEAGUE_PATHS".format(where)
                problems.append(msg)
                unresolved.append(msg)
                continue

            if espn_path not in rosters:
                try:
                    rosters[espn_path] = fetch_teams(espn_path)
                except Exception as exc:
                    warnings.append("{} - could not reach ESPN ({})".format(where, exc))
                    rosters[espn_path] = None
            live = rosters[espn_path]
            if not live:
                if live is not None:
                    # Fetch succeeded but returned no teams (e.g. ESPN entries
                    # missing 'abbreviation', or an API shape change) — distinct
                    # from the connectivity failure above, which already warned.
                    warnings.append(
                        "{} - ESPN returned no teams for this league".format(where))
                continue

            labels = (node.get("x-options") or {}).get("labels") or {}
            unreal = [c for c in enum if c not in live]
            missing = [c for c in live if c not in enum]
            unlabelled = [c for c in enum if c not in labels]
            mislabelled = {c: (labels[c], live[c]) for c in enum
                           if c in live and c in labels and labels[c] != live[c]}

            if unreal:
                problems.append(
                    "{} - offers {} which ESPN does not have: {}".format(
                        where, len(unreal), ", ".join(sorted(unreal))))
            if missing:
                problems.append(
                    "{} - cannot select {} real team(s): {}".format(
                        where, len(missing),
                        ", ".join("{} ({})".format(c, live[c])
                                  for c in sorted(missing))))
            if unlabelled:
                problems.append("{} - no label for: {}".format(
                    where, ", ".join(sorted(unlabelled))))
            for code, (was, now) in sorted(mislabelled.items()):
                warnings.append("{} - {} is labelled {!r}, ESPN says {!r}".format(
                    where, code, was, now))

            if unreal or missing or unlabelled:
                print("  DRIFT  {}".format(where))
                pending.setdefault(path, []).append((league, espn_path))
            elif mislabelled:
                # Cosmetic only, so do not call it drift and do not fail on it.
                print("  OK*    {} ({} teams, {} label(s) differ from ESPN)"
                      .format(where, len(enum), len(mislabelled)))
            else:
                print("  OK     {} ({} teams)".format(where, len(enum)))

    if args.apply and pending:
        for path, entries in pending.items():
            def mutate(schema, entries=entries):
                for league, espn_path in entries:
                    live = rosters.get(espn_path) or {}
                    if not live:
                        continue
                    for found_league, node in find_pickers(schema):
                        if found_league != league:
                            continue
                        set_enum(node, sorted(live))
                        options = node.setdefault("x-options", {})
                        existing = options.setdefault("labels", {})
                        # Keep hand-written labels unless asked otherwise; only
                        # fill in the ones that are missing entirely.
                        merged = {}
                        for code in sorted(live):
                            if args.labels or code not in existing:
                                merged[code] = live[code]
                            else:
                                merged[code] = existing[code]
                        options["labels"] = merged
            rewrite(path, mutate)
            print("  rewrote {}".format(os.path.relpath(path, ROOT)))
        print("\nEnums regenerated. Bump the affected plugin versions before committing.")
        for warning in warnings:
            print("  warn   {}".format(warning))
        if unresolved:
            print("\n{} problem(s) could not be regenerated automatically:"
                  .format(len(unresolved)))
            for problem in unresolved:
                print("  - {}".format(problem))
            return 1
        return 0

    for warning in warnings:
        print("  warn   {}".format(warning))
    if problems:
        print("\n{} problem(s) across {} picker(s):".format(len(problems), checked))
        for problem in problems:
            print("  - {}".format(problem))
        print("\nRun with --apply to regenerate the enums from ESPN.")
        return 1

    print("\nOK: {} picker(s) match ESPN.".format(checked))
    return 0


if __name__ == "__main__":
    sys.exit(main())
