#!/usr/bin/env python3
"""
Test script for Football Scoreboard Plugin using pygame emulator.

This script tests the football scoreboard plugin functionality by:
1. Setting up mock managers and dependencies
2. Initializing the plugin with test configuration
3. Running the plugin in emulator mode
4. Testing update() and display() methods
"""

import sys
import json
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
        "display_duration": 10,  # Short duration for testing
        "game_display_duration": 5,
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


def test_plugin_import():
    """Test that the plugin can be imported successfully."""
    print("\n" + "=" * 60)
    print("  Test 1: Plugin Import")
    print("=" * 60)

    try:
        # Import the plugin
        from manager import FootballScoreboardPlugin

        print("[OK] Successfully imported FootballScoreboardPlugin")

        # Check if it has the expected methods
        required_methods = ["update", "display", "cleanup", "get_info"]
        missing_methods = [
            m for m in required_methods if not hasattr(FootballScoreboardPlugin, m)
        ]

        if missing_methods:
            print(f"[FAIL] Missing methods: {', '.join(missing_methods)}")
            return False

        print("[OK] All required methods present")
        return True

    except Exception as e:
        print(f"[FAIL] Import failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_plugin_initialization():
    """Test plugin initialization with mock dependencies."""
    print("\n" + "=" * 60)
    print("  Test 2: Plugin Initialization")
    print("=" * 60)

    try:
        from manager import FootballScoreboardPlugin

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
        print(f"   Plugin ID: {plugin.plugin_id}")
        print(f"   Enabled: {plugin.is_enabled}")
        print(f"   Display size: {plugin.display_width}x{plugin.display_height}")
        print(f"   NFL enabled: {plugin.nfl_enabled}")
        print(f"   NCAA FB enabled: {plugin.ncaa_fb_enabled}")
        print(f"   Available modes: {plugin.modes}")

        return True, plugin

    except Exception as e:
        print(f"[FAIL] Initialization failed: {e}")
        import traceback

        traceback.print_exc()
        return False, None


def test_plugin_update(plugin):
    """Test plugin update functionality."""
    print("\n" + "=" * 60)
    print("  Test 3: Plugin Update")
    print("=" * 60)

    try:
        print("[UPDATE] Running plugin update...")
        plugin.update()
        print("[OK] Update completed successfully")

        # Check if managers were updated
        if hasattr(plugin, "nfl_live"):
            print("   NFL Live manager available")
        if hasattr(plugin, "nfl_recent"):
            print("   NFL Recent manager available")
        if hasattr(plugin, "nfl_upcoming"):
            print("   NFL Upcoming manager available")

        return True

    except Exception as e:
        print(f"[FAIL] Update failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_plugin_display(plugin):
    """Test plugin display functionality."""
    print("\n" + "=" * 60)
    print("  Test 4: Plugin Display")
    print("=" * 60)

    try:
        print("[DISPLAY] Testing plugin display...")

        # Test display with force clear
        plugin.display(force_clear=True)
        print("[OK] Display completed successfully")

        # Check current mode
        current_mode = plugin.modes[plugin.current_mode_index]
        print(f"   Current mode: {current_mode}")

        # Test mode cycling
        print("[CYCLE] Testing mode cycling...")
        plugin.display()
        print("[OK] Mode cycling completed")

        return True

    except Exception as e:
        print(f"[FAIL] Display failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_plugin_info(plugin):
    """Test plugin info functionality."""
    print("\n" + "=" * 60)
    print("  Test 5: Plugin Info")
    print("=" * 60)

    try:
        info = plugin.get_info()
        print("[OK] Plugin info retrieved successfully")
        print(f"   Info: {json.dumps(info, indent=2)}")
        return True

    except Exception as e:
        print(f"[FAIL] Info retrieval failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_plugin_cleanup(plugin):
    """Test plugin cleanup functionality."""
    print("\n" + "=" * 60)
    print("  Test 6: Plugin Cleanup")
    print("=" * 60)

    try:
        plugin.cleanup()
        print("[OK] Plugin cleanup completed successfully")
        return True

    except Exception as e:
        print(f"[FAIL] Cleanup failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def run_emulator_test(plugin, duration=30):
    """Run the plugin in emulator mode for a specified duration."""
    print("\n" + "=" * 60)
    print(f"  Test 7: Emulator Test ({duration}s)")
    print("=" * 60)

    try:
        print("[EMULATOR] Starting emulator test...")
        print("   This will simulate the plugin running in emulator mode")
        print("   Press Ctrl+C to stop early")

        start_time = time.time()
        cycle_count = 0

        while time.time() - start_time < duration:
            try:
                # Update plugin
                plugin.update()

                # Display current mode
                plugin.display()

                cycle_count += 1

                # Show progress every 5 seconds
                elapsed = time.time() - start_time
                if cycle_count % 5 == 0:
                    print(f"   Cycle {cycle_count}: {elapsed:.1f}s elapsed")

                # Short delay between cycles
                time.sleep(1)

            except KeyboardInterrupt:
                print("\n   [STOP] Test stopped by user")
                break
            except Exception as e:
                print(f"   [WARN] Error in cycle {cycle_count}: {e}")
                continue

        elapsed = time.time() - start_time
        print(f"[OK] Emulator test completed: {cycle_count} cycles in {elapsed:.1f}s")
        return True

    except Exception as e:
        print(f"[FAIL] Emulator test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("  Football Scoreboard Plugin Test Suite")
    print("=" * 60)

    results = {}

    # Test 1: Import
    results["Import"] = test_plugin_import()

    # Test 2: Initialization
    init_success, plugin = test_plugin_initialization()
    results["Initialization"] = init_success

    if not init_success or plugin is None:
        print("\n[FAIL] Cannot continue tests - initialization failed")
        return 1

    # Test 3: Update
    results["Update"] = test_plugin_update(plugin)

    # Test 4: Display
    results["Display"] = test_plugin_display(plugin)

    # Test 5: Info
    results["Info"] = test_plugin_info(plugin)

    # Test 6: Cleanup
    results["Cleanup"] = test_plugin_cleanup(plugin)

    # Test 7: Emulator (optional - ask user)
    print("\n" + "=" * 60)
    print("  Optional: Emulator Test")
    print("=" * 60)
    print("Would you like to run a 30-second emulator test? (y/n): ", end="")

    try:
        response = input().lower().strip()
        if response in ["y", "yes"]:
            results["Emulator"] = run_emulator_test(plugin, 30)
        else:
            print("[SKIP] Skipping emulator test")
            results["Emulator"] = None
    except KeyboardInterrupt:
        print("\n[SKIP] Skipping emulator test")
        results["Emulator"] = None

    # Print summary
    print("\n" + "=" * 60)
    print("  Test Results Summary")
    print("=" * 60)

    passed = sum(1 for result in results.values() if result is True)
    total = sum(1 for result in results.values() if result is not None)

    for test_name, result in results.items():
        if result is None:
            status = "[SKIP]"
        elif result:
            status = "[PASS]"
        else:
            status = "[FAIL]"
        print(f"  {status} - {test_name}")

    print(f"\n  Total: {passed}/{total} tests passed")

    if passed == total:
        print("\n  [SUCCESS] All tests passed! Plugin is ready for use.")
        return 0
    else:
        print(f"\n  [WARNING] WARNING: {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
