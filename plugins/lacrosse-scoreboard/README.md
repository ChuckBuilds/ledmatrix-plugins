# Lacrosse Scoreboard Plugin

Live, recent, and upcoming NCAA Men's and Women's Lacrosse games on your LEDMatrix display. Real-time scores, schedules, favorite-team filtering, live-game priority, poll-rank badges, and both switch and scroll display modes — modeled on the existing hockey scoreboard plugin.

> **Breaking change in 1.1.0:** display modes gained a `lax_` prefix
> (e.g. `lax_ncaa_mens_recent`) to avoid colliding with the NCAA
> hockey modes exposed by `hockey-scoreboard`. If you pinned any of
> the old `ncaa_mens_*` / `ncaa_womens_*` names in
> `display_durations`, `rotation_order`, or anywhere else in
> `config.json`, update them to the new prefixed names. See the
> plugin [CHANGELOG](CHANGELOG.md) for the full mapping.

## Features

- **NCAA Men's Lacrosse** (Inside Lacrosse D1 Poll — top 20)
- **NCAA Women's Lacrosse** (Inside Lacrosse / IWLCA Coaches Top 25 Poll)
- **Live games** with quarter, clock, score, and optional shot totals
- **Recent (completed) games** with final score and OT indicator
- **Upcoming games** with start time, matchup, records, and rankings
- **Favorite team filtering** — pin specific teams, or use the dynamic shortcuts `NCAA_MENS_TOP_20`, `NCAA_MENS_TOP_10`, `NCAA_MENS_TOP_5`, `NCAA_WOMENS_TOP_25`, `NCAA_WOMENS_TOP_10`, `NCAA_WOMENS_TOP_5` to auto-track whichever teams are currently in the poll
- **Live priority** — force live favorite-team games to preempt the rotation
- **Per-mode display style** — `switch` (one game card rotating) or `scroll` (horizontal ticker), independently configurable for live, recent, and upcoming
- **Poll rank badges** — `#1`, `#2` overlays on team names, updated hourly from ESPN's public rankings feed
- **Element customization** — toggle records, rankings, odds, shot totals; override layout offsets for logos, score, and status text
- **Configurable durations, update intervals, and game counts** per league
- **Favorite Team Result Colors**: Optionally show a finished game's score in green when your favorite team won and red when it lost

## Requirements

- Python 3.9+
- LEDMatrix core 2.0.0 or newer
- A minimum display of 64×32 (128×32 recommended for full scroll and scoreboard layouts)
- Internet access to reach the public ESPN API

No API key is required.

## Installation

The easiest way is the Plugin Store in the LEDMatrix web UI:

1. Open `http://your-pi-ip:5000`
2. Open the **Plugin Manager** tab
3. Find **Lacrosse Scoreboard** in the **Plugin Store** section and click
   **Install**
4. Open the plugin's tab in the second nav row to configure favorite
   teams

On first launch, team logos for any teams in the current scoreboard
window will be downloaded to `assets/sports/ncaa_logos/` automatically.

Manual install from source:

```bash
cd /path/to/LEDMatrix
python -m pip install --user pillow requests pytz   # see requirements.txt
cp -r /path/to/ledmatrix-plugins/plugins/lacrosse-scoreboard plugin-repos/
sudo systemctl restart ledmatrix
```

Then add a `lacrosse-scoreboard` entry to your LEDMatrix `config.json`
(see **Configuration** below) — or just use the web UI to configure it.

## Dependencies

From `requirements.txt`:

- `Pillow>=9.0.0` — image compositing and logo rendering
- `requests>=2.28.0` — ESPN API calls
- `pytz>=2022.1` — timezone conversion for game start times
- `urllib3>=1.26.0` — HTTP retry logic

All dependencies are standard and already present in a typical LEDMatrix install.

## Configuration

The plugin config is split into per-league blocks. See `config_schema.json` for the authoritative list of fields and their defaults. Minimal working example:

```json
{
  "enabled": true,
  "defaults": {
    "display_duration": 15,
    "show_records": true,
    "show_ranking": true,
    "show_odds": false
  },
  "ncaa_mens": {
    "enabled": true,
    "display_modes": {
      "live": true,
      "live_display_mode": "switch",
      "recent": true,
      "recent_display_mode": "scroll",
      "upcoming": true,
      "upcoming_display_mode": "scroll"
    },
    "teams": {
      "favorite_teams": ["NCAA_MENS_TOP_10", "JOHNS HOPKINS"],
      "favorite_teams_only": false,
      "show_all_live": true,
      "exclude_teams": [],
      "favorite_live_boost": 2
    },
    "filtering": {
      "recent_games_to_show": 5,
      "upcoming_games_to_show": 10
    },
    "live_priority": true
  },
  "ncaa_womens": {
    "enabled": true,
    "display_modes": {
      "live": true,
      "live_display_mode": "switch",
      "recent": true,
      "recent_display_mode": "scroll",
      "upcoming": true,
      "upcoming_display_mode": "scroll"
    },
    "teams": {
      "favorite_teams": ["MARYLAND", "NORTH CAROLINA", "SYRACUSE"],
      "favorite_teams_only": false,
      "show_all_live": true
    }
  }
}
```

### Display modes per league

Each of live / recent / upcoming can be independently enabled and given its own display style:

- `switch` — one game card at a time, rotating on a timer
- `scroll` — all matching games composited into a horizontal ticker that scrolls across the display

### Live priority

When `live_priority: true`, live games for configured favorite teams will interrupt the normal rotation whenever they are in progress.

### Favorite live boost

`teams.favorite_live_boost` (default `2`, range `1`-`5`) tunes how much extra
attention your favorite team gets *within* the live rotation itself: while a
favorite's game is live, it's always queued first whenever the rotation
refreshes, and gets that many turns for every 1 turn other live games get
(e.g. `favorite_live_boost: 2` with your favorite plus two other live games
rotates `[favorite, other1, favorite, other2]`). It never interrupts a game
already on screen — it just gets more/sooner turns. Set it to `1` for a
perfectly even rotation (the pre-1.3.0 default behavior). This is independent
of `live_priority`, which controls whether live games preempt the
recent/upcoming rotation at all.

### Shorter dwell for non-favorite live games

`display_durations.non_favorite_live` (0-120, default `0` = off) gives live
games that involve **none** of your favorite teams a shorter on-screen turn than
your favorites. For example `ncaa_mens.display_durations.live: 30` with
`ncaa_mens.display_durations.non_favorite_live: 5` shows your teams for 30s each
while everyone else's games flash by in 5s.

This **only takes effect** when favorite teams are configured **and**
non-favorite live games are being shown — `favorite_teams_only` off, or
`show_all_live` on (otherwise non-favorite games are never on screen to
shorten). Leave it at `0` to display every live game for `display_durations.live`.

| Favorite teams set? | Non-favorite games shown? | Live game has a favorite? | Duration used |
|---|---|---|---|
| No | — | — | `display_durations.live` (unchanged) |
| Yes | No (`favorite_teams_only` on, `show_all_live` off) | favorite | `display_durations.live` |
| Yes | Yes (`favorite_teams_only` off, or `show_all_live` on) | favorite | `display_durations.live` |
| Yes | Yes (`favorite_teams_only` off, or `show_all_live` on) | none | `display_durations.non_favorite_live` (when > 0) |

### Excluding teams (spoiler protection)

`teams.exclude_teams` (default `[]`) hides specific teams from **both** the
live rotation and the recent/final-scores display — useful if you plan to
watch a game delayed and don't want the score spoiled. It uses the same
full-name abbreviation format as `favorite_teams` (see below), and always
wins if a team appears in both lists.

### Timezone

- `timezone` (Advanced): IANA name used to display event start times, e.g.
  `America/Chicago`. Leave blank (the default) to follow the LEDMatrix global
  timezone; if that isn't set, the host system's timezone is used, and only if
  neither is available do times fall back to UTC.

## Team Abbreviations

**Important — NCAA lacrosse uses full-name abbreviations, not the short codes you may be used to from the football, basketball, or hockey plugins.** ESPN's lacrosse feed returns team abbreviations like `NORTH CAROLINA`, `JOHNS HOPKINS`, `SAINT JOSEPH'S`, not `UNC` / `JHU` / `SJU`. Use the full-name form in `favorite_teams` or the matching will fail silently.

A few recurring examples (use exactly as shown, uppercase, with spaces, apostrophes, and periods as they appear):

| Team | Abbreviation |
|---|---|
| Maryland | `MARYLAND` |
| North Carolina | `NORTH CAROLINA` |
| Syracuse | `SYRACUSE` |
| Johns Hopkins | `JOHNS HOPKINS` |
| Duke | `DUKE` |
| Notre Dame | `NOTRE DAME` |
| Princeton | `PRINCETON` |
| Virginia | `VIRGINIA` |
| Yale | `YALE` |
| Harvard | `HARVARD` |
| Cornell | `CORNELL` |
| Penn State | `PENN STATE` |
| Richmond | `RICHMOND` |
| Saint Joseph's | `SAINT JOSEPH'S` |
| Mount St. Mary's | `MOUNT ST. MARY'S` |
| William & Mary | `WILLIAM & MARY` |
| Long Island University | `LONG ISLAND UNIVERSI` *(ESPN truncates to 20 chars)* |

If you're unsure of a team's exact abbreviation, hit the ESPN scoreboard endpoint directly and look at `events[].competitions[].competitors[].team.abbreviation`:

```bash
curl -s 'https://site.api.espn.com/apis/site/v2/sports/lacrosse/mens-college-lacrosse/scoreboard' \
  | python -m json.tool | grep -A1 abbreviation
```

### Dynamic team shortcuts

Instead of listing abbreviations manually, use one of these tokens in `favorite_teams` to auto-expand to the current poll:

| Token | League | Expands to |
|---|---|---|
| `NCAA_MENS_TOP_5` | Men's | Top 5 of Inside Lacrosse D1 Men's Poll |
| `NCAA_MENS_TOP_10` | Men's | Top 10 of Inside Lacrosse D1 Men's Poll |
| `NCAA_MENS_TOP_20` | Men's | Full top 20 (the entire men's poll) |
| `NCAA_WOMENS_TOP_5` | Women's | Top 5 of IWLCA Coaches Poll |
| `NCAA_WOMENS_TOP_10` | Women's | Top 10 of IWLCA Coaches Poll |
| `NCAA_WOMENS_TOP_25` | Women's | Full top 25 |

Tokens can be mixed with literal abbreviations: `["NCAA_MENS_TOP_10", "JOHNS HOPKINS", "PRINCETON"]` tracks the current top 10 *plus* any of those two teams that aren't already in it.

## Display Modes (plugin-level)

The plugin exposes six granular display modes the LEDMatrix host rotation can cycle through:

- `lax_ncaa_mens_live`, `lax_ncaa_mens_recent`, `lax_ncaa_mens_upcoming`
- `lax_ncaa_womens_live`, `lax_ncaa_womens_recent`, `lax_ncaa_womens_upcoming`

## Data Source

Scores and schedules come from ESPN's public site API:

- Men's scoreboard: `https://site.api.espn.com/apis/site/v2/sports/lacrosse/mens-college-lacrosse/scoreboard`
- Men's rankings: `https://site.api.espn.com/apis/site/v2/sports/lacrosse/mens-college-lacrosse/rankings`
- Women's scoreboard: `https://site.api.espn.com/apis/site/v2/sports/lacrosse/womens-college-lacrosse/scoreboard`
- Women's rankings: `https://site.api.espn.com/apis/site/v2/sports/lacrosse/womens-college-lacrosse/rankings`

Team logos are fetched from `https://a.espncdn.com/i/teamlogos/ncaa/500/{team_id}.png` and cached locally under `assets/sports/ncaa_logos/`.

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
**My favorite team doesn't show up.** You're almost certainly using a short abbreviation like `UNC` or `JHU`. Lacrosse abbreviations are the full school name in uppercase — see **Team Abbreviations** above.

**No games appear at all.** NCAA lacrosse is a spring sport. Men's runs roughly January through late May; women's runs February through late May. Outside that window, the ESPN scoreboard endpoint returns an empty `events[]` array and the plugin has nothing to display.

**Rank badges (`#1`, `#2`) aren't appearing.** Ensure `display_options.show_ranking: true` (the default). Rankings are cached for 1 hour and are only populated for teams that appear in the current poll. Unranked teams show no badge, which is intentional.

**Shot totals are always 0.** ESPN's lacrosse feed does not currently expose per-team shot counts in the `competitors[].statistics` array the way hockey does for saves. The `show_shots` toggle is wired but will remain empty until ESPN publishes the stat. Leave it off for now.

**Tournament games show `TBD` placeholders.** ESPN uses team IDs `-1` and `-2` for bracket slots where the opponent hasn't been determined yet. The plugin renders these as text placeholders — they'll resolve to real logos once the bracket is set.

**A team's logo is missing or looks wrong.** Delete the cached logo at `assets/sports/ncaa_logos/{ABBR}.png` (use the exact file name, spaces and all) and the plugin will re-download it from ESPN on the next update.

## Testing

A standalone smoke test is included at `test_lacrosse_plugin.py`:

```bash
cd plugins/lacrosse-scoreboard
python test_lacrosse_plugin.py
```

It stubs the LEDMatrix host modules, imports every plugin module, exercises the dynamic team resolver against live ESPN rankings, and runs a 50-event window of both men's and women's scoreboard data through `Lacrosse._extract_game_details`, asserting that required fields are populated. No external test framework is required.

## License

See `LICENSE` in this directory.

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
