# Weather Display Plugin

Comprehensive weather display plugin for LEDMatrix showing current conditions, hourly forecast, and daily forecast.

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

Get a free API key from [OpenWeatherMap](https://openweathermap.org/api):
1. Sign up for a free account
2. Navigate to API Keys section
3. Generate a new API key
4. Add it to your plugin configuration

### Example Configuration

```json
{
  "enabled": true,
  "api_key": "your_openweathermap_api_key_here",
  "location": {
    "city": "Dallas",
    "state": "Texas",
    "country": "US"
  },
  "units": "imperial",
  "update_interval": 1800,
  "display_modes": {
    "weather": true,
    "hourly_forecast": true,
    "daily_forecast": true
  },
  "display_duration": 30
}
```

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

**No weather data displayed:**
- Check that your API key is valid
- Verify internet connection
- Check logs for API errors
- Ensure location is spelled correctly

**Slow updates:**
- API has rate limits, respect the minimum update interval
- Free tier allows 1000 calls/day

## API Rate Limits

OpenWeatherMap free tier provides:
- 1,000 API calls per day
- 60 calls per minute

With default settings (1800s = 30 min intervals), this plugin uses ~48 calls per day.

## License

MIT License - see main LEDMatrix repository for details.

