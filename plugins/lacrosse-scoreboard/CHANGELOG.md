# Changelog

## [1.26.1] - 2026-09-11

### Fixed
- **Live score updates now actually reach the scrolling strip.**
  1.41.0 added the rebuild-on-change machinery but wired it in the wrong order,
  which left it inert: the rebuild decision is computed by fingerprinting the
  live managers' cached games, and the only call that refreshed those managers
  (_ensure_manager_updated) sat INSIDE the block that decision gates. So once
  the first strip was built nothing refreshed the data, the fingerprint could
  never change, and the block never ran again -- the same frozen-until-restart
  symptom the previous release set out to fix. Switch mode was never affected
  because _try_manager_display() refreshes unconditionally on every pass; scroll
  mode now gets the same guarantee, refreshing the live managers before it
  fingerprints them. _ensure_manager_updated() is itself interval-guarded, so on
  frames where no refresh is due this costs two getattrs and a comparison.
  Ported across all eight scoreboards in one change, per CLAUDE.md non-
  negotiable #7, and pinned by a test that asserts the ordering structurally --
  reversing the two lines leaves every behavioural test passing while the panel
  silently freezes.

## [1.26.0] - 2026-09-10

### Fixed
- **Live games now reach the scrolling strip mid-cycle.**
  The strip was rendered once per scroll cycle and _scroll_prepared was cleared
  only when the cycle completed, so a score changed while the marquee was
  running stayed frozen in the pixels until it finished -- minutes, for a long
  game list. Restarting the display forced a rebuild, which is the workaround
  users were finding. The strip is now rebuilt when anything the card draws
  changes, keeping scroll_position and total_distance_scrolled so the marquee
  does not snap back to the start and the cycle still completes on schedule. The
  game clock deliberately does not trigger a rebuild -- it ticks every second
  and re-rendering every card that often is the whole frame budget on a Pi --
  and rebuilds are floored at 5s so a large slate cannot thrash. Ported across
  all eight scoreboards in one change, per CLAUDE.md non-negotiable #7. Rebuild
  frequency is self-limiting: the floor between rebuilds scales with what the
  last one actually cost, so the marquee never spends more than about 5% of its
  time frozen re-rendering. Measured on a Pi 4, a strip rebuild takes 29ms for
  one game and 463ms for fifteen; a fixed floor would have been fine for the
  first and wrong for the second. Also fixes the rebuild-cost bookkeeping being
  keyed differently from where it is read, which left the duty-cycle cap inert
  in most plugins.
## [1.25.1] - 2026-09-11

### Fixed
- **Placeholder team logos draw their abbreviation at PressStart2P 16, not 12.**
  That face is crisp only at multiples of 8; 12 was anti-aliased, and 16 is the
  nearest crisp size for the 64px logo tile. Panel text was already on-grid via
  `_FONT_PIXEL_GRID` and is unchanged.

## [1.19.3] - 2026-09-01

### Fixed
- **Recent games now get their odds.** `SportsUpcoming` fetches odds for the games that survive selection and `SportsLive` fetches them per included game — the Recent screen never fetched them at all, so its "odds if available" renderer never had anything attached and every final rendered bare. `update()` now fetches odds for the selected finals, exactly as Upcoming does; ESPN keeps a completed game's closing line on the same endpoint, so a final is as answerable as an upcoming game. Same fix as football-scoreboard 2.29.3 — which only surfaced there because football's display-path rotation attached odds to rotated-in finals by accident; this plugin has no such rotation, so its finals were bare in every configuration. Pinned by `test_recent_games_get_odds.py`.

## [1.19.2] - 2026-08-31

### Changed
- **The rank badge chooses its ranking block instead of taking ESPN's first.** That endpoint returns several blocks and the first is not promised to be a poll — men's and women's college hockey are fronted by *NCAA Tournament Seedings*, and college lacrosse publishes seedings of its own beside the Inside Lacrosse poll. The poll leads today, so this league was one reordering away from a bracket seed appearing where a viewer expects a poll position. ESPN's order is kept among genuine polls; seedings and lower divisions are stepped over. Ported from the same fix in `hockey-scoreboard`, where the wrong block was being drawn live, and held by `scripts/test_poll_choice.py`.

## [1.19.1] - 2026-08-30

### Fixed
- **Recent games come back when favourite teams are set.** `SportsRecent.update()` calls `self._favorites_first(...)`, but that helper — and `_other_games_window` and `_is_favorite_game` with it — was defined on `SportsUpcoming`, a sibling class rather than an ancestor, so the call raised `AttributeError`. `update()` catches it, logs `Error updating recent games` and carries on with an empty list, so the recent screen simply showed nothing. It only bites when favourite teams are configured without `show_favorite_teams_only`, which is the ordinary way to use the setting.
- `football-scoreboard` already had all three on `SportsCore` and was unaffected; this brings the rest into line. Every safety-harness render is byte-identical — this plugin's fixture sets no favourites, so the broken path was never reached there.

## [1.19.0] - 2026-08-29

### Changed
- **The score is now the headline it was always meant to be.** It was the only element on the card not sized from the panel, and it was not even bigger than its neighbours: PressStart2P renders crisply on an 8px grid, so the 10px default snapped to 8 — the same 8 the clock above it and the game date below it are drawn at. It is now sized from `display_height`, snapped to its face's pixel grid and capped at twice its design size, with the clock/date face held a grid step below it.
- **A narrower face instead of smaller logos.** Where the grown score would swamp the panel the layout reaches for a narrower *face*, which is what `football-scoreboard` has always done via `_fit_score_font` and the single reason its logos read larger than every other scoreboard's at the same panel size. Measured on 128x64: `4x6-font` at 14px reserves 28px and leaves 52x52 logos, where `PressStart2P` at 16px reserved 60px and left 36x36. The two faces are not the same shape — PressStart2P is square, 4x6-font is nearly as tall and about half as wide — so the score keeps the dimension that carries legibility and gives back the one the logos need.
- **Logos are sized against the space the score actually needs**, and only where the score grew. A panel whose score did not move keeps exactly the logos it had.
- **Score and date positions scale with their faces.** The bottom-anchored score's `-14`, the centred score's `-3`, and the date's 7px drop were all chosen for an 8px face and clipped a grown one off the card.
- **The upcoming screen is untouched at every size.** It draws no score — `fonts["score"]` appears in `SportsUpcoming` zero times, `fonts["time"]` five times — so none of the score-driven sizing applies to it and its date and time keep the face and size they always had. Measured on the live and recent screens: 64x32, 128x32 and 256x32 are byte-identical to the previous release; every taller panel gains a larger score with logos the score is no longer drawn across.

## [1.7.0] - 2026-08-04

### Changed
- **Scroll display now runs on the core's shared implementation.** Orchestration — scroll-helper configuration, frame pumping, completion, settings resolution, native `global_config['target_fps']` — moves to the core's `src.common.sports_scroll` (LEDMatrix 3.2.0). Only the sport-specific content half stays here.
- **Nothing changes on an older core.** The import is guarded: a core without that module falls back to `scroll_display_legacy.py` and the plugin behaves exactly as before. The minimum core version is unchanged at 2.0.0 — the plugin does not *require* 3.2.0, it prefers it.
- Verified byte-for-byte: all 16 safety-harness renders (8 panel sizes × 2 screens) are identical to 1.6.0.

## [1.6.0] - 2026-07-29

### Fixed
- Explain an empty screen instead of leaving the user guessing. A favorite team code that is not a real ESPN abbreviation matched no game and showed nothing, and so did a correct code before its season started - the two were indistinguishable from the logs. The plugin now says which it is, suggests the right code for a near miss (GBP -> GB), and reports when the league's next games are. The check runs in the background, once per league, and cannot affect what is displayed.

# Lacrosse Scoreboard — Changelog

## 1.5.1 (2026-07-30)

### Fixed
- **The core's own `"UTC"` default no longer masks a missing global setting**: `ConfigManager.get_timezone()` is `self.config.get('timezone', 'UTC')`, so it returns `"UTC"` for a config with no `timezone` key at all. 1.5.0 took that at face value and therefore never reached the host system zone. Resolution now reads the raw config dict and treats an absent key as absent, falling through to the system timezone as designed. A plugin-level `"UTC"` set by you is still honored verbatim — this plugin never wrote one back into your config.

## 1.5.0 (2026-07-29)

### Fixed
- **Game start times shown in UTC**: The plugin read the LEDMatrix global timezone only from `cache_manager.config_manager`. On cores that hang `config_manager` off the plugin manager instead, that lookup came back empty and every start time was rendered in UTC, while plugins that check the plugin manager first (clock-simple, geochron) showed the correct local time on the same device. Timezone resolution now lives in `lacrosse_timezone.py` and tries, in order: the plugin's own `timezone` setting, `plugin_manager.config_manager`, `cache_manager.config_manager`, the host system zone (`TZ`, `/etc/timezone`, `/etc/localtime`), and only then UTC.
- **`timezone` setting was not in the config schema**, so it never appeared in the web UI. It is now a documented string property under Advanced Settings.

### Added
- `timezone` (Advanced Settings): optional IANA zone override, e.g. `America/Chicago`. Blank (the default) follows the LEDMatrix global timezone.

## 1.1.0 (2026-04-07)

### Breaking change — display modes renamed with `lax_` prefix

The six display modes this plugin exposes previously collided with
the NCAA hockey modes shipped by `hockey-scoreboard`. LEDMatrix's
display controller keys modes in a flat dict
(`src/display_controller.py`), so installing both plugins at the
same time meant whichever loaded second silently overrode the
first one's NCAA modes.

All lacrosse modes now carry a `lax_` prefix. The six renames:

| Old                     | New                         |
|-------------------------|-----------------------------|
| `ncaa_mens_recent`      | `lax_ncaa_mens_recent`      |
| `ncaa_mens_upcoming`    | `lax_ncaa_mens_upcoming`    |
| `ncaa_mens_live`        | `lax_ncaa_mens_live`        |
| `ncaa_womens_recent`    | `lax_ncaa_womens_recent`    |
| `ncaa_womens_upcoming`  | `lax_ncaa_womens_upcoming`  |
| `ncaa_womens_live`      | `lax_ncaa_womens_live`      |

### Migration required

If you referenced any of the old names anywhere in `config.json`,
update them to the new prefixed names. Common places:

- `display_durations` overrides keyed by mode name
- `rotation_order` entries listing which modes to cycle through
- Any custom scripting or automation that pokes the REST API with
  these mode names

There is no backward-compat alias — the old names are no longer
recognized by the plugin dispatch logic.

### Why now

The collision with `hockey-scoreboard` was a silent data loss bug:
whichever plugin loaded second won, without any warning in the
logs. Renaming with a plugin-specific prefix is the only durable
fix until the display controller grows proper namespacing. The
`lax_` prefix was chosen to be short and consistent with how other
prefix-disambiguated codebases handle the same problem.

## 1.0.3 (2026-04-06)

Schema-conformance manifest cleanup.

## 1.0.2 (2026-04-06)

Initial monorepo release.
