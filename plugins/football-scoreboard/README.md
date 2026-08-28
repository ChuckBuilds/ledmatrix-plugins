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

# Football Scoreboard Plugin

A production-ready plugin for LEDMatrix that displays live, recent, and upcoming football games across NFL and NCAA Football leagues. This plugin reuses the proven, battle-tested code from the main LEDMatrix project for maximum reliability and feature completeness.

## 🏈 Features

Upcoming Game (NCAA FB):

<img width="768" height="192" alt="led_matrix_1764889978847" src="https://github.com/user-attachments/assets/3561386b-1327-415d-92bc-f17f7e446984" />

Recent Game (NCAA FB):

<img width="768" height="192" alt="led_matrix_1764889931266" src="https://github.com/user-attachments/assets/a5361ddf-5472-4724-9665-1783db4eb3d1" />



### Core Functionality
- **Multiple League Support**: NFL and NCAA Football with independent configuration
- **Live Game Tracking**: Real-time scores, quarters, time remaining, down & distance
- **Recent Games**: Recently completed games with final scores and records
- **Upcoming Games**: Scheduled games with start times and odds
- **Dynamic Team Resolution**: Support for `AP_TOP_25`, `AP_TOP_10`, `AP_TOP_5` automatic team selection
- **Production-Ready**: Real ESPN API integration with caching and error handling
- **Favorite Team Result Colors**: Optionally show a finished game's score in green when your favorite team won and red when it lost

### Professional Display
- **Team Logos**: Professional team logos with automatic download fallback
- **Scorebug Layout**: Broadcast-quality scoreboard display
- **Football-Specific Details**: Down & distance, possession indicators, timeout tracking
- **Color-Coded States**: Live (green), final (gray), upcoming (yellow), redzone (red)
- **Odds Integration**: Real-time betting odds display with spread and over/under
- **Rankings Display**: AP Top 25 rankings for NCAA Football teams

### Advanced Features
- **Score/Win Celebrations**: Full-screen takeover when a favorite team scores or wins a live game (see below)
- **Background Data Service**: Non-blocking API calls with intelligent caching
- **Smart Filtering**: Show favorite teams only or all games
- **Granular Mode Control**: Enable/disable specific league/mode combinations independently
- **Dual Display Styles**: Switch mode (one game at a time) or scroll mode (all games scrolling)
- **High-FPS Scrolling**: Smooth 100+ FPS horizontal scrolling for scroll mode
- **Font Customization**: Customize fonts, sizes, and styles for all text elements
- **Layout Customization**: Adjust X/Y positioning offsets for all display elements
- **Error Recovery**: Graceful handling of API failures and missing data
- **Memory Optimized**: Efficient resource usage for Raspberry Pi deployment

## 🎯 Dynamic Team Resolution

The plugin supports automatic team selection using dynamic patterns:

- **`AP_TOP_25`**: Automatically includes all 25 AP Top 25 ranked teams
- **`AP_TOP_10`**: Automatically includes top 10 ranked teams  
- **`AP_TOP_5`**: Automatically includes top 5 ranked teams

These patterns update automatically as rankings change throughout the season. You can mix them with specific teams:

```json
"favorite_teams": ["AP_TOP_25", "UGA", "ALA"]
```

This will show games for all AP Top 25 teams plus Georgia and Alabama (duplicates are automatically removed).

> **These expand into real teams, and that has consequences.** Adding `AP_TOP_10` alongside two teams of your own makes yours 2 of 11 favorites, all competing for the same slots — so your teams can stop appearing. See [Which Games Get Shown](#-which-games-get-shown) before mixing them.

## 📺 Display Modes

### Granular Mode Control

The plugin supports **granular display modes** that give you precise control over what's shown:

- **NFL Modes**: `nfl_live`, `nfl_recent`, `nfl_upcoming`
- **NCAA FB Modes**: `ncaa_fb_live`, `ncaa_fb_recent`, `ncaa_fb_upcoming`

Each league and game type can be independently enabled or disabled. This allows you to:
- Show only NFL live games
- Show only NCAA FB recent games
- Mix and match any combination of modes
- Control exactly which content appears on your display

### Display Style Options

The plugin supports two display styles for each game type:

1. **Switch Mode** (Default): Display one game at a time with timed transitions
   - Shows each game for a configurable duration
   - Smooth transitions between games
   - Best for focused viewing of individual games

2. **Scroll Mode**: High-FPS horizontal scrolling of all games
   - All games scroll horizontally in a continuous stream
   - League separator icons between different leagues
   - Dynamic duration based on total content width
   - Supports 100+ FPS smooth scrolling
   - Best for seeing all games at once

You can configure the display mode separately for live, recent, and upcoming games in each league.

### How Rotation Works

The plugin registers granular display modes directly in `manifest.json`. The display controller rotates through these modes automatically in the order they appear. Each mode can have its own `display_duration` configured in the plugin config.

**Default Rotation Order:**
1. `nfl_recent`
2. `nfl_upcoming`
3. `nfl_live`
4. `ncaa_fb_recent`
5. `ncaa_fb_upcoming`
6. `ncaa_fb_live`

**Customizing Rotation Order:**
You can reorder modes in `manifest.json` to change the rotation sequence. For example, to show all Recent games before Upcoming:

```json
"display_modes": [
  "nfl_recent",
  "ncaa_fb_recent",
  "nfl_upcoming",
  "ncaa_fb_upcoming",
  "nfl_live",
  "ncaa_fb_live"
]
```

**Disabled Leagues/Modes:**
If a league or mode is disabled in the config, the plugin returns `False` for that mode, and the display controller automatically skips it. This allows you to:
- Disable entire leagues (e.g., disable NCAA FB to show only NFL)
- Disable specific modes per league (e.g., disable `nfl_upcoming` but keep `nfl_recent` and `nfl_live`)
- Mix and match enabled/disabled modes as needed

### Mode Durations

Each granular mode respects its own mode duration settings:
- `nfl_recent` uses `nfl.mode_durations.recent_mode_duration` or top-level `recent_mode_duration`
- `ncaa_fb_upcoming` uses `ncaa_fb.mode_durations.upcoming_mode_duration` or top-level `upcoming_mode_duration`
- Each mode can have independent duration configuration

### Live Priority

When live games are available, the display controller prioritizes live modes (`nfl_live`, `ncaa_fb_live`) based on the `has_live_content()` and `get_live_modes()` methods. The plugin returns only the granular live modes that actually have live content.

## ⏱️ Duration Configuration

The plugin offers flexible duration control at multiple levels to fine-tune your display experience:

### Per-Game Duration

Controls how long each individual game displays before rotating to the next game **within the same mode**.

**Configuration:**
- `live_game_duration`: Seconds per live game (default: 30s)
- `non_favorite_live_game_duration`: Seconds per live game with **no** favorite team (default: 0 = off)
- `recent_game_duration`: Seconds per recent game (default: 15s)
- `upcoming_game_duration`: Seconds per upcoming game (default: 15s)

**Example:** With `recent_game_duration: 15`, each recent game shows for 15 seconds before moving to the next.

#### Shorter dwell for non-favorite live games

Set `non_favorite_live_game_duration` to give live games that don't involve one of your favorite teams a shorter turn than your favorites. For example, `live_game_duration: 30` and `non_favorite_live_game_duration: 5` shows your teams for 30s each while everyone else's games flash by in 5s.

This **only takes effect when both** of the following are true:

- one or more `favorite_teams` are configured for the league, **and**
- non-favorite live games are actually shown — `filtering.show_favorite_teams_only` is **off**, or `filtering.show_all_live` is **on** (otherwise non-favorite games never appear in the first place).

| Favorite teams set? | Non-favorite games shown? | Live game has a favorite? | Duration used |
|---|---|---|---|
| No | — | — | `live_game_duration` (unchanged) |
| Yes | No (`show_favorite_teams_only` on, `show_all_live` off) | favorite | `live_game_duration` |
| Yes | Yes (`show_favorite_teams_only` off, or `show_all_live` on) | favorite | `live_game_duration` |
| Yes | Yes (`show_favorite_teams_only` off, or `show_all_live` on) | none | `non_favorite_live_game_duration` (when > 0) |

Leave it at `0` to display every live game for `live_game_duration` (the previous behavior).

### Per-Mode Duration

Controls the **total time** a mode displays before rotating to the next mode, regardless of how many games are available.

**Configuration:**
- `recent_mode_duration`: Total seconds for Recent mode (default: dynamic)
- `upcoming_mode_duration`: Total seconds for Upcoming mode (default: dynamic)
- `live_mode_duration`: Total seconds for Live mode (default: dynamic)

**Example:** With `recent_mode_duration: 60` and `recent_game_duration: 15`, Recent mode shows 4 games (60s ÷ 15s = 4) before rotating to Upcoming mode.

### How They Work Together

**Per-game duration** + **Per-mode duration**:
```
Recent Mode (60s total):
  ├─ Game 1: 15s
  ├─ Game 2: 15s
  ├─ Game 3: 15s
  └─ Game 4: 15s
  → Rotate to Upcoming Mode

Upcoming Mode (60s total):
  ├─ Game 1: 15s
  └─ ... (continues)
```

### Resume Functionality

When a mode times out before showing all games, it **resumes from where it left off** on the next cycle:

```
Cycle 1: Recent Mode (60s, 10 games available)
  ├─ Game 1-4 shown ✓
  └─ Time expires → Rotate

Cycle 2: Recent Mode resumes
  ├─ Game 5-8 shown ✓ (continues from Game 4, no repetition)
  └─ Time expires → Rotate

Cycle 3: Recent Mode resumes
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
  "nfl": {
    "mode_durations": {
      "recent_mode_duration": 45,
      "upcoming_mode_duration": 30
    }
  },
  "ncaa_fb": {
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

## 🎨 Visual Features

### Professional Scorebug Display
- **Team Logos**: High-quality team logos positioned on left and right sides
- **Scores**: Centered score display with outlined text for visibility
- **Game Status**: Quarter/time display at top center
- **Date Display**: Recent games show date underneath score
- **Down & Distance**: Live game situation information (NFL only)
- **Possession Indicator**: Visual indicators for ball possession
- **Odds Display**: Spread and over/under betting lines
- **Rankings**: AP Top 25 rankings for NCAA Football
- **Customizable Layout**: Adjust positioning of all elements via X/Y offsets
- **Customizable Fonts**: Configure font family and size for each text element

### Adaptive Layout (beta)

Set `"layout_mode": "adaptive"` to scale fonts, logos, and element regions
to your panel size — the score renders at up to 32px on a 256x128 instead of
the fixed 10px, and layouts degrade gracefully on small panels.

```json
{
  "layout_mode": "adaptive"
}
```

- The default is `"classic"`: rendering is completely unchanged unless you
  opt in. **To revert at any time, set it back to `"classic"`** — no
  reinstall needed.
- Your font and X/Y offset customizations still apply in adaptive mode:
  an explicitly configured font wins over the adaptive sizing, and offsets
  shift elements from their computed positions.
- Requires a LEDMatrix core with the adaptive layout system
  (`docs/ADAPTIVE_LAYOUT.md`); older cores silently keep the classic layout.

### Layout Customization

The plugin supports fine-tuning element positioning for custom display sizes. All offsets are relative to the default calculated positions, allowing you to adjust elements without breaking the layout.

#### Accessing Layout Settings

Layout customization is available in the web UI under the plugin configuration section:
1. Open the **Football Scoreboard** tab (second nav row)
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

### Color Coding
- **Live Games**: Green text for active status
- **Redzone**: Red highlighting when teams are in scoring position
- **Final Games**: Gray text for completed games
- **Upcoming Games**: Yellow text for scheduled games
- **Odds**: Green text for betting information

### Score & Win Celebrations
When a favorite team scores or wins a **live** game, the scorebug briefly gives
way to a full-screen celebration: the involved team logos at the edges, the new
score centered with the scoring side's digit pulsing, and a banner at the top.

The banner is chosen from the **points scored between two updates** (not from any
feed text), so it works for every league the same way:

| Points gained | Banner |
|---|---|
| 6 or more | `TOUCHDOWN!` / `<TEAM> TD!` |
| 3 | `<TEAM> FIELD GOAL!` |
| 2 | `<TEAM> SAFETY!` |
| other (e.g. lone extra point) | `<TEAM> SCORES!` |
| game goes final, favorite ahead | `<TEAM> WINS!` |

A touchdown that arrives as `+6` then a `+1` extra point a few seconds later
shows a **single** celebration — the extra point is folded in while the first is
still on screen. Note that a 2-point conversion and a safety are both `+2`; the
banner reads `SAFETY!` for either.

Configure per league (under the `nfl` / `ncaa_fb` config sections):
- `celebration_enabled` (boolean, default `true`)
- `celebration_duration` (seconds on screen, default `8`)
- `celebrate_opponent_scores` (also celebrate the opponent, default `false`; when
  no favorite teams are configured, any team's score celebrates)

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

## 🏷️ Team Abbreviations

### NFL Teams
Common abbreviations: TB, DAL, GB, KC, BUF, SF, PHI, NE, MIA, NYJ, LAC, DEN, LV, CIN, BAL, CLE, PIT, IND, HOU, TEN, JAX, ARI, LAR, SEA, WAS, NYG, MIN, DET, CHI, ATL, CAR, NO

### NCAA Football Teams
Common abbreviations: UGA (Georgia), AUB (Auburn), BAMA (Alabama), CLEM (Clemson), OSU (Ohio State), MICH (Michigan), FSU (Florida State), LSU (LSU), OU (Oklahoma), TEX (Texas), ORE (Oregon), MISS (Mississippi), GT (Georgia Tech), VAN (Vanderbilt), BYU (BYU)

## 🔧 Technical Details

### Architecture
This plugin reuses the proven code from the main LEDMatrix project:
- **SportsCore**: Base class for all sports functionality
- **Football**: Football-specific game detail extraction
- **NFL Managers**: Live, Recent, and Upcoming managers for NFL
- **NCAA FB Managers**: Live, Recent, and Upcoming managers for NCAA Football
- **BaseOddsManager**: Production-ready odds fetching from ESPN API
- **DynamicTeamResolver**: Automatic team resolution for rankings

### Data Sources
- **ESPN API**: Primary data source for games, scores, and rankings
- **Real-time Updates**: Live game data updates every 30 seconds
- **Intelligent Caching**: 1-hour cache for rankings, 30-minute cache for odds
- **Error Recovery**: Graceful handling of API failures

### Performance
- **Background Processing**: Non-blocking data fetching
- **Memory Optimized**: Efficient resource usage for Raspberry Pi
- **Smart Caching**: Reduces API calls while maintaining data freshness
- **Configurable Intervals**: Adjustable update frequencies per league

## 📦 Installation

### From the Plugin Store (recommended)
1. Open the LEDMatrix web interface (`http://your-pi-ip:5000`)
2. Open the **Plugin Manager** tab
3. Find **Football Scoreboard** in the **Plugin Store** section and click
   **Install**
4. Open the **Football Scoreboard** tab in the second nav row to configure
   your favorite teams and per-league preferences


## ⚙️ Configuration

### Display Mode Settings

Each league (NFL, NCAA FB) can be configured with:
- **Enable/Disable**: Turn entire leagues on or off
- **Mode Toggles**: Enable/disable live, recent, or upcoming games independently
- **Display Style**: Choose "switch" (one game at a time) or "scroll" (all games scrolling) for each game type
- **Scroll Settings**: Configure scroll speed, frame delay, gap between games, and league separators

### Filtering & Favorites

Per league (`nfl`, `ncaa_fb`), under `filtering`:

| Option | Default | Description |
|--------|---------|-------------|
| `favorite_teams` | `[]` | Teams to follow — see [Dynamic Team Resolution](#-dynamic-team-resolution) |
| `exclude_teams` | `[]` | Teams to always hide from live rotation **and** recent/final scores (e.g. to avoid spoilers if you're watching delayed). Wins over every other setting below — an excluded team never shows up even if `show_all_live` is on. |
| `filtering.show_favorite_teams_only` | `true` | Only show games from favorite teams |
| `filtering.show_all_live` | `false` | Show all live games, not just favorites |
| `filtering.favorite_live_boost` | `2` | How many turns your favorite's live game gets in the rotation for every 1 turn other live games get. Your favorite's game is also always queued first whenever the live rotation refreshes. Set to `1` for perfectly even rotation. Only has a visible effect when more than one game is live at once and `favorite_teams` is configured. |

With both `show_favorite_teams_only` and `show_all_live` off, all live games rotate evenly — `favorite_live_boost` is what gives your favorite's game precedence in that mode without hiding everyone else's scores.

## 🎯 Which Games Get Shown

This trips people up, so it is worth being precise: **`upcoming_games_to_show` is not "how many cards you see".** It is the size of a *pool*. The panel cycles through that pool one card at a time (`upcoming_game_duration`, 15s by default), and it keeps its place between visits. So a pool of 3 means the board rotates through the same 3 games until the schedule moves on.

That is why making the number bigger does not help you see a particular team more often — a bigger pool means a *longer lap*, so any one game comes round **less** often.

### The three modes

Which mode you are in depends on two things: whether `favorite_teams` is set, and whether `filtering.show_favorite_teams_only` is on.

| `favorite_teams` | `show_favorite_teams_only` | What you get |
|---|---|---|
| empty | either | The next N games league-wide, chronologically. Every game shown is a non-favorite game, so the two filters below apply to all of them. |
| set | **on** | Only your teams. `upcoming_games_to_show` is a budget **per team**. |
| set | **off** | **Your teams first, then other games to fill.** Both limits are **totals**. |

The third row is the one most people actually want, and before v2.26.0 it did not exist — with the flag off, favorites were ignored *entirely* and you got the next N games league-wide. On a college slate that is ~950 upcoming games, so your team showed up about as often as chance allowed.

### The settings

Per league, under `game_limits`:

| Option | Default | Description |
|---|---|---|
| `upcoming_games_to_show` | `1` | How many **favorite** upcoming games to show (a total, not per team, when `show_favorite_teams_only` is off). |
| `recent_games_to_show` | varies | The same, for finished games. |
| `other_upcoming_games_to_show` | matches `upcoming_games_to_show` | How many **non-favorite** upcoming games to add. `0` gives you favorites only. |
| `other_recent_games_to_show` | matches `recent_games_to_show` | The same, for finished games. |
| `other_rotation_interval_seconds` | `1800` | How often the non-favorite slice advances. `0` pins it. |
| `other_games_min_quality` | `ranked` | Which non-favorite games qualify: `ranked`, `broadcast`, or `any`. |
| `other_games_divisions` | `["fbs"]` | Which divisions non-favorite games may come from: `fbs`, `fcs`, `other`. |

**Your favorite teams are never filtered by the last two.** Follow a Division II school and its games always appear, whatever the quality bar or division boxes say. Those settings only decide what fills the *remaining* slots.

### Variety comes from turnover, not from a bigger pool

Rather than widening the pool, the non-favorite slice **moves**. The window advances by its own width every `other_rotation_interval_seconds`, so consecutive windows do not overlap and the board works through the schedule instead of resampling the front of it.

Measured on a real board — favorites `UGA` + `AUB`, 3 others, rotating every 30 minutes:

```
  +  0 min: UNC@TCU, SJSU@USC, NCSU@UVA
  + 30 min: JVST@NDSU, SAC@EMU, HAW@STAN
  + 60 min: NMSU@FSU, MEM@UNLV, MASS@RUTG
  + 90 min: BCU@UCF,  AKR@WAKE, MRMK@DEL
```

18 different matchups over three hours, while the pool stays at 6 cards and a full lap still takes about 90 seconds of airtime.

Your favorites are **not** rotated. For upcoming games the soonest ones are the point — rotating them would show you a week-8 fixture instead of Saturday's.

### Keeping the filler out

Selection is otherwise purely chronological, and on a college slate most of what that returns is filler. Of ~950 upcoming games, roughly 250 involve a nationally ranked team; the rest are matchups most viewers have never heard of. Rotating harder just serves more of them, which is why `other_games_min_quality` defaults to `ranked`.

`other_games_divisions` uses **every** team in a game, not just the higher-division one. Leaving `fcs` unchecked therefore also hides a ranked team hosting an FCS school — which is usually what people mean by "show me FBS games". Check `fcs` or `other` if you want them back.

Both filters **fail open**: if rankings cannot be fetched, or the division rosters do not resolve, the game is allowed through. A board showing filler is a poor board; a board showing nothing is a broken one.

They fail open a second time, as a set: if the filters between them leave **nothing at all** — your teams idle and every other game rejected — the unfiltered list is used instead. Setting `other_upcoming_games_to_show` or `other_recent_games_to_show` to `0` is the one way to ask for an empty slate, and that is honoured.

> These two settings only mean something for `ncaa_fb`. The NFL has no poll and no divisions, so both are inert there and cost nothing — no poll is requested and no division lookup is made. College football is also the only league ESPN publishes FBS/FCS group rosters for at all, so `other_games_divisions` does nothing in the other sports plugins either.

### A worked example

Say you follow Georgia and Auburn and want to see their next games plus some variety:

```json
"ncaa_fb": {
  "favorite_teams": ["UGA", "AUB"],
  "filtering": { "show_favorite_teams_only": false },
  "game_limits": {
    "upcoming_games_to_show": 3,
    "other_upcoming_games_to_show": 3
  }
}
```

That gives 6 cards: the 3 soonest UGA/AUB games, plus 3 ranked FBS matchups that turn over every half hour.

> **Careful with `AP_TOP_25` / `AP_TOP_10` in `favorite_teams`.** They expand into real teams, so adding `AP_TOP_10` makes UGA and AUB 2 of 11 favorites — and your own teams then queue behind every top-10 game that kicks off earlier. On one real schedule, UGA's next game was favorite-game #5 and Auburn's was #8, so with `upcoming_games_to_show: 3` neither appeared. If you want your teams guaranteed, keep the favorites list to your teams and let `other_upcoming_games_to_show` supply the variety.


### Customization Options

- **Font Customization**: Adjust font family and size for:
  - Score text
  - Period/time text
  - Team names
  - Status text
  - Detail text (down/distance, etc.)
  - Ranking text

- **Layout Customization**: Fine-tune positioning with X/Y offsets for:
  - Team logos (home/away)
  - Score display
  - Status/period text
  - Date and time
  - Down & distance
  - Timeouts
  - Possession indicator
  - Records/rankings
  - Betting odds

### Timezone

- `timezone` (Advanced): IANA name used to display event start times, e.g.
  `America/Chicago`. Leave blank (the default) to follow the LEDMatrix global
  timezone; if that isn't set, the host system's timezone is used, and only if
  neither is available do times fall back to UTC.

  **Leftover `"UTC"` from an older version?** Before the write-back fix this
  plugin could persist `"timezone": "UTC"` into your saved config, where it
  then shadowed your real global timezone. That stale value is now detected
  and ignored automatically whenever your global or system timezone disagrees
  — no manual edit needed. If you genuinely want UTC here, set `Etc/UTC`,
  which is always honored.


## 🐛 Troubleshooting

### Common Issues
- **Start times look like UTC** (a 6:45pm Central start showing as 11:45PM):
  the plugin couldn't read your global timezone. Set `timezone` under the
  plugin's Advanced Settings to your IANA zone, e.g. `America/Chicago`.
- **No games showing**: Check if leagues are enabled and favorite teams are configured
- **Missing team logos**: Logos are automatically downloaded from ESPN API
- **Slow updates**: Adjust the `live_update_interval` in league configuration
- **API errors**: Check your internet connection and ESPN API availability
- **Dynamic teams not working**: Ensure you're using exact patterns like `AP_TOP_25`
- **Scroll mode not working**: Verify `scroll_display_mode` is set to "scroll" in config
- **Modes not appearing**: Check that specific modes (e.g., `nfl_live`) are enabled in display_modes settings


## 📊 Version History

### v2.0.7 (Current)
- ✅ **Granular Display Modes**: Independent control of NFL/NCAA FB live/recent/upcoming modes
- ✅ **Scroll Display Mode**: High-FPS horizontal scrolling of all games with league separators
- ✅ **Switch Display Mode**: One game at a time with timed transitions (default)
- ✅ **Font Customization**: Customize fonts and sizes for all text elements
- ✅ **Layout Customization**: Adjust X/Y positioning offsets for all display elements
- ✅ **Date Display**: Recent games show date underneath score
- ✅ Production-ready with real ESPN API integration
- ✅ Dynamic team resolution (AP_TOP_25, AP_TOP_10, AP_TOP_5)
- ✅ Real-time odds display with spread and over/under
- ✅ Nested configuration structure for better organization
- ✅ Full compatibility with LEDMatrix web UI
- ✅ Comprehensive error handling and caching
- ✅ Memory-optimized for Raspberry Pi deployment

### Previous Versions
- v2.0.6: Bug fixes and improvements
- v2.0.5: Production-ready release with ESPN API integration
- v2.0.4: Initial refactoring to reuse LEDMatrix core code
- v1.x: Original modular implementation

## 🤝 Contributing

This plugin is built on the proven LEDMatrix core codebase. For issues or feature requests, please use the GitHub issue tracker.

## 📄 License

This plugin follows the same license as the main LEDMatrix project.

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
