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

![An aircraft overhead on a 128x32 panel: airline tail, callsign, altitude and
speed, route, and distance](../../docs/assets/ledmatrix-flights/hero.png)

*Every image in this README is real plugin output, rendered at the true panel
size from seeded aircraft so it reproduces exactly. Positions and callsigns are
invented.*

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

### Full configuration options

Settings live in the plugin's tab in the web UI and in `config/config.json`
under `ledmatrix-flights`. The full schema is
[`config_schema.json`](config_schema.json).

### Source and polling

| Key | Default | Notes |
|---|---|---|
| `enabled` | `false` | Enable or disable the flight tracker plugin. |
| `data_source` | `"skyaware"` | Where to get live aircraft position data. Choose one setup path: (1) Local receiver — 'skyaware': requires a PiAware/dump1090 ADS-B receiver on your network, most accurate data. (2) Free cloud — 'adsbfi': free global ADS-B feed from adsb.fi, no account or hardware needed. 'adsblol': same idea via adsb.lol. Both free cloud options work worldwide with no sign-up — one of `skyaware`, `adsbfi`, `adsblol`. |
| `skyaware_url` | `"http://192.168.86.30/skyaware/data/aircraf…` | URL to your local ADS-B receiver's aircraft.json endpoint. Only used when data_source is 'skyaware'. Change this to match your receiver's IP address. |
| `update_interval` | `5` | Interval in seconds between aircraft data updates (1–300). |
| `live_update_interval` | `2` | Faster fetch interval (seconds) used while a flight is locked on for the overhead view, so altitude/distance update smoothly. The ADS-B source is ~1Hz, so a low value is safe. Idle fetches use update_interval (1–60). Advanced. |
| `live_priority` | `false` | When enabled, an aircraft entering the proximity radius immediately preempts the normal rotation to show the overhead view for the proximity alert window (see proximity_alert.duration_seconds). Adds a 'flight_tracker_live' rotation slot that stays blank/skipped until a plane is overhead. Leave off for legacy behavior. Advanced. |
| `display_duration` | `30` | How long to show the flight tracker display (10-300 seconds). |
| `flight_records` | — | Track all-time closest and farthest flights ever seen, shown as extra stats rotation slots. |
| `fr24_enrichment` | `true` | Fetch origin/destination and aircraft type for free in the background using FlightRadar24 data. Works with all data sources. This is the recommended free alternative to a paid FlightAware API key — leave enabled unless you have a specific reason to turn it off. Advanced. |
| `fr24_enrichment_interval` | `60` | How often to refresh free FR24 route data in the background. Applies when fr24_enrichment is enabled (30–600). Advanced. |
| `enrichment_provider` | `"adsbnet"` | Fallback source for origin/destination data not covered by FR24 enrichment. 'adsbnet': free route lookups via adsb.lol — good coverage for major airlines, no account needed (recommended). 'flightaware': paid FlightAware AeroAPI — highest coverage but requires a paid subscription configured in the FlightAware section below — one of `adsbnet`, `flightaware`. Advanced. |
| `route_cache_ttl` | `300` | How long to cache flight route enrichment data (60–3600). Advanced. |
| `flight_records.enabled` | `true` | Track and display all-time closest and farthest flights (persisted across restarts). |

### Where you are, and what counts as nearby

| Key | Default | Notes |
|---|---|---|
| `center_latitude` | `27.9506` | Center latitude for the map display (-90–90). |
| `center_longitude` | `-82.4572` | Center longitude for the map display (-180–180). |
| `map_radius_miles` | `10` | Radius in miles to display around center point (1–100). |
| `zoom_factor` | `1.0` | Zoom factor to use more of the display (1.0 = normal, higher = more zoomed in) (0.5–5.0). Advanced. |
| `max_aircraft` | `5` | Maximum aircraft to display per page in area mode (1–20). Advanced. |
| `min_altitude_ft` | `0` | Minimum altitude in feet for area mode filtering. Set to 0 to disable. Advanced. |
| `max_altitude_ft` | `0` | Maximum altitude in feet for area mode filtering. Set to 0 to disable. Advanced. |
| `aircraft_categories` | *(empty)* | ICAO aircraft categories to display (e.g. A1, A2, A3). Empty list shows all. Advanced. |
| `tracked_flights` | *(empty)* | Flight numbers, callsigns, or tail numbers to track specifically (max 3). E.g. ["AA123", "N12345"]. |
| `anchor_airport` | *(blank)* | ICAO or IATA airport code to prioritize in area mode (e.g. KTPA or TPA). Arrivals/departures shown first. |

### Display mode and layout

| Key | Default | Notes |
|---|---|---|
| `display_mode` | `"auto"` | Single-view display mode, used only when 'rotation_views' is not set. 'area' shows multi-aircraft list with FlightWall metrics. 'flight_tracking' shows tracked flight details. 'auto' chooses based on context — one of `map`, `overhead`, `stats`, `area`, `flight_tracking`, `auto`. |
| `rotation_views` | — | Which views the display rotation cycles through. Each selected view gets its own rotation slot and an empty/no-content slot is skipped. Leave all unchecked to show nothing in the normal rotation — useful for an overhead-only board (pair with Overhead Live Priority). When this field is omitted entirely, the single 'Display Mode' setting is used instead (legacy behavior). The overhead view is not listed here; it is driven by live_priority + proximity_alert. |
| `layout` | *(blank)* | Force a specific flight detail layout. Leave empty for auto-selection based on display width — one of `""`, `flight_detail_wide`, `flight_detail_condensed`. Advanced. |
| `widescreen_threshold` | `256` | Minimum canvas width in pixels to use the widescreen flight detail layout (128–1280). Advanced. |
| `show_banner` | `false` | Show a 'FLIGHTS' banner for 2 seconds at the start of each display slot. Advanced. |
| `show_aircraft_icon` | `true` | Show airline logos in area mode (8×8 pixel sprites next to callsigns). Flight detail layouts always show logos in the logo zone when available (52 airlines included as PNG assets). Advanced. |
| `show_trails` | `true` | Show aircraft movement trails. Advanced. |
| `trail_length` | `10` | Number of trail points to display per aircraft (0–50). Advanced. |
| `scroll_speed` | `2` | Scroll speed in pixels per frame for long text (1–10). Advanced. |
| `overhead_alt_interval` | `4` | On the overhead (live-priority) card, the route (e.g. SEA>PHX) and the aircraft model share one text row and alternate. This is how many seconds each stays up before swapping. Set to 0 to disable alternation (route always wins). The model is shown as a friendly name (e.g. 'Boeing 737-900') when the type is known. Advanced. |

### Units and formatting

| Key | Default | Notes |
|---|---|---|
| `units` | `"imperial"` | Legacy unit system toggle. For finer control use the per-metric options below — one of `imperial`, `metric`. |
| `altitude_unit` | `"ft"` | Altitude display unit — one of `ft`, `m`, `km`, `nmi`. Advanced. |
| `speed_unit` | `"kn"` | Speed display unit — one of `kn`, `mph`, `kmh`, `ms`, `mach`. Advanced. |
| `track_format` | `"deg"` | Track/heading display format. 'deg' = numeric degrees (090deg), 'cardinal' = compass point (E) — one of `deg`, `cardinal`. Advanced. |
| `vr_unit` | `"fpm"` | Vertical rate display unit — one of `fpm`, `fts`, `ms`, `mph`, `kmh`. Advanced. |

### Colours

| Key | Default | Notes |
|---|---|---|
| `header_color` | `[255, 200, 0]` | RGB color for headers/callsigns in area and flight tracking modes. Advanced. |
| `metric_color` | `[255, 255, 255]` | RGB color for metric values (alt, speed, etc.) in area and flight tracking modes. Advanced. |
| `error_color` | `[255, 0, 0]` | RGB color for error/no-data messages. Advanced. |
| `airport_color` | `[0, 120, 255]` | RGB color for airport full names in widescreen layout. Advanced. |

### Offline aircraft database

| Key | Default | Notes |
|---|---|---|
| `use_offline_database` | `true` | Use offline aircraft database for aircraft type lookups. |
| `offline_database_auto_update` | `true` | Automatically update offline database. |
| `offline_database_update_interval_days` | `30` | Interval in days between offline database updates (1–365). |

### Map background

| Key | Default | Notes |
|---|---|---|
| `map_background.enabled` | `true` | Enable map background tiles. |
| `map_background.tile_provider` | `"carto_dark"` | Map tile provider — one of `osm`, `carto`, `carto_dark`, `stamen`, `esri`. |
| `map_background.tile_size` | `256` | Tile size in pixels. Advanced. |
| `map_background.cache_ttl_hours` | `8760` | Tile cache time-to-live in hours (1–8760). Advanced. |
| `map_background.fade_intensity` | `0.4` | Fade intensity for map background (0.0-1.0). Advanced. |
| `map_background.brightness` | `1.0` | Brightness adjustment for map (0.0-2.0). Advanced. |
| `map_background.contrast` | `1.0` | Contrast adjustment for map (0.0-2.0). Advanced. |
| `map_background.saturation` | `1.0` | Saturation adjustment for map (0.0-2.0). Advanced. |
| `map_background.disable_on_cache_error` | `false` | Disable map background if cache errors occur. Advanced. |
| `map_background.custom_tile_server` | `"https://maps.chuck-builds.com"` | Custom tile server URL (optional, for self-hosted OSM servers). When set, this overrides the tile_provider setting. Leave empty to use the tile_provider setting instead. Advanced. |

### Airport weather

| Key | Default | Notes |
|---|---|---|
| `metar.enabled` | `false` | Fetch and display METAR/TAF/PIREP/SIGMET for the airports below. |
| `metar.airports` | *(empty)* | ICAO (e.g. KTPA) or IATA (e.g. TPA) airport codes. The display rotates through each airport's weather. Example: ["KTPA", "KJFK"]. |
| `metar.show_taf` | `true` | Show the terminal aerodrome forecast (raw) on a page after each airport's METAR. |
| `metar.show_raw` | `true` | Show the raw METAR string on its own page in addition to the decoded card. |
| `metar.show_pirep` | `false` | Show recent pilot reports near each airport. Advanced. |
| `metar.show_sigmet` | `false` | Show active domestic SIGMET/AIRMET advisories (region-based, not airport-specific). Advanced. |
| `metar.pirep_distance_nm` | `200` | How far from each airport to search for pilot reports (25–500). Advanced. |
| `metar.update_interval_minutes` | `10` | How often to refresh weather from NOAA. METARs update roughly hourly, so 10 minutes is plenty (5–120). Advanced. |
| `metar.page_duration_seconds` | `8` | How long each weather page (decoded METAR, raw, TAF, etc.) is shown before advancing (3–60). Advanced. |
| `metar.altimeter_unit` | `"inhg"` | Altimeter setting display: 'inhg' shows US style (A30.01), 'hpa' shows international style (Q1016) — one of `inhg`, `hpa`. Advanced. |
| `metar.temp_unit` | `"c"` | Temperature/dewpoint unit on the decoded card — one of `c`, `f`. Advanced. |
| `metar.wind_unit` | `"kt"` | Wind speed unit. Aviation standard is knots (kt) — one of `kt`, `mph`, `kmh`, `ms`. Advanced. |
| `metar.visibility_unit` | `"sm"` | Visibility unit: statute miles (US), metres or kilometres (international) — one of `sm`, `m`, `km`. Advanced. |

### Proximity alert

| Key | Default | Notes |
|---|---|---|
| `proximity_alert.enabled` | `true` | Enable proximity alerts. |
| `proximity_alert.distance_miles` | `0.1` | Distance threshold in miles for proximity alert (0.01–10.0). |
| `proximity_alert.duration_seconds` | `30` | Hard cap (seconds) on how long a single overhead flight holds the screen, measured from when it is locked on. The flight shows for this long even if it leaves the radius sooner, and is released after this even if it lingers (5–300). Advanced. |
| `proximity_alert.cooldown_seconds` | `30` | After a flight's window ends, suppress the overhead preempt for this many seconds so the normal rotation (weather/clock/sports) gets guaranteed screen time, even if planes remain overhead. Set to 0 to disable the cooldown (0–600). Advanced. |

### Fonts

| Key | Default | Notes |
|---|---|---|
| `fonts.large_size` | `0` | Override size for the large font tier. 0 = auto (0–32). Advanced. |
| `fonts.medium_size` | `0` | Override size for the medium font tier. 0 = auto (0–32). Advanced. |
| `fonts.small_size` | `0` | Override size for the small font tier. 0 = auto (0–32). Advanced. |

### FlightAware / OpenSky

| Key | Default | Notes |
|---|---|---|
| `flightaware.api_key` | *(blank)* | Your FlightAware AeroAPI key. Leave blank if you are not using FlightAware — the plugin works fully without this. Secret, masked in the web UI. |
| `flightaware.enabled` | `false` | Enable paid FlightAware API calls. Must be true AND api_key must be set for FlightAware to be used. Disabled by default — do not enable unless you have a paid subscription. |
| `flightaware.max_api_calls_per_hour` | `25` | Maximum FlightAware API calls per hour (1–100). Advanced. |
| `flightaware.daily_api_budget` | `60` | Maximum FlightAware API calls per day (1–200). Advanced. |
| `flightaware.cache_ttl_hours` | `12` | Flight plan cache time-to-live in hours (1–168). Advanced. |
| `flightaware.min_callsign_length` | `4` | Minimum callsign length to fetch flight plan data (3–10). Advanced. |
| `flightaware.airline_callsign_prefixes` | `["AAL", "UAL", "DAL", "SWA", "JBU", "ASQ", …` | List of airline callsign prefixes to prioritize for flight plan fetching. Advanced. |
| `flightaware.background_service` | — | Background service configuration for fetching flight plan data without blocking the display. |

### Background service

| Key | Default | Notes |
|---|---|---|
| `background_service.enabled` | `true` | . |
| `background_service.fetch_interval_hours` | `4` | . Advanced. |
| `background_service.max_calls_per_run` | `10` | . Advanced. |

The FlightAware block has its own background-service settings, separate from
the top-level `background_service`:

| Key | Default | Notes |
|---|---|---|
| `flightaware.background_service.enabled` | `true` | Enable the background service for flight plan fetching. |
| `flightaware.background_service.fetch_interval_hours` | `4` | Interval in hours between background fetch runs (1–168). Advanced. |
| `flightaware.background_service.max_calls_per_run` | `10` | Maximum number of flight plan calls fetched per background run (1–100). Advanced. |

### Legacy flat API keys

The plugin accepts the FlightAware and OpenSky credentials either nested under
`flightaware` (above) or as flat top-level keys. `_normalize_flightaware_config()`
copies the nested form onto the flat names once at start-up, so both work and
you only need to set one.


| Key | Default | Notes |
|---|---|---|
| `opensky_username` | *(blank)* | OpenSky Network username. Only needed if you have manually set enrichment_provider to 'opensky' via direct config edit. Leave blank for the standard free setup. Secret, masked in the web UI. Advanced. |
| `opensky_password` | *(blank)* | OpenSky Network password. Only needed alongside opensky_username above. Secret, masked in the web UI. Advanced. |
| `flightaware_api_key` | *(blank)* | Deprecated — use the FlightAware section above instead. Kept only for backward compatibility with older configs. Secret, masked in the web UI. Advanced. |
| `flight_plan_enabled` | `false` | Deprecated: moved to FlightAware section. Advanced. |
| `max_api_calls_per_hour` | `25` | Deprecated: moved to FlightAware section. Advanced. |
| `daily_api_budget` | `60` | Deprecated: moved to FlightAware section. Advanced. |
| `flight_plan_cache_ttl_hours` | `12` | Deprecated: moved to FlightAware section. Advanced. |
| `min_callsign_length` | `4` | Deprecated: moved to FlightAware section. Advanced. |
| `airline_callsign_prefixes` | *(empty)* | Deprecated: moved to FlightAware section. Advanced. |


## Display Modes

![The four display modes](../../docs/assets/ledmatrix-flights/display-modes.png)

`map` is shown here with `map_background.enabled` off. With it on, the aircraft
are plotted over basemap tiles fetched from a tile server — that is why this
one screen cannot be reproduced offline the way the others are.

Units and heading format apply across the modes:

![imperial and metric](../../docs/assets/ledmatrix-flights/units.png)

![degrees and cardinal headings](../../docs/assets/ledmatrix-flights/track-format.png)

![The same aircraft on four panel sizes](../../docs/assets/ledmatrix-flights/panel-sizes.png)


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

Released under the GNU General Public License v3.0 — see [LICENSE](LICENSE).

## Author

ChuckBuilds

## Support

For issues and feature requests, please open an issue on the GitHub repository.

