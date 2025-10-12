# Basketball Scoreboard Plugin

A plugin for LEDMatrix that displays live, recent, and upcoming basketball games across NBA, NCAA Men's Basketball, NCAA Women's Basketball, and WNBA leagues.

## Features

- **Multiple League Support**: NBA, NCAA Men's Basketball, NCAA Women's Basketball, WNBA
- **Live Game Tracking**: Real-time scores, quarters, time remaining
- **Recent Games**: Recently completed games with final scores
- **Upcoming Games**: Scheduled games with start times
- **Favorite Teams**: Prioritize games involving your favorite teams
- **Background Data Fetching**: Efficient API calls without blocking display

## Configuration

### Global Settings

- `display_duration`: How long to show each game (5-60 seconds, default: 15)
- `show_records`: Display team win-loss records (default: false)
- `show_ranking`: Display team rankings when available (default: false)
- `background_service`: Configure API request settings

### Per-League Settings

#### NBA Configuration

```json
{
  "nba": {
    "enabled": true,
    "favorite_teams": ["LAL", "BOS", "GSW"],
    "display_modes": {
      "live": true,
      "recent": true,
      "upcoming": true
    },
    "recent_games_to_show": 5,
    "upcoming_games_to_show": 10
  }
}
```

#### NCAA Men's Basketball Configuration

```json
{
  "ncaam_basketball": {
    "enabled": true,
    "favorite_teams": ["DUKE", "UNC", "KANSAS"],
    "display_modes": {
      "live": true,
      "recent": true,
      "upcoming": true
    },
    "recent_games_to_show": 5,
    "upcoming_games_to_show": 10
  }
}
```

#### NCAA Women's Basketball Configuration

```json
{
  "ncaaw_basketball": {
    "enabled": true,
    "favorite_teams": ["UCONN", "SCAR", "STAN"],
    "display_modes": {
      "live": true,
      "recent": true,
      "upcoming": true
    },
    "recent_games_to_show": 5,
    "upcoming_games_to_show": 10
  }
}
```

#### WNBA Configuration

```json
{
  "wnba": {
    "enabled": true,
    "favorite_teams": ["LVA", "NYL", "CHI"],
    "display_modes": {
      "live": true,
      "recent": true,
      "upcoming": true
    },
    "recent_games_to_show": 5,
    "upcoming_games_to_show": 10
  }
}
```

## Display Modes

The plugin supports three display modes:

1. **basketball_live**: Shows currently active games
2. **basketball_recent**: Shows recently completed games
3. **basketball_upcoming**: Shows scheduled upcoming games

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

- Requests timeout after 30 seconds (configurable)
- Up to 3 retries for failed requests
- Priority level 2 (medium priority)

## Data Source

Game data is fetched from ESPN's public API endpoints for all supported basketball leagues.

## Dependencies

This plugin requires the main LEDMatrix installation and inherits functionality from the Basketball base classes.

## Installation

1. Copy this plugin directory to your `ledmatrix-plugins/plugins/` folder
2. Ensure the plugin is enabled in your LEDMatrix configuration
3. Configure your favorite teams and display preferences
4. Restart LEDMatrix to load the new plugin

## Troubleshooting

- **No games showing**: Check if leagues are enabled and API endpoints are accessible
- **Missing team logos**: Ensure team logo files exist in your assets/sports/ directory
- **Slow updates**: Adjust the update interval in league configuration
- **API errors**: Check your internet connection and ESPN API availability
