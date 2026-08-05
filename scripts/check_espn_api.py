#!/usr/bin/env python3
"""
Probe every shape of ESPN request this repo makes, and say what is actually wrong.

ESPN has no public API. Every endpoint the scoreboards use is undocumented and
can change without notice, so "the ESPN plugins went blank" is a report we get
periodically and can rarely act on: it arrives as a symptom, and the interesting
question — *which* part broke — needs a machine that can reach ESPN to answer.
This script is that answer. Run it from a host with normal internet access (a
Pi running LEDMatrix, a laptop) and it reports, per endpoint, whether ESPN still
serves what the plugins expect.

The important trick is the second axis. The plugins do not speak to ESPN with one
voice; they send three different ``User-Agent`` values depending on which file
happens to make the call:

* ``python-urllib`` / ``python-requests`` — the stdlib or requests default, sent
  by every caller that passes no headers at all (odds-ticker's data_fetcher, most
  of the ``*_managers.py``, every ``base_odds_manager.py``, this repo's own
  check_team_pickers.py).
* ``LEDMatrix/1.0`` — the custom agent set by the ``data_sources.py`` family.
* a browser string — what a handful of files already send, and what ESPN's own
  site sends.

Anti-bot filtering is the most common way an undocumented API "changes", and it
discriminates on exactly that header. So each endpoint is tried under all three
profiles. That turns an ambiguous outage into a diagnosis:

* every profile fails  -> ESPN moved or withdrew the endpoint; the URL needs work.
* only the non-browser profiles fail -> ESPN is filtering on User-Agent, and the
  fix is a header change, not a URL change.
* everything passes -> ESPN is fine; look at the plugin, the cache, or the
  network in front of it.

Usage::

    python scripts/check_espn_api.py              # probe, non-zero exit if broken
    python scripts/check_espn_api.py --verbose    # show every profile's result
    python scripts/check_espn_api.py --json       # machine-readable report
    python scripts/check_espn_api.py --timeout 30
"""

import argparse
import datetime
import json
import ssl
import sys
import urllib.error
import urllib.request

# The distinct endpoint families the plugins call. Each entry is
# (label, url, key that must be present and non-empty in the JSON response).
#
# "expect" is what makes this a contract test rather than a ping: ESPN can return
# a cheerful 200 whose body no longer holds the field the renderer reads, and a
# status-code-only check would call that healthy.
TODAY = datetime.date.today().strftime("%Y%m%d")

ENDPOINTS = [
    (
        "site.api scoreboard (MLB)",
        "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard",
        "events",
    ),
    (
        "site.api scoreboard w/ dates (NFL)",
        "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
        f"?dates={TODAY}&limit=1000",
        "leagues",
    ),
    (
        "site.api scoreboard (NCAA FB, groups)",
        "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"
        "?groups=80&limit=1000",
        "leagues",
    ),
    (
        "site.api teams (NHL)",
        "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/teams?limit=1000",
        "sports",
    ),
    (
        "site.api rankings (NCAA FB)",
        "https://site.api.espn.com/apis/site/v2/sports/football/college-football/rankings",
        "rankings",
    ),
    (
        "site.api standings v2 (NBA)",
        "https://site.api.espn.com/apis/v2/sports/basketball/nba/standings",
        None,
    ),
    (
        "site.web.api scoreboard header (cricket)",
        "https://site.web.api.espn.com/apis/v2/scoreboard/header?sport=cricket",
        "sports",
    ),
    (
        "site.web.api common v3 (golf athlete)",
        "https://site.web.api.espn.com/apis/common/v3/sports/golf/pga/athletes/9478",
        None,
    ),
    (
        "sports.core.api league (NFL)",
        "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl",
        None,
    ),
    (
        "site.api soccer scoreboard (EPL)",
        "https://site.api.espn.com/apis/site/v2/sports/soccer/eng.1/scoreboard",
        "leagues",
    ),
]

# The three voices the plugins actually use. Order matters: the browser profile
# is last so a "browser works, ours do not" split is easy to read off the table.
PROFILES = [
    ("default", {}),
    ("LEDMatrix/1.0", {"User-Agent": "LEDMatrix/1.0", "Accept": "application/json"}),
    (
        "browser",
        {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
        },
    ),
]


def probe(url, headers, timeout):
    """Fetch url and return a result dict. Never raises."""
    request = urllib.request.Request(url)
    for name, value in headers.items():
        request.add_header(name, value)

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
            status = response.getcode()
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status": exc.code, "error": f"HTTP {exc.code} {exc.reason}"}
    except urllib.error.URLError as exc:
        return {"ok": False, "status": None, "error": f"unreachable: {exc.reason}"}
    except (ssl.SSLError, OSError) as exc:
        return {"ok": False, "status": None, "error": f"connection: {exc}"}

    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        head = body[:80].decode("utf-8", "replace").replace("\n", " ")
        return {
            "ok": False,
            "status": status,
            "error": f"not JSON (got {len(body)}B starting {head!r})",
        }

    return {"ok": True, "status": status, "data": data, "bytes": len(body)}


def check_expected_key(result, expected):
    """Fold the response-shape contract into the result dict."""
    if not result["ok"] or expected is None:
        return result

    data = result.get("data")
    if not isinstance(data, dict) or expected not in data:
        result["ok"] = False
        result["error"] = f"200 but no {expected!r} key (shape changed)"
    elif not data[expected]:
        # An empty events list is normal on a day with no games, so this is a
        # note rather than a failure — flagging it would cry wolf every off-day.
        result["note"] = f"{expected!r} present but empty"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--timeout", type=float, default=20.0, help="per-request timeout")
    parser.add_argument("--verbose", action="store_true", help="show every profile")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    report = []
    for label, url, expected in ENDPOINTS:
        row = {"endpoint": label, "url": url, "profiles": {}}
        for profile_name, headers in PROFILES:
            result = check_expected_key(probe(url, headers, args.timeout), expected)
            row["profiles"][profile_name] = {
                k: v for k, v in result.items() if k != "data"
            }
        report.append(row)

    if args.as_json:
        print(json.dumps(report, indent=2))
    else:
        render(report, args.verbose)

    return summarize(report, args.as_json)


def render(report, verbose):
    print(f"ESPN endpoint probe — {datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n")
    for row in report:
        states = row["profiles"]
        worked = [name for name, r in states.items() if r["ok"]]
        mark = "PASS" if len(worked) == len(states) else ("PART" if worked else "FAIL")
        print(f"[{mark}] {row['endpoint']}")

        for name, result in states.items():
            if result["ok"] and not verbose:
                if result.get("note"):
                    print(f"         {name}: ok — {result['note']}")
                continue
            if result["ok"]:
                detail = result.get("note") or f"{result.get('bytes', 0)}B"
                print(f"         {name}: ok — {detail}")
            else:
                print(f"         {name}: {result['error']}")
        if mark != "PASS":
            print(f"         {row['url']}")
    print()


def summarize(report, as_json):
    """Print the diagnosis and pick an exit code."""
    total = len(report)
    failed = [r for r in report if not any(p["ok"] for p in r["profiles"].values())]

    # A request that never got an HTTP status never reached ESPN, and says nothing
    # about ESPN. Keep it apart from a genuine ESPN error: a DNS failure, a proxy
    # that denies the host, or a captive portal all look like "everything is down"
    # while ESPN is perfectly healthy, and reporting that as a withdrawn endpoint
    # sends whoever runs this off rewriting URLs that were never broken.
    unreachable = [
        r
        for r in failed
        if all(p.get("status") is None for p in r["profiles"].values())
    ]
    all_dead = [r for r in failed if r not in unreachable]
    ua_split = [
        r
        for r in report
        if r["profiles"]["browser"]["ok"]
        and not (r["profiles"]["default"]["ok"] and r["profiles"]["LEDMatrix/1.0"]["ok"])
    ]

    if as_json:
        return 1 if failed or ua_split else 0

    if unreachable and len(unreachable) == total:
        reason = unreachable[0]["profiles"]["browser"]["error"]
        print(f"CANNOT REACH ESPN: all {total} endpoints failed without ever getting "
              "an HTTP response.")
        print(f"  First reason: {reason}")
        print("  This is a problem between this machine and ESPN — DNS, a proxy that "
              "denies the host, or no route out — not an ESPN API change. Re-run from "
              "a host with normal internet access before concluding anything about ESPN.")
        return 2

    if not failed and not ua_split:
        print(f"All {total} endpoints healthy under every User-Agent. ESPN is not "
              "the problem — look at the plugin, its cache, or the local network.")
        return 0

    if ua_split:
        print(f"USER-AGENT FILTERING: {len(ua_split)}/{total} endpoints answer a "
              "browser agent but reject ours.")
        print("  ESPN is filtering on User-Agent. The fix is a header change, not a "
              "URL change: send a browser User-Agent from every ESPN caller.")
        for row in ua_split:
            print(f"    - {row['endpoint']}")

    if all_dead:
        print(f"\nENDPOINT DOWN: {len(all_dead)}/{total} endpoints fail under every "
              "agent, browser included.")
        print("  Not a header problem — the URL moved or was withdrawn, or the "
              "response shape changed. These need per-endpoint work:")
        for row in all_dead:
            reason = row["profiles"]["browser"]["error"]
            print(f"    - {row['endpoint']}: {reason}")

    if unreachable:
        print(f"\nUNREACHABLE: {len(unreachable)}/{total} endpoints never got an HTTP "
              "response, so they are undiagnosed rather than broken:")
        for row in unreachable:
            print(f"    - {row['endpoint']}: {row['profiles']['browser']['error']}")

    return 1


if __name__ == "__main__":
    sys.exit(main())
