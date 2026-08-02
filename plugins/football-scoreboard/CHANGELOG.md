# Changelog

## [2.9.4] - 2026-08-02

### Fixed
- **Live games will no longer flood the log**: `has_live_content()` is called from the display path — once per *frame* in Vegas mode — and it emitted a per-league INFO line for NFL and NCAA FB on every call where that league had any live game. Those two lines had no throttle at all; only the final summary did, and that one skipped the throttle whenever the answer was True ("always log True immediately"), which is harmless for an occasional caller and ruinous for a per-frame one. The identical defect was measured on the sibling baseball plugin at **13,871 lines a minute, 98% of the entire journal**, on a 512x64 device with nine live games; football was quiet only because this is the off-season, and would have started spamming the moment the season began. The two per-league lines are now folded into the single summary, which carries the same counts, and that summary is logged when the answer *changes* — a game starting or ending, a league flipping — then at most once a minute while it holds.

## [2.9.3] - 2026-08-02

### Fixed
- **Leftover `"timezone": "UTC"` no longer has to be removed by hand**: the write-back bug in versions before 2.9.0 persisted `"timezone": "UTC"` into the saved plugin config, where it then shadowed the real global timezone — so users who updated to 2.9.0 still saw UTC until they edited the config. That stale value is now detected and ignored automatically whenever the global or system timezone disagrees, with a warning naming what it used instead. `Etc/UTC` is the unambiguous way to ask for UTC on purpose and is always honored.
- **The core's own `"UTC"` default no longer masks a missing global setting**: `ConfigManager.get_timezone()` is `self.config.get('timezone', 'UTC')`, so it returns `"UTC"` for a config with no `timezone` key at all. 2.9.0 took that at face value and therefore never reached the host system zone. Resolution now reads the raw config dict and treats an absent key as absent.

## [2.9.1] - 2026-07-29

### Fixed
- Correct the NCAA football example team codes in the favorite-teams help text: Alabama is ALA in ESPN's data, not BAMA. Copying the old example matched no team and showed nothing.

## [2.9.0] - 2026-07-29

### Fixed
- **Game start times shown in UTC**: The plugin read the LEDMatrix global timezone only from `cache_manager.config_manager`. On cores that hang `config_manager` off the plugin manager instead, that lookup came back empty and every start time was rendered in UTC, while plugins that check the plugin manager first (clock-simple, geochron) showed the correct local time on the same device. Timezone resolution now lives in `football_timezone.py`, shared by the scorebug and the plugin manager, and tries, in order: the plugin's own `timezone` setting, `plugin_manager.config_manager`, `cache_manager.config_manager`, the host system zone (`TZ`, `/etc/timezone`, `/etc/localtime`), and only then UTC.
- **`timezone` setting was silently discarded**: The key was never declared in `config_schema.json`, which sets `additionalProperties: false`, so hand-editing it in the saved config had no effect. It is now a documented string property under Advanced Settings.
- **Plugin no longer writes a timezone back into your config**: `on_config_change` used to assign `self.config["timezone"]`, mutating the dict the core handed it and persisting a stale `"timezone": "UTC"` into the saved plugin config, which then shadowed the real global timezone.

### Added
- `timezone` (Advanced Settings): optional IANA zone override, e.g. `America/Chicago`. Blank (the default) follows the LEDMatrix global timezone.

## [2.8.1] - 2026-07-10

### Fixed
- **Adaptive layout (beta): blurry text on small panels.** Two of the ladder rungs
  used for score/status/detail text rendered with visible antialiasing:
  `press_start@10px`/`@12px` (PressStart2P only rasterizes crisply at exact
  multiples of its 8px design grid) and `5by7.regular` (never crisp at any
  size tested, in this or any other font's PIL rendering). Both dropped;
  `4x6-font` corrected from 6px (33% antialiased) to 7px (its actual crisp
  size). Every rung is now verified with `measure_font_crispness()` at 0%
  antialiasing, with a regression test guarding it.
- **Adaptive layout (beta): score text could overlap the team logos on
  larger panels.** Score/status/detail text was sized to the largest crisp
  font that fit its own region — on a big panel that region has generous
  room, so the score could balloon large enough to visually overlap/obscure
  the logos next to it (which scale by a fixed geometry factor instead).
  Text now sizes proportionally to the panel's scale factor relative to the
  classic fixed size for that element (score=10px, status=8px, detail=6px)
  via the new core `LayoutContext.fit_text_proportional()`, matching
  classic's visual balance at every size while still being crisp and
  larger than classic's fixed size.

## [2.8.0] - 2026-07-10

### Added
- **Adaptive layout (beta, opt-in)**: set `"layout_mode": "adaptive"` to scale
  fonts, logos, and element regions to the panel size — score/status/detail
  text grows on large panels (e.g. 32px score on a 256x128) instead of staying
  at the fixed classic sizes, and layouts degrade gracefully on small panels.
  Built on the LEDMatrix core adaptive layout system (`src/adaptive_layout.py`);
  on older cores the plugin silently keeps the classic layout.
  - **Default is `"classic"`** — rendering is byte-identical to 2.7.0 unless
    you opt in (verified by the committed golden images).
  - **Your customization still applies in adaptive mode**: explicitly
    configured `customization.<element>.font`/`font_size` win over the
    adaptive sizing, and `customization.layout.<element>` x/y offsets
    translate elements from their computed positions. Note: adaptive mode
    applies layout offsets in scroll mode too (classic scroll never did).
  - **To revert**: set `"layout_mode": "classic"` in the plugin config — no
    reinstall needed. (Or roll back to 2.7.0 in the plugin store.)
- Manifest now declares `display.design_size` (128x32), enabling the harness
  scale-up fill check. Adaptive-mode golden images live in
  `test/golden-adaptive/` (`test_adaptive_layout_mode.py`).

## [2.4.0] - 2026-06-15

### Added
- **Score/win celebration takeover**: a full-screen flash when a favorite team
  scores or wins a live game. The phrase is inferred from the points scored
  between updates: `TOUCHDOWN!` / `<TEAM> TD!` (+6 or more), `<TEAM> FIELD GOAL!`
  (+3), `<TEAM> SAFETY!` (+2), `<TEAM> SCORES!` (otherwise), and `<TEAM> WINS!`
  when a tracked game goes final in the favorite's favor.
  - A touchdown that lands as +6 then a +1 extra point produces a single
    takeover (the follow-up is suppressed while the first is on screen).
  - First-sighting and downward corrections never fire; wins only fire for games
    actually watched go live (no false win when the board boots after the final).
  - Per-league config: `celebration_enabled` (default on), `celebration_duration`
    (seconds, default 8), `celebrate_opponent_scores` (default off).

## [2.0.4] - 2025-10-21

### Added
- **Diagnostic Logging**: Added detailed logging to identify configuration and data fetching issues
  - Logs league configuration (enabled status, favorite teams) on initialization
  - Logs smart polling decisions (should_update, time_since_last_update)
  - Logs each league check with enabled status and type information
  - Helps diagnose why plugin isn't fetching game data

### Technical Details
- Configuration logged at startup: enabled status for each league
- Update method logs polling interval checks
- League iteration logs show whether each league is enabled and its data type
- Purpose: Identify if configuration is being read correctly or if smart polling is blocking updates

## [2.0.3] - 2025-10-21

### Fixed
- **CRITICAL: display() Method Signature**: Fixed argument mismatch with display controller
  - Added `explicit_mode` as first parameter: `display(self, explicit_mode=None, force_clear=False)`
  - Fixed "got multiple values for argument 'force_clear'" error
  - Display controller passes mode name as first positional argument
  - Plugin now correctly receives the requested mode from display controller

### Technical Details
- Display controller calls: `plugin.display('football_live', force_clear=False)`
- Previous signature: `display(self, force_clear=False)` caused conflict
- New signature: `display(self, explicit_mode=None, force_clear=False)` matches expected interface
- The `explicit_mode` parameter receives the mode name ('football_live', 'football_recent', 'football_upcoming')

## [2.0.2] - 2025-10-21

### Fixed
- **CRITICAL: AttributeError in get_info()**: Removed references to deprecated flat config attributes
  - `show_records` and `show_ranking` are now per-league settings, not top-level attributes
  - Fixed "AttributeError: 'FootballScoreboardPlugin' object has no attribute 'show_records'"
  - These values are still available in the `leagues_config` dictionary returned by `get_info()`
  - No user-facing impact - plugin will now load correctly in web interface

### Technical Details
- After nested config migration in v2.0.1, these attributes moved to per-league configuration
- Removed lines 1778-1779 from `get_info()` method that accessed obsolete attributes
- Settings remain accessible via: `leagues_config['nfl']['show_records']`, etc.

## [2.0.1] - 2025-10-21

### Fixed
- **Interface Compatibility**: Updated `display()` method signature to match BasePlugin v3 interface
  - Changed from `display(canvas, explicit_mode=None)` to `display(canvas, width, height, explicit_mode=None)`
  - Ensures compatibility with LEDMatrix plugin system v2.0+
  - No functional changes to plugin behavior

## [1.6.0] - 2025-10-20

### Changed
- **Nested Config Schema**: Migrated from flat to nested config structure for better organization
  - NFL settings now grouped under `nfl` with sub-sections:
    - `display_modes`: Control live/recent/upcoming display
    - `game_limits`: Configure how many games to show
    - `display_options`: Toggle records, rankings, odds
    - `filtering`: Control favorite teams and all-live behavior
  - NCAA Football settings now grouped under `ncaa_fb` with same structure
  - **Backward Compatible**: Still supports flat config structure from older versions
  - **Benefits**:
    - Much easier to navigate 32 configuration options
    - Collapsible sections in web UI reduce visual clutter
    - Logical grouping makes related settings easier to find
    - Cleaner, more professional configuration experience

### Technical Details
- Added `get_config_value()` helper function to support both flat and nested config access
- Config reading attempts flat keys first (e.g., `nfl_enabled`), then nested paths (e.g., `['nfl', 'enabled']`)
- No breaking changes - existing flat configs continue to work
- Updated logging to show whether config is flat or nested
- Example nested schema provided in `config_schema_nested_example.json`

## [1.5.2] - 2025-10-20

### Added
- **Step-by-Step Display Logging**: Added detailed step logging throughout display() method
  - Step 1: Shows explicit_mode and current_games count
  - Step 2: Shows auto-selected or provided display_mode  
  - Step 3-4: Shows filtering process and results
  - Step 5: Shows when no games available
  - Step 6-8: Shows game display process
  - Full exception handling with stack traces

### Purpose
- Diagnose where display() method is exiting or failing
- Identify if games are being filtered out incorrectly
- Confirm _display_game() is being called
- Catch any hidden exceptions

## [1.5.1] - 2025-10-20

### Added
- **Diagnostic Logging**: Added comprehensive logging to debug display controller integration
  - Logs when `update()` method is called
  - Logs when `display()` method is called with mode parameter
  - Shows if plugin is initialized
  - Shows how many games are being fetched and added
  - Helps diagnose why display isn't updating

### Purpose
- Identify if display controller is calling plugin methods
- Confirm data is being fetched successfully
- Debug "manager_to_display is None" issue

## [1.5.0] - 2025-10-20

### Added
- **Background Service Integration**: Async, non-blocking API fetching using background worker threads
  - Submitted via `background_service.submit_fetch_request()` with callbacks
  - Returns cached data immediately while fetch happens in background
  - Prevents display freezing during 2-5 second ESPN API calls
  - Tracks pending requests to avoid duplicate fetches
  - Graceful fallback to synchronous fetching if background service unavailable

- **Season-Wide Caching Strategy**: Dramatically reduced API calls by caching entire season
  - **NFL**: Cache key `football_nfl_season_2024` (Aug 1 → March 1) 
  - **NCAA FB**: Cache key `football_ncaa_fb_season_2024` (Aug 1 → Feb 1)
  - Fetches ~300 games once per season instead of daily
  - **API call reduction**: 99% fewer calls (1 per season vs 1 per day)
  - Long-lived cache persists until season changes or manual clear

- **Separate Live Game Fetching**: Per-league optimization for live vs season data
  - **Live strategy**: Fetches only today's games (`?dates=20251020&limit=100`)
  - **Season strategy**: Fetches full season data (`?dates=20240801-20250301&limit=1000`)
  - Decision made **per league** to handle different schedules (NFL Sunday, NCAA FB Saturday)
  - **10-25x faster** live updates (~200ms vs 2-5s)
  - Cache TTL: 60s for live games, long-lived for season data

- **Automatic Logo Downloading**: Missing logos automatically downloaded from ESPN API
  - Uses `LogoDownloader.get_logo_filename_variations()` for name variations (e.g., TA&M vs TAANDM)
  - Downloads logo from ESPN API if not found locally
  - Creates placeholder image if download fails
  - Falls back to text display if all attempts fail
  - Matches old manager behavior exactly

- **Game Rotation Logic**: Cycles through multiple games within same mode
  - Rotates every 15 seconds by default (configurable via `game_display_duration`)
  - Resets rotation when game list changes (using hash-based detection)
  - Logs game switches: `"[football_recent] Switched to: AUB @ UGA"`
  - Matches old `SportsRecent`/`SportsUpcoming` behavior exactly

- **Separate Recent Game Layout**: Dedicated layout for final/completed games
  - Score displayed at **bottom** (not middle like live games)
  - **White** text colors (not gold/green like live games)
  - Logos positioned closer to edges (`+2` instead of `+10`)
  - Shows "Final" or "Final/OT" at top
  - No down/distance or timeouts (only relevant for live games)
  - Matches old `SportsRecent._draw_scorebug_layout()` pixel-perfect

- **Display Duration Controls**: Two new configurable timing settings
  - `display_duration` (default 30s): How long mode is shown before display controller rotates to next plugin
  - `game_display_duration` (default 15s): How long each individual game is shown before rotating within mode
  - Range: 5-300s for mode duration, 3-60s for game duration
  - Allows full customization of rotation speed

### Changed
- **Recent Games Sorting**: Fixed to show most recent games first (reverse chronological order)
  - Old behavior: Sorted by start_time ascending (showed Oct 4 game first)
  - New behavior: Sorted by start_time descending (shows Oct 18 game first)
  - Uses negative timestamp for recent games: `-dt.timestamp()` for reverse sort
  - Matches old `SportsRecent` line 942: `reverse=True`

- **Per-Team Game Limits**: Changed from per-league limits to per-favorite-team limits
  - `recent_games_to_show: 1` now means **1 game per favorite team**, not 1 total
  - Example: TB and UGA with setting=1 → Shows 1 TB game + 1 UGA game = 2 total
  - Uses per-team counting: `{league_key}:{team_abbr}:{state}` keys
  - Matches user expectation: "If I have 2 favorites and want 1 recent, show 2 games"

- **Logging Level**: Set to INFO level to reduce verbose DEBUG output
  - Suppresses cache hit/miss details, filtering minutiae
  - Keeps important messages: initialization, data updates, game counts
  - All WARNING and ERROR messages still logged
  - Added `self.logger.setLevel(logging.INFO)` at initialization

- **Skip Empty Modes**: No longer displays "No Live Games" when mode explicitly requested
  - If display controller requests `football_live` with no games, plugin returns silently
  - Display controller then moves to next mode in rotation
  - Only shows "No games" message when mode was auto-selected
  - Better UX: users only see actual game data or nothing

### Fixed
- **Live-Only Fetch Per League**: Fixed bug where NFL live games would break NCAA FB data
  - `_should_fetch_live_only(league_key)` now checks per league, not globally
  - Sunday NFL games no longer cause NCAA FB to fetch "today only" (and miss Saturday games)
  - Each league makes independent decision based on its own live games
  - Critical for handling different game schedules (NFL vs NCAA FB)

### Technical Details
- Background service initialized with 1 worker thread for memory optimization
- Callback functions update cache asynchronously when fetches complete
- Season cache persists across restarts (stored in cache_manager)
- Logo download uses ESPN team ID and logo URL from API response
- Game rotation uses tuple hash of game IDs to detect list changes
- Per-team counting handles games involving multiple favorites correctly

### Performance Impact
- **Live games**: 10-25x faster fetches (200ms vs 2-5s)
- **Display updates**: Non-blocking (0ms freeze vs 2-5s freeze)
- **API calls**: 99% reduction for season data (1 call vs 365 calls per year)
- **Memory**: Minimal increase (~1MB for full season cache)

## [1.4.1] - 2025-10-20

### Fixed
- **WORKAROUND: Web UI Not Saving Favorite Teams**: Plugin now treats empty favorite teams list as "show all games"
  - If `favorite_teams` is empty but `show_favorite_teams_only` is enabled, the filter is automatically disabled
  - Prevents "No games" message when web UI fails to save arrays properly
  - **ROOT CAUSE**: Web UI is saving array fields as empty strings instead of arrays

### Investigation Needed
- Web UI form submit handler not properly converting array fields before POST
- Config shows: `nfl_favorite_teams: "" (type: str)` instead of `["TB"] (type: list)`
- Need to fix the JavaScript in plugins.html to properly handle array submissions

## [1.4.0] - 2025-10-20

### Added
- **Smart Polling**: Dynamically adjust API polling frequency based on game schedules
  - **Live games**: Poll every 1 minute
  - **Games < 1 hour away**: Poll every 1 minute  
  - **Games < 2 hours away**: Poll every 5 minutes
  - **Games today**: Poll every 10 minutes
  - **Games tomorrow**: Poll every 30 minutes
  - **Games 2+ days away**: Poll every 12 hours
  - **No games scheduled**: Poll every 24 hours

### Benefits
- Dramatically reduces API calls (from 273 games every hour to smart intervals)
- Respects ESPN's API and cache more intelligently
- Football games only on Fri/Sat/Sun, no point polling frequently Mon-Thu
- Logs "Next poll in: X minutes" for visibility

### Technical Details
- Implements `_should_update()` to check polling interval
- Implements `_calculate_next_update_interval()` to adjust based on soonest game
- Finds nearest upcoming game and calculates time until start
- Automatically increases polling frequency as game time approaches

## [1.3.0] - 2025-10-20

### Fixed
- **CRITICAL: Recent Games Not Showing**: Added date range parameters to ESPN API calls
  - Now fetches last 21 days + next 14 days of games (matching old implementation)
  - Previously only fetched "today's" games, missing Saturday's UGA game
  - `recent_games_to_show` means "N games per favorite team", not "N days ago"
  
### Changed
- ESPN API now called with `?dates=YYYYMMDD-YYYYMMDD` parameter
- Matches old base class behavior (21-day lookback for recent games)

### Technical Details
- Old implementation: fetched 21 days of data, then filtered to N most recent games per team
- New implementation: same 21-day fetch, proper filtering by favorite teams
- This fixes UGA's Saturday game not appearing in recent games

## [1.2.2] - 2025-10-20

### Added
- **Deep Game Structure Logging**: Added comprehensive logging to show exact game dict structure when checking favorites
  - Shows all keys in game dict
  - Shows all keys in home_team and away_team dicts
  - Shows actual abbreviation values being compared
  - Shows favorites list and membership check results
  - Limited to first 3 checks to avoid log spam

### Purpose
- Compare with old base class implementation to identify structural differences
- Diagnose why UGA and TB aren't matching when they worked in old managers

## [1.2.1] - 2025-10-20

### Added
- **Enhanced Team Abbreviation Logging**: Added detailed debug logging to show exact team abbreviations returned by ESPN API
  - Shows original and uppercase versions of team abbreviations
  - Shows explicit membership checks against favorites list
  - Helps diagnose why specific teams aren't matching (e.g., if ESPN uses "GEOR" instead of "UGA")

### Changed
- Set logger to INFO level by default to reduce DEBUG noise

## [1.2.0] - 2025-10-20

### Fixed
- **CRITICAL: Favorite Teams Array Handling**: Added robust normalization for favorite_teams configuration
  - Handles both array and comma-separated string formats from web UI
  - Normalizes all team abbreviations to UPPERCASE for consistent matching
  - Case-insensitive team matching (TB, tb, Tb all work)
- **Configuration Validation**: Enhanced config loading with detailed logging
  - Logs RAW config values with types to diagnose web UI saving issues
  - Logs normalized values to show what plugin is actually using
  - Shows enabled/disabled status for each league

### Technical Details
- Added `normalize_favorite_teams()` helper function
- Updated `_is_favorite_game()` to use uppercase comparison
- This ensures UGA, TB, and all favorite teams work regardless of how web UI saves them

## [1.1.9] - 2025-10-20

### Added
- **Startup Configuration Logging**: Added INFO-level logging on startup to show:
  - Which leagues are enabled (NFL, NCAA FB)
  - How many favorite teams are configured for each league
  - Actual favorite team lists (e.g., `['TB']`, `['UGA']`)
- **Troubleshooting**: Immediately visible in logs to diagnose configuration issues

## [1.1.8] - 2025-10-20

### Added
- **Enhanced Debug Logging**: Added detailed filtering logs to diagnose game visibility issues
  - Shows total games available before filtering
  - Logs first 3 games being evaluated with their favorite status
  - Shows favorite teams list and filtering settings for each game
  - Displays final filtered count
- **Troubleshooting**: Helps identify why UGA or other favorite teams aren't showing

## [1.1.7] - 2025-10-20

### Fixed
- **CRITICAL: Favorite Team Filtering**: Added missing favorite team filter logic matching original managers
  - Now properly checks `show_favorite_teams_only` setting
  - Respects `show_all_live` for showing all live games regardless of favorites
  - Filters live, recent, and upcoming games based on favorite teams
- **Timeout Display**: Timeouts now only display for live games (not FINAL or UPCOMING)
- **Debug Logging**: Added detailed game breakdown logging (NFL vs NCAA FB, Live vs Recent vs Upcoming)
  - Helps diagnose why games aren't appearing

### Technical Details
- Filtering logic now matches `SportsLive.update()` from base classes (line 1229)
- Timeout indicators only drawn when `status.state == 'in'` (live games only)
- Enhanced logging shows per-league and per-state game counts

## [1.1.6] - 2025-10-20

### Fixed
- **Live Priority System**: Implemented `has_live_content()` method to properly integrate with display controller
- **Display Logic**: Plugin now only shows "football_live" mode when there are actual live games
- **No More "No Live Games"**: Plugin won't be called when there are no live games to display
- **Mode Filtering**: Added `get_live_modes()` to only show live mode during live priority takeover

## [1.1.5] - 2025-10-20

### Fixed
- **Logo Sizing**: Fixed logo size to match original managers - now uses `display_width/height * 1.5`
- **Visual Parity**: Logos now display at the correct size matching NFL/NCAA FB managers exactly
- **Before**: Logos were too small (20x20 max)
- **After**: Logos properly scaled to display dimensions (96x96 for 64x64 matrix)

## [1.1.4] - 2025-10-20

### Changed
- **Reduced Log Noise**: Throttled repetitive DEBUG logs to only appear every 5 minutes
- **Smarter Logging**: "Updated football data" now only logs when game count changes or every 5 minutes
- **Cleaner Logs**: Removed "Logo not found" debug messages, fail silently and use text fallback
- **Performance**: Less log I/O improves overall system performance

## [1.1.3] - 2025-10-20

### Fixed
- **Logo Loading Case Sensitivity**: Fixed logo loading to try uppercase, lowercase, and original case variations
- **Missing Logos**: Now correctly finds logo files regardless of case (DET.png vs det.png)
- **Logo Fallback**: Improved logo search to match original managers' behavior

## [1.1.2] - 2025-10-19

### Fixed
- **Logo Loading**: Fixed team logo loading by using absolute paths to LEDMatrix assets directory
- **Path Resolution**: Added logic to find LEDMatrix project root and resolve logo paths correctly
- **Debug Logging**: Added better debug logging for logo loading failures
- **Cross-Platform**: Improved path handling for different operating systems

## [1.1.1] - 2025-10-19

### Fixed
- **Upcoming Game Display**: Fixed upcoming games to use proper layout matching original NCAA FB manager
- **Layout Separation**: Added separate `_draw_upcoming_layout()` method for upcoming games vs live/recent games
- **Date/Time Parsing**: Proper parsing and display of game date and time for upcoming games
- **Odds Display**: Added `_draw_dynamic_odds()` method for proper odds display on upcoming games
- **Visual Parity**: Upcoming games now show "Next Game", date, time, team logos, and rankings exactly like original managers

## [1.1.0] - 2025-10-19

### Changed
- **MAJOR VISUAL UPDATE**: Complete rewrite of rendering to match original NFL/NCAA FB managers exactly
  - Added proper font loading with PressStart2P and 4x6 fonts
  - Use `textlength()` for accurate text measurement instead of approximations
  - Updated `_draw_text_with_outline()` to accept font parameter (matching base class API)
  
### Added
- Team records display (e.g., "8-1", "10-0")
- Team rankings display for NCAA (e.g., "#1", "#5")
- Halftime detection and display
- Proper possession indicator mapping (home/away based on team IDs)
- Records/rankings positioning in bottom corners above timeouts

### Fixed
- Possession indicator now correctly identifies home vs away team
- Timeout defaults to 3 if not specified (matching football rules)
- All text rendering now uses proper fonts for consistent appearance
- Text positioning uses accurate measurements instead of character-count approximations

### Technical Details
- Fonts loaded: PressStart2P (8px, 10px), 4x6 (6px)
- Rankings cache infrastructure added (for NCAA rankings)
- Visual layout now pixel-perfect match to original managers
- Halftime status extracted from ESPN API

## [1.0.10] - 2025-10-19

### Fixed
- **CRITICAL**: Fixed type comparison error in cache validation
  - Added explicit type conversion for all numeric configuration values
  - Ensures `update_interval_seconds`, `recent_games_to_show`, `upcoming_games_to_show`, and `display_duration` are proper numbers
  - Fixes "'<' not supported between instances of 'float' and 'str'" error

## [1.0.9] - 2025-10-19

### Fixed
- **CRITICAL**: Fixed cache manager API compatibility
  - Removed invalid `ttl` parameter from `cache_manager.set()` call
  - Fixes "CacheManager.set() got an unexpected keyword argument 'ttl'" error
  - Plugin can now successfully cache game data

## [1.0.8] - 2025-10-19

### Fixed
- **CRITICAL**: Added missing `class_name` field to manifest
  - Plugin system now correctly identifies the Python class to load
  - Fixes "No class_name in manifest" error

## [1.0.7] - 2025-10-19

### Removed
- Removed redundant `enabled` field from config schema
  - Plugin enabled state is now managed solely by the plugin system
  - This eliminates confusion from having two "enabled" toggles in the UI
  - League-specific enabled fields (`nfl_enabled`, `ncaa_fb_enabled`) remain unchanged

### Fixed
- Configuration UI no longer shows duplicate enabled toggle

## [1.0.6] - 2025-10-19

### Changed
- **Per-League Configuration**: All display settings are now configurable separately for NFL and NCAA Football
  - Added `nfl_show_records`, `ncaa_fb_show_records` - Show team records per league
  - Added `nfl_show_ranking`, `ncaa_fb_show_ranking` - Show team rankings per league (NCAA defaults to true)
  - Added `nfl_show_odds`, `ncaa_fb_show_odds` - Show betting odds per league
  - Added `nfl_show_favorite_teams_only`, `ncaa_fb_show_favorite_teams_only` - Filter by favorites per league
  - Added `nfl_show_all_live`, `ncaa_fb_show_all_live` - Override favorites for live games per league
- Removed global settings in favor of per-league control

### Benefits
- Configure rankings to show for NCAA but not NFL (or vice versa)
- Different odds display preferences for professional vs college football
- Independent favorite team filtering for each league

## [1.0.5] - 2025-10-19

### Added
- `show_odds` - Toggle to show/hide betting odds for games
- `show_favorite_teams_only` - Control whether to show only favorite teams or all games
- `show_all_live` - Override favorites to show all live games

### Fixed
- Restored missing configuration options that were removed in 1.0.4

## [1.0.4] - 2025-10-19

### Changed
- **BREAKING CHANGE**: Flattened configuration structure to remove nested objects
  - Replaced `nfl.enabled` with `nfl_enabled`
  - Replaced `nfl.favorite_teams` with `nfl_favorite_teams`
  - Replaced `nfl.display_modes.live` with `nfl_show_live`
  - Replaced `nfl.display_modes.recent` with `nfl_show_recent`
  - Replaced `nfl.display_modes.upcoming` with `nfl_show_upcoming`
  - Replaced `nfl.recent_games_to_show` with `nfl_recent_games_to_show`
  - Replaced `nfl.upcoming_games_to_show` with `nfl_upcoming_games_to_show`
  - Same pattern applied for NCAA FB with `ncaa_fb_*` prefixes
  - Removed `background_service` nested configuration (handled internally)

### Fixed
- Configuration UI now properly displays all fields instead of empty text boxes
- Web interface can now render and save all configuration options

### Technical Details
- Plugin internally rebuilds nested structure from flattened config for backward compatibility
- All league-specific settings now use prefixed flat keys
- Logo directories are automatically determined from league configuration
- Update intervals are shared globally across all leagues

## [1.0.3] - 2025-10-19

### Initial Release
- Support for NFL and NCAA Football games
- Live, recent, and upcoming game modes
- Team logos and professional scorebug layout
- Down/distance and possession indicators
- Timeout tracking
- Scoring event detection

