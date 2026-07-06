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

# Baseball Scoreboard Plugin

A plugin for LEDMatrix that displays live, recent, and upcoming baseball games across MLB, MiLB, and NCAA Baseball leagues.

## Features

- **Multiple League Support**: MLB, MiLB (Minor League Baseball), NCAA Baseball
- **Live Game Tracking**: Real-time scores, innings, time remaining
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

#### MLB Configuration

```json
{
  "mlb": {
    "enabled": true,
    "favorite_teams": ["NYY", "BOS", "LAD"],
    "display_modes": {
      "show_live": true,
      "show_recent": true,
      "show_upcoming": true
    },
    "recent_games_to_show": 5,
    "upcoming_games_to_show": 10
  }
}
```

#### MiLB Configuration

```json
{
  "milb": {
    "enabled": true,
    "favorite_teams": ["DUR", "SWB", "MEM"],
    "display_modes": {
      "show_live": true,
      "show_recent": true,
      "show_upcoming": true
    },
    "recent_games_to_show": 5,
    "upcoming_games_to_show": 10
  }
}
```

#### NCAA Baseball Configuration

```json
{
  "ncaa_baseball": {
    "enabled": true,
    "favorite_teams": ["LSU", "FLA", "VANDY"],
    "display_modes": {
      "show_live": true,
      "show_recent": true,
      "show_upcoming": true
    },
    "recent_games_to_show": 5,
    "upcoming_games_to_show": 10
  }
}
```

### Filtering & Live Priority

Each league's `filtering` block controls which live games are shown, and
`favorite_teams` / `exclude_teams` control which teams are eligible:

```json
{
  "mlb": {
    "favorite_teams": ["SF"],
    "exclude_teams": [],
    "filtering": {
      "show_favorite_teams_only": false,
      "show_all_live": false,
      "favorite_live_boost": 2
    }
  }
}
```

- `favorite_teams`: teams you follow. When a favorite is live, it's always
  queued first as soon as the live rotation refreshes.
- `exclude_teams`: teams to always hide from the live rotation **and**
  recent/final scores (e.g. to avoid spoilers if you're watching delayed).
  This always wins — even over `show_all_live` or a team also listed in
  `favorite_teams`.
- `show_favorite_teams_only`: only show live games involving a favorite team.
- `show_all_live`: show every live game regardless of favorites.
- With both `show_favorite_teams_only` and `show_all_live` off, every live
  game is shown and rotated evenly — this is the same set as `show_all_live`,
  the difference is in *how* they rotate (see `favorite_live_boost` below).
- `favorite_live_boost` (1-5, default 2): how many turns your favorite's live
  game gets in the rotation for every 1 turn other live games get. Set to `1`
  for perfectly even rotation. Only matters when more than one live game is
  eligible to show (i.e. not when `show_favorite_teams_only` is on with a
  single favorite).

## Display Modes

The plugin registers per-league granular modes in `manifest.json`. The
display controller rotates through any that are enabled:

**MLB:** `mlb_live`, `mlb_recent`, `mlb_upcoming`
**MiLB:** `milb_live`, `milb_recent`, `milb_upcoming`
**NCAA Baseball:** `ncaa_baseball_live`, `ncaa_baseball_recent`, `ncaa_baseball_upcoming`

Toggle individual modes per league with the `show_live` / `show_recent`
/ `show_upcoming` flags inside each league's `display_modes` block.

## Team Abbreviations

### MLB Teams
Common abbreviations: NYY (Yankees), BOS (Red Sox), LAD (Dodgers), HOU (Astros), ATL (Braves), PHI (Phillies), TOR (Blue Jays), TB (Rays), MIL (Brewers), CHC (Cubs), CIN (Reds), PIT (Pirates), STL (Cardinals), MIN (Twins), CLE (Guardians), CHW (White Sox), DET (Tigers), KC (Royals), LAA (Angels), OAK (Athletics), SEA (Mariners), TEX (Rangers), ARI (Diamondbacks), COL (Rockies), SD (Padres), SF (Giants), BAL (Orioles), MIA (Marlins), NYM (Mets), WAS (Nationals)

### MiLB Teams
Common abbreviations vary by league and level (AAA, AA, A+, A, etc.). Examples: DUR (Durham Bulls), SWB (Scranton/Wilkes-Barre RailRiders), MEM (Memphis Redbirds), etc.

### NCAA Baseball Teams
Common abbreviations: LSU (LSU), FLA (Florida), VANDY (Vanderbilt), ARK (Arkansas), MISS (Ole Miss), TAMU (Texas A&M), TENN (Tennessee), UK (Kentucky), UGA (Georgia), BAMA (Alabama), AUB (Auburn), SCAR (South Carolina), CLEM (Clemson), FSU (Florida State), MIA (Miami), UNC (North Carolina), DUKE, WAKE (Wake Forest), VT (Virginia Tech), LOU (Louisville)

## Background Service

The plugin uses background data fetching for efficient API calls:

- Requests timeout after 30 seconds (configurable)
- Up to 3 retries for failed requests
- Priority level 2 (medium priority)

## Data Source

Game data is fetched from ESPN's public API endpoints for all supported baseball leagues.

## Dependencies

This plugin requires the main LEDMatrix installation and inherits functionality from the Baseball base classes.

## Installation

The easiest way is the Plugin Store in the LEDMatrix web UI:

1. Open `http://your-pi-ip:5000`
2. Open the **Plugin Manager** tab
3. Find **Baseball Scoreboard** in the **Plugin Store** section and click
   **Install**
4. Open the plugin's tab in the second nav row to configure favorite
   teams and per-league preferences

Manual install: copy this directory into your LEDMatrix
`plugins_directory` (default `plugin-repos/`) and restart the display
service.

## Troubleshooting

- **No games showing**: Check if leagues are enabled and API endpoints are accessible
- **Missing team logos**: Ensure team logo files exist in your assets/sports/ directory
- **Slow updates**: Adjust the update interval in league configuration
- **API errors**: Check your internet connection and ESPN API availability
