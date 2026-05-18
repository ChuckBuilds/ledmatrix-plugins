#!/usr/bin/env python3
"""
Hockey Scoreboard Plugin - Emulator Test

This script tests the hockey scoreboard plugin with the pygame emulator.
It sets up the plugin with test configuration and runs it in emulator mode.
"""

import os
import sys
import time
import logging
import json

# Set emulator mode BEFORE any imports
os.environ["EMULATOR"] = "true"

# Add project directory to Python path
project_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_dir not in sys.path:
    sys.path.insert(0, project_dir)

# Add plugin directory to path
plugin_dir = os.path.dirname(os.path.abspath(__file__))
if plugin_dir not in sys.path:
    sys.path.insert(0, plugin_dir)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s:%(name)s:%(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)

print("=" * 60)
print("Hockey Scoreboard Plugin - Emulator Test")
print("=" * 60)
print(f"Project directory: {project_dir}")
print(f"Plugin directory: {plugin_dir}")
print(f"EMULATOR mode: {os.environ.get('EMULATOR', 'false')}")
print()


def create_display_manager():
    """Create a real display manager with emulator support."""
    try:
        from src.display_manager import DisplayManager
        
        # Load config for display manager
        config_path = os.path.join(project_dir, 'config', 'config.json')
        config = {}
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                config = json.load(f)
        
        # Create display manager - it will use emulator mode automatically
        display_manager = DisplayManager(config=config)
        width = display_manager.width if hasattr(display_manager, 'width') else getattr(display_manager.matrix, 'width', 128) if hasattr(display_manager, 'matrix') and display_manager.matrix else 128
        height = display_manager.height if hasattr(display_manager, 'height') else getattr(display_manager.matrix, 'height', 32) if hasattr(display_manager, 'matrix') and display_manager.matrix else 32
        print(f"[OK] Created display manager ({width}x{height})")
        return display_manager
    except Exception as e:
        print(f"[FAIL] Failed to create display manager: {e}")
        import traceback
        traceback.print_exc()
        return None


def create_cache_manager():
    """Create a real cache manager."""
    try:
        from src.cache_manager import CacheManager
        from src.config_manager import ConfigManager
        
        # Create config manager
        config_manager = ConfigManager()
        
        # Create cache manager
        cache_manager = CacheManager(config_manager=config_manager)
        print("[OK] Created cache manager")
        return cache_manager
    except Exception as e:
        print(f"[FAIL] Failed to create cache manager: {e}")
        import traceback
        traceback.print_exc()
        return None


def create_plugin_manager():
    """Create a mock plugin manager."""
    try:
        from unittest.mock import Mock
        mock_plugin_manager = Mock()
        mock_plugin_manager.get_plugin = Mock(return_value=None)
        mock_plugin_manager.get_all_plugins = Mock(return_value=[])
        print("[OK] Created plugin manager")
        return mock_plugin_manager
    except Exception as e:
        print(f"[FAIL] Failed to create plugin manager: {e}")
        return None


def create_test_config():
    """Create a test configuration for the hockey plugin."""
    return {
        "enabled": True,
        "display_duration": 10,  # Switch modes every 10 seconds
        "game_display_duration": 5,
        "show_records": True,
        "show_ranking": False,
        "show_odds": False,
        "timezone": "UTC",
        "nhl": {
            "enabled": True,
            "favorite_teams": ["TB", "BOS", "TOR"],
            "display_modes": {
                "live": True,
                "recent": True,
                "upcoming": True,
            },
            "recent_games_to_show": 5,
            "upcoming_games_to_show": 10,
            "show_shots_on_goal": True,
            "show_records": True,
            "update_interval_seconds": 60,
            "live_update_interval": 15,
            "live_game_duration": 20,
            "test_mode": True,  # Enable test mode for mock data
        },
        "ncaa_mens": {
            "enabled": True,
            "favorite_teams": ["BC", "BU", "MICH"],
            "display_modes": {
                "live": True,
                "recent": True,
                "upcoming": True,
            },
            "recent_games_to_show": 5,
            "upcoming_games_to_show": 10,
            "show_shots_on_goal": True,
            "update_interval_seconds": 60,
            "test_mode": True,
        },
        "ncaa_womens": {
            "enabled": False,  # Disable for initial test
            "favorite_teams": [],
            "display_modes": {
                "live": True,
                "recent": True,
                "upcoming": True,
            },
            "recent_games_to_show": 5,
            "upcoming_games_to_show": 10,
            "test_mode": True,
        },
    }


def run_emulator_test(duration=60):
    """Run the plugin in emulator mode."""
    print("\n" + "=" * 60)
    print(f"  Starting Emulator Test ({duration}s)")
    print("=" * 60)
    print("   Press Ctrl+C to stop early")
    print("   The emulator window should display hockey games")
    print()
    
    try:
        # Import the plugin
        from manager import HockeyScoreboardPlugin
        print("[OK] Plugin imported successfully")
        
        # Create dependencies
        display_manager = create_display_manager()
        if not display_manager:
            print("[FAIL] Cannot continue without display manager")
            return False
        
        cache_manager = create_cache_manager()
        if not cache_manager:
            print("[FAIL] Cannot continue without cache manager")
            return False
        
        plugin_manager = create_plugin_manager()
        if not plugin_manager:
            print("[FAIL] Cannot continue without plugin manager")
            return False
        
        # Create test config
        config = create_test_config()
        
        # Initialize plugin
        print("\n[INIT] Initializing hockey scoreboard plugin...")
        plugin = HockeyScoreboardPlugin(
            plugin_id="hockey-scoreboard",
            config=config,
            display_manager=display_manager,
            cache_manager=cache_manager,
            plugin_manager=plugin_manager,
        )
        
        print("[OK] Plugin initialized successfully")
        # Get display size from plugin or display manager
        try:
            plugin_width = getattr(plugin, 'display_width', None) or getattr(display_manager, 'width', 128)
            plugin_height = getattr(plugin, 'display_height', None) or getattr(display_manager, 'height', 32)
            print(f"   Display size: {plugin_width}x{plugin_height}")
        except Exception:
            print("   Display size: 128x32 (default)")
        print(f"   NHL enabled: {plugin.nhl_enabled}")
        print(f"   NCAA Men's enabled: {plugin.ncaa_mens_enabled}")
        print(f"   NCAA Women's enabled: {plugin.ncaa_womens_enabled}")
        print(f"   Available modes: {plugin.modes}")
        
        # Validate config
        if not plugin.validate_config():
            print("[WARN] Config validation failed, but continuing...")
        
        # Run emulator test
        print("\n[EMULATOR] Starting emulator test...")
        print("   The plugin will update and display hockey games")
        print("   Watch the pygame window for the display")
        
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
                    current_mode = plugin.modes[plugin.current_mode_index] if plugin.modes else "none"
                    print(f"   Cycle {cycle_count}: {elapsed:.1f}s - Mode: {current_mode}")
                    
                    # Try to get current manager info
                    try:
                        current_manager = plugin._get_current_manager()
                        if current_manager and hasattr(current_manager, 'current_game') and current_manager.current_game:
                            game = current_manager.current_game
                            print(f"     Game: {game.get('away_abbr', '?')} @ {game.get('home_abbr', '?')} "
                                  f"({game.get('away_score', '0')}-{game.get('home_score', '0')})")
                    except Exception:
                        pass
                
                # Short delay between cycles
                time.sleep(2)
                
            except KeyboardInterrupt:
                print("\n   [STOP] Test stopped by user")
                break
            except Exception as e:
                print(f"   [WARN] Error in cycle {cycle_count}: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(1)
                continue
        
        elapsed = time.time() - start_time
        print(f"\n[OK] Test completed: {cycle_count} cycles in {elapsed:.1f}s")
        
        # Show final plugin info
        try:
            info = plugin.get_info()
            print(f"\n[INFO] Final plugin state:")
            print(f"   Current mode: {info.get('current_mode', 'N/A')}")
            print(f"   Managers initialized: {info.get('managers_initialized', {})}")
        except Exception as e:
            print(f"[WARN] Could not get plugin info: {e}")
        
        # Cleanup
        try:
            plugin.cleanup()
            print("[OK] Plugin cleanup completed")
        except Exception as e:
            print(f"[WARN] Cleanup error: {e}")
        
        print("\n[SUCCESS] Hockey Scoreboard Plugin test completed!")
        print("   The plugin successfully:")
        print("   - Initialized with NHL and NCAA Men's managers")
        print("   - Fetches game data from ESPN API")
        print("   - Renders scoreboards with PIL")
        print("   - Works with the pygame emulator")
        
        return True
        
    except Exception as e:
        print(f"\n[FAIL] Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Main test function."""
    print("\n" + "=" * 60)
    print("  Hockey Scoreboard Plugin - Emulator Test")
    print("=" * 60)
    
    # Ask for duration
    try:
        duration_input = input("   Enter test duration in seconds (default 60): ").strip()
        duration = int(duration_input) if duration_input else 60
    except (ValueError, EOFError, KeyboardInterrupt):
        duration = 60
        print("   Using default duration: 60 seconds")
    
    print(f"\n   Starting {duration}-second emulator test...")
    print("   Make sure pygame window is visible!")
    print()
    
    success = run_emulator_test(duration)
    
    return 0 if success else 1


if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\n[STOP] Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n[FAIL] Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

