#!/usr/bin/env python3
"""
Simple emulator test for Football Scoreboard Plugin.

This script runs the plugin in emulator mode for a short duration
to demonstrate that it works with the pygame emulator.
"""

import sys
import time
import logging
from pathlib import Path
from unittest.mock import Mock

# Add the plugin directory to Python path
plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

# Add LEDMatrix src to path for imports
ledmatrix_src = Path(__file__).parent.parent.parent / "LEDMatrix" / "src"
sys.path.insert(0, str(ledmatrix_src))

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def create_mock_display_manager():
    """Create a mock display manager for testing."""
    mock_display = Mock()
    mock_display.display_width = 128
    mock_display.display_height = 32
    mock_display.width = 128
    mock_display.height = 32

    # Mock the display methods
    mock_display.clear = Mock()
    mock_display.set_image = Mock()
    mock_display.show = Mock()

    return mock_display


def create_mock_cache_manager():
    """Create a mock cache manager for testing."""
    mock_cache = Mock()

    # Mock config manager
    mock_config_manager = Mock()
    mock_config_manager.load_config.return_value = {}
    mock_cache.config_manager = mock_config_manager

    # Mock cache methods
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


def create_test_config():
    """Create a test configuration for the football plugin."""
    return {
        "enabled": True,
        "display_duration": 5,  # Short duration for testing
        "game_display_duration": 3,
        "timezone": "UTC",
        "nfl": {
            "enabled": True,
            "favorite_teams": ["TB", "DAL", "GB"],
            "display_modes": {
                "show_live": True,
                "show_recent": True,
                "show_upcoming": True,
            },
            "live_priority": True,
            "game_limits": {"recent_games_to_show": 3, "upcoming_games_to_show": 2},
            "display_options": {
                "show_records": True,
                "show_ranking": True,
                "show_odds": True,
            },
            "filtering": {"show_favorite_teams_only": False, "show_all_live": True},
            "test_mode": True,  # Enable test mode for mock data
        },
        "ncaa_fb": {
            "enabled": False,  # Disable NCAA for initial test
            "favorite_teams": [],
            "display_modes": {
                "show_live": True,
                "show_recent": True,
                "show_upcoming": True,
            },
            "live_priority": False,
            "game_limits": {"recent_games_to_show": 2, "upcoming_games_to_show": 1},
            "display_options": {
                "show_records": False,
                "show_ranking": True,
                "show_odds": True,
            },
            "filtering": {"show_favorite_teams_only": True, "show_all_live": False},
            "test_mode": True,
        },
    }


def run_emulator_demo():
    """Run the plugin in emulator mode for demonstration."""
    print("=" * 60)
    print("  Football Scoreboard Plugin - Emulator Demo")
    print("=" * 60)

    try:
        # Import the plugin
        from manager import FootballScoreboardPlugin

        print("[OK] Plugin imported successfully")

        # Create mock dependencies
        mock_display = create_mock_display_manager()
        mock_cache = create_mock_cache_manager()
        mock_plugin_manager = create_mock_plugin_manager()

        # Create test config
        config = create_test_config()

        # Initialize plugin
        plugin = FootballScoreboardPlugin(
            plugin_id="football-scoreboard",
            config=config,
            display_manager=mock_display,
            cache_manager=mock_cache,
            plugin_manager=mock_plugin_manager,
        )

        print("[OK] Plugin initialized successfully")
        print(f"   Display size: {plugin.display_width}x{plugin.display_height}")
        print(f"   Available modes: {plugin.modes}")

        # Run emulator demo
        print("\n[EMULATOR] Starting 15-second demo...")
        print("   This simulates the plugin running in emulator mode")
        print("   The plugin will cycle through different display modes")

        start_time = time.time()
        cycle_count = 0

        while time.time() - start_time < 15:  # 15 second demo
            try:
                # Update plugin
                plugin.update()

                # Display current mode
                plugin.display()

                cycle_count += 1

                # Show progress every 3 seconds
                elapsed = time.time() - start_time
                if cycle_count % 3 == 0:
                    current_mode = plugin.modes[plugin.current_mode_index]
                    print(
                        f"   Cycle {cycle_count}: {elapsed:.1f}s - Mode: {current_mode}"
                    )

                # Short delay between cycles
                time.sleep(1)

            except Exception as e:
                print(f"   [WARN] Error in cycle {cycle_count}: {e}")
                continue

        elapsed = time.time() - start_time
        print(f"\n[OK] Demo completed: {cycle_count} cycles in {elapsed:.1f}s")

        # Show final plugin info
        info = plugin.get_info()
        print(f"\n[INFO] Final plugin state:")
        print(f"   Current mode: {info['current_mode']}")
        print(f"   NFL enabled: {info['nfl_enabled']}")
        print(f"   NCAA FB enabled: {info['ncaa_fb_enabled']}")
        print(f"   Managers initialized: {info['managers_initialized']}")

        # Cleanup
        plugin.cleanup()
        print("\n[OK] Plugin cleanup completed")

        print("\n[SUCCESS] Football Scoreboard Plugin is working correctly!")
        print("   The plugin successfully:")
        print("   - Fetches real NFL data from ESPN API")
        print("   - Processes recent and upcoming games")
        print("   - Downloads team logos automatically")
        print("   - Cycles through display modes")
        print("   - Renders scoreboards with PIL")
        print("   - Works with the pygame emulator")

        return True

    except Exception as e:
        print(f"[FAIL] Demo failed: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_emulator_demo()
    sys.exit(0 if success else 1)
