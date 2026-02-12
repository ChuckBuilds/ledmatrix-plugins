# 7-Segment Clock Plugin

A retro-style 7-segment clock plugin for LEDMatrix that displays time using digit images with configurable formats and sunrise/sunset-based color transitions.

## Features

- **Retro 7-Segment Display**: Uses classic digit images (13x32px) with customizable colors
- **Time Format Options**: Support for 12-hour and 24-hour time formats
- **Leading Zero Control**: Optional leading zero for hours (e.g., "09:30" vs "9:30")
- **Flashing Separator**: Optional blinking colon separator between hours and minutes
- **Sunrise/Sunset Color Transitions**: Automatically transitions between daytime and nighttime colors based on sun elevation
- **Location-Based**: Configure latitude/longitude for accurate sunrise/sunset calculations
- **Timezone Support**: Display time in any timezone

## Installation

### From Plugin Store (Recommended)

1. Open the LEDMatrix web interface (`http://your-pi-ip:5000`)
2. Go to **Plugin Store**
3. Find **7-Segment Clock** and click **Install**

### Manual Installation

1. Copy the plugin from the monorepo:
   ```bash
   cp -r ledmatrix-plugins/plugins/7-segment-clock /path/to/LEDMatrix/plugin-repos/
   ```

2. Install dependencies:
   ```bash
   pip install -r plugin-repos/7-segment-clock/requirements.txt
   ```

3. Enable the plugin in `config/config.json`:
   ```json
   {
     "7-segment-clock": {
       "enabled": true,
       "display_duration": 15
     }
   }
   ```

4. Restart LEDMatrix to load the plugin.

## Configuration

The plugin can be configured via the web interface or directly in `config/config.json`:

### Basic Configuration

```json
{
  "7-segment-clock": {
    "enabled": true,
    "display_duration": 15,
    "is_24_hour_format": true,
    "has_leading_zero": false,
    "has_flashing_separator": true
  }
}
```

### Full Configuration with Location and Colors

```json
{
  "7-segment-clock": {
    "enabled": true,
    "display_duration": 15,
    "location": {
      "lat": 37.541290,
      "lng": -77.434769,
      "timezone": "US/Eastern",
      "locality": "Richmond, VA"
    },
    "is_24_hour_format": true,
    "has_leading_zero": false,
    "has_flashing_separator": true,
    "color_daytime": "#FFFFFF",
    "color_nighttime": "#220000",
    "min_fade_elevation": "-1"
  }
}
```

### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enabled` | boolean | `true` | Enable or disable the plugin |
| `display_duration` | number | `15` | How long to display the clock (seconds) |
| `location.lat` | number | `37.541290` | Latitude for sunrise/sunset calculations |
| `location.lng` | number | `-77.434769` | Longitude for sunrise/sunset calculations |
| `location.timezone` | string | `"US/Eastern"` | Timezone string (e.g., "US/Eastern", "UTC") |
| `location.locality` | string | `"Richmond, VA"` | Human-readable location name |
| `is_24_hour_format` | boolean | `true` | Use 24-hour format (false for 12-hour) |
| `has_leading_zero` | boolean | `false` | Show leading zero for hours |
| `has_flashing_separator` | boolean | `true` | Enable blinking separator (colon) |
| `color_daytime` | string | `"#FFFFFF"` | Hex color for daytime (white) |
| `color_nighttime` | string | `"#FFFFFF"` | Hex color for nighttime (white) |
| `min_fade_elevation` | string | `"-1"` | Sun elevation threshold for color mixing |

### Color Transition Options

The `min_fade_elevation` option controls when color transitions occur based on sun elevation:

- **`"-1"`** (None): No fading, switches directly between day/night colors
- **`"-6"`** (Civil twilight): Fades during civil twilight (sun 6° below horizon)
- **`"-12"`** (Nautical twilight): Fades during nautical twilight (sun 12° below horizon)
- **`"-18"`** (Astronomical twilight): Fades during astronomical twilight (sun 18° below horizon)

## Usage

Once installed and enabled, the plugin will automatically display the current time during the normal plugin rotation. The display updates every 60 seconds (configurable via `update_interval` in manifest).

### Time Formats

- **24-hour format** (`is_24_hour_format: true`): Displays time as "HH:MM" (e.g., "14:30")
- **12-hour format** (`is_24_hour_format: false`): Displays time as "H:MM" or "HH:MM" (e.g., "2:30" or "02:30")

### Separator Flashing

When `has_flashing_separator` is enabled, the colon separator blinks every second (visible on even seconds, hidden on odd seconds), similar to traditional digital clocks.

## Technical Details

### Image Assets

The plugin uses digit images (13x32 pixels) and a separator image (4x14 pixels) stored in `assets/images/`:
- `number_0.png` through `number_9.png`: Digit images
- `separator.png`: Colon separator image

Images have transparent foreground on black background, allowing colors to be applied dynamically.

### Sunrise/Sunset Calculations

The plugin uses the `astral` library to calculate sun elevation based on:
- Location (latitude/longitude)
- Current date and time
- Timezone

Color mixing is calculated based on the sun's elevation relative to the configured fade thresholds.

### Display Dimensions

The plugin automatically adapts to any display size configured in LEDMatrix. Display dimensions are read from `display_manager.width` and `display_manager.height`.

Centering calculations ensure the clock is properly positioned regardless of display width (supports 64x32, 128x32, chained panels, etc.).

## Dependencies

- `astral>=3.2`: Sunrise/sunset and sun elevation calculations
- `pytz>=2023.3`: Timezone support
- `PIL` (Pillow): Image processing (provided by LEDMatrix core)

## Troubleshooting

### Clock Not Displaying

1. Check that the plugin is enabled in `config/config.json`
2. Verify images are present in `assets/images/` directory
3. Check plugin logs for errors: `journalctl -u ledmatrix -f` (if running as service)

### Wrong Time Displayed

1. Verify timezone is correct in configuration
2. Check system time is correct
3. Ensure location coordinates are accurate if using sunrise/sunset features

### Colors Not Transitioning

1. Verify location coordinates (lat/lng) are correct
2. Check that `min_fade_elevation` is set appropriately
3. Verify `color_daytime` and `color_nighttime` are different colors

### Images Not Loading

1. Verify all image files exist in `assets/images/` directory
2. Check file permissions on image files
3. Verify image files are valid PNG files

## Development

### File Structure

```
7-segment-clock/
├── manifest.json          # Plugin metadata
├── manager.py             # Main plugin class
├── config_schema.json     # Configuration schema
├── requirements.txt       # Python dependencies
├── README.md             # This file
└── assets/
    └── images/
        ├── number_0.png  # Digit images (0-9)
        ├── ...
        ├── number_9.png
        └── separator.png # Colon separator
```

### Testing

Test the plugin in emulator mode:
```bash
python run.py --emulator
```

## License

[Add your license here]

## Credits

- Original Big Clock applet: [TronbyT Apps](https://github.com/tronbyt/apps)
- Digit images sourced from TronbyT repository
- Adapted for LEDMatrix plugin system

## Support

For issues, questions, or contributions, please open an issue on the GitHub repository.

