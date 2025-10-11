# Of The Day Display Plugin

Display daily featured content like Word of the Day, Bible verses, or custom daily items with automatic rotation and multi-category support.

## Features

- **Multiple Categories**: Word of the Day, Bible verses, custom content
- **Automatic Daily Updates**: Loads new content each day
- **Rotating Display**: Alternates between title and content
- **Multi-line Text Wrapping**: Handles long definitions
- **Configurable Data Sources**: Load from JSON files
- **Category Rotation**: Cycles through enabled categories

## Configuration

### Example Configuration

```json
{
  "enabled": true,
  "update_interval": 3600,
  "display_rotate_interval": 20,
  "subtitle_rotate_interval": 10,
  "category_order": ["word_of_the_day", "bible_verse_of_the_day"],
  "categories": {
    "word_of_the_day": {
      "enabled": true,
      "data_file": "of_the_day/word_of_the_day.json",
      "display_name": "Word of the Day"
    },
    "bible_verse_of_the_day": {
      "enabled": false,
      "data_file": "of_the_day/bible_verse_of_the_day.json",
      "display_name": "Bible Verse"
    }
  },
  "display_duration": 40
}
```

### Configuration Options

- `enabled`: Enable/disable the plugin
- `update_interval`: Seconds between checking for new day (default: 3600)
- `display_rotate_interval`: Seconds between category rotations (default: 20)
- `subtitle_rotate_interval`: Seconds between title/content rotation (default: 10)
- `category_order`: Order to display categories
- `categories`: Dictionary of category configurations
- `display_duration`: Total display duration in seconds

## Plugin Structure

This plugin is fully self-contained. All data files are stored within the plugin directory:

```
of-the-day/
├── manifest.json
├── config_schema.json
├── manager.py
├── requirements.txt
├── README.md
└── of_the_day/                    # Data directory
    ├── word_of_the_day.json
    ├── slovenian_word_of_the_day.json
    └── bible_verse_of_the_day.json
```

When you download/install this plugin, everything it needs is included. When you delete it, no traces remain.

## Data File Format

Each category uses a JSON file with daily entries:

### Word of the Day Format

```json
{
  "2025-10-11": {
    "word": "Ephemeral",
    "pronunciation": "ih-FEM-er-uhl",
    "type": "adjective",
    "definition": "Lasting for a very short time; transitory",
    "example": "The beauty of cherry blossoms is ephemeral, lasting only a week or two."
  }
}
```

### Bible Verse Format

```json
{
  "2025-10-11": {
    "title": "John 3:16",
    "content": "For God so loved the world that he gave his one and only Son...",
    "reference": "John 3:16 (NIV)"
  }
}
```

### Custom Format

You can create custom categories with any structure containing:
- `word` or `title`: Main heading
- `definition` or `content` or `text`: Main content
- Optional: `pronunciation`, `type`, `example`, etc.

## Usage

### Adding New Categories

1. Create a JSON data file in the plugin's `of_the_day/` directory
   - Path: `plugins/of-the-day/of_the_day/my_custom.json`
2. Add entries for each date in YYYY-MM-DD format
3. Add category to config:

```json
{
  "categories": {
    "my_custom_category": {
      "enabled": true,
      "data_file": "of_the_day/my_custom.json",
      "display_name": "My Daily Item"
    }
  },
  "category_order": ["my_custom_category", "word_of_the_day"]
}
```

### Display Behavior

The plugin rotates through:
1. **Category rotation**: Changes every `display_rotate_interval` seconds
2. **Content rotation**: Within each category, alternates between:
   - Title/word display with category name
   - Definition/content display with word wrapping

### Built-in Categories

**word_of_the_day**
- Displays vocabulary words with definitions
- Shows pronunciation and part of speech
- Great for learning and education

**bible_verse_of_the_day**
- Displays daily Bible verses
- Shows reference and translation
- Perfect for inspiration

**slovenian_word_of_the_day**
- Example of foreign language words
- Can be adapted for any language

## Plugin Isolation

This plugin is designed to be completely self-contained:

- ✅ All data files stored in plugin directory
- ✅ No external dependencies on main project structure
- ✅ Can be installed/uninstalled cleanly
- ✅ No traces left after deletion
- ✅ Easy to backup (just copy the plugin folder)
- ✅ Easy to share (distribute the entire plugin directory)

Data files are automatically loaded from `of_the_day/` subdirectory within the plugin.

## Creating Data Files

### Template Structure

```json
{
  "2025-01-01": {
    "word": "Example",
    "definition": "A representative form or pattern",
    "pronunciation": "ig-ZAM-puhl",
    "type": "noun",
    "example": "This is an example sentence."
  },
  "2025-01-02": {
    "word": "Another",
    "definition": "One more; an additional",
    ...
  }
}
```

### Tips for Creating Content

1. **Date Format**: Always use YYYY-MM-DD
2. **Keep it Short**: Definitions should fit on 4-5 lines
3. **Clear Pronunciation**: Use phonetic spelling
4. **Good Examples**: Make them memorable and relevant
5. **Consistent Structure**: Use same fields across all entries

## Display Examples

### Title Display
```
    Word of the Day    
    
       Ephemeral
       
    (ih-FEM-er-uhl)
```

### Content Display
```
Lasting for a very
short time; transitory
The beauty of cherry
blossoms is ephemeral
```

## Advanced Usage

### Multiple Data Sources

You can maintain separate data files for different purposes:
- Educational words
- Technical terms
- Inspirational quotes
- Historical facts
- Daily trivia

### Automated Updates

Data files can be updated automatically:
- From APIs (Merriam-Webster, etc.)
- From RSS feeds
- From custom scripts
- From database exports

## Troubleshooting

**No content displayed:**
- Verify data file path is correct
- Check that today's date exists in JSON file
- Ensure category is enabled in config
- Check file permissions

**Content cut off:**
- Reduce text length in data file
- Adjust display dimensions
- Shorten definitions or examples

**Category not showing:**
- Verify it's in `category_order`
- Check that `enabled` is `true`
- Ensure data file exists and is valid JSON

**Wrong date content:**
- Check system date/time
- Verify date format in JSON (YYYY-MM-DD)
- Check timezone settings

## Integration with Education

Perfect for:
- Vocabulary building
- Language learning
- Daily inspiration
- Historical facts
- Science concepts
- Programming terms

## License

MIT License - see main LEDMatrix repository for details.

