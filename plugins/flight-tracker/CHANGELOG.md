# Changelog

All notable changes to the Flight Tracker plugin will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2025-01-10

### Added
- Initial release of Flight Tracker plugin
- Map view with altitude-coded aircraft positions
- Overhead view displaying detailed information for closest aircraft
- Flight statistics view (closest, fastest, highest) with 10-second rotation
- OpenStreetMap background support with multiple tile providers:
  - OpenStreetMap (default)
  - CartoDB Light and Dark themes
  - Stamen Terrain
  - ESRI World Street Map
  - Custom tile server support
- Altitude-based color coding using standard aviation color scale (ground to 45,000ft)
- Optional aircraft position trails
- FlightAware AeroAPI integration for flight plan data (origin/destination)
- Offline aircraft database support for type lookups without API calls
- Smart API rate limiting and cost control:
  - Hourly rate limits
  - Daily budget limits
  - Monthly budget tracking and warnings
  - Intelligent callsign filtering to reduce API costs
- Proximity alert system:
  - Automatic switch to overhead view when aircraft are very close
  - Configurable distance threshold
  - Configurable alert duration
- Background service for proactive flight plan data fetching
- Comprehensive configuration options:
  - Map appearance controls (brightness, contrast, saturation, fade)
  - Zoom factor for detailed or wide-area views
  - Update interval configuration
  - Display duration per mode
- Map tile caching with configurable TTL (default 1 year)
- Support for displays from 64x32 to larger formats
- Three display modes that integrate with LEDMatrix rotation:
  - `flight-tracker-map`
  - `flight-tracker-overhead`
  - `flight-tracker-stats`
- Comprehensive README with setup instructions, configuration examples, and troubleshooting
- JSON schema for configuration validation
- Example configuration file

### Technical Details
- Built on LEDMatrix plugin API v1.0.0
- Inherits from BasePlugin for seamless integration
- Uses Haversine formula for accurate distance calculations
- Implements efficient tile caching to minimize bandwidth
- Supports both small (64x32) and large (128x64+) display formats
- Dynamic layout adjustment based on display size
- Mixed font rendering: PressStart2P for titles, 4x6 for data
- Robust error handling and fallback mechanisms
- Cache error tracking with automatic map background disable option

### Requirements
- LEDMatrix v2.0.0 or higher
- Python 3.9+
- SkyAware/dump1090/readsb ADS-B receiver
- Pillow (PIL) for image processing
- requests library for HTTP operations
- Optional: pytz for timezone support
- Optional: FlightAware AeroAPI key for flight plan data

### Known Limitations
- Map tile fetching simplified in initial release (basic implementation)
- Full map tile implementation with detailed error handling to be enhanced
- FlightAware API integration uses basic rate limiting (advanced quota management planned)
- Aircraft database requires manual updates (auto-update planned for future release)

### Credits
- OpenStreetMap contributors for map tile data
- FlightAware for AeroAPI flight plan data
- OpenSky Network for aircraft database
- dump1090/readsb developers for ADS-B receiver software
- LEDMatrix framework by ChuckBuilds

---

## Future Roadmap

### Planned for 1.1.0
- Enhanced map tile fetching with better error recovery
- Support for additional tile providers
- Improved aircraft database auto-update mechanism
- Historical flight path tracking
- Airport information overlays
- Noise level visualization
- Customizable aircraft icons

### Planned for 1.2.0
- Multi-receiver support (aggregate data from multiple ADS-B sources)
- MLAT position support
- Aircraft type-specific icons
- Weather overlay integration
- Flight alert notifications (specific airlines, aircraft types, routes)
- Advanced filtering options

### Under Consideration
- Web-based configuration interface
- Mobile app integration
- Real-time audio alerts for proximity
- Integration with other flight tracking services
- Support for additional ADS-B data formats
- 3D visualization mode for larger displays

