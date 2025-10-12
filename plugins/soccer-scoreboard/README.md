# Soccer Scoreboard Plugin

A plugin for LEDMatrix that displays live, recent, and upcoming soccer games across multiple leagues including Premier League, La Liga, Bundesliga, Serie A, Ligue 1, MLS, and more.

## Features

- **Multiple League Support**: Premier League, La Liga, Bundesliga, Serie A, Ligue 1, MLS, Champions League, Europa League, and more
- **Live Game Tracking**: Real-time scores, match time, and half information
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

#### Premier League Configuration

```json
{
  "leagues": {
    "eng.1": {
      "enabled": true,
      "favorite_teams": ["Manchester United", "Liverpool", "Arsenal"],
      "display_modes": {
        "live": true,
        "recent": true,
        "upcoming": true
      },
      "recent_games_to_show": 5,
      "upcoming_games_to_show": 10
    }
  }
}
```

#### La Liga Configuration

```json
{
  "leagues": {
    "esp.1": {
      "enabled": true,
      "favorite_teams": ["Real Madrid", "Barcelona", "Atletico Madrid"],
      "display_modes": {
        "live": true,
        "recent": true,
        "upcoming": true
      },
      "recent_games_to_show": 5,
      "upcoming_games_to_show": 10
    }
  }
}
```

#### Bundesliga Configuration

```json
{
  "leagues": {
    "ger.1": {
      "enabled": true,
      "favorite_teams": ["Bayern Munich", "Borussia Dortmund", "RB Leipzig"],
      "display_modes": {
        "live": true,
        "recent": true,
        "upcoming": true
      },
      "recent_games_to_show": 5,
      "upcoming_games_to_show": 10
    }
  }
}
```

#### Serie A Configuration

```json
{
  "leagues": {
    "ita.1": {
      "enabled": true,
      "favorite_teams": ["Juventus", "Inter Milan", "AC Milan"],
      "display_modes": {
        "live": true,
        "recent": true,
        "upcoming": true
      },
      "recent_games_to_show": 5,
      "upcoming_games_to_show": 10
    }
  }
}
```

#### Ligue 1 Configuration

```json
{
  "leagues": {
    "fra.1": {
      "enabled": true,
      "favorite_teams": ["PSG", "Marseille", "Lyon"],
      "display_modes": {
        "live": true,
        "recent": true,
        "upcoming": true
      },
      "recent_games_to_show": 5,
      "upcoming_games_to_show": 10
    }
  }
}
```

#### MLS Configuration

```json
{
  "leagues": {
    "usa.1": {
      "enabled": true,
      "favorite_teams": ["LA Galaxy", "Seattle Sounders", "Atlanta United"],
      "display_modes": {
        "live": true,
        "recent": true,
        "upcoming": true
      },
      "recent_games_to_show": 5,
      "upcoming_games_to_show": 10
    }
  }
}
```

## Display Modes

The plugin supports three display modes:

1. **soccer_live**: Shows currently active games
2. **soccer_recent**: Shows recently completed games
3. **soccer_upcoming**: Shows scheduled upcoming games

## Supported Leagues

The plugin supports the following soccer leagues:

- **eng.1**: Premier League (England)
- **esp.1**: La Liga (Spain)
- **ger.1**: Bundesliga (Germany)
- **ita.1**: Serie A (Italy)
- **fra.1**: Ligue 1 (France)
- **usa.1**: MLS (USA)
- **uefa.champions**: UEFA Champions League
- **uefa.europa**: UEFA Europa League

## Team Names

You can use either full team names or common abbreviations:

- Manchester United, Man United, Man Utd
- Liverpool, LFC
- Arsenal, AFC
- Real Madrid, RM
- Barcelona, Barca, FCB
- Bayern Munich, Bayern, FCB
- Borussia Dortmund, BVB
- Juventus, Juve
- Inter Milan, Inter
- AC Milan, Milan
- PSG, Paris Saint-Germain
- Marseille, OM
- Lyon, OL
- LA Galaxy, LA
- Seattle Sounders, Seattle
- Atlanta United, ATL UTD

## Background Service

The plugin uses background data fetching for efficient API calls:

- Requests timeout after 30 seconds (configurable)
- Up to 3 retries for failed requests
- Priority level 2 (medium priority)

## Data Source

Game data is fetched from ESPN's public API endpoints for all supported soccer leagues.

## Dependencies

This plugin requires the main LEDMatrix installation and uses the plugin system base classes.

## Installation

1. Copy this plugin directory to your `ledmatrix-plugins/plugins/` folder
2. Ensure the plugin is enabled in your LEDMatrix configuration
3. Configure your favorite teams and display preferences
4. Restart LEDMatrix to load the new plugin

## Troubleshooting

- **No games showing**: Check if leagues are enabled and API endpoints are accessible
- **Missing team logos**: Ensure team logo files exist in your assets/sports/soccer_logos/ directory
- **Slow updates**: Adjust the update interval in league configuration
- **API errors**: Check your internet connection and ESPN API availability

## Advanced Configuration

For more advanced users, you can add additional leagues by modifying the `ESPN_API_URLS` dictionary in the plugin code and updating the configuration schema accordingly.
