# Cricket Scoreboard

Live, recent, and upcoming cricket for the LEDMatrix display — covering both
**international** matches (Test / ODI / T20I) and the **major domestic T20
leagues** (IPL, Big Bash, The Hundred, PSL, CPL, SA20, ILT20, MLC, and more).

Data comes from ESPN's public cricket API (no API key required).

## Display modes

| Mode | Shows |
|------|-------|
| `cricket_live` | In-progress matches. Limited-overs matches show `runs/wickets (overs/max ov)`, current run rate, and — when a side is chasing — the target, runs still needed, and required run rate. Test matches show the day + session (Stumps / Lunch / Tea …) and both innings, with no clock. |
| `cricket_recent` | Completed matches: final scores + ESPN's result summary (e.g. `"RCB won by 5 wkts (12b rem)"`). |
| `cricket_upcoming` | Scheduled matches: date/time, teams, venue, and a format badge. |

Live matches take priority in the rotation when `live_priority` is on.

## How series discovery works

Unlike most sports, cricket has **no single stable league id** on ESPN — it is
organised as dozens of concurrent, per-tour / per-season numeric *series* ids
(e.g. a given season of the IPL might be `8048`, Major League Cricket `21266`,
the Vitality Blast `8053`). Those ids change every season.

So instead of hardcoding ids, the plugin **discovers them periodically**:

1. It reads a curated seed list, [`competitions.json`](competitions.json), that
   maps human competition keys (`ipl`, `bbl`, `the-hundred`, …) to stable
   **search terms** (competition *names* are far more stable than their ids).
2. Every `series_discovery_interval` seconds (default 24h) it queries ESPN's
   cricket header endpoint, lists every active series, and resolves them:
   - **domestic** competitions are matched by name against your
     `favorite_competitions` search terms;
   - **international** series are matched by your `favorite_teams` national-team
     names appearing in the series/event names (e.g. *"India tour of England
     2026"*).
3. Each resolved numeric id's `/scoreboard` is then fetched and parsed.

Resolved ids are cached (via the host `cache_manager`) so discovery is cheap.

## Overs math (base-6)

Cricket overs are **base-6 in the fractional part**: `18.4` overs means 18
completed overs **plus 4 balls** = `18 + 4/6 = 18.667` decimal overs, *not*
18.4. The plugin converts `overs → decimal overs` before any run-rate division:

- current run rate = `runs / decimal_overs`
- required run rate = `runs_needed / (balls_remaining / 6)`

This conversion is unit-tested (`test_cricket_plugin.py::TestOversMath`).

## Configuration

Configured under the `cricket-scoreboard` key in `config/config.json`. See
[`config_schema.json`](config_schema.json) for the full schema; key fields:

| Key | Default | Purpose |
|-----|---------|---------|
| `enabled` | `false` | Master on/off |
| `favorite_teams` | `[]` | National teams (name or abbr, e.g. `"India"`, `"IND"`) whose international series are followed |
| `favorite_competitions` | `["international","ipl","bbl"]` | Domestic competition keys from `competitions.json` (`international` follows Test/ODI/T20I tours for your favorite teams) |
| `exclude_teams` | `[]` | Teams to always hide (spoiler protection) |
| `show_favorite_teams_only` | `false` | Restrict *international* matches to those featuring a favorite team |
| `live_game_duration` / `recent_game_duration` / `upcoming_game_duration` | 20 / 15 / 15 | Per-match on-screen seconds |
| `non_favorite_live_game_duration` | `0` | Shorter turn for live matches without a favorite (0 = same as `live_game_duration`) |
| `update_interval_seconds` / `live_update_interval` | 3600 / 30 | Data refresh cadence |
| `series_discovery_interval` | `86400` | How often numeric series ids are re-resolved |
| `recent_games_to_show` / `upcoming_games_to_show` | 5 / 5 | Match counts per mode |
| `live_priority` | `true` | Live matches interrupt the normal rotation |
| `display_modes` | all on | Toggle live / recent / upcoming |
| `dynamic_duration`, `mode_durations` | off / null | Auto-size or cap each mode's total time |
| `celebration_enabled`, `celebration_duration` | true / 8 | Win-celebration takeover |
| `background_service` | enabled | Worker/timeout/retry tuning |
| `customization` | — | Fonts + colors for score / overs / team / status / detail text |

## Logos and flags

- **Franchise** teams (IPL/BBL/etc.) auto-download their logo from ESPN
  (`team.logos[0].href`) into `assets/logos/` on first sight, with a
  text-abbreviation placeholder on failure — the same pattern the other sports
  scoreboards use.
- **National** teams use bundled flag PNGs in
  [`assets/flags/`](assets/flags/) (keyed by both abbreviation and lowercase
  name), because national-team abbreviations can collide with franchise codes.

> **Note:** the bundled flags are **simple generated placeholders** (solid
> national colors + abbreviation) so the wiring is complete and functional out
> of the box. Replace them with real 48×48 flag art (same filenames) for a nicer
> display.

## v1 limitations

- **No per-ball / per-player detail** (current striker, bowler figures, economy
  rate). ESPN's cricket scoreboard response carries no `rosters`/`lineups`; that
  would require a separate boxscore endpoint and is a possible fast-follow.
- **The Hundred** counts balls (100) rather than overs; run rates for it are
  best-effort.
- Flag art is placeholder (see above).

## Testing

```bash
python -m unittest test_cricket_plugin   # needs Pillow + requests
```

Covers the base-6 overs conversion, run-rate math, format normalization, all
four renderer branches at every matrix size, and a manager update/display
smoke test driven by the mocked responses in [`test/harness.json`](test/harness.json).
