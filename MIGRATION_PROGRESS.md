# Manager to Plugin Migration Progress

## Overview
Migration of all managers from `src/` to standalone plugins in `ledmatrix-plugins`.

## Progress Summary

### Phase 1: Simple Standalone Managers (7 plugins)
Target: Migrate straightforward, single-purpose managers

| Plugin | Status | Location | Notes |
|--------|--------|----------|-------|
| clock | ✅ EXISTS | `plugins/clock-simple/` | Already migrated as simple version |
| weather | ✅ COMPLETE | `plugins/weather/` | Full featured with 3 display modes |
| static-image | ✅ COMPLETE | `plugins/static-image/` | Complete with scaling & transparency |
| text-display | 🔄 IN PROGRESS | `plugins/text-display/` | Directory created, files pending |
| calendar | ⏳ PENDING | - | Not started |
| of-the-day | ⏳ PENDING | - | Not started |
| music | ⏳ PENDING | - | Not started |

**Phase 1 Progress: 3/7 complete (42.9%)**

### Phase 2: Complex Managers (9 plugins)

#### Sports Plugins (5 plugins)

| Plugin | Status | Leagues | Display Modes | Notes |
|--------|--------|---------|---------------|-------|
| football-scoreboard | ⏳ PENDING | NFL, NCAA FB | live/recent/upcoming | Not started |
| hockey-scoreboard | ⏳ PENDING | NHL, NCAA M/W | live/recent/upcoming | Not started |
| basketball-scoreboard | ⏳ PENDING | NBA, NCAA M/W, WNBA | live/recent/upcoming | Not started |
| baseball-scoreboard | ⏳ PENDING | MLB, MiLB, NCAA | live/recent/upcoming | Not started |
| soccer-scoreboard | ⏳ PENDING | Multiple leagues | live/recent/upcoming | Not started |

#### Advanced Managers (4 plugins)

| Plugin | Status | Location | Notes |
|--------|--------|----------|-------|
| odds-ticker | ⏳ PENDING | - | Multi-sport odds, scrolling |
| leaderboard | ⏳ PENDING | - | Multi-sport standings |
| news | ⏳ PENDING | - | RSS feed aggregation |
| stock-news | ⏳ PENDING | - | Stock-specific news |

**Phase 2 Progress: 0/9 complete (0%)**

### Phase 3: Stock-related (2 plugins)

| Plugin | Status | Location | Notes |
|--------|--------|----------|-------|
| stocks | ⏳ PENDING | - | Stock ticker with charts |
| crypto | ⏳ PENDING | - | Can be integrated with stocks |

**Phase 3 Progress: 0/2 complete (0%)**

### Special Plugins (Already Complete)

| Plugin | Status | Location | Notes |
|--------|--------|----------|-------|
| flight-tracker | ✅ COMPLETE | `plugins/flight-tracker/` | Advanced flight tracking |
| hello-world | ✅ COMPLETE | `plugins/hello-world/` | Example plugin |

## Overall Progress

**Total: 9/18 plugins complete (50%)**  
**Phase 1: COMPLETE ✅**  
**Phase 2: Not started**  
**Phase 3: Not started**

## Completed Plugin Details

### ✅ of-the-day
- **Location**: `plugins/of-the-day/`
- **Display Modes**: of_the_day
- **Files**: manifest.json, config_schema.json, manager.py, requirements.txt, README.md
- **Features**:
  - Multiple category support (Word of the Day, Bible verses, custom)
  - JSON-based data files
  - Automatic daily updates
  - Content rotation (title/subtitle/definition)
  - Text wrapping for long content
  - Font manager integration

### ✅ music
- **Location**: `plugins/music/`
- **Display Modes**: music
- **Files**: manifest.json, config_schema.json, manager.py, requirements.txt, README.md
- **Features**:
  - Spotify integration with OAuth
  - YouTube Music integration with companion server
  - Album artwork display with caching
  - Scrolling text for long titles
  - Real-time playback polling
  - Background threading
  - Font manager integration

### ✅ calendar
- **Location**: `plugins/calendar/`
- **Display Modes**: calendar
- **Files**: manifest.json, config_schema.json, manager.py, requirements.txt, README.md
- **Features**:
  - Google Calendar API OAuth authentication
  - Multiple calendar support
  - Event rotation
  - All-day and timed events
  - Timezone-aware formatting
  - Text wrapping for long event titles
  - Font manager integration

### ✅ weather
- **Location**: `plugins/weather/`
- **Display Modes**: weather, hourly_forecast, daily_forecast
- **Files**: manifest.json, config_schema.json, manager.py, requirements.txt, README.md
- **Features**: 
  - OpenWeatherMap API integration
  - Current conditions, hourly & daily forecasts
  - UV index, humidity, wind speed
  - Error handling with backoff
  - Font manager integration
  - Cache manager integration

### ✅ static-image
- **Location**: `plugins/static-image/`
- **Display Modes**: static_image
- **Files**: manifest.json, config_schema.json, manager.py, requirements.txt, README.md
- **Features**:
  - Multiple image format support (PNG, JPG, BMP, GIF)
  - Automatic scaling with aspect ratio preservation
  - Transparency support
  - Configurable background color
  - LANCZOS resampling for quality

### ✅ clock-simple
- **Location**: `plugins/clock-simple/`
- **Display Modes**: clock-simple
- **Status**: Already existed, functional
- **Features**:
  - 12h/24h format
  - Timezone support
  - Date display
  - Configurable colors

## Next Steps

1. ✅ Complete text-display plugin (Phase 1)
2. Complete calendar plugin (Phase 1)
3. Complete of-the-day plugin (Phase 1)
4. Complete music plugin (Phase 1)
5. Begin Phase 2: Sports plugins (highest priority)
6. Begin Phase 2: Advanced managers
7. Complete Phase 3: Stock-related plugins

## Implementation Checklist per Plugin

For each plugin, ensure:
- ✅ Create plugin directory
- ✅ Create manifest.json with metadata and display_modes
- ✅ Create config_schema.json with complete validation
- ✅ Create manager.py inheriting from BasePlugin
- ✅ Implement update() method
- ✅ Implement display() method with mode handling
- ✅ Register fonts with font_manager
- ✅ Integrate with cache_manager
- ✅ Integrate with background_service (if needed)
- ✅ Create requirements.txt
- ✅ Create comprehensive README.md
- ⏳ Test plugin functionality
- ⏳ Add to plugins.json registry
- ⏳ Update main config.json structure

## Configuration Migration Status

- ⏳ Update config.json structure for plugin-based configuration
- ⏳ Add league selection to sport plugins
- ⏳ Migrate display_durations to plugin configs
- ⏳ Test Web UI integration

## Testing Status

- ⏳ Config validation testing
- ⏳ Display mode testing
- ⏳ Font override testing
- ⏳ Web UI integration testing
- ⏳ Plugin installation testing

## Documentation Status

- ⏳ Migration guide
- ⏳ Plugin development guide updates
- ⏳ Configuration guide updates
- ⏳ Troubleshooting guide

## Known Issues / TODOs

- [ ] Need to test on Raspberry Pi (can only run on Pi)
- [ ] Need to validate all font registrations work correctly
- [ ] Need to ensure background service integration works for sports
- [ ] Need to test plugin store integration
- [ ] Consider creating migration script for existing configs

## Estimated Completion

- **Phase 1**: 4 plugins remaining (~4-6 hours)
- **Phase 2**: 9 plugins (~12-15 hours)
- **Phase 3**: 2 plugins (~2-3 hours)
- **Testing & Documentation**: ~4-6 hours
- **Total Estimated**: ~22-30 hours of work

## Notes

- All plugins follow the BasePlugin interface
- Font manager integration is consistent across all plugins
- Cache manager is used for API responses
- Background service is used for heavy data fetching (sports plugins)
- Each plugin has comprehensive config schema for Web UI generation
- All plugins support multiple display modes where applicable

