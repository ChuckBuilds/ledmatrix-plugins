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

# Basketball Scoreboard Plugin

A plugin for LEDMatrix that displays live, recent, and upcoming basketball games across NBA, NCAA Men's Basketball, NCAA Women's Basketball, and WNBA leagues.

## Features

- **Multiple League Support**: NBA, NCAA Men's Basketball, NCAA Women's Basketball, WNBA
- **Live Game Tracking**: Real-time scores, quarters, time remaining
- **Recent Games**: Recently completed games with final scores
- **Upcoming Games**: Scheduled games with start times
- **Favorite Teams**: Prioritize games involving your favorite teams
- **Live Priority Mode**: Live games can interrupt normal rotation when enabled
- **Background Data Fetching**: Efficient API calls without blocking display
- **Per-League Configuration**: Independent settings for each league
- **Flexible Display Options**: Show records, rankings, and betting odds
- **Advanced Filtering**: Control which teams and games are displayed

## Configuration

### Global Settings

- `display_duration`: How long the plugin mode is shown before rotating to next plugin (5-300 seconds, default: 30)
- `update_interval`: How often to fetch new data in seconds (30-86400, default: 3600)
- `game_display_duration`: Duration to show each individual game before rotating to next game (3-60 seconds, default: 15)
- `background_service`: Configure API request settings (timeout, retries, priority)

### Per-League Settings

#### NBA Configuration

```json
{
  "nba": {
    "enabled": true,
    "favorite_teams": ["LAL", "BOS", "GSW"],
    "display_modes": {
      "show_live": true,
      "show_recent": true,
      "show_upcoming": true
    },
    "live_priority": true,
    "live_game_duration": 20,
    "live_update_interval": 30,
    "update_interval_seconds": 3600,
    "game_limits": {
      "recent_games_to_show": 1,
      "upcoming_games_to_show": 1
    },
    "display_options": {
      "show_records": false,
      "show_ranking": false,
      "show_odds": true
    },
    "filtering": {
      "show_favorite_teams_only": true,
      "show_all_live": false
    },
    "display_durations": {
      "base": 15,
      "live": 20,
      "recent": 15,
      "upcoming": 15
    }
  }
}
```

**Configuration Options:**

- `enabled`: Enable/disable NBA games (default: true)
- `favorite_teams`: Array of team abbreviations (e.g., ["LAL", "BOS", "GSW"])
- `display_modes`: Control which game types to show
  - `show_live`: Show live games (default: true)
  - `show_recent`: Show recently completed games (default: true)
  - `show_upcoming`: Show upcoming games (default: true)
- `live_priority`: Give live games priority over other modes - interrupts normal rotation (default: true)
- `live_game_duration`: Duration in seconds to display each live game (10-120, default: 20)
- `live_update_interval`: How often to update live game data in seconds (5-300, default: 30)
- `update_interval_seconds`: How often to fetch new data in seconds (30-86400, default: 3600)
- `game_limits`: Control how many games to show
  - `recent_games_to_show`: With favorite teams: per team (e.g., 1 with 2 teams = 2 games). Without favorites: total games (default: 1)
  - `upcoming_games_to_show`: With favorite teams: per team (e.g., 2 with 3 teams = up to 6 games). Without favorites: total games (default: 1)
- `display_options`: Additional information to show
  - `show_records`: Show team win-loss records (default: false)
  - `show_ranking`: Show team rankings when available (default: false)
  - `show_odds`: Show betting odds (default: true)
- `filtering`: Control which teams are shown
  - `show_favorite_teams_only`: Only show games from favorite teams (default: true)
  - `show_all_live`: Show all live games, not just favorites (default: false)
- `display_durations`: Per-mode display durations in seconds (5-120)
  - `base`: Base duration (default: 15)
  - `live`: Live games duration (default: 20)
  - `recent`: Recent games duration (default: 15)
  - `upcoming`: Upcoming games duration (default: 15)

#### NCAA Men's Basketball Configuration

**Note**: Full season data is only fetched for teams in `favorite_teams`. Recent/Upcoming modes require favorite teams to be configured.

```json
{
  "ncaam": {
    "enabled": true,
    "favorite_teams": ["DUKE", "UNC", "KANSAS"],
    "display_modes": {
      "show_live": true,
      "show_recent": true,
      "show_upcoming": true
    },
    "live_priority": true,
    "live_game_duration": 20,
    "live_update_interval": 30,
    "update_interval_seconds": 3600,
    "game_limits": {
      "recent_games_to_show": 1,
      "upcoming_games_to_show": 1
    },
    "display_options": {
      "show_records": false,
      "show_ranking": false,
      "show_odds": true
    },
    "filtering": {
      "show_favorite_teams_only": true,
      "show_all_live": false
    }
  }
}
```

**Configuration Options:** Same as NBA (see NBA Configuration section above for detailed descriptions).

#### NCAA Women's Basketball Configuration

**Note**: Full season data is only fetched for teams in `favorite_teams`. Recent/Upcoming modes require favorite teams to be configured.

```json
{
  "ncaaw": {
    "enabled": true,
    "favorite_teams": ["UCONN", "SCAR", "STAN"],
    "display_modes": {
      "show_live": true,
      "show_recent": true,
      "show_upcoming": true
    },
    "live_priority": true,
    "live_game_duration": 20,
    "live_update_interval": 30,
    "update_interval_seconds": 3600,
    "game_limits": {
      "recent_games_to_show": 1,
      "upcoming_games_to_show": 1
    },
    "display_options": {
      "show_records": false,
      "show_ranking": false,
      "show_odds": true
    },
    "filtering": {
      "show_favorite_teams_only": true,
      "show_all_live": false
    }
  }
}
```

**Configuration Options:** Same as NBA (see NBA Configuration section above for detailed descriptions).

#### WNBA Configuration

```json
{
  "wnba": {
    "enabled": true,
    "favorite_teams": ["LVA", "NYL", "CHI"],
    "display_modes": {
      "show_live": true,
      "show_recent": true,
      "show_upcoming": true
    },
    "live_priority": true,
    "live_game_duration": 20,
    "live_update_interval": 30,
    "update_interval_seconds": 3600,
    "game_limits": {
      "recent_games_to_show": 1,
      "upcoming_games_to_show": 1
    },
    "display_options": {
      "show_records": false,
      "show_ranking": false,
      "show_odds": true
    },
    "filtering": {
      "show_favorite_teams_only": true,
      "show_all_live": false
    }
  }
}
```

**Configuration Options:** Same as NBA (see NBA Configuration section above for detailed descriptions).

## Display Modes

The plugin registers granular display modes per league. Each league has three modes:

### NBA Modes
- **nba_live**: Shows currently active NBA games
- **nba_recent**: Shows recently completed NBA games
- **nba_upcoming**: Shows scheduled upcoming NBA games

### WNBA Modes
- **wnba_live**: Shows currently active WNBA games
- **wnba_recent**: Shows recently completed WNBA games
- **wnba_upcoming**: Shows scheduled upcoming WNBA games

### NCAA Men's Basketball Modes
- **ncaam_live**: Shows currently active NCAA Men's games
- **ncaam_recent**: Shows recently completed NCAA Men's games
- **ncaam_upcoming**: Shows scheduled upcoming NCAA Men's games

### NCAA Women's Basketball Modes
- **ncaaw_live**: Shows currently active NCAA Women's games
- **ncaaw_recent**: Shows recently completed NCAA Women's games
- **ncaaw_upcoming**: Shows scheduled upcoming NCAA Women's games

### Live Priority Mode

When `live_priority` is enabled for a league, live games will:
- Interrupt the normal mode rotation
- Be displayed immediately when available
- Take priority over other plugin modes
- Only show if there are actual live games available

This feature allows you to never miss live action - when a game goes live, it will automatically be shown on the display, even if other content was scheduled.

## Team Abbreviations

### NBA Teams
Common abbreviations: LAL, BOS, GSW, MIL, PHI, DEN, MIA, BKN, ATL, CHA, NYK, IND, DET, TOR, CHI, CLE, ORL, WAS, HOU, SAS, MIN, POR, SAC, LAC, MEM, DAL, PHX, UTA, OKC, NOP

### NCAA Men's Basketball Teams
Common abbreviations: DUKE, UNC, KANSAS, KENTUCKY, UCLA, ARIZONA, GONZAGA, BAYLOR, VILLANOVA, MICHIGAN, OHIOST, FLORIDA, WISCONSIN, MARYLAND, VIRGINIA, LOUISVILLE, SYRACUSE, INDIANA, PURDUE, IOWA

### NCAA Women's Basketball Teams
Common abbreviations: UCONN, SCAR (South Carolina), STAN (Stanford), BAYLOR, LOUISVILLE, OREGON, MISSST (Mississippi State), NDAME (Notre Dame), DUKE, MARYLAND, UCLA, ARIZONA, OREGONST (Oregon State), FLORIDA, TENNESSEE, TEXAS, OKLAHOMA, IOWA

### WNBA Teams
Common abbreviations: LVA (Las Vegas Aces), NYL (New York Liberty), CHI (Chicago Sky), CONN (Connecticut Sun), DAL (Dallas Wings), ATL (Atlanta Dream), IND (Indiana Fever), MIN (Minnesota Lynx), PHX (Phoenix Mercury), SEA (Seattle Storm), WAS (Washington Mystics), LAC (Los Angeles Sparks)

## Background Service

The plugin uses background data fetching for efficient API calls:

- Requests timeout after 30 seconds (configurable via `background_service.request_timeout`)
- Up to 3 retries for failed requests (configurable via `background_service.max_retries`)
- Priority level 2 (medium priority, configurable via `background_service.priority`)

Configure in `background_service`:
```json
{
  "background_service": {
    "request_timeout": 30,
    "max_retries": 3,
    "priority": 2
  }
}
```

## Data Source

Game data is fetched from ESPN's public API endpoints for all supported basketball leagues.

### NCAA Basketball Season Data

**Important**: For NCAA Men's and Women's Basketball, full season data is only fetched for teams in your `favorite_teams` list:

- **Live Mode**: Shows all current/live games (not limited to favorite teams)
- **Recent/Upcoming Modes**: Only displays games from your favorite teams' full season schedules
- **No Favorite Teams**: If no favorite teams are configured, Recent/Upcoming modes will only show games from the current scoreboard (limited data)

This approach works around ESPN API limitations that prevent fetching full season schedules via date ranges for college basketball. The plugin uses team-specific schedule endpoints (`/teams/{id}/schedule`) to get complete season data for each favorite team.

**NBA and WNBA**: These leagues support date range queries, so full season data is available regardless of favorite teams configuration.

## Dependencies

This plugin requires the main LEDMatrix installation and inherits functionality from the Basketball base classes.

## Installation

The easiest way is the Plugin Store in the LEDMatrix web UI:

1. Open `http://your-pi-ip:5000`
2. Open the **Plugin Manager** tab
3. Find **Basketball Scoreboard** in the **Plugin Store** section and
   click **Install**
4. Open the plugin's tab in the second nav row to configure favorite
   teams and per-league preferences

Manual install: copy this directory into your LEDMatrix
`plugins_directory` (default `plugin-repos/`) and restart the display
service.

## Game Limits Behavior

The `game_limits` configuration behaves differently based on whether favorite teams are configured:

### With Favorite Teams
- `recent_games_to_show`: Number of recent games **per team**
  - Example: `1` with 2 favorite teams = up to 2 games total (1 per team)
  - Example: `2` with 3 favorite teams = up to 6 games total (2 per team)
- `upcoming_games_to_show`: Number of upcoming games **per team**
  - Example: `1` with 2 favorite teams = up to 2 games total (1 per team)
  - Example: `3` with 2 favorite teams = up to 6 games total (3 per team)

### Without Favorite Teams
- `recent_games_to_show`: Total number of most recent games to show
  - Example: `5` = show the 5 most recent games total
- `upcoming_games_to_show`: Total number of next upcoming games to show
  - Example: `1` = show only the next 1 game total

## Filtering Options

The `filtering` section controls which games are displayed:

- `show_favorite_teams_only` (default: true): When enabled, only shows games involving your favorite teams. When disabled, shows all games.
- `show_all_live` (default: false): When enabled, shows all live games regardless of favorite teams setting. This is useful if you want to see all live action even if you only have favorite teams configured for recent/upcoming modes.

**Note**: For live mode, if `show_all_live` is true, all live games will be shown. If false and `show_favorite_teams_only` is true, only live games involving favorite teams will be shown.

## Troubleshooting

- **No games showing**: 
  - Check if leagues are enabled in configuration
  - Verify API endpoints are accessible
  - Check if favorite teams are configured (required for NCAA recent/upcoming modes)
  - Review filtering settings - may be filtering out all games
  
- **Missing team logos**: Ensure team logo files exist in your `assets/sports/` directory

- **Slow updates**: 
  - Adjust `update_interval_seconds` in league configuration
  - Adjust `live_update_interval` for live games
  - Check network connectivity and API response times

- **API errors**: 
  - Check your internet connection
  - Verify ESPN API availability
  - Review logs for specific error messages
  - Check if rate limiting is occurring

- **Live games not interrupting**: 
  - Verify `live_priority` is enabled for the league
  - Check that there are actual live games available
  - Review `has_live_content()` logs to see if live content is detected

- **Too many/few games showing**: 
  - Adjust `game_limits.recent_games_to_show` and `game_limits.upcoming_games_to_show`
  - Remember: with favorite teams, these are per-team limits
  - Without favorite teams, these are total game limits
