# Tide Display

Coastal tide information with four auto-rotating display modes.

**Data source:** [NOAA Tides & Currents](https://tidesandcurrents.noaa.gov/) — free, no API key required (US stations).

---

## Display Modes

| Mode | Shows |
|------|-------|
| **Current** | Animated wave-level bar, tide direction (rising/falling), current height, next two tide events |
| **Schedule** | Today's full tide schedule in columns (up to 4 high/low tides) with mini height bars |
| **Chart** | 24-hour filled tide curve with current-time marker and H/L labels |
| **Stats** | Moon phase icon + name, spring/neap indicator, tidal range, cycle progress bar |

---

## Setup

1. Find your nearest NOAA tide station at **[tidesandcurrents.noaa.gov/stations.html](https://tidesandcurrents.noaa.gov/stations.html)**
2. Note the 7-digit station ID (e.g., `9447130` for Seattle, `8724580` for Key West)
3. Enter it in the **Station ID** field in the plugin configuration

---

## Configuration

| Option | Default | Description |
|--------|---------|-------------|
| `station_id` | — | **Required.** 7-digit NOAA station ID |
| `station_name` | `""` | Optional display name override |
| `units` | `imperial` | `imperial` (feet) or `metric` (meters) |
| `display_duration` | `12` | Seconds to show each mode before rotating |
| `show_moon_phase` | `true` | Show moon phase icon on the stats screen |
| `tide_color` | `[0,100,200]` | RGB color for tide water fill |
| `highlight_color` | `[0,220,255]` | RGB color for wave crests and chart line |

---

## Popular Station IDs

| Location | Station ID |
|----------|-----------|
| Seattle, WA | 9447130 |
| San Francisco, CA | 9414290 |
| Los Angeles, CA | 9410660 |
| Key West, FL | 8724580 |
| Miami, FL | 8723170 |
| Boston, MA | 8443970 |
| New York, NY | 8518750 |
| Bar Harbor, ME | 8413320 |
| Galveston, TX | 8771341 |
| Honolulu, HI | 1612340 |

---

## Notes

- Tide predictions are cached for 24 hours — minimal API usage
- Live water level (where available) is cached for 6 minutes
- If the station does not provide live observations, the plugin interpolates from hourly predictions
- Not all NOAA stations provide real-time water level data; predictions are always available
