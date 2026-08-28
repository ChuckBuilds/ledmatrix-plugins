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
- **Favorite Team Result Colors**: Optionally show a finished game's score in green when your favorite team won and red when it lost

## Configuration

### Global Settings

- `display_duration`: How long to show each game (5-60 seconds, default: 15)
- `show_records`: Display team win-loss records (default: false)
- `show_ranking`: Display team rankings when available (default: false)
- `background_service`: Configure API request settings
- `timezone` (Advanced): IANA name used to display game start times, e.g.
  `America/Chicago`. Leave blank (the default) to follow the LEDMatrix global
  timezone; if that isn't set, the host system's timezone is used, and only if
  neither is available do times fall back to UTC.

  **Leftover `"UTC"` from an older version?** Before the write-back fix this
  plugin could persist `"timezone": "UTC"` into your saved config, where it
  then shadowed your real global timezone. That stale value is now detected
  and ignored automatically whenever your global or system timezone disagrees
  — no manual edit needed. If you genuinely want UTC here, set `Etc/UTC`,
  which is always honored.


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

#### Shorter dwell for non-favorite live games

`non_favorite_live_game_duration` (0-120, default 0 = off) gives live games that
involve **none** of your favorite teams a shorter on-screen turn than your
favorites. For example `live_game_duration: 30` with
`non_favorite_live_game_duration: 5` shows your teams for 30s each while everyone
else's games flash by in 5s. It sits next to `live_game_duration` in each league
block.

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
| `show_team_color_backgrounds` | `true` | Tint each team's row with a subtle (~12% brightness) wash of their real ESPN color, plus a solid team-color accent strip on the left edge — a colorful ballpark look. Requires `use_team_colors`; a team with no ESPN color simply gets no tint. Text stays legible because it's drawn with a black outline over the wash. |
| `show_logos` | `true` | Show a small team logo beside each abbreviation when there's spare width (see "How it works" above). |
| `show_dividers` | `true` | Draw thin 1px grid lines between innings, rows, and the R/H/E columns for readability. |
| `highlight_winner` | `true` | On a final game, color the winning team's run total in `winner_color` so the winner is obvious at a glance instead of having to compare both R values yourself. Pairs naturally with `game_scope: "recent"`. No effect on live games. |
| `text_color` | `[255, 255, 255]` | `[R, G, B]` for score digits, and team abbreviations when `use_team_colors` is off or a team's color is unavailable. |
| `header_color` | `[180, 180, 180]` | `[R, G, B]` for the inning-number and R/H/E header row. |
| `highlight_color` | `[255, 140, 0]` | `[R, G, B]` accent color for the current-inning highlight, the batting-team ▲/▼ indicator, and lit ball/strike/out indicators. |
| `divider_color` | `[90, 90, 90]` | `[R, G, B]` for the grid divider lines. |
| `winner_color` | `[0, 200, 0]` | `[R, G, B]` for the winning team's run total on a final game (see `highlight_winner`). |

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

## Pitcher / Batter / Last Play Screen

A dedicated full-screen view showing the current at-bat's pitcher,
batter, and a short code for the most recently completed play (`1B`,
`HR`, `K`, `BB`, etc.), replacing the normal scorebug for a few
seconds at a time. The pitcher and batter lines are labeled in full —
`Pitcher: G. Cole` / `Batter: J. Soto` — so there's no ambiguity with
the grid's `B` (Balls) indicator. Available for **MLB and NCAA Baseball only**, and
**live games only** — this data only exists during an actual live
at-bat, so unlike the Traditional Scoreboard there's no `game_scope`
option (nothing analogous exists for a final or upcoming game).

Text is centered both horizontally and vertically, and auto-fits the
largest font that still fits every line's actual text — a long name
falls back to a smaller font (and, as a last resort, gets truncated)
before it would otherwise run off the edge.

### Enabling it

Turn on the parts you want per league under that league's
`display_options`:

```json
{
  "mlb": {
    "display_options": {
      "show_pitcher_batter": true,
      "show_last_play": true
    }
  }
}
```

Both flags exist under `ncaa_baseball.display_options` too, and both
default to off. You can enable just one (e.g. only `show_last_play`
for a compact "what just happened" ticker).

### Toggles and customization

All of the following live under `customization.at_bat_info`:

| Option | Default | What it does |
|---|---|---|
| `favorites_only` | `false` | Only rotates in for games involving one of this league's `favorite_teams` — independent of `show_all_live`/`show_favorite_teams_only`, which control the *normal* rotation. Has no effect if `favorite_teams` is empty. |
| `dwell_seconds` | `4` | How many seconds this screen stays on screen each time it rotates in. |
| `interval_seconds` | `25` | How often (in seconds) it rotates in. |
| `font` | `"9x15.bdf"` | Font for all text on this screen. The default auto-fits as large as the display and each line's actual text allow, falling back to a smaller same-family font rather than overflowing. Use a scalable `.ttf` font (e.g. `"press_start"`) if you want `font_size` to directly control the size. |
| `font_size` | `24` | Maximum font size cap, for scalable `.ttf` fonts only (ignored by fixed-size `.bdf` fonts like the default). Lower it to force a smaller, more consistent size. |
| `use_team_colors` | `true` | Color the pitcher's name with the fielding team's real ESPN color and the batter's name with the batting team's color, instead of the flat colors below. |
| `pitcher_color` | `[255, 255, 255]` | `[R, G, B]` for the pitcher line when `use_team_colors` is off or unavailable. |
| `batter_color` | `[255, 255, 0]` | `[R, G, B]` for the batter line when `use_team_colors` is off or unavailable. |
| `last_play_color` | `[0, 255, 255]` | `[R, G, B]` for the last-play code line (always this flat color — there's no "team" a play code belongs to). |

## Player Card Screen

A dedicated full-screen "baseball card" that rotates in for the current
batter (and optionally the pitcher): a **headshot image**, **jersey
number**, **position**, **bat/throw hand**, and **season stats** —
`AVG` / `HR` / `RBI` for hitters, `ERA` / `W-L` / `K` for pitchers.
The headshot and bio are fetched from ESPN's athlete API and cached
(in memory and on disk under `assets/headshots/`, which is gitignored).
Available for **MLB and NCAA Baseball only** and **live games only**
(the pitcher/batter are only known during a live at-bat); MiLB is
skipped because it has no ESPN player data.

The layout adapts to your panel size: on larger displays the headshot
sits on the left with a team-colored frame and the text stacks beside
it; on tiny panels (e.g. 64×32) the headshot is hidden and a compact
two-line text card is shown instead. If a headshot can't be loaded the
card renders text-only, and if no bio is available yet the card is
simply skipped that rotation (never shown blank).

### Enabling it

Turn it on per league under that league's `display_options`:

```json
{
  "mlb": {
    "display_options": {
      "show_player_card": true
    }
  }
}
```

The same flag exists under `ncaa_baseball.display_options`, off by
default. Enabling it works alongside (and independently of) the
Pitcher/Batter and Traditional Scoreboard screens — each rotates in on
its own schedule.

### Toggles and customization

All of the following live under `customization.player_card`:

| Option | Default | What it does |
|---|---|---|
| `show_batter` | `true` | Show a card for the current batter. |
| `show_pitcher` | `false` | Also show a card for the current pitcher (the batter is preferred when both are available). |
| `favorites_only` | `false` | Only rotate the card in for games involving one of this league's `favorite_teams`. Has no effect if `favorite_teams` is empty. |
| `dwell_seconds` | `6` | How many seconds the card stays on screen each time it rotates in. |
| `interval_seconds` | `40` | How often (in seconds) the card rotates in. |
| `font` | `"9x15.bdf"` | Font for the card's text; auto-fits within the space beside the headshot. Use a scalable `.ttf` font (e.g. `"press_start"`) if you want `font_size` to directly control the size. |
| `font_size` | `24` | Maximum font size cap, for scalable `.ttf` fonts only (ignored by fixed-size `.bdf` fonts like the default). |
| `use_team_colors` | `true` | Color the player's name with their real ESPN team color instead of the flat `text_color`. |
| `use_team_colors_border` | `true` | Draw the headshot's frame in the player's team color instead of the flat `border_color`. |
| `border_color` | `[255, 200, 0]` | `[R, G, B]` for the headshot frame when `use_team_colors_border` is off or the team color is unavailable. |
| `text_color` | `[255, 255, 255]` | `[R, G, B]` for the name (when team colors are off) and the jersey/position/bat-throw line. |
| `stat_color` | `[0, 220, 255]` | `[R, G, B]` for the season-stats line. |

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

- Off by default. Until you enable it the score is drawn in the plain white the
  scorebug uses everywhere else. (Before this release the scroll/Vegas recent
  card drew the final score gold, out of step with the switch view and with
  every other scoreboard; it is white now.)
- Only finished games are colored. Live and upcoming cards are untouched.
- A game needs exactly one favorite team. If neither side is a favorite, or both
  are, the score keeps its normal color.
- Applies to both the one-game-at-a-time switch view and the scroll/Vegas
  ticker.
- The three colors are Advanced settings; leave them alone for the defaults
  above.

## Troubleshooting

- **Game times look like UTC** (a 6:45pm Central first pitch showing as
  11:45PM): the plugin couldn't read your global timezone. Set `timezone`
  under the plugin's Advanced Settings to your IANA zone, e.g.
  `America/Chicago`. A `timezone` entry stuck on `"UTC"` from a version
  before 1.20.0 no longer needs clearing — since 1.20.1 it's ignored
  automatically whenever your global or system timezone disagrees. (Set
  `Etc/UTC` if you actually want UTC; that's always honored.)
- **No games showing**: Check if leagues are enabled and API endpoints are accessible
- **Missing team logos**: Ensure team logo files exist in your assets/sports/ directory
- **Slow updates**: Adjust the update interval in league configuration
- **API errors**: Check your internet connection and ESPN API availability

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

