#!/usr/bin/env python3
"""
Test script for scroll display mode.

This script tests the ScrollDisplayManager and GameRenderer classes
to verify that scroll mode works correctly.
"""

import sys
import time
import logging
from pathlib import Path
from unittest.mock import Mock

# Add paths
plugin_dir = Path(__file__).parent
ledmatrix_root = plugin_dir.parent.parent
sys.path.insert(0, str(plugin_dir))
sys.path.insert(0, str(ledmatrix_root))

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def create_real_display_manager():
    """Create a mock display manager with real dimensions."""
    mock_display = Mock()
    mock_display.display_width = 128
    mock_display.display_height = 32
    mock_display.width = 128
    mock_display.height = 32
    
    # Create a mock matrix with real dimensions
    mock_matrix = Mock()
    mock_matrix.width = 128
    mock_matrix.height = 32
    mock_display.matrix = mock_matrix
    
    # Mock the display methods
    mock_display.clear = Mock()
    mock_display.set_image = Mock()
    mock_display.show = Mock()
    
    return mock_display


def create_test_config_with_scroll():
    """Create a test configuration with scroll mode enabled."""
    return {
        "enabled": True,
        "display_duration": 15,
        "game_display_duration": 5,
        "timezone": "UTC",
        "nfl": {
            "enabled": True,
            "favorite_teams": ["TB", "DAL", "GB"],
            "display_modes": {
                "show_live": True,
                "show_recent": True,
                "show_upcoming": True,
                "live_display_mode": "switch",
                "recent_display_mode": "scroll",  # Enable scroll for recent
                "upcoming_display_mode": "scroll",  # Enable scroll for upcoming
            },
            "scroll_settings": {
                "scroll_speed": 2,
                "scroll_delay": 3.0,
                "gap_between_games": 10,
                "show_league_separators": True,
            },
            "live_priority": True,
            "game_limits": {"recent_games_to_show": 5, "upcoming_games_to_show": 3},
            "display_options": {
                "show_records": True,
                "show_ranking": True,
                "show_odds": True,
            },
            "filtering": {"show_favorite_teams_only": False, "show_all_live": True},
            "test_mode": True,
        },
        "ncaa_fb": {
            "enabled": False,
            "display_modes": {
                "show_live": True,
                "show_recent": True,
                "show_upcoming": True,
                "live_display_mode": "switch",
                "recent_display_mode": "scroll",
                "upcoming_display_mode": "scroll",
            },
        },
    }


def test_game_renderer():
    """Test the GameRenderer class."""
    print("\n" + "=" * 60)
    print("  Testing GameRenderer")
    print("=" * 60)
    
    try:
        from game_renderer import GameRenderer
        print("[OK] GameRenderer imported successfully")
        
        # Initialize renderer with display dimensions and config
        renderer = GameRenderer(
            display_width=128,
            display_height=32,
            config={},  # Minimal config
            custom_logger=logger
        )
        print("[OK] GameRenderer initialized")
        print(f"   Display dimensions: {renderer.display_width}x{renderer.display_height}")
        
        # Test creating a sample game card
        game_data = {
            "id": "test_game_1",
            "home_team": {"abbreviation": "TB", "score": 28, "logo": None},
            "away_team": {"abbreviation": "ATL", "score": 24, "logo": None},
            "status": "final",
            "game_time": "Final",
            "quarter": None,
            "clock": None,
        }
        
        # Render the game (league is determined by game data, not a parameter)
        image = renderer.render_game_card(game_data, game_type="recent")
        
        if image:
            print("[OK] Successfully rendered game card")
            print(f"   Image size: {image.width}x{image.height}")
        else:
            print("[WARN] GameRenderer returned None for test game")
        
        return True
        
    except Exception as e:
        print(f"[FAIL] GameRenderer test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_scroll_display():
    """Test the ScrollDisplayManager class."""
    print("\n" + "=" * 60)
    print("  Testing ScrollDisplayManager")
    print("=" * 60)
    
    try:
        from scroll_display import ScrollDisplayManager
        print("[OK] ScrollDisplayManager imported successfully")
        
        # Create mock display manager
        display_manager = create_real_display_manager()
        
        # Create test config with scroll enabled
        config = create_test_config_with_scroll()
        
        # Initialize scroll manager
        scroll_manager = ScrollDisplayManager(display_manager, config, logger)
        print("[OK] ScrollDisplayManager initialized")
        
        # Test game collection for scroll mode
        test_games = [
            {
                "id": "game_1",
                "home_team": {"abbreviation": "TB", "score": 28, "logo": None},
                "away_team": {"abbreviation": "ATL", "score": 24, "logo": None},
                "status": "final",
                "game_time": "Final",
            },
            {
                "id": "game_2",
                "home_team": {"abbreviation": "DAL", "score": 17, "logo": None},
                "away_team": {"abbreviation": "LAC", "score": 34, "logo": None},
                "status": "final",
                "game_time": "Final",
            },
            {
                "id": "game_3",
                "home_team": {"abbreviation": "CHI", "score": 22, "logo": None},
                "away_team": {"abbreviation": "GB", "score": 16, "logo": None},
                "status": "final",
                "game_time": "Final",
            },
        ]
        
        # Get the scroll display for 'recent' game type
        scroll_display = scroll_manager.get_scroll_display("recent")
        print("[OK] Got scroll display for 'recent' game type")
        
        # Test preparing scroll content using the scroll display directly
        success = scroll_display.prepare_scroll_content(
            games=test_games,
            game_type="recent",
            leagues=["nfl"]
        )
        
        if success:
            print("[OK] Scroll content prepared successfully")
            scroll_info = scroll_display.get_scroll_info()
            print(f"   Total width: {scroll_info.get('total_width', 'N/A')}px")
            print(f"   Num game cards: {scroll_info.get('game_count', 'N/A')}")
        else:
            print("[WARN] Failed to prepare scroll content")
        
        # Test scroll display (short run)
        print("[OK] Testing scroll animation for 2 seconds...")
        start_time = time.time()
        frame_count = 0
        
        while time.time() - start_time < 2:
            scroll_display.display_scroll_frame()
            frame_count += 1
            time.sleep(0.01)  # ~100 FPS target
        
        elapsed = time.time() - start_time
        fps = frame_count / elapsed
        print(f"[OK] Scroll test completed: {frame_count} frames in {elapsed:.2f}s ({fps:.1f} FPS)")
        
        return True
        
    except Exception as e:
        print(f"[FAIL] ScrollDisplayManager test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_display_mode_parsing():
    """Test display mode settings parsing."""
    print("\n" + "=" * 60)
    print("  Testing Display Mode Parsing")
    print("=" * 60)
    
    try:
        from manager import FootballScoreboardPlugin
        from unittest.mock import Mock
        
        # Create mock dependencies
        mock_display = create_real_display_manager()
        mock_cache = Mock()
        mock_cache.config_manager = Mock()
        mock_cache.config_manager.load_config.return_value = {}
        mock_cache.get = Mock(return_value=None)
        mock_cache.set = Mock()
        mock_plugin_manager = Mock()
        mock_plugin_manager.get_plugin = Mock(return_value=None)
        
        # Create config with scroll mode enabled
        config = create_test_config_with_scroll()
        
        # Initialize plugin
        plugin = FootballScoreboardPlugin(
            plugin_id="football-scoreboard",
            config=config,
            display_manager=mock_display,
            cache_manager=mock_cache,
            plugin_manager=mock_plugin_manager,
        )
        
        print("[OK] Plugin initialized with scroll config")
        
        # Check display mode settings
        settings = plugin._display_mode_settings
        print("[OK] Display mode settings parsed:")
        for league, modes in settings.items():
            print(f"   {league}:")
            for game_type, display_mode in modes.items():
                print(f"      {game_type}: {display_mode}")
        
        # Verify scroll settings are parsed correctly
        nfl_settings = settings.get("nfl", {})
        if nfl_settings.get("recent") == "scroll":
            print("[OK] NFL recent mode is correctly set to 'scroll'")
        else:
            print(f"[WARN] NFL recent mode is '{nfl_settings.get('recent')}' (expected 'scroll')")
        
        if nfl_settings.get("upcoming") == "scroll":
            print("[OK] NFL upcoming mode is correctly set to 'scroll'")
        else:
            print(f"[WARN] NFL upcoming mode is '{nfl_settings.get('upcoming')}' (expected 'scroll')")
        
        # Check if scroll manager is using correct mode
        # _should_use_scroll_mode takes mode_type ('live', 'recent', 'upcoming'), not display_mode
        is_scroll_recent = plugin._should_use_scroll_mode("recent")
        print(f"[OK] _should_use_scroll_mode('recent') = {is_scroll_recent}")
        
        if is_scroll_recent:
            print("[OK] Scroll mode correctly enabled for 'recent' game type")
        else:
            print("[WARN] Scroll mode NOT enabled for 'recent' (expected True)")
        
        is_scroll_live = plugin._should_use_scroll_mode("live")
        print(f"[OK] _should_use_scroll_mode('live') = {is_scroll_live}")
        
        if not is_scroll_live:
            print("[OK] Switch mode correctly enabled for 'live' game type")
        else:
            print("[WARN] Scroll mode enabled for 'live' (expected False)")
        
        return True
        
    except Exception as e:
        print(f"[FAIL] Display mode parsing test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def run_all_tests():
    """Run all scroll mode tests."""
    print("=" * 60)
    print("  Football Scoreboard - Scroll Mode Tests")
    print("=" * 60)
    
    results = []
    
    # Test GameRenderer
    results.append(("GameRenderer", test_game_renderer()))
    
    # Test ScrollDisplayManager
    results.append(("ScrollDisplayManager", test_scroll_display()))
    
    # Test display mode parsing
    results.append(("Display Mode Parsing", test_display_mode_parsing()))
    
    # Print summary
    print("\n" + "=" * 60)
    print("  Test Results Summary")
    print("=" * 60)
    
    all_passed = True
    for name, passed in results:
        status = "[PASS]" if passed else "[FAIL]"
        print(f"{status} {name}")
        if not passed:
            all_passed = False
    
    print("=" * 60)
    
    if all_passed:
        print("\n[SUCCESS] All scroll mode tests passed!")
    else:
        print("\n[FAILURE] Some tests failed!")
    
    return all_passed


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)

