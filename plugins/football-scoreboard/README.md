# Football Scoreboard Plugin

A plugin for LEDMatrix that displays live, recent, and upcoming football games across NFL and NCAA Football leagues.

## Features

- **Multiple League Support**: NFL and NCAA Football
- **Live Game Tracking**: Real-time scores, quarters, time remaining
- **Recent Games**: Recently completed games with final scores
- **Upcoming Games**: Scheduled games with start times
- **Favorite Teams**: Prioritize games involving your favorite teams
- **Football-Specific Details**: Down & distance, possession indicators
- **Background Data Fetching**: Efficient API calls without blocking display

## Configuration

### Global Settings

- `display_duration`: How long to show each game (5-60 seconds, default: 15)
- `show_records`: Display team win-loss records (default: false)
- `show_ranking`: Display team rankings when available (default: false)
- `background_service`: Configure API request settings

### Per-League Settings

#### NFL Configuration

```json
{
  "nfl": {
    "enabled": true,
    "favorite_teams": ["TB", "DAL", "GB"],
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

#### NCAA Football Configuration

```json
{
  "ncaa_fb": {
    "enabled": true,
    "favorite_teams": ["UGA", "AUB", "BAMA"],
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

1. **football_live**: Shows currently active games
2. **football_recent**: Shows recently completed games
3. **football_upcoming**: Shows scheduled upcoming games

## Team Abbreviations

### NFL Teams
Common abbreviations: TB, DAL, GB, KC, BUF, SF, PHI, NE, MIA, NYJ, LAC, DEN, LV, CIN, BAL, CLE, PIT, IND, HOU, TEN, JAX, ARI, LAR, SEA, WAS, NYG, MIN, DET, CHI, ATL, CAR, NO

### NCAA Football Teams
Common abbreviations: UGA (Georgia), AUB (Auburn), BAMA (Alabama), CLEM (Clemson), OSU (Ohio State), MICH (Michigan), FSU (Florida State), LSU (LSU), OU (Oklahoma), TEX (Texas)

## Background Service

The plugin uses background data fetching for efficient API calls:

- Requests timeout after 30 seconds (configurable)
- Up to 3 retries for failed requests
- Priority level 2 (medium priority)

## Data Source

Game data is fetched from ESPN's public API endpoints for both NFL and NCAA Football.

## Dependencies

This plugin requires the main LEDMatrix installation and inherits functionality from the Football base classes.

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
