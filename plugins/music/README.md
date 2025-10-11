# Music Now Playing Plugin

Display currently playing music from Spotify or YouTube Music with album art, track information, and smooth scrolling text.

## Features

- **Spotify Integration**: Show Spotify now playing
- **YouTube Music Integration**: Show YTM now playing
- **Album Artwork**: Display album cover art
- **Scrolling Text**: Smooth scrolling for long titles
- **Real-time Updates**: Auto-polling for playback changes
- **Multi-source Support**: Switch between Spotify and YTM

## Requirements

### For Spotify

1. Spotify Premium account
2. Spotify API credentials from [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
3. Run authentication script: `python plugins/music/authenticate_spotify.py`
4. Authentication files are stored in the plugin directory

### For YouTube Music

1. YouTube Music subscription (optional but recommended)
2. WebNowPlaying-Redux companion app
3. Companion server running on local network

## Configuration

### Example Configuration

```json
{
  "enabled": true,
  "preferred_source": "ytm",
  "POLLING_INTERVAL_SECONDS": 2,
  "YTM_COMPANION_URL": "http://192.168.86.12:9863",
  "show_album_art": true,
  "scroll_long_text": true,
  "scroll_speed": 1,
  "display_duration": 30
}
```

### Configuration Options

- `enabled`: Enable/disable the plugin
- `preferred_source`: Music source (`spotify` or `ytm`)
- `POLLING_INTERVAL_SECONDS`: How often to check for updates (1-10 seconds)
- `YTM_COMPANION_URL`: URL to YTM companion server
- `show_album_art`: Display album artwork
- `scroll_long_text`: Enable scrolling for long titles/artists
- `scroll_speed`: Speed of scrolling (1-10, higher = faster)
- `display_duration`: Display duration in seconds

## Setup Instructions

### Spotify Setup

1. **Create Spotify App**:
   - Go to https://developer.spotify.com/dashboard
   - Create a new app
   - Note your Client ID and Client Secret
   - Set redirect URI to `http://localhost:8888/callback` (or your preferred URI)

2. **Configure Credentials**:
   
   **Option A: Environment Variables (Recommended)**
   ```bash
   export SPOTIFY_CLIENT_ID="your_client_id"
   export SPOTIFY_CLIENT_SECRET="your_client_secret"
   export SPOTIFY_REDIRECT_URI="http://localhost:8888/callback"
   ```
   
   **Option B: Plugin Configuration**
   Add to your music plugin config:
   ```json
   {
     "spotify_client_id": "your_client_id",
     "spotify_client_secret": "your_client_secret",
     "spotify_redirect_uri": "http://localhost:8888/callback"
   }
   ```

3. **Authenticate**:
   ```bash
   cd plugins/music
   python authenticate_spotify.py
   ```
   
   Follow the prompts:
   - Visit the provided authorization URL in your browser
   - Authorize the application
   - Copy the full redirected URL (even if it shows an error)
   - Paste it back into the terminal
   
   This will create `spotify_auth.json` in the plugin directory.

4. **Enable in Config**:
   ```json
   {
     "music": {
       "enabled": true,
       "preferred_source": "spotify"
     }
   }
   ```

### YouTube Music Setup

1. **Install Companion App**:
   - Download and install the YTM Companion desktop app
   - Or use WebNowPlaying-Redux with browser extension
   - Start the companion server (default port: 9863)

2. **Authenticate**:
   ```bash
   cd plugins/music
   python authenticate_ytm.py
   ```
   
   Follow the prompts:
   - Enter your YTM Companion URL (or press Enter for `http://localhost:9863`)
   - When prompted, approve the authentication request in your YTM Desktop App
   - You have 30 seconds to approve
   
   This will create `ytm_auth.json` in the plugin directory.

3. **Configure URL**:
   ```json
   {
     "music": {
       "enabled": true,
       "preferred_source": "ytm",
       "YTM_COMPANION_URL": "http://YOUR_PC_IP:9863"
     }
   }
   ```

4. **Start Companion**:
   - Ensure companion server is running
   - Play music in YouTube Music
   - Plugin will auto-detect playback

## Display Layout

### With Album Art (64x32 display)
```
┌──────┬────────────────────┐
│      │ Now Playing Title  │
│ Art  │ Artist Name        │
│      │ Album Name         │
└──────┴────────────────────┘
```

### Without Album Art
```
┌────────────────────────────┐
│     Now Playing Title      │
│       Artist Name          │
│       Album Name           │
└────────────────────────────┘
```

## Usage Tips

### Scrolling Text

For long titles that don't fit:
- Enable `scroll_long_text`
- Adjust `scroll_speed` for readability
- Slow speeds (1-2) are more readable
- Fast speeds (5-10) for quick info

### Album Artwork

- Automatically downloads and caches album art
- Resized to fit display
- Slightly dimmed for better text visibility
- Cached per album to reduce network requests

### Polling Interval

- 1-2 seconds: Very responsive, more CPU usage
- 3-5 seconds: Balanced, recommended
- 5-10 seconds: Less responsive, lower resource use

## Troubleshooting

**Nothing displayed:**
- Check that music is actually playing
- Verify preferred_source matches your setup
- Check authentication for Spotify
- Verify companion server URL for YTM

**Spotify not working:**
- Re-run `authenticate_spotify.py` in the plugin directory
- Check that environment variables or config contains valid credentials
- Verify Spotify Premium subscription
- Check that `spotify_auth.json` exists in the plugin directory
- Ensure redirect URI in Spotify dashboard matches your configuration

**YTM not working:**
- Re-run `authenticate_ytm.py` in the plugin directory
- Verify companion server is running
- Check that `ytm_auth.json` exists in the plugin directory
- Check companion URL is correct in config
- Ensure firewall allows connection
- Try opening companion URL in browser (e.g., `http://localhost:9863`)

**Album art not showing:**
- Check internet connection
- Verify `show_album_art` is true
- Some tracks may not have artwork
- Check for image loading errors in logs

**Text scrolling too fast/slow:**
- Adjust `scroll_speed` value
- Try values 1-3 for readability
- Values above 5 may be hard to read

**Lagging/stuttering:**
- Increase `POLLING_INTERVAL_SECONDS`
- Disable album art if not needed
- Check network latency

## Advanced Configuration

### Custom Styling

Modify the display appearance by adjusting font sizes and colors in the code:

```python
# In manager.py
title_font = ImageFont.truetype('path/to/font.ttf', 10)  # Larger title
info_font = ImageFont.truetype('path/to/font.ttf', 8)   # Larger info
```

### Multiple Sources

While only one source is active at a time, you can quickly switch:

```json
{
  "preferred_source": "spotify"  // or "ytm"
}
```

### Performance Tuning

For lower-end devices:
- Increase polling interval to 5+ seconds
- Disable album art
- Disable text scrolling
- Use simpler fonts

## Integration Notes

### Spotify Client

Uses existing `SpotifyClient` from main LEDMatrix codebase:
- Handles OAuth authentication
- Manages token refresh
- Provides playback API access

### YTM Client

Uses existing `YTMClient` from main LEDMatrix codebase:
- Connects to companion server
- Receives real-time updates
- Handles connection errors gracefully

## Examples

### Spotify Configuration
```json
{
  "music": {
    "enabled": true,
    "preferred_source": "spotify",
    "POLLING_INTERVAL_SECONDS": 2,
    "show_album_art": true,
    "scroll_long_text": true,
    "scroll_speed": 2
  }
}
```

### YouTube Music Configuration
```json
{
  "music": {
    "enabled": true,
    "preferred_source": "ytm",
    "YTM_COMPANION_URL": "http://192.168.1.100:9863",
    "POLLING_INTERVAL_SECONDS": 3,
    "show_album_art": true,
    "scroll_long_text": true,
    "scroll_speed": 1
  }
}
```

### Minimal Configuration (No Album Art)
```json
{
  "music": {
    "enabled": true,
    "preferred_source": "ytm",
    "YTM_COMPANION_URL": "http://localhost:9863",
    "show_album_art": false,
    "scroll_long_text": true
  }
}
```

## Plugin Isolation and Security

### Self-Contained Design

This music plugin is fully self-contained. All authentication files are stored within the plugin directory:

- `spotify_auth.json` - Spotify OAuth token
- `ytm_auth.json` - YouTube Music Companion token
- `authenticate_spotify.py` - Spotify authentication script
- `authenticate_ytm.py` - YTM authentication script
- `spotify_client.py` - Spotify API client
- `ytm_client.py` - YTM API client

### Security Notes

**Important:** Authentication files contain sensitive tokens and should be protected:

1. **.gitignore Protection**: The plugin includes a `.gitignore` file that prevents authentication files from being committed to git:
   ```
   spotify_auth.json
   ytm_auth.json
   ```

2. **File Permissions**: Ensure authentication files have appropriate permissions:
   ```bash
   chmod 600 spotify_auth.json ytm_auth.json
   ```

3. **Clean Uninstall**: If you delete this plugin, all authentication data is removed with it. No traces are left in the main LEDMatrix configuration directory.

4. **Environment Variables**: For added security, use environment variables for API credentials instead of storing them in the config file.

### Data Storage Locations

All music plugin data is stored in the plugin directory:

```
plugins/music/
├── authenticate_spotify.py    # Spotify auth script
├── authenticate_ytm.py         # YTM auth script
├── spotify_client.py           # Spotify client
├── ytm_client.py               # YTM client
├── manager.py                  # Plugin main logic
├── manifest.json               # Plugin metadata
├── config_schema.json          # Configuration schema
├── requirements.txt            # Dependencies
├── README.md                   # This file
├── .gitignore                  # Git ignore rules
├── spotify_auth.json           # (created after Spotify auth)
└── ytm_auth.json               # (created after YTM auth)
```

## License

MIT License - see main LEDMatrix repository for details.

