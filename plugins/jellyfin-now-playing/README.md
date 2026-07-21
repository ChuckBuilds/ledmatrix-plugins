# Jellyfin Now Playing

Shows what's currently playing on your Jellyfin media server: the poster on the
left, with the title, a subtitle, and a playback progress bar on the right.

- **Movies** show the movie poster with the title and the watching user's name.
- **TV episodes** show the *series* poster with the episode title and series name.
- **Music** shows the album art with the track title and artist.
- Long titles scroll as a marquee (or truncate with `...` if scrolling is disabled).
- The progress bar moves smoothly between polls and turns **amber with a ⏸
  indicator** while playback is paused.
- When nothing is playing, a dim "Nothing Playing" screen is shown.
- Works on all supported panel sizes (64×32, 128×32, 128×64, 256×32). Wide and
  tall panels also get a `position / duration` time readout.

## Setup

### 1. Get a Jellyfin API key

1. Open your Jellyfin web UI as an administrator.
2. Go to **Dashboard → Advanced → API Keys**.
3. Click **+**, name the key (e.g. `LEDMatrix`), and copy the generated key.

### 2. Configure the plugin

| Setting | Description |
|---|---|
| `jellyfin_url` | Your server's base URL, e.g. `http://192.168.1.50:8096` (or your reverse-proxy HTTPS URL). |
| `api_key` | The API key from step 1. Stored as a secret and only ever sent to your own server. |

Until both are set, the panel shows `Jellyfin: Set URL/API Key`.

## Configuration reference

| Key | Default | Description |
|---|---|---|
| `enabled` | `false` | Enable the plugin |
| `display_duration` | `15` | Seconds the screen is shown per rotation |
| `jellyfin_url` | `http://localhost:8096` | Jellyfin server base URL |
| `api_key` | — | Jellyfin API key (secret) |
| `username` | `""` | Only show sessions for this user; empty shows any user's session |
| `content_types` | Movie, Episode, Audio | Which media types are shown |
| `show_progress` | `true` | Draw the playback progress bar |
| `show_paused` | `true` | Keep showing paused sessions (off treats paused as nothing playing) |
| `update_interval` | `10` | Seconds between session polls (advanced) |
| `scroll_enabled` | `true` | Marquee-scroll text that doesn't fit |
| `scroll_speed` | `5` | Frames per one-character scroll step; higher is slower (advanced) |
| `scroll_separator` | `"   "` | Gap text between marquee repetitions (advanced) |
| `customization` | — | Fonts, sizes, and colors for the title, subtitle, and progress bar |

## Multiple sessions

If several people are streaming at once, the plugin picks one session:

1. Sessions without media, filtered-out users, and filtered-out content types
   are ignored (paused sessions too, if `show_paused` is off).
2. Actively **playing** sessions are preferred over paused ones.
3. Ties keep the server's order.

Set `username` to pin the display to one account.

## Troubleshooting

| Panel says | Meaning |
|---|---|
| `Jellyfin: Set URL/API Key` | `jellyfin_url` or `api_key` isn't configured yet. |
| `Jellyfin: Update API Key` | The server rejected the key (revoked or mistyped). Create a new one. |
| `Jellyfin: Unreachable` | Wrong URL, server down, or a firewall is blocking the LEDMatrix host. |
| `Nothing Playing` | No client is actively streaming (sessions idle longer than ~60s don't count). |
| Series poster instead of an episode still | By design — episodes show the show's poster, which reads far better at 21–42 px wide. |
| Gray placeholder instead of a poster | The item has no primary image, or the image fetch failed; the text still shows. |

## Privacy

The API key is stored via the LEDMatrix secrets store (`x-secret`) and is only
sent to the Jellyfin server you configure — no third-party services are involved.
