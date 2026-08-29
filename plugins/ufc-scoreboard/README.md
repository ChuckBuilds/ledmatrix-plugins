# UFC Scoreboard Plugin

A UFC/MMA plugin for LEDMatrix that displays live, recent, and upcoming
fights with fighter headshots, records, odds, and results.

> Originally contributed by Alex Resnick
> ([@legoguy1000](https://github.com/legoguy1000)) — see
> [PR #137](https://github.com/ChuckBuilds/LEDMatrix/pull/137).

## Features

- **Live fight tracking** — current fights with round and time remaining
- **Recent fights** — results from completed events
- **Upcoming fights** — scheduled cards with start times
- **Fighter headshots** downloaded automatically on first display
- **Records and odds** alongside fighter info
- **Favorite fighters and weight classes** for prioritized display
- No API key required

## Installation

1. Open the LEDMatrix web interface (`http://your-pi-ip:5000`)
2. Open the **Plugin Manager** tab
3. Find **UFC Scoreboard** in the **Plugin Store** section and click
   **Install**
4. Open the plugin's tab in the second nav row to configure favorite
   fighters and weight classes

## Display Modes

The plugin registers three modes in `manifest.json`:

| Mode | Description |
|---|---|
| `ufc_live` | Currently active fights with round/time remaining |
| `ufc_recent` | Recently completed fights with method/round of finish |
| `ufc_upcoming` | Scheduled fights with cards and start times |

## Configuration

The full schema lives in
[`config_schema.json`](config_schema.json) — the web UI form is generated
from it. The most-used keys:

| Key | Default | Notes |
|---|---|---|
| `enabled` | `true` | Master switch |
| `display_duration` | `30` | Seconds per mode |
| `update_interval` | `3600` | Seconds between data fetches |
| `game_display_duration` | `15` | Seconds per individual fight in switch mode |
| `ufc.enabled` | `true` | Toggle UFC content |
| `ufc.favorite_fighters` | `[]` | Array of fighter names to prioritize (e.g. `["Jon Jones", "Islam Makhachev"]`) |
| `ufc.favorite_weight_classes` | `[]` | Weight class abbreviations to prioritize (e.g. `["HW", "LW"]`; see `config_schema.json` for the full list: `LW`, `HW`, `WW`, `MW`, `FW`, `BW`, `FLW`, `LHW`, `WSW`, `WFW`, `WBW`, `WFLW`) |
| `ufc.display_modes.show_live` | `true` | Toggle live mode |
| `ufc.display_modes.show_recent` | `true` | Toggle recent mode |
| `ufc.display_modes.show_upcoming` | `true` | Toggle upcoming mode |
| `ufc.display_modes.live_display_mode` | `"switch"` | `"switch"` (one fight at a time) or `"scroll"` |
| `ufc.display_modes.recent_display_mode` | `"switch"` | Same options for recent mode |

For the full set of nested keys (scroll tuning, display durations,
update intervals, customization fonts/colors), see
[`config_schema.json`](config_schema.json).

### Timezone

- `timezone` (Advanced): IANA name used to display event start times, e.g.
  `America/Chicago`. Leave blank (the default) to follow the LEDMatrix global
  timezone; if that isn't set, the host system's timezone is used, and only if
  neither is available do times fall back to UTC.

## Fighter headshots

On first display the plugin downloads fighter headshots into
`assets/sports/ufc_fighters/`. This requires write access to the
LEDMatrix assets directory and an internet connection. If a headshot
fails to download, the plugin falls back to a placeholder icon.

## Data source

ESPN's public MMA endpoints. No API key required. Be mindful of
`update_interval` — the default of 3600s is suitable for normal use.

## 🎯 Which Fights Get Shown

**`upcoming_games_to_show` is not "how many cards you see".** It is the size of a *pool*. The panel cycles through that pool one card at a time and keeps its place between visits, so a pool of 3 means the board rotates through the same 3 fights until the schedule moves on. Making the number bigger gives you a *longer lap*, so any one fight comes round **less** often.

Which mode you are in depends on whether `ufc.favorite_fighters` is set and whether `ufc.filtering.show_favorite_fighters_only` is on:

| `favorite_fighters` | `show_favorite_fighters_only` | What you get |
|---|---|---|
| empty | either | The next N fights chronologically. Every fight shown is a non-favorite fight, so the two filters below apply to all of them. |
| set | **on** | Only your fighters. The limit is a budget **per fighter**. |
| set | **off** | **Your fighters first, then other fights to fill.** Both limits are **totals**. |

The third row is what most people want, and it did not exist before: with the flag off, favorite fighters used to be ignored *entirely*.

### The settings

| Option | Default | Description |
|---|---|---|
| `upcoming_games_to_show` | varies | How many upcoming fights with a **favorite** fighter to show. |
| `recent_games_to_show` | varies | The same, for finished fights. |
| `other_upcoming_games_to_show` | matches `upcoming_games_to_show` | How many **non-favorite** upcoming fights to add. `0` gives you favorites only. |
| `other_recent_games_to_show` | matches `recent_games_to_show` | The same, for finished fights. |
| `other_rotation_interval_seconds` | `1800` | How often the non-favorite slice advances. `0` pins it. |
| `other_games_min_quality` | `ranked` | Which non-favorite fights qualify: `ranked`, `broadcast`, or `any`. |
| `other_games_divisions` | `["fbs"]` | A college-football setting that this plugin inherits from the shared code — see the note below. |

**Your favorite fighters are never filtered by the last two** — a fighter you follow always appears. Those settings only decide what fills the *remaining* slots.

Within the other-games pool, **the better matchup leads**. The slice is ordered by the best poll position of either side, so a top-five game sits in the first window rather than whichever kicks off soonest; ties fall back to kickoff order, and a league with no poll keeps chronological order. Your favorite teams are ordered by when they play, not by rank -- for your own team the next game is the point.

### Variety comes from turnover

Rather than widening the pool, the non-favorite slice **moves**: the window advances by its own width every `other_rotation_interval_seconds`, so consecutive windows do not overlap and the board works through the card instead of resampling the front of it. Your favorites are not rotated — for upcoming fights the soonest ones are the point.

Both filters **fail open**: if the data behind them cannot be fetched, the fight is allowed through. A board showing filler is a poor board; a board showing nothing is a broken one.

They fail open a second time, as a set: if the filters between them leave **nothing at all** — your teams idle and every other fight rejected — the unfiltered list is used instead. Setting `other_upcoming_games_to_show` or `other_recent_games_to_show` to `0` is the one way to ask for an empty slate, and that is honoured.

> Both `other_games_min_quality` and `other_games_divisions` are inert in this plugin. `ranked` needs a national poll and the division filter needs ESPN's FBS/FCS group rosters; UFC has neither, so every fight passes both, and neither costs a request — no poll is fetched and no division lookup is made. `broadcast` does work here: ESPN carries a broadcaster for UFC cards.


## License

GPL-3.0, same as the LEDMatrix project.

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
`favorite_live_weight` applies when one of your `ufc.favorite_fighters` is in a
live fight, so your fighter's bout comes round more often than other live fights. That distinction
has to be made here rather than in the core, which can tell *that* a game is
live but not *whose*.

Two things to keep in mind:

- The weight is per **plugin**, not per game. With four fights live this
  scoreboard still occupies one slot at a time and picks between its own fights; these weights control how often the scoreboard
  itself comes round.
- More slots make the cycle **longer**, not faster — everything else appears
  proportionally less often. And appearing more often only helps if the data is
  fresh, which is governed by this plugin's own live update interval.
