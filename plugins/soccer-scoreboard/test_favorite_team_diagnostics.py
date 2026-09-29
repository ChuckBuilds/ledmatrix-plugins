"""
Tests for the favorite-team diagnostics.

An empty screen has two very different causes that were indistinguishable from
the logs: a team code that matches nothing, or a correct code in a league with no
fixtures yet. Favourites are matched by exact ESPN abbreviation and the codes are
not guessable — ESPN calls Manchester United ``MAN``, and ``MUN`` is Bayern
Munich — so a plausible-looking code silently shows nothing.

The check itself is core's ``src.common.favorite_team_check``, tested in full
where it lives. These tests pin what is soccer's own: the messages for real
Premier League codes, and which leagues the plugin hands the check, custom
leagues included. Everything is offline.
"""

import logging
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

    # The stubs above are plain ModuleTypes, so `from src.common.X import Y`
    # fails with "'src.common' is not a package" even when a real core is on
    # the path. Giving them a __path__ lets genuine submodules -- sports_shared,
    # sports_card -- resolve from the core while the stubbed ones stay stubbed.
    # Stubbing those too would make this test pass against dummies instead of
    # the code under test.
    #
    # This file was the one of eight that never got this block, so it broke the
    # day sports.py started importing src.common.sports_shared. It looked fine
    # because the CI runner was reporting pytest files as passing without
    # running them; fixing that runner is what made these 22 failures visible.
    _core = os.environ.get("LEDMATRIX_CORE") or next(
        (p for p in sys.path
         if p and os.path.isdir(os.path.join(p, "src", "common"))), None)
    if _core:
        if "src" in sys.modules and not sys.modules["src"].__path__:
            sys.modules["src"].__path__ = [os.path.join(_core, "src")]
        if ("src.common" in sys.modules
                and not sys.modules["src.common"].__path__):
            sys.modules["src.common"].__path__ = [
                os.path.join(_core, "src", "common")]

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


class RecordingLogger(logging.Logger):
    """Captures formatted records so tests can assert on the message text."""

    def __init__(self):
        super().__init__("test")
        self.records = []

    def handle(self, record):
        self.records.append((record.levelname, record.getMessage()))

    def messages(self, level):
        return [m for lvl, m in self.records if lvl == level]


def premier_league_check(teams=None, note=None):
    """The check the plugin builds, wired to canned ESPN responses."""
    from manager import FavoriteTeamCheck

    checker = FavoriteTeamCheck(RecordingLogger(),
                                {'eng.1': ('Premier League', 'soccer/eng.1')})
    checker._fetch_teams = staticmethod(
        lambda path: dict(PREMIER_LEAGUE if teams is None else teams))
    checker._schedule_note = staticmethod(lambda path: note)
    return checker


def run(favorites, **kwargs):
    checker = premier_league_check(**kwargs)
    checker._check('eng.1', favorites)
    return checker.logger


class TestUnknownCode:
    def test_the_reported_case_suggests_the_right_code(self):
        # A user typed MUN for Manchester United, which ESPN calls MAN.
        joined = " ".join(run(['MUN']).messages('WARNING'))
        assert "'MUN' is not a Premier League team code" in joined
        assert "'MAN'" in joined and "Manchester United" in joined

    def test_all_codes_unknown_says_nothing_will_show(self):
        warnings = run(['MUN', 'MCI']).messages('WARNING')
        assert any("no recognised favorite teams" in w for w in warnings)

    def test_mixed_valid_and_invalid_reports_both(self):
        log = run(['MAN', 'MUN'])
        assert any("'MUN'" in w for w in log.messages('WARNING'))
        assert any('recognised: MAN' in i for i in log.messages('INFO'))


class TestSeasonNotStarted:
    def test_valid_code_out_of_season_explains_the_empty_screen(self):
        log = run(['MAN'], note="the league has nothing on until 21 August 2026")
        joined = " ".join(log.messages('INFO'))
        assert 'MAN' in joined and '21 August 2026' in joined
        assert 'expected, not a configuration problem' in joined
        assert log.messages('WARNING') == []

    def test_season_is_not_mentioned_when_every_code_is_wrong(self):
        # No point reporting the season when the config is the real problem.
        log = run(['MUN'], note="the league has nothing on until 21 August 2026")
        assert not any('21 August 2026' in i for i in log.messages('INFO'))


class TestSuggestions:
    @pytest.mark.parametrize('typed,expected', [
        ('MUN', 'MAN'),
        ('MCI', 'MNC'),
        ('ARSENAL', 'ARS'),
        ('TOTTENHAM', 'TOT'),
        ('Liverpool', 'LIV'),
    ])
    def test_close_matches(self, typed, expected):
        from manager import FavoriteTeamCheck
        assert "'{}'".format(expected) in FavoriteTeamCheck._suggest(typed, PREMIER_LEAGUE)

    def test_no_hint_for_something_unrelated(self):
        from manager import FavoriteTeamCheck
        assert FavoriteTeamCheck._suggest('QQQQQQ', PREMIER_LEAGUE) == ''

    def test_wrong_case_is_called_out_explicitly(self):
        from manager import FavoriteTeamCheck
        hint = FavoriteTeamCheck._suggest('liv', PREMIER_LEAGUE)
        assert 'case-sensitive' in hint and "'LIV'" in hint


def make_plugin():
    """Plugin shell with no ESPN access: scheduled checks are recorded."""
    from manager import SoccerScoreboardPlugin

    plugin = SoccerScoreboardPlugin.__new__(SoccerScoreboardPlugin)
    plugin.logger = RecordingLogger()
    return plugin


def league(enabled, **favorites_by_mode):
    managers = {mode: types.SimpleNamespace(favorite_teams=favs)
                for mode, favs in favorites_by_mode.items()}
    return {'enabled': enabled, 'managers': managers}


def scheduled(plugin, registry):
    """(league key, favorites) for each league the plugin asks the check about."""
    calls = []
    plugin._check_favorite_teams(registry)  # builds the check
    plugin._favorite_check.schedule = lambda key, favs: calls.append((key, list(favs)))
    plugin._check_favorite_teams(registry)
    return calls


class TestWiring:
    def test_each_enabled_league_with_favorites_is_checked(self):
        registry = {
            'eng.1': league(True, live=['MAN']),
            'esp.1': league(False, live=['RMA']),   # disabled
            'ger.1': league(True, live=[]),         # no favorites
        }
        assert scheduled(make_plugin(), registry) == [('eng.1', ['MAN'])]

    def test_favorites_come_from_the_first_mode_that_has_them(self):
        registry = {'eng.1': league(True, live=[], recent=['LIV'], upcoming=['ARS'])}
        assert scheduled(make_plugin(), registry) == [('eng.1', ['LIV'])]

    def test_every_league_maps_to_its_espn_soccer_endpoint(self):
        # A custom league's key is the ESPN code the user typed, so it is
        # checked against that league like any predefined one.
        import manager
        plugin = make_plugin()
        manager.LEAGUE_NAMES['sco.1'] = 'Scottish Premiership'
        try:
            plugin._check_favorite_teams({'eng.1': league(True), 'sco.1': league(True)})
        finally:
            manager.LEAGUE_NAMES.pop('sco.1', None)
        assert plugin._favorite_check.leagues == {
            'eng.1': ('Premier League', 'soccer/eng.1'),
            'sco.1': ('Scottish Premiership', 'soccer/sco.1'),
        }

    def test_a_broken_registry_entry_never_escapes_update(self):
        plugin = make_plugin()
        plugin._check_favorite_teams({'eng.1': None})  # must not raise
