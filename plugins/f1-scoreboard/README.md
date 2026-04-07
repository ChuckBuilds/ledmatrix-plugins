# F1 Scoreboard Plugin

A Formula 1 plugin for LEDMatrix that displays driver and constructor
standings, race results, qualifying and practice times, sprint results,
upcoming races, and the season calendar — with team-colored visuals and
favorite-driver/team highlighting.

Data comes from the public ESPN F1 endpoints; no API key is required.

## Features

- **Driver standings** with optional always-show-favorite
- **Constructor standings** with team colors
- **Recent races** with podium and your favorite's finish
- **Upcoming race** card with countdown and session times
- **Qualifying** results (Q1 / Q2 / Q3 with gaps)
- **Practice** sessions (FP1 / FP2 / FP3) with configurable depth
- **Sprint** results
- **Season calendar** with optional sprint/qualifying flags
- Per-element font and color customization
- No API key required

## Installation

1. Open the LEDMatrix web interface (`http://your-pi-ip:5000`)
2. Open the **Plugin Manager** tab
3. Find **F1 Scoreboard** in the **Plugin Store** section and click
   **Install**
4. Open the plugin's tab in the second nav row to configure your
   favorite driver/team and toggle which sections appear

## Display Modes

The plugin registers eight granular modes in `manifest.json`. The
display controller rotates through any that are enabled in your config:

| Mode | Section |
|---|---|
| `f1_driver_standings` | Driver standings |
| `f1_constructor_standings` | Constructor standings |
| `f1_recent_races` | Recent race results |
| `f1_upcoming` | Next race card with countdown |
| `f1_qualifying` | Qualifying session results |
| `f1_practice` | Practice session standings |
| `f1_sprint` | Sprint race results |
| `f1_calendar` | Season schedule overview |

## Configuration

The full schema lives in
[`config_schema.json`](config_schema.json) — the web UI form is generated
from it. The most-used keys:

| Key | Default | Notes |
|---|---|---|
| `enabled` | `true` | Master switch |
| `display_duration` | `30` | Seconds per section |
| `update_interval` | `3600` | Seconds between data fetches |
| `favorite_team` | `""` | Constructor abbreviation (e.g. `MER`, `RBR`) |
| `favorite_driver` | `""` | Driver code (e.g. `VER`, `HAM`, `LEC`) |
| `driver_standings.enabled` | `true` | Toggle driver standings mode |
| `driver_standings.top_n` | `10` | How many drivers to show |
| `driver_standings.always_show_favorite` | `true` | Always include your favorite even if outside top N |
| `constructor_standings.*` | mirrors `driver_standings.*` | |
| `recent_races.number_of_races` | `3` | How many past races to cycle through |
| `recent_races.top_finishers` | `3` | Top N finishers per race |
| `upcoming.show_session_times` | `true` | Show practice/qualifying/race times |
| `upcoming.countdown_enabled` | `true` | Live countdown to next race |
| `qualifying.show_q1` / `show_q2` / `show_q3` | `true` | Toggle each Q session |
| `qualifying.show_gaps` | `true` | Show gap to pole |
| `practice.sessions_to_show` | `["FP1","FP2","FP3"]` | Which practice sessions to render |
| `practice.top_n` | `10` | Drivers per practice session |
| `sprint.top_finishers` | `10` | Sprint result depth |
| `calendar.max_events` | `5` | Races per calendar view |
| `calendar.show_practice` / `show_qualifying` / `show_sprint` | varies | Calendar detail toggles |
| `dynamic_duration.enabled` | `true` | Cycle through more content per slot |
| `dynamic_duration.max_duration_seconds` | `120` | Cap for dynamic-duration sessions |
| `scroll.scroll_speed` / `scroll.scroll_delay` | `1` / `0.03` | Scroll tuning |
| `customization.*` | various | Per-element font and color overrides |

### Driver / team codes

Use the standard F1 three-letter codes:

- **Drivers**: `VER`, `HAM`, `LEC`, `NOR`, `RUS`, `SAI`, `PER`, `ALO`, etc.
- **Constructors**: `MER` (Mercedes), `RBR` (Red Bull), `FER` (Ferrari),
  `MCL` (McLaren), `AST` (Aston Martin), `ALP` (Alpine), `WIL` (Williams),
  `STA` (Stake), `RB`, `HAA` (Haas)

## Data source

ESPN's public Formula 1 endpoints. No API key required. Cached locally
to keep request volume low — adjust `update_interval` if you need fresher
data.

## License

GPL-3.0, same as the LEDMatrix project.
