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

# Hockey Scoreboard Plugin

Display live, recent, and upcoming hockey games across NHL, NCAA Men's, and NCAA Women's hockey on your LED matrix.


Recent Game:

<img width="768" height="192" alt="led_matrix_1764889670771" src="https://github.com/user-attachments/assets/1d32b4d9-7d01-4cb2-896b-bc9c889bf188" />

Upcoming Game:

<img width="768" height="192" alt="led_matrix_1764889695301" src="https://github.com/user-attachments/assets/5e6dd53c-0486-4d42-bdaa-6d486729bcc4" />




## Features

- **Multi-League Support**: NHL, NCAA Men's Hockey, NCAA Women's Hockey
- **Live Game Tracking**: Real-time scores, periods, time remaining
- **Recent Games**: View recently completed game results
- **Upcoming Games**: See scheduled games with start times
- **Favorite Teams**: Prioritize your favorite teams across all leagues
- **Power Play Indicators**: Highlight power play situations
- **Shots on Goal**: Optional SOG statistics display
- **Team Logos**: Display team logos when available
- **Background Data Fetching**: Efficient API calls with caching
- **Font Customization**: Override fonts via Web UI
- **Favorite Team Result Colors**: Optionally show a finished game's score in green when your favorite team won and red when it lost

## Requirements

- LEDMatrix 2.0.0+
- Display: Minimum 64x32 pixels (recommended)
- No API key required (uses ESPN public API)
- Internet connection for live data


#### League Selection

- **`leagues.nhl`**: Enable NHL games (default: true)
- **`leagues.ncaa_mens`**: Enable NCAA Men's Hockey (default: false)
- **`leagues.ncaa_womens`**: Enable NCAA Women's Hockey (default: false)

  (note: College Club Hockey is not tracked - team like UGA does not have D1 hockey and cannot be shown)

Enable multiple leagues to see games from all selected leagues in rotation.

## 📺 Display Modes

The plugin registers granular display modes directly in `manifest.json`. The display controller rotates through these modes automatically:

**NHL Modes:**
- `nhl_recent`: Recently completed NHL games with final scores
- `nhl_upcoming`: Scheduled NHL games with start times
- `nhl_live`: Currently active NHL games with real-time updates

**NCAA Men's Hockey Modes:**
- `ncaa_mens_recent`: Recently completed NCAA Men's Hockey games with final scores
- `ncaa_mens_upcoming`: Scheduled NCAA Men's Hockey games with start times
- `ncaa_mens_live`: Currently active NCAA Men's Hockey games with real-time updates

**NCAA Women's Hockey Modes:**
- `ncaa_womens_recent`: Recently completed NCAA Women's Hockey games with final scores
- `ncaa_womens_upcoming`: Scheduled NCAA Women's Hockey games with start times
- `ncaa_womens_live`: Currently active NCAA Women's Hockey games with real-time updates

### How Rotation Works

The display controller rotates through all registered modes in the order they appear in `manifest.json`. Each mode's duration is configured under `<league>.display_durations.{base,live,recent,upcoming}` (or the cross-league fallback `defaults.display_duration`).

**Default Rotation Order:**
1. `nhl_recent`
2. `nhl_upcoming`
3. `nhl_live`
4. `ncaa_mens_recent`
5. `ncaa_mens_upcoming`
6. `ncaa_mens_live`
7. `ncaa_womens_recent`
8. `ncaa_womens_upcoming`
9. `ncaa_womens_live`

**Customizing Rotation Order:**
You can reorder modes in `manifest.json` to change the rotation sequence. For example, to show all Recent games before Upcoming:

```json
"display_modes": [
  "nhl_recent",
  "ncaa_mens_recent",
  "ncaa_womens_recent",
  "nhl_upcoming",
  "ncaa_mens_upcoming",
  "ncaa_womens_upcoming",
  "nhl_live",
  "ncaa_mens_live",
  "ncaa_womens_live"
]
```

### Disabled Leagues/Modes

If a league or mode is disabled in the config, the plugin returns `False` for that mode, and the display controller automatically skips it. This allows you to:

- Disable entire leagues (e.g., disable NCAA Men's to show only NHL)
- Disable specific modes per league (e.g., disable `nhl_upcoming` but keep `nhl_recent` and `nhl_live`)
- Mix and match enabled/disabled modes as needed

### Mode Durations

Each granular mode respects its own mode duration settings:
- `nhl_recent` uses `nhl.mode_durations.recent_mode_duration` or falls back to dynamic calculation
- `ncaa_mens_upcoming` uses `ncaa_mens.mode_durations.upcoming_mode_duration` or falls back to dynamic calculation
- Each mode can have independent duration configuration

### Live Priority

When live games are available, the display controller prioritizes live modes (`nhl_live`, `ncaa_mens_live`, `ncaa_womens_live`) based on the `has_live_content()` and `get_live_modes()` methods. The plugin returns only the granular live modes that actually have live content.

## ⏱️ Duration Configuration

The plugin offers flexible duration control at multiple levels to fine-tune your display experience:

### Per-Game Duration

Controls how long each individual game displays before rotating to the next game **within the same mode**.

**Configuration:**
- Per-league `display_durations.live`: Seconds per live game (default: 20s for NHL)
- Per-league `display_durations.non_favorite_live`: Seconds per live game with **no** favorite team (default: 0 = off)
- Per-league `display_durations.recent`: Seconds per recent game (default: 15s)
- Per-league `display_durations.upcoming`: Seconds per upcoming game (default: 15s)

**Example:** With `nhl.display_durations.recent: 15`, each NHL recent game shows for 15 seconds before moving to the next.

#### Shorter dwell for non-favorite live games

Set `display_durations.non_favorite_live` to give live games that don't involve one of your favorite teams a shorter turn than your favorites. For example `nhl.display_durations.live: 30` with `nhl.display_durations.non_favorite_live: 5` shows your teams for 30s each while everyone else's games flash by in 5s.

This **only takes effect when both** of the following are true:

- one or more `favorite_teams` are configured for the league, **and**
- non-favorite live games are actually shown — `filtering.show_favorite_teams_only` is **off**, or `filtering.show_all_live` is **on** (otherwise non-favorite games never appear in the first place).

| Favorite teams set? | Non-favorite games shown? | Live game has a favorite? | Duration used |
|---|---|---|---|
| No | — | — | `display_durations.live` (unchanged) |
| Yes | No (`show_favorite_teams_only` on, `show_all_live` off) | favorite | `display_durations.live` |
| Yes | Yes (`show_favorite_teams_only` off, or `show_all_live` on) | favorite | `display_durations.live` |
| Yes | Yes (`show_favorite_teams_only` off, or `show_all_live` on) | none | `display_durations.non_favorite_live` (when > 0) |

Leave it at `0` to display every live game for `display_durations.live` (the previous behavior).

### Per-Mode Duration

Controls the **total time** a mode displays before rotating to the next mode, regardless of how many games are available.

**Configuration:**
- `nhl.mode_durations.recent_mode_duration`: Total seconds for NHL Recent mode (default: dynamic)
- `nhl.mode_durations.upcoming_mode_duration`: Total seconds for NHL Upcoming mode (default: dynamic)
- `nhl.mode_durations.live_mode_duration`: Total seconds for NHL Live mode (default: dynamic)
- Same structure for `ncaa_mens` and `ncaa_womens`

**Example:** With `nhl.mode_durations.recent_mode_duration: 60` and `nhl.display_durations.recent: 15`, NHL Recent mode shows 4 games (60s ÷ 15s = 4) before rotating to the next mode.

### How They Work Together

**Per-game duration** + **Per-mode duration**:
```text
NHL Recent Mode (60s total):
  ├─ Game 1: 15s
  ├─ Game 2: 15s
  ├─ Game 3: 15s
  └─ Game 4: 15s
  → Rotate to NHL Upcoming Mode

NHL Upcoming Mode (60s total):
  ├─ Game 1: 15s
  └─ ... (continues)
```

### Resume Functionality

When a mode times out before showing all games, it **resumes from where it left off** on the next cycle:

```text
Cycle 1: NHL Recent Mode (60s, 10 games available)
  ├─ Game 1-4 shown ✓
  └─ Time expires → Rotate

Cycle 2: NHL Recent Mode resumes
  ├─ Game 5-8 shown ✓ (continues from Game 4, no repetition)
  └─ Time expires → Rotate

Cycle 3: NHL Recent Mode resumes
  ├─ Game 9-10 shown ✓
  └─ All games shown → Full cycle complete → Reset progress
```

### Dynamic Duration (Fallback)

If per-mode durations are **not** configured, the plugin uses **dynamic calculation**:
- **Formula**: `total_duration = number_of_games × per_game_duration`
- **Example**: 24 games @ 15s each = 360 seconds for the mode

This ensures all games are shown but may result in very long mode durations if you have many games.

### Per-League Overrides

You can set different durations per league using the `mode_durations` section:

```json
{
  "nhl": {
    "mode_durations": {
      "recent_mode_duration": 45,
      "upcoming_mode_duration": 30
    }
  },
  "ncaa_mens": {
    "mode_durations": {
      "recent_mode_duration": 60
    }
  }
}
```

When multiple leagues are enabled with different durations, the system uses the **maximum** to ensure all leagues get their time.

### Integration with Dynamic Duration Caps

If you have dynamic duration caps configured (e.g., `max_duration_seconds: 120`), the system uses the **minimum** of:
- Per-mode duration (e.g., 180s)
- Dynamic duration cap (e.g., 120s)
- **Result**: 120s (ensures cap is respected)

#### Favorite Teams

Specify team abbreviations for each league:

```json
"favorite_teams": {
  "nhl": ["TB", "TOR", "BOS", "DET"],
  "ncaa_mens": ["BU", "BC", "MICH"],
  "ncaa_womens": ["WISC", "MINN"]
}
```

#### Favorite Live Boost

Each league's `teams` block also has a `favorite_live_boost` (default `2`,
range 1-5): whenever one of your favorite teams is playing live, their game
is always queued first in the live rotation, and gets `favorite_live_boost`
turns for every 1 turn other live games get (evenly spaced, not clumped
together). Set it to `1` for perfectly even rotation among all live games —
this exactly matches the plugin's previous behavior. It has no effect unless
`favorite_teams` is configured, so it's safe to leave at its default.

#### Exclude Teams

Each league's `teams` block also has an `exclude_teams` list (same format as
`favorite_teams`) for teams you never want to see — useful if you're
planning to watch a game delayed and don't want the score spoiled. An
excluded team's games are hidden from **both** the live rotation and the
Recent/Final-scores mode, regardless of `favorite_teams`, `favorite_teams_only`,
or `show_all_live`. If a team is in both `favorite_teams` and `exclude_teams`,
exclusion wins.

#### Display Settings

The full set of options lives in
[`config_schema.json`](config_schema.json) — the schema is the source of
truth and is what generates the web UI. The most commonly tweaked keys:

- **`enabled`** (boolean, default `false`) — master switch for the plugin
- **`defaults.display_duration`** (5–60s, default `15`) — fallback per-game
  duration when a league doesn't override it
- **`defaults.show_records`** (boolean, default `false`) — show team
  records (W-L)
- **`defaults.show_shots_on_goal`** (boolean, default `false`) — show SOG
  during live games
- **`defaults.show_powerplay`** (boolean, default `true`) — highlight power
  play situations
- **`defaults.update_interval_seconds`** (30–86400s, default `3600`) —
  default base poll interval. Per-league `update_intervals.*` overrides
  this.

Each league (`nhl`, `ncaa_mens`, `ncaa_womens`) then has its own block with
finer-grained controls:

- `<league>.update_intervals.{base,live,recent,upcoming,odds}` — how often
  to poll ESPN for each kind of data. Live games default to 30s; recent
  and upcoming default to 3600s.
- `<league>.display_durations.{base,live,recent,upcoming}` — per-mode
  display duration overrides for that league.
- `<league>.display_options.{show_records,show_ranking,show_odds,...}` —
  per-league overrides of the cross-league defaults.
- `<league>.live_priority` (boolean) — let this league's live games take
  over the rotation when one is in progress.

## Display Mode Details

### Live Games (e.g., `nhl_live`, `ncaa_mens_live`)

Shows games currently in progress with:
- Current score
- Period (P1, P2, P3, OT, OT2, etc.)
- Time remaining in period
- Power play indicator (if enabled)
- Shots on goal (if enabled)

### Recent Games (e.g., `nhl_recent`, `ncaa_mens_recent`)

Shows completed games from the last X hours with:
- Final score
- Game status ("Final", "Final/OT", "Final/SO")
- Team logos

### Upcoming Games (e.g., `nhl_upcoming`, `ncaa_mens_upcoming`)

Shows scheduled games for the next X hours with:
- Game start time
- Venue information
- Team matchup

## Setup Instructions

### 1. Install Plugin

Install from the Plugin Store in the LEDMatrix web UI:

1. Open `http://your-pi-ip:5000`
2. Open the **Plugin Manager** tab
3. Find **Hockey Scoreboard** in the **Plugin Store** section and click
   **Install**
4. The plugin appears in **Installed Plugins** above and gets its own tab
   in the second nav row — open that tab to configure it

### 2. Configure Leagues

Enable the leagues you want to track:

- **NHL Only**: Set `leagues.nhl: true`, others false
- **All Leagues**: Set all to true
- **NCAA Only**: Enable `ncaa_mens` and/or `ncaa_womens`

### 3. Add Favorite Teams

Add your favorite team abbreviations to the `favorite_teams` object for each league. Games involving these teams will be shown first when `<league>.live_priority` is enabled.

### 4. Adjust Display Settings

- Set `<league>.display_durations.{base,live,recent,upcoming}` (or the fallback `defaults.display_duration`) based on how many games you expect (shorter = more games shown)
- Adjust `<league>.update_intervals.{base,live,recent,upcoming,odds}` (or the fallback `defaults.update_interval_seconds`) based on desired freshness (30s live poll recommended)
- Enable/disable display modes based on preference

### 5. Enable Plugin

Make sure `enabled: true` in the configuration and the plugin is activated in the rotation.


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

**No games showing:**
- **Start times look like UTC** (a 6:45pm Central start showing as 11:45PM):
  the plugin couldn't read your global timezone. Set `timezone` under the
  plugin's Advanced Settings to your IANA zone, e.g. `America/Chicago`.
- Check that at least one league is enabled in config
- Verify the season is active for enabled leagues
- Check `recent_games_hours` and `upcoming_games_hours` settings
- Ensure internet connection is working

**Games not updating:**
- Check `<league>.update_intervals.*` (or `defaults.update_interval_seconds`) settings
- Verify API is responding (check logs)
- Try clearing cache: restart plugin or clear cache manually
- Check background service is enabled

**Favorite teams not showing:**
- Verify team abbreviations are correct (case-sensitive)
- Ensure `<league>.live_priority` is true
- Check that favorite teams have games in current time window

**Logos not displaying:**
- Verify logo assets are available in LEDMatrix installation
- Check `assets/sports/nhl_logos` and `assets/sports/ncaa_logos` directories
- Some NCAA teams may not have logos available

**Power play not showing:**
- Enable `show_powerplay` in config
- Verify ESPN API includes situation data (may not be available for all leagues)

**SOG not accurate:**
- Enable `defaults.show_shots_on_goal` (or the per-league override `<league>.display_options.show_shots_on_goal`) in config
- ESPN API may have delayed SOG updates
- Some leagues may not provide SOG data

## Advanced Configuration

### Custom Fonts

Override default fonts via config or Web UI:

```json
"fonts": {
  "team_name": {
    "family": "press_start",
    "size": 10,
    "color": "#FFFFFF"
  },
  "score": {
    "family": "press_start",
    "size": 12,
    "color": "#FFC800"
  },
  "status": {
    "family": "four_by_six",
    "size": 6,
    "color": "#00FF00"
  }
}
```

### Layout Customization

The plugin supports fine-tuning element positioning for custom display sizes. All offsets are relative to the default calculated positions, allowing you to adjust elements without breaking the layout.

#### Accessing Layout Settings

Layout customization is available in the plugin's tab in the web UI:
1. Open the **Hockey Scoreboard** tab (second nav row)
2. Expand the **Customization** section
3. Find the **Layout Positioning** subsection

#### Offset Values

- **Positive values**: Move element right (x_offset) or down (y_offset)
- **Negative values**: Move element left (x_offset) or up (y_offset)
- **Default (0)**: No change from calculated position

#### Available Elements

- **home_logo**: Home team logo position (x_offset, y_offset)
- **away_logo**: Away team logo position (x_offset, y_offset)
- **score**: Game score position (x_offset, y_offset)
- **status_text**: Status/period text position (x_offset, y_offset)
- **date**: Game date position (x_offset, y_offset)
- **time**: Game time position (x_offset, y_offset)
- **records**: Team records/rankings position (away_x_offset, home_x_offset, y_offset)

#### Example Adjustments

**Move logos inward for smaller displays:**
```json
{
  "customization": {
    "layout": {
      "home_logo": { "x_offset": -5 },
      "away_logo": { "x_offset": 5 }
    }
  }
}
```

**Adjust score position:**
```json
{
  "customization": {
    "layout": {
      "score": { "x_offset": 0, "y_offset": -2 }
    }
  }
}
```

**Shift records upward:**
```json
{
  "customization": {
    "layout": {
      "records": { "y_offset": -3 }
    }
  }
}
```

#### Display Size Compatibility

Layout offsets work across different display sizes. The plugin calculates default positions based on your display dimensions, and offsets are applied relative to those defaults. This ensures compatibility with various LED matrix configurations.

### Multi-League Strategy

Enable all three leagues for comprehensive coverage:

```json
"leagues": {
  "nhl": true,
  "ncaa_mens": true,
  "ncaa_womens": true
}
```

Games from all leagues will be mixed and sorted by:
1. Live games first
2. Favorite teams (if enabled)
3. Start time

### Timezone

- `timezone` (Advanced): IANA name used to display event start times, e.g.
  `America/Chicago`. Leave blank (the default) to follow the LEDMatrix global
  timezone; if that isn't set, the host system's timezone is used, and only if
  neither is available do times fall back to UTC.

## Data Source

This plugin uses the **ESPN public API** for all hockey data:

- **NHL**: `https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard`
- **NCAA M**: `https://site.api.espn.com/apis/site/v2/sports/hockey/mens-college-hockey/scoreboard`
- **NCAA W**: `https://site.api.espn.com/apis/site/v2/sports/hockey/womens-college-hockey/scoreboard`

**Note**: No API key required. Please use responsibly and respect ESPN's rate limits.

## Examples

### NHL Only Configuration

```json
{
  "enabled": true,
  "leagues": {
    "nhl": true,
    "ncaa_mens": false,
    "ncaa_womens": false
  },
  "favorite_teams": {
    "nhl": ["TB", "TOR", "BOS"]
  },
  "defaults": {
    "update_interval_seconds": 60,
    "display_duration": 15
  },
  "nhl": {
    "enabled": true,
    "display_modes": {
      "live": true,
      "recent": true,
      "upcoming": false
    },
    "update_intervals": {
      "base": 60,
      "live": 30
    },
    "display_durations": {
      "base": 15,
      "live": 20
    }
  }
}
```

### NCAA Men's Only Configuration

```json
{
  "enabled": true,
  "leagues": {
    "nhl": false,
    "ncaa_mens": true,
    "ncaa_womens": false
  },
  "favorite_teams": {
    "ncaa_mens": ["BU", "BC", "MICH", "WISC"]
  },
  "ncaa_mens": {
    "enabled": true,
    "display_modes": {
      "live": true,
      "recent": true,
      "upcoming": true
    },
    "update_intervals": {
      "base": 120
    },
    "upcoming_games_hours": 168
  }
}
```

### All Leagues Configuration

```json
{
  "enabled": true,
  "leagues": {
    "nhl": true,
    "ncaa_mens": true,
    "ncaa_womens": true
  },
  "favorite_teams": {
    "nhl": ["TB", "DET"],
    "ncaa_mens": ["MICH"],
    "ncaa_womens": ["WISC"]
  },
  "defaults": {
    "show_shots_on_goal": true,
    "show_powerplay": true
  },
  "nhl": {
    "enabled": true,
    "live_priority": true,
    "display_modes": {
      "live": true,
      "recent": true,
      "upcoming": true
    }
  },
  "ncaa_mens": {
    "enabled": true,
    "display_modes": {
      "live": true,
      "recent": true,
      "upcoming": true
    }
  },
  "ncaa_womens": {
    "enabled": true,
    "display_modes": {
      "live": true,
      "recent": true,
      "upcoming": true
    }
  }
}
```

## Integration Notes

### Base Classes

This plugin uses LEDMatrix base classes:
- `Hockey` - Base hockey functionality
- `HockeyLive` - Live game display logic
- `SportsRecent` - Recent games display
- `SportsUpcoming` - Upcoming games display

These are imported from the main LEDMatrix installation at `src/base_classes/`.

### Caching

The plugin uses LEDMatrix's `CacheManager` to cache API responses:
- Cache duration: 5 minutes for live data
- Cache key format: `hockey_{league}_{date}`
- Automatic cache invalidation on date change

### Background Service

Uses LEDMatrix's `BackgroundDataService` for:
- Non-blocking API requests
- Automatic retries on failure
- Request prioritization
- Timeout handling

## Performance

### Resource Usage

- **CPU**: Low (background fetching, cached data)
- **Memory**: ~5–10 MB for game data
- **Network**: ~1–5 KB per API call per league
- **API calls**: depends on how many leagues are enabled and which
  `update_intervals` you set. With defaults (NHL only, base 60s, live 30s,
  recent/upcoming 3600s) and no live games, expect about one ESPN call per
  minute per enabled league.

### Optimization Tips

1. **Disable Unused Leagues**: Only enable leagues you follow
2. **Increase Update Interval**: Use 120-300s during off-season
3. **Reduce Time Windows**: Lower `recent_games_hours` and `upcoming_games_hours`
4. **Enable Caching**: Keep `background_service.enabled: true`

## 🎯 Which Games Get Shown

**`upcoming_games_to_show` is not "how many cards you see".** It is the size of a *pool*. The panel cycles through that pool one card at a time and keeps its place between visits, so a pool of 3 means the board rotates through the same 3 games until the schedule moves on. Making the number bigger gives you a *longer lap*, so any one game comes round **less** often.

Which mode you are in depends on whether `favorite_teams` is set and whether `show_favorite_teams_only` is on:

| `favorite_teams` | `show_favorite_teams_only` | What you get |
|---|---|---|
| empty | either | The next N games league-wide, chronologically. |
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
| `other_games_divisions` | `["fbs"]` | Which divisions non-favorite games may come from. |

**Your favorite teams are never filtered by the last two** — follow a smaller-division team and its games always appear. Those settings only decide what fills the *remaining* slots.

### Variety comes from turnover

Rather than widening the pool, the non-favorite slice **moves**: the window advances by its own width every `other_rotation_interval_seconds`, so consecutive windows do not overlap and the board works through the schedule instead of resampling the front of it. Your favorites are not rotated — for upcoming games the soonest ones are the point.

Both filters **fail open**: if the data behind them cannot be fetched, the game is allowed through. A board showing filler is a poor board; a board showing nothing is a broken one.

> `other_games_min_quality` and `other_games_divisions` only mean something for leagues with a national poll and divisions — that is, the college ones. Elsewhere they are inert and cost nothing: no poll is requested and no division lookup is made.


## License

GPL-3.0 License - see main LEDMatrix repository for details.

## Support

- **Issues**: [GitHub Issues](https://github.com/ChuckBuilds/ledmatrix-plugins/issues)
- **Documentation**: see the LEDMatrix
  [`docs/`](https://github.com/ChuckBuilds/LEDMatrix/tree/main/docs) directory
- **Community**: [Discussions](https://github.com/ChuckBuilds/LEDMatrix/discussions)

---

For the current version, author, category and tags see
[`manifest.json`](manifest.json) — that's the source of truth and is
what the Plugin Store reads.

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
