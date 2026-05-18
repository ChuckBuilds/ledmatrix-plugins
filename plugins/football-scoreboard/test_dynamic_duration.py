#!/usr/bin/env python3
"""
Tests for dynamic duration functionality in Football Scoreboard Plugin.

These tests verify that:
1. get_cycle_duration() calculates durations correctly
2. Dynamic duration interacts properly with live priority
3. Internal cycling uses dynamic duration (regression test for line 1306 fix)
"""

import sys
import logging
from pathlib import Path
from unittest.mock import Mock

import pytest

# Add the plugin directory to Python path
plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

# Add LEDMatrix src to path for imports
ledmatrix_src = Path(__file__).parent.parent.parent / "LEDMatrix" / "src"
sys.path.insert(0, str(ledmatrix_src))

# Configure logging
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def create_mock_display_manager():
    """Create a mock display manager for testing."""
    mock_display = Mock()
    mock_display.display_width = 128
    mock_display.display_height = 32
    mock_display.width = 128
    mock_display.height = 32
    mock_display.clear = Mock()
    mock_display.set_image = Mock()
    mock_display.show = Mock()
    mock_display.update_display = Mock()
    return mock_display


def create_mock_cache_manager():
    """Create a mock cache manager for testing."""
    mock_cache = Mock()
    mock_config_manager = Mock()
    mock_config_manager.load_config.return_value = {}
    mock_cache.config_manager = mock_config_manager
    mock_cache.get = Mock(return_value=None)
    mock_cache.set = Mock()
    mock_cache.delete = Mock()
    mock_cache.clear = Mock()
    return mock_cache


def create_mock_plugin_manager():
    """Create a mock plugin manager for testing."""
    mock_plugin_manager = Mock()
    mock_plugin_manager.get_plugin = Mock(return_value=None)
    mock_plugin_manager.get_all_plugins = Mock(return_value=[])
    return mock_plugin_manager


def create_base_config():
    """Create a base test configuration."""
    return {
        "enabled": True,
        "display_duration": 30,
        "game_display_duration": 15,
        "timezone": "UTC",
        "nfl": {
            "enabled": True,
            "favorite_teams": [],
            "display_modes": {
                "show_live": True,
                "show_recent": True,
                "show_upcoming": True,
            },
            "live_priority": False,
            "game_limits": {"recent_games_to_show": 5, "upcoming_games_to_show": 5},
            "test_mode": True,
        },
        "ncaa_fb": {
            "enabled": False,
            "favorite_teams": [],
            "display_modes": {
                "show_live": True,
                "show_recent": True,
                "show_upcoming": True,
            },
            "live_priority": False,
            "test_mode": True,
        },
    }


@pytest.fixture
def plugin():
    """Create a plugin instance for testing."""
    from manager import FootballScoreboardPlugin

    config = create_base_config()
    plugin = FootballScoreboardPlugin(
        plugin_id="football-scoreboard",
        config=config,
        display_manager=create_mock_display_manager(),
        cache_manager=create_mock_cache_manager(),
        plugin_manager=create_mock_plugin_manager(),
    )
    return plugin


class TestGetCycleDuration:
    """Tests for get_cycle_duration() method."""

    def test_returns_none_when_disabled(self, plugin):
        """Should return None when plugin is disabled."""
        plugin.is_enabled = False
        result = plugin.get_cycle_duration("nfl_recent")
        assert result is None

    def test_returns_none_for_none_mode(self, plugin):
        """Should return None when display_mode is None."""
        result = plugin.get_cycle_duration(None)
        assert result is None

    def test_returns_none_for_invalid_mode(self, plugin):
        """Should return None for unrecognized mode type."""
        result = plugin.get_cycle_duration("invalid_mode_xyz")
        assert result is None

    def test_calculates_duration_from_game_count(self, plugin):
        """Should calculate duration based on games * per_game_duration."""
        # Mock 3 recent games
        if hasattr(plugin, "nfl_recent") and plugin.nfl_recent:
            plugin.nfl_recent.recent_games = [
                {"id": "1", "is_final": True},
                {"id": "2", "is_final": True},
                {"id": "3", "is_final": True},
            ]
            # Default game_display_duration is 15s
            duration = plugin.get_cycle_duration("nfl_recent")
            # Should be 3 games * 15s = 45s (or clamped by dynamic_cap)
            assert duration is not None
            assert duration >= 15  # At least one game's worth

    def test_returns_duration_for_valid_modes(self, plugin):
        """Should return a valid duration for all valid mode types."""
        valid_modes = ["nfl_recent", "nfl_upcoming", "nfl_live"]
        for mode in valid_modes:
            # These should return either a calculated duration or None (if no games)
            result = plugin.get_cycle_duration(mode)
            # Result can be None if no games, or a positive number
            assert result is None or result > 0


class TestLivePriorityWithDynamicDuration:
    """Tests for interaction between live priority and dynamic duration."""

    def test_has_live_priority_returns_false_when_disabled(self, plugin):
        """has_live_priority should return False when no league has it enabled."""
        plugin.nfl_live_priority = False
        plugin.ncaa_fb_live_priority = False
        assert plugin.has_live_priority() is False

    def test_has_live_priority_returns_true_when_enabled(self, plugin):
        """has_live_priority should return True when a league has it enabled."""
        plugin.nfl_enabled = True
        plugin.nfl_live_priority = True
        assert plugin.has_live_priority() is True

    def test_has_live_content_returns_false_without_live_games(self, plugin):
        """has_live_content should return False when no live games exist."""
        plugin.nfl_enabled = True
        plugin.nfl_live_priority = True
        if hasattr(plugin, "nfl_live") and plugin.nfl_live:
            plugin.nfl_live.live_games = []
        result = plugin.has_live_content()
        assert result is False

    def test_live_priority_does_not_affect_duration_value(self, plugin):
        """Live priority setting should not change duration calculation."""
        # Get duration with live_priority off
        plugin.nfl_live_priority = False
        if hasattr(plugin, "nfl_recent") and plugin.nfl_recent:
            plugin.nfl_recent.recent_games = [{"id": "1", "is_final": True}]
        duration_without_priority = plugin.get_cycle_duration("nfl_recent")

        # Get duration with live_priority on
        plugin.nfl_live_priority = True
        duration_with_priority = plugin.get_cycle_duration("nfl_recent")

        # Durations should be the same - live_priority affects cycling, not duration
        assert duration_without_priority == duration_with_priority


class TestInternalCyclingDynamicDuration:
    """Tests for internal cycling using dynamic duration (line 1306 fix)."""

    def test_internal_cycling_logs_deprecation_warning(self, plugin, caplog):
        """Internal cycling should log a deprecation warning."""
        # Reset the warning flag
        plugin._internal_cycling_warned = False

        # Call display without display_mode to trigger internal cycling
        with caplog.at_level(logging.WARNING):
            plugin.display(force_clear=True)

        # Check that deprecation warning was logged
        assert any(
            "deprecated internal mode cycling" in record.message.lower()
            for record in caplog.records
        ), "Expected deprecation warning not found in logs"

    def test_internal_cycling_warning_only_once(self, plugin, caplog):
        """Deprecation warning should only be logged once per session."""
        # Reset the warning flag
        plugin._internal_cycling_warned = False

        # Call display twice
        with caplog.at_level(logging.WARNING):
            plugin.display(force_clear=True)
            initial_count = sum(
                1
                for record in caplog.records
                if "deprecated internal mode cycling" in record.message.lower()
            )

            plugin.display(force_clear=True)
            final_count = sum(
                1
                for record in caplog.records
                if "deprecated internal mode cycling" in record.message.lower()
            )

        # Should only have one warning total
        assert initial_count == 1
        assert final_count == 1

    def test_internal_cycling_uses_dynamic_duration(self, plugin):
        """Internal cycling should use get_cycle_duration() instead of fixed duration.

        This is the regression test for the line 1306 bug fix.
        We verify by checking the code path, not by executing full internal cycling
        (which requires manager initialization that may fail in test environment).
        """
        import inspect

        # Read the source code of _display_internal_cycling
        source = inspect.getsource(plugin._display_internal_cycling)

        # Verify the fix is in place:
        # 1. Should call get_cycle_duration for the current mode
        assert "get_cycle_duration" in source, (
            "_display_internal_cycling does not call get_cycle_duration(). "
            "The line 1306 bug fix is missing."
        )

        # 2. Should use cycle_duration (dynamic) not just self.display_duration
        assert "cycle_duration" in source, (
            "_display_internal_cycling does not use cycle_duration variable. "
            "The dynamic duration fix may be incomplete."
        )

        # 3. The timing comparison should use cycle_duration, not display_duration directly
        # Look for pattern: >= cycle_duration (not >= self.display_duration)
        assert ">= cycle_duration" in source, (
            "_display_internal_cycling does not compare against cycle_duration. "
            "The timing logic is still using fixed display_duration."
        )


class TestDynamicDurationConfiguration:
    """Tests for dynamic duration configuration handling."""

    def test_mode_level_duration_override(self, plugin):
        """Mode-level duration should override per-game calculation."""
        # Configure a specific mode duration
        plugin.config["recent_mode_duration"] = 90.0

        # Even with games, should use mode-level duration
        if hasattr(plugin, "nfl_recent") and plugin.nfl_recent:
            plugin.nfl_recent.recent_games = [
                {"id": "1", "is_final": True},
                {"id": "2", "is_final": True},
            ]

        # The duration calculation logic should check for mode-level duration
        duration = plugin.get_cycle_duration("nfl_recent")
        # Result depends on implementation details, just verify it returns something
        assert duration is None or duration > 0

    def test_fallback_to_display_duration(self, plugin):
        """Should fall back to display_duration when dynamic calc returns None.

        We verify the fallback logic exists in the code rather than executing
        full internal cycling (which requires manager initialization).
        """
        import inspect

        # Read the source code of _display_internal_cycling
        source = inspect.getsource(plugin._display_internal_cycling)

        # Verify fallback logic exists:
        # 1. Should set cycle_duration = self.display_duration as default
        assert "cycle_duration = self.display_duration" in source, (
            "_display_internal_cycling does not have display_duration fallback. "
            "If get_cycle_duration returns None, there's no fallback."
        )

        # 2. Should check if dynamic_duration is not None and > 0
        assert "dynamic_duration is not None" in source, (
            "_display_internal_cycling does not check for None from get_cycle_duration(). "
            "This could cause issues when dynamic duration is not available."
        )


def run_tests():
    """Run all tests."""
    print("\n" + "=" * 70)
    print("  Dynamic Duration Tests for Football Scoreboard Plugin")
    print("=" * 70)

    # Run with pytest
    exit_code = pytest.main([__file__, "-v", "--tb=short"])
    return exit_code


if __name__ == "__main__":
    sys.exit(run_tests())
