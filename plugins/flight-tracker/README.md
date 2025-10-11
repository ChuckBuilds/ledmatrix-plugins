# Flight Tracker Plugin for LEDMatrix

Advanced real-time aircraft tracking plugin that displays live ADS-B data with map visualization, detailed aircraft information, and flight statistics.

![Version](https://img.shields.io/badge/version-1.0.0-blue)
![LEDMatrix](https://img.shields.io/badge/LEDMatrix-%3E%3D2.0.0-green)
![License](https://img.shields.io/badge/license-GPL--3.0-orange)

## ✈️ Features

- **Live Aircraft Tracking**: Real-time display of aircraft from your ADS-B receiver
- **Map View**: Visual map with OpenStreetMap backgrounds showing aircraft positions
- **Altitude-Coded Colors**: Aircraft colored by altitude using standard aviation color scale
- **Overhead View**: Detailed information about the closest aircraft
- **Flight Statistics**: Rotating display of closest, fastest, and highest aircraft
- **Position Trails**: Optional aircraft position history trails
- **Proximity Alerts**: Automatic switch to detailed view when aircraft are very close
- **Flight Plan Data**: Optional integration with FlightAware API for origin/destination
- **Offline Database**: Aircraft type lookups without API calls
- **Cost Control**: Smart API rate limiting and budget management

## 📋 Requirements

### Hardware
- Raspberry Pi (with ADS-B receiver)
- LED Matrix (minimum 64x32, recommended 128x64 or larger)
- ADS-B receiver running dump1090/readsb/SkyAware

### Software
- LEDMatrix v2.0.0 or higher
- Python 3.9+
- SkyAware/dump1090 accessible on local network

### Optional
- FlightAware AeroAPI key (for flight plan data)
- Internet connection (for map tiles and API)

## 🚀 Installation

### Via Web Interface (Recommended)
1. Open LEDMatrix web interface: `http://your-pi-ip:5050`
2. Navigate to **Plugin Store**
3. Search for "Flight Tracker"
4. Click **Install**

### Via API
```bash
curl -X POST http://your-pi-ip:5050/api/plugins/install \
  -H "Content-Type: application/json" \
  -d '{"plugin_id": "flight-tracker"}'
```

### From GitHub URL
```bash
curl -X POST http://your-pi-ip:5050/api/plugins/install-from-url \
  -H "Content-Type: application/json" \
  -d '{"repo_url": "https://github.com/ChuckBuilds/ledmatrix-flight-tracker"}'
```

## ⚙️ Configuration

### Basic Configuration

The plugin requires your ADS-B receiver URL and location coordinates:

```json
{
  "flight-tracker": {
    "enabled": true,
    "skyaware_url": "http://192.168.86.30/skyaware/data/aircraft.json",
    "center_latitude": 27.9506,
    "center_longitude": -82.4572,
    "map_radius_miles": 10,
    "update_interval": 5
  }
}
```

### Finding Your Coordinates

1. **Google Maps**: Right-click on your location → first number is latitude, second is longitude
2. **SkyAware**: Your receiver may show coordinates in the settings
3. **GPS App**: Use any GPS app on your phone

### Advanced Configuration

#### Map Background
```json
{
  "flight-tracker": {
    "map_background": {
      "enabled": true,
      "tile_provider": "osm",
      "fade_intensity": 0.3,
      "brightness": 1.0,
      "contrast": 1.0,
      "saturation": 1.0,
      "cache_ttl_hours": 8760
    }
  }
}
```

**Tile Providers:**
- `osm` - OpenStreetMap (default, free)
- `carto` - CartoDB Light theme
- `carto_dark` - CartoDB Dark theme
- `stamen` - Stamen Terrain
- `esri` - ESRI World Street Map

**Custom Tile Server:**
```json
{
  "map_background": {
    "custom_tile_server": "http://your-tile-server:8080"
  }
}
```

#### Flight Plan Data (Optional)

Requires FlightAware AeroAPI key:

```json
{
  "flight-tracker": {
    "flight_plan_enabled": true,
    "flightaware_api_key": "your-api-key-here",
    "max_api_calls_per_hour": 20,
    "daily_api_budget": 60,
    "flight_plan_cache_ttl_hours": 12
  }
}
```

**Getting a FlightAware API Key:**
1. Sign up at https://aeroapi.flightaware.com/
2. Free tier: 1,000 queries/month (~$0.005 per query)
3. Copy your API key to configuration

**Cost Control Features:**
- Daily budget limits
- Hourly rate limiting
- Smart callsign filtering (only fetch commercial flights)
- 12-hour caching
- Monthly budget warnings

#### Proximity Alerts
```json
{
  "flight-tracker": {
    "proximity_alert": {
      "enabled": true,
      "distance_miles": 0.1,
      "duration_seconds": 30
    }
  }
}
```

#### Display Options
```json
{
  "flight-tracker": {
    "zoom_factor": 1.0,
    "show_trails": false,
    "trail_length": 10,
    "display_duration": 30
  }
}
```

## 🎮 Display Modes

The plugin provides three display modes that can be cycled through in your rotation:

### 1. Map View (`flight-tracker-map`)
- Shows all aircraft within radius
- Color-coded by altitude
- Optional map background
- Aircraft count displayed

### 2. Overhead View (`flight-tracker-overhead`)
- Detailed info on closest aircraft
- Callsign, altitude, speed
- Distance and heading
- Aircraft type (if available)

### 3. Stats View (`flight-tracker-stats`)
- Rotates between three views:
  - **Closest**: Nearest aircraft
  - **Fastest**: Highest ground speed
  - **Highest**: Maximum altitude
- Automatically cycles every 10 seconds

### Adding to Rotation

In your main `config.json`:
```json
{
  "display_modes": [
    "clock",
    "flight-tracker-map",
    "flight-tracker-overhead",
    "flight-tracker-stats",
    "weather"
  ],
  "mode_duration": 30
}
```

## 🎨 Altitude Color Scale

Aircraft are colored by altitude using standard aviation colors:

| Altitude | Color |
|----------|-------|
| Ground - 500ft | Deep Orange-Red |
| 1,000ft | Orange |
| 4,000ft | Yellow |
| 8,000ft | Green |
| 10,000ft | Teal |
| 20,000ft | Blue |
| 30,000ft | Deep Blue |
| 40,000ft+ | Purple/Magenta |

## 🔧 Troubleshooting

### No Aircraft Displayed

1. **Check SkyAware URL**:
   ```bash
   curl http://your-pi-ip/skyaware/data/aircraft.json
   ```
   Should return JSON with aircraft data

2. **Verify Coordinates**: Make sure latitude/longitude are correct

3. **Check Radius**: Increase `map_radius_miles` if no aircraft in range

4. **Test Receiver**: Open SkyAware web interface to verify it's working

### Map Background Not Showing

1. **Check Internet**: Map tiles require internet connection
2. **Clear Cache**: Delete cached tiles in `~/.cache/ledmatrix/map_tiles/`
3. **Try Different Provider**: Change `tile_provider` to `carto` or `osm`
4. **Disable Temporarily**: Set `map_background.enabled` to `false`

### API Rate Limits

If you see "Rate limit reached" messages:
1. **Increase Cache TTL**: Set `flight_plan_cache_ttl_hours` to 24
2. **Reduce Budget**: Lower `max_api_calls_per_hour` to 10
3. **Disable Temporarily**: Set `flight_plan_enabled` to `false`
4. **Check Costs**: Monitor at https://aeroapi.flightaware.com/portal/

### Performance Issues

1. **Reduce Radius**: Lower `map_radius_miles` to 5 or less
2. **Disable Trails**: Set `show_trails` to `false`
3. **Increase Update Interval**: Set `update_interval` to 10 seconds
4. **Disable Map**: Set `map_background.enabled` to `false`

## 📊 Data Sources

### Aircraft Data (Required)
- **Source**: Local ADS-B receiver (dump1090/readsb)
- **Format**: SkyAware JSON format
- **Update**: Real-time (1-5 second updates)
- **Cost**: Free (local data)

### Map Tiles (Optional)
- **Source**: OpenStreetMap or other tile providers
- **Format**: PNG tiles (256x256px)
- **Caching**: 1 year default TTL
- **Cost**: Free (public tile servers, fair use policy)

### Flight Plans (Optional)
- **Source**: FlightAware AeroAPI
- **Format**: JSON API
- **Caching**: 12 hours default
- **Cost**: ~$5-10/month with smart usage

### Aircraft Database (Optional)
- **Source**: OpenSky Network / LEDMatrix offline DB
- **Format**: Local SQLite database
- **Update**: Manual updates
- **Cost**: Free

## 🤝 Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly on actual hardware
5. Submit a pull request

## 📝 License

GPL-3.0 License - see LICENSE file for details

## 🙏 Credits

- **OpenStreetMap**: Map tile data
- **FlightAware**: Flight plan API
- **OpenSky Network**: Aircraft database
- **dump1090/readsb**: ADS-B receiver software
- **LEDMatrix**: Display framework

## 📧 Support

- **Issues**: https://github.com/ChuckBuilds/ledmatrix-flight-tracker/issues
- **Discussions**: https://github.com/ChuckBuilds/LEDMatrix/discussions
- **Wiki**: https://github.com/ChuckBuilds/LEDMatrix/wiki

## 🔄 Version History

### 1.0.0 (2025-01-10)
- Initial release
- Map view with altitude-coded aircraft
- Overhead view for closest aircraft
- Flight statistics rotation
- Optional flight plan data
- Offline aircraft database support
- Smart API rate limiting
- Proximity alerts
- Map background with multiple tile providers

---

**Enjoy tracking! ✈️**

