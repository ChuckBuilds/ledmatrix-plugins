#!/usr/bin/env python3
"""Data-path fixes ported from sibling scoreboards.

  * A cached {"no_odds": True} marker is a cache hit: get_odds returns None
    without calling ESPN again (it refetched on every call until expiry).
  * The rankings shortcut skips tournament / lower-division polls instead of
    trusting ESPN's block order (data["rankings"][0]).
  * get_vegas_content rebuilds when the game slate changes, reads only the
    dedicated 'mixed' display, and never calls update() on the render path.
  * sports.py uses the core logo downloader (whose placeholders carry the
    refresh marker), and the bundled fallback refuses to save a non-image body.

Run: <core-venv>/bin/python plugins/lacrosse-scoreboard/test_data_path_drift_fixes.py
Exit 0 pass, 2 skip, anything else fail.
"""

import logging
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))

_core = os.environ.get("LEDMATRIX_CORE", "")
for _candidate in (_core, str(PLUGIN_DIR.parents[2] / "LEDMatrix")):
    if _candidate and (Path(_candidate) / "src" / "plugin_system").is_dir():
        sys.path.insert(0, _candidate)
        break
else:
    print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
    sys.exit(2)

import base_odds_manager  # noqa: E402
import dynamic_team_resolver  # noqa: E402
import logo_downloader  # noqa: E402
import manager as m  # noqa: E402
import sports  # noqa: E402

failures = []
LOG = logging.getLogger("lax_data_probe")
LOG.addHandler(logging.NullHandler())
LOG.propagate = False


def check(name, cond, detail=""):
    print("  %s  %s%s" % ("PASS" if cond else "FAIL", name,
                          "" if cond else (": " + str(detail))))
    if not cond:
        failures.append(name)


def test_no_odds_marker_is_a_cache_hit():
    mgr = base_odds_manager.BaseOddsManager.__new__(base_odds_manager.BaseOddsManager)
    mgr.logger = LOG
    mgr.update_interval = 3600
    mgr.request_timeout = 5
    mgr.base_url = "https://example.invalid"
    mgr.cache_manager = MagicMock()
    mgr.cache_manager.get.return_value = {"no_odds": True}
    with patch.object(base_odds_manager.requests, "get",
                      side_effect=AssertionError("network called")) as get:
        try:
            result = mgr.get_odds("lacrosse", "mens-college-lacrosse", "123")
        except AssertionError as exc:
            result = exc
    check("cached no_odds marker returns None", result is None, result)
    check("... without calling ESPN", not get.called)


class _Resp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def test_rankings_skip_non_top_polls():
    r = dynamic_team_resolver.DynamicTeamResolver(request_timeout=5)
    r.logger = LOG
    data = {"rankings": [
        {"name": "NCAA Tournament Seedings", "type": "tournament",
         "ranks": [{"team": {"abbreviation": "SEED1"}}]},
        {"name": "Division II Poll", "type": "poll",
         "ranks": [{"team": {"abbreviation": "D2A"}}]},
        {"name": "Inside Lacrosse Poll", "type": "poll",
         "ranks": [{"team": {"abbreviation": "ND"}}, {"team": {"abbreviation": "DUKE"}}]},
    ]}
    with patch.object(dynamic_team_resolver.requests, "get", return_value=_Resp(data)):
        teams = r._fetch_rankings("ncaa_mens_lacrosse")
    check("top-N resolves from the first top-division poll",
          teams == ["ND", "DUKE"], teams)


class _FakeScroll:
    def __init__(self):
        self.items = {}
        self.builds = 0

    def get_vegas_content_items_for(self, key):
        return list(self.items.get(key, []))

    def get_all_vegas_content_items(self):
        return [object()]  # a stale standalone strip that must be ignored

    def prepare_content(self, games, key, leagues, rankings):
        self.builds += 1
        img = MagicMock()
        img.width = 100
        self.items[key] = [img for _ in games]
        return True


def test_vegas_rebuilds_on_change_without_update():
    p = m.LacrosseScoreboardPlugin.__new__(m.LacrosseScoreboardPlugin)
    p.logger = LOG
    p._scroll_manager = _FakeScroll()
    p._vegas_signature = None
    p.update = MagicMock(side_effect=AssertionError("update() on render path"))
    slate = [{"id": "1", "home_abbr": "ND", "away_abbr": "DUKE", "home_score": 3,
              "away_score": 2, "status": {"state": "in"}, "league": "ncaam_lacrosse"}]
    p._collect_games_for_scroll = lambda: ([dict(g) for g in slate], ["ncaam_lacrosse"])

    first = p.get_vegas_content()
    check("first call builds the mixed slate", p._scroll_manager.builds == 1
          and first and len(first) == 1, (p._scroll_manager.builds, first))
    p.get_vegas_content()
    check("unchanged slate is served from cache", p._scroll_manager.builds == 1,
          p._scroll_manager.builds)
    slate[0]["home_score"] = 4
    p.get_vegas_content()
    check("a score change rebuilds the cards", p._scroll_manager.builds == 2,
          p._scroll_manager.builds)
    check("update() is never called", not p.update.called)


def test_logo_downloader_choice():
    try:
        import src.logo_downloader as core_ld
    except ImportError:
        print("  (core has no src.logo_downloader; skipping)")
        return
    check("sports.py uses the core LogoDownloader",
          sports.LogoDownloader is core_ld.LogoDownloader)
    check("bundled downloader rejects an HTML body",
          not logo_downloader._is_image_body(b"<html>503</html>"))
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGBA", (4, 4)).save(buf, format="PNG")
    check("bundled downloader accepts a PNG body",
          logo_downloader._is_image_body(buf.getvalue()))


if __name__ == "__main__":
    test_no_odds_marker_is_a_cache_hit()
    test_rankings_skip_non_top_polls()
    test_vegas_rebuilds_on_change_without_update()
    test_logo_downloader_choice()
    print("\n%d failure(s)" % len(failures))
    sys.exit(1 if failures else 0)
