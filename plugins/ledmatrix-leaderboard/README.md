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

# Leaderboard Plugin

![The NFL standings scrolling across a 256x32 panel: position number, team logo
and abbreviation for each team in
order](../../docs/assets/ledmatrix-leaderboard/hero.png)

*Every image in this README is real plugin output, rendered at the true panel
size from seeded standings so it reproduces exactly. Teams and records are
invented.*

Each team is drawn as **position number, logo, abbreviation**. Records are not
shown for the major leagues — the only place a record replaces the number is
NCAA football with `show_ranking` off, below.

A plugin for LEDMatrix that displays scrolling leaderboards and standings for multiple sports leagues including NFL, NBA, MLB, NCAA Football, NCAA Basketball, NHL, and more.

## Features

- **Multi-Sport Support**: NFL, NBA, MLB, NHL, NCAA Football, NCAA Men's and Women's Basketball, NCAA Men's Hockey, NCAA Baseball
- **Scrolling Ticker Display**: Continuous scrolling of standings and rankings
- **NCAA Rankings**: Poll rank (`#1`) for college football, basketball and hockey
- **Dynamic Duration**: Adjust display time based on content width
- **Live settings**: Changes saved in the web UI apply without a restart

## Configuration

### Global Settings

All of these sit under `global`; the full list is in the [`global`](#global)
table below.

- `update_interval` (top level, default `3600`): seconds between standings
  fetches (300–86400).
- `global.display.scroll_speed` / `global.display.scroll_delay` (defaults `1.0`
  / `0.01`): the scroll speed — see [Scroll speed](#scroll-speed).
- `global.dynamic_duration.*`: size the turn to the length of the ticker
  (default on, 45–600 seconds).
- `global.display_duration` (default `30`): seconds on screen when dynamic
  duration is off.
- `global.scroll_mode` / `global.loop` (defaults `one_shot` / `false`): scroll
  the list once per turn, or loop it.

### Scroll speed

```text
pixels per second = global.display.scroll_speed / global.display.scroll_delay
```

The defaults (1 pixel every 0.01s) give 100 px/s. The LEDMatrix core moves the
figure to the nearest speed the panel can draw in whole pixels (on a 100Hz
panel: 100, 50, 33.3, 66.7 px/s and so on) and logs the result at startup as
`Scroll configured: …`.

### Appearance (`global.appearance`)

The leaderboard renders for a 1:1 LED matrix, where a partially-lit pixel is a
visibly dim LED rather than a smooth edge. These options control that:

- `pixel_perfect_text` (default `true`): draw text with anti-aliasing off, so
  every glyph pixel is fully on or fully off. Set to `false` for the older,
  softer look.
- `crisp_logos` (default `true`): give logos hard edges instead of a ring of
  half-lit pixels.
- `text_outline` (default `true`): black outline behind text so it stays
  readable where it sits near a logo.
- `logo_scale` (default `1.0`): logo height as a fraction of the panel height.
  `1.0` fits the panel exactly; anything above `1.0` crops the top and bottom of
  every logo.
- `font_size` (default `0` = pick a size for the panel height): sizes are
  snapped to the font's pixel grid — multiples of 8 for Press Start 2P — because
  off-grid sizes are what make pixel fonts look blurry.

### How many teams are shown

Each league's `top_teams` sets how far down the standings to go. **Set it to `0`
to show every team the league returns** (all 32 NFL teams, the full AP Top 25,
and so on).

A longer list needs proportionally more time on screen. The display controller
gives the plugin `min(plugin cap, core cap)` seconds and then moves on
mid-scroll, so a list longer than that budget simply stops partway through —
which looks like the leaderboard cutting off at an arbitrary team. The relevant
settings:

| Setting | Where | Default |
|---|---|---|
| `global.dynamic_duration.max_duration_seconds` | this plugin | 600 |
| `global.dynamic_duration.controller_cap_seconds` | this plugin | 600 |
| `display.dynamic_duration.max_duration_seconds` | LEDMatrix core config | 180 |

The **lowest** of the three wins, so the core's 180s default is usually the one
that decides it. All 32 NFL teams is roughly 3,200px of ticker: about 36s at
the default 100 px/s, or about 70s at 50 px/s.

If the content will not fit the budget, the plugin logs a warning at startup
naming which cap is limiting it and roughly how much of the list will not be
reached. Raise that cap, increase the scroll speed
(`global.display.scroll_speed` / `scroll_delay`), or lower `top_teams`.

### Per-League Settings

Leagues live under `enabled_sports`, one block per league. Every league takes
`enabled` and `top_teams`; the college rankings leagues (`ncaa_fb`,
`ncaam_basketball`, `ncaaw_basketball`, `ncaam_hockey`) also take
`show_ranking`, and `ncaa_baseball` takes `season`, `level` and `sort`. There
are no conference or division filters: each league shows its overall standings
(or poll), top `top_teams` first.

```json
{
  "ledmatrix-leaderboard": {
    "enabled": true,
    "update_interval": 3600,
    "enabled_sports": {
      "nfl": { "enabled": true, "top_teams": 10 },
      "nba": { "enabled": true, "top_teams": 10 },
      "ncaa_fb": { "enabled": true, "top_teams": 25, "show_ranking": true },
      "ncaam_hockey": { "enabled": false, "top_teams": 10, "show_ranking": true }
    },
    "global": {
      "display": { "scroll_speed": 1.0, "scroll_delay": 0.01 },
      "loop": false
    }
  }
}
```

The full key list is in the [`enabled_sports`](#enabled_sports) table below.

### Top level

| Key | Default | Notes |
|---|---|---|
| `enabled` | `false` | Enable or disable the leaderboard plugin. |
| `update_interval` | `3600` | How often to fetch new leaderboard data in seconds (300–86400). While nothing has been fetched yet (for example ESPN was unreachable), the plugin retries every 5 minutes. |

### `global`

| Key | Default | Notes |
|---|---|---|
| `global.display_duration` | `30` | Duration in seconds to display the leaderboard when dynamic duration is off (10–300). |
| `global.request_timeout` | `30` | Request timeout in seconds (5–120). |
| `global.dynamic_duration.enabled` | `true` | Enable dynamic duration based on content width. |
| `global.dynamic_duration.min_duration_seconds` | `45` | Minimum display duration when dynamic duration is enabled (10–300). |
| `global.dynamic_duration.max_duration_seconds` | `600` | Maximum display duration when dynamic duration is enabled (30–1200). |
| `global.dynamic_duration.buffer_ratio` | `0.1` | Extra buffer applied to the calculated duration (percentage expressed as 0-1). |
| `global.dynamic_duration.controller_cap_seconds` | `600` | Failsafe cap for the display controller when dynamic duration is enabled (60–1800). |
| `global.min_duration` | `45` | [Deprecated] Use dynamic_duration.min_duration_seconds instead (10–300). |
| `global.max_duration` | `600` | [Deprecated] Use dynamic_duration.max_duration_seconds instead (30–1200). |
| `global.duration_buffer` | `0.1` | [Deprecated] Use dynamic_duration.buffer_ratio instead (0.01–1.0). |
| `global.max_display_time` | `600` | [Deprecated] Use dynamic_duration.controller_cap_seconds instead (60–1800). |
| `global.display.scroll_speed` | `1.0` | Pixels moved per scroll step (0.5–5.0). Speed is `scroll_speed / scroll_delay` px/s — see [Scroll speed](#scroll-speed). |
| `global.display.scroll_delay` | `0.01` | Seconds per scroll step (0.001–0.1). |
| `global.scroll_mode` | `"one_shot"` | Scrolling mode — one of `one_shot`, `continuous`. |
| `global.loop` | `false` | Continuously loop the leaderboard. |

Removed in 1.5.0 because nothing read them: `global.scroll_speed`,
`global.scroll_delay`, `global.scroll_pixels_per_second`, `global.target_fps`,
`global.scroll_target_fps`, `global.scroll_speed_scale`,
`global.scroll_direction`, `global.enable_scroll_metrics`, and the top-level
`display_duration`. A config that still has them loads with a schema warning
until it is next saved from the web UI.
| `global.appearance.pixel_perfect_text` | `true` | Render text with hard pixel edges. Disable only if you prefer the older anti-aliased (softer, blurrier) look. |
| `global.appearance.crisp_logos` | `true` | Give logos hard edges instead of a ring of half-lit pixels. |
| `global.appearance.text_outline` | `true` | Draw a black outline around text so it stays readable over logos. |
| `global.appearance.logo_scale` | `1.0` | Logo height as a fraction of the panel height. 1.0 fits the panel exactly; above 1.0 crops the top and bottom of every logo (0.5–1.5). |
| `global.appearance.font_size` | `0` | Font size in pixels. 0 picks a size that suits the panel height. Values are snapped to the font's pixel grid (multiples of 8 for Press Start 2P) to keep text sharp (0–32). |

### `enabled_sports`

Each league takes the same four or five keys.

| Key | Default | Notes |
|---|---|---|
| `enabled_sports.nfl.enabled` | `true` | Enable NFL standings. |
| `enabled_sports.nfl.top_teams` | `10` | Number of top NFL teams to display. 0 shows every team the standings return (up to 32). Long lists need a matching display duration - see the README (0–32). |
| `enabled_sports.nba.enabled` | `true` | Enable NBA standings. |
| `enabled_sports.nba.top_teams` | `10` | Number of top NBA teams to display. 0 shows every team the standings return (up to 30). Long lists need a matching display duration - see the README (0–30). |
| `enabled_sports.mlb.enabled` | `true` | Enable MLB standings. |
| `enabled_sports.mlb.top_teams` | `10` | Number of top MLB teams to display. 0 shows every team the standings return (up to 30). Long lists need a matching display duration - see the README (0–30). |
| `enabled_sports.ncaa_fb.enabled` | `true` | Enable NCAA Football rankings. |
| `enabled_sports.ncaa_fb.top_teams` | `25` | Number of top NCAA Football teams to display. 0 shows every team the standings return (up to 130). Long lists need a matching display duration - see the README (0–130). |
| `enabled_sports.ncaa_fb.show_ranking` | `true` | Show NCAA Football rankings instead of standings. |
| `enabled_sports.nhl.enabled` | `true` | Enable NHL standings. |
| `enabled_sports.nhl.top_teams` | `10` | Number of top NHL teams to display. 0 shows every team the standings return (up to 32). Long lists need a matching display duration - see the README (0–32). |
| `enabled_sports.ncaam_basketball.enabled` | `false` | Enable NCAA Men's Basketball rankings. |
| `enabled_sports.ncaam_basketball.top_teams` | `25` | Number of top NCAA Men's Basketball teams to display. 0 shows every team the standings return (up to 350). Long lists need a matching display duration - see the README (0–350). |
| `enabled_sports.ncaam_basketball.show_ranking` | `true` | Show rankings/seeds instead of sequential numbering. During March Madness, automatically shows tournament seeds. |
| `enabled_sports.ncaam_hockey.enabled` | `false` | Enable NCAA Men's Hockey rankings. |
| `enabled_sports.ncaam_hockey.top_teams` | `10` | Number of top NCAA Men's Hockey teams to display. 0 shows every team the standings return (up to 60). Long lists need a matching display duration - see the README (0–60). |
| `enabled_sports.ncaam_hockey.show_ranking` | `true` | Show the poll rank (`#1`) instead of sequential numbering. |
| `enabled_sports.ncaaw_basketball.enabled` | `false` | Enable NCAA Women's Basketball rankings. |
| `enabled_sports.ncaaw_basketball.top_teams` | `25` | Number of top NCAA Women's Basketball teams to display. 0 shows every team the standings return (up to 350). Long lists need a matching display duration - see the README (0–350). |
| `enabled_sports.ncaaw_basketball.show_ranking` | `true` | Show rankings/seeds instead of sequential numbering. During March Madness, automatically shows tournament seeds. |
| `enabled_sports.ncaa_baseball.enabled` | `false` | Enable NCAA Baseball standings. |
| `enabled_sports.ncaa_baseball.top_teams` | `25` | Number of top NCAA Baseball teams to display. 0 shows every team the standings return (up to 350). Long lists need a matching display duration - see the README (0–350). |
| `enabled_sports.ncaa_baseball.season` | — | Season identifier (e.g. '2026'). Omit to use the current ESPN season. |
| `enabled_sports.ncaa_baseball.level` | `1` | Competition level (1 = Division I, 2 = Division II, 3 = Division III) (1–3). |
| `enabled_sports.ncaa_baseball.sort` | `"winpercent:desc,gamesbehind:asc"` | Sort key and order for standings. |


### What the settings look like

![text_outline and logo_scale](../../docs/assets/ledmatrix-leaderboard/appearance.png)

`show_ranking` is the one setting that changes *what information* appears
rather than how it looks. For college basketball and hockey it swaps the
position number for the poll rank; for NCAA football, turning it off shows each
team's record instead:

![show_ranking on and off](../../docs/assets/ledmatrix-leaderboard/ncaa-ranking.png)

![The same standings on four panel sizes](../../docs/assets/ledmatrix-leaderboard/panel-sizes.png)

## Display Format

Each team is drawn as a scrolling group of:

- **Position or rank**: `1.`, `2.` … in standings order, or the poll rank
  (`#1`) for the college rankings leagues with `show_ranking` on
- **Team logo**
- **Abbreviation**

The only place a record appears is NCAA football with `show_ranking` off, where
it replaces the number.

## Supported Leagues

The plugin supports the following sports leagues (the `enabled_sports` keys):

- **nfl**, **nba**, **mlb**, **nhl**: overall league standings, best win
  percentage first
- **ncaa_fb**: NCAA Football AP poll (records with `show_ranking` off)
- **ncaam_basketball**, **ncaaw_basketball**: NCAA Basketball polls, or
  tournament seeds during March Madness
- **ncaam_hockey**: NCAA Men's Hockey poll
- **ncaa_baseball**: NCAA Baseball standings

## Data fetching

- Standings are fetched in `update()`, never while drawing, and cached.
- Requests time out after `global.request_timeout` seconds (default 30); there
  are no automatic retries within a fetch.
- Fetches run every `update_interval` seconds (default one hour). Until the
  first successful fetch the panel shows "No Leaderboard Data" and the plugin
  tries again every 5 minutes.

## Data Sources

Standings and rankings data is fetched from ESPN's public API endpoints for all supported leagues.

## Dependencies

This plugin requires the main LEDMatrix installation and uses the cache manager for data storage.

## Installation

The easiest way is the Plugin Store in the LEDMatrix web UI:

1. Open `http://your-pi-ip:5000`
2. Open the **Plugin Manager** tab
3. Find **Sports Leaderboard** in the **Plugin Store** section and click
   **Install**
4. Open the plugin's tab in the second nav row to configure leagues and
   display options

Manual install: copy this directory into your LEDMatrix
`plugins_directory` (default `plugin-repos/`) and restart the display
service.

## Troubleshooting

- **No standings showing**: Check if leagues are enabled and API endpoints are accessible
- **Missing team information**: Ensure standings data is available for the selected leagues
- **Slow scrolling**: Adjust scroll speed and delay settings
- **API errors**: Check your internet connection and ESPN API availability

## Advanced Features

- **Dynamic Duration**: Automatically adjusts display time based on content width
- **Conference Filtering**: Filter standings by conference or division
- **NCAA Rankings**: Display college football and basketball rankings
- **Team Records**: Show detailed win-loss records and statistics
- **Continuous Loop**: Optionally loop the leaderboard continuously

## Performance Notes

- The plugin is designed to be lightweight and not impact display performance
- Background fetching ensures smooth scrolling without blocking
- Configurable update intervals balance freshness vs. API load
