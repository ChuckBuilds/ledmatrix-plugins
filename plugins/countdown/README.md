# Countdown Plugin for LEDMatrix

Display customizable countdowns with images on your LED matrix. Perfect for birthdays, holidays, vacations, events, and any special occasion you want to count down to!

## Features

- **Multiple Countdowns**: Create and manage multiple countdown entries
- **Custom Images**: Upload a unique image for each countdown
- **Individual Control**: Enable/disable each countdown independently
- **Customizable Display**: Configure fonts, colors, and sizes
- **Smart Layout**: Image on left 1/3rd, countdown text on right 2/3rds
- **Auto Rotation**: Automatically cycles through enabled countdowns
- **Flexible Dates**: Supports future dates with automatic "TODAY!" display
- **Web UI Management**: Full configuration via LEDMatrix web interface

## Installation

### From Plugin Store (Recommended)

1. Open the LEDMatrix web interface (`http://your-pi-ip:5000`)
2. Go to **Plugin Store**
3. Find **Countdown Display** and click **Install**

### Manual Installation

1. Copy the plugin from the monorepo:
   ```bash
   cp -r ledmatrix-plugins/plugins/countdown /path/to/LEDMatrix/plugin-repos/
   ```

2. Restart LEDMatrix or reload plugins via the web UI

## Configuration

### Adding a Countdown

1. Open the LEDMatrix web UI
2. Navigate to Settings > Plugins > Countdown Display
3. Click "Add Countdown"
4. Fill in the details:
   - **Name**: Display name (e.g., "Birthday", "Vacation")
   - **Target Date**: The date you're counting down to
   - **Image**: Upload a custom image (PNG, JPG, GIF, or BMP)
   - **Enabled**: Toggle to show/hide this countdown
5. Click Save

### Configuration Options

#### Per-Countdown Settings
- **Name** (required): Display name, max 30 characters
- **Target Date** (required): Date in YYYY-MM-DD format
- **Image**: Custom image upload (optional)
- **Enabled**: Toggle to enable/disable this countdown
- **Display Order**: Controls rotation order (lower numbers first)

#### Global Settings
- **Display Duration**: How long to show each countdown (seconds)
- **Font Family**: Choose from press_start, four_by_six, tom_thumb, tiny, picopixel
- **Font Size**: Size for countdown value (6-16px)
- **Font Color**: RGB color for countdown value
- **Name Font Size**: Size for countdown name (6-16px)
- **Name Font Color**: RGB color for countdown name
- **Fit to Display**: Auto-scale images to fit
- **Preserve Aspect Ratio**: Maintain image proportions when scaling
- **Background Color**: RGB color for background
- **Show Expired**: Display countdowns that have already passed

## Display Layout

The plugin uses a split layout for optimal readability:

```
┌──────────────────────────────┐
│          │                   │
│  IMAGE   │    Countdown      │
│  (1/3)   │      Name         │
│          │                   │
│          │    15 Days        │
│          │                   │
└──────────────────────────────┘
```

### Display Formats

- **Multiple Days**: "15 Days", "100 Days"
- **One Day**: "1 Day"
- **Event Day**: "TODAY!" (shown in bright yellow)

## Examples

### Birthday Countdown
```json
{
  "name": "Mom's Birthday",
  "target_date": "2026-06-15",
  "enabled": true,
  "image": [
    {
      "path": "assets/plugins/countdown/uploads/birthday-cake.png"
    }
  ]
}
```

### Vacation Countdown
```json
{
  "name": "Hawaii Trip",
  "target_date": "2026-07-20",
  "enabled": true,
  "image": [
    {
      "path": "assets/plugins/countdown/uploads/beach.jpg"
    }
  ]
}
```

### Holiday Countdown
```json
{
  "name": "Christmas",
  "target_date": "2026-12-25",
  "enabled": true,
  "image": [
    {
      "path": "assets/plugins/countdown/uploads/christmas-tree.png"
    }
  ]
}
```

## Image Guidelines

- **Supported Formats**: PNG, JPEG, BMP, GIF
- **Recommended Size**: Images will be scaled to fit left 1/3 of display
- **Transparency**: PNG transparency is supported
- **Max File Size**: 5MB per image
- **Best Practice**: Use square or portrait-oriented images for best fit

## Troubleshooting

### Countdown Not Showing
- Verify the countdown is **enabled** in the configuration
- Check that the target date is in the correct format (YYYY-MM-DD)
- Ensure at least one countdown is enabled

### Image Not Displaying
- Verify the image file was uploaded successfully
- Check image format is supported (PNG, JPG, BMP, GIF)
- Try re-uploading the image
- Check LEDMatrix logs for image loading errors

### Wrong Date Calculation
- Verify date format is YYYY-MM-DD
- Check your system date/time is correct
- Dates are calculated based on midnight local time

### Font Too Large/Small
- Adjust `font_size` and `name_font_size` in configuration
- Range is 6-16 pixels
- Smaller fonts work better on smaller displays

## Technical Details

### API Version
- LEDMatrix API: 1.0.0
- Compatible with LEDMatrix >=2.0.0

### Dependencies
- Pillow >= 9.0.0
- python-dateutil >= 2.8.0

### Plugin Architecture
- Inherits from `BasePlugin`
- Uses font manager for text rendering
- Implements dynamic duration for smooth rotation
- Caches loaded images for performance

### File Locations
- **Plugin Directory**: `plugin-repos/countdown/`
- **Uploaded Images**: `assets/plugins/countdown/uploads/`
- **Configuration**: Stored in LEDMatrix `config.json`

## Development

### Project Structure
```
countdown/
├── manifest.json          # Plugin metadata
├── config_schema.json     # Configuration schema
├── manager.py             # Plugin implementation
├── requirements.txt       # Python dependencies
└── README.md             # This file
```

### Key Methods
- `update()`: Recalculates all countdown values
- `display()`: Renders current countdown with image and text
- `_calculate_time_remaining()`: Computes days/hours/minutes to target
- `_load_and_scale_image()`: Loads and scales images to fit layout

## Contributing

Feel free to submit issues, feature requests, or pull requests!

## License

MIT License - See LICENSE file for details

## Credits

Created for the LEDMatrix project by Charles

Inspired by the static-image plugin for image handling patterns.

## Support

For issues or questions:
1. Check the LEDMatrix documentation
2. Review the troubleshooting section above
3. Check LEDMatrix logs for error messages
4. Open an issue on the repository

## Changelog

### Version 1.0.0
- Initial release
- Multiple countdown support
- Custom image uploads per countdown
- Configurable fonts and colors
- Split layout (image left 1/3, text right 2/3)
- Auto-rotation through enabled countdowns
- "TODAY!" special display for event day
