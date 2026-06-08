# Changelog

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

