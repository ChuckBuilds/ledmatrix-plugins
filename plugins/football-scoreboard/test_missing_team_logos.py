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
import logging
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

PLUGIN_DIR = Path(__file__).resolve().parent
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))

sports = pytest.importorskip("sports")

logging.basicConfig(level=logging.ERROR)


class _Manager(sports.SportsCore):
    """Concrete SportsCore so the real method can be exercised.

    SportsCore.__init__ is deliberately not called: it builds HTTP sessions,
    fonts and a display manager, none of which this method touches. Only the
    three attributes _ensure_team_logos actually reads are set.
    """

    def __init__(self):                      # pylint: disable=super-init-not-called
        self.sport_key = "ncaa_fb"
        self._logo_fetch_failed = set()
        self.logger = Mock()

    def _extract_game_details(self, game_event):
        return None

    def _fetch_data(self):
        return None


def _manager():
    return _Manager()


def _game(tmp_path, abbr="FUR", url="https://a.espncdn.com/i/teamlogos/ncaa/500/231.png"):
    return {
        "home_abbr": abbr,
        "home_id": "231",
        "home_logo_path": tmp_path / ("%s.png" % abbr),
        "home_logo_url": url,
        "away_abbr": None,          # exercise one side only
        "away_logo_path": None,
    }


def test_an_existing_badge_is_not_refetched(tmp_path):
    (tmp_path / "FUR.png").write_bytes(b"png")
    m = _manager()
    with patch.object(sports, "download_missing_logo") as dl:
        m._ensure_team_logos(_game(tmp_path))
    assert dl.call_count == 0, "re-downloaded a badge already on disk"


def test_a_missing_badge_is_fetched_with_the_url_from_the_game(tmp_path):
    m = _manager()

    def fake(sport_key, team_id, abbr, path, url):
        Path(path).write_bytes(b"png")
        return True

    with patch.object(sports, "download_missing_logo", side_effect=fake) as dl:
        m._ensure_team_logos(_game(tmp_path))
    assert dl.call_count == 1, "a missing badge was never requested"
    args = dl.call_args[0]
    assert args[2] == "FUR"
    assert args[4] == "https://a.espncdn.com/i/teamlogos/ncaa/500/231.png", \
        "the ESPN URL from the game payload was not passed through"
    assert m._logo_fetch_failed == set()


def test_a_genuine_failure_is_not_retried_forever(tmp_path):
    m = _manager()
    with patch.object(sports, "download_missing_logo", return_value=False) as dl:
        m._ensure_team_logos(_game(tmp_path))
        m._ensure_team_logos(_game(tmp_path))
    assert dl.call_count == 1, "kept requesting a badge that cannot be fetched"
    assert "FUR" in m._logo_fetch_failed


def test_losing_the_race_is_not_recorded_as_a_failure(tmp_path):
    # Another manager wrote the file while this call was in flight. The badge is
    # there; treating it as a failure would blacklist a logo that now exists.
    m = _manager()

    def written_by_someone_else(sport_key, team_id, abbr, path, url):
        Path(path).write_bytes(b"png")
        return False            # our own download reports failure

    with patch.object(sports, "download_missing_logo", side_effect=written_by_someone_else):
        m._ensure_team_logos(_game(tmp_path))

    assert m._logo_fetch_failed == set(), "blacklisted a team whose badge is on disk"


def test_a_raising_downloader_does_not_break_the_game(tmp_path):
    m = _manager()
    with patch.object(sports, "download_missing_logo", side_effect=OSError("boom")):
        m._ensure_team_logos(_game(tmp_path))       # must not propagate
    assert "FUR" in m._logo_fetch_failed


def test_a_game_without_logo_fields_is_skipped(tmp_path):
    m = _manager()
    with patch.object(sports, "download_missing_logo") as dl:
        m._ensure_team_logos({"home_abbr": None, "away_abbr": None})
    assert dl.call_count == 0
