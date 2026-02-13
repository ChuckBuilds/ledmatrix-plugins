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

- **Current Weather**: Temperature, conditions, humidity, wind speed
- **Hourly Forecast**: Next 24-48 hours of weather data
- **Daily Forecast**: 7-day forecast with high/low temperatures
- **Weather Icons**: Beautiful icons matching current conditions
- **UV Index**: UV radiation levels for sun safety
- **Automatic Updates**: Configurable update intervals
- **Error Handling**: Robust retry logic and error recovery

## Requirements

- OpenWeatherMap API key (free tier available)
- Internet connection for API access
- Display size: minimum 64x32 pixels recommended

## Configuration

### API Key

This plugin requires a **One Call API 3.0** subscription from [OpenWeatherMap](https://openweathermap.org/api) (free tier: 1,000 calls/day):

1. Sign up for an account at https://openweathermap.org
2. Navigate to API Keys section and generate a new API key
3. **Subscribe to One Call API 3.0** — this is a separate step from getting an API key:
   - Go to https://openweathermap.org/api
   - Find "One Call API 3.0" and click Subscribe
   - The free tier requires adding payment info but will not charge you
   - A standard API key alone will **not** work; you must subscribe to One Call 3.0
4. Add the API key to your plugin configuration


### Configuration Options

- `enabled`: Enable/disable the plugin
- `api_key`: Your OpenWeatherMap API key (required)
- `location`: City, state, and country for weather data
- `units`: Temperature units (`imperial` for Fahrenheit, `metric` for Celsius)
- `update_interval`: Seconds between API updates (minimum 300, recommended 1800)
- `display_modes`: Enable/disable specific display modes
- `display_duration`: Seconds to display each mode

## Display Modes

### weather
Shows current conditions with temperature, condition text, and humidity.

### hourly_forecast
Displays next 4-24 hours of forecasted weather with temperatures.

### daily_forecast
Shows 3-7 day forecast with daily high/low temperatures.

## Usage

The plugin automatically rotates through enabled display modes based on the `display_duration` setting.

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

## API Rate Limits

OpenWeatherMap free tier provides:
- 1,000 API calls per day
- 60 calls per minute

With default settings (1800s = 30 min intervals), this plugin uses ~48 calls per day.

## License

GPL-3.0 License - see main LEDMatrix repository for details.

