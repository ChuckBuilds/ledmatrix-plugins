# AFL Scoreboard

Live, recent, and upcoming **AFL (Australian Football League)** games on your LED
matrix — real-time scores, the quarter and running clock, club logos, and start
times in your own timezone.

![Carlton 74 def. Melbourne 55, shown on a 128x32 panel with both club logos and
the match date](../../docs/assets/afl-scoreboard/hero.png)

*Every image in this README is real plugin output, rendered at the true panel
size from archived ESPN data and then scaled up so the pixels stay pixels.
Nothing here is a mockup — the scores, logos, records and start times are the
real 2026 finals series.*

---

## Table of Contents

1. [What's On Screen](#whats-on-screen)
2. [Installation](#installation)
3. [Quick Start](#quick-start)
4. [How Games Are Picked](#how-games-are-picked)
   - [The three selection modes](#the-three-selection-modes)
   - [What the "games to show" numbers mean](#what-the-games-to-show-numbers-mean)
   - [Which games exist to pick from](#which-games-exist-to-pick-from)
   - [Live games and priority](#live-games-and-priority)
   - [Seeing live games more often in the Vegas ticker](#seeing-live-games-more-often-in-the-vegas-ticker)
5. [Configuration Reference](#configuration-reference)
   - [Teams and filtering](#teams-and-filtering)
   - [Display modes and rotation](#display-modes-and-rotation)
   - [How long things stay on screen](#how-long-things-stay-on-screen)
   - [How often data is fetched](#how-often-data-is-fetched)
   - [What appears on the card](#what-appears-on-the-card)
   - [Card layout and text](#card-layout-and-text)
   - [Celebrations](#celebrations)
   - [Fonts, colours and offsets](#fonts-colours-and-offsets)
   - [Timezone](#timezone)
6. [Panel Sizes](#panel-sizes)
7. [Team Abbreviations](#team-abbreviations)
8. [Known Limitations](#known-limitations)
9. [Troubleshooting](#troubleshooting)
10. [Development](#development)
11. [Support](#support)

---

## What's On Screen

The plugin provides three display modes. Each is a separate entry in your
LEDMatrix rotation, and each can be turned on or off independently.

![The three display modes on a 128x32 panel: afl_live showing Q3 and a running
score, afl_recent showing a final score, afl_upcoming showing a date and start
time](../../docs/assets/afl-scoreboard/display-modes.png)

| Mode | Shows | Status area |
|------|-------|-------------|
| `afl_live` | Games in progress | `Q1`–`Q4` plus the running clock, or `HALF` at the main break |
| `afl_recent` | Completed games | `Final`, the score, and the match date |
| `afl_upcoming` | Scheduled games | The date and start time, in your timezone |

The away team's logo is always on the left and the home team's on the right, so
a separator like `at` or `@` reads correctly as "away at home".

---

## Installation

**From the Plugin Store (recommended).** Open the LEDMatrix web interface at
`http://<your-pi-ip>:5000`, go to **Plugin Manager**, find **AFL Scoreboard**
in the **Plugin Store** section, and click **Install**.

**Manually.** Copy this directory into your LEDMatrix `plugins_directory`
(default `plugin-repos/`) and restart the display service.

---

## Quick Start

The minimum useful configuration is your teams:

```json
{
  "afl-scoreboard": {
    "enabled": true,
    "favorite_teams": ["CARL", "GEEL"]
  }
}
```

A fuller example — favourites first, but other games still get a look in:

```json
{
  "afl-scoreboard": {
    "enabled": true,
    "favorite_teams": ["CARL", "GEEL"],
    "show_favorite_teams_only": false,
    "upcoming_games_to_show": 2,
    "other_upcoming_games_to_show": 2,
    "recent_games_to_show": 2,
    "timezone": "Australia/Melbourne",
    "show_odds": false,
    "display_modes": {
      "live": true,
      "recent": true,
      "upcoming": true,
      "live_display_mode": "switch",
      "recent_display_mode": "switch",
      "upcoming_display_mode": "switch"
    },
    "customization": {
      "favorite_result_colors": { "enabled": true }
    }
  }
}
```

You can set all of this from the web UI instead — the settings form is generated
from `config_schema.json`, which is the source of truth for every default listed
below.

---

## How Games Are Picked

This is the part that surprises people, so it is worth reading once. The plugin
does not simply show "the next game". It runs a selection pass every update,
separately for each mode, and which of three code paths it takes depends
entirely on two settings: whether `favorite_teams` is empty, and whether
`show_favorite_teams_only` is on.

### The three selection modes

**1. No favourites configured** (`favorite_teams: []`)

The next *N* games league-wide, sorted by start time. `N` is
`upcoming_games_to_show` (or `recent_games_to_show` for the recent screen).
Simple, and the right setting for a neutral scoreboard.

**2. Favourites, exclusively** (`favorite_teams` set, `show_favorite_teams_only: true`)

Only games involving your teams. The plugin walks the schedule in time order and
keeps a per-team counter: each favourite team gets up to `upcoming_games_to_show`
games. A game between two of your favourites counts toward **both** teams'
budgets. Once every favourite team has hit its budget, selection stops early.

**3. Favourites first, then others** (`favorite_teams` set, `show_favorite_teams_only: false`)

This is the middle setting most people actually want. Your favourites' games are
taken first — up to `upcoming_games_to_show` of them — and then the list is
topped up with `other_upcoming_games_to_show` non-favourite games. The combined
list is then **re-sorted by start time**, so the cards still read as a schedule:
tonight's neutral game appears before next week's game involving your club.

The non-favourite games are not the same handful every time. They come from a
window that advances through the schedule every
`other_rotation_interval_seconds` (default 30 minutes), so over an evening the
board works through the round rather than resampling the front of it. Set
`other_upcoming_games_to_show: 0` to get favourites only while still leaving
`show_favorite_teams_only` off.

> **Edge case worth knowing.** If `show_favorite_teams_only` is `true` but
> `favorite_teams` is empty, the favourites filter is skipped entirely and you
> get mode 1 — every game. An empty favourites list never means "show nothing".

### Two settings that do nothing in this league

`other_games_min_quality` and `other_games_divisions` filter which *non-favourite*
games earn a slot in the favourites-first path. Both come from the shared sports
engine, and neither has anything to work with here:

- `other_games_min_quality: "ranked"` needs a national poll. The AFL publishes
  none, so the filter lets every game through and no poll is requested.
- `other_games_divisions: ["fbs"]` needs ESPN's FBS/FCS group rosters, which
  exist for **college football and nothing else**. Asked for any other league
  they come back empty, so no lookup is made.

Your favourite teams are never filtered by either setting in any case — they
only decide what fills the remaining slots. Leave both at their defaults.

Both filters also **fail open**: if the data behind them cannot be fetched the
game is allowed through, and if they would between them leave nothing at all,
the unfiltered list is used instead. Setting `other_upcoming_games_to_show` to
`0` is the one way to ask for favourites only, and that is honoured.

### What the "games to show" numbers mean

`upcoming_games_to_show` and `recent_games_to_show` change meaning depending on
which selection mode you are in. This is the single most confusing thing in the
plugin's configuration:

| Selection mode | `upcoming_games_to_show` means |
|----------------|-------------------------------|
| No favourites | A **total** across the league |
| Favourites, exclusively | A budget **per favourite team** |
| Favourites first, then others | A **total** for the favourites portion only |

So with three favourite teams and `upcoming_games_to_show: 3`, exclusive mode
can produce up to nine cards, while the other two modes produce three.

**And it is a pool size, not a card count.** The panel shows one game at a time
and keeps its place between visits, cycling through the pool. Raising
`upcoming_games_to_show` therefore gives you a *longer lap* — any one game comes
round **less** often, not more. To see your team's next game more, make the
number smaller.

`exclude_teams` is applied on top of all of this and beats everything — a team
listed there is hidden from the live rotation and from recent scores even if it
is also a favourite. That is what makes it useful for spoiler protection.

### Which games exist to pick from

Selection can only choose from games the plugin actually fetched. The fetch
window is controlled by two settings:

- `schedule_lookback_days` (default `14`) — how far back the recent screen can see.
- `schedule_lookahead_days` (default `7`) — how far ahead the upcoming screen can see.

A fixture beyond the lookahead horizon is never fetched, so it cannot appear no
matter how high you set `upcoming_games_to_show`. If your upcoming screen looks
empty during a bye or between finals weeks, this is usually why — raise
`schedule_lookahead_days`.

### Live games and priority

The live screen has its own selection:

- By default it shows only live games involving your favourite teams. Set
  `filtering.show_all_live: true` to include every live game regardless.
- `filtering.favorite_live_boost` (default `2`) gives your favourite's live game
  that many turns in the live rotation for every one turn another live game
  gets, and queues it first whenever the rotation refreshes. Set it to `1` for
  an even rotation.
- `live_priority` (default `true`) lets a live game interrupt the normal mode
  rotation rather than waiting its turn.

### Seeing live games more often in the Vegas ticker

By default a live game **takes over** the display: the Vegas ticker stops and
this scoreboard goes full screen until the game ends. If you would rather keep
the marquee scrolling and still see scores, the relevant settings live in the
**core** LEDMatrix config rather than in this plugin:

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
weights let this scoreboard claim several slots per cycle, spaced evenly through
it rather than bunched together.

`live_weight` applies whenever this scoreboard has any live game.
`favorite_live_weight` applies when one of your `favorite_teams` is playing, so
your club's game comes round more often than other live games. That distinction
has to be made here rather than in the core, which can tell *that* a game is
live but not *whose*.

Two things to keep in mind:

- The weight is per **plugin**, not per game. With four games live this
  scoreboard still occupies one slot at a time and picks between its own games
  using `filtering.favorite_live_boost`; these weights control how often the
  scoreboard itself comes round.
- More slots make the cycle **longer**, not faster — everything else appears
  proportionally less often. And appearing more often only helps if the data is
  fresh, which is governed by `live_update_interval` above.

---

## Configuration Reference

Every option below is real and read by the plugin unless explicitly marked
otherwise. Options marked **advanced** are hidden behind the "advanced" toggle
in the web UI; they are safe to ignore.

### Teams and filtering

| Option | Default | What it does |
|--------|---------|--------------|
| `enabled` | `true` | Whether the plugin takes part in the rotation at all |
| `favorite_teams` | `[]` | Team abbreviations to prioritise, e.g. `["CARL", "GEEL"]`. See [Team Abbreviations](#team-abbreviations) |
| `exclude_teams` | `[]` | Teams to always hide, from live *and* recent screens. Beats `favorite_teams` and `show_all_live` |
| `show_favorite_teams_only` | `true` | Restrict to games involving `favorite_teams`. See [the three selection modes](#the-three-selection-modes) |
| `filtering.show_all_live` | `false` | Show every live game, not just favourites' |
| `filtering.favorite_live_boost` | `2` | **Advanced.** Turns your favourite's live game gets per turn for other live games |

`favorite_teams` also does more than filter. It decides whose result the
[favourite result colours](#what-appears-on-the-card) apply to, and which team's
score triggers a [celebration](#celebrations).

> **A default worth checking.** The schema default for
> `show_favorite_teams_only` is `true`, which is what the web UI shows and what a
> store install gets. If you hand-write `config.json` and leave the key out
> entirely, the plugin's own fallback is `false` instead. Set it explicitly if
> you edit config by hand.

### Display modes and rotation

| Option | Default | What it does |
|--------|---------|--------------|
| `display_modes.live` | `true` | Enable the live screen |
| `display_modes.recent` | `true` | Enable the recent screen |
| `display_modes.upcoming` | `true` | Enable the upcoming screen |
| `display_modes.live_display_mode` | `switch` | `switch` = one full-screen game at a time; `scroll` = all games scrolling horizontally |
| `display_modes.recent_display_mode` | `switch` | As above, for recent games |
| `display_modes.upcoming_display_mode` | `switch` | As above, for upcoming games |
| `live_priority` | `true` | Let live games interrupt the normal rotation |

**`switch` vs `scroll`.** Switch mode is the full-screen scoreboard shown
throughout this README: two large logos with the score or start time between
them. Scroll mode instead draws a compact card per game and scrolls the whole
strip sideways, which fits more games on a long panel at the cost of size. The
`scroll_card` and `scroll_settings` groups only affect scroll mode, except for
the handful of `switch_*` keys called out below.

### How long things stay on screen

| Option | Default | What it does |
|--------|---------|--------------|
| `display_duration` | `15` | Seconds each mode holds the panel |
| `live_game_duration` | `20` | Seconds per live game before rotating to the next |
| `recent_game_duration` | `15` | **Advanced.** Seconds per recent game |
| `upcoming_game_duration` | `15` | **Advanced.** Seconds per upcoming game |
| `game_display_duration` | `15` | **Advanced.** Generic per-game duration within a mode |
| `non_favorite_live_game_duration` | `0` | **Advanced.** Separate, usually shorter duration for live games with no favourite in them. `0` means "use `live_game_duration` for everything" |
| `mode_durations.live_mode_duration` | `null` | **Advanced.** Fixed total duration for the whole live mode, overriding the per-game maths |
| `mode_durations.recent_mode_duration` | `null` | **Advanced.** As above, for recent |
| `mode_durations.upcoming_mode_duration` | `null` | **Advanced.** As above, for upcoming |
| `dynamic_duration.enabled` | `false` | **Advanced.** Size a mode's duration from how many games it actually has |
| `dynamic_duration.max_duration_seconds` | `null` | **Advanced.** Cap for the above |
| `dynamic_duration.modes.<mode>.enabled` | `false` | **Advanced.** Per-mode override of `dynamic_duration.enabled` |

`non_favorite_live_game_duration` is the setting to reach for when four games
are on at once and you only care about one: set `live_game_duration: 30` and
`non_favorite_live_game_duration: 8`, and your club's game gets most of the
airtime while the others still tick past.

### How often data is fetched

All of these are **advanced** — the defaults are tuned for a Raspberry Pi that is
also driving a panel, and raising the polling rate rarely helps.

| Option | Default | What it does |
|--------|---------|--------------|
| `update_interval_seconds` | `3600` | Base fetch interval for schedule data |
| `live_update_interval` | `30` | Fetch interval while a game is live |
| `recent_update_interval` | `3600` | Fetch interval for the recent screen |
| `upcoming_update_interval` | `3600` | Fetch interval for the upcoming screen |
| `stale_game_timeout` | `300` | How long a live game may go without an update before it is dropped from the rotation. Guards against a game the API stops reporting sitting on the board forever |
| `no_data_interval_seconds` | `300` | How long to wait between live checks when nothing is on. Backs off further the longer nothing is found |
| `live_idle_max_interval_seconds` | `900` | Ceiling for that back-off. Raise it out of season; lower it to notice the first game of the night sooner |
| `schedule_lookback_days` | `14` | How far back the recent screen can see |
| `schedule_lookahead_days` | `7` | How far ahead the upcoming screen can see |
| `background_service.enabled` | `true` | Fetch in a background thread so the panel never stalls on the network |
| `background_service.request_timeout` | `30` | Seconds before a fetch gives up |
| `background_service.max_retries` | `3` | Retries per failed fetch |
| `background_service.priority` | `2` | Queue priority against other plugins' fetches |

### What appears on the card

| Option | Default | What it does |
|--------|---------|--------------|
| `recent_games_to_show` | `1` | How many recent games — see [what the numbers mean](#what-the-games-to-show-numbers-mean) |
| `upcoming_games_to_show` | `1` | How many upcoming games — same caveat |
| `other_recent_games_to_show` | `1` | **Advanced.** Non-favourite recent games, in "favourites first" mode |
| `other_upcoming_games_to_show` | `1` | **Advanced.** Non-favourite upcoming games, in "favourites first" mode |
| `other_rotation_interval_seconds` | `1800` | **Advanced.** How often the non-favourite window advances |
| `other_games_min_quality` | `ranked` | **Advanced.** Which non-favourite games earn a slot: `any` or `ranked`. **Inert for AFL** — see below |
| `other_games_divisions` | `["fbs"]` | **Advanced.** Which divisions non-favourite games may come from. **Inert for AFL** — see below |
| `show_records` | `false` | **Advanced.** Draw each team's season record in the bottom corners |
| `show_ranking` | `false` | **Advanced.** Draw a rank badge. AFL publishes no poll, so this shows nothing |
| `show_odds` | `true` | Draw the betting line. **ESPN publishes no odds for AFL** — see [Known Limitations](#known-limitations) |
| `customization.favorite_result_colors.enabled` | `false` | Colour a finished game's score by whether your favourite won |
| `customization.favorite_result_colors.win_color` | `[0, 255, 0]` | **Advanced.** Colour for a win |
| `customization.favorite_result_colors.loss_color` | `[255, 0, 0]` | **Advanced.** Colour for a loss |
| `customization.favorite_result_colors.tie_color` | `[255, 200, 0]` | **Advanced.** Colour for a draw |

![The same Carlton-Melbourne final three times: score in white with the feature
off, green with Carlton as the favourite, red with Melbourne as the
favourite](../../docs/assets/afl-scoreboard/favorite-result-colors.png)

Favourite result colours only apply to *finished* games, and only when one of
the two teams is in `favorite_teams`. A neutral game is always drawn in the
normal score colour, which is why the feature is invisible until you set your
teams.

![The same upcoming card with show_records off and on; with it on, each team's
record appears in the bottom corners](../../docs/assets/afl-scoreboard/show-records.png)

### Card layout and text

These control what sits between the two logos and how dates and times are
written. `switch_*` keys apply to the full-screen scoreboard; the others apply to
scroll mode.

| Option | Default | Values |
|--------|---------|--------|
| `scroll_card.switch_upcoming_center` | `date_time` | `date_time`, `vs`, `none`, `inherit` |
| `scroll_card.upcoming_center` | `vs` | `vs`, `date_time`, `none` |
| `scroll_card.vs_text` | `VS` | Any short string — `VS`, `@`, `at`, `v`. Blank draws nothing |
| `scroll_card.switch_date_format` | `numeric` | `numeric` (9/4), `abbrev` (Sep 4), `day_first` (4 Sep), `numeric_day_first` (4/9), `weekday` (Fri Sep 4), `inherit` |
| `scroll_card.date_format` | `abbrev` | Same set, minus `inherit` |
| `scroll_card.time_format` | `12h` | `12h` (7:40PM) or `24h` (19:40) |
| `scroll_card.show_date` | `true` | Draw the date at all |
| `scroll_card.show_time` | `true` | Draw the start time at all |
| `scroll_card.swap_date_time` | `false` | Put the time above the date instead of below |
| `scroll_card.center_gap` | *(auto)* | Fixed pixel gap in the middle of a scroll card |
| `scroll_card.center_gap_ratio` | `0.28` | **Advanced.** Gap as a fraction of card width, when `center_gap` is unset |
| `scroll_card.center_gap_min` | `22` | **Advanced.** Floor for the computed gap |
| `scroll_card.center_gap_max` | `40` | **Advanced.** Ceiling for the computed gap |

![Four upcoming cards showing the centre as date_time, VS, at, and
nothing](../../docs/assets/afl-scoreboard/upcoming-center.png)

Note how `at` reads correctly in the third panel: the away team is on the left,
so "Carlton at Geelong" is what the card actually says.

![Four upcoming cards comparing 12-hour against 24-hour time, and numeric
against abbreviated and weekday date
formats](../../docs/assets/afl-scoreboard/date-time-formats.png)

Scroll-mode-only settings:

| Option | Default | What it does |
|--------|---------|--------------|
| `scroll_settings.scroll_speed` | `1.0` | **Advanced.** Pixels per step |
| `scroll_settings.scroll_delay` | `0.01` | **Advanced.** Seconds between steps. Lower is faster and costs more CPU |
| `scroll_settings.gap_between_games` | `48` | **Advanced.** Blank pixels between cards |
| `scroll_settings.game_card_width` | `128` | **Advanced.** Width of one card |
| `scroll_settings.show_league_separators` | `true` | **Advanced.** Divider between leagues (single-league here, so rarely visible) |
| `scroll_settings.dynamic_duration` | `true` | **Advanced.** Let the scroll run as long as one full pass takes |

### Celebrations

| Option | Default | What it does |
|--------|---------|--------------|
| `celebration_enabled` | `true` | Show a takeover screen when a favourite scores or wins a live game |
| `celebration_duration` | `8` | **Advanced.** Seconds the celebration holds the panel |
| `celebrate_opponent_goals` | `false` | **Advanced.** Also celebrate the opponent's goals |

Celebrations need `favorite_teams` to be set — with no favourites there is
nobody to celebrate for.

### Fonts, colours and offsets

Every text element on the card can be restyled independently. All of these are
**advanced**, and the defaults are tuned to be legible at 128×32.

| Group | Font default | Size | Colour |
|-------|--------------|------|--------|
| `customization.score_text` | `PressStart2P-Regular.ttf` | `10` | `[255, 255, 255]` |
| `customization.period_text` | `PressStart2P-Regular.ttf` | `8` | `[255, 255, 255]` |
| `customization.team_name` | `PressStart2P-Regular.ttf` | `8` | `[255, 255, 255]` |
| `customization.status_text` | `4x6-font.ttf` | `6` | `[255, 255, 255]` |
| `customization.detail_text` | `4x6-font.ttf` | `6` | `[255, 255, 255]` |
| `customization.rank_text` | `PressStart2P-Regular.ttf` | `10` | `[255, 255, 255]` |

Each group takes `font`, `font_size` and `text_color` (an RGB array):

```json
{
  "customization": {
    "score_text": { "font_size": 12, "text_color": [255, 220, 0] }
  }
}
```

`customization.layout` nudges individual elements by a pixel offset, for panels
where something sits slightly wrong. Each entry takes `x_offset` and `y_offset`,
both defaulting to `0`: `home_logo`, `away_logo`, `score`, `status_text`, `date`,
`time` and `odds`. The `records` entry takes `away_x_offset`, `home_x_offset`
and `y_offset` instead, since the two records are positioned separately.

### Timezone

| Option | Default | What it does |
|--------|---------|--------------|
| `timezone` | `""` | **Advanced.** IANA timezone for start times, e.g. `Australia/Melbourne` |

Resolution order, first match wins:

1. `timezone` in this plugin's config
2. The global LEDMatrix `timezone` setting
3. The system timezone

For AFL specifically this matters more than for most sports: matches are played
across three Australian timezones, and ESPN reports every start time in UTC.
Leave it blank unless you want this plugin to differ from the rest of your board.

---

## Panel Sizes

The scoreboard lays itself out from the panel dimensions rather than assuming a
size. Logos scale to the available height, and the score keeps the centre.

![The same final rendered on 64x32, 128x32, 128x64 and 256x32
panels](../../docs/assets/afl-scoreboard/panel-sizes.png)

- **64×32** is tight. The logos are drawn behind the text rather than beside it,
  and the score takes priority. It works, but a longer panel is much easier to
  read across a room.
- **128×32** is the size everything is tuned for.
- **128×64** gives the logos real estate and separates the status line, score and
  date into three bands.
- **256×32** keeps the same element sizes and simply centres them, so a long
  chain buys width rather than a bigger scoreboard. Scroll mode is what makes a
  long panel pay off, since it can show several cards at once.

---

## Team Abbreviations

`favorite_teams` and `exclude_teams` take the ESPN abbreviation, not the club
name:

| Abbrev | Club | Abbrev | Club |
|--------|------|--------|------|
| `ADEL` | Adelaide Crows | `MELB` | Melbourne |
| `BL` | Brisbane Lions | `NMFC` | North Melbourne |
| `CARL` | Carlton | `PORT` | Port Adelaide |
| `COLL` | Collingwood | `RICH` | Richmond |
| `ESS` | Essendon | `STK` | St Kilda |
| `FRE` | Fremantle | `SUNS` | Gold Coast Suns |
| `GEEL` | Geelong Cats | `SYD` | Sydney Swans |
| `GWS` | GWS Giants | `WB` | Western Bulldogs |
| `HAW` | Hawthorn | `WCE` | West Coast Eagles |

ESPN's team list also exposes a stale `GCFC` entry mislabelled as "Sydney
Swans". Use `SUNS` for Gold Coast.

If you are ever unsure of a code, enable debug logging: the plugin logs
`home_abbr` and `away_abbr` for every game it processes.

---

## Known Limitations

These are real, verified against the live ESPN feed — they are documented here
rather than left for you to discover on the panel.

**`show_odds` does nothing for AFL.** The setting defaults to `true`, but ESPN
publishes no odds block for any AFL fixture — a full finals-week payload
contains zero. The card is byte-identical with the setting on or off. It is not
free, though: with it on, the plugin still issues one odds request per selected
game on every update. **Set `show_odds: false`** to save those calls.

**`show_ranking` does nothing for AFL.** The AFL publishes no poll, so the rank
badge has nothing to draw. The setting exists because this plugin shares its
rendering code with the college-sport scoreboards, where it does work.

**`dynamic_duration.min_duration_seconds` is not applied.** The schema exposes it
with a default of `30`, but only `max_duration_seconds` is read. Setting a
minimum has no effect.

**`background_service.max_workers` is not applied.** The schema exposes it with a
default of `3`, but the plugin creates its background service with a single
worker regardless.

---

## Troubleshooting

**The upcoming screen is empty, but I know there are fixtures.**
The most likely cause is the fetch window: `schedule_lookahead_days` defaults to
`7`, and during a bye or between finals weeks the next fixture can sit beyond
that. Raise it to `14`. The second most likely cause is
`show_favorite_teams_only: true` with favourites who are not playing this round.

**I see far more games than I asked for.**
`upcoming_games_to_show` is a *per-team* budget when `show_favorite_teams_only`
is on. Three favourites and a value of 3 is up to nine cards. See
[what the numbers mean](#what-the-games-to-show-numbers-mean).

**A team shows as a grey box with text instead of a logo.**
Logos are downloaded on demand and cached under
`assets/sports/afl_logos/` in your LEDMatrix install. A failed download is
cached as a tiny placeholder file that is never retried, so the team stays
logo-less. Delete the undersized file (a real logo is tens of kilobytes; a
placeholder is well under 1 KB) and restart to force a fresh download.

**Start times are wrong by hours.**
Check `timezone`. ESPN reports every AFL start time in UTC and the plugin
converts on display, so an unset or wrong timezone shifts every card.

**The score is white even though I enabled favourite result colours.**
The feature only applies to finished games in which one of the two teams is in
`favorite_teams`. Check the abbreviation matches the table above exactly.

**Nothing updates during a live game.**
Check `display_modes.live` is on and that the game involves a favourite, or set
`filtering.show_all_live: true`.

---

## Development

### File structure

```text
afl-scoreboard/
├── manifest.json           # Metadata and version history
├── manager.py              # AflScoreboardPlugin: mode rotation and config plumbing
├── afl_managers.py         # AFL-specific fetching and cache keys
├── sports.py               # Shared sports engine: selection, extraction, rendering
├── game_renderer.py        # Card drawing
├── scroll_display.py       # Scroll-mode display
├── config_schema.json      # Settings schema; source of truth for defaults
└── test_*.py               # Standalone regression tests
```

`sports.py`, `game_renderer.py` and `scroll_display.py` are **shared copies**
carried by every sports scoreboard in this monorepo. A fix in one must be
ported to its siblings in the same change — see
[docs/plugin-development/08-shared-sports-code.md](../../docs/plugin-development/08-shared-sports-code.md).

### Data source

ESPN's public `australian-football/afl` scoreboard API. No key required, and no
account needed. The plugin fetches one date-range request per update and shares
the result across all three modes, rather than one request per mode.

### Regenerating the images in this README

Every screenshot is produced from a declarative shot list against archived ESPN
payloads and a frozen clock, so re-rendering is reproducible:

```bash
python scripts/render_docs_assets.py --plugin afl-scoreboard
```

The fixtures under `docs/assets/afl-scoreboard/fixtures/` are real ESPN
responses from the 2026 finals series. The live-mode fixture is that same real
data with one match's status rewound to three-quarter time and its score set to
the real cumulative three-quarter total, so the live card shows a moment that
genuinely happened rather than an invented one.

---

## Support

- YouTube: <https://www.youtube.com/@ChuckBuilds>
- Instagram: <https://www.instagram.com/ChuckBuilds/>
- Discord: <https://discord.com/invite/uW36dVAtcT>
- Sponsor: [GitHub Sponsors](https://github.com/sponsors/ChuckBuilds) ·
  [Buy Me a Coffee](https://buymeacoffee.com/chuckbuilds) ·
  [Ko-fi](https://ko-fi.com/chuckbuilds/)

Released under the GNU General Public License v3.0 — see [LICENSE](LICENSE).
