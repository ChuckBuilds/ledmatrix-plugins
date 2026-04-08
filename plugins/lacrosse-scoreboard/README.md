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
      "show_all_live": true
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

## Troubleshooting

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
