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

The important trick is the second axis: each endpoint is tried under several
``User-Agent`` values, because anti-bot filtering is the most common way an
undocumented API "changes" and it discriminates on exactly that header.

Do not assume which side of that filter is the safe one. This script originally
tested for the familiar shape — a browser agent works, a script agent is
refused — and reported "healthy" all the way through the 2026-08-04 outage,
where ESPN had inverted it:

* a browser string is refused unconditionally (no other header rescues it),
* a bare custom token like ``LEDMatrix/1.0`` is refused when the request also
  sends no ``Accept`` header,
* honest client tokens (``python-requests``, ``curl``, ``Python-urllib``) and a
  token carrying a project URL are accepted.

So the profiles below are split into what the plugins actually send (``shipped``)
and controls kept only to characterise the filter, and the verdict is
direction-agnostic — it names which agents were accepted and which refused
rather than assuming. The diagnosis:

* every profile fails  -> ESPN moved or withdrew the endpoint; the URL needs work.
* some accepted, some refused -> ESPN is filtering on User-Agent. It only breaks
  the plugins if a *shipped* profile is on the refused side; the fix is then a
  header change, not a URL change.
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

# The voices to try. `shipped` marks the ones the plugins actually send, which
# is what decides the exit code: a control failing is information, a shipped
# profile failing is the outage. The controls are kept because *which* agents
# ESPN rejects is the diagnosis — on 2026-08-04 it started refusing browser
# strings and bare custom tokens while accepting honest client tokens, the
# reverse of the anti-bot filtering this script was first written to expect.
PROFILES = [
    ("default", {}, True),
    (
        "shipped",
        {
            "User-Agent": "LEDMatrix/1.0 (+https://github.com/ChuckBuilds/LEDMatrix)",
            "Accept": "application/json",
        },
        True,
    ),
    (
        "bare-custom",
        {"User-Agent": "LEDMatrix/1.0", "Accept": "application/json"},
        False,
    ),
    (
        "browser",
        {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
        },
        False,
    ),
]

SHIPPED = [name for name, _headers, shipped in PROFILES if shipped]


def probe(url, headers, timeout):
    """Fetch url and return a result dict. Never raises."""
    # The URLs come from the table above, but pin the scheme rather than trusting
    # them: urlopen would honour file:// or a custom scheme if an entry ever
    # arrived from somewhere less trustworthy. Reported as an ordinary failure so
    # the promise above holds and one bad row cannot abort the whole run.
    if not url.startswith("https://"):
        return {"ok": False, "status": None, "error": f"refusing non-HTTPS URL: {url!r}"}

    request = urllib.request.Request(url)
    for name, value in headers.items():
        request.add_header(name, value)

    try:
        # B310 is a syntactic blacklist rule and fires on the call regardless of
        # the scheme guard above, which is what actually makes this safe.
        with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310
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
        for profile_name, headers, _shipped in PROFILES:
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

    # Direction-agnostic on purpose. The first version of this asked only
    # "does browser work where ours does not", so when ESPN inverted the rule
    # and began rejecting browser strings instead, every endpoint looked
    # healthy and the advice it printed — send a browser agent — was the exact
    # change that would have kept the plugins broken.
    ua_split = [
        r for r in report
        if any(p["ok"] for p in r["profiles"].values())
        and not all(p["ok"] for p in r["profiles"].values())
    ]
    # Only a shipped profile failing actually breaks a plugin.
    broken_shipped = [
        r for r in report
        if r not in unreachable and not all(r["profiles"][n]["ok"] for n in SHIPPED)
    ]

    if as_json:
        return 1 if failed or broken_shipped else 0

    if unreachable and len(unreachable) == total:
        reason = next(iter(unreachable[0]["profiles"].values()))["error"]
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
        # Name the agents rather than assuming which side of the split is ours.
        accepted, rejected = set(), set()
        for row in ua_split:
            for name, result in row["profiles"].items():
                (accepted if result["ok"] else rejected).add(name)

        print(f"USER-AGENT FILTERING: {len(ua_split)}/{total} endpoints accept some "
              "agents and reject others.")
        print(f"  accepted: {', '.join(sorted(accepted)) or 'none'}")
        print(f"  rejected: {', '.join(sorted(rejected)) or 'none'}")

        broken_names = sorted(n for n in SHIPPED if n in rejected)
        if broken_names:
            print(f"  The plugins send {', '.join(broken_names)}, which ESPN is now "
                  "rejecting. This is a header change, not a URL change: switch every "
                  "ESPN caller to an agent in the accepted list above.")
        else:
            print("  Every agent the plugins actually send is still accepted, so this "
                  "does not break them today. It is a warning: ESPN is discriminating "
                  "on User-Agent, and which side is allowed has flipped before.")
        for row in ua_split:
            missing = sorted(n for n, r in row["profiles"].items() if not r["ok"])
            print(f"    - {row['endpoint']}: rejects {', '.join(missing)}")

    if all_dead:
        print(f"\nENDPOINT DOWN: {len(all_dead)}/{total} endpoints fail under every "
              "agent, browser included.")
        print("  Not a header problem — the URL moved or was withdrawn, or the "
              "response shape changed. These need per-endpoint work:")
        for row in all_dead:
            reason = next(iter(row["profiles"].values()))["error"]
            print(f"    - {row['endpoint']}: {reason}")

    if unreachable:
        print(f"\nUNREACHABLE: {len(unreachable)}/{total} endpoints never got an HTTP "
              "response, so they are undiagnosed rather than broken:")
        for row in unreachable:
            reason = next(iter(row["profiles"].values()))["error"]
            print(f"    - {row['endpoint']}: {reason}")

    # A split that leaves every shipped agent working is a warning, not a
    # failure: nothing is broken today, and exiting non-zero for it would train
    # whoever runs this to ignore the one exit code that means "act now".
    if not failed and not broken_shipped:
        print("\nNothing the plugins send is being rejected — reporting the split "
              "above as a warning, not a failure.")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
