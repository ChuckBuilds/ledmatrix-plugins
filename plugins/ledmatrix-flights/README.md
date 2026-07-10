-----------------------------------------------------------------------------------
### Connect with ChuckBuilds

- Show support on Youtube: https://www.youtube.com/@ChuckBuilds
- Stay in touch on Instagram: https://www.instagram.com/ChuckBuilds/
- Want to chat or need support? Reach out on the ChuckBuilds Discord: https://discord.com/invite/uW36dVAtcT
- Feeling Generous? Support the project:
  - Github Sponsorship: https://github.com/sponsors/ChuckBuilds
  - Buy Me a Coffee: https://buymeacoffee.com/chuckbuilds
  - Ko-fi: https://ko-fi.com/chuckbuilds/ 

-----------------------------------------------------------------------------------

# LEDMatrix Flight Tracker Plugin

Real-time aircraft tracking plugin for LEDMatrix with ADS-B data, map backgrounds, flight plans, and proximity alerts.

## Features

- **Real-time Aircraft Tracking**: Displays aircraft positions from SkyAware ADS-B data
- **Multiple Display Modes**:
  - **Map View**: Geographic map with aircraft positions and trails
  - **Overhead View**: Detailed information about the closest aircraft
  - **Stats View**: Statistics showing closest, fastest, and highest aircraft
  - **Auto Mode**: Automatically switches between modes based on proximity alerts
- **Map Backgrounds**: Support for multiple tile providers (OSM, CartoDB, Stamen, ESRI)
- **Flight Plan Data**: Integration with FlightAware API for origin/destination information
- **Offline Aircraft Database**: Local database for aircraft type lookups (reduces API calls)
- **Proximity Alerts**: Live priority mode when aircraft are nearby
- **Trail Rendering**: Visual trails showing aircraft movement paths
- **Altitude Color Coding**: Color-coded aircraft based on altitude (standard aviation scale)
- **Airport Weather (optional)**: METAR/TAF/PIREP/SIGMET for airports you choose, from the free NOAA Aviation Weather Center API — no API key required

## Installation

### From Plugin Store (Recommended)

1. Open the LEDMatrix web interface (`http://your-pi-ip:5000`)
2. Open the **Plugin Manager** tab
3. Find **Flight Tracker** in the **Plugin Store** section and click
   **Install**

### Manual Installation

1. Copy the plugin from the monorepo:
```bash
cp -r ledmatrix-plugins/plugins/ledmatrix-flights /path/to/LEDMatrix/plugin-repos/
```

2. Install dependencies:
```bash
pip install -r plugin-repos/ledmatrix-flights/requirements.txt
```

## Configuration

### Basic Configuration

Add the following to `config/config.json`:

```json
{
  "ledmatrix-flights": {
    "enabled": true,
    "display_duration": 30,
    "update_interval": 5,
    "skyaware_url": "http://192.168.86.30/skyaware/data/aircraft.json",
    "center_latitude": 27.9506,
    "center_longitude": -82.4572,
    "map_radius_miles": 10,
    "display_mode": "auto"
  }
}
```

### Secrets Configuration

**Option 1: Via Web Interface (Recommended)**
When configuring the plugin through the LEDMatrix web interface, the `flightaware_api_key` field is automatically saved to `config/config_secrets.json` as a secret. Just enter your API key in the plugin configuration form.

**Option 2: Manual Configuration**
Add FlightAware API key to `config/config_secrets.json`:

```json
{
  "ledmatrix-flights": {
    "flightaware_api_key": "YOUR_API_KEY_HERE"
  }
}
```

**Getting a FlightAware API Key:**
1. Sign up for a free account at [FlightAware AeroAPI](https://flightaware.com/aeroapi/)
2. Navigate to your account settings and create an API key
3. Free tier includes 1,000 requests per month
4. The API key is only required if you enable `flight_plan_enabled` (for origin/destination information)

**Note:** The plugin will work without an API key for basic aircraft tracking, but flight plan features (origin/destination) will be disabled.

### Full Configuration Options

See `config_schema.json` for complete configuration options including:
- Map background settings (tile provider, brightness, contrast, saturation)
- Proximity alert configuration
- Flight plan fetching settings
- Background service configuration
- Offline database settings

## Display Modes

### Map Mode (`display_mode: "map"`)

Shows a geographic map with:
- Aircraft positions (color-coded by altitude)
- Aircraft trails (if enabled)
- Center position marker
- Aircraft count indicator

### Overhead Mode (`display_mode: "overhead"`)

Shows detailed information about the closest aircraft:
- Callsign
- Altitude (color-coded)
- Speed
- Distance
- Heading
- Aircraft type

### Stats Mode (`display_mode: "stats"`)

Rotates through statistics every 10 seconds:
- **Closest**: Aircraft nearest to center point
- **Fastest**: Aircraft with highest speed
- **Highest**: Aircraft at highest altitude

Includes flight plan data (origin, destination, manufacturer, model, operator) when available.

### Auto Mode (`display_mode: "auto"`)

Automatically switches:
- Uses **overhead** mode when proximity alert is triggered
- Uses **stats** mode otherwise

## Airport Weather (METAR/TAF/PIREP/SIGMET)

An optional add-on for pilots: show aviation weather for airports you choose,
using the **free NOAA Aviation Weather Center API** (`aviationweather.gov`) — no
API key or account needed.

It adds a new **`metar`** rotation view that cycles through, for each configured
airport:

- **Decoded METAR card** — airport identifier, a color-coded flight-category
  badge (**VFR** green, **MVFR** blue, **IFR** red, **LIFR** magenta), plus wind,
  visibility, present weather, ceiling/clouds, temperature/dewpoint, and altimeter.
  It also shows the **observation age** (e.g. `14m`); if the report is stale
  (older than ~75 min, i.e. a likely missed hourly update) the age turns amber
  with a `!` so you never read old weather as current.
- **Raw METAR page** — the raw observation as filed (toggle with `show_raw`).
- **TAF page** — the terminal forecast (toggle with `show_taf`).
- **PIREP page** — recent pilot reports near the airport (toggle with `show_pirep`).
- **SIGMET/AIRMET page** — active advisories (toggle with `show_sigmet`; these are
  region-based, not airport-specific).

> NOTAMs are **not** included — they require separate FAA API credentials
> (OAuth), unlike the key-free weather endpoints above.

### Enabling it

1. Set `metar.enabled` to `true` and list your airports in `metar.airports`
   (ICAO like `KTPA`, or IATA like `TPA`).
2. Add `"metar"` to **Rotation Views** so it appears in the rotation.

```json
{
  "enabled": true,
  "rotation_views": ["map", "stats", "metar"],
  "metar": {
    "enabled": true,
    "airports": ["KTPA", "KJFK"],
    "show_taf": true,
    "show_raw": true,
    "show_pirep": false,
    "show_sigmet": false,
    "update_interval_minutes": 10,
    "page_duration_seconds": 8,
    "altimeter_unit": "inhg",
    "temp_unit": "c",
    "wind_unit": "kt",
    "visibility_unit": "sm"
  }
}
```

**Units** default to the US convention (`A30.01` inHg, statute miles, knots, °C).
For international style set `altimeter_unit` to `hpa` (shows `Q1013`) and
`visibility_unit` to `m` or `km`; `temp_unit` also accepts `f`, and `wind_unit`
accepts `mph`, `kmh`, or `ms`.

Weather is fetched on its own slow cadence (default every 10 minutes; METARs
update roughly hourly), cached, and served stale on any network hiccup. The
refresh is serviced one request per update cycle, so it never stalls the
aircraft display loop.

## Requirements

- Python 3.7+
- `requests` library
- `pillow` (PIL) library
- Access to SkyAware ADS-B data (local or remote)
- FlightAware API key (optional, for flight plan data)

## SkyAware Setup

This plugin requires access to SkyAware ADS-B data. You can use:
- Local SkyAware instance (default: `http://192.168.86.30/skyaware/data/aircraft.json`)
- Remote SkyAware instance
- Any compatible ADS-B JSON endpoint

## FlightAware API (Optional)

Flight plan data is fetched from FlightAware AeroAPI:
1. Sign up at https://www.flightaware.com/commercial/aeroapi/
2. Get your API key
3. Add to `config/config_secrets.json` as shown above

The plugin includes rate limiting and cost controls to manage API usage.

## Offline Aircraft Database

The plugin includes an offline aircraft database for aircraft type lookups, reducing the need for API calls. The database:
- Automatically downloads from FAA and OpenSky Network
- Updates monthly (configurable)
- Provides aircraft type, manufacturer, model, and operator information

## Development

### Testing

Run the emulator to test the plugin:

```bash
cd /path/to/LEDMatrix
python run.py --emulator
```

### Development Viewer

A Windows development viewer is included (`flight_tracker_dev_viewer.py`) for testing map tiles and aircraft data without the LED matrix hardware.

## Migration from Old Branch

This plugin was extracted from the `feature/flight-tracker-manager` branch. All functionality has been preserved:

- ✅ Map tile fetching and caching
- ✅ Aircraft data processing
- ✅ Altitude-based color coding
- ✅ Flight plan fetching
- ✅ Offline aircraft database
- ✅ Proximity alerts
- ✅ Background service
- ✅ All display rendering logic
- ✅ Trail rendering
- ✅ Map background configuration

Configuration has been flattened - remove the `flight_tracker` wrapper from your old config.

## License

MIT

## Author

ChuckBuilds

## Support

For issues and feature requests, please open an issue on the GitHub repository.

