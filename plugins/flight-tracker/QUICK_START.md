# Flight Tracker Plugin - Quick Start Guide

Get your flight tracker running in 5 minutes!

## Prerequisites

✅ Raspberry Pi with LEDMatrix installed  
✅ ADS-B receiver (dump1090/readsb/SkyAware) running  
✅ LED Matrix display connected  

## Step 1: Install the Plugin

### Option A: Via Web Interface (Easiest)
1. Open `http://your-pi-ip:5050` in your browser
2. Click on **Plugin Store**
3. Search for "Flight Tracker"
4. Click **Install**
5. Wait for installation to complete

### Option B: Via Command Line
```bash
ssh pi@your-pi-ip
curl -X POST http://localhost:5050/api/plugins/install \
  -H "Content-Type: application/json" \
  -d '{"plugin_id": "flight-tracker"}'
```

## Step 2: Find Your Coordinates

You need your latitude and longitude. Use one of these methods:

### Method 1: Google Maps
1. Open [Google Maps](https://maps.google.com)
2. Right-click on your location
3. Click the coordinates at the top
4. First number = latitude, second = longitude
5. Example: `27.9506, -82.4572`

### Method 2: GPS App
Use any GPS app on your phone to get your coordinates.

## Step 3: Configure the Plugin

### Minimum Configuration

Edit your LEDMatrix config (via web interface or `/path/to/config.json`):

```json
{
  "plugins": {
    "flight-tracker": {
      "enabled": true,
      "skyaware_url": "http://192.168.1.100/skyaware/data/aircraft.json",
      "center_latitude": 27.9506,
      "center_longitude": -82.4572,
      "map_radius_miles": 10
    }
  }
}
```

**Change these values:**
- `skyaware_url`: Your SkyAware IP address
- `center_latitude`: Your latitude
- `center_longitude`: Your longitude

### Find Your SkyAware URL

Your ADS-B receiver should be accessible at one of these:
- `http://192.168.1.X/skyaware/data/aircraft.json`
- `http://192.168.86.X/skyaware/data/aircraft.json`
- `http://piaware.local/skyaware/data/aircraft.json`

Test it in your browser - you should see JSON data with aircraft.

## Step 4: Add to Display Rotation

Add the flight tracker modes to your display rotation:

```json
{
  "display_modes": [
    "clock",
    "flight-tracker-map",
    "weather",
    "flight-tracker-stats"
  ],
  "mode_duration": 30
}
```

**Available modes:**
- `flight-tracker-map` - Shows all aircraft on a map
- `flight-tracker-overhead` - Details of closest aircraft  
- `flight-tracker-stats` - Rotating statistics (closest/fastest/highest)

## Step 5: Restart LEDMatrix

```bash
sudo systemctl restart ledmatrix
```

Or via web interface: **Settings** → **Restart Display**

## Step 6: Verify It's Working

### Check the Display
- You should see aircraft within your radius
- Numbers represent aircraft count
- Colors indicate altitude (red=low, blue=high, purple=very high)

### Check the Logs
```bash
sudo journalctl -u ledmatrix -f | grep Flight
```

You should see:
```
[Flight Tracker] Initialized - Center: (27.9506, -82.4572), Radius: 10mi
[Flight Tracker] Currently tracking 5 aircraft
```

### No Aircraft Showing?

1. **Test SkyAware directly:**
   ```bash
   curl http://your-skyaware-ip/skyaware/data/aircraft.json
   ```
   Should show aircraft JSON data

2. **Increase radius:**
   ```json
   "map_radius_miles": 50
   ```

3. **Check coordinates are correct** - use Google Maps to verify

4. **Wait for aircraft** - may take a few minutes for aircraft to appear in your area

## Optional: Enable Flight Plan Data

Want to see where aircraft are flying to/from?

### Get a FlightAware API Key
1. Sign up at https://aeroapi.flightaware.com/
2. Free tier: 1,000 queries/month
3. Copy your API key

### Add to Configuration
```json
{
  "plugins": {
    "flight-tracker": {
      "flight_plan_enabled": true,
      "flightaware_api_key": "your-api-key-here",
      "max_api_calls_per_hour": 20,
      "daily_api_budget": 60
    }
  }
}
```

### Cost Control
The plugin automatically:
- Only fetches data for commercial flights
- Caches results for 12 hours
- Limits to 20 calls/hour and 60/day
- Uses offline database when possible
- **Typical cost: $5-10/month**

## Troubleshooting

### "No Aircraft" Displayed
- ✅ Check SkyAware is accessible
- ✅ Verify coordinates are correct
- ✅ Increase radius to 25-50 miles
- ✅ Wait a few minutes - aircraft need to be in range

### Map Background Not Showing
- ✅ Check internet connection
- ✅ Try different tile provider in config
- ✅ Temporarily disable: `"map_background": {"enabled": false}`

### Performance Issues
- ✅ Reduce radius to 5 miles
- ✅ Disable trails: `"show_trails": false`
- ✅ Increase update interval: `"update_interval": 10`

### API Rate Limit Errors
- ✅ Reduce hourly limit: `"max_api_calls_per_hour": 10`
- ✅ Increase cache time: `"flight_plan_cache_ttl_hours": 24`
- ✅ Check usage at https://aeroapi.flightaware.com/portal/

## Next Steps

### Customize Your Display
- Adjust `zoom_factor` for closer/wider view
- Enable `show_trails` for aircraft paths
- Try different `tile_provider` values for map styles
- Adjust `map_radius_miles` for your area

### Learn More
- 📖 [Full README](README.md) - Complete documentation
- 🔧 [Example Config](example_config.json) - All configuration options
- 📝 [Changelog](CHANGELOG.md) - Version history and updates
- 💬 [Support Forum](https://github.com/ChuckBuilds/LEDMatrix/discussions)

## Example Complete Configuration

```json
{
  "plugins": {
    "flight-tracker": {
      "enabled": true,
      "skyaware_url": "http://192.168.1.100/skyaware/data/aircraft.json",
      "center_latitude": 27.9506,
      "center_longitude": -82.4572,
      "map_radius_miles": 10,
      "zoom_factor": 1.0,
      "update_interval": 5,
      "show_trails": false,
      "map_background": {
        "enabled": true,
        "tile_provider": "osm",
        "fade_intensity": 0.3
      },
      "proximity_alert": {
        "enabled": true,
        "distance_miles": 0.1,
        "duration_seconds": 30
      },
      "display_duration": 30
    }
  },
  "display_modes": [
    "clock",
    "flight-tracker-map",
    "weather",
    "flight-tracker-overhead",
    "flight-tracker-stats"
  ],
  "mode_duration": 30
}
```

---

## Need Help?

- 🐛 [Report Issues](https://github.com/ChuckBuilds/ledmatrix-flight-tracker/issues)
- 💡 [Feature Requests](https://github.com/ChuckBuilds/ledmatrix-flight-tracker/issues/new)
- 💬 [Community Discussion](https://github.com/ChuckBuilds/LEDMatrix/discussions)
- 📖 [LEDMatrix Wiki](https://github.com/ChuckBuilds/LEDMatrix/wiki)

**Happy Flight Tracking! ✈️**

