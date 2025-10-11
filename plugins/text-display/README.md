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
  "scroll_speed": 30,
  "scroll_gap_width": 32,
  "text_color": [255, 0, 0],
  "background_color": [0, 0, 0],
  "display_duration": 10
}
```

### Configuration Options

- `enabled`: Enable/disable the plugin
- `text`: The message to display
- `font_path`: Path to TTF or BDF font file
- `font_size`: Font size in pixels (4-32)
- `scroll`: Enable scrolling animation
- `scroll_speed`: Scroll speed in pixels per second (1-200)
- `scroll_gap_width`: Gap between scroll repetitions in pixels
- `text_color`: RGB text color [R, G, B]
- `background_color`: RGB background color [R, G, B]
- `display_duration`: Display duration in seconds

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

1. **Adjust speed for readability**: Slower speeds (20-40) are more readable
2. **Set appropriate gap**: Use gap equal to display width for smooth loops
3. **Test message length**: Very long messages may need speed adjustment

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
  "scroll_speed": 35
}
```

### Call to Action
```json
{
  "text": "Subscribe to ChuckBuilds on YouTube!",
  "scroll": true,
  "scroll_speed": 40,
  "text_color": [255, 0, 0]
}
```

## Troubleshooting

**Text not visible:**
- Check text_color is different from background_color
- Verify text string is not empty
- Check font_path points to valid font file

**Scrolling too fast/slow:**
- Adjust scroll_speed value
- Try values between 20-50 for best readability

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

- Scrolling text uses pre-rendered cache for smooth animation
- Update interval is 0.033s (~30 FPS) for smooth scrolling
- Text cache is created once and reused for efficiency
- Font loading happens once at initialization

## License

MIT License - see main LEDMatrix repository for details.

