# Hello World Plugin - Quick Start Guide

## 🚀 Enable the Plugin

Add this to your `config/config.json`:

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

## ✅ Test Results

All plugin system tests passed:
- ✅ Plugin Discovery
- ✅ Plugin Loading  
- ✅ Manifest Validation
- ✅ BasePlugin Interface
- ✅ Store Manager

## 📋 Verify Plugin is Working

### 1. Check Plugin Discovery (Windows)
```bash
python test/test_plugin_system.py
```

### 2. Check on Raspberry Pi
```bash
# SSH into your Pi
ssh pi@your-pi-ip

# Check if plugin is discovered
sudo journalctl -u ledmatrix -n 50 | grep "hello-world"

# Should see:
# Discovered plugin: hello-world v1.0.0
# Loaded plugin: hello-world
```

### 3. Via Web API
```bash
# List installed plugins
curl http://localhost:5001/api/plugins/installed

# Enable the plugin
curl -X POST http://localhost:5001/api/plugins/toggle \
  -H "Content-Type: application/json" \
  -d '{"plugin_id": "hello-world", "enabled": true}'
```

## 🎨 Customization Examples

### Lightning Theme
```json
{
  "hello-world": {
    "enabled": true,
    "message": "Go Bolts!",
    "color": [0, 128, 255],
    "time_color": [255, 255, 255],
    "display_duration": 15
  }
}
```

### RGB Rainbow
```json
{
  "hello-world": {
    "enabled": true,
    "message": "RGB Test",
    "color": [255, 0, 255],
    "show_time": false,
    "display_duration": 5
  }
}
```

## 🔧 Troubleshooting

### Plugin Not Showing
1. Check `enabled: true` in config
2. Restart the display service
3. Check logs for errors

### Configuration Errors
- Ensure all colors are [R, G, B] arrays
- Values must be 0-255
- `display_duration` must be a positive number

## 📂 Plugin Files

```
plugins/hello-world/
├── manifest.json          # Plugin metadata
├── manager.py             # Plugin code
├── config_schema.json     # Configuration schema
├── example_config.json    # Example configuration
├── README.md              # Full documentation
└── QUICK_START.md         # This file
```

## 🎯 What This Demonstrates

- ✅ Plugin discovery and loading
- ✅ Configuration validation
- ✅ Display rendering
- ✅ Error handling
- ✅ BasePlugin interface
- ✅ Integration with display rotation

## 📚 Next Steps

- Modify the message to personalize it
- Change colors to match your team
- Adjust display_duration for timing
- Use this as a template for your own plugins!

---

**Need Help?** Check the main [README.md](README.md) or [Plugin System Documentation](../../docs/PLUGIN_PHASE_1_SUMMARY.md)

