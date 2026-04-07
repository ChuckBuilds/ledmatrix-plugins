# Standalone Basketball Plugin Architecture

## Overview

The basketball plugin has been redesigned to be completely independent and not rely on Basketball or Sports base classes. All functionality has been extracted into the plugin itself.

## Architecture

### Core Components

1. **`manager.py`** - Main plugin class (BasketballScoreboardPlugin)
   - Only inherits from `BasePlugin` (plugin system requirement)
   - Contains all basketball-specific logic
   - Handles data fetching, game filtering, and display

2. **`basketball_helpers.py`** - Helper module
   - Font loading
   - Logo loading and caching
   - Text drawing with outlines
   - Game data extraction from ESPN API
   - Period/quarter formatting for basketball

### Key Features

- ✅ **No base class dependencies**: Only inherits from BasePlugin
- ✅ **Self-contained**: All basketball logic in the plugin
- ✅ **Matches old managers**: Same rendering, layout, fonts, colors, logos
- ✅ **Multiple leagues**: NBA, WNBA, NCAA Men's, NCAA Women's
- ✅ **League enable/disable**: Configure each league independently

## Differences from Base Classes Approach

### Before (with base classes)
```python
class BasketballScoreboardPlugin(BasePlugin, Basketball):
    # Inherited from Basketball base class:
    # - Font loading
    # - Logo loading
    # - Text drawing
    # - Game extraction
    # - Scorebug rendering
```

### Now (standalone)
```python
class BasketballScoreboardPlugin(BasePlugin):
    # Uses BasketballHelpers for:
    # - Font loading
    # - Logo loading  
    # - Text drawing
    # - Game extraction
    
    # Own methods for:
    # - Scorebug rendering
    # - Game filtering
    # - Data fetching
```

## Benefits

1. **Independence**: Plugin works without LEDMatrix base classes
2. **Portability**: Easy to share/install standalone
3. **Clarity**: All code in one place, easier to understand
4. **Flexibility**: Can modify without affecting other sports plugins

## Testing

Run the syntax checker:
```bash
python3 test_plugin_syntax.py
```

Expected output:
```
✓ Plugin imported successfully
✓ Class name: BasketballScoreboardPlugin
✓ Base classes: (<class 'src.plugin_system.base_plugin.BasePlugin'>,)
Plugin structure is valid!
```

## Module Structure

```
ledmatrix-basketball-scoreboard/
├── manager.py              # Main plugin (standalone)
├── basketball_helpers.py   # Helper functions
├── config_schema.json      # Configuration schema
├── manifest.json           # Plugin manifest
├── test_plugin_syntax.py   # Syntax checker
└── STANDALONE.md          # This file
```

## Functionality Coverage

All functionality from the old basketball managers is preserved:

- ✅ Period/quarter display (Q1, Q2, Q3, Q4, OT)
- ✅ Halftime display
- ✅ Game clock display
- ✅ Score display
- ✅ Team logos (home/away)
- ✅ Logo positioning (same as old managers)
- ✅ Font usage (PressStart2P, 4x6)
- ✅ Text with outline
- ✅ Live/recent/upcoming game modes
- ✅ League enable/disable
- ✅ Favorite teams support

## Configuration

Works with per-league nested configuration. The full schema lives in
[`config_schema.json`](config_schema.json); a minimal example:

```json
{
  "nba": {
    "enabled": true,
    "favorite_teams": ["LAL", "BOS"],
    "display_modes": {
      "show_live": true,
      "show_recent": true,
      "show_upcoming": true
    }
  },
  "ncaam": {
    "enabled": false
  }
}
```
