#!/usr/bin/env python3
"""
Script-style tests for the Elections plugin (PASS/FAIL + sys.exit).

Covers provider parsing against real fixtures, the state/race-type filters,
the multi-provider merge, the importance sort, and the newly-called diff.

Run with the core venv from anywhere:
    .venv/bin/python plugins/ledmatrix-elections/test_elections.py
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from election_data_model import Candidate, Race, Scope  # noqa: E402
from providers.nyt import NytStaticProvider, parse_called_slugs  # noqa: E402
from providers.ca_sos import CaSosProvider  # noqa: E402
from store import RaceStore  # noqa: E402

FIX = os.path.join(HERE, "test", "fixtures")
_passed = 0
_failed = 0


def check(cond, msg):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS: {msg}")
    else:
        _failed += 1
        print(f"  FAIL: {msg}")


def load(name):
    with open(os.path.join(FIX, name)) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# 1. NYT parsing
# ---------------------------------------------------------------------------

def test_nyt_parse():
    print("[NYT parse]")
    data = load("nyt_ca_results.json")
    provider = NytStaticProvider({"election_date": "2026-06-02", "election_type": "primary"})
    races = provider.parse(data)
    check(len(races) == 168, f"parsed all races (got {len(races)})")

    by_id = {r.id: r for r in races}
    gov = by_id.get("governor-ca")
    check(gov is not None, "governor-ca race present")
    check(gov.office == "Governor" and gov.state == "CA", "governor office/state correct")
    check(gov.scope == Scope.STATEWIDE, "governor scope STATEWIDE")
    check(abs(gov.pct_reporting - 57.54) < 0.01, f"governor pct_reporting from eevp (got {gov.pct_reporting})")
    check(len(gov.candidates) == 61, f"governor candidate count (got {len(gov.candidates)})")
    check(gov.candidates == sorted(gov.candidates, key=lambda c: c.votes, reverse=True),
          "governor candidates sorted by votes desc")
    check(gov.is_key_race(), "governor flagged as key race")
    # Leader Hilton had 1,386,966 votes in the fixture's top reporting unit.
    check(gov.leader is not None and gov.leader.votes == 1386966,
          f"governor leader votes (got {gov.leader.votes if gov.leader else None})")

    # House district 1 appears twice: All-Party Primary + Nonpartisan Special.
    house1 = by_id.get("u-s-house-ca-1")
    house1_special = by_id.get("u-s-house-ca-1-special")
    check(house1 is not None, "u-s-house-ca-1 (primary) present")
    check(house1_special is not None, "u-s-house-ca-1-special present (no id collision)")
    check(house1.scope == Scope.DISTRICT and house1.district == "1", "house district/scope correct")
    check(house1.called, "house-1 primary called (advanced_to_runoff/won non-empty)")

    # Party normalization: every governor candidate maps to a single letter.
    parties = {c.party for c in gov.candidates}
    check(parties <= {"D", "R", "I", "G", "L", "P", "N", "O"},
          f"parties normalized to single letters (got {parties})")


# ---------------------------------------------------------------------------
# 2. NYT race-calls cheap feed
# ---------------------------------------------------------------------------

def test_nyt_build_url():
    print("[NYT build_url]")
    p = NytStaticProvider({"election_date": "2026-06-02", "election_type": "primary"})
    # Regression: slug uses the FULL state name, not the 2-letter code.
    check(p.build_url("CA").endswith("/2026-06-02/results-california-primary.json"),
          f"CA primary slug uses full state name (got {p.build_url('CA')})")
    check(p.build_url("WA").endswith("results-washington-primary.json"),
          "WA primary slug uses full state name")
    g = NytStaticProvider({"election_date": "2026-11-03", "election_type": "general"})
    check(g.build_url("CA").endswith("/2026-11-03/results-california.json"),
          f"general slug drops the -primary suffix (got {g.build_url('CA')})")


def test_nyt_race_calls():
    print("[NYT race-calls feed]")
    data = load("nyt_race_calls.json")
    slugs = parse_called_slugs(data)
    check(len(slugs) == 19, f"parsed all call slugs (got {len(slugs)})")
    check("CA-APP-H-11-2026-06-02" in slugs,
          f"recovered nyt_id from generated-rc slug (sample: {sorted(slugs)[:1]})")


# ---------------------------------------------------------------------------
# 3. CA-SoS parsing
# ---------------------------------------------------------------------------

def test_ca_sos_parse():
    print("[CA-SoS parse]")
    provider = CaSosProvider({"enabled": True})

    gov_raw = load("ca_sos_governor.json")
    gov = provider.parse_office(gov_raw, "Governor")
    check(gov is not None and gov.id == "governor-ca", "governor id matches NYT key")
    check(abs(gov.pct_reporting - 100.0) < 0.01, f"reporting % parsed from string (got {gov.pct_reporting})")
    becerra = next((c for c in gov.candidates if c.name == "Xavier Becerra"), None)
    check(becerra is not None and becerra.votes == 1267070,
          f"comma-string votes parsed (got {becerra.votes if becerra else None})")
    check(gov.called, "governor called (reporting >= threshold)")
    winners = [c for c in gov.candidates if c.is_winner]
    check(len(winners) == 2, f"top-two derived as winners (got {len(winners)})")

    county_raw = load("ca_sos_governor_la_county.json")
    gov_county = provider.parse_office(county_raw, "Governor")
    check(gov_county is not None and gov_county.id == "governor-ca",
          "county rollup keeps same race id")
    check("County" in (gov_county.title or ""), "county title preserved")

    house_raw = load("ca_sos_us_rep_all.json")
    house = provider.parse_house_all(house_raw)
    check(len(house) == 52, f"parsed all house districts (got {len(house)})")
    h1 = next((r for r in house if r.id == "u-s-house-ca-1"), None)
    check(h1 is not None and h1.district == "1", "house district id/number correct")


# ---------------------------------------------------------------------------
# 4. State + race-type filters
# ---------------------------------------------------------------------------

def _race(rid, office, state, scope, called=False):
    return Race(id=rid, office=office, state=state, scope=scope,
                candidates=[Candidate("X", "D", 10, 50.0)], called=called)


def test_filters():
    print("[Filters]")
    races = [
        _race("president-us", "President", None, Scope.NATIONAL),
        _race("governor-ca", "Governor", "CA", Scope.STATEWIDE),
        _race("u-s-house-ca-12", "U.S. House", "CA", Scope.DISTRICT),
        _race("governor-wa", "Governor", "WA", Scope.STATEWIDE),
        _race("attorney-general-ca", "Attorney General", "CA", Scope.STATEWIDE),
    ]
    kept = RaceStore.filter_races(races, "CA", only_my_state=True)
    ids = {r.id for r in kept}
    check("president-us" in ids, "national race kept under state filter")
    check("governor-ca" in ids and "u-s-house-ca-12" in ids, "CA statewide + house kept")
    check("governor-wa" not in ids, "out-of-state race dropped")

    typed = RaceStore.filter_races(races, "CA", only_my_state=True,
                                   race_types=["president", "governor", "house"])
    tids = {r.id for r in typed}
    check("attorney-general-ca" not in tids, "downballot office dropped by race_types")
    check("governor-ca" in tids, "governor kept by race_types")


# ---------------------------------------------------------------------------
# 5. Merge precedence
# ---------------------------------------------------------------------------

def test_merge():
    print("[Merge]")
    nyt = NytStaticProvider({"election_date": "2026-06-02", "election_type": "primary"})
    nyt_races = nyt.parse(load("nyt_ca_results.json"))
    ca = CaSosProvider({"enabled": True})
    ca_gov = ca.parse_office(load("ca_sos_governor.json"), "Governor")

    nyt_gov = next(r for r in nyt_races if r.id == "governor-ca")
    nyt_gov_called = nyt_gov.called
    nyt_gov_key = nyt_gov.is_key_race()
    nyt_gov_reporting = nyt_gov.pct_reporting

    store = RaceStore(override_votes=True)
    merged = store.merge([(nyt, nyt_races), (ca, [ca_gov])])
    by_id = {r.id: r for r in merged}
    gov = by_id["governor-ca"]
    check(gov.called == nyt_gov_called, "merge keeps NYT called flag")
    check(gov.is_key_race() == nyt_gov_key, "merge keeps NYT key-race marker")
    check(gov.source == "nyt+ca_sos", f"merge marks combined source (got {gov.source})")
    # CA-SoS reports "% of precincts reporting" (100% on election night while mail
    # ballots are still counted). NYT eevp is the honest "% of expected vote in",
    # so the merge must keep NYT's reporting, not the local source's 100%.
    check(abs(gov.pct_reporting - nyt_gov_reporting) < 0.01,
          f"merge keeps NYT eevp reporting, not CA-SoS precinct % (got {gov.pct_reporting})")
    becerra = next((c for c in gov.candidates if c.name == "Xavier Becerra"), None)
    check(becerra is not None and becerra.votes == 1267070,
          "merge still takes CA-SoS authoritative vote totals")
    # CA-SoS-only races (house) are absent here; NYT races elsewhere untouched.
    check(len(merged) == len(nyt_races), "merge does not drop or duplicate races")

    store_no = RaceStore(override_votes=False)
    merged_no = store_no.merge([(nyt, nyt_races), (ca, [ca_gov])])
    gov_no = {r.id: r for r in merged_no}["governor-ca"]
    check(gov_no.source == "nyt", "override_votes=False keeps NYT untouched")


# ---------------------------------------------------------------------------
# 6. Importance sort
# ---------------------------------------------------------------------------

def test_sort():
    print("[Importance sort]")
    uncalled_house = _race("u-s-house-ca-30", "U.S. House", "CA", Scope.DISTRICT, called=False)
    called_house = _race("u-s-house-ca-12", "U.S. House", "CA", Scope.DISTRICT, called=True)
    key_gov = _race("governor-ca", "Governor", "CA", Scope.STATEWIDE, called=False)
    key_gov._key_race = True
    pres = _race("president-us", "President", None, Scope.NATIONAL, called=False)

    ordered = RaceStore.sort_by_importance([uncalled_house, key_gov, pres, called_house])
    check(ordered[0].id == "u-s-house-ca-12", "called race sorts first")
    check(ordered[1].id == "governor-ca", "key race sorts before non-key uncalled")
    check(ordered.index(pres) < ordered.index(uncalled_house),
          "within non-key tier, President outranks House")


# ---------------------------------------------------------------------------
# 7. Newly-called diff
# ---------------------------------------------------------------------------

def test_diff():
    print("[Newly-called diff]")
    store = RaceStore()
    snap_a = [
        _race("governor-ca", "Governor", "CA", Scope.STATEWIDE, called=False),
        _race("u-s-house-ca-12", "U.S. House", "CA", Scope.DISTRICT, called=True),
    ]
    cold = store.diff_newly_called(snap_a, now=1000.0)
    check(cold == [], "cold start emits no interrupts (already-called not replayed)")

    snap_b = [
        _race("governor-ca", "Governor", "CA", Scope.STATEWIDE, called=True),
        _race("u-s-house-ca-12", "U.S. House", "CA", Scope.DISTRICT, called=True),
    ]
    newly = store.diff_newly_called(snap_b, now=1100.0)
    check(len(newly) == 1 and newly[0].id == "governor-ca",
          f"exactly one newly-called race (got {[r.id for r in newly]})")
    check(newly[0].called_at == 1100.0, "called_at stamped at detection time")

    again = store.diff_newly_called(snap_b, now=1200.0)
    check(again == [], "re-running same snapshot emits nothing (dedup)")


# ---------------------------------------------------------------------------
# 8. Local races (state legislature by chamber district, any state)
# ---------------------------------------------------------------------------

def test_ca_sos_defaults():
    print("[CA-SoS advanced defaults]")
    p = CaSosProvider({})
    check(p.offices == [] and p.include_house is False,
          "CA-SoS contributes nothing by default (NYT already covers CA races)")


def test_chamber_classification():
    print("[Chamber classification]")
    from election_data_model import chamber_of_office
    check(chamber_of_office("State Senate") == "upper", "State Senate -> upper")
    check(chamber_of_office("State Assembly") == "lower", "State Assembly -> lower")
    check(chamber_of_office("State House") == "lower", "State House -> lower")
    check(chamber_of_office("House of Delegates") == "lower", "House of Delegates -> lower")
    check(chamber_of_office("General Assembly") == "lower", "General Assembly -> lower")
    # Federal offices that share the words must NOT classify as local.
    check(chamber_of_office("U.S. Senate") is None, "U.S. Senate is not local")
    check(chamber_of_office("U.S. House") is None, "U.S. House is not local")
    check(chamber_of_office("Governor") is None, "Governor is not local")
    check(chamber_of_office(None) is None, "None office is not local")


def test_local_races():
    print("[Local races]")
    nyt = NytStaticProvider({"election_date": "2026-06-02", "election_type": "primary"})
    races = nyt.parse(load("nyt_ca_results.json"))

    # The NYT feed already carries every CA legislative district with an honest
    # eevp ("% of expected vote") estimate — not a precinct-based 100%.
    asm1 = next((r for r in races if r.id == "state-assembly-ca-1"), None)
    check(asm1 is not None, "NYT feed carries state assembly races")
    check(asm1.reporting_basis == "vote", "NYT local race uses vote-share (eevp) reporting")
    check(asm1.pct_reporting < 100.0,
          f"local race reporting isn't a false 100% (got {asm1.pct_reporting})")

    # Show only the user's configured chamber district; the rest are dropped, and
    # the local races bypass race_types (here only 'governor' is listed).
    districts = {"lower": "1", "upper": "2"}
    kept = RaceStore.filter_races(races, "CA", only_my_state=True,
                                  race_types=["governor"], local_districts=districts)
    local_ids = {r.id for r in kept if r.office in ("State Assembly", "State Senate")}
    check(local_ids == {"state-assembly-ca-1", "state-senate-ca-2"},
          f"only the configured chamber districts are kept (got {sorted(local_ids)})")

    # With no district configured, no legislative races show (avoids flooding the
    # ticker with all 80 + 40 of them).
    none_kept = RaceStore.filter_races(races, "CA", only_my_state=True, race_types=["governor"])
    check(not any(r.office in ("State Assembly", "State Senate") for r in none_kept),
          "no local races without district config")


def test_local_races_other_state():
    print("[Local races - non-CA chamber names]")
    # A state that names its lower chamber "House of Delegates" (e.g. VA) must
    # work the same as CA's "State Assembly".
    hod = Race(id="house-of-delegates-va-5", office="House of Delegates", state="VA",
               scope=Scope.DISTRICT, district="5",
               candidates=[Candidate("X", "D", 10, 50.0)])
    senate = Race(id="state-senate-va-9", office="State Senate", state="VA",
                  scope=Scope.DISTRICT, district="9",
                  candidates=[Candidate("Y", "R", 8, 45.0)])
    other = Race(id="state-senate-va-3", office="State Senate", state="VA",
                 scope=Scope.DISTRICT, district="3",
                 candidates=[Candidate("Z", "R", 8, 45.0)])
    kept = RaceStore.filter_races([hod, senate, other], "VA", only_my_state=True,
                                  race_types=["governor"],
                                  local_districts={"lower": "5", "upper": "9"})
    ids = {r.id for r in kept}
    check(ids == {"house-of-delegates-va-5", "state-senate-va-9"},
          f"non-CA chamber names matched by district (got {sorted(ids)})")


def test_district_aliases():
    print("[District config aliases]")
    from manager import ElectionPlugin
    neutral = ElectionPlugin._build_local_districts(
        {"upper_chamber_district": "9", "lower_chamber_district": "5"})
    check(neutral == {"upper": "9", "lower": "5"}, "chamber-neutral keys map to chambers")
    ca = ElectionPlugin._build_local_districts(
        {"senate_district": "2", "assembly_district": "1"})
    check(ca == {"upper": "2", "lower": "1"}, "CA-style aliases still work")
    check(ElectionPlugin._build_local_districts({"assembly_district": "x"}) == {},
          "non-numeric district ignored")


def test_status_label():
    print("[Reporting label]")
    from renderer import _status_text
    vote = _race("governor-ca", "Governor", "CA", Scope.STATEWIDE)
    vote.pct_reporting = 57.0
    check(_status_text(vote)[0] == "57% in", "vote-basis reporting shows '% in'")

    prec = _race("state-assembly-ca-1", "State Assembly", "CA", Scope.DISTRICT)
    prec.pct_reporting = 100.0
    prec.reporting_basis = "precincts"
    check(_status_text(prec)[0] == "100% prec",
          "precinct-basis reporting shows '% prec', not a false '100% in'")


def _raw_mayor(nyt_id, called):
    """Minimal NYT-raw 'Mayor' race (no seat_number) — collides on office+state."""
    return {
        "office": "Mayor",
        "nyt_id": nyt_id,
        "type": "primary",
        "top_reporting_unit": {
            "state_postal": "CA",
            "total_votes": 100,
            "eevp": 100,
            "candidates": [
                {"nyt_id": "c1", "votes": {"total": 60}},
                {"nyt_id": "c2", "votes": {"total": 40}},
            ],
        },
        "outcome": {"won": ["c1"]} if called else {},
    }


def test_stable_race_id_across_reorder():
    print("[Stable race id across feed reorder]")
    p = NytStaticProvider({"election_date": "2026-06-02", "election_type": "primary"})
    called_mayor = _raw_mayor("mayor-aaa", called=True)
    other_mayor = _raw_mayor("mayor-bbb", called=False)

    # Same two physical races, but NYT serves them in a different order on the
    # next pull (it reorders by reporting/votes).
    races1 = p.parse({"races": [called_mayor, other_mayor]})
    races2 = p.parse({"races": [other_mayor, called_mayor]})

    id_by_nyt1 = {r.nyt_id: r.id for r in races1}
    id_by_nyt2 = {r.nyt_id: r.id for r in races2}
    check(len(set(id_by_nyt1.values())) == 2, "colliding mayors get distinct ids")
    check(id_by_nyt1 == id_by_nyt2,
          f"each physical race keeps a stable id across reorder ({id_by_nyt1} vs {id_by_nyt2})")

    # End-to-end: the called mayor must fire as 'newly called' exactly once, not
    # re-fire on every reordered pull (the interrupt-loop bug).
    store = RaceStore()
    store.set_election("CA_2026-06-02_primary")
    check(store.diff_newly_called(races1, now=1000.0) == [],
          "cold start seeds snapshot, no replay")
    check(store.diff_newly_called(races2, now=1100.0) == [],
          "reordered pull does not re-fire the already-called race")


def main():
    for fn in (test_nyt_parse, test_nyt_build_url, test_nyt_race_calls, test_ca_sos_parse,
               test_filters, test_merge, test_sort, test_diff,
               test_stable_race_id_across_reorder,
               test_ca_sos_defaults, test_chamber_classification, test_local_races,
               test_local_races_other_state, test_district_aliases, test_status_label):
        fn()
    print(f"\n{_passed} passed, {_failed} failed")
    sys.exit(0 if _failed == 0 else 1)


if __name__ == "__main__":
    main()
