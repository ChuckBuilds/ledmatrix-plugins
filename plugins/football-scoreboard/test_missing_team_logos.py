"""A team whose badge is not on disk must have it fetched.

The shipped logo set covers FBS only. An FCS opponent -- Furman, Tennessee
State, and 94 others on one live rig -- has no file, so its card drew with no
badge. Nothing was logged and nothing errored, because nothing had failed: the
file simply was not there, and the renderer's own lazy download never ran.

The fetch now happens where the game dict is built, on the data thread. ESPN
returns the logo URL in the same payload as the game, so the moment a team is
known to be showing, its badge URL is already in hand -- and the download stays
off the render thread, where an HTTP round trip stalls the panel.

Three managers (live, recent, upcoming) build game dicts, so two can want the
same badge at once. The one that loses that race must not record a permanent
failure for a logo the winner just wrote.
"""
import sys
import types
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))


def _load_method():
    """Pull _ensure_team_logos off sports.py without importing the world."""
    import ast

    src = (PLUGIN_DIR / "sports.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "_ensure_team_logos"), None)
    if fn is None:
        pytest.fail("_ensure_team_logos is gone; missing badges will not be fetched")
    module = types.ModuleType("_extracted")
    module.__dict__.update({"Path": Path, "download_missing_logo": None})
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "sports.py", "exec"), module.__dict__)
    return module


MOD = _load_method()


class _Manager:
    """Minimal stand-in carrying just what the method touches."""

    _ensure_team_logos = MOD.__dict__["_ensure_team_logos"]

    def __init__(self):
        self.sport_key = "ncaa_fb"
        self._logo_fetch_failed = set()
        self.logger = Mock()


def _game(tmp_path, abbr="FUR", url="https://espncdn/231.png"):
    return {
        "home_abbr": abbr,
        "home_id": "231",
        "home_logo_path": tmp_path / f"{abbr}.png",
        "home_logo_url": url,
        "away_abbr": None,          # only exercise one side
        "away_logo_path": None,
    }


def test_an_existing_badge_is_not_refetched(tmp_path):
    (tmp_path / "FUR.png").write_bytes(b"png")
    m = _Manager()
    with patch.object(MOD, "download_missing_logo") as dl:
        m._ensure_team_logos(_game(tmp_path))
        assert dl.call_count == 0, "re-downloaded a badge already on disk"


def test_a_missing_badge_is_fetched_with_the_url_from_the_game(tmp_path):
    m = _Manager()

    def fake(sport_key, team_id, abbr, path, url):
        Path(path).write_bytes(b"png")
        return True

    with patch.object(MOD, "download_missing_logo", side_effect=fake) as dl:
        m._ensure_team_logos(_game(tmp_path))
        assert dl.call_count == 1, "a missing badge was never requested"
        args = dl.call_args[0]
        assert args[2] == "FUR"
        assert args[4] == "https://espncdn/231.png", "the ESPN URL was not passed through"
    assert m._logo_fetch_failed == set()


def test_a_genuine_failure_is_not_retried_forever(tmp_path):
    m = _Manager()
    with patch.object(MOD, "download_missing_logo", return_value=False) as dl:
        m._ensure_team_logos(_game(tmp_path))
        m._ensure_team_logos(_game(tmp_path))
        assert dl.call_count == 1, "kept requesting a badge that cannot be fetched"
    assert "FUR" in m._logo_fetch_failed


def test_losing_the_race_is_not_recorded_as_a_failure(tmp_path):
    # Another manager wrote the file while this call was in flight. The badge is
    # there; treating it as a failure would blacklist a logo that now exists.
    m = _Manager()

    def wrote_by_someone_else(sport_key, team_id, abbr, path, url):
        Path(path).write_bytes(b"png")
        return False          # our own download reports failure

    with patch.object(MOD, "download_missing_logo", side_effect=wrote_by_someone_else):
        m._ensure_team_logos(_game(tmp_path))

    assert m._logo_fetch_failed == set(), \
        "blacklisted a team whose badge is on disk"


def test_a_raising_downloader_does_not_break_the_game(tmp_path):
    m = _Manager()
    with patch.object(MOD, "download_missing_logo", side_effect=OSError("boom")):
        m._ensure_team_logos(_game(tmp_path))   # must not propagate
    assert "FUR" in m._logo_fetch_failed


def test_a_game_without_logo_fields_is_skipped(tmp_path):
    m = _Manager()
    with patch.object(MOD, "download_missing_logo") as dl:
        m._ensure_team_logos({"home_abbr": None, "away_abbr": None})
        assert dl.call_count == 0
