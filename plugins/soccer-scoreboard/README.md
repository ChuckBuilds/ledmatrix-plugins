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
- **Favorite Team Result Colors**: Optionally show a finished game's score in green when your favorite team won and red when it lost

## Configuration

### Global Settings

- `display_duration`: How long to show each game (5-60 seconds, default: 15)
- `show_records`: Display team win-loss records (default: false)
- `show_ranking`: Display team rankings when available (default: false)
- `background_service`: Configure API request settings
- `timezone` (Advanced): IANA name used to display event start times, e.g.
  `America/Chicago`. Leave blank (the default) to follow the LEDMatrix global
  timezone; if that isn't set, the host system's timezone is used, and only if
  neither is available do times fall back to UTC.

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

### Adding another league

Any other league ESPN covers can be added under **Add More Leagues** in the plugin
settings. Click **Add Item**, then fill in **both** a display name and the ESPN
league code — a row with a blank name will not save.

Common codes:

| Code | League |
| --- | --- |
| `eng.2` | English Championship |
| `eng.3` | English League One |
| `eng.fa` | FA Cup |
| `eng.league_cup` | EFL (Carabao) Cup |
| `mex.1` | Liga MX |
| `arg.1` | Argentine Primera División |
| `bra.1` | Brasileirão Série A |
| `ned.1` | Eredivisie |
| `sco.1` | Scottish Premiership |
| `tur.1` | Turkish Süper Lig |
| `bel.1` | Belgian Pro League |
| `conmebol.libertadores` | Copa Libertadores |

Codes are lowercase and dot-separated, exactly as they appear in ESPN's own URLs
(`espn.com/soccer/scoreboard/_/league/eng.2`). Per-league favorites, durations,
and display modes live behind the ⚙ button on the league's row.

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

## Filtering & Live Priority

Each league (and each custom league) has its own `filtering` block plus a couple of sibling settings:

| Setting | Default | Effect |
|---|---|---|
| `filtering.show_favorite_teams_only` | `true` | Only show games involving `favorite_teams`. |
| `filtering.show_all_live` | `false` | Overrides the above — show every live game, favorites or not. |
| `favorite_teams` | `[]` | Teams to prioritize (see above for abbreviation format). |
| `exclude_teams` | `[]` | Teams to always hide, from **both** the live rotation and Recent/Final scores — useful for spoiler protection if you're planning to watch a game delayed. Takes precedence over every other setting: an excluded team's games never show, even if `show_all_live` is on or the team is also listed in `favorite_teams`. |
| `filtering.favorite_live_boost` | `2` | How many turns your favorite's live game gets in the live rotation for every 1 turn other live games get. Your favorite's game is also always queued first the moment it goes live. Set to `1` for perfectly even rotation (no boost). Has no effect unless `favorite_teams` is configured and more than one game is live. |
| `non_favorite_live_game_duration` | `0` (off) | Seconds to show live games with **no** favorite team, so they flash by faster than your favorites (which keep `live_game_duration`). Only applies when `favorite_teams` is set **and** non-favorite live games are shown (`show_favorite_teams_only` off, or `show_all_live` on). `0` = every live game uses `live_game_duration` (no change). See below. |
| `live_priority` | varies | Lets this league's live games interrupt the recent/upcoming mode rotation (unrelated to which *specific* live game is shown — that's what `favorite_live_boost` controls). |

Example:
```json
{
  "leagues": {
    "eng.1": {
      "favorite_teams": ["LIV"],
      "exclude_teams": ["MUN"],
      "filtering": {
        "show_favorite_teams_only": false,
        "show_all_live": false,
        "favorite_live_boost": 3
      }
    }
  }
}
```
With both `show_favorite_teams_only` and `show_all_live` off, all live games rotate evenly — except Liverpool's game shows 3× as often (and jumps to the front the instant it goes live) whenever they're playing, and Man United's games never appear in live or recent/final scores at all.

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
- **No games showing**: Check if leagues are enabled and API endpoints are accessible
- **Missing team logos**: Ensure team logo files exist in your assets/sports/soccer_logos/ directory
- **Slow updates**: Adjust the update interval in league configuration
- **API errors**: Check your internet connection and ESPN API availability

## Advanced Configuration

For more advanced users, you can add additional leagues by modifying the `ESPN_API_URLS` dictionary in the plugin code and updating the configuration schema accordingly.

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

## Matchup separator and the upcoming card middle

The **Matchup Card Layout** section (advanced) controls what sits between the
two team logos before a game starts, and how the date and time are written.
These settings now apply to every display mode -- the scroll ticker, the Vegas
ticker, and the full-screen scoreboard -- rather than only the tickers.

| Setting | Key | Default | What it does |
|---|---|---|---|
| Matchup Separator | `vs_text` | `VS` | Text drawn between the teams: `VS`, `@`, `at`, `v`. The away team is always on the left, so `@` and `at` read as "away at home". Blank draws nothing. |
| Middle of an Upcoming Card | `upcoming_center` | `vs` | Scroll and Vegas cards: the separator, the date and time stacked, or nothing. |
| Middle of a Full-Screen Upcoming Scoreboard | `switch_upcoming_center` | `date_time` | The same choice for the full-screen scoreboard, plus `inherit` to follow the setting above. It defaults to the stacked date and time, which is what this display has always shown, so nothing changes until you pick something else. |
| Date Format | `date_format` | `abbrev` | How the scroll and Vegas cards write the date: `Sep 19`, `9/19`, `19 Sep`, `19/9`, or `Fri Sep 19`. |
| Full-Screen Date Format | `switch_date_format` | `numeric` | The same choice for the full-screen scoreboard, plus `inherit` to follow the row above. It has its own default because the two displays disagree about what is normal: the cards have always written `Sep 19` and the full-screen scoreboard `9/19`, so a single shared default would restyle one of them. |
| Time Format | `time_format` | `12h` | 12- or 24-hour clock. |
| Show Date / Show Time | `show_date`, `show_time` | `true` | Drop either line. |
| Swap Date and Time | `swap_date_time` | `false` | Swap the two lines over. Each display starts from its own order, so this flips them rather than forcing one: the scroll and Vegas cards put the time on top, the full-screen date/time stack puts the date on top. |

Choosing the separator for the full-screen scoreboard moves the date and time
out of the middle and onto the top and bottom rows, the same way the scroll
card lays them out; the "Next Game" header gives up the top row to them.

The center-gap settings in the same section size the scroll and Vegas card's
middle strip only -- the full-screen scoreboard pins its logos to the panel
edges and is unaffected.

Example:

```json
{
  "scroll_card": {
    "vs_text": "@",
    "switch_upcoming_center": "vs",
    "date_format": "weekday"
  }
}
```

### Text Colours

Each text element in the **Customization** section carries a colour, and it now
applies to the text drawn in that element's face — on the full-screen scoreboard
and on the scroll and Vegas cards alike. Until this version the picker changed
only which font was loaded; every string was drawn white.

| Element | Key | Colours |
|---|---|---|
| Score | `score_text` | The score, and the matchup separator on an upcoming card |
| Period / clock | `period_text` | The clock, period, and the date and time on an upcoming scoreboard |
| Team name | `team_name` | Team names and abbreviations |
| Status | `status_text` | Status lines such as "Next Game" |
| Detail | `detail_text` | Small detail lines |
| Ranking | `rank_text` | Team rankings drawn in the ranking face |

Colours are `[r, g, b]` or `"#RRGGBB"`, and every default is white, so a display
nobody has recoloured looks exactly as it did.

```json
{
  "customization": {
    "score_text": { "text_color": [255, 200, 0] },
    "status_text": { "text_color": "#00A0FF" }
  }
}
```

Two things keep their own colours on purpose: the betting-odds figures, which
are coloured by which side is favoured, and a finished game's score when
**Favorite Team Result Colors** is on — that tint wins, and your score colour
shows on every other game. Records and rankings drawn in the small fixed face
stay white; no element in the schema owns that face.
