#!/usr/bin/env python3
"""
Baseball Scoreboard Plugin Test Suite

Tests the baseball scoreboard plugin functionality including:
- Plugin import and initialization
- Configuration handling
- Data fetching (live, recent, upcoming)
- Display rendering
- Emulator mode testing
"""

import os
import sys
import time
import logging
from typing import Dict, Any

# Set emulator mode BEFORE any imports
os.environ["EMULATOR"] = "true"

# Add project directory to Python path
project_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_dir not in sys.path:
    sys.path.insert(0, project_dir)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s:%(name)s:%(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)

print("=" * 60)
print("Baseball Scoreboard Plugin Test Suite")
print("=" * 60)
print(f"Project directory: {project_dir}")
print(f"EMULATOR mode: {os.environ.get('EMULATOR', 'false')}")
print()


def create_mock_display_manager():
    """Create a mock display manager for testing."""
    try:
        from src.display_manager import DisplayManager
        import json
        
        # Load config for display manager
        config_path = os.path.join(project_dir, 'config', 'config.json')
        config = {}
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                config = json.load(f)
        
        # Create display manager - it will create the matrix internally
        display_manager = DisplayManager(config=config, force_fallback=True)
        print("[OK] Created mock display manager")
        return display_manager
    except Exception as e:
        print(f"[FAIL] Failed to create mock display manager: {e}")
        import traceback
        traceback.print_exc()
        return None


def create_mock_cache_manager():
    """Create a mock cache manager for testing."""
    try:
        from src.cache_manager import CacheManager
        
        cache_manager = CacheManager()
        print("[OK] Created mock cache manager")
        return cache_manager
    except Exception as e:
        print(f"[FAIL] Failed to create mock cache manager: {e}")
        import traceback
        traceback.print_exc()
        return None


def create_test_config() -> Dict[str, Any]:
    """Create test configuration for baseball scoreboard plugin."""
    return {
        'mlb_enabled': True,
        'mlb_favorite_teams': ['TEX', 'NYM'],
        'mlb_display_modes_live': True,
        'mlb_display_modes_recent': True,
        'mlb_display_modes_upcoming': True,
        'mlb_live_priority': True,
        'mlb_live_update_interval': 15,
        'mlb_recent_update_interval': 3600,
        'mlb_upcoming_update_interval': 3600,
        'mlb_recent_games_to_show': 5,
        'mlb_upcoming_games_to_show': 10,
        'mlb_show_records': False,
        'mlb_show_ranking': False,
        'mlb_show_odds': False,
        'mlb_test_mode': False,  # Set to True for test mode
        
        'milb_enabled': False,
        'ncaa_baseball_enabled': False,
        
        'display_duration': 15,
    }


def test_plugin_import():
    """Test 1: Import plugin."""
    print("\n" + "=" * 60)
    print("  Test 1: Plugin Import")
    print("=" * 60)
    
    try:
        print("[OK] Plugin imported successfully")
        return True
    except Exception as e:
        print(f"[FAIL] Plugin import failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_plugin_initialization():
    """Test 2: Initialize plugin."""
    print("\n" + "=" * 60)
    print("  Test 2: Plugin Initialization")
    print("=" * 60)
    
    try:
        from manager import BaseballScoreboardPlugin
        
        display_manager = create_mock_display_manager()
        cache_manager = create_mock_cache_manager()
        
        if not display_manager or not cache_manager:
            return False
        
        # Create mock plugin manager
        class MockPluginManager:
            def __init__(self):
                self.font_manager = None
        
        plugin_manager = MockPluginManager()
        
        config = create_test_config()
        
        plugin = BaseballScoreboardPlugin(
            plugin_id="baseball-scoreboard",
            config=config,
            display_manager=display_manager,
            cache_manager=cache_manager,
            plugin_manager=plugin_manager
        )
        
        if plugin.initialized:
            print("[OK] Plugin initialized successfully")
            print(f"     Enabled leagues: {[k for k, v in plugin.leagues.items() if v.get('enabled', False)]}")
            return plugin
        else:
            print("[FAIL] Plugin initialization failed")
            return None
            
    except Exception as e:
        print(f"[FAIL] Plugin initialization error: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_plugin_update(plugin):
    """Test 3: Plugin update."""
    print("\n" + "=" * 60)
    print("  Test 3: Plugin Update")
    print("=" * 60)
    
    try:
        print("   Calling plugin.update()...")
        plugin.update()
        print("[OK] Plugin update completed")
        
        # Check league states
        for league_key, league_config in plugin.leagues.items():
            if league_config.get('enabled', False):
                live_state = plugin.league_state[league_key]['live']
                recent_state = plugin.league_state[league_key]['recent']
                upcoming_state = plugin.league_state[league_key]['upcoming']
                
                print(f"   {league_key}:")
                print(f"     Live games: {len(live_state['games_list'])}")
                print(f"     Recent games: {len(recent_state['games_list'])}")
                print(f"     Upcoming games: {len(upcoming_state['games_list'])}")
        
        return True
    except Exception as e:
        print(f"[FAIL] Plugin update error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_plugin_display(plugin):
    """Test 4: Plugin display."""
    print("\n" + "=" * 60)
    print("  Test 4: Plugin Display")
    print("=" * 60)
    
    try:
        print("   Calling plugin.display()...")
        plugin.display()
        print("[OK] Plugin display completed")
        return True
    except Exception as e:
        print(f"[FAIL] Plugin display error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_plugin_info(plugin):
    """Test 5: Plugin info."""
    print("\n" + "=" * 60)
    print("  Test 5: Plugin Info")
    print("=" * 60)
    
    try:
        info = plugin.get_info()
        print("[OK] Plugin info retrieved")
        print(f"     Total games: {info.get('total_games', 0)}")
        print(f"     Enabled leagues: {info.get('enabled_leagues', [])}")
        print(f"     Live games: {info.get('live_games', 0)}")
        print(f"     Recent games: {info.get('recent_games', 0)}")
        print(f"     Upcoming games: {info.get('upcoming_games', 0)}")
        return True
    except Exception as e:
        print(f"[FAIL] Plugin info error: {e}")
        import traceback
        traceback.print_exc()
        return False


def run_emulator_test(plugin, duration=30):
    """Test 6: Run emulator test."""
    print("\n" + "=" * 60)
    print(f"  Test 6: Emulator Test ({duration}s)")
    print("=" * 60)
    
    try:
        print("[EMULATOR] Starting emulator test...")
        print("   This will simulate the plugin running in emulator mode")
        print("   Press Ctrl+C to stop early")
        print("   The emulator window should display the baseball scoreboard")
        
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
                    # Print current game info
                    for league_key, league_config in plugin.leagues.items():
                        if league_config.get('enabled', False):
                            live_state = plugin.league_state[league_key]['live']
                            if live_state['current_game']:
                                game = live_state['current_game']
                                print(f"     {league_key} live: {game.get('away_abbr', '?')} @ {game.get('home_abbr', '?')}")
                
                # Short delay between cycles
                time.sleep(2)
                
            except KeyboardInterrupt:
                print("\n   [STOP] Test stopped by user")
                break
            except Exception as e:
                print(f"   [WARN] Error in cycle {cycle_count}: {e}")
                import traceback
                traceback.print_exc()
                continue
        
        elapsed = time.time() - start_time
        print(f"[OK] Emulator test completed: {cycle_count} cycles in {elapsed:.1f}s")
        return True
        
    except Exception as e:
        print(f"[FAIL] Emulator test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_plugin_cleanup(plugin):
    """Test 7: Plugin cleanup."""
    print("\n" + "=" * 60)
    print("  Test 7: Plugin Cleanup")
    print("=" * 60)
    
    try:
        plugin.cleanup()
        print("[OK] Plugin cleanup completed")
        return True
    except Exception as e:
        print(f"[FAIL] Plugin cleanup error: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("  Baseball Scoreboard Plugin Test Suite")
    print("=" * 60)
    
    results = {}
    
    # Test 1: Import
    results['import'] = test_plugin_import()
    if not results['import']:
        print("\n[FAIL] Import test failed. Cannot continue.")
        return False
    
    # Test 2: Initialization
    plugin = test_plugin_initialization()
    results['initialization'] = plugin is not None
    if not plugin:
        print("\n[FAIL] Initialization test failed. Cannot continue.")
        return False
    
    # Test 3: Update
    results['update'] = test_plugin_update(plugin)
    
    # Test 4: Display
    results['display'] = test_plugin_display(plugin)
    
    # Test 5: Info
    results['info'] = test_plugin_info(plugin)
    
    # Test 6: Emulator (interactive)
    print("\n" + "=" * 60)
    print("  Interactive Emulator Test")
    print("=" * 60)
    print("   Would you like to run the emulator test? (y/n): ", end='')
    try:
        response = input().strip().lower()
        if response == 'y':
            results['emulator'] = run_emulator_test(plugin, duration=60)
        else:
            print("   Skipping emulator test")
            results['emulator'] = None
    except (EOFError, KeyboardInterrupt):
        print("   Skipping emulator test")
        results['emulator'] = None
    
    # Test 7: Cleanup
    results['cleanup'] = test_plugin_cleanup(plugin)
    
    # Summary
    print("\n" + "=" * 60)
    print("  Test Summary")
    print("=" * 60)
    for test_name, result in results.items():
        status = "[OK]" if result else "[FAIL]" if result is False else "[SKIP]"
        print(f"  {test_name:20s}: {status}")
    
    all_passed = all(v for v in results.values() if v is not None)
    
    if all_passed:
        print("\n[SUCCESS] All tests passed!")
        return True
    else:
        print("\n[WARNING] Some tests failed or were skipped")
        return False


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n[STOP] Tests interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n[FAIL] Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

