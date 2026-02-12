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

# Olympics Countdown Plugin

A LEDMatrix plugin that displays a countdown to the next Olympics (summer or winter) with an Olympics logo. Once the Olympics starts, it automatically switches to countdown to the closing ceremony.

Screenshot Preview:

<img width="512" height="128" alt="led_matrix_1765854815412" src="https://github.com/user-attachments/assets/a73e6c3c-97e2-412d-8ea3-6a35d301040c" />


## Features

- **Automatic Olympics Detection**: Automatically determines the next Olympics (summer or winter)
- **Dynamic Countdown**: 
  - Before Olympics: Countdown to opening ceremony
  - During Olympics: Countdown to closing ceremony
- **Olympics Logo**: Displays Olympics logo (image or programmatically drawn Olympic rings)
- **Adaptive Text Display**: Automatically adjusts text size and layout for different display sizes
- **Multiple Olympics Support**: Includes dates for upcoming Olympics through 2032

## Installation

### From Plugin Store (Recommended)

1. Open the LEDMatrix web interface (`http://your-pi-ip:5000`)
2. Go to **Plugin Store**
3. Find **Olympics Countdown** and click **Install**

### Manual Installation

1. Copy the plugin from the monorepo:
   ```bash
   cp -r ledmatrix-plugins/plugins/olympics /path/to/LEDMatrix/plugin-repos/
   ```

2. Enable the plugin in `config/config.json`:
   ```json
   {
     "olympics": {
       "enabled": true,
       "display_duration": 15
     }
   }
   ```

## Configuration

The plugin supports the following configuration options:

### Basic Settings

- `enabled` (boolean, default: `false`): Enable or disable the plugin
- `display_duration` (number, default: `15`): How long to display the countdown in seconds (1-300)
- `update_interval` (integer, default: `3600`): How often to update the countdown in seconds (60-86400). Default is 1 hour since the countdown changes daily.

### Appearance

- `text_color` (array, default: `[255, 255, 255]`): RGB color for the countdown text (default: white)
- `logo_size` (integer, optional): Size of the Olympics logo in pixels (8-64). If not specified, size is auto-calculated based on display height.

### Transitions

- `transition` (object): Transition configuration
  - `type` (string): Transition type - `redraw`, `fade`, `slide`, `wipe`, `dissolve`, `pixelate` (default: `redraw`)
  - `speed` (integer): Transition speed 1-10 (default: `2`)
  - `enabled` (boolean): Enable transitions (default: `true`)

### Example Configuration

```json
{
  "olympics": {
    "enabled": true,
    "display_duration": 20,
    "update_interval": 3600,
    "text_color": [255, 255, 255],
    "logo_size": 24,
    "transition": {
      "type": "fade",
      "speed": 3,
      "enabled": true
    }
  }
}
```

## Display Behavior

### Countdown Display

- **Before Olympics**: Shows "N DAYS UNTIL [SUMMER/WINTER] OLYMPICS"
- **During Olympics**: Shows "N DAYS UNTIL CLOSING"
- **On Opening Day**: Shows "OLYMPICS OPENING TODAY"
- **On Closing Day**: Shows "OLYMPICS CLOSING TODAY"

### Layout

- Olympics logo is displayed on the left half of the display
- Countdown text is displayed on the right half, stacked vertically
- Layout automatically adjusts for different display sizes

### Supported Olympics

The plugin includes dates for:
- **Winter Olympics 2026**: Milan-Cortina (Feb 6-22, 2026)
- **Summer Olympics 2028**: Los Angeles (July 14-30, 2028)
- **Winter Olympics 2030**: TBD (placeholder dates)
- **Summer Olympics 2032**: Brisbane (July 23 - Aug 8, 2032)

## Assets

The plugin will look for an Olympics logo image in the following locations:
- `olympics-logo.png`
- `olympics logo.png`
- `olympics-icon.png`
- `logo.png`
- `assets/olympics-logo.png`
- `assets/logo.png`

If no image is found, the plugin will automatically draw the Olympic rings programmatically as a fallback.

**Note**: You can provide your own Olympics logo image by placing it in the plugin directory with one of the names above.

## Dependencies

- Python 3.7+
- PIL/Pillow (for image handling)
- LEDMatrix 2.0.0 or higher

No additional Python packages are required beyond what LEDMatrix provides.

## Troubleshooting

### Logo Image Not Displaying

If the logo image doesn't appear:
1. Check that the image file exists in the plugin directory with one of the supported names
2. The plugin will automatically fall back to programmatic Olympic rings if the image is missing
3. Verify file permissions allow reading the image file

### Countdown Not Updating

- The countdown updates based on `update_interval` (default: 1 hour)
- The countdown changes once per day, so hourly updates are sufficient
- Check the plugin logs for any errors

### Text Not Fitting

- The plugin automatically adjusts text size and layout based on display dimensions
- If text still doesn't fit, reduce `logo_size` in configuration
- The plugin automatically adjusts layout based on display dimensions

## Development

### Project Structure

```
olympics/
├── manifest.json          # Plugin metadata
├── manager.py             # Main plugin class
├── config_schema.json     # Configuration schema
├── README.md             # This file
├── requirements.txt      # Python dependencies
└── assets/               # Optional: Olympics logo image
    └── olympics-logo.png
```

### Testing

Test the plugin using the LEDMatrix emulator:
```bash
python run.py --emulator
```

## License

This plugin follows the same license as the LEDMatrix project.

## Author

ChuckBuilds

## Version

1.0.0

