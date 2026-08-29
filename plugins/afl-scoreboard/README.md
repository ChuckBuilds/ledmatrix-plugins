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

# AFL Scoreboard Plugin

A plugin for LEDMatrix that displays live, recent, and upcoming **AFL (Australian
Football League)** games with real-time scores and game status.

## Features

- **Live Game Tracking**: Real-time scores, quarter (Q1–Q4), and running clock
- **Recent Games**: Recently completed games with final scores
- **Upcoming Games**: Scheduled games with start times
- **Favorite Teams**: Prioritize (or exclusively show) games involving your favorite teams
- **Switch or Scroll**: Show one game at a time, or scroll all games horizontally
- **Dynamic Duration & Live Priority**: Spend more time on live games; let live games interrupt the rotation
- **Background Data Fetching**: Efficient API calls without blocking the display
- **Favorite Team Result Colors**: Optionally show a finished game's score in green when your favorite team won and red when it lost

## Display Modes

The plugin exposes three display modes:

1. **afl_live** — currently active games (quarter + clock)
2. **afl_recent** — recently completed games with final scores
3. **afl_upcoming** — scheduled upcoming games with start times

During a live game the status area shows:

- **Q1 / Q2 / Q3 / Q4** — the current quarter, followed by the running clock (e.g. `Q3 12:45`)
- **HALF** — the main break after the second quarter
- **Final** — completed game
- the scheduled start time for upcoming games

## Configuration

AFL is a single league, so all settings live at the top level of the plugin
config (there is no per-league nesting).

```json
{
  "enabled": true,
  "favorite_teams": ["COLL", "GEEL", "RICH"],
  "exclude_teams": [],
  "show_favorite_teams_only": false,
  "display_modes": {
    "live": true,
    "recent": true,
    "upcoming": true,
    "live_display_mode": "switch",
    "recent_display_mode": "switch",
    "upcoming_display_mode": "switch"
  },
  "display_duration": 30,
  "live_game_duration": 20,
  "non_favorite_live_game_duration": 0,
  "recent_game_duration": 15,
  "upcoming_game_duration": 15,
  "recent_games_to_show": 5,
  "upcoming_games_to_show": 10,
  "update_interval_seconds": 300,
  "live_update_interval": 30,
  "show_records": false,
  "show_odds": false,
  "live_priority": false,
  "celebration_enabled": true,
  "celebration_duration": 8
}
```

### Key settings

| Setting | Default | Effect |
|---|---|---|
| `favorite_teams` | `[]` | AFL team abbreviations to prioritize (e.g. `COLL`, `GEEL`, `RICH`). |
| `exclude_teams` | `[]` | Teams to always hide — from both the live rotation and recent/final scores (spoiler protection). |
| `show_favorite_teams_only` | `false` | Only show games involving `favorite_teams`. |
| `display_modes.*_display_mode` | `switch` | `switch` shows one game at a time; `scroll` scrolls all games horizontally. |
| `display_duration` | `30` | How long each display mode stays on screen before cycling. |
| `live_game_duration` | `20` | Seconds each live game stays on screen. |
| `non_favorite_live_game_duration` | `0` | Shorter dwell for live games with no favorite team (0 = off). |
| `live_priority` | `false` | Let live AFL games interrupt the recent/upcoming rotation. |
| `dynamic_duration` | off | Size a mode's total on-screen time to the number of games it has. |
| `mode_durations` | null | Fix the total duration of each mode (overrides dynamic calculation). |

### Timezone

- `timezone` (Advanced): IANA name used to display event start times, e.g.
  `America/Chicago`. Leave blank (the default) to follow the LEDMatrix global
  timezone; if that isn't set, the host system's timezone is used, and only if
  neither is available do times fall back to UTC.

## Team Names & Abbreviations

The `favorite_teams` / `exclude_teams` fields require the **ESPN API
abbreviation** for each team (e.g. `"COLL"` for Collingwood, `"GEEL"` for
Geelong). Full team names are not supported.

> **Tip:** If you're unsure of an abbreviation, enable debug logging — the plugin
> logs `home_abbr` and `away_abbr` for every game it processes.

## Team Logos

Team logos are downloaded automatically from ESPN's CDN on first use and cached to
disk — no manual asset work is required. If a logo can't be fetched, a generated
text-abbreviation placeholder is drawn instead.

## Data Source

Game data is fetched from ESPN's public AFL scoreboard endpoint (no API key
required):

```
https://site.api.espn.com/apis/site/v2/sports/australian-football/afl/scoreboard
```

## Dependencies

This plugin requires the main LEDMatrix installation and uses the plugin system
base classes.

## Installation

The easiest way is the Plugin Store in the LEDMatrix web UI:

1. Open `http://your-pi-ip:5000`
2. Open the **Plugin Manager** tab
3. Find **AFL Scoreboard** in the **Plugin Store** section and click **Install**
4. Open the plugin's tab in the second nav row to configure favorite teams and
   display modes

Manual install: copy this directory into your LEDMatrix `plugins_directory`
(default `plugin-repos/`) and restart the display service.

## Testing

- `python test_afl_plugin.py` — standalone smoke tests (display modes, mode
  routing, live content, AFL quarter parsing). No network or host required.
- `test/harness.json` — a deterministic fixture (one live, one recent, one
  upcoming game) for the core plugin safety harness
  (`LEDMatrix/scripts/check_plugin.py`).

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
- **No games showing**: Confirm the ESPN endpoint is reachable and that at least
  one display mode is enabled.
- **Missing team logos**: The plugin auto-downloads logos; check the display's
  internet access and logo cache directory permissions.
- **Slow updates**: Adjust `update_interval_seconds` / `live_update_interval`.
- **API errors**: Check your internet connection and ESPN API availability.

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
