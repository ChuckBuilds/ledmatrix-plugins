# Election Results

Live election results on your LED matrix — a scrolling ticker of the important
races plus a full-screen takeover when a race is newly called. Filterable to your
state.

It **auto-activates** around your state's elections and is **dormant** the rest
of the year (no network, no screen time), so you can leave it enabled and it only
shows up when there's news.

![called card](#) <!-- add a screenshot when available -->

## What it shows

- **Ticker (normal rotation):** one card per race — office + state/district, a
  `CALLED` chip or `% in`, and the top two candidates with party color and vote
  share. Advancing/winning candidates are marked with `*`.
- **Race-called interrupt:** when a race flips to *called*, the plugin uses the
  core's live-priority preemption to take over the screen with a "RACE CALLED"
  card (office, winner, party, vote % and % reporting), the same path live sports
  use. Each call shows once.

## Scope when filtered to your state

With `only_my_state` on (default), the ticker shows **national** races
(President) plus **every race in your state**: statewide offices (Senate,
Governor, ballot measures) and all of that state's U.S. House districts. The
`race_types` list narrows which office types appear; downballot offices (state
legislature, local offices) are excluded by default.

## When it's active (the election calendar)

The plugin decides on its own whether to do anything right now:

- **Dormant** (most of the year): if today isn't inside an election window for
  your state, the plugin fetches nothing, fires no interrupts, and returns no
  frame — the display controller skips it in rotation entirely.
- **Active**: when today falls inside the window of an election it can name and
  build a feed URL for, it polls that feed and shows the ticker (and interrupts).

It knows two elections per state per year without any config:

- **General** — the date is computed (first Tuesday after the first Monday of
  November); slug is the standard `results-{state}.json`.
- **Primary** — dates vary by state, so they come from a small built-in table.
  Only **CA 2026-06-02** ships seeded; add your state's primary via
  `calendar_events` (below) — no code change needed.

An active **window** runs from election day through `trail_days` after (default
14) to cover results that arrive over several days.

### Staleness — the ticker drains itself

- A **called** race drops off the ticker `hide_called_after_seconds` after it was
  called (default 24h), **even while sibling races are still uncalled**. Uncalled
  races and fresh calls stay. Once everything has been called and aged out, the
  ticker is empty and the plugin goes quiet again.
- The "newly called" snapshot is **persisted** (via `cache_manager`), so a
  restart mid-count neither replays old calls as "breaking" nor misses a fresh
  one. Races already called when the plugin first boots are dated to election day,
  so booting on election night still shows that day's calls while booting days
  later hides them.

### Manual override (demo / pin a feed)

Use `override` to force the plugin on without waiting for the calendar — handy for
testing or to point at one specific feed:

```jsonc
// "Today is an election day in ZZ" (forces active now):
"override": { "active": true, "state": "ZZ", "election_date": "2026-11-03", "election_type": "general" }

// "Show me exactly this file":
"override": { "feed_url": "https://static01.nyt.com/elections-assets/pages/data/2026-11-03/results-california.json" }
```

## Configuration

| Key | Default | Notes |
|---|---|---|
| `enabled` | `false` | Turn the plugin on. |
| `state` | `"CA"` | 2-letter code. Filters races and selects which calendar entries apply. |
| `only_my_state` | `true` | National + your state's races only. |
| `race_types` | `["president","senate","governor","house","ballot"]` | Office types to show. |
| `update_interval` | `60` | Poll seconds. Use 30–60 on election night. |
| `display_duration` | `30` | Ticker seconds per rotation (dynamic duration may extend). |
| `hide_called_after_seconds` | `86400` | Drop a called race from the ticker this long after it was called (0 disables). |
| `live_priority` | `true` | Allow the called-race interrupt. |
| `interrupt.duration_seconds` | `12` | How long each called card holds the screen. |
| `interrupt.my_state_only` | `true` | Only interrupt for races passing the state filter. |
| `interrupt.max_age_seconds` | `300` | Drop stale queued calls older than this. |
| `override.active` | `false` | Treat today as an election day (skips the calendar/window check). |
| `override.state` | `""` | State for the override (defaults to `state`). |
| `override.election_date` | `""` | Feed date to show; defaults to today when `active`. |
| `override.election_type` | `"general"` | `primary` / `general` / `special`. |
| `override.feed_filename` | `""` | Exact NYT filename for a non-standard slug (specials). |
| `override.feed_url` | `""` | Full URL of a results JSON; bypasses URL building entirely. |
| `override.trail_days` | `14` | Days after election day to keep showing results. |
| `calendar_events` | `[]` | Extra scheduled elections (e.g. your state's primary). Each: `{state,date,type,feed_filename?,trail_days?}`. |
| `local_races` | `true` | Use your state's authoritative local results source where one exists (auto-engages by state; currently CA). |
| `test_mode` | `false` | Render bundled fixtures offline (demo / no election night). |

> The active election's date and type are chosen by the calendar/override and
> pushed to the NYT provider automatically; you don't set `providers.nyt.election_date`
> by hand anymore.

### California local results

For California users this **engages automatically** (`local_races` is on by
default) — there's no provider to switch on. It supplements CA races with the
authoritative Secretary of State tally and an optional **county/city rollup**.
The knobs under `providers.ca_sos` only fine-tune that rollup:

- `county` — a county slug (e.g. `los-angeles`) for county-level totals.
- `city` — a major CA city, mapped to its county (ignored if `county` is set).
- `override_nyt_votes` — use the SoS authoritative vote totals for CA races. NYT
  still drives **calls** and **importance**; CA-SoS supplies granular/authoritative
  **votes**.

The SoS feed has no winner flag, so "called" is derived from reporting
completeness (`called_threshold`, default 99%) with the top two advancing.

## How a race is called

- **NYT:** `outcome.won` (winners) or `outcome.advanced_to_runoff` (top-two)
  non-empty.
- **CA-SoS:** derived — once reporting reaches `called_threshold`, the top two
  advance.

## Architecture / adding a provider

```text
ElectionProvider (ABC)          providers/__init__.py
  ├─ NytStaticProvider          providers/nyt.py   (baseline: national + all states)
  └─ CaSosProvider              providers/ca_sos.py (CA-only enhancement)
RaceStore                       store.py  (merge + filter + sort + newly-called diff)
renderer                        renderer.py (ticker segment + called card)
ElectionPlugin(BasePlugin)      manager.py (update loop, scroll, live-priority hooks)
```

To add a state/source:

1. Create `providers/<name>.py` with a class extending `ElectionProvider`.
   Implement `fetch(state)` → `list[Race]` and `provides_states()` (return the
   set of states it supplements, or `None` for a national baseline).
2. Normalize into the common `Race`/`Candidate` model (`data_model.py`). Use
   `make_race_id(office, state, district)` so your races merge with the baseline.
3. Register it in `create_providers()` (`providers/__init__.py`), gated on its
   own `providers.<name>.enabled` config flag.

State-scoped providers override the baseline for their states (the baseline keeps
calls + importance); the merge is keyed by the stable race id.

## Data source note

The NYT provider reads NYT's own static front-end JSON feed with a normal browser
User-Agent. This is a **personal-use, best-effort** read and may break when NYT
changes their feed format. The provider abstraction means swapping to AP / DDHQ /
another source is a new file, not a rewrite.

## Testing

```bash
# Logic tests (parsing, merge, filter, sort, interrupt diff) against real fixtures:
/path/to/LEDMatrix/.venv/bin/python plugins/ledmatrix-elections/test_elections.py

# Cross-size / cross-screen safety harness (run from a LEDMatrix core checkout):
python scripts/check_plugin.py --plugin ledmatrix-elections \
  --plugin-dir /path/to/ledmatrix-plugins/plugins --out-dir /tmp/preview \
  --config '{"test_mode": true, "state": "CA", "race_types": ["governor","house"]}'
```

Fixtures under `test/fixtures/` are real captures from the June 2, 2026 California
primary.
