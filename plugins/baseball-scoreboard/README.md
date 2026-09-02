# Baseball Scoreboard

Live, recent, and upcoming baseball on your LED matrix across three leagues —
**MLB**, **MiLB** (Minor League Baseball), and **NCAA Baseball**. The live
screen is a real scorebug: the score, the inning and whether it's the top or
bottom, the bases, the outs, and the count.

![A live MLB game on a 128x32 panel: San Diego 3, Cincinnati 4, top of the 4th,
bases empty, two out](../../docs/assets/baseball-scoreboard/hero.png)

*Every image in this README is real plugin output, rendered at the true panel
size from a recorded ESPN response and then scaled up so the pixels stay pixels.
The live shot is an actual game in progress on 2 September 2026 — the score,
inning, bases, outs and count are what the panel showed at that moment.*

---

## Table of Contents

1. [What's On Screen](#whats-on-screen)
2. [Quick Start](#quick-start)
3. [Installation](#installation)
4. [Three Leagues, Three Config Blocks](#three-leagues-three-config-blocks)
5. [How Games Are Picked](#how-games-are-picked)
6. [Configuration Reference](#configuration-reference)
   - [Plugin-wide settings](#plugin-wide-settings)
   - [Per-league: teams and filtering](#per-league-teams-and-filtering)
   - [Per-league: display modes](#per-league-display-modes)
   - [Per-league: how many games](#per-league-how-many-games)
   - [Per-league: durations](#per-league-durations)
   - [Per-league: update intervals](#per-league-update-intervals)
   - [Per-league: background fetching](#per-league-background-fetching)
   - [Per-league: what appears on the card](#per-league-what-appears-on-the-card)
   - [The extra baseball screens](#the-extra-baseball-screens)
   - [The matchup card: separator, date and time](#the-matchup-card-separator-date-and-time)
   - [Favourite team result colours](#favourite-team-result-colours)
   - [Seeing live games more often in the Vegas ticker](#seeing-live-games-more-often-in-the-vegas-ticker)
   - [Fonts, colours and offsets](#fonts-colours-and-offsets)
7. [Team Abbreviations](#team-abbreviations)
8. [Panel Sizes](#panel-sizes)
9. [Troubleshooting](#troubleshooting)
10. [Development](#development)
11. [Support](#support)

---

## What's On Screen

Each league contributes three display modes, so the plugin exposes nine in
total — `mlb_live`, `mlb_recent`, `mlb_upcoming`, `milb_live`, `milb_recent`,
`milb_upcoming`, `ncaa_baseball_live`, `ncaa_baseball_recent` and
`ncaa_baseball_upcoming`. Every one can be enabled or disabled independently,
via the `show_live` / `show_recent` / `show_upcoming` flags inside that
league's `display_modes` block.

![The three MLB display modes on a 128x32 panel: a live scorebug, a final
score, and an upcoming game with its first-pitch
time](../../docs/assets/baseball-scoreboard/display-modes.png)

| Mode | Shows | Centre of the card |
|------|-------|--------------------|
| `*_live` | Games in progress | Inning with a top/bottom arrow, the bases diamond, outs, and the count |
| `*_recent` | Completed games | `Final`, the score, and the date |
| `*_upcoming` | Scheduled games | `Next Game`, the date and first pitch in your timezone |

Reading the live scorebug, from the hero image above:

```text
        ▲4        top of the 4th (▼ for the bottom)
   ●   ◇          bases: filled = runner on. The diamond is
   ●  ◇ ◇         second at the top, third left, first right
   ◌             outs: filled = out recorded, hollow = still to come
       3-3        the count, balls-strikes
```

The away team is always on the left and the home team on the right.

---

## Quick Start

The minimum useful configuration is one league and your teams:

```json
{
  "baseball-scoreboard": {
    "enabled": true,
    "mlb": {
      "enabled": true,
      "favorite_teams": ["STL", "LAD"]
    },
    "milb": { "enabled": false },
    "ncaa_baseball": { "enabled": false }
  }
}
```

Turning off the leagues you don't follow matters more here than in a
single-league plugin: each enabled league fetches on its own schedule, and
NCAA Baseball in particular is out of season for most of the year, so leaving
it on costs requests for screens that will never have anything to show.

---

## Installation

**From the Plugin Store (recommended).** Open the LEDMatrix web interface at
`http://<your-pi-ip>:5000`, go to **Plugin Manager**, find **Baseball
Scoreboard** in the **Plugin Store** section, and click **Install**. Its own tab
appears in the second nav row for configuring leagues and favourite teams.

**Manually.** Copy this directory into your LEDMatrix `plugins_directory`
(default `plugin-repos/`) and restart the display service. The plugin's
metadata, including the nine display modes it registers, lives in
`manifest.json`.

---

## Three Leagues, Three Config Blocks

This is the biggest structural difference from the single-league scoreboards.
Almost every setting lives **inside a league block**, not at the top level:

```json
{
  "baseball-scoreboard": {
    "enabled": true,
    "timezone": "America/Chicago",

    "mlb":           { "enabled": true,  "favorite_teams": ["STL"] },
    "milb":          { "enabled": true,  "favorite_teams": ["MEM"] },
    "ncaa_baseball": { "enabled": false }
  }
}
```

Only nine settings are plugin-wide — see
[Plugin-wide settings](#plugin-wide-settings). Everything else
(`favorite_teams`, `display_modes`, durations, update intervals, filtering,
game limits, display options) exists **once per league** and is configured
independently. Setting `favorite_teams` at the top level does nothing.

The practical consequence: if you follow one MLB team and one MiLB affiliate,
you set two separate `favorite_teams` lists, and you can give them different
durations and different filtering.

---

## How Games Are Picked

Selection runs per league, per mode, on every update. Which of three code paths
runs depends on two settings in that league's block: whether `favorite_teams`
is empty, and whether `filtering.show_favorite_teams_only` is on.

**1. No favourites** (`favorite_teams: []`) — the next *N* games league-wide,
sorted by time.

**2. Favourites, exclusively** (`show_favorite_teams_only: true`) — only games
involving your teams, with a per-team budget: each favourite gets up to
`game_limits.upcoming_games_to_show` games, and a game between two favourites
counts toward both.

**3. Favourites first, then others** (`show_favorite_teams_only: false`) — your
favourites' games first, then a top-up of `game_limits.other_upcoming_games_to_show`
non-favourite games, with the combined list re-sorted by start time so the
cards still read as a schedule. The non-favourite games come from a window that
advances every `other_rotation_interval_seconds` (default 30 minutes), so the
board works through the day rather than resampling the same handful.

**What the numbers mean changes with the path.** This is the single most
confusing thing in the configuration:

| Selection path | `upcoming_games_to_show` means |
|----------------|-------------------------------|
| No favourites | A **total** across the league |
| Favourites, exclusively | A budget **per favourite team** |
| Favourites first, then others | A **total** for the favourites portion only |

Three favourite teams with a value of `3` is up to nine cards in the exclusive
path and three in the others.

**And it is a pool size, not a card count.** This catches people out: the panel
shows one game at a time and keeps its place between visits, cycling through
the pool. So raising `upcoming_games_to_show` gives you a *longer lap* — any
one game comes round **less** often, not more. If you want your team's next
game on screen more, make the number smaller, not bigger.

### Which non-favourite games fill the remaining slots

Two settings decide what qualifies, and both have important limits in baseball:

| Option | Values | Reality in this plugin |
|--------|--------|------------------------|
| `other_games_min_quality` | `ranked`, `broadcast`, `any` | `ranked` needs a national poll. MLB and MiLB publish none, so it lets every game through and no poll is requested. It only bites for NCAA Baseball |
| `other_games_divisions` | e.g. `["fbs"]` | Needs ESPN's FBS/FCS group rosters, which exist for **college football and nothing else**. Inert here — no lookup is made |

**Your favourite teams are never filtered by either.** Follow a lower-division
side and its games always appear; these only decide what fills the *remaining*
slots.

Within the non-favourite pool the better matchup leads and each team appears
once: it is each team's *next* game, ordered by the best poll position of
either side, so a top-five matchup sits in the first window rather than
whichever starts soonest. Ties fall back to start time, and a league with no
poll — MLB, MiLB — simply stays chronological. Favourites are always ordered by
when they play; for your own team the next game is the point.

Both filters **fail open**. If the data behind them cannot be fetched the game
is allowed through, and if the filters between them leave nothing at all — your
teams idle and every other game rejected — the unfiltered list is used instead.
A board showing filler beats a board showing nothing. Setting
`other_upcoming_games_to_show` or `other_recent_games_to_show` to `0` is the
one way to ask for an empty slate, and that is honoured.

Two more rules that apply on top:

- `exclude_teams` beats everything — a team listed there is hidden from the
  live rotation and from finished scores even if it is also a favourite. That
  is what makes it useful for spoiler protection.
- If `show_favorite_teams_only` is `true` but `favorite_teams` is empty, the
  filter is skipped entirely and you get path 1. An empty favourites list never
  means "show nothing".

**Selection can only choose from games that were fetched.**
`schedule_lookback_days` (default `14`) and `schedule_lookahead_days`
(default `7`) bound the window. A fixture beyond the lookahead horizon cannot
appear no matter how high you set the limits.

### Live games

The live screen has its own selection. By default it shows only live games
involving your favourites; `filtering.show_all_live: true` includes every live
game. `filtering.favorite_live_boost` (default `2`) gives your team's game that
many turns per one turn for other live games, and queues it first when the
rotation refreshes. `live_priority` (default `false` here) lets a live game
interrupt the normal mode rotation.

`stale_game_timeout` (default `300`) drops a live game that has gone that long
without an update, which is what stops a suspended or abandoned game holding a
slot forever.

---

## Configuration Reference

Options marked **advanced** are behind the "advanced" toggle in the web UI and
are safe to ignore.

### Plugin-wide settings

These nine sit at the top level, outside any league block.

| Option | Default | What it does |
|--------|---------|--------------|
| `enabled` | `true` | Whether the plugin takes part in the rotation at all |
| `display_duration` | `30` | Seconds each mode holds the panel before the rotation moves on |
| `game_display_duration` | `15` | Seconds each individual game shows before the next one within the same mode |
| `update_interval` | `3600` | Base fetch interval |
| `timezone` | `""` | **Advanced.** IANA timezone for start times, e.g. `America/Chicago`. Blank follows the global LEDMatrix timezone, then the system one |

> **A leftover `"UTC"` from an older version?** This plugin used to persist
> `"timezone": "UTC"` into your saved config, where it then shadowed your real
> global timezone. That stale value is now detected and ignored automatically
> whenever your global or system timezone disagrees — no manual edit needed. If
> you genuinely want UTC here, set `Etc/UTC`, which is always honoured.
| `schedule_lookback_days` | `14` | **Advanced.** How far back the recent screens can see |
| `schedule_lookahead_days` | `7` | **Advanced.** How far ahead the upcoming screens can see |
| `no_data_interval_seconds` | `300` | **Advanced.** Gap between live checks when nothing is on, backing off the longer it stays quiet |
| `live_idle_max_interval_seconds` | `900` | **Advanced.** Ceiling for that back-off |

Baseball is a daily sport in season and dormant out of it, so the back-off pair
matters: out of season the plugin settles to one check every 15 minutes rather
than one every five.

### Per-league: teams and filtering

Set these inside `mlb`, `milb`, or `ncaa_baseball`.

| Option | Default | What it does |
|--------|---------|--------------|
| `enabled` | `true` | Whether this league is fetched and displayed at all |
| `favorite_teams` | `[]` | Team abbreviations, e.g. `["STL", "LAD"]` |
| `exclude_teams` | `[]` | Teams to always hide, from live *and* finished scores |
| `filtering.show_favorite_teams_only` | `true` | Restrict to games involving `favorite_teams` |
| `filtering.show_all_live` | `false` | Show every live game, not just favourites' |
| `filtering.favorite_live_boost` | `2` | **Advanced.** Turns your favourite's live game gets per turn for others |

Abbreviations are ESPN's, not the club name — `STL`, `LAD`, `NYY`, `SD`, `CIN`.
If you are unsure of one, enable debug logging and the plugin logs
`home_abbr` and `away_abbr` for every game it processes.

### Per-league: display modes

| Option | Default | What it does |
|--------|---------|--------------|
| `display_modes.show_live` | `true` | Enable this league's live screen |
| `display_modes.show_recent` | `true` | Enable its recent screen |
| `display_modes.show_upcoming` | `true` | Enable its upcoming screen |
| `display_modes.live_display_mode` | `switch` | `switch` = one full-screen game at a time; `scroll` = all games scrolling sideways |
| `display_modes.recent_display_mode` | `switch` | As above, for recent |
| `display_modes.upcoming_display_mode` | `switch` | As above, for upcoming |

Every screenshot in this README is `switch` mode. `scroll` draws a compact card
per game and scrolls the strip, which fits more games on a long panel at the
cost of size; the `scroll_card` and `scroll_settings` groups only affect it.

### Per-league: how many games

| Option | Default | What it does |
|--------|---------|--------------|
| `game_limits.recent_games_to_show` | `5` | Finished games — see [what the numbers mean](#how-games-are-picked) |
| `game_limits.upcoming_games_to_show` | `1` | Scheduled games — same caveat |
| `game_limits.other_recent_games_to_show` | `5` | **Advanced.** Non-favourite finished games, in the favourites-first path |
| `game_limits.other_upcoming_games_to_show` | `1` | **Advanced.** Non-favourite scheduled games, same path |
| `game_limits.other_rotation_interval_seconds` | `1800` | **Advanced.** How often the non-favourite window advances |
| `game_limits.other_games_min_quality` | `ranked` | **Advanced.** Which non-favourite games earn a slot. Meaningful for NCAA, where a national ranking exists |
| `game_limits.other_games_divisions` | `["fbs"]` | **Advanced.** Divisions non-favourite games may come from. NCAA only |

Note the asymmetric defaults: five recent games but one upcoming. That suits
baseball's daily schedule — yesterday produced a full slate of finals worth
rotating through, while "the next game" is usually the only upcoming one you
care about.

### Per-league: durations

| Option | Default | What it does |
|--------|---------|--------------|
| `live_game_duration` | `30` | Seconds per live game before rotating to the next |
| `non_favorite_live_game_duration` | `0` | **Advanced.** Separate, usually shorter duration for live games with no favourite in them. `0` means "use `live_game_duration` for everything" |
| `recent_game_duration` | `15` | **Advanced.** Seconds per finished game |
| `upcoming_game_duration` | `15` | **Advanced.** Seconds per scheduled game |
| `live_priority` | `false` | Let a live game in this league interrupt the normal rotation |
| `mode_durations.*` | `null` | **Advanced.** Fixed total duration for a whole mode, overriding the per-game maths |
| `dynamic_duration.enabled` | `false` | **Advanced.** Size a mode's duration from how many games it actually has |

`non_favorite_live_game_duration` is the setting for a full slate: with fifteen
games on at once, `live_game_duration: 30` and
`non_favorite_live_game_duration: 8` keeps your club's game on screen while the
rest still tick past.

It only takes effect when favourites are configured **and** non-favourite live
games are actually being shown — otherwise there is nothing on screen to
shorten:

| Favourites set? | Non-favourite games shown? | Game has a favourite? | Duration used |
|---|---|---|---|
| No | — | — | `live_game_duration` |
| Yes | No (`show_favorite_teams_only` on, `show_all_live` off) | yes | `live_game_duration` |
| Yes | Yes (`show_favorite_teams_only` off, or `show_all_live` on) | yes | `live_game_duration` |
| Yes | Yes | no | `non_favorite_live_game_duration`, when above `0` |

### Per-league: update intervals

All **advanced**. The defaults are tuned for a Raspberry Pi that is also driving
a panel.

| Option | Default | What it does |
|--------|---------|--------------|
| `live_update_interval` | `30` | How often live game data is refreshed |
| `recent_update_interval` | `3600` | How often the finished-games list is rebuilt |
| `upcoming_update_interval` | `3600` | How often the upcoming list is rebuilt |
| `update_interval_seconds` | `3600` | Base fetch interval for this league |
| `stale_game_timeout` | `300` | How long a live game may go without an update before it is dropped |

### Per-league: background fetching

Data is fetched on a background thread so the panel never stalls on the
network. Under each league's `background_service`, all **advanced**:

| Option | Default | What it does |
|--------|---------|--------------|
| `enabled` | `true` | Fetch in the background rather than inline |
| `request_timeout` | `30` | Seconds before a request gives up |
| `max_retries` | `3` | Retries per failed request |
| `priority` | `2` | Queue priority against other plugins' fetches (medium) |

---

### Per-league: what appears on the card

| Option | Default | What it does |
|--------|---------|--------------|
| `display_options.show_records` | `false` | **Advanced.** Each team's win-loss record in the bottom corners |
| `display_options.show_odds` | `true` | Draw the betting line when ESPN has one |
| `display_options.show_ranking` | `false` | **Advanced.** Rank badge. Meaningful for NCAA; MLB and MiLB publish no poll |
| `display_options.show_series_summary` | `false` | **Advanced.** Where the teams stand in the current series |

![The same finished game with show_records off and on; with it on, 69-70 and
82-56 appear in the bottom corners](../../docs/assets/baseball-scoreboard/show-records.png)

`show_odds` is not shown here because it cannot be captured in a still: odds
are fetched asynchronously on a background thread after the card is first
drawn, so the line appears a moment later, once the fetch returns. That also
means it costs an extra request per selected game — worth turning off if you
do not want the line.

### The extra baseball screens

Baseball has more to say than most sports mid-at-bat, so the plugin can
periodically take over with a dedicated screen. All are **off by default** and
all cost an extra per-game data fetch.

| Option | Default | What it does |
|--------|---------|--------------|
| `display_options.show_pitcher_batter` | `false` | A screen naming the current pitcher and batter during a live at-bat |
| `display_options.show_last_play` | `false` | Adds a short code for the last completed play (`1B`, `HR`, `K`, `BB`) to that screen |
| `display_options.show_player_card` | `false` | A full card for the current batter: headshot, number, position, bat/throw and season stats |
| `display_options.show_traditional_scoreboard` | `false` | A full-screen ballpark scoreboard: inning-by-inning line score, R/H/E, and an at-bat panel |

`show_last_play` only does anything with `show_pitcher_batter` on — it adds a
field to that screen rather than being a screen of its own.

**All four are MLB and NCAA Baseball only.** MiLB's data does not come from
ESPN in the same shape, so the flags exist under `milb.display_options` but
nothing is wired up behind them. The pitcher/batter and player-card screens are
additionally **live-games only**, since the current at-bat is the data they are
built from; only the traditional scoreboard has a `game_scope` option, because
only it has anything to say about a finished game.

They also need panel height. The traditional scoreboard wants 64 rows or more
for a line score; the player card hides the headshot and falls back to a
compact two-line text card on a 64×32 panel.

#### Traditional scoreboard: `customization.traditional_scoreboard`

A full-screen ballpark scoreboard — inning-by-inning line score with R/H/E, the
current inning highlighted, and a lit ball/strike/out column during a live
at-bat. It is not a display mode you select: it periodically *rotates into*
whichever game the normal rotation is already showing, then reverts.

| Option | Default | What it does |
|--------|---------|--------------|
| `game_scope` | `both` | `live`, `recent`, or `both`. `recent` is the "glance at the final line score" setting |
| `favorites_only` | `false` | Only rotate in for games involving this league's `favorite_teams`. Independent of the normal rotation's filtering, so you can watch every live game in the compact scorebug but reserve the full-screen treatment for your team |
| `dwell_seconds` | `6` | How long it stays each time it rotates in |
| `interval_seconds` | `30` | How often it rotates in |
| `font` | `9x15.bdf` | A fixed-size `.bdf` renders at its native pixel size with a smaller-sibling fallback; use a scalable `.ttf` (e.g. `press_start`) if you want `font_size` to control the size |
| `font_size` | `24` | Cap for scalable fonts only; ignored by `.bdf`. The screen auto-fits, so the default means "as big as the panel allows" |
| `use_team_colors` | `true` | Colour each abbreviation with the team's real ESPN colours instead of flat `text_color` |
| `show_team_color_backgrounds` | `true` | Tint each row with a ~12% wash of the team's colour plus an accent strip. Requires `use_team_colors` |
| `show_logos` | `true` | Small team logo beside each abbreviation when there is spare width |
| `show_dividers` | `true` | 1px grid lines between innings, rows and the R/H/E columns |
| `highlight_winner` | `true` | On a final game, colour the winner's run total in `winner_color`. Pairs with `game_scope: recent` |
| `text_color` | `[255, 255, 255]` | Score digits, and abbreviations when team colours are off |
| `header_color` | `[180, 180, 180]` | The inning-number and R/H/E header row |
| `highlight_color` | `[255, 140, 0]` | Current-inning highlight, the batting-team arrow, and lit ball/strike/out indicators |
| `divider_color` | `[90, 90, 90]` | The grid lines |
| `winner_color` | `[0, 200, 0]` | The winning team's run total on a final game |

```json
{
  "mlb": { "display_options": { "show_traditional_scoreboard": true } },
  "customization": {
    "traditional_scoreboard": { "game_scope": "recent", "favorites_only": true }
  }
}
```

#### Pitcher / batter: `customization.at_bat_info`

Names the current at-bat's pitcher and batter, labelled in full
(`Pitcher: G. Cole` / `Batter: J. Soto`) so there is no confusing the `B` with
the balls indicator. Text auto-fits, falling back to a smaller font — and only
as a last resort truncating — rather than running off the edge.

| Option | Default | What it does |
|--------|---------|--------------|
| `favorites_only` | `false` | Only rotate in for favourites' games |
| `dwell_seconds` | `4` | How long it stays |
| `interval_seconds` | `25` | How often it rotates in |
| `font` | `9x15.bdf` | As above |
| `font_size` | `24` | Cap for scalable fonts only |
| `use_team_colors` | `true` | Pitcher in the fielding team's colour, batter in the batting team's |
| `pitcher_color` | `[255, 255, 255]` | Fallback when team colours are off |
| `batter_color` | `[255, 255, 0]` | Fallback when team colours are off |
| `last_play_color` | `[0, 255, 255]` | The last-play code — always flat, since a play code belongs to no team |

#### Player card

A "baseball card" for the current batter, and optionally the pitcher: headshot,
jersey number, position, bat/throw, and season stats (`AVG`/`HR`/`RBI` for
hitters, `ERA`/`W-L`/`K` for pitchers). Headshots come from ESPN's athlete API
and are cached in memory and on disk under `assets/headshots/`, which is
gitignored. If a headshot cannot be loaded the card renders text-only.

Under `customization.player_card`:

| Option | Default | What it does |
|--------|---------|--------------|
| `show_batter` | `true` | A card for the current batter |
| `show_pitcher` | `false` | Also a card for the pitcher. The batter wins when both are available |
| `favorites_only` | `false` | Only rotate in for favourites' games |
| `dwell_seconds` | `6` | How long the card stays |
| `interval_seconds` | `40` | How often it rotates in |
| `font` / `font_size` | `9x15.bdf` / `24` | As for the other screens; the cap applies to scalable fonts only |
| `use_team_colors` | `true` | The player's name in their team's ESPN colour |
| `use_team_colors_border` | `true` | The headshot frame in the team's colour |
| `border_color` | `[255, 200, 0]` | Frame colour when the team colour is off or unavailable |
| `text_color` | `[255, 255, 255]` | Name and the jersey/position/bat-throw line |
| `stat_color` | `[0, 220, 255]` | The season-stats line |

### The matchup card: separator, date and time

The **Matchup Card Layout** group (`scroll_card`, advanced) controls what sits
between the two logos before a game starts and how the date and time are
written. It applies to every display mode — the scroll ticker, the Vegas ticker
and the full-screen scoreboard.

| Key | Default | Values |
|-----|---------|--------|
| `vs_text` | `VS` | Any short string: `VS`, `@`, `at`, `v`. The away team is on the left, so `@` and `at` read as "away at home". Blank draws nothing |
| `upcoming_center` | `vs` | Scroll and Vegas cards: `vs`, `date_time`, `none` |
| `switch_upcoming_center` | `date_time` | The full-screen scoreboard: `date_time`, `vs`, `none`, `inherit` |
| `date_format` | `abbrev` | Scroll and Vegas: `abbrev` (Sep 19), `numeric` (9/19), `day_first` (19 Sep), `numeric_day_first` (19/9), `weekday` (Fri Sep 19) |
| `switch_date_format` | `numeric` | The same set for the full-screen scoreboard, plus `inherit` |
| `time_format` | `12h` | `12h` (7:40PM) or `24h` (19:40) |
| `show_date` / `show_time` | `true` | Drop either line |
| `swap_date_time` | `false` | Swap the two lines. Each display starts from its own order, so this flips rather than forces: cards put the time on top, the full-screen stack puts the date on top |

The two `*_date_format` keys have different defaults on purpose: the cards have
always written `Sep 19` and the full-screen scoreboard `9/19`, so one shared
default would have restyled one of them.

Choosing the separator for the full-screen scoreboard moves the date and time
out of the middle and onto the top and bottom rows, and the "Next Game" header
gives up the top row to them. The `center_gap*` keys size the scroll and Vegas
card's middle strip only — the full-screen scoreboard pins its logos to the
panel edges and ignores them.

```json
{
  "scroll_card": {
    "vs_text": "@",
    "switch_upcoming_center": "vs",
    "date_format": "weekday"
  }
}
```

### Favourite team result colours

A run of games against the same opponent is hard to read at a glance: the same
two logos go past and only the digits change. Turn this on to colour a finished
game's score by how your team did — green for a win, red for a loss.

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

Off by default. Only *finished* games are coloured — live and upcoming cards are
untouched — and a game needs exactly one favourite in it: if neither side is a
favourite, or both are, the score keeps its normal colour. The three colours are
advanced settings; leave them alone for the defaults above.

### Seeing live games more often in the Vegas ticker

By default a live game **takes over** the display: the Vegas ticker stops and
this scoreboard goes full screen until the game ends. To keep the marquee
scrolling and still see scores, the settings live in the **core** LEDMatrix
config rather than in this plugin:

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
cycle — so with a dozen plugins a score comes round once a lap. `live_weight`
applies whenever this scoreboard has any live game; `favorite_live_weight`
applies when one of your teams is playing, a distinction that has to be made
here because the core can tell *that* a game is live but not *whose*.

The weight is per **plugin**, not per game: with fifteen games live this
scoreboard still occupies one slot at a time and picks between its own games
using `filtering.favorite_live_boost`. And more slots make the cycle *longer*,
not faster — everything else appears proportionally less often.

### Fonts, colours and offsets

`customization` restyles each text element independently, and is plugin-wide
rather than per-league. Each group takes `font`, `font_size` and `text_color`,
and the colour applies to the text drawn in that element's face on the
full-screen scoreboard and on the scroll and Vegas cards alike.

| Group | Covers |
|-------|--------|
| `score_text` | The score, and the matchup separator on an upcoming card |
| `period_text` | The clock, the inning, and the date and time on an upcoming scoreboard |
| `team_name` | Team names and abbreviations |
| `status_text` | Status lines such as "Next Game" |
| `detail_text` | Small detail lines |
| `rank_text` | Team rankings |

Colours are `[r, g, b]` or `"#RRGGBB"`, and every default is white:

```json
{
  "customization": {
    "score_text": { "font_size": 12, "text_color": [255, 220, 0] }
  }
}
```

`customization.layout` nudges individual elements by `x_offset` / `y_offset`
for panels where something sits slightly wrong.

---

## Team Abbreviations

`favorite_teams` and `exclude_teams` take ESPN's abbreviation, not the club
name. If you are unsure of one, enable debug logging — the plugin logs
`home_abbr` and `away_abbr` for every game it processes.

**MLB.** `ARI` `ATL` `BAL` `BOS` `CHC` `CHW` `CIN` `CLE` `COL` `DET` `HOU`
`KC` `LAA` `LAD` `MIA` `MIL` `MIN` `NYM` `NYY` `OAK` `PHI` `PIT` `SD` `SEA`
`SF` `STL` `TB` `TEX` `TOR` `WAS`

**NCAA Baseball.** `LSU` `FLA` `VANDY` `ARK` `MISS` `TAMU` `TENN` `UK` `UGA`
`BAMA` `AUB` `SCAR` `CLEM` `FSU` `MIA` `UNC` `DUKE` `WAKE` `VT` `LOU`, among
many others.

**MiLB.** Abbreviations vary by league and level (AAA, AA, A+, A) — for example
`DUR` (Durham Bulls), `SWB` (Scranton/Wilkes-Barre RailRiders), `MEM` (Memphis
Redbirds). The debug-log trick is the reliable way to find an affiliate's code.

---

## Panel Sizes

The scoreboard lays itself out from the panel dimensions rather than assuming a
size.

![The same live game rendered on 64x32, 128x32, 128x64 and 256x32
panels](../../docs/assets/baseball-scoreboard/panel-sizes.png)

- **64×32** is tight for baseball specifically: the bases diamond, outs and
  count all compete for the centre with the score. It works, but a wider panel
  is much easier to read across a room.
- **128×32** is the size everything is tuned for.
- **128×64** gives the scorebug room and is what the traditional scoreboard and
  player-card screens want.
- **256×32** keeps element sizes and centres them, so a long chain buys width
  rather than a bigger scoreboard — `scroll` mode is what makes a long panel
  pay off.

---

## Troubleshooting

**Nothing shows for a league I enabled.**
Check that league's `display_modes` — all three can be off. Then check whether
the league is in season: NCAA Baseball runs roughly February to June, and MiLB
finishes before MLB does.

**The upcoming screen is empty but I know there are games.**
`schedule_lookahead_days` defaults to `7`; during an All-Star break or between
series the next fixture can sit beyond it. The other common cause is
`show_favorite_teams_only: true` with favourites who are not playing.

**I see far more games than I asked for.**
`upcoming_games_to_show` is a *per-team* budget when `show_favorite_teams_only`
is on. See [How Games Are Picked](#how-games-are-picked).

**My settings seem to be ignored.**
Check they are inside the league block. `favorite_teams` at the top level does
nothing — it has to be `mlb.favorite_teams`. See
[Three Leagues, Three Config Blocks](#three-leagues-three-config-blocks).

**Start times are wrong by hours.**
Set `timezone`. ESPN reports first pitch in UTC and the plugin converts on
display.

**A team shows as a grey box instead of a logo.**
Logos are downloaded on demand and cached. A failed download used to be cached
permanently; on a current core it is retried automatically after six hours. If
you are on an older core, delete the undersized file (a real logo is tens of
kilobytes) and restart.

**The pitcher/batter or player-card screen never appears.**
Both need an extra per-game fetch and only appear during a live at-bat. They
also need panel height — check a 128×64 panel before concluding they are
broken.

---

## Development

### File structure

```text
baseball-scoreboard/
├── manifest.json                  # Metadata and version history
├── manager.py                     # BaseballScoreboardPlugin: league and mode routing
├── mlb_managers.py                # MLB fetching and cache keys
├── milb_managers.py               # MiLB fetching
├── ncaa_baseball_managers.py      # NCAA fetching
├── sports.py                      # Shared sports engine: selection, extraction, rendering
├── logo_manager.py                # Logo loading and download
├── config_schema.json             # Settings schema; source of truth for defaults
└── test_*.py                      # Standalone regression tests
```

`sports.py` and the other shared files are **copies** carried by every sports
scoreboard in this monorepo. A fix in one must be ported to its siblings in the
same change — see
[docs/plugin-development/08-shared-sports-code.md](../../docs/plugin-development/08-shared-sports-code.md).

### Data source

ESPN's public scoreboard APIs for `baseball/mlb`,
`baseball/college-baseball` and the MiLB feeds. No API key required.

One wrinkle worth knowing if you are testing: the recent and upcoming managers
read through the cache, but the live manager calls
`_fetch_todays_games()` straight over HTTP with no cache read. Seeded cache
fixtures therefore cannot drive the live screen.

### Regenerating the images in this README

```bash
python scripts/render_docs_assets.py --plugin baseball-scoreboard
```

The fixtures under `docs/assets/baseball-scoreboard/fixtures/` are real ESPN
responses captured on 2 September 2026. Because the live manager bypasses the
cache, its screen is fed by a **recorded HTTP response** rather than seeded
cache data — that is what `http_replay` in `shots.json` does. The result is
real data that re-renders identically every time, which
`--check` verifies.

---

## Support

- YouTube: <https://www.youtube.com/@ChuckBuilds>
- Instagram: <https://www.instagram.com/ChuckBuilds/>
- Discord: <https://discord.com/invite/uW36dVAtcT>
- Sponsor: [GitHub Sponsors](https://github.com/sponsors/ChuckBuilds) ·
  [Buy Me a Coffee](https://buymeacoffee.com/chuckbuilds) ·
  [Ko-fi](https://ko-fi.com/chuckbuilds/)

Released under the GNU General Public License v3.0 — see [LICENSE](LICENSE).
