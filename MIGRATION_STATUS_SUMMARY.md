# Manager to Plugin Migration - Status Summary

**Date**: October 11, 2025  
**Progress**: 6/18 plugins complete (33.3%)

## ✅ Completed Plugins

### Phase 1: Simple Standalone Managers

| Plugin | Status | Files | Features |
|--------|--------|-------|----------|
| **weather** | ✅ COMPLETE | All 5 files | Current, hourly & daily forecasts, OpenWeatherMap API, 3 display modes |
| **static-image** | ✅ COMPLETE | All 5 files | Multiple formats, scaling, transparency, aspect ratio preservation |
| **text-display** | ✅ COMPLETE | All 5 files | Scrolling/static text, TTF/BDF fonts, custom colors & speed |

### Already Existing

| Plugin | Status | Location |
|--------|--------|----------|
| **clock-simple** | ✅ EXISTS | `plugins/clock-simple/` |
| **flight-tracker** | ✅ EXISTS | `plugins/flight-tracker/` |
| **hello-world** | ✅ EXISTS | `plugins/hello-world/` |

## 🔄 Remaining Work

### Phase 1: Simple Managers (3 remaining)

| Plugin | Complexity | Estimated Time | Priority |
|--------|------------|----------------|----------|
| **calendar** | Medium | 2-3 hours | Medium |
| **of-the-day** | Medium | 2-3 hours | Low |
| **music** | Medium | 2-3 hours | Medium |

**Total Phase 1 Remaining**: ~6-9 hours

### Phase 2: Complex Managers (9 plugins)

#### Sports Plugins (5 plugins) - HIGH PRIORITY

These are the most important for your setup and share common patterns:

| Plugin | Leagues | Complexity | Estimated Time |
|--------|---------|------------|----------------|
| **football-scoreboard** | NFL, NCAA FB | High | 4-5 hours |
| **hockey-scoreboard** | NHL, NCAA M/W | High | 4-5 hours |
| **basketball-scoreboard** | NBA, NCAA M/W, WNBA | High | 4-5 hours |
| **baseball-scoreboard** | MLB, MiLB, NCAA | High | 4-5 hours |
| **soccer-scoreboard** | Multiple leagues | High | 4-5 hours |

**Key Pattern**: Each sports plugin:
- Combines multiple league managers into one plugin
- Supports 3 display modes: `{sport}_live`, `{sport}_recent`, `{sport}_upcoming`
- Uses base classes from `src/base_classes/` (Hockey, Football, Basketball, Baseball)
- Integrates with BackgroundDataService for efficient season data fetching
- Has league-specific config (e.g., `nfl`, `ncaa_fb` under `football-scoreboard`)

**Total Sports Plugins**: ~20-25 hours

#### Advanced Managers (4 plugins)

| Plugin | Source | Complexity | Estimated Time |
|--------|--------|------------|----------------|
| **odds-ticker** | `odds_ticker_manager.py` | High | 3-4 hours |
| **leaderboard** | `leaderboard_manager.py` | High | 3-4 hours |
| **news** | `news_manager.py` | Medium | 2-3 hours |
| **stock-news** | `stock_news_manager.py` | Medium | 2-3 hours |

**Total Advanced Managers**: ~10-14 hours

### Phase 3: Stock-related (2 plugins)

| Plugin | Source | Complexity | Estimated Time |
|--------|--------|------------|----------------|
| **stocks** | `stock_manager.py` | High | 3-4 hours |
| **crypto** | Extract from stocks | Low | 1-2 hours |

**Total Phase 3**: ~4-6 hours

## Implementation Pattern Established

All completed plugins follow this structure:

```
plugin-name/
├── manifest.json          # ✅ Metadata, display modes, requirements
├── config_schema.json     # ✅ Complete JSON schema for validation
├── manager.py            # ✅ BasePlugin inheritance, update(), display()
├── requirements.txt      # ✅ Python dependencies
└── README.md            # ✅ Comprehensive documentation
```

### Code Patterns Used

1. **BasePlugin Inheritance**
   ```python
   class PluginName(BasePlugin):
       def __init__(self, plugin_id, config, display_manager, 
                    cache_manager, plugin_manager):
           super().__init__(...)
   ```

2. **Font Registration**
   ```python
   def _register_fonts(self):
       font_manager.register_manager_font(
           manager_id=self.plugin_id,
           element_key=f"{self.plugin_id}.element",
           family="press_start",
           size_px=12,
           color=(255, 255, 255)
       )
   ```

3. **Cache Integration**
   ```python
   cached_data = self.cache_manager.get(cache_key)
   if cached_data:
       return cached_data
   # Fetch fresh data
   self.cache_manager.set(cache_key, data)
   ```

4. **Display Mode Handling**
   ```python
   def display(self, display_mode: str = None):
       if display_mode == 'mode1':
           self._display_mode1()
       elif display_mode == 'mode2':
           self._display_mode2()
   ```

## Next Steps & Recommendations

### Immediate Priority (Hockey is enabled in your config)

1. **Create hockey-scoreboard plugin** (4-5 hours)
   - Combines: `nhl_managers.py`, `ncaam_hockey_managers.py`, `ncaaw_hockey_managers.py`
   - Display modes: `hockey_live`, `hockey_recent`, `hockey_upcoming`
   - Config structure:
     ```json
     "hockey-scoreboard": {
       "enabled": true,
       "leagues": {
         "nhl": true,
         "ncaam": false,
         "ncaaw": false
       },
       "nhl": {...existing nhl_scoreboard config...},
       "display_modes": {
         "hockey_live": true,
         "hockey_recent": true,
         "hockey_upcoming": true
       }
     }
     ```

2. **Create odds-ticker plugin** (3-4 hours)
   - Already enabled in your config
   - Complex scrolling with dynamic duration
   - Multi-sport odds aggregation

### Medium Priority

3. **football-scoreboard** - For when NFL/NCAA FB are in season
4. **basketball-scoreboard** - For NBA season
5. **baseball-scoreboard** - For baseball season

### Lower Priority

6. **news, stock-news** - RSS and stock headlines
7. **calendar, music** - Additional features
8. **of-the-day** - Word/verse displays

## Sports Plugin Implementation Strategy

Since sports plugins are the highest priority and share common patterns, here's the recommended approach:

### Template Structure for Sports Plugins

```python
class SportsScoreboardPlugin(BasePlugin):
    """
    Unified sports scoreboard supporting multiple leagues.
    
    Each plugin (football, hockey, basketball, baseball) follows this pattern:
    - Inherits from base sport class (Hockey, Football, etc.)
    - Supports league-specific configuration
    - Provides 3 display modes per sport
    - Uses background service for data fetching
    """
    
    def __init__(self, plugin_id, config, ...):
        super().__init__(...)
        
        # League configuration
        self.leagues_config = config.get('leagues', {})
        self.enabled_leagues = [k for k, v in self.leagues_config.items() if v]
        
        # Create managers for each enabled league
        self.league_managers = {}
        for league in self.enabled_leagues:
            league_config = config.get(league, {})
            # Create league-specific manager instances
        
        # Display mode routing
        self.display_modes = config.get('display_modes', {})
    
    def display(self, display_mode: str = None):
        # Route to appropriate league and mode
        # e.g., hockey_live -> NHL/NCAA live display
        pass
```

### Configuration Pattern

```json
{
  "hockey-scoreboard": {
    "enabled": true,
    "leagues": {
      "nhl": true,
      "ncaam": true,
      "ncaaw": false
    },
    "nhl": {
      "favorite_teams": ["TB"],
      "show_odds": true,
      "live_priority": true,
      ...all existing nhl_scoreboard config...
    },
    "ncaam": {
      "favorite_teams": ["RIT"],
      ...all existing ncaam_hockey_scoreboard config...
    },
    "display_modes": {
      "hockey_live": true,
      "hockey_recent": true,
      "hockey_upcoming": true
    },
    "background_service": {
      "enabled": true,
      "max_workers": 3,
      "request_timeout": 30
    }
  }
}
```

## Testing Requirements

After plugins are created, each needs:

- ✅ Config validation testing
- ✅ Display mode functionality
- ✅ Font override testing (Web UI)
- ✅ Plugin installation testing
- ✅ On-device testing (Raspberry Pi) - **REQUIRED**

## Total Estimated Remaining Work

- **Phase 1 remaining**: 6-9 hours
- **Phase 2 (Sports)**: 20-25 hours  
- **Phase 2 (Advanced)**: 10-14 hours
- **Phase 3**: 4-6 hours
- **Testing & Documentation**: 4-6 hours

**Total**: ~44-60 hours of development work

## Current Session Accomplishments

✅ Created comprehensive migration plan  
✅ Created **weather** plugin (full-featured)  
✅ Created **static-image** plugin (complete)  
✅ Created **text-display** plugin (scrolling & static)  
✅ Established plugin structure pattern  
✅ Documented font manager integration  
✅ Documented cache manager integration  
✅ Created progress tracking system  

## Recommendations for Completion

### Option 1: Priority-Based (Recommended)
Focus on plugins currently enabled in your config:
1. hockey-scoreboard (NHL/NCAA M)
2. odds-ticker  
3. leaderboard
4. Other sports as seasons start

### Option 2: Phase-Based
Complete each phase fully before moving to next:
1. Finish Phase 1 (3 plugins)
2. Complete Phase 2 (9 plugins)
3. Finish Phase 3 (2 plugins)

### Option 3: Iterative
Create one plugin per sport first, test thoroughly, then create remaining:
1. Create hockey-scoreboard (test)
2. Create football-scoreboard (test)
3. Create basketball-scoreboard (test)
4. etc.

## Files Ready for Review

The following plugins are complete and ready for testing:

1. `plugins/weather/` - Full weather display
2. `plugins/static-image/` - Image display
3. `plugins/text-display/` - Scrolling text

Each includes:
- ✅ manifest.json with complete metadata
- ✅ config_schema.json for Web UI generation
- ✅ manager.py with BasePlugin inheritance
- ✅ requirements.txt with dependencies
- ✅ README.md with comprehensive documentation

## Next Session Goals

When resuming this work:

1. Complete remaining Phase 1 plugins OR
2. Start with hockey-scoreboard (highest priority for your setup) OR
3. Create a sports plugin template that can be reused

The foundation is solid, patterns are established, and the path forward is clear!

