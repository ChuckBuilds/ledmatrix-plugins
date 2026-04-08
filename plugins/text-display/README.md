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

# Text Display Plugin

Display custom scrolling or static text messages on your LED matrix with configurable fonts, colors, and animations.

## Features

- **Scrolling Text**: Smooth horizontal scrolling animation
- **Static Text**: Centered text display
- **Custom Fonts**: Support for TTF and BDF fonts
- **Custom Colors**: Configurable text and background colors
- **Adjustable Speed**: Control scroll speed
- **Auto-sizing**: Automatic text width calculation
- **Gap Control**: Configurable gap between scroll loops

## Configuration

### Example Configuration

```json
{
  "enabled": true,
  "text": "Subscribe to ChuckBuilds!",
  "font_path": "assets/fonts/PressStart2P-Regular.ttf",
  "font_size": 8,
  "scroll": true,
  "scroll_speed": 1,
  "scroll_delay": 0.01,
  "scroll_loop": true,
  "scroll_gap_width": 32,
  "target_fps": 120,
  "text_color": [255, 0, 0],
  "background_color": [0, 0, 0],
  "display_duration": 10
}
```

### Configuration Options

The full schema lives in
[`config_schema.json`](config_schema.json) — the web UI form is generated
from it. Key options:

| Key | Default | Notes |
|---|---|---|
| `enabled` | `false` | Master switch |
| `text` | `"Subscribe to ChuckBuilds"` | The message to display |
| `font_path` | `assets/fonts/PressStart2P-Regular.ttf` | Path to TTF or BDF font file |
| `font_size` | `8` | Font size in pixels |
| `scroll` | `true` | Enable horizontal scrolling animation |
| `scroll_speed` | `1` | Speed multiplier (≈ pixels per frame). Higher = faster. |
| `scroll_delay` | `0.01` | Sleep between scroll steps in seconds. Lower = smoother but more CPU |
| `scroll_loop` | `true` | Loop the text instead of stopping after one pass |
| `scroll_gap_width` | `32` | Pixels of space between scroll loops |
| `target_fps` | `120` | Target frames per second cap for scroll rendering |
| `text_color` | `[255, 255, 255]` | RGB text color |
| `background_color` | `[0, 0, 0]` | RGB background color |
| `display_duration` | `10` | Seconds the plugin holds the screen |
| `update_interval` | `60` | Seconds between plugin update ticks |

## Usage

### Basic Static Text

For text that fits on screen:
```json
{
  "text": "HELLO",
  "scroll": false,
  "font_size": 12
}
```

### Scrolling Message

For longer messages:
```json
{
  "text": "This is a long message that will scroll across the display",
  "scroll": true,
  "scroll_speed": 40
}
```

### Custom Styling

```json
{
  "text": "ALERT!",
  "text_color": [255, 0, 0],
  "background_color": [0, 0, 0],
  "font_path": "assets/fonts/PressStart2P-Regular.ttf",
  "font_size": 10
}
```

## Font Support

### TTF Fonts (TrueType)

Most common, widely available:
```json
{
  "font_path": "assets/fonts/PressStart2P-Regular.ttf",
  "font_size": 8
}
```

### BDF Fonts (Bitmap)

Optimized for LED matrices:
```json
{
  "font_path": "assets/fonts/4x6.bdf",
  "font_size": 6
}
```

## Tips & Best Practices

### For Scrolling Text

1. **Adjust speed for readability**: `scroll_speed` is a multiplier, not px/s.
   Values around `1`–`2` are typical; higher values scroll faster.
2. **Tune smoothness with `scroll_delay`**: lower (0.005) = smoother but
   more CPU; higher (0.05) = choppier but lighter.
3. **Set appropriate gap**: a `scroll_gap_width` equal to your display width
   produces clean loops.
4. **Test message length**: very long messages benefit from a higher
   `target_fps` cap and lower `scroll_delay`.

### For Static Text

1. **Center short messages**: Disable scroll for text that fits
2. **Choose appropriate font size**: Match display height
3. **Use contrasting colors**: Ensure good visibility

### Font Selection

1. **For LED matrices**: Pixel fonts (BDF) work best
2. **For clarity**: Use fonts designed for small sizes
3. **For style**: TrueType fonts offer more options

## Common Use Cases

### Announcements
```json
{
  "text": "WELCOME!",
  "scroll": false,
  "font_size": 12,
  "text_color": [0, 255, 0]
}
```

### Ticker Messages
```json
{
  "text": "Breaking News: LED matrices are awesome! Stay tuned for more...",
  "scroll": true,
  "scroll_speed": 1.5
}
```

### Call to Action
```json
{
  "text": "Subscribe to ChuckBuilds on YouTube!",
  "scroll": true,
  "scroll_speed": 2,
  "text_color": [255, 0, 0]
}
```

## Troubleshooting

**Text not visible:**
- Check text_color is different from background_color
- Verify text string is not empty
- Check font_path points to valid font file

**Scrolling too fast/slow:**
- Adjust `scroll_speed` (multiplier, default `1`). Try values between `0.5` and `3`.
- For finer control, also tune `scroll_delay` and `target_fps`.

**Font not loading:**
- Verify font_path is correct
- Check font file exists
- Ensure font file permissions are correct
- For BDF fonts, ensure freetype-py is installed

**Text appears cut off:**
- Reduce font_size
- For static text, ensure text fits display width
- For scrolling, text should extend beyond display

## Performance Notes

- Scrolling text uses a pre-rendered cache for smooth animation
- The render loop targets `target_fps` (default 120) and sleeps
  `scroll_delay` between steps
- Text cache is created once at first render and reused
- Font loading happens once at initialization

## License

GPL-3.0 License - see main LEDMatrix repository for details.

