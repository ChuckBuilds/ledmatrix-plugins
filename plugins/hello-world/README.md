# Hello World Plugin

A simple test plugin for the LEDMatrix plugin system. Displays a customizable greeting message with optional time display.

## Purpose

This plugin serves as:
- **Test plugin** for validating the plugin system works correctly
- **Example plugin** for developers creating their own plugins
- **Simple demonstration** of the BasePlugin interface

## Features

- ✅ Customizable greeting message
- ✅ Optional time display
- ✅ Configurable text colors
- ✅ Proper error handling
- ✅ Configuration validation

## Installation

This plugin is included as a test plugin. To enable it:

1. Edit `config/config.json` and add:

```json
{
  "hello-world": {
    "enabled": true,
    "message": "Hello, World!",
    "show_time": true,
    "color": [255, 255, 255],
    "time_color": [0, 255, 255],
    "display_duration": 10
  }
}
```

2. Restart the display:

```bash
sudo systemctl restart ledmatrix
```

## Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enabled` | boolean | `true` | Enable/disable the plugin |
| `message` | string | `"Hello, World!"` | The greeting message to display |
| `show_time` | boolean | `true` | Show current time below message |
| `color` | array | `[255, 255, 255]` | RGB color for message (white) |
| `time_color` | array | `[0, 255, 255]` | RGB color for time (cyan) |
| `display_duration` | number | `10` | Display time in seconds |

## Examples

### Minimal Configuration
```json
{
  "hello-world": {
    "enabled": true
  }
}
```

### Custom Message
```json
{
  "hello-world": {
    "enabled": true,
    "message": "Go Lightning!",
    "color": [0, 128, 255],
    "display_duration": 15
  }
}
```

### Message Only (No Time)
```json
{
  "hello-world": {
    "enabled": true,
    "message": "LED Matrix",
    "show_time": false,
    "color": [255, 0, 255]
  }
}
```

## Testing the Plugin

### 1. Check Plugin Discovery

After adding the configuration, check the logs:

```bash
sudo journalctl -u ledmatrix -f | grep hello-world
```

You should see:
```
Discovered plugin: hello-world v1.0.0
Loaded plugin: hello-world
Hello World plugin initialized with message: 'Hello, World!'
```

### 2. Test via Web API

Check if the plugin is installed:
```bash
curl http://localhost:5001/api/plugins/installed | jq '.plugins[] | select(.id=="hello-world")'
```

### 3. Watch It Display

The plugin will appear in the normal display rotation based on your `display_duration` setting.

## Development Notes

This plugin demonstrates:

### BasePlugin Interface
```python
class HelloWorldPlugin(BasePlugin):
    def __init__(self, plugin_id, config, display_manager, cache_manager, plugin_manager):
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)
        # Initialize your plugin
    
    def update(self):
        # Fetch/update data
        pass
    
    def display(self, force_clear=False):
        # Render to display
        pass
```

### Configuration Validation
```python
def validate_config(self):
    # Validate configuration values
    return True
```

### Error Handling
```python
try:
    # Plugin logic
except Exception as e:
    self.logger.error(f"Error: {e}", exc_info=True)
```

## Troubleshooting

### Plugin Not Loading
- Check that `manifest.json` is valid JSON
- Verify `enabled: true` in config.json
- Check logs for error messages
- Ensure Python path is correct

### Display Issues
- Verify display_manager is initialized
- Check that colors are valid RGB arrays
- Ensure message isn't too long for display

### Configuration Errors
- Validate JSON syntax in config.json
- Check that all color arrays have 3 values (RGB)
- Ensure display_duration is a positive number

## License

MIT License - Same as LEDMatrix project

## Contributing

This is a reference plugin included with LEDMatrix. Feel free to use it as a template for your own plugins!

## Support

For plugin system questions, see:
- [Plugin Architecture Spec](../../PLUGIN_ARCHITECTURE_SPEC.md)
- [Plugin Phase 1 Summary](../../docs/PLUGIN_PHASE_1_SUMMARY.md)
- [Main README](../../README.md)

