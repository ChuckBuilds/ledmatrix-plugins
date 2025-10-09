# Simple Clock Plugin

A simple, customizable clock display plugin for LEDMatrix that shows the current time and date.

## Features

- **Time Display**: Shows current time in 12-hour or 24-hour format
- **Date Display**: Optional date display with multiple format options
- **Timezone Support**: Configurable timezone for accurate time display
- **Color Customization**: Customizable colors for time, date, and AM/PM indicator
- **Position Control**: Configurable display position

## Installation

### From Plugin Store (Recommended)

1. Open the LEDMatrix web interface
2. Navigate to the Plugin Store tab
3. Search for "Simple Clock" or browse the "time" category
4. Click "Install"

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
    "time_color": [255, 255, 255],
    "date_color": [255, 128, 64],
    "ampm_color": [255, 255, 128],
    "display_duration": 15,
    "position": {
      "x": 0,
      "y": 0
    }
  }
}
```

### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enabled` | boolean | `true` | Enable or disable the plugin |
| `timezone` | string | `"UTC"` | Timezone for display (e.g., `"America/New_York"`) |
| `time_format` | string | `"12h"` | Time format: `"12h"` or `"24h"` |
| `show_seconds` | boolean | `false` | Show seconds in time display |
| `show_date` | boolean | `true` | Show date below the time |
| `date_format` | string | `"MM/DD/YYYY"` | Date format: `"MM/DD/YYYY"`, `"DD/MM/YYYY"`, or `"YYYY-MM-DD"` |
| `time_color` | array | `[255, 255, 255]` | RGB color for time display |
| `date_color` | array | `[255, 128, 64]` | RGB color for date display |
| `ampm_color` | array | `[255, 255, 128]` | RGB color for AM/PM indicator |
| `display_duration` | number | `15` | Display duration in seconds |
| `position.x` | integer | `0` | X position for display |
| `position.y` | integer | `0` | Y position for display |

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
- Verify the `timezone` setting in your configuration
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

Test the plugin by running:

```bash
cd /path/to/LEDMatrix
python3 -c "
from src.plugin_system.plugin_manager import PluginManager
pm = PluginManager()
pm.discover_plugins()
pm.load_plugin('clock-simple')
plugin = pm.get_plugin('clock-simple')
plugin.update()
plugin.display()
"
```

## License

MIT License - feel free to modify and distribute.

## Contributing

Found a bug or want to add features? Please create an issue or submit a pull request on the [LEDMatrix GitHub repository](https://github.com/ChuckBuilds/LEDMatrix).
