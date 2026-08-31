"""A team whose badge is not on disk must have it fetched, without blocking.

The shipped logo set covers FBS only. An FCS opponent -- Furman, Tennessee
State, and 94 others on one live rig -- has no file, so its card drew with no
badge. Nothing was logged and nothing errored, because nothing had failed: the
file simply was not there, and the renderer's own lazy download never ran.

The request is now made where the game dict is built, using the logo URL ESPN
returns in the same payload as the game. The download itself is handed to a
shared pool:

  * inline it would block. download_missing_logo allows 30s per request, so a
    game with two missing badges could hold its own detail extraction for a
    minute and delay every scoreboard update behind it.

  * per-instance state would duplicate it. Live, recent and upcoming managers
    each build game dicts, so three of them would queue the same badge and each
    keep a private note of what failed.
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

URL = "https://a.espncdn.com/i/teamlogos/ncaa/500/231.png"


@pytest.fixture(autouse=True)
def _clear_shared_state():
    """The fetcher's records are class-level, so tests must not inherit them."""
    sports._LogoFetcher._pending.clear()
    sports._LogoFetcher._failed.clear()
    yield
    sports._LogoFetcher._pending.clear()
    sports._LogoFetcher._failed.clear()


class _Manager(sports.SportsCore):
    """Concrete SportsCore so the real method can be exercised.

    SportsCore.__init__ is deliberately not called: it builds HTTP sessions,
    fonts and a display manager, none of which this method touches.
    """

    def __init__(self):                      # pylint: disable=super-init-not-called
        self.sport_key = "ncaa_fb"
        self.logger = Mock()

    def _extract_game_details(self, game_event):
        return None

    def _fetch_data(self):
        return None


def _game(tmp_path, abbr="FUR"):
    return {
        "home_abbr": abbr,
        "home_id": "231",
        "home_logo_path": tmp_path / ("%s.png" % abbr),
        "home_logo_url": URL,
        "away_abbr": None,          # exercise one side only
        "away_logo_path": None,
    }


class TestWhatTheGameAsksFor:
    """_ensure_team_logos decides whether to ask; it must never download."""

    def test_an_existing_badge_is_not_requested(self, tmp_path):
        (tmp_path / "FUR.png").write_bytes(b"png")
        with patch.object(sports._LogoFetcher, "request") as req:
            _Manager()._ensure_team_logos(_game(tmp_path))
        assert req.call_count == 0, "asked for a badge already on disk"

    def test_a_missing_badge_is_requested_with_the_url_from_the_game(self, tmp_path):
        with patch.object(sports._LogoFetcher, "request") as req:
            _Manager()._ensure_team_logos(_game(tmp_path))
        assert req.call_count == 1, "a missing badge was never requested"
        args = req.call_args[0]
        assert args[0] == "ncaa_fb"
        assert args[2] == "FUR"
        assert args[4] == URL, "the ESPN URL from the game payload was not passed through"

    def test_a_game_without_logo_fields_is_skipped(self):
        with patch.object(sports._LogoFetcher, "request") as req:
            _Manager()._ensure_team_logos({"home_abbr": None, "away_abbr": None})
        assert req.call_count == 0

    def test_the_data_thread_is_never_the_one_downloading(self, tmp_path):
        # The whole point of the split: extraction must not wait on HTTP.
        with patch.object(sports, "download_missing_logo") as dl:
            with patch.object(sports._LogoFetcher, "request"):
                _Manager()._ensure_team_logos(_game(tmp_path))
        assert dl.call_count == 0, "download ran on the calling thread"


class TestTheSharedFetcher:
    def _wait(self, future):
        assert future is not None, "request was skipped when it should have run"
        return future.result(timeout=10)

    def test_it_downloads_and_reports_success(self, tmp_path):
        def fake(sport_key, team_id, abbr, path, url):
            Path(path).write_bytes(b"png")
            return True

        with patch.object(sports, "download_missing_logo", side_effect=fake) as dl:
            fut = sports._LogoFetcher.request(
                "ncaa_fb", "231", "FUR", tmp_path / "FUR.png", URL, Mock())
            assert self._wait(fut) is True
        assert dl.call_count == 1
        assert ("ncaa_fb", "FUR") not in sports._LogoFetcher._failed

    def test_a_second_manager_does_not_queue_the_same_badge(self, tmp_path):
        # Live, recent and upcoming all build game dicts for the same game.
        def writes_it(sport_key, team_id, abbr, path, url):
            Path(path).write_bytes(b"png")
            return True

        with patch.object(sports, "download_missing_logo", side_effect=writes_it) as dl:
            first = sports._LogoFetcher.request(
                "ncaa_fb", "231", "FUR", tmp_path / "FUR.png", URL, Mock())
            second = sports._LogoFetcher.request(
                "ncaa_fb", "231", "FUR", tmp_path / "FUR.png", URL, Mock())
            assert second is None, "a second manager queued a badge already in flight"
            self._wait(first)
        assert dl.call_count == 1

    def test_a_genuine_failure_is_not_retried(self, tmp_path):
        with patch.object(sports, "download_missing_logo", return_value=False) as dl:
            self._wait(sports._LogoFetcher.request(
                "ncaa_fb", "231", "FUR", tmp_path / "FUR.png", URL, Mock()))
            again = sports._LogoFetcher.request(
                "ncaa_fb", "231", "FUR", tmp_path / "FUR.png", URL, Mock())
        assert again is None, "kept asking for a badge that cannot be fetched"
        assert dl.call_count == 1

    def test_losing_the_race_is_not_recorded_as_a_failure(self, tmp_path):
        # Our own call reports failure, but the file is there -- someone else
        # wrote it. Blacklisting would discard a badge that exists.
        def written_by_someone_else(sport_key, team_id, abbr, path, url):
            Path(path).write_bytes(b"png")
            return False

        with patch.object(sports, "download_missing_logo",
                          side_effect=written_by_someone_else):
            assert self._wait(sports._LogoFetcher.request(
                "ncaa_fb", "231", "FUR", tmp_path / "FUR.png", URL, Mock())) is True
        assert ("ncaa_fb", "FUR") not in sports._LogoFetcher._failed

    def test_a_raising_downloader_is_contained(self, tmp_path):
        with patch.object(sports, "download_missing_logo", side_effect=OSError("boom")):
            assert self._wait(sports._LogoFetcher.request(
                "ncaa_fb", "231", "FUR", tmp_path / "FUR.png", URL, Mock())) is False
        assert ("ncaa_fb", "FUR") in sports._LogoFetcher._failed

    def test_failures_are_namespaced_by_sport(self, tmp_path):
        # Two leagues can use the same abbreviation.
        with patch.object(sports, "download_missing_logo", return_value=False):
            self._wait(sports._LogoFetcher.request(
                "ncaa_fb", "231", "FUR", tmp_path / "FUR.png", URL, Mock()))
        with patch.object(sports, "download_missing_logo", return_value=False) as dl:
            other = sports._LogoFetcher.request(
                "nfl", "231", "FUR", tmp_path / "nfl_FUR.png", URL, Mock())
            assert other is not None, "one sport's failure blocked another's badge"
            self._wait(other)
            assert dl.call_count == 1
