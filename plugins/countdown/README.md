# Countdown Plugin for LEDMatrix

Display customizable countdowns with images on your LED matrix. Perfect for birthdays, holidays, vacations, events, and any special occasion you want to count down to!

## Features

- **Multiple Countdowns**: Create and manage multiple countdown entries
- **Custom Images**: Use a unique local image path for each countdown
- **Individual Control**: Enable/disable each countdown independently
- **Customizable Display**: Configure fonts, colors, and sizes
- **Smart Layout**: Image on left 1/3rd, countdown text on right 2/3rds
- **Auto Rotation**: Automatically cycles through enabled countdowns
- **Flexible Dates**: Supports future dates with automatic "TODAY!" display
- **Web UI Management**: Full configuration via LEDMatrix web interface

## Installation

### From Plugin Store (Recommended)

1. Open the LEDMatrix web interface (`http://your-pi-ip:5000`)
2. Open the **Plugin Manager** tab
3. Find **Countdown Display** in the **Plugin Store** section and click
   **Install**

### Manual Installation

1. Copy the plugin from the monorepo:
   ```bash
   cp -r ledmatrix-plugins/plugins/countdown /path/to/LEDMatrix/plugin-repos/
   ```

2. Restart LEDMatrix or reload plugins via the web UI

## Configuration

### Adding a Countdown

1. Open the LEDMatrix web UI
2. Open the **Countdown Display** tab (second nav row, added once the
   plugin is installed)
3. Click "Add Countdown"
4. Fill in the details:
   - **Name**: Display name (e.g., "Birthday", "Vacation")
   - **Target Date**: The date you're counting down to
   - **Image Path**: Enter a local path (e.g., `assets/plugins/countdown/uploads/birthday.png`)
   - **Enabled**: Toggle to show/hide this countdown
5. Click Save

### Configuration Options

The web UI form is generated from `config_schema.json` (the source of truth).

#### Per-Countdown Settings

Each entry in the **Countdowns** table supports:

| Field | Default | Notes |
|-------|---------|-------|
| `name` (required) | — | Display name, max 30 chars |
| `target_date` (required) | — | `YYYY-MM-DD` — the date to count to/from |
| `target_time` | `00:00` | Optional `HH:MM` (24h) for sub-day precision; switches to hours/minutes as the event nears |
| `mode` | `until` | `until` counts down to the date (Days Until); `since` counts up from it (Days Since) |
| `layout_preset` | `image-left` | `image-left`, `image-right`, `text-only`, or `image-only` |
| `text_align` | `center` | `left`, `center`, or `right` for the name/value text |
| `image_path` | — | Optional image shown alongside the countdown |
| `enabled` | `true` | Show/hide this countdown |
| `display_order` | `0` | Rotation order (lower first) |
| `layout.*` | auto | Optional pixel position/size overrides for the image and text |
| `style.*` | inherit | Optional per-countdown font/size/color overrides (`null` inherits the global settings below) |

#### Global Settings (defaults for all countdowns)

| Key | Default | Notes |
|-----|---------|-------|
| `display_duration` | `15` | Seconds to show each countdown before rotating (5–300) |
| `font_family` | `press_start` | One of `press_start`, `four_by_six`, `tom_thumb`, `tiny`, `picopixel` |
| `font_size` | `8` | Countdown value font size (4–16px) |
| `font_color` | `[255, 255, 255]` | RGB color for the countdown value |
| `name_font_size` | `8` | Countdown name font size (4–16px) |
| `name_font_color` | `[200, 200, 200]` | RGB color for the countdown name |
| `background_color` | `[0, 0, 0]` | RGB background color |
| `show_expired` | `false` | Show `until` countdowns that have passed (as "Nd ago") |
| `fit_to_display` | `true` | Auto-scale images to their allocated area |
| `preserve_aspect_ratio` | `true` | Keep image proportions when scaling |

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
  "image_path": "assets/plugins/countdown/uploads/birthday-cake.png"
}
```

### Vacation Countdown
```json
{
  "name": "Hawaii Trip",
  "target_date": "2026-07-20",
  "enabled": true,
  "image_path": "assets/plugins/countdown/uploads/beach.jpg"
}
```

### Holiday Countdown
```json
{
  "name": "Christmas",
  "target_date": "2026-12-25",
  "enabled": true,
  "image_path": "assets/plugins/countdown/uploads/christmas-tree.png"
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
- Verify the configured image path exists on disk
- Check image format is supported (PNG, JPG, BMP, GIF)
- Confirm the path is readable by the LEDMatrix process
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
- **Suggested Image Directory**: `assets/plugins/countdown/uploads/` (example location only; set each countdown's `image_path` explicitly in plugin configuration)
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

Released under the GNU General Public License v3.0 — see the LICENSE file for details.

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

### Version 2.0.0
- Breaking: countdown image configuration is now path-based only (no per-row upload widget in web UI)
- Updated documentation to use `image_path` text input workflow

### Version 1.0.2
- Removed redundant legacy image fallback in `display()` and rely on normalized `image_path`
- Improved cache invalidation to refresh images when countdown metadata changes (not only count changes)
- Added strict date-schema note and manifest version history metadata

### Version 1.0.1
- Fixed web UI schema for countdown table editing
- Improved config normalization (auto-generate IDs and migrate legacy image format)

### Version 1.0.0
- Initial release
- Multiple countdown support
- Custom image uploads per countdown
- Configurable fonts and colors
- Split layout (image left 1/3, text right 2/3)
- Auto-rotation through enabled countdowns
- "TODAY!" special display for event day
