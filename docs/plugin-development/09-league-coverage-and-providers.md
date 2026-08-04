# 9. League Coverage and Data Providers

This document answers a question that keeps coming up: *why is adding a league
so expensive, and can we make it cheap?* It uses
[ha-teamtracker](https://github.com/vasqued2/ha-teamtracker) — a Home Assistant
integration covering 31 native leagues plus ~40 more from non-ESPN sources — as
the comparison, because it solves the same problem with a very different shape.

Doc 08 covers the *other* half of the sports-code problem: nine near-identical
copies of `sports.py`. Read it first; this document deliberately does not
overlap with it, and §3 explains why the two problems should not be attacked
together.

> **Licence note.** ha-teamtracker ships **no LICENSE file**, so default
> copyright applies — all rights reserved. Everything below reuses *facts*
> (URL patterns, league slugs, sport IDs) and *architectural ideas*, both of
> which are freely usable. **Do not copy code from it.** It is itself a fork of
> [`zacs/ha-nfl`](https://github.com/zacs/ha-nfl).

---

## 1. How ha-teamtracker gets its data

The codebase splits into **providers** (fetch, URL construction, caching) and
**parsers** (normalise into one flat attribute record), joined by two very small
factories. `provider_factory.get_provider()` dispatches on `sport_path`;
`parser_factory.get_parser()` dispatches on a `data_format` string the provider
declares; `set_values.py` multiply-inherits nine sport mixins (baseball,
cricket, golf, hockey, mma, racing, soccer, tennis, volleyball) and dispatches
on `sport` through the MRO.

The idea worth taking is this: **non-ESPN providers transform their payload into
ESPN's JSON envelope** (`_transform_hockeytech_to_espn()`), so one downstream
pipeline serves every source. A second trick keeps the user-facing model at two
strings regardless of backend — **`sport_path` doubles as a provider selector**:
`hockeytech/ahl`, `mlbstats/aaa`, `cflscoreboard/cfl` sit in the same two config
fields as `hockey/nhl`.

### Endpoints

| Purpose | URL |
|---|---|
| Scoreboard | `https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard` |
| Team list | `.../{sport}/{league}/teams?limit=1000` |
| Team detail | `.../{sport}/{league}/teams/{team_id}` |

Query params: `limit=50`, `dates=YYYYMMDD-YYYYMMDD` (**skipped entirely for
tennis and baseball**), `groups={conference_id}` for NCAA filtering, and `lang`.
Non-ESPN sources are `lscluster.hockeytech.com/feed/index.php` (per-league `key`
+ `client_code`), `statsapi.mlb.com/api`, and
`cflscoreboard.cfl.ca/json/scoreboard`.

### What it exposes per team

`team_record` (from `competitor.records[0].summary`), `team_rank` (from
`curatedRank.current`, with ESPN's `99` "unranked" sentinel mapped to null),
`odds` / `overunder`, `tv_network` (all `broadcasts[*].names` joined), 
`series_summary`, `last_play`, win probability, and sport-specific extras
(balls/strikes/outs, shots on target, sets won).

Notably it exposes **no season statistics** — no PPG, no ERA, no yardage. "Team
stats" here means the record and rank that ride along on the scoreboard payload,
which is exactly what our scoreboards already read in
`SportsCore._extract_team_record()`. There is no richer stats source to adopt,
because it does not use one.

---

## 2. League coverage: where we stand

### 2.1 The thing that actually determines cost

We ship two plugin shapes, and they cost wildly different amounts to extend.

| Shape | Plugins | Manifest `display_modes` | Cost to add a league |
|---|---|---|---|
| **Generic / parametrized** | `soccer`, `afl`, `nrl`, `ufc` | `soccer_live`, `soccer_recent`, `soccer_upcoming` | a few dict entries — or **zero code** via `custom_leagues` |
| **Per-league hardcoded** | `football`, `hockey`, `basketball`, `baseball`, `lacrosse` | `nhl_recent`, `ncaa_mens_live`, … (hockey declares 9) | new managers module + ~115–150 edit sites across ~30 methods + ~20 KB of schema + manifest modes |

Soccer already *is* the architecture §3 proposes.
`plugins/soccer-scoreboard/soccer_managers.py:45` takes `league_key` as a
constructor argument, `create_custom_league_managers()` (`:479`) instantiates
any ESPN soccer slug at runtime, and `manager.py:1219` (`_get_available_modes`)
synthesises `soccer_{league_key}_{mode}` names dynamically — so **adding a
soccer league never touches the manifest.**

The hardcoded case is measurable. In
`plugins/hockey-scoreboard/manager.py` the string `ncaa_womens` appears **115
times across 30 methods**; in `football-scoreboard`, `ncaa_fb` appears 151 times.

### 2.2 Cheap ESPN adds

- **Soccer — NWSL, Copa Libertadores, Women's World Cup.** Already reachable
  **today** with no code at all, through the `custom_leagues` array in
  `plugins/soccer-scoreboard/config_schema.json` (max 20 entries; the
  `league_code` pattern accepts `usa.nwsl`, `conmebol.libertadores` and
  `fifa.wwc`). This is a **discoverability** gap, not a capability one — nobody
  guesses `conmebol.libertadores`. Promoting them to built-ins is a
  two-file change plus a version bump, with no manifest mode change.
- **Extra MiLB levels — a dead config hook.**
  `plugins/baseball-scoreboard/milb_managers.py:56` reads
  `self.mode_config.get("sport_ids", DEFAULT_MILB_SPORT_IDS)` and `:240-263`
  already joins the list into `?sportId=`, so the fetch is level-agnostic. But
  `manager.py` never forwards `sport_ids` into the `milb_scoreboard` dict and
  the key appears nowhere in `config_schema.json`. **The knob exists and is
  unreachable.** Wiring it up is roughly one line plus a schema block.
- **PWHL and UFL are *not* cheap.** They land in per-league-mode plugins and pay
  the full bill in §2.1 — a new `*_managers.py`, the ~115-site sweep, ~20 KB of
  schema, new manifest modes, `LEAGUE_PATHS` in `scripts/check_team_pickers.py`,
  and a cross-repo dependency on the core's
  `src/logo_downloader.get_logo_directory()` knowing the new `sport_key`.

### 2.3 The rest, by cost

| Target | Vehicle | Rough cost | Why |
|---|---|---|---|
| **NCAA volleyball** (M + W) | new `volleyball-scoreboard` | ~2–3 days | Well-behaved ESPN team sport; needs a sport mixin and a renderer that draws sets-won instead of a clock. **The cheapest genuinely-new plugin, and the best proof that a registry pays for itself.** |
| **CFL** | non-ESPN provider into `football-scoreboard` | ~2 days | Football rendering exists; the work is one adapter reshaping `cflscoreboard.cfl.ca` into ESPN's envelope. |
| **PGA Tour** (full season) | generalise `masters-tournament` | ~3–4 days | That plugin is 5,741 lines and Masters-specific. Leaderboard rendering is done; the work is season-wide event discovery and de-Masters-ing the renderer. |
| **NASCAR + IndyCar** | new `racing-scoreboard` | ~4–5 days | `f1-scoreboard` (6,351 lines) is bespoke on Jolpica/OpenF1 and not ESPN-shaped, so generalising it is not cheaper than starting fresh on the ESPN racing endpoint. Leave F1 alone. |
| **Tennis** (ATP + WTA) | new `tennis-scoreboard` | ~4–5 days | Breaks nearly every assumption in `sports.py`: two athletes not two clubs, no abbreviations, headshots instead of logos, set-by-set scoring, tournament-shaped scheduling. `ufc-scoreboard` is the right conceptual model. |
| **HockeyTech** (15 junior/minor hockey leagues) | provider adapter into `hockey-scoreboard` | ~4–6 days | The fetch is easy — one endpoint shape. **Logos dominate the calendar time**: no ESPN CDN, so ~20 teams × 15 leagues need a source or bundled assets. The per-league `key`/`client_code` pairs are effectively credentials. Ship AHL + ECHL only in a v1. |

### 2.4 What we have that they don't

Worth stating so the comparison isn't one-directional: lacrosse (M/W), NRL,
cricket (11 domestic T20 leagues), college hockey M/W, college baseball, MiLB,
Olympics, the NFL Draft, March Madness, the odds ticker, and standings via
`ledmatrix-leaderboard`. Our per-league depth is well ahead; our per-league
*cost* is well behind.

---

## 3. Should we restructure? (proposal only — nothing here is built)

### 3.1 Two problems get conflated, and only one is ours

- **The 25,452 lines of duplicated `sports.py`** across nine plugins (65–80%
  mutually identical) is **doc 08's problem.** It belongs to the core repo, it
  is already converging module by module, and it is gated on a sunset rule whose
  condition 3 does not hold yet. **League work should not touch it.**
- **The per-league hardcoding inside each plugin's `manager.py`** is *this*
  repo's problem. It needs no core release, it is entirely in our control, and
  it is what actually makes adding a league expensive.

Evidence that the hardcoding is already rotting:
`plugins/hockey-scoreboard/manager.py` defines `_get_manager_for_league_mode`
**twice in the same class** — at line 1299 and again at line 3093. The second
shadows the first. All three real callers pass sport_keys, so behaviour is
currently correct *by luck*; the dead definition at 1299 keys on league ids and
would silently return `None` for the exact keys its own docstring advertises.

### 3.2 The proposal

**Do not build a generic multi-sport plugin.** One plugin per sport family is
the right boundary — rendering, status text, logo namespaces and the store UX
all follow sport, and changing it would break every saved config. Instead, make
each existing plugin registry-driven, **using soccer as the template it already
is.**

Four layers:

1. **`leagues.json` per plugin — data, not code.** One record absorbs everything
   currently scattered across the `ESPN_*_SCOREBOARD_URL` constant, the
   `sport_key_map`, `_get_default_logo_dir`, `FAVORITE_CHECK_LEAGUES`, the
   priority table, the season window, and the enabled-by-default flag:

   ```jsonc
   { "id": "pwhl", "name": "PWHL", "sport_key": "pwhl",
     "provider": "espn", "espn": { "sport": "hockey", "league": "pwhl" },
     "logo_dir": "assets/sports/pwhl_logos",
     "season": { "start": "1101", "end": "0601" },
     "priority": 4, "default_enabled": false, "unverified": true }
   ```

2. **One parametrized managers module per plugin**, taking a league record the
   way `soccer_managers.py:45` takes `league_key`. This replaces
   `nhl_managers.py` + `ncaam_hockey_managers.py` + `ncaaw_hockey_managers.py`,
   which are already ~90% identical — diff them and the only substantive
   differences are the URL, the sport_key, log strings, and the date window
   (`nhl_managers.py:52` is `0901-0801`; `ncaam_hockey_managers.py:51` is
   `0901-0501`).

3. **Provider adapters** implementing one method,
   `fetch_events(window) -> {"events": [...]}` in ESPN's envelope. ESPN itself
   needs **no adapter** — just the two fields from the record. We have already
   proven the pattern once:
   `plugins/baseball-scoreboard/milb_managers.py:97`
   (`_convert_stats_game_to_espn_event`) reshapes statsapi.mlb.com so the shared
   extraction code works unchanged.

4. **`custom_leagues` for every sport plugin**, feeding the same record path.
   This is what makes the whole plan robust to §5: a wrong built-in slug becomes
   a user-fixable config value instead of a broken release.

### 3.3 Why this is safe under the module loader

- **`leagues.json` is data, and data is invisible to the collision checker.**
  `scripts/check_module_collisions.py:48` only globs `*.py`. There is a shipping
  precedent: `cricket-scoreboard` loads `competitions.json` at `manager.py:149`
  via `_PLUGIN_DIR / "competitions.json"`.
- The *loader* module must still follow the CLAUDE.md rule — plugin-prefixed
  (`hockey_league_registry.py`) and imported **at module level from the entry
  point**, never from a function body. The existing `hockey_timezone.py` /
  `hockey_favorite_check.py` imports are exactly this shape.
- **Providers go in flat, prefixed top-level modules**
  (`hockey_provider_hockeytech.py`), never a `providers/` subpackage — that is
  precisely the `ledmatrix-elections` failure CLAUDE.md documents.

### 3.4 This repo first, core later — and only the loader

The same league table is **already duplicated five times**:
`ledmatrix-leaderboard/league_config.py:35`, `odds-ticker/data_fetcher.py`,
`LEAGUE_PATHS` in `scripts/check_team_pickers.py:38`,
`FAVORITE_CHECK_LEAGUES` in seven `manager.py` files, and the per-manager
`ESPN_*_SCOREBOARD_URL` constants. One shared table is strictly better — *once
it can be relied on*.

It can't be yet. Doc 08 establishes that the core's compatibility floor is
advisory only and that `StoreManager.update_plugin` never compares core
versions, so anything requiring a core release is undeliverable today. Start
here; promote `src/common/league_registry.py` (the loader) to the core when the
sunset rule's condition 3 holds, and keep each `leagues.json` (the data) local.
When that happens, remember doc 08's warning that the guard must name the exact
dotted path — `{"src"}` alone will not match `src.common.league_registry`.

### 3.5 What a first increment would look like

**One plugin, no new leagues, no behaviour change.** `hockey-scoreboard` is the
right candidate: its three `*_managers.py` are near-identical, so the
consolidation is clean, and the duplicate method above gets fixed on the way.

The acceptance gate is doc 08's own: run the safety harness before and after,
`diff -r` the output directories, and require **byte-identical PNGs** at all
four sizes × all nine modes. Manifest `display_modes` stays unchanged in this
step so nothing about the core's rotation moves.

Only after that does PWHL become one record, one schema block, one version bump.

---

## 4. Techniques worth taking, ranked

**Every item below that touches `sports.py` is a nine-copy sweep** under doc 08's
"fix all lineage members in one PR" rule. Budget the sweep, not the edit.

### Tier 1 — small, and directly enabling

1. **Three-tier ESPN fallback.** Call with the date range; if zero events, retry
   **without `dates`**; if still zero, retry **without `lang`**. Lands in
   `_fetch_todays_games` (`sports.py:859`) and `_get_weeks_data` (`:892`).
   *Why this one matters most:* our season windows are hand-written per league
   (§3.2), and a wrong window today returns zero events — indistinguishable from
   "this league doesn't exist." Every new league with a short or unusual season
   (PWHL, UFL, NWSL, college volleyball) is exposed to this.
2. **API-limit awareness.** We already pass `limit: 1000`. Emitting a diagnostic
   when `len(events) == limit` — rather than reporting nothing found — is ~4
   lines, and it fits the diagnostic voice `hockey_favorite_check.py` already
   established.
3. **Make `_fetch_todays_games` cache-aware.** Highest value per line in this
   list. It is currently a raw `session.get` with no cache read, so three
   managers per league each hit ESPN independently — *and* live screens cannot
   be tested offline. That second cost is documented in our own tree; the
   `_comment` in `plugins/hockey-scoreboard/test/harness.json` says live mode is
   disabled because `_fetch_todays_games()` "is a direct network call with no
   cache read … so the live screen can never be fed from mock data." Routing it
   through `cache_manager` buys the shared cache **and** unblocks live-mode
   golden images in CI.

### Tier 2 — worthwhile, medium effort

4. **Adaptive refresh.** We have half of it (`live_update_interval` vs
   `update_interval_seconds`; cricket does the simple data-driven version at
   `manager.py:186-192`). The missing piece is ha-teamtracker's rule that a
   *pre*-game starting within ~20 minutes also triggers the fast interval, so
   the opening minutes aren't stale.
5. **Overrides — fold into `leagues.json`, don't build a second mechanism.**
   ha-teamtracker keeps a separate deep-merged overrides file for logos, names,
   colours and API credentials. We should carry the same fields on the league
   record instead, and mark credential-ish ones `x-secret`.
6. **Flexible team matching.** Users type `GSW` for `GS` and `BAMA` for `ALA`.
   `hockey_favorite_check.py:247` already *detects* this with
   `difflib.get_close_matches` and then refuses to act on it. Promoting
   detection to matching is real user value — but it is a behaviour change, and
   `exclude_teams` must be matched by the same ladder or a fuzzy match could
   leak a score the user asked to hide. Do it with tests.

### Tier 3 — adopt narrowly, or skip

7. **`get_value(json, *keys, default)`** — a tolerant nested accessor that is
   why their code survives ESPN's inconsistent schemas. Right idea, wrong time:
   retrofitting it across nine copies of a 3,000-line file is a review-hostile
   diff, and doc 08 warns against refactors that make the next cross-copy patch
   harder. **Adopt for new code only** — every provider adapter and new sport
   mixin uses it from day one.
8. **Reuse generic fields for non-team sports.** Not actionable until
   tennis/racing/golf exist, but record the convention now so those plugins
   reuse `game_renderer` instead of forking it: rank = leaderboard position
   (`T4`), grid position, or seed; period = session; `last_play` = the top-10.
9. **Their prior-vs-next game selection** (a 12-hour rule set) — **skip.** Our
   `recent_games_to_show` / `upcoming_games_to_show` model is different and
   arguably better; porting theirs would be a user-visible regression.
10. **Their `conference_id == "9999"` canned-JSON hook** — **skip.** Our
    `test/harness.json` `mock_data` + `freeze_time` is strictly better and lives
    outside production code paths. Spend that effort on Tier 1 item 3, which is
    what actually blocks the harness from covering live modes.

---

## 5. Verifying any of this

**No ESPN slug named in this document has been verified live.** The environment
this assessment was written in blocks `site.api.espn.com` at the proxy (403 on
CONNECT). That is a property of the sandbox, not of the endpoints — but it means
every slug below is *reported*, not *confirmed*.

Open questions a maintainer on a networked machine must settle first:

- `football/ufl` vs `football/xfl` vs neither. The XFL and USFL merged into the
  UFL in 2024, so ha-teamtracker's `xfl` entry may simply predate that.
- `hockey/pwhl` — and whether `/teams` returns abbreviations we can match
  favourites against.
- `volleyball/mens-college-volleyball`, `volleyball/womens-college-volleyball`.
- `racing/nascar-premier`, `racing/irl` — and critically whether their payloads
  are ESPN-envelope-shaped at all.
- `soccer/conmebol.libertadores`, `soccer/usa.nwsl`, `soccer/fifa.wwc`.
- The authoritative MLB StatsAPI sport-id table from
  `https://statsapi.mlb.com/api/v1/sports`, rather than guessing ids for
  rookie / winter / independent ball.
- Whether the core's `src/logo_downloader.get_logo_directory()` handles each new
  `sport_key` or falls through.

### The probe script (specified, not written)

`scripts/probe_leagues.py`, modelled closely on `scripts/check_team_pickers.py`
— same house style: `urllib.request`, the explicit `https://` scheme pin with
its `# nosec B310` justification, an `--apply` mode, non-zero exit on drift.
It should take candidate slugs from a list *and* from every `leagues.json` so a
new record is probed automatically; try all three fallback tiers and record
which one succeeded; also hit `/teams?limit=1000`, since a 200 with a non-empty
team list proves a slug exists **even out of season**; report event counts,
whether `len(events) == limit`, and the key set of a sample event so we can see
whether the envelope matches what `_extract_game_details_common` expects; and
offer `--save-fixtures`.

### Turning captures into permanent coverage

Each captured payload becomes `plugins/<id>/test/fixtures/*.json`, referenced
from `harness.json` with `freeze_time` pinned to the capture date. The safety
harness then renders the new league at 64×32 / 128×32 / 128×64 / 256×32 with
**zero network**, on every PR, forever. That is the only mechanism in this repo
that can prove a new league renders correctly — and it works precisely because
it is offline.

**Keep the probe out of CI**, exactly as `check_team_pickers.py` is today. A
third-party outage must never be able to block a merge. A nightly non-blocking
job that opens an issue on drift is fine; a PR gate is not.

### Ship unverified leagues safely

Any league whose slug hasn't been confirmed ships `"default_enabled": false`,
`"default": false` in the schema, and a description pointing at the
`custom_leagues` escape hatch. Combined with §3.2 layer 4, a wrong guess costs a
user one config edit instead of costing us a release.

---

## 6. Open findings

Two real defects surfaced while measuring the above. Both want their own PR with
a version bump, and neither is fixed by this document:

- `plugins/hockey-scoreboard/manager.py` defines `_get_manager_for_league_mode`
  twice (lines 1299 and 3093); the first is dead code that would return `None`
  for the league keys it documents.
- `plugins/baseball-scoreboard/milb_managers.py:56` reads a `sport_ids` config
  key that `manager.py` never forwards and `config_schema.json` never declares,
  so MiLB is permanently pinned to sport IDs 11–14.
