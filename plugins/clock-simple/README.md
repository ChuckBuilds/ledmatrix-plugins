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

# Simple Clock Plugin

A simple, customizable clock display plugin for LEDMatrix that shows the current time and date.

## Features

- **Time Display**: Shows current time in 12-hour or 24-hour format
- **Date Display**: Optional date display with multiple format options
- **Timezone Support**: Configurable timezone for accurate time display
- **Color Customization**: Customizable colors for time, date, and AM/PM indicator
- **Position Control**: Configurable display position

## Installation

### From the Plugin Store (recommended)

1. Open the LEDMatrix web interface (`http://your-pi-ip:5000`)
2. Open the **Plugin Manager** tab
3. Find **Simple Clock** in the **Plugin Store** section (it's in the
   `time` category) and click **Install**
4. Toggle the plugin on, then click **Restart Display Service** on the
   **Overview** tab

### Manual Installation

1. Copy this plugin directory to your `plugins/` folder
2. Restart LEDMatrix
3. Enable the plugin in the web interface

## Configuration

Add the following to your `config/config.json`:

```json
{
  "clock-simple": {
    "enabled": true,
    "timezone": "America/New_York",
    "time_format": "12h",
    "show_seconds": false,
    "show_date": true,
    "date_format": "MM/DD/YYYY",
    "display_duration": 15,
    "position_x": 0,
    "position_y": 0,
    "customization": {
      "time_text": {
        "font": "PressStart2P-Regular.ttf",
        "font_size": 8,
        "text_color": [255, 255, 255]
      },
      "date_text": {
        "font": "PressStart2P-Regular.ttf",
        "font_size": 8,
        "text_color": [255, 128, 64]
      },
      "ampm_text": {
        "font": "PressStart2P-Regular.ttf",
        "font_size": 8,
        "text_color": [255, 255, 128]
      }
    }
  }
}
```

### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enabled` | boolean | `false` | Enable or disable the plugin |
| `display_duration` | number | `15` | Seconds to hold the screen each rotation (1–300) |
| `update_interval` | integer | `1` | How often to redraw the clock, in seconds (1–60) |
| `timezone` | string \| null | `null` | IANA timezone name (e.g. `"America/New_York"`). When null, inherits the global LEDMatrix timezone |
| `time_format` | string | `"12h"` | `"12h"` or `"24h"` |
| `center_time_with_ampm` | boolean | `false` | Center the time + AM/PM as one block (12h only) |
| `show_seconds` | boolean | `false` | Include seconds in the time |
| `show_date` | boolean | `true` | Show date below the time |
| `date_format` | string | `"OLD_CLOCK"` | One of `"MM/DD/YYYY"`, `"DD/MM/YYYY"`, `"YYYY-MM-DD"`, `"OLD_CLOCK"` (e.g. `Monday, January 1st`) |
| `position_x` | integer | `0` | X offset in pixels |
| `position_y` | integer | `0` | Y offset in pixels |
| `customization` | object | See below | Per-element font and color overrides |

### Customization Options

The `customization` object allows you to customize fonts and colors for each display element:

- **`time_text`**: Font and color settings for the time display
  - `font`: Font family (e.g., `"PressStart2P-Regular.ttf"`)
  - `font_size`: Font size in pixels (4-16)
  - `text_color`: RGB color array `[R, G, B]` (default: `[255, 255, 255]`)

- **`date_text`**: Font and color settings for the date display
  - `font`: Font family
  - `font_size`: Font size in pixels (4-16)
  - `text_color`: RGB color array (default: `[255, 128, 64]`)

- **`ampm_text`**: Font and color settings for AM/PM indicator (12-hour format only)
  - `font`: Font family
  - `font_size`: Font size in pixels (4-16)
  - `text_color`: RGB color array (default: `[255, 255, 128]`)

### Timezone Examples

- `"America/New_York"` - Eastern Time
- `"America/Chicago"` - Central Time
- `"America/Denver"` - Mountain Time
- `"America/Los_Angeles"` - Pacific Time
- `"Europe/London"` - GMT/BST
- `"Asia/Tokyo"` - Japan Standard Time
- `"Australia/Sydney"` - Australian Eastern Time

## Usage

Once installed and configured:

1. The plugin will automatically update every second (based on `update_interval` in manifest)
2. The display will show during rotation according to your configured `display_duration`
3. The time updates in real-time based on your configured timezone

## Troubleshooting

### Common Issues

**Time shows wrong timezone:**
- Verify the `timezone` setting in your configuration (if specified)
- If not specified, check the global `timezone` setting in your main LEDMatrix config
- Check that the timezone string is valid (see timezone examples above)

**Colors not displaying correctly:**
- Ensure RGB values are between 0-255
- Check that your display supports the chosen colors

**Plugin not appearing in rotation:**
- Verify `enabled` is set to `true`
- Check that the plugin loaded successfully in the web interface
- Ensure `display_duration` is greater than 0

### Debug Logging

Enable debug logging to troubleshoot issues:

```json
{
  "logging": {
    "level": "DEBUG",
    "file": "/path/to/ledmatrix.log"
  }
}
```

## Development

### Plugin Structure

```
plugins/clock-simple/
├── manifest.json      # Plugin metadata and requirements
├── manager.py         # Main plugin class
├── config_schema.json # Configuration validation schema
└── README.md          # This file
```

### Testing

The fastest way to verify a change without restarting the full display
service is the LEDMatrix dev preview server, which renders this plugin in
your browser without any hardware:

```bash
cd /path/to/LEDMatrix
python3 scripts/dev_server.py --extra-dir /path/to/ledmatrix-plugins/plugins/clock-simple
# then open http://localhost:5001
```

You can also render a single still frame to a PNG with
`scripts/render_plugin.py` — see
[`docs/DEV_PREVIEW.md`](https://github.com/ChuckBuilds/LEDMatrix/blob/main/docs/DEV_PREVIEW.md)
for details.

## License

GPL-3.0 License - feel free to modify and distribute.

## Contributing

Found a bug or want to add features? Please create an issue or submit a pull request on the [LEDMatrix GitHub repository](https://github.com/ChuckBuilds/LEDMatrix).
