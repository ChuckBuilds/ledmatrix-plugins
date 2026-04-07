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

# Christmas Countdown Plugin

A festive LEDMatrix plugin that displays a countdown to Christmas with a stylized Christmas tree logo and holiday text.

Screenshot of Christmas Countdown:
<img width="768" height="192" alt="led_matrix_1765383616554" src="https://github.com/user-attachments/assets/899cb576-e7bc-41ee-853e-100395fc22dc" />



## Features

- **Stylized Christmas Tree**: Displays a pixel-art style Christmas tree logo (image or programmatically drawn)
- **Adaptive Text Display**: 
  - Large displays: "N DAYS UNTIL CHRISTMAS"
  - Small displays (width < 64px): "N DAYS UNTIL XMAS"
- **Merry Christmas Message**: Automatically shows "MERRY CHRISTMAS" on and after December 25th
- **Traditional Colors**: Green tree, red text with white accents
- **Customizable**: Configurable colors and tree size

## Configuration

The plugin supports the following configuration options:

### Configuration options

Full schema lives in [`config_schema.json`](config_schema.json):

| Key | Default | Notes |
|---|---|---|
| `enabled` | `false` | Master switch |
| `display_duration` | `15` | Seconds the plugin holds the screen (1–300) |
| `update_interval` | `3600` | Seconds between updates (60–86400). Default 1 hour since the countdown only changes daily. |
| `high_performance_transitions` | `false` | Use a faster path for transitions on weaker Pis |
| `transition.enabled` | `true` | Toggle transition animation between displays |
| `transition.type` | `"redraw"` | Transition style |
| `transition.speed` | `2` | Animation speed |
| `text_color` | `[255, 0, 0]` | RGB color for the countdown text (default red) |
| `tree_color` | `[0, 128, 0]` | RGB color for the programmatically-drawn tree (default green) |
| `tree_size` | _auto_ | Override the auto-sized tree height in pixels |

## Display Behavior

### Countdown Display

- Before December 25th: Shows "N DAYS UNTIL CHRISTMAS" (or "N DAYS UNTIL XMAS" on small displays)
- On December 25th: Shows "MERRY CHRISTMAS"
- After December 25th: Shows "MERRY CHRISTMAS" (countdown to next year's Christmas)

### Layout

- Christmas tree logo is centered horizontally and positioned in the upper portion of the display
- Countdown text is centered below the tree
- Layout automatically adjusts for different display sizes

### Display Size Detection

- Displays with width < 64 pixels automatically use "XMAS" instead of "CHRISTMAS" to fit the text
- Tree size is automatically calculated based on display height (25-40% of height)
- All content is centered for optimal viewing

## Assets

The plugin includes a stylized Christmas tree image at `assets/christmas_tree.png`. If the image is not found, the plugin will automatically draw a simple tree programmatically.

To regenerate the tree image, run:
```bash
python3 generate_tree_image.py
```

## Dependencies

- Python 3.7+
- PIL/Pillow (for image handling)
- LEDMatrix 2.0.0 or higher

No additional Python packages are required beyond what LEDMatrix provides.

## Troubleshooting

### Tree Image Not Displaying

If the tree image doesn't appear:
1. Check that `assets/christmas_tree.png` exists in the plugin directory
2. The plugin will automatically fall back to programmatic drawing if the image is missing
3. Verify file permissions allow reading the image file

### Countdown Not Updating

- The countdown updates based on `update_interval` (default: 1 hour)
- The countdown changes once per day, so hourly updates are sufficient
- Check the plugin logs for any errors

### Text Not Fitting

- On small displays (width < 64px), the plugin automatically uses "XMAS" instead of "CHRISTMAS"
- If text still doesn't fit, reduce `tree_size` in configuration
- The plugin automatically adjusts layout based on display dimensions

## Development

### Project Structure

```
christmas-countdown/
├── manifest.json          # Plugin metadata
├── manager.py             # Main plugin class
├── config_schema.json     # Configuration schema
├── README.md             # This file
├── requirements.txt      # Python dependencies
├── generate_tree_image.py # Utility to generate tree image
└── assets/
    └── christmas_tree.png # Christmas tree image
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

