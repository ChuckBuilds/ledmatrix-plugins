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

# Hockey Scoreboard Plugin

Display live, recent, and upcoming hockey games across NHL, NCAA Men's, and NCAA Women's hockey on your LED matrix.


Recent Game:

<img width="768" height="192" alt="led_matrix_1764889670771" src="https://github.com/user-attachments/assets/1d32b4d9-7d01-4cb2-896b-bc9c889bf188" />

Upcoming Game:

<img width="768" height="192" alt="led_matrix_1764889695301" src="https://github.com/user-attachments/assets/5e6dd53c-0486-4d42-bdaa-6d486729bcc4" />




## Features

- **Multi-League Support**: NHL, NCAA Men's Hockey, NCAA Women's Hockey
- **Live Game Tracking**: Real-time scores, periods, time remaining
- **Recent Games**: View recently completed game results
- **Upcoming Games**: See scheduled games with start times
- **Favorite Teams**: Prioritize your favorite teams across all leagues
- **Power Play Indicators**: Highlight power play situations
- **Shots on Goal**: Optional SOG statistics display
- **Team Logos**: Display team logos when available
- **Background Data Fetching**: Efficient API calls with caching
- **Font Customization**: Override fonts via Web UI

## Requirements

- LEDMatrix 2.0.0+
- Display: Minimum 64x32 pixels (recommended)
- No API key required (uses ESPN public API)
- Internet connection for live data


#### League Selection

- **`leagues.nhl`**: Enable NHL games (default: true)
- **`leagues.ncaa_mens`**: Enable NCAA Men's Hockey (default: false)
- **`leagues.ncaa_womens`**: Enable NCAA Women's Hockey (default: false)

  (note: College Club Hockey is not tracked - team like UGA does not have D1 hockey and cannot be shown)

Enable multiple leagues to see games from all selected leagues in rotation.

## 📺 Display Modes

The plugin registers granular display modes directly in `manifest.json`. The display controller rotates through these modes automatically:

**NHL Modes:**
- `nhl_recent`: Recently completed NHL games with final scores
- `nhl_upcoming`: Scheduled NHL games with start times
- `nhl_live`: Currently active NHL games with real-time updates

**NCAA Men's Hockey Modes:**
- `ncaa_mens_recent`: Recently completed NCAA Men's Hockey games with final scores
- `ncaa_mens_upcoming`: Scheduled NCAA Men's Hockey games with start times
- `ncaa_mens_live`: Currently active NCAA Men's Hockey games with real-time updates

**NCAA Women's Hockey Modes:**
- `ncaa_womens_recent`: Recently completed NCAA Women's Hockey games with final scores
- `ncaa_womens_upcoming`: Scheduled NCAA Women's Hockey games with start times
- `ncaa_womens_live`: Currently active NCAA Women's Hockey games with real-time updates

### How Rotation Works

The display controller rotates through all registered modes in the order they appear in `manifest.json`. Each mode's duration is configured under `<league>.display_durations.{base,live,recent,upcoming}` (or the cross-league fallback `defaults.display_duration`).

**Default Rotation Order:**
1. `nhl_recent`
2. `nhl_upcoming`
3. `nhl_live`
4. `ncaa_mens_recent`
5. `ncaa_mens_upcoming`
6. `ncaa_mens_live`
7. `ncaa_womens_recent`
8. `ncaa_womens_upcoming`
9. `ncaa_womens_live`

**Customizing Rotation Order:**
You can reorder modes in `manifest.json` to change the rotation sequence. For example, to show all Recent games before Upcoming:

```json
"display_modes": [
  "nhl_recent",
  "ncaa_mens_recent",
  "ncaa_womens_recent",
  "nhl_upcoming",
  "ncaa_mens_upcoming",
  "ncaa_womens_upcoming",
  "nhl_live",
  "ncaa_mens_live",
  "ncaa_womens_live"
]
```

### Disabled Leagues/Modes

If a league or mode is disabled in the config, the plugin returns `False` for that mode, and the display controller automatically skips it. This allows you to:

- Disable entire leagues (e.g., disable NCAA Men's to show only NHL)
- Disable specific modes per league (e.g., disable `nhl_upcoming` but keep `nhl_recent` and `nhl_live`)
- Mix and match enabled/disabled modes as needed

### Mode Durations

Each granular mode respects its own mode duration settings:
- `nhl_recent` uses `nhl.mode_durations.recent_mode_duration` or falls back to dynamic calculation
- `ncaa_mens_upcoming` uses `ncaa_mens.mode_durations.upcoming_mode_duration` or falls back to dynamic calculation
- Each mode can have independent duration configuration

### Live Priority

When live games are available, the display controller prioritizes live modes (`nhl_live`, `ncaa_mens_live`, `ncaa_womens_live`) based on the `has_live_content()` and `get_live_modes()` methods. The plugin returns only the granular live modes that actually have live content.

## ⏱️ Duration Configuration

The plugin offers flexible duration control at multiple levels to fine-tune your display experience:

### Per-Game Duration

Controls how long each individual game displays before rotating to the next game **within the same mode**.

**Configuration:**
- Per-league `display_durations.live`: Seconds per live game (default: 20s for NHL)
- Per-league `display_durations.recent`: Seconds per recent game (default: 15s)
- Per-league `display_durations.upcoming`: Seconds per upcoming game (default: 15s)

**Example:** With `nhl.display_durations.recent: 15`, each NHL recent game shows for 15 seconds before moving to the next.

### Per-Mode Duration

Controls the **total time** a mode displays before rotating to the next mode, regardless of how many games are available.

**Configuration:**
- `nhl.mode_durations.recent_mode_duration`: Total seconds for NHL Recent mode (default: dynamic)
- `nhl.mode_durations.upcoming_mode_duration`: Total seconds for NHL Upcoming mode (default: dynamic)
- `nhl.mode_durations.live_mode_duration`: Total seconds for NHL Live mode (default: dynamic)
- Same structure for `ncaa_mens` and `ncaa_womens`

**Example:** With `nhl.mode_durations.recent_mode_duration: 60` and `nhl.display_durations.recent: 15`, NHL Recent mode shows 4 games (60s ÷ 15s = 4) before rotating to the next mode.

### How They Work Together

**Per-game duration** + **Per-mode duration**:
```text
NHL Recent Mode (60s total):
  ├─ Game 1: 15s
  ├─ Game 2: 15s
  ├─ Game 3: 15s
  └─ Game 4: 15s
  → Rotate to NHL Upcoming Mode

NHL Upcoming Mode (60s total):
  ├─ Game 1: 15s
  └─ ... (continues)
```

### Resume Functionality

When a mode times out before showing all games, it **resumes from where it left off** on the next cycle:

```text
Cycle 1: NHL Recent Mode (60s, 10 games available)
  ├─ Game 1-4 shown ✓
  └─ Time expires → Rotate

Cycle 2: NHL Recent Mode resumes
  ├─ Game 5-8 shown ✓ (continues from Game 4, no repetition)
  └─ Time expires → Rotate

Cycle 3: NHL Recent Mode resumes
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
  "nhl": {
    "mode_durations": {
      "recent_mode_duration": 45,
      "upcoming_mode_duration": 30
    }
  },
  "ncaa_mens": {
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

#### Favorite Teams

Specify team abbreviations for each league:

```json
"favorite_teams": {
  "nhl": ["TB", "TOR", "BOS", "DET"],
  "ncaa_mens": ["BU", "BC", "MICH"],
  "ncaa_womens": ["WISC", "MINN"]
}
```


#### Display Settings

The full set of options lives in
[`config_schema.json`](config_schema.json) — the schema is the source of
truth and is what generates the web UI. The most commonly tweaked keys:

- **`enabled`** (boolean, default `false`) — master switch for the plugin
- **`defaults.display_duration`** (5–60s, default `15`) — fallback per-game
  duration when a league doesn't override it
- **`defaults.show_records`** (boolean, default `false`) — show team
  records (W-L)
- **`defaults.show_shots_on_goal`** (boolean, default `false`) — show SOG
  during live games
- **`defaults.show_powerplay`** (boolean, default `true`) — highlight power
  play situations
- **`defaults.update_interval_seconds`** (30–86400s, default `3600`) —
  default base poll interval. Per-league `update_intervals.*` overrides
  this.

Each league (`nhl`, `ncaa_mens`, `ncaa_womens`) then has its own block with
finer-grained controls:

- `<league>.update_intervals.{base,live,recent,upcoming,odds}` — how often
  to poll ESPN for each kind of data. Live games default to 30s; recent
  and upcoming default to 3600s.
- `<league>.display_durations.{base,live,recent,upcoming}` — per-mode
  display duration overrides for that league.
- `<league>.display_options.{show_records,show_ranking,show_odds,...}` —
  per-league overrides of the cross-league defaults.
- `<league>.live_priority` (boolean) — let this league's live games take
  over the rotation when one is in progress.

## Display Mode Details

### Live Games (e.g., `nhl_live`, `ncaa_mens_live`)

Shows games currently in progress with:
- Current score
- Period (P1, P2, P3, OT, OT2, etc.)
- Time remaining in period
- Power play indicator (if enabled)
- Shots on goal (if enabled)

### Recent Games (e.g., `nhl_recent`, `ncaa_mens_recent`)

Shows completed games from the last X hours with:
- Final score
- Game status ("Final", "Final/OT", "Final/SO")
- Team logos

### Upcoming Games (e.g., `nhl_upcoming`, `ncaa_mens_upcoming`)

Shows scheduled games for the next X hours with:
- Game start time
- Venue information
- Team matchup

## Setup Instructions

### 1. Install Plugin

Install from the Plugin Store in the LEDMatrix web UI:

1. Open `http://your-pi-ip:5000`
2. Open the **Plugin Manager** tab
3. Find **Hockey Scoreboard** in the **Plugin Store** section and click
   **Install**
4. The plugin appears in **Installed Plugins** above and gets its own tab
   in the second nav row — open that tab to configure it

### 2. Configure Leagues

Enable the leagues you want to track:

- **NHL Only**: Set `leagues.nhl: true`, others false
- **All Leagues**: Set all to true
- **NCAA Only**: Enable `ncaa_mens` and/or `ncaa_womens`

### 3. Add Favorite Teams

Add your favorite team abbreviations to the `favorite_teams` object for each league. Games involving these teams will be shown first when `<league>.live_priority` is enabled.

### 4. Adjust Display Settings

- Set `<league>.display_durations.{base,live,recent,upcoming}` (or the fallback `defaults.display_duration`) based on how many games you expect (shorter = more games shown)
- Adjust `<league>.update_intervals.{base,live,recent,upcoming,odds}` (or the fallback `defaults.update_interval_seconds`) based on desired freshness (30s live poll recommended)
- Enable/disable display modes based on preference

### 5. Enable Plugin

Make sure `enabled: true` in the configuration and the plugin is activated in the rotation.


## Troubleshooting

**No games showing:**
- Check that at least one league is enabled in config
- Verify the season is active for enabled leagues
- Check `recent_games_hours` and `upcoming_games_hours` settings
- Ensure internet connection is working

**Games not updating:**
- Check `<league>.update_intervals.*` (or `defaults.update_interval_seconds`) settings
- Verify API is responding (check logs)
- Try clearing cache: restart plugin or clear cache manually
- Check background service is enabled

**Favorite teams not showing:**
- Verify team abbreviations are correct (case-sensitive)
- Ensure `<league>.live_priority` is true
- Check that favorite teams have games in current time window

**Logos not displaying:**
- Verify logo assets are available in LEDMatrix installation
- Check `assets/sports/nhl_logos` and `assets/sports/ncaa_logos` directories
- Some NCAA teams may not have logos available

**Power play not showing:**
- Enable `show_powerplay` in config
- Verify ESPN API includes situation data (may not be available for all leagues)

**SOG not accurate:**
- Enable `defaults.show_shots_on_goal` (or the per-league override `<league>.display_options.show_shots_on_goal`) in config
- ESPN API may have delayed SOG updates
- Some leagues may not provide SOG data

## Advanced Configuration

### Custom Fonts

Override default fonts via config or Web UI:

```json
"fonts": {
  "team_name": {
    "family": "press_start",
    "size": 10,
    "color": "#FFFFFF"
  },
  "score": {
    "family": "press_start",
    "size": 12,
    "color": "#FFC800"
  },
  "status": {
    "family": "four_by_six",
    "size": 6,
    "color": "#00FF00"
  }
}
```

### Layout Customization

The plugin supports fine-tuning element positioning for custom display sizes. All offsets are relative to the default calculated positions, allowing you to adjust elements without breaking the layout.

#### Accessing Layout Settings

Layout customization is available in the plugin's tab in the web UI:
1. Open the **Hockey Scoreboard** tab (second nav row)
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

### Multi-League Strategy

Enable all three leagues for comprehensive coverage:

```json
"leagues": {
  "nhl": true,
  "ncaa_mens": true,
  "ncaa_womens": true
}
```

Games from all leagues will be mixed and sorted by:
1. Live games first
2. Favorite teams (if enabled)
3. Start time

## Data Source

This plugin uses the **ESPN public API** for all hockey data:

- **NHL**: `https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard`
- **NCAA M**: `https://site.api.espn.com/apis/site/v2/sports/hockey/mens-college-hockey/scoreboard`
- **NCAA W**: `https://site.api.espn.com/apis/site/v2/sports/hockey/womens-college-hockey/scoreboard`

**Note**: No API key required. Please use responsibly and respect ESPN's rate limits.

## Examples

### NHL Only Configuration

```json
{
  "enabled": true,
  "leagues": {
    "nhl": true,
    "ncaa_mens": false,
    "ncaa_womens": false
  },
  "favorite_teams": {
    "nhl": ["TB", "TOR", "BOS"]
  },
  "defaults": {
    "update_interval_seconds": 60,
    "display_duration": 15
  },
  "nhl": {
    "enabled": true,
    "display_modes": {
      "live": true,
      "recent": true,
      "upcoming": false
    },
    "update_intervals": {
      "base": 60,
      "live": 30
    },
    "display_durations": {
      "base": 15,
      "live": 20
    }
  }
}
```

### NCAA Men's Only Configuration

```json
{
  "enabled": true,
  "leagues": {
    "nhl": false,
    "ncaa_mens": true,
    "ncaa_womens": false
  },
  "favorite_teams": {
    "ncaa_mens": ["BU", "BC", "MICH", "WISC"]
  },
  "ncaa_mens": {
    "enabled": true,
    "display_modes": {
      "live": true,
      "recent": true,
      "upcoming": true
    },
    "update_intervals": {
      "base": 120
    },
    "upcoming_games_hours": 168
  }
}
```

### All Leagues Configuration

```json
{
  "enabled": true,
  "leagues": {
    "nhl": true,
    "ncaa_mens": true,
    "ncaa_womens": true
  },
  "favorite_teams": {
    "nhl": ["TB", "DET"],
    "ncaa_mens": ["MICH"],
    "ncaa_womens": ["WISC"]
  },
  "defaults": {
    "show_shots_on_goal": true,
    "show_powerplay": true
  },
  "nhl": {
    "enabled": true,
    "live_priority": true,
    "display_modes": {
      "live": true,
      "recent": true,
      "upcoming": true
    }
  },
  "ncaa_mens": {
    "enabled": true,
    "display_modes": {
      "live": true,
      "recent": true,
      "upcoming": true
    }
  },
  "ncaa_womens": {
    "enabled": true,
    "display_modes": {
      "live": true,
      "recent": true,
      "upcoming": true
    }
  }
}
```

## Integration Notes

### Base Classes

This plugin uses LEDMatrix base classes:
- `Hockey` - Base hockey functionality
- `HockeyLive` - Live game display logic
- `SportsRecent` - Recent games display
- `SportsUpcoming` - Upcoming games display

These are imported from the main LEDMatrix installation at `src/base_classes/`.

### Caching

The plugin uses LEDMatrix's `CacheManager` to cache API responses:
- Cache duration: 5 minutes for live data
- Cache key format: `hockey_{league}_{date}`
- Automatic cache invalidation on date change

### Background Service

Uses LEDMatrix's `BackgroundDataService` for:
- Non-blocking API requests
- Automatic retries on failure
- Request prioritization
- Timeout handling

## Performance

### Resource Usage

- **CPU**: Low (background fetching, cached data)
- **Memory**: ~5–10 MB for game data
- **Network**: ~1–5 KB per API call per league
- **API calls**: depends on how many leagues are enabled and which
  `update_intervals` you set. With defaults (NHL only, base 60s, live 30s,
  recent/upcoming 3600s) and no live games, expect about one ESPN call per
  minute per enabled league.

### Optimization Tips

1. **Disable Unused Leagues**: Only enable leagues you follow
2. **Increase Update Interval**: Use 120-300s during off-season
3. **Reduce Time Windows**: Lower `recent_games_hours` and `upcoming_games_hours`
4. **Enable Caching**: Keep `background_service.enabled: true`

## License

GPL-3.0 License - see main LEDMatrix repository for details.

## Support

- **Issues**: [GitHub Issues](https://github.com/ChuckBuilds/ledmatrix-plugins/issues)
- **Documentation**: see the LEDMatrix
  [`docs/`](https://github.com/ChuckBuilds/LEDMatrix/tree/main/docs) directory
- **Community**: [Discussions](https://github.com/ChuckBuilds/LEDMatrix/discussions)

---

For the current version, author, category and tags see
[`manifest.json`](manifest.json) — that's the source of truth and is
what the Plugin Store reads.

