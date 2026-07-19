# Changelog

## [2.6.0] - 2026-07-19

### Added
- **Real map tiles under the radar**: the radar now draws over an OpenStreetMap
  basemap by default (`radar_map_style: osm`), with `carto`, `carto_dark`, and
  `esri` styles available. A self-hosted OSM server is supported via
  `radar_tile_server` (tried first, public mirrors as fallback). The classic
  WeatherStar vector state map remains available as `radar_map_style: vector`
  and is used automatically whenever tiles can't be fetched — and radar is no
  longer a blank black screen outside the US.
- **Nowcast forecast frames**: after the observed frames, the animation now
  plays ~30 minutes of RainViewer's predicted radar, labeled `FCST +10m` etc.
  with yellow progress dots (`radar_show_nowcast`, on by default).
- **`radar_range_miles`**: set the radar coverage as a distance from your
  location to the panel edge instead of the old abstract zoom level. The
  deprecated `radar_zoom` is still honored for existing configs.
- New tuning knobs (Advanced): `radar_map_brightness`, `radar_past_frames`,
  `radar_frame_seconds`, `radar_loop_pause_seconds`, and an opt-in
  `dynamic_duration` block that holds the radar on screen until a full
  animation loop completes.

### Fixed
- **Radar/basemap misalignment**: the basemap and the radar were rendered at
  different Web-Mercator scales (`_composite_frame` force-cropped the single
  radar tile to at least 128px), so precipitation could be drawn up to ~4×
  too wide and displaced from the map and crosshair — worst on 64×32 panels.
  Both layers now render through one shared viewport and are pixel-aligned on
  every panel size.
- **Radar cut off at tile edges**: only the single RainViewer tile containing
  the configured location was fetched; the view now mosaics every tile that
  intersects the viewport, and the crosshair marks the location's true
  projected position instead of assuming panel center.
- **Frames lost on restart**: radar tiles and the frame index are now cached
  (disk + cache manager), so a restart rebuilds the animation without
  refetching; the `cache_manager` handed to the fetcher was previously unused.
- Font loading for the radar overlay resolved CWD-relative paths and silently
  fell back to PIL's oversized default font; it now resolves the 4x6 font
  relative to the plugin location.
- Radar overlay timestamps no longer rely on the glibc-only `%-I` strftime
  extension.

### Changed
- `radar_update_interval` default lowered from 600s to 180s (minimum from
  300s to 60s): the index poll is a tiny JSON request and tiles are only
  downloaded when RainViewer publishes a new frame, so fresh frames appear
  within ~3 minutes of publication instead of up to 10+ minutes late.
- `radar.py` is replaced by `weather_radar.py` + `weather_map_tiles.py`
  (plugin-unique module names, per the repo's deferred-import collision rule).

## [2.5.1] - 2026-06-14

### Changed
- **Full moon-phase names restored on the almanac page**: the redesigned layout
  (capped moon icon + adaptive title font) freed up the horizontal room the old
  abbreviations were working around, so the page now shows "Waxing/Waning
  Crescent" and "Waxing/Waning Gibbous" instead of the abbreviated "Wax/Wan"
  forms. It renders the full name where it fits, degrades to the abbreviation
  when the column is tight, and only trims characters as a last resort — so no
  panel ever shows a mid-word cut where a whole word would fit.

### Fixed
- **Missing moonset on the almanac page**: once a month the moonset slot showed
  `---`. astral only searches a single calendar day, so on the one day the
  moon's set straddles midnight it raises "Moon never sets on this date" even
  though the moon clearly sets that afternoon (sffjunkie/astral #88, #105 — both
  open and unreleased as of astral 3.2, the latest release). When astral fails,
  we now recover the time by scanning the moon's elevation across the local day
  with astral's own ephemeris and bisecting the horizon crossing. Matches
  astral to the minute on normal days; the same fallback covers moonrise.
- **"Illumination %" was actually cycle progress**: the percentage next to the
  moon-phase name showed how far through the lunar cycle the moon is (0=new,
  0.5=full), not how much of the disc is lit — so a waning crescent read "86%"
  when it's ~13% illuminated. It now shows the true illuminated fraction.

## [2.3.2] - 2026-06-04

### Fixed
- **Almanac (moon) page overflow on short/narrow panels**: the moon-phase name
  is rendered in a wide 8px font (PressStart2P), so names like "Wax Gibbous" or
  "Last Quarter" overran the narrow text column on 64- and 128-wide panels —
  colliding with the right-aligned illumination % and, for the longer names,
  running clean off the right edge. The day-length row was also drawn past the
  bottom of a 32px-tall panel. The page now sizes its title font and row
  positions to the actual panel: it falls back to the 6px font (and truncates
  as a last resort) when the name won't fit beside the %, and drops any row that
  would spill past the bottom edge. Verified across 64×32, 128×32, 256×32, and
  128×64.

## [2.3.0] - 2026-05-27

### Changed
- **Migrated weather data source from OpenWeatherMap to Open-Meteo**: No API key
  required. Open-Meteo is a free, open-source weather API that covers all
  previously displayed fields: temperature, humidity, wind, UV index, dew point,
  visibility, pressure, feels-like, hourly/daily forecasts, sunrise/sunset, moon
  phase, moonrise/moonset.
- **Weather alerts now use NWS API** (US locations only, free, no key). Alerts
  are silently skipped for non-US locations.
- Removed `api_key` from plugin configuration. Existing installs with an
  `api_key` in `config.json` or `config_secrets.json` can safely leave or remove it.

## [2.1.0] - 2026-02-13

### Fixed
- **CRITICAL: "No Data Available" with valid API key**: Added specific HTTP error handling
  for One Call API 3.0 401 Unauthorized errors with actionable log messages guiding users
  to subscribe to One Call 3.0
- **Wind direction always showing "N"**: Fixed missing `wind_deg` field in weather data
  storage; wind direction is now correctly read from the API response
- **Geocoding failure causes infinite retry loop**: Empty geocoding results now set
  `last_update` to prevent burning API calls on unresolvable locations

### Improved
- Diagnostic "no data" display now shows *why* there's no data (no API key, API
  subscription error, unknown location) instead of generic "No Weather Data"
- Updated config schema and README to clearly state the One Call API 3.0 subscription
  requirement

## [2.0.9] - 2025-11-05

### Fixed
- **Weather icons not displaying**: Fixed import path for WeatherIcons class
  - Moved WeatherIcons from `src/old_managers/weather_icons.py` to plugin directory
  - Plugin now self-contained and no longer depends on old_managers directory
  - Weather icons now display correctly instead of showing placeholder circles

### Changed
- **Internal mode cycling**: Implemented internal mode cycling for weather displays
  - Plugin now cycles through current, hourly, and daily forecast modes automatically
  - Similar to hockey and football plugins, handles mode rotation internally
  - Works correctly with display controller's plugin-first dispatch system

## [2.0.8] - 2025-10-19

### Fixed
- **CRITICAL**: Added missing `class_name` field to manifest
  - Plugin system now correctly identifies the Python class to load
  - Fixes "No class_name in manifest" error

## [2.0.7] - 2025-10-19

### Removed
- Removed redundant `enabled` field from config schema
  - Plugin enabled state is now managed solely by the plugin system
  - This eliminates confusion from having two "enabled" toggles in the UI

### Fixed
- Configuration UI no longer shows duplicate enabled toggle
- Reduced debug log verbosity - removed noisy hourly state comparison logs

## [2.0.6] - 2025-10-19

### Changed
- Comprehensive weather display with current conditions, hourly forecast, and daily forecast
- UV index display
- Wind direction
- Weather icons
- State caching
- API counter tracking
- Error handling

