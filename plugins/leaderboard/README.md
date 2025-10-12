# Leaderboard Plugin

A plugin for LEDMatrix that displays scrolling leaderboards and standings for multiple sports leagues including NFL, NBA, MLB, NCAA Football, NCAA Basketball, NHL, and more.

## Features

- **Multi-Sport Support**: NFL, NBA, MLB, NCAA Football, NCAA Basketball, NCAA Women's Basketball, NHL
- **Scrolling Ticker Display**: Continuous scrolling of standings and rankings
- **Conference/Division Filtering**: Filter by conference, division, or league
- **NCAA Rankings**: Display college football and basketball rankings
- **Team Records**: Show win-loss records and statistics
- **Dynamic Duration**: Adjust display time based on content width
- **Configurable Display**: Adjustable scroll speed, duration, and filtering options
- **Background Data Fetching**: Efficient API calls without blocking display

## Configuration

### Global Settings

- `display_duration`: How long to show the leaderboard (10-300 seconds, default: 30)
- `scroll_speed`: Scrolling speed multiplier (0.5-10, default: 2)
- `scroll_delay`: Delay between scroll steps (0.001-0.1 seconds, default: 0.01)
- `dynamic_duration`: Enable dynamic duration based on content width (default: true)
- `min_duration`: Minimum display duration (10-300 seconds, default: 30)
- `max_duration`: Maximum display duration (30-600 seconds, default: 300)
- `loop`: Continuously loop the leaderboard (default: true)

### Per-League Settings

#### NFL Configuration

```json
{
  "leagues": {
    "nfl": {
      "enabled": true,
      "conference": "both",
      "division": "all"
    }
  }
}
```

#### NBA Configuration

```json
{
  "leagues": {
    "nba": {
      "enabled": true,
      "conference": "both"
    }
  }
}
```

#### MLB Configuration

```json
{
  "leagues": {
    "mlb": {
      "enabled": true,
      "league": "both",
      "division": "all"
    }
  }
}
```

#### NCAA Football Configuration

```json
{
  "leagues": {
    "ncaa_fb": {
      "enabled": true,
      "division": "fbs",
      "show_rankings": true
    }
  }
}
```

#### NCAA Basketball Configuration

```json
{
  "leagues": {
    "ncaam_basketball": {
      "enabled": true,
      "show_rankings": true
    },
    "ncaaw_basketball": {
      "enabled": true,
      "show_rankings": true
    }
  }
}
```

#### NHL Configuration

```json
{
  "leagues": {
    "nhl": {
      "enabled": true,
      "conference": "both"
    }
  }
}
```

## Display Format

The leaderboard displays information in a scrolling format showing:

- **Rank**: Team's current position
- **Team Name**: Full team name or abbreviation
- **Record**: Win-loss record (e.g., "12-3")
- **Conference**: For pro leagues (AFC, NFC, East, West)
- **Statistics**: Additional stats when available

## Supported Leagues

The plugin supports the following sports leagues:

- **nfl**: NFL (National Football League) - conferences and divisions
- **nba**: NBA (National Basketball Association) - conferences
- **mlb**: MLB (Major League Baseball) - leagues and divisions
- **nhl**: NHL (National Hockey League) - conferences
- **ncaa_fb**: NCAA Football - FBS/FCS divisions, rankings
- **ncaam_basketball**: NCAA Men's Basketball - rankings
- **ncaaw_basketball**: NCAA Women's Basketball - rankings

## Filtering Options

### NFL Filtering
- **conference**: `both`, `afc`, `nfc`
- **division**: `all`, `east`, `west`, `north`, `south`

### NBA Filtering
- **conference**: `both`, `east`, `west`

### MLB Filtering
- **league**: `both`, `american`, `national`
- **division**: `all`, `east`, `central`, `west`

### NCAA Filtering
- **division**: `fbs`, `fcs` (Football only)
- **show_rankings**: `true`, `false` (show rankings vs standings)

## Background Service

The plugin uses background data fetching for efficient API calls:

- Requests timeout after 30 seconds (configurable)
- Up to 3 retries for failed requests
- Priority level 2 (medium priority)
- Updates every hour by default (configurable)

## Data Sources

Standings and rankings data is fetched from ESPN's public API endpoints for all supported leagues.

## Dependencies

This plugin requires the main LEDMatrix installation and uses the cache manager for data storage.

## Installation

1. Copy this plugin directory to your `ledmatrix-plugins/plugins/` folder
2. Ensure the plugin is enabled in your LEDMatrix configuration
3. Configure your preferred leagues and display options
4. Restart LEDMatrix to load the new plugin

## Troubleshooting

- **No standings showing**: Check if leagues are enabled and API endpoints are accessible
- **Missing team information**: Ensure standings data is available for the selected leagues
- **Slow scrolling**: Adjust scroll speed and delay settings
- **API errors**: Check your internet connection and ESPN API availability

## Advanced Features

- **Dynamic Duration**: Automatically adjusts display time based on content width
- **Conference Filtering**: Filter standings by conference or division
- **NCAA Rankings**: Display college football and basketball rankings
- **Team Records**: Show detailed win-loss records and statistics
- **Continuous Loop**: Optionally loop the leaderboard continuously

## Performance Notes

- The plugin is designed to be lightweight and not impact display performance
- Background fetching ensures smooth scrolling without blocking
- Configurable update intervals balance freshness vs. API load
