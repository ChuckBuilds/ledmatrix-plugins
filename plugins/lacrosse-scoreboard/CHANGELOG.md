# Changelog

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
