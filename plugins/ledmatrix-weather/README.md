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

# Weather Display Plugin

Comprehensive weather display plugin for LEDMatrix showing current conditions, hourly forecast, and daily forecast.

Current Weather:

<img width="768" height="192" alt="led_matrix_1765383629754" src="https://github.com/user-attachments/assets/346817dc-3ff1-4491-a5ad-e70747acf6d0" />

Hourly Forecast:

<img width="768" height="192" alt="led_matrix_1765383660051" src="https://github.com/user-attachments/assets/60533757-c22c-4654-a59c-6efa682eed3f" />

Daily Forecast:

<img width="768" height="192" alt="led_matrix_1765383688610" src="https://github.com/user-attachments/assets/6ed20a08-ebf0-482e-8ce9-60391fd064f3" />



## Features

- **Current conditions**: temperature, conditions icon, humidity, wind,
  feels-like, dew point, visibility, pressure (extra metrics need height ≥48px)
- **Hourly forecast**: next 24 hours
- **Daily forecast**: 3–7 day high/low
- **Almanac**: sunrise/sunset, moon phase, day length
- **Precipitation radar**: live RainViewer imagery — no API key required for this part
- **Weather alerts**: when active, takes priority in the rotation

## Requirements

- A **One Call API 3.0** subscription from OpenWeatherMap (free tier
  available) — see API Key below
- Internet connection for OpenWeatherMap and RainViewer
- Display size: 64x32 minimum; 64x48 or larger to see the extra current-
  conditions metrics

## Configuration

### API Key

This plugin requires the **One Call API 3.0** product from OpenWeatherMap.
A standard OpenWeatherMap API key on its own will **not** work — One Call 3.0
is a separate subscription you must enable on your account.

1. Sign up at https://openweathermap.org
2. Generate an API key under **API Keys**
3. Go to https://openweathermap.org/api, find **One Call API 3.0**, click
   **Subscribe**. The free tier requires entering payment info but does not
   charge you below 1,000 calls/day.
4. Open the **Weather** tab in the LEDMatrix web UI (or edit
   `config/config_secrets.json`) and paste the key into `api_key`.

### Configuration options

The plugin's full schema lives in
[`config_schema.json`](config_schema.json) — what you see in the web UI is
generated from it. The keys you'll touch most often:

| Key | Default | Notes |
|---|---|---|
| `enabled` | `false` | Master switch |
| `api_key` | _required_ | One Call 3.0 key (store in `config_secrets.json`) |
| `location_city` | `"Dallas"` | City name |
| `location_state` | `"Texas"` | State/province (optional, helps US disambiguation) |
| `location_country` | `"US"` | ISO 3166-1 alpha-2 code |
| `units` | `"imperial"` | `"imperial"` (°F) or `"metric"` (°C) |
| `display_duration` | `30` | Seconds per mode (5–300) |
| `update_interval` | `1800` | Seconds between OpenWeatherMap fetches (min 300) |
| `display_format` | `"{temp}°F\n{condition}"` | Placeholders: `{temp}`, `{condition}`, `{humidity}`, `{wind}` |
| `show_current_weather` | `true` | Toggle current conditions mode |
| `show_hourly_forecast` | `true` | Toggle hourly mode |
| `show_daily_forecast` | `true` | Toggle daily mode |
| `show_almanac` | `true` | Toggle almanac mode (sun/moon) |
| `show_radar` | `true` | Toggle precipitation radar mode |
| `show_alerts` | `true` | Show active weather alerts (preempts rotation) |
| `show_feels_like` / `show_dew_point` / `show_visibility` / `show_pressure` | `true` | Extra current-conditions metrics (need height ≥ 48px) |
| `radar_zoom` | `6` | 4 (regional) to 8 (very close) |
| `radar_line_color` | `[0, 130, 70]` | RGB for state outlines |
| `radar_fill_color` | `[15, 25, 15]` | RGB for land fill (`[0,0,0]` = outlines only) |
| `radar_update_interval` | `600` | RainViewer refresh seconds (300–1800) |

## Display modes

The plugin registers these modes in `manifest.json` and the display
controller rotates through them in order:

| Mode | Description |
|---|---|
| `weather` | Current conditions: temperature, icon, humidity, wind, plus optional feels-like / dew point / visibility / pressure on taller displays |
| `hourly_forecast` | Next ~24 hours |
| `daily_forecast` | 3–7 day high/low forecast |
| `almanac` | Sunrise, sunset, moon phase, day length |
| `radar` | Live precipitation radar from RainViewer |

When an active weather alert is available and `show_alerts` is true, the
alert takes priority over the normal rotation.

## Usage

The plugin auto-rotates through enabled display modes based on
`display_duration`. Toggle individual modes on or off with the
`show_*` keys above (or the matching toggles in the web UI).

## Troubleshooting

**No weather data displayed / "No Data" on screen:**
- **Most common cause**: Your API key is not subscribed to One Call API 3.0
  - Check logs for "401 Unauthorized" errors
  - Subscribe at https://openweathermap.org/api -> One Call API 3.0 -> Subscribe
- Verify your API key is correct
- Verify internet connection
- Ensure location is spelled correctly (city name must match OpenWeatherMap's geocoding)

**Slow updates:**
- API has rate limits, respect the minimum update interval
- Free tier allows 1000 calls/day

## API rate limits

OpenWeatherMap One Call 3.0 free tier:
- 1,000 calls per day
- 60 calls per minute

With the default `update_interval` of 1800s (30 minutes), this plugin
makes about 48 calls per day. Lower the interval if you want fresher
data — just keep it ≥ 300s and watch your daily total.

The radar mode uses RainViewer separately and has no API key, but obeys
`radar_update_interval` (default 600s) to avoid hammering their CDN.

## License

GPL-3.0 License - see main LEDMatrix repository for details.

