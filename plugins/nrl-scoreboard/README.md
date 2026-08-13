# NRL Scoreboard Plugin

Live, recent, and upcoming **NRL (National Rugby League)** games on your
LEDMatrix display, sourced from ESPN's public rugby-league API (no API key
required).

This plugin is a single-league fork of the `soccer-scoreboard` plugin and keeps
full feature parity: switch or scroll display, live-game priority, goal/win
celebrations, dynamic per-mode durations, and Vegas continuous-scroll support.

## Display Modes

The plugin exposes three display modes you can enable independently:

- `nrl_live` — games currently in progress (running clock, 1H/2H/HALF/ET)
- `nrl_recent` — recently completed games with final scores
- `nrl_upcoming` — scheduled games with date/time

Each mode can be shown as **switch** (one game at a time, timed) or **scroll**
(all games scroll horizontally at high FPS).

## Data Source & the `3` league-slug quirk

Games come from:

```
https://site.api.espn.com/apis/site/v2/sports/rugby-league/3/scoreboard
```

Note the `3` in the path. That is **ESPN's internal numeric slug for the NRL**
under the `rugby-league` sport — it is *not* a typo and must **not** be changed
to `nrl`. The human-facing web path is `/nrl/`, but the API path segment is the
literal string `3` (confirmed via
`site.web.api.espn.com/apis/v2/scoreboard/header?sport=rugby-league`, which lists
NRL as `id:8370, abbreviation:"NRL", slug:"3"`). Changing `3` to `nrl` makes the
endpoint 404 and the plugin silently stops fetching games. The code marks every
point where `3` is used with a comment to protect against this.

## Scoring & period model

NRL is played over two 40-minute halves (not quarters). ESPN reports
`status.period` as `1` or `2` and a running `displayClock` that counts **up** in
minutes (e.g. `40'`, `80'`), just like soccer. The plugin renders period text as:

- `1H` / `2H` — first / second half (with the running clock, e.g. `2H 63'`)
- `HALF` — half-time
- `ET` — golden-point extra time (period ≥ 3)
- `Final` — completed game
- start time — upcoming games

Each team has a single running integer score (the ESPN `score` field).

## Team logos

Team logos are downloaded automatically from ESPN's CDN and cached locally —
there are no bundled logo assets to manage. If a download fails, a text
placeholder is generated from the team abbreviation.

## Configuration

Configuration lives under the `nrl-scoreboard` key in `config/config.json`. Key
options (see `config_schema.json` for the full list, types, and defaults):

| Key | Description |
|---|---|
| `enabled` | Master on/off switch |
| `favorite_teams` | List of favorite NRL teams to prioritize. Use the full team name (e.g. `"Newcastle Knights"`) or ESPN team ID, **not** the 3-letter abbreviation — some abbreviations are shared by two teams (`NEW` is both Newcastle Knights and New Zealand Warriors; `CAN` is both Canberra Raiders and Canterbury Bulldogs). A shared abbreviation is left unresolved (logged as an error) rather than being matched to either team |
| `exclude_teams` | Teams to hide (spoiler protection). Same name/ID guidance as `favorite_teams` |
| `display_modes` | Toggle `live`/`recent`/`upcoming` and set `*_display_mode` to `switch` or `scroll` |
| `live_priority` | Interrupt the rotation to show live games immediately |
| `live_game_duration` / `recent_game_duration` / `upcoming_game_duration` | Per-game on-screen time (seconds) |
| `non_favorite_live_game_duration` | Shorter turn for live games without a favorite team |
| `recent_games_to_show` / `upcoming_games_to_show` | How many games per mode |
| `show_records` / `show_odds` / `show_ranking` | Extra info overlays |
| `celebration_enabled` / `celebration_duration` | Goal/win celebration takeover |
| `dynamic_duration` | Auto-size mode duration from the number of games |
| `mode_durations` | Fixed total time per mode |
| `update_interval_seconds` / `live_update_interval` | Data refresh cadence |
| `background_service` | Fetch timeout / retries / priority |
| `customization` | Fonts, colors, and layout for the scorebug |

### Example

```json
{
  "nrl-scoreboard": {
    "enabled": true,
    "favorite_teams": ["Penrith Panthers", "Brisbane Broncos"],
    "display_modes": {
      "live": true,
      "live_display_mode": "switch",
      "recent": true,
      "recent_display_mode": "scroll",
      "upcoming": true,
      "upcoming_display_mode": "scroll"
    },
    "live_priority": true,
    "recent_games_to_show": 3,
    "upcoming_games_to_show": 5
  }
}
```

### Timezone

- `timezone` (Advanced): IANA name used to display event start times, e.g.
  `America/Chicago`. Leave blank (the default) to follow the LEDMatrix global
  timezone; if that isn't set, the host system's timezone is used, and only if
  neither is available do times fall back to UTC.

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

## License

See `LICENSE`.

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
