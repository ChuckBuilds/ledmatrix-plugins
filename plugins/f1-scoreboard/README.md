# F1 Scoreboard Plugin

![The driver standings scrolling across a 256x32 panel: the F1 mark, a season
progress bar, then a card showing P1 VER for Red Bull with points and
wins](../../docs/assets/f1-scoreboard/hero.png)

*Every image in this README is real plugin output, rendered at the true panel
size from seeded standings so it reproduces exactly. Drivers, teams and points
are invented.*

A Formula 1 plugin for LEDMatrix that displays driver and constructor
standings, race results, qualifying and practice times, sprint results,
upcoming races, and the full season calendar — with team-colored visuals,
circuit map art, championship gap bars, favorite driver/team spotlights,
and a live-session auto-refresh mode.

Data is sourced from public ESPN F1 endpoints, Jolpica/Ergast, and OpenF1.
**No API key required.**

## Features

- **Championship leaders card** — split view of the current driver and constructor leaders with team colors and win counts
- **Driver championship battle card** — P1 vs P2 driver split card with gap in points, races remaining, ALIVE / NEAR / WON closability status, progress bar, and a last-race gap trend indicator (`+N` red = leader extending, `-N` green = challenger closing)
- **Constructor championship battle card** — P1 vs P2 constructor split card with team logos, points gap, races remaining, closability bar, and last-race gap trend indicator
- **Driver form guide card** — compact 2-column grid showing the last N race positions per driver as colored boxes (gold P1, silver P2, bronze P3, green points-finish, red DNF)
- **Driver standings** with championship points gap bars, team-color accents, and last-race `+N` points indicator (gold/green/grey by magnitude)
- **Constructor standings** with team logos, gap bars, per-driver point split (`NOR 189 | PIA 145`), and last-race combined points haul indicator
- **Favorite driver spotlight** — full card for your chosen driver: position, points, gap to leader, team color banner
- **Favorite team spotlight** — team logo, both drivers, constructor position and points
- **Recent race results** — starts with a **winners summary card** listing each recent race winner at a glance; followed by podium cards with winner, P2, P3, gap times, fastest-lap dot, positions-gained delta (`+N`/`-N`), and retirement (`RET`) indicators; plus a **favorite driver highlight card**, a **race gap chart** (team-colored horizontal bars proportional to gap from winner), and a **points haul card** (team-colored bars) per race
- **Upcoming race card** — circuit name, country, date, session times, and circuit layout map art; followed by a **circuit stats card** with laps, distance per lap, total race distance, and the official lap record
- **Qualifying results** — Q1 / Q2 / Q3 breakdown with gap-to-pole times; plus a **team H2H card** showing which driver outqualified their teammate and by how many grid positions
- **Free practice standings** — FP1, FP2, FP3 with lap times
- **Sprint results** — sprint race finishing order and times
- **Season calendar** — upcoming events with color-coded session badges (RACE, QUALI, SPRINT, FP1–3)
- **Standings header card** — F1 logo, season year, round number (Rd N/M), and red season progress bar before each standings section
- **Live session detection** — automatically increases refresh rate when a session is in progress
- Per-element font customization; no API key required

## Installation

1. Open the LEDMatrix web interface (`http://your-pi-ip:5000`)
2. Open the **Plugin Manager** tab
3. Find **F1 Scoreboard** in the **Plugin Store** and click **Install**
4. Open the plugin's config tab to set your favorite driver/team and toggle which sections appear

## Display Modes

The plugin registers eight granular modes. The display controller rotates through any that are enabled in your config:

| Mode | What it shows |
|---|---|
| `f1_driver_standings` | Championship standings with gap bars |
| `f1_constructor_standings` | Constructor standings with team logos |
| `f1_recent_races` | Last 1–10 race results (configurable) |
| `f1_upcoming` | Next race card with circuit map and countdown |
| `f1_qualifying` | Q1 / Q2 / Q3 breakdown |
| `f1_practice` | FP1, FP2, FP3 standings |
| `f1_sprint` | Sprint race results |
| `f1_calendar` | Upcoming race schedule |

## Configuration

The full schema lives in [`config_schema.json`](config_schema.json) — the LEDMatrix web UI generates the form from it automatically. Options are grouped below by section.

### Core settings

| Key | Default | Description |
|---|---|---|
| `enabled` | `true` | Master on/off switch |
| `display_duration` | `30` | Seconds each mode is shown before rotating |
| `update_interval` | `3600` | Seconds between API data refreshes |
| `favorite_driver` | `""` | Your driver's 3-letter code (see below) |
| `favorite_team` | `""` | Your constructor ID (see below) |

### Display modes

Each mode section has an `enabled` toggle and mode-specific options:

| Section | Key | Default | Description |
|---|---|---|---|
| `driver_standings` | `top_n` | `10` | Number of drivers to display |
| `driver_standings` | `always_show_favorite` | `true` | Keep your favorite visible even outside top N |
| `constructor_standings` | `top_n` | `10` | Number of constructors to display |
| `constructor_standings` | `always_show_favorite` | `true` | Keep favorite team visible |
| `constructor_standings` | `show_driver_split` | `true` | Show individual driver point contributions on each constructor card |
| `recent_races` | `number_of_races` | `3` | Past races to cycle through (1–10) |
| `recent_races` | `top_finishers` | `3` | Podium depth per race (1–20) |
| `recent_races` | `always_show_favorite` | `true` | Append favorite driver even outside top N |
| `recent_races` | `show_position_delta` | `true` | Show `+N`/`-N` positions gained/lost vs grid in green/red |
| `recent_races` | `show_dnf_status` | `true` | Show `RET` or `+NL` for retirements and lapped finishers |
| `recent_races` | `show_points_haul` | `true` | Show a points bar-chart card after each race (team-colored bars, one row per driver) |
| `recent_races` | `points_haul_drivers` | `5` | Number of drivers to show on the points haul card (3–10) |
| `recent_races` | `show_winners_summary` | `true` | Show a compact winners summary card at the start of the recent races section |
| `recent_races` | `show_gap_chart` | `true` | Show a horizontal bar chart of each finisher's time gap from the winner (team-colored bars) |
| `recent_races` | `gap_chart_drivers` | `5` | Number of drivers to show on the race gap bar chart (3–10) |
| `upcoming` | `show_session_times` | `true` | **Not implemented.** Nothing reads it; the session times are always drawn. |
| `upcoming` | `countdown_enabled` | `true` | **Not implemented.** Nothing reads it; the countdown is always drawn. |
| `upcoming` | `show_circuit_info` | `true` | Show circuit stats card after upcoming race card (laps, km, lap record) |
| `qualifying` | `show_q1` / `show_q2` / `show_q3` | `true` | Toggle each qualifying segment |
| `qualifying` | `show_gaps` | `true` | **Not implemented.** Nothing reads it. |
| `qualifying` | `show_team_duel` | `true` | Show team H2H summary card (who outqualified their teammate) |
| `practice` | `sessions_to_show` | `["FP1","FP2","FP3"]` | Which sessions to render |
| `practice` | `top_n` | `10` | Drivers per practice session |
| `sprint` | `top_finishers` | `10` | Sprint result depth |
| `calendar` | `max_events` | `5` | Race weekends to show |
| `calendar` | `show_practice` | `false` | Include practice sessions in calendar |
| `calendar` | `show_qualifying` | `true` | Include qualifying in calendar |
| `calendar` | `show_sprint` | `true` | Include sprint weekends in calendar |

### Vegas marquee

`vegas.sections` picks what F1 contributes to the Vegas continuous-scroll
marquee. It does not affect the display modes above, which still show
everything.

| Key | Default | Description |
|---|---|---|
| `vegas.sections` | `["upcoming", "last_race"]` | Sections that join the marquee |

The default is the next race (plus its circuit card) and the most recent race's
results — around 15 seconds. Sections are always shown in the canonical order
below, whatever order you list them in:

`leaders` · `battles` · `spotlight` · `upcoming` · `last_race` ·
`driver_standings` · `constructor_standings` · `recent_races` · `qualifying` ·
`practice` · `sprint` · `calendar`

`last_race` is the most recent race only; `recent_races` is all of the races
`recent_races.number_of_races` covers. Cards within a section still honour that
section's own settings, so `recent_races.show_gap_chart` and
`show_points_haul` apply to `last_race` too.

Adding sections back makes F1 hold the marquee for longer — listing all twelve
measured 114 cards on a 512px panel, close to six minutes of unbroken F1 at
50px/s. Set an empty list to keep F1 out of the marquee entirely while leaving
its own display modes running.

### Scroll & timing

| Key | Default | Description |
|---|---|---|
| `dynamic_duration.enabled` | `true` | Run a scroll until its full cycle completes instead of the fixed timer |
| `dynamic_duration.max_duration_seconds` | `120` | Hard cap even with dynamic duration |
| `scroll.scroll_speed` | `1` | Pixels per frame |
| `scroll.scroll_delay` | `0.03` | Seconds between frames |
| `scroll.game_card_width` | `128` | Card width in pixels (lower on multi-panel chains) |

### Visual features

Fine-tune which visual elements appear and how they look:

| Key | Default | Description |
|---|---|---|
| `visual.championship_leaders.enabled` | `true` | Show the split leaders card at the start of the scroll |
| `visual.championship_battle.enabled` | `true` | Show the driver P1 vs P2 title fight card with gap bar and ALIVE/NEAR/WON status |
| `visual.constructor_battle.enabled` | `true` | Show the constructor P1 vs P2 title fight card with team logos and gap bar |
| `visual.standings_header.enabled` | `true` | Show the F1-logo intro card before each standings section |
| `visual.standings_header.show_round` | `true` | Include round number and season progress bar on the header card |
| `visual.gap_bar.enabled` | `true` | Show the championship points gap bar on standing rows |
| `visual.fastest_lap_dot.enabled` | `true` | Show a colored dot on the fastest-lap driver in race results |
| `visual.fastest_lap_dot.color` | `[180, 0, 255]` | RGB color of the fastest-lap dot (default: purple) |
| `visual.circuit_map.enabled` | `true` | Show the circuit layout art on the upcoming race card |
| `visual.driver_form.enabled` | `true` | Show the driver form guide (recent race position boxes) before driver standings |
| `visual.last_race_points.enabled` | `true` | Show `+N` points scored in the most recent race on each driver and constructor standings card (gold = podium, green = solid, grey = small haul) |

**Example — change fastest lap dot to magenta and disable circuit maps:**

```json
"visual": {
  "fastest_lap_dot": {
    "enabled": true,
    "color": [255, 0, 180]
  },
  "circuit_map": {
    "enabled": false
  }
}
```

### Font customization

Override the font used for each text role. All fonts are bundled in `assets/fonts/` — no install step needed.

| Key | Default font | Description |
|---|---|---|
| `customization.header_text.font` | `PressStart2P-Regular.ttf` | Section headers and GP names |
| `customization.position_text.font` | `PressStart2P-Regular.ttf` | Position numbers and driver codes |
| `customization.detail_text.font` | `4x6-font.ttf` | Points, times, gaps |
| `customization.small_text.font` | `4x6-font.ttf` | Secondary info (circuit name, location) |

Available fonts: `PressStart2P-Regular.ttf`, `4x6-font.ttf`, `5by7.regular.ttf`

Each role also takes a size, and `auto_scale` decides whether those sizes are
used as written or scaled to the panel:

| Key | Default | Description |
|---|---|---|
| `customization.auto_scale` | `true` | Leave the font fields below blank to auto-pick a crisp pixel (bitmap) font sized for your panel. This toggle only affects a scalable TTF you choose manually: on, it scales that TTF with panel size and snaps it to its pixel grid; off, it uses the exact size below. |
| `customization.header_text.font_size` | `8` | Size in pixels. |
| `customization.position_text.font_size` | `8` | Size in pixels. |
| `customization.detail_text.font_size` | `6` | Size in pixels. |
| `customization.small_text.font_size` | `6` | Size in pixels. |

### Driver and team codes

Set `favorite_driver` to one of these three-letter codes:

`VER`, `NOR`, `PIA`, `LEC`, `SAI`, `HAM`, `RUS`, `ANT`, `ALO`, `STR`, `GAS`, `OCO`, `LAW`, `HAD`, `HUL`, `BEA`, `TSU`, `DOO`, `BOR`, `MAG`

Set `favorite_team` to one of these constructor IDs:

| ID | Team |
|---|---|
| `mclaren` | McLaren |
| `ferrari` | Ferrari |
| `red_bull` | Red Bull |
| `mercedes` | Mercedes |
| `aston_martin` | Aston Martin |
| `alpine` | Alpine |
| `haas` | Haas |
| `williams` | Williams |
| `rb` | RB F1 |
| `sauber` | Sauber (Audi) |
| `cadillac` | Cadillac |

### Timezone

- `timezone` (Advanced): IANA name used to display event start times, e.g.
  `America/Chicago`. Leave blank (the default) to follow the LEDMatrix global
  timezone; if that isn't set, the host system's timezone is used, and only if
  neither is available do times fall back to UTC.

### What the modes look like

The two standings modes need no session data, so they are pictured here. The
other six — recent races, upcoming, qualifying, practice, sprint and calendar
— need a live race weekend to have anything to show.

![Driver and constructor standings](../../docs/assets/f1-scoreboard/standings-modes.png)

Each card is tinted with the team's colour, and the header carries a season
progress bar showing the round.

![show_driver_split on and off](../../docs/assets/f1-scoreboard/driver-split.png)

![The same standings on four panel sizes](../../docs/assets/f1-scoreboard/panel-sizes.png)

## Data sources

| Data | Source |
|---|---|
| Schedule, upcoming race, calendar | ESPN F1 public API |
| Driver / constructor standings, race & qualifying results | Jolpica / Ergast API |
| Practice session data | OpenF1 API |
| Circuit layout art, team logos | Cached locally in `assets/f1/` |

All sources are public and require no API key. Data is cached locally; adjust `update_interval` if you need fresher results.

## License

GPL-3.0 — same as the LEDMatrix project.
