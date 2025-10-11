# Google Calendar Plugin

Display upcoming events from Google Calendar with automatic updates, event rotation, and timezone support.

## Features

- **Google Calendar Integration**: OAuth2 authentication
- **Multiple Calendar Support**: Display events from multiple calendars
- **Event Rotation**: Automatically cycles through upcoming events
- **All-Day Events**: Shows both timed and all-day events
- **Timezone Support**: Displays times in your local timezone
- **Text Wrapping**: Handles long event titles gracefully
- **Auto-Updates**: Fetches new events periodically

## Requirements

- Google Calendar API credentials
- Python 3.9+
- Internet connection for API access

## Setup Instructions

### 1. Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing one
3. Enable the Google Calendar API
4. Create OAuth 2.0 credentials

### 2. Download Credentials

1. In Cloud Console, go to "Credentials"
2. Click "Create Credentials" → "OAuth client ID"
3. Choose "Desktop application"
4. Download the JSON file
5. Save as `credentials.json` in the **calendar plugin directory**
   - Path: `plugins/calendar/credentials.json`

### 3. First-Time Authentication

**Option A: Use Registration Script (Recommended)**
```bash
cd plugins/calendar
python calendar_registration.py
```

**Option B: Let Plugin Authenticate**
When you first run the plugin:
1. A browser window will open
2. Sign in with your Google account
3. Grant calendar read permissions
4. Token will be saved in the plugin directory

All authentication files (`credentials.json` and `token.pickle`) are stored in the plugin directory for complete isolation.

## Configuration

### Example Configuration

```json
{
  "enabled": true,
  "credentials_file": "credentials.json",
  "token_file": "token.pickle",
  "max_events": 3,
  "calendars": ["primary"],
  "update_interval": 300,
  "show_all_day_events": true,
  "event_rotation_interval": 10,
  "display_duration": 30
}
```

### Configuration Options

- `enabled`: Enable/disable the plugin
- `credentials_file`: Path to OAuth credentials JSON file
- `token_file`: Path to store authentication token
- `max_events`: Maximum number of events to fetch (1-10)
- `calendars`: List of calendar IDs (use `"primary"` for default calendar)
- `update_interval`: Seconds between API updates (minimum 60)
- `show_all_day_events`: Include all-day events
- `event_rotation_interval`: Seconds between rotating events (minimum 5)
- `display_duration`: Total display duration in seconds

## Display Format

### Timed Event
```
    03/15 2:30pm
    
    Team Meeting
    
```

### All-Day Event
```
    03/20 All Day
    
    Birthday Party
    
```

### Long Title (Wrapped)
```
    03/22 10:00am
    
   Project Review
   and Planning
```

## Multiple Calendars

To display events from multiple calendars:

```json
{
  "calendars": [
    "primary",
    "family@group.calendar.google.com",
    "work@company.com"
  ]
}
```

Events from all calendars are merged and sorted by start time.

## Usage Tips

### Event Rotation

- Events automatically rotate every `event_rotation_interval` seconds
- Shows up to `max_events` at a time
- Sorted by start time (soonest first)

### Update Frequency

- Set `update_interval` to balance freshness vs. API usage
- 300 seconds (5 minutes) is recommended
- Lower values may hit API rate limits

### Timezone

Plugin uses timezone from main LEDMatrix config:
```json
{
  "timezone": "America/New_York"
}
```

See [List of timezones](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones)

## Troubleshooting

**No events displayed:**
- Check that calendars have upcoming events
- Verify calendar IDs are correct
- Check authentication is valid
- Review logs for API errors

**Authentication failed:**
- Delete `token.pickle` and re-authenticate
- Verify `credentials.json` is valid
- Ensure OAuth consent screen is configured
- Check API is enabled in Cloud Console

**Wrong timezone:**
- Set correct timezone in main config
- Verify timezone string is valid
- Restart after changing timezone

**Events not updating:**
- Check `update_interval` isn't too high
- Verify internet connection
- Check API quota hasn't been exceeded
- Review logs for errors

**Long titles cut off:**
- Text automatically wraps to 2 lines
- Titles longer than 2 lines will be truncated
- Consider shortening event names in Google Calendar

## Calendar IDs

### Finding Calendar IDs

1. Open Google Calendar in browser
2. Click settings gear → "Settings"
3. Select calendar from left sidebar
4. Scroll to "Integrate calendar"
5. Copy "Calendar ID"

### Common Calendar Types

- **Primary**: `"primary"` (your main calendar)
- **Shared**: `"name@group.calendar.google.com"`
- **Other Google**: `"email@gmail.com"`

## API Limits

Google Calendar API has rate limits:
- **Free tier**: 1,000,000 queries per day
- **Per user**: 10 requests per second

With default settings (300s interval):
- 288 requests per day (well within limits)

## Security Notes

- `credentials.json`: Contains OAuth client credentials (stored in plugin directory)
- `token.pickle`: Contains access token (stored in plugin directory)
- Keep both files secure and don't commit to git
- The plugin automatically stores these in its own directory
- If you delete the plugin, all authentication data is removed
- Recommended: Add to plugin `.gitignore`:
  ```
  credentials.json
  token.pickle
  ```

## Advanced Configuration

### Custom Display Duration

Match event length:
```json
{
  "display_duration": 60,
  "event_rotation_interval": 20
}
```

### Quick Rotation

Cycle through many events quickly:
```json
{
  "max_events": 10,
  "event_rotation_interval": 5
}
```

### Minimal Updates

Reduce API calls:
```json
{
  "update_interval": 900,
  "max_events": 1
}
```

## Integration with Other Plugins

Calendar works well alongside:
- **Clock**: Shows time, calendar shows events
- **Weather**: Schedule awareness for outdoor events
- **Static Image**: Display event-related images

## Examples

### Home Calendar
```json
{
  "enabled": true,
  "calendars": ["primary", "family@group.calendar.google.com"],
  "max_events": 5,
  "event_rotation_interval": 10
}
```

### Work Calendar
```json
{
  "enabled": true,
  "calendars": ["work@company.com"],
  "max_events": 3,
  "show_all_day_events": false
}
```

### Birthday Reminders
```json
{
  "enabled": true,
  "calendars": ["birthdays@group.calendar.google.com"],
  "max_events": 1,
  "event_rotation_interval": 30
}
```

## License

MIT License - see main LEDMatrix repository for details.

