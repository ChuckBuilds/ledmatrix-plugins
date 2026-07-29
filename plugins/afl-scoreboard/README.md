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
