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

## Traditional Scoreboard Screen

A dedicated full-screen view styled after a real outfield ballpark
scoreboard: an inning-by-inning line score with R/H/E, the current
inning highlighted, small team logos and team-colored abbreviations
when there's room, and (for live at-bats) a compact column of lit
ball/strike/out indicators. Available for **MLB and NCAA Baseball
only** (MiLB's data doesn't come from ESPN's API in the same shape, so
it isn't wired up for that league).

### How it works

This isn't a separate display mode you select — it periodically
*rotates into* whichever game the normal live/recent rotation is
already showing, replacing the usual compact scorebug for a few
seconds at a time, then reverting. Nothing needs to be "currently
selected" for it to appear; as long as the toggle is on, it takes over
automatically on its own timer while a live or final game is on screen.

The layout adapts to your display size automatically:
- The font auto-fits as large as your panel allows (see `font_size`).
- The ball/strike/out column only appears if there's enough width to
  fit it without shrinking the number of innings shown; on very narrow
  displays it's dropped entirely rather than clipped or forced in.
- Team logos only appear if there's leftover width to spare after
  everything else — they never cost a displayed inning or push out the
  ball/strike/out column.

### Enabling it

Turn it on per league under that league's `display_options`:

```json
{
  "mlb": {
    "display_options": {
      "show_traditional_scoreboard": true
    }
  }
}
```

The same flag exists under `ncaa_baseball.display_options`. It's off
by default.

### Toggles and customization

All of the following live under `customization.traditional_scoreboard`
in the config (this block is shared across leagues that support the
screen):

| Option | Default | What it does |
|---|---|---|
| `game_scope` | `"both"` | Which games this screen rotates in for. `"live"` — only during live action. `"recent"` — only for final/completed games (handy for glancing at the final line score and picking out the winner without watching the whole game). `"both"` — either. |
| `favorites_only` | `false` | When `true`, only rotates in for games involving one of this league's `favorite_teams`. This is independent of `show_all_live`/`show_favorite_teams_only` (which control the *normal* rotation) — so you can watch every team's live games in the compact scorebug, but reserve the full-screen ballpark treatment for your own team. Has no effect if `favorite_teams` is empty. |
| `dwell_seconds` | `6` | How many seconds this screen stays on screen each time it rotates in. |
| `interval_seconds` | `30` | How often (in seconds) it rotates in. |
| `font` | `"9x15.bdf"` | Font for all text on this screen. The default is a clean, bold bitmap font sized to fit the display; a fixed-size `.bdf` font always renders at its own native pixel size (with an automatic fallback to a smaller sibling font if your display is too small to fit it) rather than scaling to `font_size`. Use a scalable `.ttf` font (e.g. `"press_start"` for a chunkier 8-bit retro look) if you want `font_size` to directly control the size. |
| `font_size` | `24` | Maximum font size cap, for scalable `.ttf` fonts only (ignored by fixed-size `.bdf` fonts like the default). The screen auto-fits the largest text that still leaves room for the ball/strike/out column, so the default effectively means "as big as the display allows" — lower it to force a smaller, more consistent size. |
| `use_team_colors` | `true` | Color each team's abbreviation with their real ESPN team colors (brightness-adjusted for legibility on black) instead of a flat `text_color`. |
| `show_logos` | `true` | Show a small team logo beside each abbreviation when there's spare width (see "How it works" above). |
| `show_dividers` | `true` | Draw thin 1px grid lines between innings, rows, and the R/H/E columns for readability. |
| `text_color` | `[255, 255, 255]` | `[R, G, B]` for score digits, and team abbreviations when `use_team_colors` is off or a team's color is unavailable. |
| `header_color` | `[180, 180, 180]` | `[R, G, B]` for the inning-number and R/H/E header row. |
| `highlight_color` | `[255, 140, 0]` | `[R, G, B]` accent color for the current-inning highlight, the batting-team ▲/▼ indicator, and lit ball/strike/out indicators. |
| `divider_color` | `[90, 90, 90]` | `[R, G, B]` for the grid divider lines. |

Example — only show this screen for your favorite team, and only once
the game is final (a simple "check the final score" use case):

```json
{
  "mlb": {
    "display_options": {
      "show_traditional_scoreboard": true
    }
  },
  "customization": {
    "traditional_scoreboard": {
      "game_scope": "recent",
      "favorites_only": true
    }
  }
}
```

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
