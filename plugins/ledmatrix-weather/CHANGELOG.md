# Changelog

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

