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

### Appearance (`global.appearance`)

The leaderboard renders for a 1:1 LED matrix, where a partially-lit pixel is a
visibly dim LED rather than a smooth edge. These options control that:

- `pixel_perfect_text` (default `true`): draw text with anti-aliasing off, so
  every glyph pixel is fully on or fully off. Set to `false` for the older,
  softer look.
- `crisp_logos` (default `true`): give logos hard edges instead of a ring of
  half-lit pixels.
- `text_outline` (default `true`): black outline behind text so it stays
  readable where it sits near a logo.
- `logo_scale` (default `1.0`): logo height as a fraction of the panel height.
  `1.0` fits the panel exactly; anything above `1.0` crops the top and bottom of
  every logo.
- `font_size` (default `0` = pick a size for the panel height): sizes are
  snapped to the font's pixel grid — multiples of 8 for Press Start 2P — because
  off-grid sizes are what make pixel fonts look blurry.

### How many teams are shown

Each league's `top_teams` sets how far down the standings to go. **Set it to `0`
to show every team the league returns** (all 32 NFL teams, the full AP Top 25,
and so on).

A longer list needs proportionally more time on screen. The display controller
gives the plugin `min(plugin cap, core cap)` seconds and then moves on
mid-scroll, so a list longer than that budget simply stops partway through —
which looks like the leaderboard cutting off at an arbitrary team. The relevant
settings:

| Setting | Where | Default |
|---|---|---|
| `global.dynamic_duration.max_duration_seconds` | this plugin | 600 |
| `global.dynamic_duration.controller_cap_seconds` | this plugin | 600 |
| `display.dynamic_duration.max_duration_seconds` | LEDMatrix core config | 180 |

The **lowest** of the three wins, so the core's 180s default is usually the one
that decides it. All 32 NFL teams is roughly 3,200px of ticker: about 240s at
the default 15 px/s, or about 36s at 100 px/s.

If the content will not fit the budget, the plugin logs a warning at startup
naming which cap is limiting it and roughly how much of the list will not be
reached. Raise that cap, increase the scroll speed
(`global.display.scroll_speed` / `scroll_delay`), or lower `top_teams`.

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

The easiest way is the Plugin Store in the LEDMatrix web UI:

1. Open `http://your-pi-ip:5000`
2. Open the **Plugin Manager** tab
3. Find **Sports Leaderboard** in the **Plugin Store** section and click
   **Install**
4. Open the plugin's tab in the second nav row to configure leagues and
   display options

Manual install: copy this directory into your LEDMatrix
`plugins_directory` (default `plugin-repos/`) and restart the display
service.

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
