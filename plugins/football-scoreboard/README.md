[![ChuckBuilds](https://img.shields.io/badge/ChuckBuilds-LEDMatrix-blue)](https://github.com/ChuckBuilds/LEDMatrix)

# Football Scoreboard

Live, recent, and upcoming **NFL** and **NCAA Football** games on your LEDMatrix
display, from ESPN's public API. No API key required.

![NFL live scorebug](../../docs/assets/football-scoreboard/hero.png)

## Contents

- [Quick start](#quick-start)
- [Display modes](#display-modes)
- [The live card](#the-live-card)
- [How games are chosen](#how-games-are-chosen)
- [Dynamic team resolution](#dynamic-team-resolution)
- [Rotation, resume, and durations](#rotation-resume-and-durations)
- [Score and win celebrations](#score-and-win-celebrations)
- [Adaptive layout](#adaptive-layout)
- [Panel sizes](#panel-sizes)
- [Settings reference](#settings-reference)
- [Per-league settings](#per-league-settings)
- [Matchup separator and the upcoming card middle](#matchup-separator-and-the-upcoming-card-middle)
- [Text colours and layout offsets](#text-colours-and-layout-offsets)
- [Favorite team result colours](#favorite-team-result-colours)
- [Vegas ticker: seeing live games more often](#vegas-ticker-seeing-live-games-more-often)
- [Team abbreviations](#team-abbreviations)
- [Data sources and architecture](#data-sources-and-architecture)
- [Installation](#installation)
- [Troubleshooting](#troubleshooting)

## Quick start

1. Install **Football Scoreboard** from the LEDMatrix Plugin Store.
2. Turn on `enabled`, then the league you want — `nfl` is on by default,
   `ncaa_fb` is off.
3. Add your teams under that league's **Favorite Teams**.

```json
{
  "football-scoreboard": {
    "enabled": true,
    "nfl": {
      "enabled": true,
      "favorite_teams": ["KC", "BUF"],
      "filtering": { "show_favorite_teams_only": false },
      "game_limits": {
        "upcoming_games_to_show": 3,
        "other_upcoming_games_to_show": 3
      }
    },
    "ncaa_fb": {
      "enabled": true,
      "favorite_teams": ["UGA", "AUB"]
    }
  }
}
```

## Display modes

Six modes — three per league — that the LEDMatrix host rotation cycles through
independently.

![The three NFL display modes](../../docs/assets/football-scoreboard/display-modes.png)

| Mode | Shows | Top line |
|---|---|---|
| `nfl_live` | NFL games in progress | `Q1`–`Q4`, `OT1` past the fourth, or `HALF` |
| `nfl_recent` | Finished NFL games | `Final`, or `Final/OT` |
| `nfl_upcoming` | Scheduled NFL games | `Next Game`, then the date and kickoff time |
| `ncaa_fb_live` | NCAA games in progress | As above |
| `ncaa_fb_recent` | Finished NCAA games | As above |
| `ncaa_fb_upcoming` | Scheduled NCAA games | As above |

The three period states:

![Q3, HALF and Final](../../docs/assets/football-scoreboard/period-states.png)

Each mode renders as **switch** (one game at a time, timed) or **scroll** (all
games scroll horizontally at high FPS), set per league and per mode with
`<league>.display_modes.<mode>_display_mode`.

> **The mode toggles are named `show_live`, `show_recent`, `show_upcoming`** in
> this plugin, not `live` / `recent` / `upcoming` as in the other scoreboards.
> Copying a `display_modes` block over from another scoreboard's config will
> silently leave every mode at its default.

## The live card

A live football card carries more than the score. Down and distance sit under
the score in yellow, turning **red inside the red zone**; a small football icon
marks the team with possession; and three timeout pips per team run along the
bottom edge — white for remaining, grey for used.

![Down, distance, possession and timeouts](../../docs/assets/football-scoreboard/live-detail.png)

All four come straight from ESPN's `situation` block and need no configuration.
Their positions are nudgeable through `customization.layout.down_distance`,
`customization.layout.possession`, and `customization.layout.timeouts`.

## How games are chosen

**`upcoming_games_to_show` is not "how many cards you see".** It is the size of
a *pool*. The panel cycles through that pool one card at a time
(`upcoming_game_duration`, 15s by default) and keeps its place between visits,
so a pool of 3 means the board rotates through the same 3 games until the
schedule moves on. A bigger number gives you a *longer lap*, so any one game
comes round **less** often.

### The three regimes

Which one you are in depends on `favorite_teams` and
`filtering.show_favorite_teams_only`:

| `favorite_teams` | `show_favorite_teams_only` | What you get |
|---|---|---|
| empty | either | The next N games league-wide, chronologically. Every game is a non-favorite game, so both filters below apply to all of them. |
| set | **on** (default) | Only your teams. The limit is a budget **per team**. |
| set | **off** | **Your teams first, then other games to fill.** Both limits are **totals**. |

The third row is what most people want. Before v2.26.0 it did not exist — with
the flag off, favorites were ignored *entirely* and you got the next N games
league-wide. On a college slate that is roughly 950 upcoming games, so your team
appeared about as often as chance allowed.

### The settings

Per league, under `game_limits`:

| Option | Default (NFL / NCAA) | Description |
|---|---|---|
| `upcoming_games_to_show` | `1` / `5` | How many **favorite** upcoming games to pool. |
| `recent_games_to_show` | `5` / `5` | The same, for finished games. |
| `other_upcoming_games_to_show` | `1` / `5` | How many **non-favorite** upcoming games to add. `0` gives favorites only. |
| `other_recent_games_to_show` | `5` / `5` | The same, for finished games. |
| `other_rotation_interval_seconds` | `1800` | How often the non-favorite slice advances. `0` pins it. |
| `other_games_min_quality` | `ranked` | Which non-favorite games qualify: `ranked` or `any`. |
| `other_games_divisions` | `["fbs"]` | Which divisions non-favorite games may come from: `fbs`, `fcs`, `other`. |

**Your favorite teams are never filtered by the last two.** Follow a Division II
school and its games always appear, whatever the quality bar or division boxes
say. Those settings only decide what fills the *remaining* slots.

Within the other-games pool, **the better matchup leads**, and each team appears
once. The pool is each team's *next* game ordered by the best poll position of
either side, so a top-five matchup sits in the first window rather than whichever
kicks off soonest — and the #1 team's whole season does not sort above everyone
else's opener. Ties fall back to kickoff order, and a league with no poll keeps
chronological order. Your favorite teams are ordered by when they play, not by
rank: for your own team the next game is the point.

### Variety comes from turnover, not from a bigger pool

Rather than widening the pool, the non-favorite slice **moves**. The window
advances by its own width every `other_rotation_interval_seconds`, so
consecutive windows do not overlap and the board works through the schedule
instead of resampling the front of it.

Measured on a real board — favorites `UGA` + `AUB`, 3 others, rotating every 30
minutes:

```text
  +  0 min: UNC@TCU,   SJSU@USC, NCSU@UVA
  + 30 min: JVST@NDSU, SAC@EMU,  HAW@STAN
  + 60 min: NMSU@FSU,  MEM@UNLV, MASS@RUTG
  + 90 min: BCU@UCF,   AKR@WAKE, MRMK@DEL
```

18 different matchups over three hours, while the pool stays at 6 cards and a
full lap still takes about 90 seconds of airtime.

Your favorites are **not** rotated. For upcoming games the soonest ones are the
point — rotating them would show a week-8 fixture instead of Saturday's.

### Keeping the filler out

Selection is otherwise purely chronological, and on a college slate most of what
that returns is filler. Of roughly 950 upcoming games, about 250 involve a
nationally ranked team; the rest are matchups most viewers have never heard of.
Rotating harder just serves more of them, which is why `other_games_min_quality`
defaults to `ranked`.

`ranked` means ranked in the **top division's** poll — the AP Top 25 for college
football. South Dakota State is a perennial FCS number one, but South Dakota
State at Northwestern is not a ranked matchup and does not qualify: the ranked
side is FCS and the FBS side is unranked. The poll is matched on team id rather
than abbreviation, so two schools sharing an abbreviation across divisions
cannot promote each other.

> **Retired:** `broadcast` no longer exists. ESPN lists a broadcaster for almost
> every game now — ESPN+ included — so on a real Week 1/Week 2 slate it passed
> **174 of 175** games: a quality bar in the dropdown that behaved as `any`.
> Boards still holding it are read as `ranked` and say so once in the log.

`other_games_divisions` needs **one** team in a checked division, not both. With
only `fbs` checked you still get #12 Texas Tech hosting Abilene Christian — a
game involving a team you asked for — while Abilene Christian vs Furman stays
out. Check `fcs` or `other` to bring the smaller-division matchups in as well.

Both filters **fail open**: if rankings cannot be fetched, or the division
rosters do not resolve, the game is allowed through. A board showing filler is a
poor board; a board showing nothing is a broken one.

They fail open a second time, as a set: if the filters between them leave
**nothing at all**, the unfiltered list is used instead. Setting
`other_upcoming_games_to_show` or `other_recent_games_to_show` to `0` is the one
way to ask for an empty slate, and that is honoured.

> **Both settings only mean something for `ncaa_fb`.** The NFL has no poll and
> no divisions, so both are inert there and cost nothing — no poll is requested
> and no division lookup is made.

### A worked example

Follow Georgia and Auburn, and want their next games plus some variety:

```json
{
  "ncaa_fb": {
    "favorite_teams": ["UGA", "AUB"],
    "filtering": { "show_favorite_teams_only": false },
    "game_limits": {
      "upcoming_games_to_show": 3,
      "other_upcoming_games_to_show": 3
    }
  }
}
```

That gives 6 cards: the 3 soonest UGA/AUB games, plus 3 ranked FBS matchups that
turn over every half hour.

### Live rotation

When several games are live at once the rotation is weighted: a game involving
one of your teams gets `filtering.favorite_live_boost` turns for every one turn
other live games get, and is queued first whenever the rotation refreshes. Set
it to `1` for even rotation. It never interrupts a game already on screen — it
just gets more and sooner turns, and it is independent of `live_priority`, which
controls whether live games preempt the recent/upcoming rotation at all.

A live game the API stops reporting for `stale_game_timeout` seconds is dropped,
so an abandoned game does not sit on the board forever.

## Dynamic team resolution

Instead of listing schools by hand, put one of these tokens in `favorite_teams`
and it expands to the current AP poll, updating as the rankings move:

| Token | Expands to |
|---|---|
| `AP_TOP_5` | The AP Top 5 |
| `AP_TOP_10` | The AP Top 10 |
| `AP_TOP_25` | The full AP Top 25 |

Tokens mix with literal abbreviations, and duplicates are removed:

```json
"favorite_teams": ["AP_TOP_25", "UGA", "ALA"]
```

> **These expand into real teams, and that has consequences.** Adding
> `AP_TOP_10` alongside two teams of your own makes yours 2 of up to 12
> favorites, all competing for the same slots, and your own teams then queue
> behind every top-10 game that kicks off earlier. On one real schedule UGA's
> next game was favorite-game #5 and Auburn's was #8, so with
> `upcoming_games_to_show: 3` neither appeared. If you want your teams
> guaranteed, keep the favorites list to your teams and let
> `other_upcoming_games_to_show` supply the variety.

## Rotation, resume, and durations

The plugin registers its six granular modes in `manifest.json`, and the display
controller rotates through them in the order they appear:

1. `nfl_recent`
2. `nfl_upcoming`
3. `nfl_live`
4. `ncaa_fb_recent`
5. `ncaa_fb_upcoming`
6. `ncaa_fb_live`

Reorder them in `manifest.json` to change the sequence — for instance to show
both leagues' Recent screens before either Upcoming.

A league or mode disabled in the config makes the plugin return `False` for that
mode, and the controller skips it. So you can disable a whole league, or a
single mode within one, and the rotation closes up around it.

### Resume

When a mode's time runs out before it has shown every game in its pool, it
**resumes where it left off** on the next visit rather than restarting:

```text
Cycle 1: Recent mode (60s, 10 games in the pool)
  games 1-4 shown, time expires, rotate

Cycle 2: Recent mode resumes
  games 5-8 shown, time expires, rotate

Cycle 3: Recent mode resumes
  games 9-10 shown, full lap complete, progress resets
```

### Dynamic duration

With no per-mode duration configured, the mode's total is calculated as
`number_of_games x per_game_duration` — 24 games at 15s each is a 360-second
mode. That shows everything but can make a mode very long on a full slate, which
is what `dynamic_duration.max_duration_seconds` is for.

## Score and win celebrations

When a favorite team scores or wins a **live** game, the scorebug briefly gives
way to a full-screen celebration: the two logos at the edges, the new score
centered with the scoring side's digits pulsing, and a banner at the top.

The banner is chosen from the **points scored between two updates**, not from
any feed text, so it works the same way in both leagues:

| Points gained | Banner |
|---|---|
| 6 or more | `TOUCHDOWN!` / `<TEAM> TD!` |
| 3 | `<TEAM> FIELD GOAL!` |
| 2 | `<TEAM> SAFETY!` |
| Anything else, e.g. a lone extra point | `<TEAM> SCORES!` |
| Game goes final with the favorite ahead | `<TEAM> WINS!` |

A touchdown arriving as `+6` and then `+1` a few seconds later shows a
**single** celebration — the extra point folds into the one already on screen. A
two-point conversion and a safety are both `+2`, so the banner reads `SAFETY!`
for either.

Configured per league: `celebration_enabled` (default `true`),
`celebration_duration` (default `8` seconds), and `celebrate_opponent_scores`
(default `false`; with no favorites configured, any team's score celebrates).

## Adaptive layout

`layout_mode` chooses the layout engine. `classic` is the original fixed layout.
`adaptive` (beta) scales fonts, logos, and element regions to the panel, so
content grows on a large panel instead of sitting in a 128x32-shaped island.

![classic against adaptive on a 128x64 panel](../../docs/assets/football-scoreboard/layout-mode.png)

The difference is clearest on a tall panel: adaptive sizes the crests to the
space and keeps the score clear of them, where classic draws both at their fixed
size and lets the score overlap.

```json
{ "layout_mode": "adaptive" }
```

It is plugin-wide, not per league, and defaults to `classic` so nothing changes
until you ask for it.

## Panel sizes

![Live card at four panel sizes](../../docs/assets/football-scoreboard/panel-sizes.png)

The plugin passes the render-safety harness on all eight supported sizes. At
64x32 the two crests and the centre column share very little room; 128x32 or
wider is a much better fit, and `layout_mode: adaptive` is worth trying on
anything larger than 128x32.

## Settings reference

Settings marked **Advanced** sit behind the *Advanced* toggle in the web UI.
Defaults are the schema defaults, which is what the web UI writes.

### Plugin level

| Key | Type | Default | What it does |
|---|---|---|---|
| `enabled` | boolean | `true` | Master on/off switch for the whole plugin. |
| `display_duration` | 5–300 s | `30` | How long the display controller shows this plugin's mode before rotating to the next plugin. |
| `game_display_duration` | 3–60 s | `15` | **Advanced.** Per-game time within a mode, where the league does not override it. |
| `update_interval` | 30–86400 s | `3600` | **Advanced.** Base data refresh cadence. |
| `layout_mode` | `classic` \| `adaptive` | `classic` | **Advanced.** Layout engine — see [Adaptive layout](#adaptive-layout). |
| `timezone` | string | `""` | **Advanced.** IANA zone for kickoff times, e.g. `America/Chicago`. Blank follows the LEDMatrix global timezone, then the host system's, then UTC. |
| `schedule_lookback_days` | 1–60 | `14` | **Advanced.** How far back to fetch for the Recent screens. |
| `schedule_lookahead_days` | 1–60 | `7` | **Advanced.** How far ahead to fetch for Upcoming. A game beyond this horizon is never fetched, so it cannot reach the board even though the date is known. |
| `no_data_interval_seconds` | 5–86400 s | `300` | **Advanced.** Wait between live checks when nothing is live. Backs off further the longer nothing is found. |
| `live_idle_max_interval_seconds` | 5–86400 s | `900` | **Advanced.** Ceiling for that back-off. Useful out of season. |

## Per-league settings

Every table below exists twice, once under `nfl` and once under `ncaa_fb`, with
the same keys. `<league>` stands for either. **Five defaults differ between the
two leagues** — everything else is identical:

| Key | NFL | NCAA FB |
|---|---|---|
| `<league>.enabled` | `true` | `false` |
| `<league>.live_game_duration` | `30` | `20` |
| `<league>.game_limits.upcoming_games_to_show` | `1` | `5` |
| `<league>.game_limits.other_upcoming_games_to_show` | `1` | `5` |
| `<league>.display_options.show_ranking` | `false` | `true` |

The NCAA defaults are larger because a college Saturday has far more games than
an NFL Sunday, and `show_ranking` is on there because college football has a
poll to rank against.

### Teams and priority

| Key | Type | Default | What it does |
|---|---|---|---|
| `<league>.enabled` | boolean | see above | Build this league's managers at all. |
| `<league>.favorite_teams` | array | `[]` | Teams to prioritise. Abbreviations, or an `AP_TOP_*` token. |
| `<league>.exclude_teams` | array | `[]` | **Advanced.** Teams to always hide, from the live rotation and from finals alike (spoiler protection). Takes precedence over `favorite_teams` and `show_all_live`. |
| `<league>.live_priority` | boolean | `true` | **Advanced.** Let this league's live games interrupt the rotation and display immediately. |

### Display modes

| Key | Type | Default |
|---|---|---|
| `<league>.display_modes.show_live` | boolean | `true` |
| `<league>.display_modes.show_recent` | boolean | `true` |
| `<league>.display_modes.show_upcoming` | boolean | `true` |
| `<league>.display_modes.live_display_mode` | `switch` \| `scroll` | `switch` (**Advanced**) |
| `<league>.display_modes.recent_display_mode` | `switch` \| `scroll` | `switch` (**Advanced**) |
| `<league>.display_modes.upcoming_display_mode` | `switch` \| `scroll` | `switch` (**Advanced**) |

### Filtering

| Key | Type | Default | What it does |
|---|---|---|---|
| `<league>.filtering.show_favorite_teams_only` | boolean | `true` | Show only your teams' games. |
| `<league>.filtering.show_all_live` | boolean | `false` | **Advanced.** Show every live game regardless of favorites. `exclude_teams` still applies. |
| `<league>.filtering.favorite_live_boost` | 1–5 | `2` | **Advanced.** Turns a favorite's live game gets per one turn for other live games. `1` is even rotation. |

### Game limits

All **Advanced**. Defaults given as NFL / NCAA where they differ; see
[The settings](#the-settings) for what each one means.

| Key | Type | Default |
|---|---|---|
| `<league>.game_limits.recent_games_to_show` | 1–20 | `5` |
| `<league>.game_limits.upcoming_games_to_show` | 1–20 | `1` / `5` |
| `<league>.game_limits.other_recent_games_to_show` | 0–20 | `5` |
| `<league>.game_limits.other_upcoming_games_to_show` | 0–20 | `1` / `5` |
| `<league>.game_limits.other_rotation_interval_seconds` | 0–86400 s | `1800` |
| `<league>.game_limits.other_games_min_quality` | `any` \| `ranked` | `ranked` |
| `<league>.game_limits.other_games_divisions` | array | `["fbs"]` |

### Durations

All **Advanced**.

| Key | Type | Default | What it does |
|---|---|---|---|
| `<league>.live_game_duration` | 10–120 s | `30` / `20` | Per-game time for live games. Applies to games with a favorite when a non-favorite duration is set. |
| `<league>.non_favorite_live_game_duration` | 0–120 s | `0` | Shorter turn for live games with no favorite. `0` means use `live_game_duration` for everything. |
| `<league>.recent_game_duration` | number | `15` | Per-game time on the Recent screen. Falls back to the top-level `game_display_duration` when unset. |
| `<league>.upcoming_game_duration` | number | `15` | The same for Upcoming. |

`non_favorite_live_game_duration` **only takes effect** when favorite teams are
configured **and** non-favorite live games are being shown —
`show_favorite_teams_only` off, or `show_all_live` on. Otherwise non-favorite
games are never on screen to shorten:

| Favorites set? | Non-favorite games shown? | Game has a favorite? | Duration used |
|---|---|---|---|
| No | — | — | `live_game_duration` |
| Yes | No | favorite | `live_game_duration` |
| Yes | Yes | favorite | `live_game_duration` |
| Yes | Yes | none | `non_favorite_live_game_duration`, when above `0` |

### Update intervals

All **Advanced**.

| Key | Type | Default | What it does |
|---|---|---|---|
| `<league>.live_update_interval` | 5–300 s | `30` | How often live game data refreshes. |
| `<league>.recent_update_interval` | 60–86400 s | `3600` | How often the finished-games list is rebuilt. This also sets how soon a game that has just ended can appear — lower it if you want results sooner. |
| `<league>.upcoming_update_interval` | 60–86400 s | `3600` | How often the upcoming-games list is rebuilt. Selection and the non-favorite rotation both run on the display side, so this governs only the fetch. |
| `<league>.stale_game_timeout` | 60–3600 s | `300` | Drop a live game the API has stopped updating. |

### Display options

All **Advanced**.

| Key | Type | Default | What it does |
|---|---|---|---|
| `<league>.display_options.show_records` | boolean | `false` | Draw win-loss records in the bottom corners. |
| `<league>.display_options.show_ranking` | boolean | `false` / `true` | Draw poll rank badges. Unranked teams show no badge, by design. |
| `<league>.display_options.show_odds` | boolean | `true` | Draw betting odds. |

![show_records on and off](../../docs/assets/football-scoreboard/show-records.png)

### Celebrations

| Key | Type | Default |
|---|---|---|
| `<league>.celebration_enabled` | boolean | `true` |
| `<league>.celebration_duration` | 3–30 s | `8` (**Advanced**) |
| `<league>.celebrate_opponent_scores` | boolean | `false` (**Advanced**) |

### Dynamic duration

Sizes each mode's total time from how much there is to show. All **Advanced**.

| Key | Type | Default |
|---|---|---|
| `<league>.dynamic_duration.enabled` | boolean | `false` |
| `<league>.dynamic_duration.min_duration_seconds` | 10–300 s | `30` |
| `<league>.dynamic_duration.max_duration_seconds` | 60–600 s | — |
| `<league>.dynamic_duration.modes.live.enabled` | boolean | `false` |
| `<league>.dynamic_duration.modes.live.min_duration_seconds` | 10–300 s | — |
| `<league>.dynamic_duration.modes.live.max_duration_seconds` | 60–600 s | — |
| `<league>.dynamic_duration.modes.recent.enabled` | boolean | `false` |
| `<league>.dynamic_duration.modes.recent.min_duration_seconds` | 10–300 s | — |
| `<league>.dynamic_duration.modes.recent.max_duration_seconds` | 60–600 s | — |
| `<league>.dynamic_duration.modes.upcoming.enabled` | boolean | `false` |
| `<league>.dynamic_duration.modes.upcoming.min_duration_seconds` | 10–300 s | — |
| `<league>.dynamic_duration.modes.upcoming.max_duration_seconds` | 60–600 s | — |

### Scroll settings

All **Advanced**, and per league.

| Key | Type | Default | What it does |
|---|---|---|---|
| `<league>.scroll_settings.scroll_speed` | 1.0–200.0 px/s | `50.0` | Higher scrolls faster. |
| `<league>.scroll_settings.scroll_delay` | 0.001–0.1 s | `0.01` | Frame delay; `0.01` is 100 FPS. Lower is smoother. |
| `<league>.scroll_settings.gap_between_games` | 8–128 px | `48` | Gap between game cards. |
| `<league>.scroll_settings.show_league_separators` | boolean | `true` | Draw league icons between leagues. |
| `<league>.scroll_settings.dynamic_duration` | boolean | `true` | Size the scroll duration from the content width. |
| `<league>.scroll_settings.game_card_width` | 32–512 px | `128` | Card width. Lower it on a multi-panel chain to fit more games on screen at once. |

## Matchup separator and the upcoming card middle

The **Matchup Card Layout** section (`scroll_card`) controls what sits between
the two crests before a game starts, and how the date and time are written.
Plugin-wide, not per league.

| Setting | Key | Default | What it does |
|---|---|---|---|
| Matchup Separator | `scroll_card.vs_text` | `VS` | Text between the teams: `VS`, `@`, `at`, `v`. The away side is always on the left, so `@` and `at` read as "away at home". Blank draws nothing. |
| Middle of an Upcoming Card | `scroll_card.upcoming_center` | `vs` | Scroll and Vegas cards: `vs`, `date_time`, or `none`. |
| Middle of a Full-Screen Upcoming Scoreboard | `scroll_card.switch_upcoming_center` | `date_time` | The same choice for the full-screen scoreboard, plus `inherit` to follow the row above. |
| Date Format | `scroll_card.date_format` | `abbrev` | Scroll and Vegas cards: `Sep 19`, `9/19`, `19 Sep`, `19/9`, or `Fri Sep 19`. |
| Full-Screen Date Format | `scroll_card.switch_date_format` | `numeric` | **Advanced.** The same for the full-screen scoreboard, plus `inherit`. It has its own default because the two displays disagree about what is normal. |
| Time Format | `scroll_card.time_format` | `12h` | 12- or 24-hour clock. |
| Show Date / Show Time | `scroll_card.show_date`, `scroll_card.show_time` | `true` | Drop either line from the scroll and Vegas cards. |
| Full-Screen Show Date / Show Time | `scroll_card.switch_show_date`, `scroll_card.switch_show_time` | `true` | The same for the full-screen scoreboard. Separate switches because the originals predate this display reading the block, and sharing them would have changed what existing boards draw. |
| Swap Date and Time | `scroll_card.swap_date_time` | `false` | Flip the two lines. Each display starts from its own order, so this flips rather than forces. |

The centre-gap settings size the scroll and Vegas card's middle strip only — the
full-screen scoreboard pins its crests to the panel edges and is unaffected.

| Key | Type | Default | What it does |
|---|---|---|---|
| `scroll_card.center_gap` | 0–64 px | unset | Pixels kept clear down the middle. Unset scales with card width; `0` restores edge-to-edge logos. |
| `scroll_card.center_gap_ratio` | 0.0–0.6 | `0.28` | **Advanced.** Fraction of card width used when the gap is not pinned. |
| `scroll_card.center_gap_min` | 0–64 px | `22` | **Advanced.** Floor for the scaled gap. |
| `scroll_card.center_gap_max` | 0–96 px | `40` | **Advanced.** Ceiling for the scaled gap. |

## Text colours and layout offsets

Seven text elements, each with `font`, `font_size`, and `text_color`, under
`customization.<element>`. All **Advanced**. Faces:
`PressStart2P-Regular.ttf`, `4x6-font.ttf`, `5by7.regular.ttf`, `5x7.bdf`,
`4x6.bdf`, `cozette.bdf`.

| Element | Default font | Default size | Draws |
|---|---|---|---|
| `score_text` | `PressStart2P-Regular.ttf` | `10` | The score, and the matchup separator on an upcoming card |
| `period_text` | `PressStart2P-Regular.ttf` | `8` | The quarter and clock, and the date/time on an upcoming scoreboard |
| `team_name` | `PressStart2P-Regular.ttf` | `8` | Team names and abbreviations |
| `status_text` | `4x6-font.ttf` | `6` | Status lines such as "Next Game" |
| `detail_text` | `4x6-font.ttf` | `6` | Small detail lines, including down and distance |
| `rank_text` | `PressStart2P-Regular.ttf` | `10` | Poll rank badges |
| `odds_text` | `4x6-font.ttf` | `6` | Betting odds (defaults to green, `[0, 255, 0]`) |

The `.bdf` faces are bitmap fonts that exist at exactly one pixel size; sizes
snap to that grid rather than being scaled. Odds sizes snap too: `4x6-font.ttf`
to 7, 14, 21; press_start to 8, 16. Every `customization.<element>` object sets
`additionalProperties: false`.

```json
{
  "customization": {
    "score_text": { "text_color": [255, 200, 0] },
    "status_text": { "text_color": "#00A0FF" }
  }
}
```

Two things keep their own colours on purpose: the odds figures, tinted by which
side is favoured, and down-and-distance, which is yellow normally and red in the
red zone.

### Layout offsets

Nudge any element in pixels. All default to `0`, all **Advanced**, all under
`customization.layout.<element>`, and all set `additionalProperties: false`.

| Element | Keys | Measured from |
|---|---|---|
| `home_logo`, `away_logo` | `x_offset`, `y_offset` | Default logo position |
| `score` | `x_offset`, `y_offset` | Panel centre |
| `status_text` | `x_offset`, `y_offset` | Centre horizontally, top vertically |
| `date` | `x_offset`, `y_offset` | Centre horizontally, default position vertically |
| `time` | `x_offset`, `y_offset` | Centre horizontally, the date's position vertically |
| `down_distance` | `x_offset`, `y_offset` | Default down-and-distance position |
| `possession` | `x_offset`, `y_offset` | Default possession-icon position |
| `timeouts` | `x_offset`, `y_offset` | Default timeout-pip position |
| `records` | `away_x_offset`, `home_x_offset`, `y_offset` | Away from the left, home from the right, both from the bottom |
| `odds` | `x_offset`, `y_offset` | Default odds position |

## Favorite team result colours

A run of games against the same opponent is hard to read at a glance: in scroll
and Vegas mode the same two crests go past several times and only the digits
change. Turn this on to colour a finished game's score by how your team did.

| Key | Type | Default |
|---|---|---|
| `customization.favorite_result_colors.enabled` | boolean | `false` |
| `customization.favorite_result_colors.win_color` | `[r, g, b]` | `[0, 255, 0]` |
| `customization.favorite_result_colors.loss_color` | `[r, g, b]` | `[255, 0, 0]` |
| `customization.favorite_result_colors.tie_color` | `[r, g, b]` | `[255, 200, 0]` |

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

- Only finished games are coloured; live and upcoming cards are untouched.
- A game needs **exactly one** favorite team. Neither side or both, and the score
  keeps its normal colour.
- The three colours are Advanced settings.

This tint is applied by the LEDMatrix core rather than by the plugin, which is
why the keys do not appear in this plugin's source.

## Vegas ticker: seeing live games more often

By default a live game **takes over** the display: the Vegas ticker stops and
this scoreboard shows full screen until the game ends. To keep the marquee
scrolling and still see scores, set this in the **core** config — not in this
plugin's settings:

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
cycle. These weights let this plugin claim several slots per cycle, spaced
evenly through it. `live_weight` applies whenever this scoreboard has a live
game; `favorite_live_weight` applies when one of your teams is playing. That
distinction has to be made here rather than in the core, which can tell *that* a
game is live but not *whose*.

- The weight is per **plugin**, not per game. With four games live this
  scoreboard still occupies one slot at a time and picks between its own games
  using `favorite_live_boost`.
- More slots make the cycle **longer**, not faster.

## Team abbreviations

**NFL:** `TB`, `DAL`, `GB`, `KC`, `BUF`, `SF`, `PHI`, `NE`, `MIA`, `NYJ`, `LAC`,
`DEN`, `LV`, `CIN`, `BAL`, `CLE`, `PIT`, `IND`, `HOU`, `TEN`, `JAX`, `ARI`,
`LAR`, `SEA`, `WAS`, `NYG`, `MIN`, `DET`, `CHI`, `ATL`, `CAR`, `NO`.

**NCAA Football:** `UGA` (Georgia), `AUB` (Auburn), `BAMA` (Alabama), `CLEM`
(Clemson), `OSU` (Ohio State), `MICH` (Michigan), `FSU` (Florida State), `LSU`,
`OU` (Oklahoma), `TEX` (Texas), `ORE` (Oregon), `MISS` (Mississippi), `GT`
(Georgia Tech), `VAN` (Vanderbilt), `BYU`.

To check any team, read `events[].competitions[].competitors[].team.abbreviation`
from the scoreboard endpoint below.

## Data sources and architecture

ESPN's public site API, no key required:

- NFL: `https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard`
- NCAA FB: `https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard`
- AP poll: the same host's `/rankings` path for college football

Crests are downloaded on first sight and cached under `assets/sports/nfl_logos/`
and `assets/sports/ncaa_logos/`. Rankings are cached for an hour, and the two
ranking groups share one fetch.

Each league keeps three managers — live, recent, upcoming — built only when that
league's `enabled` flag is set. The plugin exposes each as its own display mode
so the host controller can schedule and skip them individually.

## Installation

From the Plugin Store in the LEDMatrix web UI: open `http://your-pi-ip:5000`, go
to **Plugin Manager**, find **Football Scoreboard** under **Plugin Store**, and
click **Install**. Then open the plugin's tab to pick your teams.

Manual install from source:

```bash
cd /path/to/LEDMatrix
cp -r /path/to/ledmatrix-plugins/plugins/football-scoreboard plugin-repos/
sudo systemctl restart ledmatrix
```

The documentation images come from `docs/assets/football-scoreboard/shots.json`
and re-render with `python scripts/render_docs_assets.py --plugin
football-scoreboard --check`.

## Troubleshooting

**Nothing appears.** Check that `enabled` is on, and that the league's own
`enabled` is on — `ncaa_fb` is off by default. With
`filtering.show_favorite_teams_only` at its default of `true` and no
`favorite_teams` set, there is nothing to select from.

**I disabled a mode and it still shows.** The keys here are `show_live`,
`show_recent`, and `show_upcoming` — not `live`, `recent`, `upcoming`. A
`display_modes` block copied from another scoreboard sets nothing.

**My team almost never appears.** You probably have an `AP_TOP_*` token in
`favorite_teams` alongside it. The token expands into real teams that compete
for the same slots — see [Dynamic team resolution](#dynamic-team-resolution).

**The same few games keep repeating.** That is the pool cycling. Lower
`other_rotation_interval_seconds` for faster turnover rather than raising the
pool size — a larger pool makes the lap longer, so each game appears less often,
not more.

**Non-favorite games are all obscure matchups.** Set
`game_limits.other_games_min_quality` to `ranked` (its default) for college
football. In the NFL there is no poll, so the setting is inert and every game
qualifies.

**A finished game disappeared too soon.** Raise `schedule_lookback_days`
(default 14), or lower `recent_update_interval` if results are slow to appear.

**Start times look like UTC.** The plugin could not read your global timezone.
Set `timezone` under Advanced Settings to your IANA zone.

**A game I know about never appears.** It may be beyond
`schedule_lookahead_days` (default 7). A game outside that horizon is never
fetched.

## Contributing and license

Issues and pull requests are welcome at
[ChuckBuilds/ledmatrix-plugins](https://github.com/ChuckBuilds/ledmatrix-plugins).
See `LICENSE`.
