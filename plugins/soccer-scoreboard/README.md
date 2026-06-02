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

# Soccer Scoreboard Plugin

A plugin for LEDMatrix that displays live, recent, and upcoming soccer games across multiple leagues including Premier League, La Liga, Bundesliga, Serie A, Ligue 1, MLS, and FIFA World Cup.

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
      "favorite_teams": ["MUN", "LIV", "ARS"],
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
      "favorite_teams": ["RM", "BAR", "ATM"],
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
      "favorite_teams": ["BAY", "BVB", "RBL"],
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
      "favorite_teams": ["JUV", "INT", "MIL"],
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
      "favorite_teams": ["PSG", "OM", "OL"],
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
      "favorite_teams": ["LA", "SEA", "ATL"],
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
- **por.1**: Liga Portugal (Portugal)
- **uefa.champions**: UEFA Champions League
- **uefa.europa**: UEFA Europa League
- **fifa.world**: FIFA World Cup

Additional leagues can be added via the **Custom Leagues** setting using any ESPN soccer league code (e.g. `mex.1`, `arg.1`, `bra.1`, `ned.1`).

## FIFA World Cup

Enable the **FIFA World Cup** league from the plugin settings to track World Cup 2026 (June 11 – July 19, USA/Canada/Mexico).

**To follow all games:** Enable `fifa.world` and leave `Show Favorite Teams Only` off.

**To follow just your country:** Enable `fifa.world`, set `Favorite Teams` to your country's ESPN abbreviation (e.g. `USA`, `ENG`, `BRA`), and enable `Show Favorite Teams Only`.

During knockout rounds, the status area shows:
- **ET1** / **ET2** — Extra Time first / second half
- **ETH** — Halftime of Extra Time
- **PEN** — Penalty Shootout in progress
- **F/ET** — Final, decided in Extra Time
- **F/Pen** — Final, decided on Penalties

## Team Names & Abbreviations

The `favorite_teams` config field requires the **ESPN API abbreviation** for each team (e.g. `"LIV"`, `"MCI"`). Full team names are not supported.

See **[TEAMS.md](TEAMS.md)** for a complete list of abbreviations for all supported leagues.

Example:
```json
"favorite_teams": ["LIV", "MCI", "ARS"]
```

> **Tip:** If you're unsure of an abbreviation, enable debug logging — the plugin logs `home_abbr` and `away_abbr` for every game it processes.

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

The easiest way is the Plugin Store in the LEDMatrix web UI:

1. Open `http://your-pi-ip:5000`
2. Open the **Plugin Manager** tab
3. Find **Soccer Scoreboard** in the **Plugin Store** section and click
   **Install**
4. Open the plugin's tab in the second nav row to configure leagues and
   favorite teams

Manual install: copy this directory into your LEDMatrix
`plugins_directory` (default `plugin-repos/`) and restart the display
service.

## Troubleshooting

- **No games showing**: Check if leagues are enabled and API endpoints are accessible
- **Missing team logos**: Ensure team logo files exist in your assets/sports/soccer_logos/ directory
- **Slow updates**: Adjust the update interval in league configuration
- **API errors**: Check your internet connection and ESPN API availability

## Advanced Configuration

For more advanced users, you can add additional leagues by modifying the `ESPN_API_URLS` dictionary in the plugin code and updating the configuration schema accordingly.
