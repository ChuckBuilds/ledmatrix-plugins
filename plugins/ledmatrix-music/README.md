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

# Music Player Plugin

A plugin for LEDMatrix that displays real-time now playing information from Spotify and YouTube Music with album art, scrolling text, and progress bars.

Screenshot

<img width="768" height="192" alt="led_matrix_1765923481911" src="https://github.com/user-attachments/assets/3317fd98-d73b-4ec0-8570-a2f38794c7cb" />



## Features

- **Dual Music Sources**: Support for both Spotify and YouTube Music
- **Real-time Updates**: Live track information with automatic refresh
- **Album Art Display**: High-quality album artwork with automatic resizing and enhancement
- **Scrolling Text**: Smooth scrolling for long track titles, artists, and album names
- **Progress Bar**: Visual progress indicator showing playback position
- **Source Switching**: Automatic detection and switching between music sources
- **Authentication Support**: Built-in OAuth2 for Spotify and token-based auth for YTM
- **Background Polling**: Non-blocking data fetching with configurable intervals
- **Error Handling**: Graceful fallback to "Nothing Playing" state
- **Thread Safety**: Thread-safe operations for concurrent access
- **Display Modes**: Dedicated "now_playing" display mode
- **Configuration**: Flattened config structure for easy plugin management

## Configuration

### Plugin Settings
Use Web Ui to configure


### Configuration Options

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `enabled` | boolean | true | Enable or disable the music plugin |
| `display_duration` | number | 30 | How long to show the music display (10-300 seconds) |
| `preferred_source` | string | "spotify" | Preferred music source ("spotify" or "ytm") |
| `polling_interval_seconds` | number | 2 | Polling interval for Spotify in seconds (1-60) |
| `ytm_companion_url` | string | "http://localhost:9863" | YouTube Music Companion server URL |

## Authentication Setup

### Spotify Authentication

1. **Create Spotify App**:
   - Go to [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
   - Create a new app
   - Note your Client ID and Client Secret
   - Set Redirect URI to `http://localhost:8080/callback` (or your preferred URL)

2. **Configure Credentials**:
   Add to `config/config_secrets.json`:
   ```json
   {
     "ledmatrix-music": {
       "spotify_client_id": "your_client_id_here",
       "spotify_client_secret": "your_client_secret_here",
       "spotify_redirect_uri": "http://localhost:8080/callback"
     }
   }
   ```

   > Older configs that put these under a `"music"` key with
   > `SPOTIFY_CLIENT_ID` (uppercase) still work — `spotify_client.py`
   > falls back to that legacy form — but new installs should use the
   > `"ledmatrix-music"` key with lowercase names shown above.

3. **Run Authentication**:
   ```bash
   cd plugins/ledmatrix-music
   python3 authenticate_spotify.py
   ```
   - Follow the prompts to authorize in your browser
   - Copy the redirected URL back to the script
   - Token will be saved to `config/spotify_auth.json`

### YouTube Music Authentication

1. **Install YTM Desktop App**:
   - Download from [YTM Desktop](https://github.com/ytmdesktop/ytmdesktop)
   - Install and run the application
   - Enable the Companion Server in settings

2. **Configure YTM URL**:
   Update your config if using a different port:
   ```json
   {
     "ledmatrix-music": {
       "ytm_companion_url": "http://localhost:9863"
     }
   }
   ```

3. **Run Authentication**:
   ```bash
   cd plugins/ledmatrix-music
   python3 authenticate_ytm.py
   ```
   - The script will request an auth code
   - Approve the request in YTM Desktop App within 30 seconds
   - Token will be saved to `config/ytm_auth.json`

## Display Format

The music display shows:

- **Album Art**: Square album artwork on the left side
- **Track Title**: Scrolling white text at the top
- **Artist**: Scrolling gray text in the middle
- **Album**: Scrolling light gray text below artist
- **Progress Bar**: White progress bar at the bottom
- **Nothing Playing**: Centered message when no music is detected


## Music Sources

### Spotify
- **API**: Spotify Web API
- **Authentication**: OAuth2 with refresh tokens
- **Data**: Track name, artist, album, artwork, progress, duration
- **Polling**: Configurable interval (default 2 seconds)
- **Features**: Real-time playback state, album art, progress tracking

### YouTube Music
- **API**: YTM Desktop Companion Server
- **Authentication**: Token-based with YTM Desktop App
- **Data**: Track name, artist, album, artwork, progress, duration
- **Updates**: Real-time via Socket.IO events
- **Features**: Live updates, ad detection, playback state

## Display Modes

### Now Playing Mode
- **Mode Name**: `now_playing`
- **Description**: Real-time music information display
- **Features**: Album art, scrolling text, progress bar
- **Duration**: Configurable (10-300 seconds)

## Technical Details

### Threading
- **Polling Thread**: Background thread for Spotify polling
- **Socket.IO Thread**: Real-time updates from YTM
- **Display Thread**: Main display rendering
- **Thread Safety**: All shared data protected with locks

### Image Processing
- **Album Art**: Automatic download and resizing
- **Enhancement**: Contrast and saturation boost for LED matrix
- **Caching**: Images cached to avoid repeated downloads
- **Fallback**: Placeholder rectangle when no artwork available

### Scrolling Logic
- **Text Scrolling**: Smooth character-by-character scrolling
- **Wrap Around**: Continuous scrolling with separator
- **Speed Control**: Configurable scroll speed and timing
- **Multi-line**: Independent scrolling for title, artist, and album

### Error Handling
- **Network Errors**: Graceful fallback to cached data
- **Authentication Errors**: Clear error messages and guidance
- **API Errors**: Automatic retry with exponential backoff
- **Display Errors**: Fallback to "Nothing Playing" state

## Troubleshooting

### No Music Display
1. Check if plugin is enabled in config
2. Verify preferred source is set correctly
3. Check authentication status
4. Review plugin logs for errors

### Spotify Issues
1. Verify credentials in `config_secrets.json`
2. Run `authenticate_spotify.py` to refresh token
3. Check Spotify app is playing music
4. Verify internet connection

### YouTube Music Issues
1. Ensure YTM Desktop App is running
2. Check Companion Server is enabled
3. Run `authenticate_ytm.py` to refresh token
4. Verify YTM is playing music

### Authentication Problems
1. Check file permissions on config directory
2. Verify credentials are correct
3. Ensure redirect URI matches Spotify app settings
4. Check YTM Desktop App is running during auth

### Display Issues
1. Check album art URLs are accessible
2. Verify font files are available
3. Check matrix dimensions and layout
4. Review scrolling configuration

### Performance Issues
1. Adjust polling interval
2. Check system resources
3. Monitor network connectivity
4. Review error logs

## Advanced Configuration

### Custom Fonts
The plugin uses LEDMatrix's font system:
- **Title Font**: `small_font` (TTF)
- **Artist/Album Font**: `bdf_5x7_font` (BDF)

### Color Customization
Colors are hardcoded for optimal LED matrix display:
- **Title**: White (255, 255, 255)
- **Artist**: Light Gray (180, 180, 180)
- **Album**: Gray (150, 150, 150)
- **Progress Bar**: White (200, 200, 200)

### Layout Customization
Layout is optimized for LED matrix displays:
- **Album Art Size**: Full height of display
- **Text Area**: Remaining width after album art
- **Positioning**: Percentage-based for different matrix sizes

## API Integration

### Spotify Web API
- **Endpoint**: `https://api.spotify.com/v1/me/player/currently-playing`
- **Authentication**: Bearer token with automatic refresh
- **Rate Limiting**: Built-in delays between requests
- **Data Format**: JSON with track, artist, album, and progress info

### YTM Companion Server
- **Protocol**: Socket.IO over WebSocket
- **Authentication**: Token-based with app approval
- **Real-time**: Live updates via event callbacks
- **Data Format**: JSON with video, player, and progress info

## Performance Features

### Background Data Fetching
- **Non-blocking**: API calls don't block display updates
- **Caching**: Album art and track data cached locally
- **Retry Logic**: Automatic retry on network errors
- **Throttling**: Rate limiting to prevent API abuse

### Memory Management
- **Image Caching**: Album art cached with size limits
- **Queue Management**: Bounded queues for event data
- **Cleanup**: Proper resource cleanup on shutdown
- **Garbage Collection**: Automatic cleanup of old data

### Display Optimization
- **Frame Rate**: Optimized for smooth scrolling
- **Redraw Logic**: Only redraw when necessary
- **State Management**: Efficient state tracking
- **Error Recovery**: Graceful recovery from errors

## Integration Notes

This plugin is designed to work alongside other LEDMatrix plugins:

- **Weather Plugin**: Rotate between weather and music
- **News Plugin**: Show music during news breaks
- **Sports Plugin**: Display music during sports intermissions
- **Clock Plugin**: Show time and music information

## Dependencies

- **spotipy**: Spotify Web API client
- **python-socketio[client]**: Socket.IO client for YTM
- **requests**: HTTP library for API calls
- **pillow**: Image processing for album art
- **LEDMatrix**: Base plugin system and display management

## Version History

### v1.0.0
- Initial plugin release
- Migrated from `src/old_managers/music_manager.py`
- Flattened configuration structure
- Plugin system integration
- Path resolution fixes for plugin location
- Comprehensive documentation

## Support

For issues, feature requests, or questions:

1. **Check Logs**: Review plugin logs for error messages
2. **Verify Config**: Ensure configuration is correct
3. **Test Authentication**: Run auth scripts to verify setup
4. **Check Dependencies**: Ensure all required packages are installed
5. **Review Documentation**: Check this README for troubleshooting steps

## License

This plugin is licensed under the MIT License. See the LICENSE file for details.

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## Acknowledgments

- **Spotify**: For the excellent Web API
- **YTM Desktop**: For the Companion Server
- **LEDMatrix**: For the plugin system and display management
- **Community**: For feedback and contributions
