# Changelog

## [1.21.1] - 2026-08-03

### Fixed
- **Live games no longer flood the log**: `has_live_content()` is called from the display path — once per *frame* in Vegas mode — and it emitted a per-league INFO line for MLB, MiLB and NCAA on every call where that league had any live game. Those three lines had no throttle at all; only the final summary did, and that one skipped the throttle whenever the answer was True ("always log True immediately"), which is harmless for an occasional caller and ruinous for a per-frame one. Measured on a 512x64 device with nine live MLB games: **13,871 lines a minute, 98% of the entire journal**, which both buried every other message and put needless journald writes on the render path. The three per-league lines are now folded into the single summary, which carries the same counts, and that summary is logged when the answer *changes* — a game starting or ending, a league flipping — then at most once a minute while it holds. Same device after the fix: **3 lines a minute.** A steady state is still visible in the log; a live afternoon no longer costs tens of thousands of lines.
## [1.21.0] - 2026-08-02

### Fixed
- Explain an empty screen instead of leaving the user guessing. A favorite team code that is not a real ESPN abbreviation matched no game and showed nothing, and so did a correct code before its season started - the two were indistinguishable from the logs. The plugin now says which it is, suggests the right code for a near miss (GBP -> GB), and reports when the league's next games are. The check runs in the background, once per league, and cannot affect what is displayed.

## [1.20.3] - 2026-08-02

### Fixed
- **Leftover `"timezone": "UTC"` no longer has to be removed by hand**: the write-back bug in versions before 1.20.0 persisted `"timezone": "UTC"` into the saved plugin config, where it then shadowed the real global timezone — so users who updated to 1.20.0 still saw UTC until they edited the config. That stale value is now detected and ignored automatically whenever the global or system timezone disagrees, with a warning naming what it used instead. `Etc/UTC` is the unambiguous way to ask for UTC on purpose and is always honored; it is a spelling the old bug could never have produced.
- **The core's own `"UTC"` default no longer masks a missing global setting**: `ConfigManager.get_timezone()` is `self.config.get('timezone', 'UTC')`, so it returns `"UTC"` for a config with no `timezone` key at all. 1.20.0 took that at face value and therefore never reached the host system zone. Resolution now reads the raw config dict and treats an absent key as absent, falling through to the system timezone as designed.

## [1.20.1] - 2026-07-28

### Fixed
- **Vegas scroll showed only one game**: `get_vegas_content()` returned the union
  of every scroll display's cached items, so once the standalone rotation had
  rendered a mode, Vegas inherited that mode's games — with a single live game in
  progress the whole ticker entry collapsed to one card. It now reads a dedicated
  combined slate (live + recent + upcoming, across every enabled league) that
  cannot be clobbered by the standalone displays, and a game held by two displays
  is no longer shown twice.
- **Vegas content stalled the scroll**: building the Vegas slate called `update()`,
  putting network I/O on the render path and freezing the ticker for seconds. The
  slate is now rendered from whatever data the plugin already has, and is rebuilt
  only when the games actually change (fingerprinted on scores, inning, count and
  game set) instead of on every fetch.
- **Vegas build hijacked the standalone scroll**: rendering the Vegas slate went
  through `prepare_and_display()`, which also repoints the manager's active
  scroll display, so the next standalone frame rendered the Vegas slate instead
  of the game type the rotation was showing. Vegas now uses a new
  `prepare_content()` that renders without switching the active display.

### Changed
- **`game_card_width` guidance**: the description advised lowering it on
  multi-panel chains, which is backwards — on a wide panel cards need to be
  *wider* to stay readable. It now suggests roughly display width / 3.

## [1.20.0] - 2026-07-28

### Fixed
- **Game start times shown in UTC**: The plugin read the LEDMatrix global timezone only from `cache_manager.config_manager`. On cores that hang `config_manager` off the plugin manager instead, that lookup came back empty and every start time was rendered in UTC — a 6:45pm Central first pitch displayed as `11:45PM` — while plugins that check the plugin manager first (clock-simple, geochron) showed the correct local time on the same device. Timezone resolution now lives in one place (`baseball_timezone.py`) shared by the switch-mode scorebug, the scroll-mode game card and the plugin manager, and tries, in order: the plugin's own `timezone` setting, `plugin_manager.config_manager`, `cache_manager.config_manager`, the host system zone (`TZ`, `/etc/timezone`, `/etc/localtime`), and only then UTC.
- **`timezone` setting was silently discarded**: The key was never declared in `config_schema.json`, which sets `additionalProperties: false`, so hand-editing it in the saved config had no effect. It is now a documented string property under Advanced Settings.
- **Plugin no longer writes a timezone back into your config**: The manager used to assign `self.config["timezone"]`, mutating the dict the core handed it and persisting a bogus `"timezone": "UTC"` into the saved plugin config. The resolved value is now kept on the instance and passed to sub-components via a copy.

### Added
- `timezone` (Advanced Settings): optional IANA zone override, e.g. `America/Chicago`. Blank (the default) follows the LEDMatrix global timezone.

## [1.19.0] - 2026-07-09

### Added
- **Player Card screen**: A new dedicated full-screen card (`show_player_card`, per league; MLB & NCAA Baseball) that periodically rotates into the live display for the current batter — and optionally the pitcher — with a headshot image, jersey number, position, bat/throw hand, and season stats (AVG/HR/RBI for hitters, ERA/W-L/K for pitchers). Bio + headshot are fetched from ESPN's athlete API and cached (in-memory + on disk). On tiny panels (e.g. 64×32) the headshot is hidden and a compact text card is shown; the card degrades to text-only whenever a headshot is unavailable and is skipped entirely for MiLB (no ESPN player data). Tunable under Customization → Player Card.
- **Team-color grid tint**: The Traditional Scoreboard now paints a subtle (~12% brightness) wash of each team's real ESPN color behind its row, plus a solid team-color accent strip on the left edge (toggle `show_team_color_backgrounds`, default on; requires `use_team_colors`).

### Changed
- **Clearer Pitcher/Batter labels**: The pitcher/batter screen now spells out `Pitcher:` and `Batter:` instead of the ambiguous `P:` / `B:` (the latter clashed visually with the grid's Balls indicator).

## [1.0.4] - 2025-10-20

### Added
- **Proper Font Loading**: Load PressStart2P and 4x6 fonts matching original managers
- **Logo Loading**: Full logo path resolution with case-insensitive matching
- **Logo Sizing**: Logos properly scaled to display dimensions (width/height * 1.5)
- **Scoreboard Rendering**: Professional scoreboard layout with team logos, scores, and status
- **Text Outline**: Text rendering with black outlines for better readability

### Changed
- **Replaced Placeholder**: Removed TODO comments and placeholder text rendering
- **Visual Parity**: Now matches original baseball manager layout and appearance

## [1.0.3] - 2025-10-20

### Fixed
- **Live Priority Integration**: Implemented `has_live_content()` method to properly integrate with display controller
- **Display Logic**: Plugin now only shows "baseball_live" mode when there are actual live games
- **No More "No Live Games"**: Plugin won't be called when there are no live games to display
- **Mode Filtering**: Added `get_live_modes()` to only show live mode during live priority takeover

## [1.0.2] - 2025-10-19

### Initial
- Initial release with basic baseball scoreboard functionality

