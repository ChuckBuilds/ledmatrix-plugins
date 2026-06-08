#!/usr/bin/env python3
"""
Script-style tests for the calendar / auto-pickup, staleness, and override
behavior added on top of the base Elections plugin.

Covers:
- the general-election date formula + window/includability rules
- resolve_active: dormant outside windows, active inside, most-recent wins
- store.filter_visible (per-race 24h drain) + cold-start called_at seeding
- snapshot persistence across a restart (no replay, no missed calls)
- NYT URL overrides (feed_url / feed_filename)
- manager-level dormancy + "today is election day in ZZ" + pinned-feed override

Run with the core venv from the LEDMatrix tree:
    .venv/bin/python plugins/ledmatrix-elections/test_calendar.py
"""

import os
import sys
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from data_model import Candidate, Race, Scope  # noqa: E402
from store import RaceStore  # noqa: E402
from providers.nyt import NytStaticProvider  # noqa: E402
from election_calendar import (  # noqa: E402
    ElectionEvent,
    general_election_date,
    resolve_active,
)

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


def _ts(date_str):
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return datetime(d.year, d.month, d.day).timestamp()


def _race(rid, called=False, called_at=None, state="CA", scope=Scope.STATEWIDE):
    r = Race(id=rid, office="Governor", state=state, scope=scope,
             candidates=[Candidate("X", "D", 10, 50.0)], called=called)
    r.called_at = called_at
    return r


# ---------------------------------------------------------------------------
# 1. Calendar primitives
# ---------------------------------------------------------------------------

def test_general_date_formula():
    print("[General election date]")
    # First Tuesday after the first Monday in November.
    check(general_election_date(2026) == date(2026, 11, 3), "2026 general is Nov 3")
    check(general_election_date(2024) == date(2024, 11, 5), "2024 general is Nov 5")
    check(general_election_date(2028) == date(2028, 11, 7), "2028 general is Nov 7")
    # Nov 1 being a Tuesday must NOT count (2022: first Mon Nov 7 -> Nov 8).
    check(general_election_date(2022) == date(2022, 11, 8),
          "Nov-1-Tuesday excluded (2022 general is Nov 8)")


def test_includable_and_window():
    print("[Includability + window]")
    gen = ElectionEvent("CA", "2026-11-03", "general")
    pri = ElectionEvent("CA", "2026-06-02", "primary")
    spc_bad = ElectionEvent("GA", "2026-07-15", "special")
    spc_ok = ElectionEvent("GA", "2026-07-15", "special",
                           feed_filename="results-georgia-special.json")
    check(gen.is_includable() and pri.is_includable(), "primary + general are includable")
    check(not spc_bad.is_includable(), "special without a feed filename is NOT includable")
    check(spc_ok.is_includable(), "special WITH a feed filename is includable")

    check(gen.window_contains(date(2026, 11, 3)), "window includes election day")
    check(gen.window_contains(date(2026, 11, 17)), "window includes day+14 (trail)")
    check(not gen.window_contains(date(2026, 11, 18)), "window excludes day+15")
    check(not gen.window_contains(date(2026, 11, 2)), "window excludes day before")


# ---------------------------------------------------------------------------
# 2. resolve_active
# ---------------------------------------------------------------------------

def test_resolve_active():
    print("[resolve_active]")
    # Dormant: mid-March in CA, no scheduled election nearby.
    check(resolve_active("CA", date(2026, 3, 15)) is None, "dormant when no window contains today")

    # CA primary window (2026-06-02 .. +14).
    ev = resolve_active("CA", date(2026, 6, 10))
    check(ev is not None and ev.type == "primary" and ev.date == "2026-06-02",
          "CA primary active during its window")

    # General window for any state (computed date).
    ev = resolve_active("WA", date(2026, 11, 5))
    check(ev is not None and ev.type == "general" and ev.date == "2026-11-03",
          "general active for any state during its window")

    # Outside both -> dormant.
    check(resolve_active("CA", date(2026, 12, 1)) is None, "dormant after general trail ends")

    # Extra special (with feed filename) becomes active; without it, dormant.
    spc = ElectionEvent("GA", "2026-07-15", "special",
                        feed_filename="results-georgia-special.json")
    ev = resolve_active("GA", date(2026, 7, 16), extra_events=[spc])
    check(ev is not None and ev.type == "special", "extra special active when predictable")
    bad = ElectionEvent("GA", "2026-07-15", "special")
    check(resolve_active("GA", date(2026, 7, 16), extra_events=[bad]) is None,
          "unpredictable special is skipped (dormant)")


# ---------------------------------------------------------------------------
# 3. Visibility drain + cold-start seeding
# ---------------------------------------------------------------------------

def test_filter_visible():
    print("[filter_visible]")
    now = 1_000_000.0
    races = [
        _race("uncalled", called=False),
        _race("fresh", called=True, called_at=now - 3600),          # 1h ago
        _race("stale", called=True, called_at=now - 90_000),        # ~25h ago
        _race("no-ts", called=True, called_at=None),                # unknown -> keep
    ]
    visible = {r.id for r in RaceStore.filter_visible(races, now=now, hide_called_after=86400)}
    check("uncalled" in visible, "uncalled race stays visible")
    check("fresh" in visible, "called <24h stays visible")
    check("stale" not in visible, "called >24h is hidden (even with uncalled siblings)")
    check("no-ts" in visible, "called with no timestamp is kept")

    all_kept = {r.id for r in RaceStore.filter_visible(races, now=now, hide_called_after=0)}
    check(all_kept == {"uncalled", "fresh", "stale", "no-ts"}, "hide disabled keeps everything")


def test_cold_start_seed():
    print("[cold-start called_at seeding]")
    election_day = _ts("2026-06-02")

    # Booting 3 days later: already-called race seeds at election day -> hidden.
    store = RaceStore()
    later = election_day + 3 * 86400
    r = _race("governor-ca", called=True)
    cold = store.diff_newly_called([r], now=later, cold_start_ts=election_day)
    check(cold == [], "cold start emits no interrupts")
    check(r.called_at == election_day, "already-called race seeded at election day, not now")
    visible = RaceStore.filter_visible([r], now=later, hide_called_after=86400)
    check(visible == [], "race called before boot (>24h ago) is hidden after restart")

    # Booting election night: same race shows (called within 24h).
    store2 = RaceStore()
    night = election_day + 3 * 3600
    r2 = _race("governor-ca", called=True)
    store2.diff_newly_called([r2], now=night, cold_start_ts=election_day)
    visible2 = RaceStore.filter_visible([r2], now=night, hide_called_after=86400)
    check(len(visible2) == 1, "same-night call still shows on a fresh boot")


# ---------------------------------------------------------------------------
# 4. Snapshot persistence across restarts
# ---------------------------------------------------------------------------

class FakeCache:
    def __init__(self):
        self.d = {}

    def get(self, k):
        return self.d.get(k)

    def set(self, k, v):
        self.d[k] = v


def test_persistence():
    print("[snapshot persistence]")
    cache = FakeCache()
    key = "CA_2026-06-02_primary"

    s1 = RaceStore(cache_manager=cache)
    s1.set_election(key)
    called = _race("governor-ca", called=True)
    s1.diff_newly_called([called], now=1000.0, cold_start_ts=900.0)
    check(any(k.startswith("elections_snapshot_") for k in cache.d), "snapshot persisted to cache")

    # Simulate a restart: new store, same cache + key.
    s2 = RaceStore(cache_manager=cache)
    s2.set_election(key)
    again = _race("governor-ca", called=True)
    newly = s2.diff_newly_called([again], now=2000.0, cold_start_ts=900.0)
    check(newly == [], "restart does not replay an already-called race as breaking")

    # A genuinely new call after restart still fires.
    new_call = _race("u-s-house-ca-12", called=True)
    keep = _race("governor-ca", called=True)
    fired = s2.diff_newly_called([keep, new_call], now=2100.0, cold_start_ts=900.0)
    check(len(fired) == 1 and fired[0].id == "u-s-house-ca-12",
          "a fresh call after restart is still detected")

    # Switching elections resets the snapshot.
    s2.set_election("CA_2026-11-03_general")
    check(s2._called_snapshot is None, "switching election resets the snapshot")


# ---------------------------------------------------------------------------
# 5. NYT URL overrides
# ---------------------------------------------------------------------------

def test_nyt_overrides():
    print("[NYT URL overrides]")
    p = NytStaticProvider({"election_date": "2026-08-01", "election_type": "special"})
    p.feed_url_override = "https://example.test/custom/results.json"
    check(p.build_url("CA") == "https://example.test/custom/results.json",
          "feed_url_override is used verbatim")

    p2 = NytStaticProvider({"election_date": "2026-08-01"})
    p2.feed_filename = "results-georgia-special-senate.json"
    url = p2.build_url(None)
    check(url.endswith("/2026-08-01/results-georgia-special-senate.json"),
          f"feed_filename builds under the date without needing state (got {url})")


# ---------------------------------------------------------------------------
# 6. Manager dormancy + overrides (constructed with fakes)
# ---------------------------------------------------------------------------

class FakeDisplay:
    width = 64
    height = 32

    def __init__(self):
        from PIL import Image
        self.image = Image.new("RGB", (64, 32))

    def update_display(self):
        pass

    def set_scrolling_state(self, *_a):
        pass


def _plugin(config):
    from manager import ElectionPlugin
    return ElectionPlugin("ledmatrix-elections", config, FakeDisplay(), FakeCache(), None)


def test_manager_resolution():
    print("[Manager resolution]")
    # Dormant: CA, mid-March, no override.
    p = _plugin({"state": "CA"})
    check(p._resolve_active(_ts("2026-03-15")) is None, "manager dormant off-season")

    # "Today is an election day in ZZ" via override.
    p = _plugin({"state": "WA", "override": {
        "active": True, "state": "ZZ",
        "election_date": "2026-11-03", "election_type": "general"}})
    ev = p._resolve_active(_ts("2026-03-15"))   # date irrelevant: override forces active
    check(ev is not None and ev.state == "ZZ" and ev.type == "general",
          "override forces an active election in the named state")
    p._apply_active(ev)
    nyt = next(pr for pr in p.providers if isinstance(pr, NytStaticProvider))
    check(nyt.election_date == "2026-11-03", "override date flows to the NYT provider")
    check(p._fetch_state == "ZZ" and nyt.build_url("ZZ").endswith("/results-zz.json"),
          "fetch + URL target the overridden state")

    # Pinned feed URL override.
    p = _plugin({"state": "CA", "override": {
        "feed_url": "https://example.test/pinned.json"}})
    ev = p._resolve_active(_ts("2026-03-15"))
    check(ev is not None and ev.feed_url == "https://example.test/pinned.json",
          "feed_url override produces an active event")
    p._apply_active(ev)
    nyt = next(pr for pr in p.providers if isinstance(pr, NytStaticProvider))
    check(nyt.build_url("anything") == "https://example.test/pinned.json",
          "pinned feed_url is what the provider will fetch")

    # Extra calendar event (user-supplied primary date) drives auto-pickup.
    p = _plugin({"state": "TX", "calendar_events": [
        {"state": "TX", "date": "2026-03-03", "type": "primary"}]})
    ev = p._resolve_active(_ts("2026-03-05"))
    check(ev is not None and ev.state == "TX" and ev.date == "2026-03-03",
          "user-supplied calendar_events drive auto-pickup")
    check(p._resolve_active(_ts("2026-03-25")) is None,
          "dormant again once the extra event's window passes")


def test_local_provider_autoengage():
    print("[Local provider auto-engage]")
    from providers import create_providers
    from providers.ca_sos import CaSosProvider

    def names(cfg):
        return [p.name for p in create_providers(cfg, None)]

    check("ca_sos" in names({"state": "CA"}),
          "CA auto-engages the local source with no per-provider flag")
    check("ca_sos" not in names({"state": "WA"}),
          "a state with no local source gets NYT only")
    check("ca_sos" not in names({"state": "CA", "local_races": False}),
          "local_races=false opts out even in CA")
    # The advanced ca_sos knobs still flow through to the provider.
    provs = create_providers({"state": "CA", "providers": {"ca_sos": {"county": "los-angeles"}}}, None)
    ca = next(p for p in provs if isinstance(p, CaSosProvider))
    check(ca.county == "los-angeles", "ca_sos sub-config still reaches the provider")


def _ticker_race(rid, ncands):
    cands = [Candidate(f"C{i}", "D" if i % 2 else "R", 100 - i, 40 - i) for i in range(ncands)]
    return Race(id=rid, office="U.S. House", state="CA", scope=Scope.DISTRICT,
                district=str(rid), candidates=cands)


def test_ticker_packing():
    print("[Ticker vertical packing (scales with height)]")
    import renderer
    races = [_ticker_race(i, 2) for i in range(4)]  # four 2-candidate races

    # 32px: one race per column (unchanged from the original behavior).
    cols32 = renderer.pack_ticker_columns(races, 32)
    check(all(len(c) == 1 for c in cols32) and len(cols32) == 4,
          f"32px packs one race per card (got {[len(c) for c in cols32]})")

    # 64px: two races stacked per card -> your "two rows, two candidates each".
    cols64 = renderer.pack_ticker_columns(races, 64)
    check(len(cols64) == 2 and all(len(c) == 2 for c in cols64),
          f"64px stacks two races per card (got {[len(c) for c in cols64]})")

    # Very tall: all races stacked into a single card (scales to any height).
    colsTall = renderer.pack_ticker_columns(races, 512)
    check(len(colsTall) == 1 and len(colsTall[0]) == 4,
          f"tall panel stacks all races top to bottom (got {[len(c) for c in colsTall]})")


def test_ticker_candidate_count():
    print("[Ticker candidates per race (more when available)]")
    import renderer
    two = _ticker_race(1, 2)
    many = _ticker_race(2, 8)
    check(renderer.ticker_block_candidate_count(two, 64) == 2, "2-candidate race shows its 2")
    check(renderer.ticker_block_candidate_count(many, 64) == 4, "big field capped at 4 on 64px")
    check(renderer.ticker_block_candidate_count(many, 32) == 3, "fewer rows fit on 32px")
    check(renderer.ticker_block_candidate_count(many, 512) == 4, "still capped at 4 on a tall panel")
    # End to end: segments render at the right size with no overflow.
    ok = True
    for h in (32, 64, 128):
        for seg in renderer.render_ticker_segments([two, many], h):
            if seg.height != h:
                ok = False
    check(ok, "packed segments render at the panel height across sizes")


def test_called_card_winners():
    print("[Called card winner selection]")
    import renderer
    a = Candidate("Alpha", "R", 100, 41.0, is_winner=True)
    b = Candidate("Beta", "D", 90, 39.0, is_winner=True)
    c = Candidate("Gamma", "I", 50, 20.0, is_winner=False)
    primary = Race(id="u-s-house-ca-48", office="U.S. House", state="CA",
                   scope=Scope.DISTRICT, candidates=[a, b, c], called=True, district="48")
    w = renderer.called_card_winners(primary)
    check([x.name for x in w] == ["Alpha", "Beta"], "top-two primary shows BOTH advancers")

    general = Race(id="governor-ca", office="Governor", state="CA", scope=Scope.STATEWIDE,
                   candidates=[Candidate("Win", "D", 100, 55.0, is_winner=True),
                               Candidate("Lose", "R", 80, 45.0)], called=True)
    check([x.name for x in renderer.called_card_winners(general)] == ["Win"],
          "single-winner general shows one")

    leader_only = Race(id="x", office="Governor", state="CA", scope=Scope.STATEWIDE,
                       candidates=[Candidate("Ahead", "D", 10, 50.0)], called=False)
    check([x.name for x in renderer.called_card_winners(leader_only)] == ["Ahead"],
          "falls back to current leader when nothing flagged")


def test_called_card_render():
    print("[Called card render across sizes]")
    import renderer
    primary = Race(id="u-s-house-ca-48", office="U.S. House", state="CA",
                   scope=Scope.DISTRICT, district="48", called=True, pct_reporting=59.0,
                   candidates=[Candidate("Desmond", "R", 100, 41.0, is_winner=True),
                               Candidate("Min", "D", 90, 38.0, is_winner=True)])
    general = Race(id="governor-ca", office="Governor", state="CA", scope=Scope.STATEWIDE,
                   called=True, pct_reporting=92.0,
                   candidates=[Candidate("Newsom", "D", 100, 58.0, is_winner=True)])
    ok = True
    for w, h in [(64, 32), (128, 32), (128, 64), (256, 32)]:
        for race in (primary, general):
            try:
                img = renderer.render_called_card(race, w, h)
                if img.size != (w, h):
                    ok = False
            except Exception as e:
                ok = False
                print("    render error:", w, h, e)
    check(ok, "called card renders at every supported size (single + two-winner)")


def test_ticker_one_pass():
    print("[Ticker one-pass duration]")
    p = _plugin({"state": "CA", "display_duration": 30, "scroll_speed": 1.0, "scroll_delay": 0.01})
    p._scroll_ready = True
    p._showing_called = False
    # pps = 100 px/s. A long chain scales the slot to one pass, not the 30s floor.
    p.scroll_helper.total_scroll_width = 2000
    check(abs(p.get_display_duration() - 20.0) < 0.5,
          f"slot ~ one pass of the content, not padded to 30s (got {p.get_display_duration():.1f}s)")
    # A short chain rotates promptly (floored so it isn't a sub-second flash).
    p.scroll_helper.total_scroll_width = 100
    check(p.get_display_duration() == 6.0, "very short ticker floored to 6s and moves on")
    # More races -> longer slot (monotonic with content).
    p.scroll_helper.total_scroll_width = 5000
    check(p.get_display_duration() > 20.0, "more races extend the slot")


def test_called_duration():
    print("[Called-card display duration]")
    p = _plugin({"state": "CA", "interrupt": {"duration_seconds": 12}})
    p._showing_called = True
    check(p.get_display_duration() == 12.0, "called card uses the short interrupt duration")
    p._showing_called = False
    p._scroll_ready = False
    check(p.get_display_duration() == p.display_duration,
          "ticker path keeps the normal duration when not showing a call")


def main():
    for fn in (test_general_date_formula, test_includable_and_window, test_resolve_active,
               test_filter_visible, test_cold_start_seed, test_persistence,
               test_nyt_overrides, test_local_provider_autoengage,
               test_ticker_packing, test_ticker_candidate_count,
               test_called_card_winners, test_called_card_render, test_ticker_one_pass,
               test_called_duration, test_manager_resolution):
        fn()
    print(f"\n{_passed} passed, {_failed} failed")
    sys.exit(0 if _failed == 0 else 1)


if __name__ == "__main__":
    main()
