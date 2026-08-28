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
- **Favorite Team Result Colors**: Optionally show a finished game's score in green when your favorite team won and red when it lost

## Configuration

### Global Settings

- `display_duration`: How long the plugin mode is shown before rotating to next plugin (5-300 seconds, default: 30)
- `update_interval`: How often to fetch new data in seconds (30-86400, default: 3600)
- `game_display_duration`: Duration to show each individual game before rotating to next game (3-60 seconds, default: 15)
- `background_service`: Configure API request settings (timeout, retries, priority)
- `timezone` (Advanced): IANA name used to display event start times, e.g.
  `America/Chicago`. Leave blank (the default) to follow the LEDMatrix global
  timezone; if that isn't set, the host system's timezone is used, and only if
  neither is available do times fall back to UTC.

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
- `live_game_duration`: Duration in seconds to display each live game (10-120, default: 20). With a non-favorite duration set, this applies to games with a favorite team.
- `non_favorite_live_game_duration`: Duration in seconds for live games with **no** favorite team (0-120, default: 0 = off). Only applies when favorite teams are set and non-favorite live games are shown (`show_favorite_teams_only` off, or `show_all_live` on). See [Shorter dwell for non-favorite live games](#shorter-dwell-for-non-favorite-live-games).
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
- `favorite_live_boost` (default: 2, range 1-5): With both filters above off (or `show_all_live` on), all live games rotate evenly by default. This setting gives your favorite's live game extra turns in that rotation — it's always queued first whenever the live list refreshes, and gets `favorite_live_boost` turns for every 1 turn other live games get. Set to `1` for perfectly even rotation (no boost). Has no effect if you don't have `favorite_teams` configured, or if your favorite isn't currently live.

**Note**: For live mode, if `show_all_live` is true, all live games will be shown. If false and `show_favorite_teams_only` is true, only live games involving favorite teams will be shown. If both are off, all live games are shown and rotate evenly, with `favorite_live_boost` giving your favorite's game precedence whenever it's playing.

### Shorter dwell for non-favorite live games

`non_favorite_live_game_duration` (0-120, default 0 = off) gives live games that
involve **none** of your favorite teams a shorter on-screen turn than your
favorites. For example `live_game_duration: 30` with
`non_favorite_live_game_duration: 5` shows your teams for 30s each while everyone
else's games flash by in 5s.

This **only takes effect** when favorite teams are configured **and**
non-favorite live games are being shown — `show_favorite_teams_only` off, or
`show_all_live` on (otherwise non-favorite games are never on screen to
shorten). Leave it at `0` to display every live game for `live_game_duration`.

| Favorite teams set? | Non-favorite games shown? | Live game has a favorite? | Duration used |
|---|---|---|---|
| No | — | — | `live_game_duration` (unchanged) |
| Yes | No (`show_favorite_teams_only` on, `show_all_live` off) | favorite | `live_game_duration` |
| Yes | Yes (`show_favorite_teams_only` off, or `show_all_live` on) | favorite | `live_game_duration` |
| Yes | Yes (`show_favorite_teams_only` off, or `show_all_live` on) | none | `non_favorite_live_game_duration` (when > 0) |

## Excluding Teams (Spoiler Protection)

`exclude_teams` (per league, same format as `favorite_teams`, e.g. `["LAL"]`) hides specific teams from both the live rotation and Recent/Final scores — handy if you're planning to watch a game delayed and don't want the result spoiled. Exclusion always wins: if a team appears in both `favorite_teams` and `exclude_teams`, it's excluded. Upcoming/schedule listings are unaffected since they carry no result to spoil.

```json
{
  "nba": {
    "exclude_teams": ["LAL"],
    "filtering": {
      "favorite_live_boost": 3
    }
  }
}
```

## Favorite Team Result Colors

A run of games against the same opponent is hard to read at a glance: in scroll
and Vegas mode the same two logos go past several times and only the digits
change. Turn on **Customization -> Favorite Team Result Colors** to color a
finished game's score by how your favorite team did - green for a win, red for
a loss.

```json
{
  "customization": {
    "favorite_result_colors": {
      "enabled": true,
      "win_color": [0, 255, 0],
      "loss_color": [255, 0, 0],
      "tie_color": [255, 200, 0]
    }
  }
}
```

- Off by default. Until you enable it the score keeps exactly the color it has
  today.
- Only finished games are colored. Live and upcoming cards are untouched.
- A game needs exactly one favorite team. If neither side is a favorite, or both
  are, the score keeps its normal color.
- Applies to both the one-game-at-a-time switch view and the scroll/Vegas
  ticker.
- The three colors are Advanced settings; leave them alone for the defaults
  above.

## Troubleshooting

- **Start times look like UTC** (a 6:45pm Central start showing as 11:45PM):
  the plugin couldn't read your global timezone. Set `timezone` under the
  plugin's Advanced Settings to your IANA zone, e.g. `America/Chicago`.
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

## Vegas ticker: seeing live games more often

By default a live game **takes over** the display: the Vegas ticker stops and
this scoreboard shows full screen until the game ends. If you would rather keep
the marquee scrolling and still see scores, set this in the core config:

```json
{
  "display": {
    "vegas_scroll": {
      "live_in_ticker": true,
      "live_weight": 3,
      "favorite_live_weight": 5
    }
  }
}
```

The ticker is otherwise a strict round robin — every plugin appears once per
cycle — so with a dozen plugins enabled a score comes round once a lap. These
weights let this plugin claim several slots per cycle, spaced evenly through
it rather than bunched together.

`live_weight` applies whenever this scoreboard has a live game.
`favorite_live_weight` applies when one of your `favorite_teams` is playing, so
your team's game comes round more often than other live games. That distinction
has to be made here rather than in the core, which can tell *that* a game is
live but not *whose*.

Two things to keep in mind:

- The weight is per **plugin**, not per game. With four games live this
  scoreboard still occupies one slot at a time and picks between its own games
  using `favorite_live_boost`; these weights control how often the scoreboard
  itself comes round.
- More slots make the cycle **longer**, not faster — everything else appears
  proportionally less often. And appearing more often only helps if the data is
  fresh, which is governed by this plugin's own live update interval.

## 🎯 Which Games Get Shown

**`upcoming_games_to_show` is not "how many cards you see".** It is the size of a *pool*. The panel cycles through that pool one card at a time and keeps its place between visits, so a pool of 3 means the board rotates through the same 3 games until the schedule moves on. Making the number bigger gives you a *longer lap*, so any one game comes round **less** often.

Which mode you are in depends on whether `favorite_teams` is set and whether `show_favorite_teams_only` is on:

| `favorite_teams` | `show_favorite_teams_only` | What you get |
|---|---|---|
| empty | either | The next N games league-wide, chronologically. Every game shown is a non-favorite game, so the two filters below apply to all of them. |
| set | **on** | Only your teams. The limit is a budget **per team**. |
| set | **off** | **Your teams first, then other games to fill.** Both limits are **totals**. |

The third row is what most people want, and it did not exist before: with the flag off, favorites used to be ignored *entirely*.

### The settings

| Option | Default | Description |
|---|---|---|
| `upcoming_games_to_show` | varies | How many **favorite** upcoming games to show. |
| `recent_games_to_show` | varies | The same, for finished games. |
| `other_upcoming_games_to_show` | matches `upcoming_games_to_show` | How many **non-favorite** upcoming games to add. `0` gives you favorites only. |
| `other_recent_games_to_show` | matches `recent_games_to_show` | The same, for finished games. |
| `other_rotation_interval_seconds` | `1800` | How often the non-favorite slice advances. `0` pins it. |
| `other_games_min_quality` | `ranked` | Which non-favorite games qualify: `ranked`, `broadcast`, or `any`. |
| `other_games_divisions` | `["fbs"]` | Which divisions non-favorite games may come from. College football only — see the note below. |

**Your favorite teams are never filtered by the last two** — follow a smaller-division team and its games always appear. Those settings only decide what fills the *remaining* slots.

### Variety comes from turnover

Rather than widening the pool, the non-favorite slice **moves**: the window advances by its own width every `other_rotation_interval_seconds`, so consecutive windows do not overlap and the board works through the schedule instead of resampling the front of it. Your favorites are not rotated — for upcoming games the soonest ones are the point.

Both filters **fail open**: if the data behind them cannot be fetched, the game is allowed through. A board showing filler is a poor board; a board showing nothing is a broken one.

> `other_games_min_quality` needs a national poll, which only the college leagues publish — set to `ranked` in a professional league it lets every game through, and no poll is requested. `other_games_divisions` needs ESPN's FBS/FCS group rosters, which exist for **college football and nothing else**: asked for any other college league they come back empty or 500, so the setting is inert here and no lookup is made.

