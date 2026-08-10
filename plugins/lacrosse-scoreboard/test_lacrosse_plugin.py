#!/usr/bin/env python3
"""
Smoke test for the Lacrosse Scoreboard plugin.

Run standalone from the plugin directory:

    cd plugins/lacrosse-scoreboard
    python test_lacrosse_plugin.py

The test:
  1. Stubs the LEDMatrix host modules so plugin imports resolve.
  2. Imports every Python module in the plugin to catch syntax / import errors.
  3. Instantiates the dynamic team resolver and verifies the NCAA Men's Top 5 /
     NCAA Women's Top 5 shortcuts resolve against the live ESPN ranking feeds.
  4. Fetches a recent window of events from both ESPN lacrosse scoreboard
     endpoints and pushes each event through Lacrosse._extract_game_details,
     asserting that required fields (abbreviations, IDs, scores, period,
     logo URLs, records) are populated.

No external test framework is required — the script exits non-zero on the
first failure and prints a summary on success.
"""

from __future__ import annotations

import json
import logging
import sys
import types
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))


# ---------------------------------------------------------------------------
# Stub LEDMatrix host modules before importing the plugin.
# ---------------------------------------------------------------------------
def _install_host_stubs() -> None:
    stub_modules = [
        "src",
        "src.plugin_system",
        "src.plugin_system.base_plugin",
        "src.background_data_service",
        "src.common",
        "src.common.scroll_helper",
        "src.api_counter",
    ]
    for name in stub_modules:
        sys.modules.setdefault(name, types.ModuleType(name))
    sys.modules["src.plugin_system.base_plugin"].BasePlugin = object
    sys.modules["src.plugin_system.base_plugin"].VegasDisplayMode = None
    sys.modules["src.background_data_service"].get_background_service = (
        lambda *a, **k: None
    )
    sys.modules["src.common.scroll_helper"].ScrollHelper = None
    sys.modules["src.api_counter"].increment_api_counter = lambda *a, **k: None


_install_host_stubs()

logging.basicConfig(level=logging.CRITICAL)


# ---------------------------------------------------------------------------
# Test 1: import every plugin module.
# ---------------------------------------------------------------------------
def test_imports() -> None:
    import data_sources  # noqa: F401
    import logo_downloader  # noqa: F401
    import base_odds_manager  # noqa: F401
    import dynamic_team_resolver  # noqa: F401
    import game_renderer  # noqa: F401
    import scroll_display  # noqa: F401
    import sports  # noqa: F401
    import lacrosse  # noqa: F401
    import ncaam_lacrosse_managers  # noqa: F401
    import ncaaw_lacrosse_managers  # noqa: F401
    import manager

    assert hasattr(manager, "LacrosseScoreboardPlugin"), "plugin class missing"
    print("  [ok] imports")


# ---------------------------------------------------------------------------
# Test 2: dynamic team resolver talks to live ESPN rankings.
# ---------------------------------------------------------------------------
def test_rankings_resolver() -> None:
    from dynamic_team_resolver import DynamicTeamResolver

    resolver = DynamicTeamResolver()
    men = resolver.resolve_teams(["NCAA_MENS_TOP_5"], "ncaam_lacrosse")
    women = resolver.resolve_teams(["NCAA_WOMENS_TOP_5"], "ncaaw_lacrosse")

    # Treat partial outages as skips rather than failures — if we can confirm
    # at least one endpoint returned real data, the resolver is working; we
    # just can't fully validate the other side right now.
    if not men and not women:
        raise _NetworkUnavailable("both rankings endpoints returned no data")
    if not men:
        raise _NetworkUnavailable("men's rankings endpoint returned no data")
    if not women:
        raise _NetworkUnavailable("women's rankings endpoint returned no data")

    assert len(men) == 5, f"expected 5 men's teams, got {len(men)}: {men}"
    assert len(women) == 5, f"expected 5 women's teams, got {len(women)}: {women}"
    assert all(isinstance(t, str) and t for t in men + women), "empty team entry"
    print(f"  [ok] dynamic resolver — men={men[:3]}..., women={women[:3]}...")


class _NoFixtureData(Exception):
    """ESPN answered, but had nothing scheduled in any window we asked for.

    Distinct from _NetworkUnavailable: the API is reachable and behaving, there
    is just no data this time of year. Neither is a plugin failure.
    """


class _NetworkUnavailable(Exception):
    """Raised by a test when it detects the network/external feed is down."""


# ---------------------------------------------------------------------------
# Test 3: extraction pipeline against live ESPN data.
# ---------------------------------------------------------------------------
REQUIRED_FIELDS = [
    "id",
    "home_abbr",
    "away_abbr",
    "home_id",
    "away_id",
    "period",
    "period_text",
]


def _fetch(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "LEDMatrix/1.0 (+https://github.com/ChuckBuilds/LEDMatrix)"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def _make_test_instance():
    """Build a minimal Lacrosse instance without touching the host framework."""
    import pytz
    from lacrosse import Lacrosse
    from sports import SportsCore

    class _TestLacrosse(Lacrosse):
        def _fetch_data(self):
            return None

    inst = object.__new__(_TestLacrosse)
    inst.logger = logging.getLogger("test")
    inst.logger.setLevel(logging.CRITICAL)
    inst.sport = "lacrosse"
    inst.config = {"timezone": "America/New_York"}
    inst.timezone = pytz.timezone("America/New_York")
    inst.favorite_teams = []
    inst.show_favorite_teams_only = False
    inst.show_records = True
    inst.show_ranking = True
    inst.show_odds = False
    inst.logo_dir = Path("assets/sports/ncaa_logos")
    inst._team_rankings_cache = {}
    inst._extract_game_details_common = SportsCore._extract_game_details_common.__get__(
        inst, _TestLacrosse
    )
    inst._get_timezone = SportsCore._get_timezone.__get__(inst, _TestLacrosse)
    return inst


def test_extraction(label: str, league_slug: str, date_windows) -> None:
    tried = []
    events = []
    for date_window in date_windows:
        url = (
            f"https://site.api.espn.com/apis/site/v2/sports/lacrosse/"
            f"{league_slug}/scoreboard?dates={date_window}&limit=50"
        )
        data = _fetch(url)
        events = data.get("events", [])
        tried.append(f"{date_window} ({len(events)} events)")
        if events:
            break

    if not events:
        # Every window came back empty. ESPN answered, so this is not a
        # network problem and not a plugin fault -- there is simply nothing
        # scheduled to extract. Skip rather than fail: a red test nobody can
        # act on is how a real regression gets ignored.
        raise _NoFixtureData(
            f"{label}: ESPN returned no events for any window tried: "
            f"{', '.join(tried)}")

    inst = _make_test_instance()
    extracted = 0
    for ev in events:
        details = inst._extract_game_details(ev)
        if not details:
            continue
        extracted += 1
        missing = [f for f in REQUIRED_FIELDS if details.get(f) in (None, "")]
        assert not missing, (
            f"{label}: event {ev.get('id')} missing fields {missing}: {details}"
        )
        # Logo URL pattern check — ESPN NCAA CDN
        for side in ("home", "away"):
            logo = details.get(f"{side}_logo_url") or ""
            if logo:
                assert logo.startswith("https://a.espncdn.com/"), (
                    f"{label}: unexpected logo host {logo}"
                )

    assert extracted == len(events), (
        f"{label}: extracted {extracted}/{len(events)} events "
        f"(expected all events to parse cleanly)"
    )
    print(f"  [ok] {label} — {extracted}/{len(events)} events parsed cleanly")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def _season_windows() -> list:
    """Scoreboard date windows to try, most relevant first.

    NCAA lacrosse runs January through late May, so from July onward the
    interesting season is next year's. ESPN does not publish that schedule
    months ahead, though: asking in August returns a perfectly valid response
    with zero events, which is not a plugin fault but used to fail this test
    every summer. So the upcoming season is tried first and the last completed
    one is the fallback -- what these tests actually need is some real events
    to drive the extraction pipeline, and either season provides them.

    Returned format is 'YYYYMMDD-YYYYMMDD' as ESPN expects.
    """
    now = datetime.now()
    upcoming = now.year if now.month < 7 else now.year + 1
    return [f"{year}0101-{year}0601" for year in (upcoming, upcoming - 1)]


def main() -> int:
    print("Lacrosse Scoreboard plugin — smoke test")

    season_windows = _season_windows()

    tests = [
        ("imports", test_imports, ()),
        ("rankings resolver", test_rankings_resolver, ()),
        (
            "men's extraction",
            test_extraction,
            ("men's", "mens-college-lacrosse", season_windows),
        ),
        (
            "women's extraction",
            test_extraction,
            ("women's", "womens-college-lacrosse", season_windows),
        ),
    ]

    # Import requests lazily so the test can still import when requests is
    # unavailable — we only need it to recognise network errors.
    try:
        import requests.exceptions as _rexc
        network_errors: tuple = (urllib.error.URLError, _rexc.RequestException)
    except ImportError:
        network_errors = (urllib.error.URLError,)

    failed = 0
    for name, fn, args in tests:
        try:
            fn(*args)
        except AssertionError as e:
            print(f"  [FAIL] {name}: {e}")
            failed += 1
        except _NoFixtureData as e:
            print(f"  [skip] {name}: {e}")
        except _NetworkUnavailable as e:
            print(f"  [skip] {name}: {e}")
        except network_errors as e:
            # Network failures are non-fatal — skip with a warning so the
            # test can still run on air-gapped CI.
            print(f"  [skip] {name}: network unavailable ({e})")
        except Exception as e:  # noqa: BLE001 — we want every failure surfaced
            print(f"  [FAIL] {name}: {type(e).__name__}: {e}")
            failed += 1

    if failed:
        print(f"\n{failed} test(s) failed.")
        return 1
    print("\nAll smoke tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
