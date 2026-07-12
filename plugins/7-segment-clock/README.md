# 7-Segment Clock Plugin

A retro-style 7-segment clock plugin for LEDMatrix that displays the time using
digit images with configurable format, spacing, and color.

## Features

- **Retro 7-Segment Display**: Classic digit images (13×32px) with a customizable color
- **Time Format Options**: 12-hour and 24-hour formats
- **Leading Zero Control**: Optional leading zero for hours (e.g. "09:30" vs "9:30")
- **Flashing Separator**: Optional blinking colon between hours and minutes
- **Adjustable Digit Spacing**: Tune the pixel gap between digits for readability
- **Timezone Support**: Display time in any timezone (or inherit the main LEDMatrix timezone)

## Installation

### From Plugin Store (Recommended)

1. Open the LEDMatrix web interface (`http://your-pi-ip:5000`)
2. Open the **Plugin Manager** tab
3. Find **7-Segment Clock** in the **Plugin Store** section and click **Install**

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

The plugin can be configured via the web interface (the form is generated from
`config_schema.json`, which is the source of truth) or directly in
`config/config.json`.

### Example

```json
{
  "7-segment-clock": {
    "enabled": true,
    "display_duration": 15,
    "location": {
      "timezone": "US/Eastern"
    },
    "is_24_hour_format": true,
    "has_leading_zero": false,
    "has_flashing_separator": true,
    "digit_spacing": 2,
    "color": "#FFFFFF"
  }
}
```

### Configuration Options

| Option | Type | Default | Notes |
|--------|------|---------|-------|
| `enabled` | boolean | `true` | Enable or disable the plugin |
| `display_duration` | number | `15` | How long to show the clock, in seconds (5–300) |
| `location.timezone` | string | *(inherits)* | Timezone string (e.g. `US/Eastern`, `UTC`). If unset, inherits the main LEDMatrix timezone |
| `is_24_hour_format` | boolean | `true` | Use 24-hour format (`false` for 12-hour) |
| `has_leading_zero` | boolean | `false` | Show a leading zero for hours (e.g. `09:30` instead of `9:30`) |
| `has_flashing_separator` | boolean | `true` | Blink the colon separator once per second |
| `digit_spacing` | number | `2` | Pixels between digits, for readability (0–10) |
| `color` | string | `"#FFFFFF"` | Hex color for the digits (e.g. `#FFFFFF` white, `#FF0000` red) |

## Usage

Once installed and enabled, the plugin displays the current time during the normal
plugin rotation. The core refreshes the plugin on its own cadence (see
`update_interval` in `manifest.json`, default 60s).

### Time Formats

- **24-hour** (`is_24_hour_format: true`): "HH:MM" (e.g. "14:30")
- **12-hour** (`is_24_hour_format: false`): "H:MM" or "HH:MM" depending on `has_leading_zero` (e.g. "2:30" or "02:30")

### Separator Flashing

When `has_flashing_separator` is enabled, the colon blinks each second (visible on
even seconds, hidden on odd), like a traditional digital clock.

## Technical Details

### Image Assets

The plugin uses digit images (13×32px) and a separator image (4×14px) in
`assets/images/`:
- `number_0.png` through `number_9.png`: digit images
- `separator.png`: the colon separator

Images have a transparent foreground on a black background, so the configured
`color` is applied dynamically.

### Display Dimensions

The plugin adapts to any display size configured in LEDMatrix (dimensions are read
from `display_manager`), and centers the clock regardless of panel width (64×32,
128×32, chained panels, etc.).

## Dependencies

- `pytz>=2023.3`: Timezone support
- `PIL` (Pillow): Image processing (provided by LEDMatrix core)

## Troubleshooting

### Clock Not Displaying

1. Check that the plugin is enabled in `config/config.json`
2. Verify the images are present in the `assets/images/` directory
3. Check plugin logs for errors: `journalctl -u ledmatrix -f` (if running as a service)

### Wrong Time Displayed

1. Verify `location.timezone` is correct (or that the inherited main timezone is right)
2. Check that the system time is correct

### Images Not Loading

1. Verify all image files exist in `assets/images/`
2. Check file permissions on the image files
3. Verify the image files are valid PNGs

## Development

### File Structure

```
7-segment-clock/
├── manifest.json          # Plugin metadata
├── manager.py             # Main plugin class
├── config_schema.json     # Configuration schema
├── requirements.txt       # Python dependencies
├── README.md              # This file
├── LICENSE
└── assets/
    └── images/
        ├── number_0.png   # Digit images (0-9)
        ├── ...
        ├── number_9.png
        └── separator.png  # Colon separator
```

### Testing

Test the plugin in emulator mode:
```bash
python run.py --emulator
```

## License

Released under the GNU General Public License v3.0 — see [LICENSE](LICENSE).

## Credits

- Original Big Clock applet: [TronbyT Apps](https://github.com/tronbyt/apps)
- Digit images sourced from the TronbyT repository
- Adapted for the LEDMatrix plugin system

## Support

For issues, questions, or contributions, please open an issue on the GitHub repository.
