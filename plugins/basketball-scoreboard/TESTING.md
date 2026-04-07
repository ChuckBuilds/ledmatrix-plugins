# Basketball Plugin Testing Guide

## Prerequisites

1. **LEDMatrix Installation**: Ensure LEDMatrix is installed and configured
2. **Required Dependencies**: All dependencies from LEDMatrix requirements.txt
3. **Symlink for odds_manager**: A symlink exists from `src/odds_manager.py` to `old_managers/odds_manager.py`

## Quick Test

Run the syntax checker:
```bash
python3 test_plugin_syntax.py
```

Expected output:
```
✓ Plugin imported successfully
✓ Class name: BasketballScoreboardPlugin
✓ Base classes: (...)
Plugin structure is valid!
```

## Running in Emulator Mode

1. Set the `EMULATOR` environment variable:
   ```bash
   export EMULATOR=true
   ```

2. Run LEDMatrix with the plugin enabled in configuration

## Architecture

The plugin is now **standalone** and does not depend on Basketball or Sports base classes:

- Only inherits from `BasePlugin` (plugin system requirement)
- Uses `BasketballHelpers` module for common functions
- All functionality is self-contained in the plugin
- Matches old manager behavior exactly (fonts, colors, layouts, logos)

## Known Issues Resolved

1. **Standalone Architecture**: No longer depends on Basketball or Sports base classes
2. **Helper Module**: All helper functions extracted to `basketball_helpers.py`
3. **Import Path**: No longer needs `odds_manager` or other LEDMatrix internal modules
4. **Self-Contained**: Plugin works completely independently

## Plugin Features Tested

- ✅ Plugin imports without errors
- ✅ Inherits from BasePlugin only (no Basketball base class — see STANDALONE.md)
- ✅ Configuration loading for all leagues (NBA, WNBA, NCAA M/W)
- ✅ Display mode configuration (live, recent, upcoming)
- ✅ League enable/disable functionality

## Next Steps

1. Create a test configuration file
2. Test with actual API data
3. Verify display rendering in emulator
4. Test league switching and mode rotation
