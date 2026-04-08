-----------------------------------------------------------------------------------
### Connect with ChuckBuilds

- Show support on Youtube: https://www.youtube.com/@ChuckBuilds
- Stay in touch on Instagram: https://www.instagram.com/ChuckBuilds/
- Want to chat or need support? Reach out on the ChuckBuilds Discord: https://discord.com/invite/uW36dVAtcT
- Feeling Generous? Support the project:
  - Github Sponsorship: https://github.com/sponsors/ChuckBuilds
  - Buy Me a Coffee: https://buymeacoffee.com/chuckbuilds
  - Ko-fi: https://ko-fi.com/chuckbuilds/ 

-----------------------------------------------------------------------------------

# Football Scoreboard Plugin

A production-ready plugin for LEDMatrix that displays live, recent, and upcoming football games across NFL and NCAA Football leagues. This plugin reuses the proven, battle-tested code from the main LEDMatrix project for maximum reliability and feature completeness.

## 🏈 Features

Upcoming Game (NCAA FB):

<img width="768" height="192" alt="led_matrix_1764889978847" src="https://github.com/user-attachments/assets/3561386b-1327-415d-92bc-f17f7e446984" />

Recent Game (NCAA FB):

<img width="768" height="192" alt="led_matrix_1764889931266" src="https://github.com/user-attachments/assets/a5361ddf-5472-4724-9665-1783db4eb3d1" />



### Core Functionality
- **Multiple League Support**: NFL and NCAA Football with independent configuration
- **Live Game Tracking**: Real-time scores, quarters, time remaining, down & distance
- **Recent Games**: Recently completed games with final scores and records
- **Upcoming Games**: Scheduled games with start times and odds
- **Dynamic Team Resolution**: Support for `AP_TOP_25`, `AP_TOP_10`, `AP_TOP_5` automatic team selection
- **Production-Ready**: Real ESPN API integration with caching and error handling

### Professional Display
- **Team Logos**: Professional team logos with automatic download fallback
- **Scorebug Layout**: Broadcast-quality scoreboard display
- **Football-Specific Details**: Down & distance, possession indicators, timeout tracking
- **Color-Coded States**: Live (green), final (gray), upcoming (yellow), redzone (red)
- **Odds Integration**: Real-time betting odds display with spread and over/under
- **Rankings Display**: AP Top 25 rankings for NCAA Football teams

### Advanced Features
- **Background Data Service**: Non-blocking API calls with intelligent caching
- **Smart Filtering**: Show favorite teams only or all games
- **Granular Mode Control**: Enable/disable specific league/mode combinations independently
- **Dual Display Styles**: Switch mode (one game at a time) or scroll mode (all games scrolling)
- **High-FPS Scrolling**: Smooth 100+ FPS horizontal scrolling for scroll mode
- **Font Customization**: Customize fonts, sizes, and styles for all text elements
- **Layout Customization**: Adjust X/Y positioning offsets for all display elements
- **Error Recovery**: Graceful handling of API failures and missing data
- **Memory Optimized**: Efficient resource usage for Raspberry Pi deployment

## 🎯 Dynamic Team Resolution

The plugin supports automatic team selection using dynamic patterns:

- **`AP_TOP_25`**: Automatically includes all 25 AP Top 25 ranked teams
- **`AP_TOP_10`**: Automatically includes top 10 ranked teams  
- **`AP_TOP_5`**: Automatically includes top 5 ranked teams

These patterns update automatically as rankings change throughout the season. You can mix them with specific teams:

```json
"favorite_teams": ["AP_TOP_25", "UGA", "ALA"]
```

This will show games for all AP Top 25 teams plus Georgia and Alabama (duplicates are automatically removed).

## 📺 Display Modes

### Granular Mode Control

The plugin supports **granular display modes** that give you precise control over what's shown:

- **NFL Modes**: `nfl_live`, `nfl_recent`, `nfl_upcoming`
- **NCAA FB Modes**: `ncaa_fb_live`, `ncaa_fb_recent`, `ncaa_fb_upcoming`

Each league and game type can be independently enabled or disabled. This allows you to:
- Show only NFL live games
- Show only NCAA FB recent games
- Mix and match any combination of modes
- Control exactly which content appears on your display

### Display Style Options

The plugin supports two display styles for each game type:

1. **Switch Mode** (Default): Display one game at a time with timed transitions
   - Shows each game for a configurable duration
   - Smooth transitions between games
   - Best for focused viewing of individual games

2. **Scroll Mode**: High-FPS horizontal scrolling of all games
   - All games scroll horizontally in a continuous stream
   - League separator icons between different leagues
   - Dynamic duration based on total content width
   - Supports 100+ FPS smooth scrolling
   - Best for seeing all games at once

You can configure the display mode separately for live, recent, and upcoming games in each league.

### How Rotation Works

The plugin registers granular display modes directly in `manifest.json`. The display controller rotates through these modes automatically in the order they appear. Each mode can have its own `display_duration` configured in the plugin config.

**Default Rotation Order:**
1. `nfl_recent`
2. `nfl_upcoming`
3. `nfl_live`
4. `ncaa_fb_recent`
5. `ncaa_fb_upcoming`
6. `ncaa_fb_live`

**Customizing Rotation Order:**
You can reorder modes in `manifest.json` to change the rotation sequence. For example, to show all Recent games before Upcoming:

```json
"display_modes": [
  "nfl_recent",
  "ncaa_fb_recent",
  "nfl_upcoming",
  "ncaa_fb_upcoming",
  "nfl_live",
  "ncaa_fb_live"
]
```

**Disabled Leagues/Modes:**
If a league or mode is disabled in the config, the plugin returns `False` for that mode, and the display controller automatically skips it. This allows you to:
- Disable entire leagues (e.g., disable NCAA FB to show only NFL)
- Disable specific modes per league (e.g., disable `nfl_upcoming` but keep `nfl_recent` and `nfl_live`)
- Mix and match enabled/disabled modes as needed

### Mode Durations

Each granular mode respects its own mode duration settings:
- `nfl_recent` uses `nfl.mode_durations.recent_mode_duration` or top-level `recent_mode_duration`
- `ncaa_fb_upcoming` uses `ncaa_fb.mode_durations.upcoming_mode_duration` or top-level `upcoming_mode_duration`
- Each mode can have independent duration configuration

### Live Priority

When live games are available, the display controller prioritizes live modes (`nfl_live`, `ncaa_fb_live`) based on the `has_live_content()` and `get_live_modes()` methods. The plugin returns only the granular live modes that actually have live content.

## ⏱️ Duration Configuration

The plugin offers flexible duration control at multiple levels to fine-tune your display experience:

### Per-Game Duration

Controls how long each individual game displays before rotating to the next game **within the same mode**.

**Configuration:**
- `live_game_duration`: Seconds per live game (default: 30s)
- `recent_game_duration`: Seconds per recent game (default: 15s)
- `upcoming_game_duration`: Seconds per upcoming game (default: 15s)

**Example:** With `recent_game_duration: 15`, each recent game shows for 15 seconds before moving to the next.

### Per-Mode Duration

Controls the **total time** a mode displays before rotating to the next mode, regardless of how many games are available.

**Configuration:**
- `recent_mode_duration`: Total seconds for Recent mode (default: dynamic)
- `upcoming_mode_duration`: Total seconds for Upcoming mode (default: dynamic)
- `live_mode_duration`: Total seconds for Live mode (default: dynamic)

**Example:** With `recent_mode_duration: 60` and `recent_game_duration: 15`, Recent mode shows 4 games (60s ÷ 15s = 4) before rotating to Upcoming mode.

### How They Work Together

**Per-game duration** + **Per-mode duration**:
```
Recent Mode (60s total):
  ├─ Game 1: 15s
  ├─ Game 2: 15s
  ├─ Game 3: 15s
  └─ Game 4: 15s
  → Rotate to Upcoming Mode

Upcoming Mode (60s total):
  ├─ Game 1: 15s
  └─ ... (continues)
```

### Resume Functionality

When a mode times out before showing all games, it **resumes from where it left off** on the next cycle:

```
Cycle 1: Recent Mode (60s, 10 games available)
  ├─ Game 1-4 shown ✓
  └─ Time expires → Rotate

Cycle 2: Recent Mode resumes
  ├─ Game 5-8 shown ✓ (continues from Game 4, no repetition)
  └─ Time expires → Rotate

Cycle 3: Recent Mode resumes
  ├─ Game 9-10 shown ✓
  └─ All games shown → Full cycle complete → Reset progress
```

### Dynamic Duration (Fallback)

If per-mode durations are **not** configured, the plugin uses **dynamic calculation**:
- **Formula**: `total_duration = number_of_games × per_game_duration`
- **Example**: 24 games @ 15s each = 360 seconds for the mode

This ensures all games are shown but may result in very long mode durations if you have many games.

### Per-League Overrides

You can set different durations per league using the `mode_durations` section:

```json
{
  "nfl": {
    "mode_durations": {
      "recent_mode_duration": 45,
      "upcoming_mode_duration": 30
    }
  },
  "ncaa_fb": {
    "mode_durations": {
      "recent_mode_duration": 60
    }
  }
}
```

When multiple leagues are enabled with different durations, the system uses the **maximum** to ensure all leagues get their time.

### Integration with Dynamic Duration Caps

If you have dynamic duration caps configured (e.g., `max_duration_seconds: 120`), the system uses the **minimum** of:
- Per-mode duration (e.g., 180s)
- Dynamic duration cap (e.g., 120s)
- **Result**: 120s (ensures cap is respected)

## 🎨 Visual Features

### Professional Scorebug Display
- **Team Logos**: High-quality team logos positioned on left and right sides
- **Scores**: Centered score display with outlined text for visibility
- **Game Status**: Quarter/time display at top center
- **Date Display**: Recent games show date underneath score
- **Down & Distance**: Live game situation information (NFL only)
- **Possession Indicator**: Visual indicators for ball possession
- **Odds Display**: Spread and over/under betting lines
- **Rankings**: AP Top 25 rankings for NCAA Football
- **Customizable Layout**: Adjust positioning of all elements via X/Y offsets
- **Customizable Fonts**: Configure font family and size for each text element

### Layout Customization

The plugin supports fine-tuning element positioning for custom display sizes. All offsets are relative to the default calculated positions, allowing you to adjust elements without breaking the layout.

#### Accessing Layout Settings

Layout customization is available in the web UI under the plugin configuration section:
1. Open the **Football Scoreboard** tab (second nav row)
2. Expand the **Customization** section
3. Find the **Layout Positioning** subsection

#### Offset Values

- **Positive values**: Move element right (x_offset) or down (y_offset)
- **Negative values**: Move element left (x_offset) or up (y_offset)
- **Default (0)**: No change from calculated position

#### Available Elements

- **home_logo**: Home team logo position (x_offset, y_offset)
- **away_logo**: Away team logo position (x_offset, y_offset)
- **score**: Game score position (x_offset, y_offset)
- **status_text**: Status/period text position (x_offset, y_offset)
- **date**: Game date position (x_offset, y_offset)
- **time**: Game time position (x_offset, y_offset)
- **records**: Team records/rankings position (away_x_offset, home_x_offset, y_offset)

#### Example Adjustments

**Move logos inward for smaller displays:**
```json
{
  "customization": {
    "layout": {
      "home_logo": { "x_offset": -5 },
      "away_logo": { "x_offset": 5 }
    }
  }
}
```

**Adjust score position:**
```json
{
  "customization": {
    "layout": {
      "score": { "x_offset": 0, "y_offset": -2 }
    }
  }
}
```

**Shift records upward:**
```json
{
  "customization": {
    "layout": {
      "records": { "y_offset": -3 }
    }
  }
}
```

#### Display Size Compatibility

Layout offsets work across different display sizes. The plugin calculates default positions based on your display dimensions, and offsets are applied relative to those defaults. This ensures compatibility with various LED matrix configurations.

### Color Coding
- **Live Games**: Green text for active status
- **Redzone**: Red highlighting when teams are in scoring position
- **Final Games**: Gray text for completed games
- **Upcoming Games**: Yellow text for scheduled games
- **Odds**: Green text for betting information

## 🏷️ Team Abbreviations

### NFL Teams
Common abbreviations: TB, DAL, GB, KC, BUF, SF, PHI, NE, MIA, NYJ, LAC, DEN, LV, CIN, BAL, CLE, PIT, IND, HOU, TEN, JAX, ARI, LAR, SEA, WAS, NYG, MIN, DET, CHI, ATL, CAR, NO

### NCAA Football Teams
Common abbreviations: UGA (Georgia), AUB (Auburn), BAMA (Alabama), CLEM (Clemson), OSU (Ohio State), MICH (Michigan), FSU (Florida State), LSU (LSU), OU (Oklahoma), TEX (Texas), ORE (Oregon), MISS (Mississippi), GT (Georgia Tech), VAN (Vanderbilt), BYU (BYU)

## 🔧 Technical Details

### Architecture
This plugin reuses the proven code from the main LEDMatrix project:
- **SportsCore**: Base class for all sports functionality
- **Football**: Football-specific game detail extraction
- **NFL Managers**: Live, Recent, and Upcoming managers for NFL
- **NCAA FB Managers**: Live, Recent, and Upcoming managers for NCAA Football
- **BaseOddsManager**: Production-ready odds fetching from ESPN API
- **DynamicTeamResolver**: Automatic team resolution for rankings

### Data Sources
- **ESPN API**: Primary data source for games, scores, and rankings
- **Real-time Updates**: Live game data updates every 30 seconds
- **Intelligent Caching**: 1-hour cache for rankings, 30-minute cache for odds
- **Error Recovery**: Graceful handling of API failures

### Performance
- **Background Processing**: Non-blocking data fetching
- **Memory Optimized**: Efficient resource usage for Raspberry Pi
- **Smart Caching**: Reduces API calls while maintaining data freshness
- **Configurable Intervals**: Adjustable update frequencies per league

## 📦 Installation

### From the Plugin Store (recommended)
1. Open the LEDMatrix web interface (`http://your-pi-ip:5000`)
2. Open the **Plugin Manager** tab
3. Find **Football Scoreboard** in the **Plugin Store** section and click
   **Install**
4. Open the **Football Scoreboard** tab in the second nav row to configure
   your favorite teams and per-league preferences


## ⚙️ Configuration

### Display Mode Settings

Each league (NFL, NCAA FB) can be configured with:
- **Enable/Disable**: Turn entire leagues on or off
- **Mode Toggles**: Enable/disable live, recent, or upcoming games independently
- **Display Style**: Choose "switch" (one game at a time) or "scroll" (all games scrolling) for each game type
- **Scroll Settings**: Configure scroll speed, frame delay, gap between games, and league separators

### Customization Options

- **Font Customization**: Adjust font family and size for:
  - Score text
  - Period/time text
  - Team names
  - Status text
  - Detail text (down/distance, etc.)
  - Ranking text

- **Layout Customization**: Fine-tune positioning with X/Y offsets for:
  - Team logos (home/away)
  - Score display
  - Status/period text
  - Date and time
  - Down & distance
  - Timeouts
  - Possession indicator
  - Records/rankings
  - Betting odds

## 🐛 Troubleshooting

### Common Issues
- **No games showing**: Check if leagues are enabled and favorite teams are configured
- **Missing team logos**: Logos are automatically downloaded from ESPN API
- **Slow updates**: Adjust the `live_update_interval` in league configuration
- **API errors**: Check your internet connection and ESPN API availability
- **Dynamic teams not working**: Ensure you're using exact patterns like `AP_TOP_25`
- **Scroll mode not working**: Verify `scroll_display_mode` is set to "scroll" in config
- **Modes not appearing**: Check that specific modes (e.g., `nfl_live`) are enabled in display_modes settings


## 📊 Version History

### v2.0.7 (Current)
- ✅ **Granular Display Modes**: Independent control of NFL/NCAA FB live/recent/upcoming modes
- ✅ **Scroll Display Mode**: High-FPS horizontal scrolling of all games with league separators
- ✅ **Switch Display Mode**: One game at a time with timed transitions (default)
- ✅ **Font Customization**: Customize fonts and sizes for all text elements
- ✅ **Layout Customization**: Adjust X/Y positioning offsets for all display elements
- ✅ **Date Display**: Recent games show date underneath score
- ✅ Production-ready with real ESPN API integration
- ✅ Dynamic team resolution (AP_TOP_25, AP_TOP_10, AP_TOP_5)
- ✅ Real-time odds display with spread and over/under
- ✅ Nested configuration structure for better organization
- ✅ Full compatibility with LEDMatrix web UI
- ✅ Comprehensive error handling and caching
- ✅ Memory-optimized for Raspberry Pi deployment

### Previous Versions
- v2.0.6: Bug fixes and improvements
- v2.0.5: Production-ready release with ESPN API integration
- v2.0.4: Initial refactoring to reuse LEDMatrix core code
- v1.x: Original modular implementation

## 🤝 Contributing

This plugin is built on the proven LEDMatrix core codebase. For issues or feature requests, please use the GitHub issue tracker.

## 📄 License

This plugin follows the same license as the main LEDMatrix project.
