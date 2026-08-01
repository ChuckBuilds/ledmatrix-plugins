"""
Tests for the favorite-team diagnostics.

An empty screen has two very different causes that were indistinguishable from
the logs: a team code that matches nothing, or a correct code in a league with no
fixtures yet. Favourites are matched by exact ESPN abbreviation and the codes are
not guessable — ESPN calls Manchester United ``MAN``, and ``MUN`` is Bayern
Munich — so a plausible-looking code silently shows nothing.
"""

import os
import sys
import types

import pytest

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

# manager.py's import chain reaches src.logo_downloader, src.background_data_service,
# src.common.scroll_helper and src.plugin_system.base_plugin at module load. Stub
# them so the import succeeds; instances are built via __new__ so none is called.
# Mirrors the pattern in the plugin's other tests.
if "src.logo_downloader" not in sys.modules:
    import tempfile

    src_pkg = types.ModuleType("src")
    src_pkg.__path__ = []  # mark as a package so submodules can be registered

    logo_mod = types.ModuleType("src.logo_downloader")

    class _StubLogoDownloader:
        def get_logo_directory(self, *a, **k):
            return tempfile.gettempdir()

        def ensure_logo_directory(self, *a, **k):
            return True

    logo_mod.LogoDownloader = _StubLogoDownloader
    logo_mod.download_missing_logo = lambda *a, **k: None

    bg_mod = types.ModuleType("src.background_data_service")
    bg_mod.get_background_service = lambda *a, **k: None

    common_pkg = types.ModuleType("src.common")
    common_pkg.__path__ = []
    scroll_mod = types.ModuleType("src.common.scroll_helper")

    class _StubScrollHelper:
        def __init__(self, *a, **k):
            pass

    scroll_mod.ScrollHelper = _StubScrollHelper

    ps_pkg = types.ModuleType("src.plugin_system")
    ps_pkg.__path__ = []
    bp_mod = types.ModuleType("src.plugin_system.base_plugin")

    class _BasePlugin:
        def __init__(self, *a, **k):
            pass

    bp_mod.BasePlugin = _BasePlugin
    bp_mod.VegasDisplayMode = None

    sys.modules.update({
        "src": src_pkg,
        "src.logo_downloader": logo_mod,
        "src.background_data_service": bg_mod,
        "src.common": common_pkg,
        "src.common.scroll_helper": scroll_mod,
        "src.plugin_system": ps_pkg,
        "src.plugin_system.base_plugin": bp_mod,
    })

# ESPN's real Premier League codes, as returned by its teams endpoint.
PREMIER_LEAGUE = {
    'ARS': 'Arsenal', 'AVL': 'Aston Villa', 'BOU': 'AFC Bournemouth',
    'BRE': 'Brentford', 'BHA': 'Brighton & Hove Albion', 'CHE': 'Chelsea',
    'COV': 'Coventry City', 'CRY': 'Crystal Palace', 'EVE': 'Everton',
    'FUL': 'Fulham', 'HUL': 'Hull City', 'IPS': 'Ipswich Town',
    'LEE': 'Leeds United', 'LIV': 'Liverpool', 'MNC': 'Manchester City',
    'MAN': 'Manchester United', 'NEW': 'Newcastle United',
    'NFO': 'Nottingham Forest', 'SUN': 'Sunderland', 'TOT': 'Tottenham Hotspur',
}


class Recorder:
    def __init__(self):
        self.warnings = []
        self.infos = []

    def _fmt(self, msg, args):
        return msg % args if args else msg

    def warning(self, msg, *args, **kw):
        self.warnings.append(self._fmt(msg, args))

    def info(self, msg, *args, **kw):
        self.infos.append(self._fmt(msg, args))

    def debug(self, msg, *args, **kw):
        pass

    def error(self, msg, *args, **kw):
        pass


def make_plugin(favorites, teams=None, season_start=None, teams_raise=False):
    """Plugin shell wired to canned ESPN responses."""
    import threading
    from manager import SoccerScoreboardPlugin

    class _Shell(SoccerScoreboardPlugin):
        def __init__(self):
            pass

        def _fetch_league_teams(self, league_key):
            if teams_raise:
                raise RuntimeError("network down")
            return PREMIER_LEAGUE if teams is None else teams

        def _fetch_season_start(self, league_key):
            return season_start

    plugin = _Shell()
    plugin.logger = Recorder()
    plugin._config_lock = threading.RLock()
    plugin._favorites_checked = set()

    manager = types.SimpleNamespace(favorite_teams=favorites)
    plugin._managers = {'live': manager}
    return plugin


def check(plugin):
    plugin._check_favorite_teams('eng.1', 'Premier League', plugin._managers)
    return plugin.logger


class TestUnknownCode:
    def test_the_reported_case_suggests_the_right_code(self):
        # A user typed MUN for Manchester United, which ESPN calls MAN.
        log = check(make_plugin(['MUN']))
        joined = " ".join(log.warnings)
        assert "'MUN' is not a Premier League team code" in joined
        assert "'MAN'" in joined and "Manchester United" in joined

    def test_man_city_typo_is_also_caught(self):
        log = check(make_plugin(['MCI']))
        assert "'MNC'" in " ".join(log.warnings)

    def test_a_club_name_resolves_to_its_code(self):
        log = check(make_plugin(['Liverpool']))
        assert "'LIV'" in " ".join(log.warnings)

    def test_all_codes_unknown_says_nothing_will_show(self):
        log = check(make_plugin(['MUN', 'MCI']))
        assert any("no recognised favorite teams" in w for w in log.warnings)

    def test_nonsense_code_still_warns_without_a_suggestion(self):
        log = check(make_plugin(['ZZZZZZ']))
        assert any("is not a Premier League team code" in w for w in log.warnings)

    def test_lowercase_is_reported_since_matching_is_case_sensitive(self):
        log = check(make_plugin(['liv']))
        assert any("'liv'" in w for w in log.warnings)
        assert "'LIV'" in " ".join(log.warnings)


class TestSeasonNotStarted:
    def test_valid_code_with_no_fixtures_names_the_start_date(self):
        log = check(make_plugin(['MAN'], season_start='21 August 2026'))
        joined = " ".join(log.infos)
        assert 'MAN' in joined
        assert '21 August 2026' in joined
        assert 'expected, not a configuration problem' in joined

    def test_no_warning_when_the_code_is_valid(self):
        log = check(make_plugin(['MAN'], season_start='21 August 2026'))
        assert log.warnings == []

    def test_valid_code_with_fixtures_reports_plainly(self):
        log = check(make_plugin(['MAN'], season_start=None))
        assert any('recognised' in i for i in log.infos)
        assert log.warnings == []

    def test_season_check_is_skipped_when_every_code_is_wrong(self):
        # No point reporting the season when the config is the real problem.
        log = check(make_plugin(['MUN'], season_start='21 August 2026'))
        assert not any('21 August 2026' in i for i in log.infos)


class TestRobustness:
    def test_runs_once_per_league(self):
        plugin = make_plugin(['MUN'])
        for _ in range(4):
            plugin._check_favorite_teams('eng.1', 'Premier League', plugin._managers)
        assert len(plugin.logger.warnings) == 2  # one per-code, one summary

    def test_no_favorites_is_silent(self):
        log = check(make_plugin([]))
        assert log.warnings == [] and log.infos == []

    def test_a_failed_fetch_is_silent_and_not_retried(self):
        plugin = make_plugin(['MUN'], teams_raise=True)
        plugin._check_favorite_teams('eng.1', 'Premier League', plugin._managers)
        assert plugin.logger.warnings == []
        assert 'eng.1' in plugin._favorites_checked

    def test_empty_team_list_is_silent(self):
        log = check(make_plugin(['MUN'], teams={}))
        assert log.warnings == []

    def test_mixed_valid_and_invalid_reports_both(self):
        log = check(make_plugin(['MAN', 'MUN'], season_start=None))
        assert any("'MUN'" in w for w in log.warnings)
        assert any('MAN' in i for i in log.infos)


class TestSuggestions:
    @pytest.mark.parametrize('typed,expected', [
        ('MUN', 'MAN'),
        ('MCI', 'MNC'),
        ('ARSENAL', 'ARS'),
        ('TOTTENHAM', 'TOT'),
    ])
    def test_close_matches(self, typed, expected):
        from manager import SoccerScoreboardPlugin
        hint = SoccerScoreboardPlugin._suggest_team_code(typed, PREMIER_LEAGUE)
        assert expected in hint

    def test_no_hint_for_something_unrelated(self):
        from manager import SoccerScoreboardPlugin
        assert SoccerScoreboardPlugin._suggest_team_code('QQQQQQ', PREMIER_LEAGUE) == ''

    def test_a_valid_code_draws_no_suggestion(self):
        # Only unknown codes reach the suggester in production, but a valid one
        # must not be told its case is wrong.
        from manager import SoccerScoreboardPlugin
        assert SoccerScoreboardPlugin._suggest_team_code('LIV', PREMIER_LEAGUE) == ''

    def test_wrong_case_is_called_out_explicitly(self):
        from manager import SoccerScoreboardPlugin
        hint = SoccerScoreboardPlugin._suggest_team_code('liv', PREMIER_LEAGUE)
        assert 'case-sensitive' in hint and "'LIV'" in hint
