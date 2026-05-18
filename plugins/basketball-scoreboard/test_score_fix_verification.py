#!/usr/bin/env python3
"""
Verification script to test score extraction fix with mock NCAA Men's Basketball API data.

This script simulates various score formats that might come from the ESPN API
to verify the fix handles stringified dicts correctly.
"""

import sys
import os

# Add project directory to path
project_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_dir not in sys.path:
    sys.path.insert(0, project_dir)

# Mock logger
class MockLogger:
    def debug(self, msg):
        pass
    def warning(self, msg):
        print(f"WARNING: {msg}")
    def info(self, msg):
        pass

def test_score_extraction_with_mock_api_data():
    """Test score extraction with mock API data that simulates real ESPN responses."""
    
    # Import the sports module to test the actual extract_score function
    # We'll need to create a minimal test setup
    # Change to the plugin directory to import correctly
    plugin_dir = os.path.dirname(os.path.abspath(__file__))
    if plugin_dir not in sys.path:
        sys.path.insert(0, plugin_dir)
    
    from sports import SportsCore
    
    logger = MockLogger()
    
    # Mock display manager and cache manager
    class MockDisplayManager:
        def __init__(self):
            self.width = 128
            self.height = 32
            self.matrix = None
    
    class MockCacheManager:
        def get(self, key, max_age=None):
            return None
        def set(self, key, value, ttl=None):
            pass
    
    # Create a test instance (we'll use a minimal config)
    config = {
        "ncaam_scoreboard": {
            "enabled": True,
            "favorite_teams": []
        }
    }
    
    display_manager = MockDisplayManager()
    cache_manager = MockCacheManager()
    
    # Create a test class that inherits from SportsCore
    class TestSportsCore(SportsCore):
        def _extract_game_details(self, game_event):
            return self._extract_game_details_common(game_event)[0]
        def _fetch_data(self):
            return None
    
    try:
        sports_core = TestSportsCore(
            config=config,
            display_manager=display_manager,
            cache_manager=cache_manager,
            logger=logger,
            sport_key="ncaam"
        )
        
        # Test cases with various score formats
        test_cases = [
            {
                "name": "Dict with value key",
                "home_team": {"score": {"value": 75}, "homeAway": "home"},
                "away_team": {"score": {"value": 68}, "homeAway": "away"},
                "expected_home": "75",
                "expected_away": "68"
            },
            {
                "name": "Stringified JSON dict",
                "home_team": {"score": '{"value": 75}', "homeAway": "home"},
                "away_team": {"score": '{"value": 68}', "homeAway": "away"},
                "expected_home": "75",
                "expected_away": "68"
            },
            {
                "name": "Numeric strings",
                "home_team": {"score": "75", "homeAway": "home"},
                "away_team": {"score": "68", "homeAway": "away"},
                "expected_home": "75",
                "expected_away": "68"
            },
            {
                "name": "Integer scores",
                "home_team": {"score": 75, "homeAway": "home"},
                "away_team": {"score": 68, "homeAway": "away"},
                "expected_home": "75",
                "expected_away": "68"
            },
            {
                "name": "Dict with displayValue",
                "home_team": {"score": {"displayValue": "75"}, "homeAway": "home"},
                "away_team": {"score": {"displayValue": "68"}, "homeAway": "away"},
                "expected_home": "75",
                "expected_away": "68"
            }
        ]
        
        print("Testing score extraction with mock API data...")
        print("=" * 60)
        
        all_passed = True
        for i, test_case in enumerate(test_cases, 1):
            print(f"\nTest {i}: {test_case['name']}")
            
            # Create a mock game event
            game_event = {
                "id": f"test_{i}",
                "competitions": [{
                    "competitors": [test_case["home_team"], test_case["away_team"]],
                    "status": {
                        "type": {
                            "name": "STATUS_FINAL",
                            "state": "post",
                            "shortDetail": "Final"
                        }
                    }
                }],
                "date": "2024-01-01T12:00:00Z"
            }
            
            # Extract game details
            details = sports_core._extract_game_details(game_event)
            
            if details:
                home_score = details.get("home_score", "ERROR")
                away_score = details.get("away_score", "ERROR")
                
                home_ok = home_score == test_case["expected_home"]
                away_ok = away_score == test_case["expected_away"]
                
                if home_ok and away_ok:
                    print(f"  ✓ PASS: Home={home_score}, Away={away_score}")
                else:
                    print(f"  ✗ FAIL: Expected Home={test_case['expected_home']}, Away={test_case['expected_away']}")
                    print(f"         Got Home={home_score}, Away={away_score}")
                    all_passed = False
            else:
                print("  ✗ FAIL: Could not extract game details")
                all_passed = False
        
        print("\n" + "=" * 60)
        if all_passed:
            print("✓ All tests PASSED!")
            return 0
        else:
            print("✗ Some tests FAILED")
            return 1
            
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(test_score_extraction_with_mock_api_data())

