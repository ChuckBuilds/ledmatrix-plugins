import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from manager import HockeyScoreboardPlugin


class DummyImage:
    def paste(self, *args, **kwargs):
        pass


class DummyDisplay:
    display_width = 128
    display_height = 32

    def __init__(self):
        self.image = DummyImage()

    def clear(self):
        pass

    def update_display(self):
        pass


class DummyCache:
    def __init__(self):
        self.config_manager = MagicMock()
        self.config_manager.get_timezone.return_value = "UTC"
        self.config_manager.get_display_config.return_value = {}

    def get(self, *args, **kwargs):
        return None

    def set(self, *args, **kwargs):
        pass

    def clear_cache(self, *args, **kwargs):
        pass


class HockeyConfigAdapterTests(unittest.TestCase):
    def setUp(self):
        self.display = DummyDisplay()
        self.cache = DummyCache()
        self.plugin_manager = MagicMock()

    @patch("manager.get_background_service", autospec=True)
    def test_favorite_team_filter_defaults(self, mock_background_service):
        mock_background_service.return_value = MagicMock()

        config = {
            "enabled": True,
            "display_duration": 10,
            "nhl": {
                "enabled": True,
                "favorite_teams": ["TB"],
                "favorite_teams_only": True,
                "display_modes": {
                    "live": True,
                    "recent": False,
                    "upcoming": False,
                },
                "game_rotation_interval_seconds": 9,
            },
        }

        plugin = HockeyScoreboardPlugin(
            plugin_id="hockey-scoreboard",
            config=config,
            display_manager=self.display,
            cache_manager=self.cache,
            plugin_manager=self.plugin_manager,
        )

        self.assertTrue(plugin.nhl_live.show_favorite_teams_only)
        self.assertFalse(
            plugin.nhl_live.show_all_live,
            msg="show_all_live should remain disabled when only favorites are requested",
        )
        self.assertEqual(
            plugin.modes,
            ["nhl_live"],
            msg="Only live mode should be enabled when recent/upcoming are disabled",
        )
        self.assertEqual(
            plugin.nhl_live.game_display_duration,
            9,
            msg="Fallback duration should honour game_rotation_interval_seconds",
        )

    @patch("manager.get_background_service", autospec=True)
    def test_manager_auto_refresh_runs_when_stale(self, mock_background_service):
        mock_background_service.return_value = MagicMock()

        config = {
            "enabled": True,
            "nhl": {
                "enabled": True,
                "display_modes": {"live": True},
            },
        }

        plugin = HockeyScoreboardPlugin(
            plugin_id="hockey-scoreboard",
            config=config,
            display_manager=self.display,
            cache_manager=self.cache,
            plugin_manager=self.plugin_manager,
        )

        manager = plugin.nhl_live
        manager.update = MagicMock()
        manager.last_update = time.time() - (manager.update_interval + 1)
        manager.live_games = [{}]  # ensure update interval is used instead of no-data interval

        plugin._ensure_manager_updated(manager)
        manager.update.assert_called_once()


if __name__ == "__main__":
    unittest.main()

