# BirdNET-Go Plugin

Subscribe to a [BirdNET-Go](https://github.com/tphakala/birdnet-go) MQTT feed and display the most recently identified bird on your LED matrix — common name, confidence, time since detection, and a species image fetched from BirdNET-Go's built-in media API.

## Features

- MQTT subscription with auto-reconnect and exponential backoff
- Two-line layout: scrolling bird name + confidence/time-ago
- Species images pulled on demand from BirdNET-Go and cached for 30 days
- Three display modes: `rotation`, `interrupt`, or `both`
- Configurable confidence threshold to filter noisy detections
- Defensive payload parsing — tolerates `CommonName` / `commonName` / `common_name` and decimal-or-percent confidence
- Optional field mapping for unusual BirdNET-Go forks

## Configuration

Minimum example:

```json
{
  "enabled": true,
  "mqtt": {
    "host": "192.168.1.10",
    "port": 1883,
    "username": "user",
    "password": "pass",
    "topic": "birdnet/detections"
  },
  "birdnet_api": {
    "base_url": "http://birdnet-go.local:8080"
  },
  "display": {
    "mode": "both",
    "min_confidence": 0.6
  }
}
```

Full option reference: see `config_schema.json`.

### Display modes

- **`rotation`** — plugin renders the last detected bird during its rotation slot; nothing pops up mid-rotation.
- **`interrupt`** — plugin stays silent during rotation; new detections interrupt the current display for `interrupt_duration` seconds.
- **`both`** (default) — rotation slot shows the last bird, *and* new detections interrupt immediately.

If more than `stale_after_minutes` pass without a detection, the rotation slot shows "No recent birds" instead.

## Configuring MQTT with the Home Assistant broker

Most people running BirdNET-Go alongside Home Assistant already have the **Mosquitto broker** add-on installed in HA. This plugin connects to that same broker — BirdNET-Go publishes detections, and this plugin subscribes.

### 1. Create a dedicated MQTT user in Home Assistant

Sharing your personal HA account's MQTT credentials works but is messy. Create a separate user for the LED matrix:

1. In Home Assistant: **Settings → People → Users → Add User**
2. Name it something like `ledmatrix` (not an admin, just a regular user)
3. Set a password — you'll paste this into the plugin config

The Mosquitto add-on authenticates against HA's user list by default, so no extra broker config is needed.

### 2. Find your broker's address and port

- **Host**: the LAN IP or hostname of the machine running Home Assistant (e.g. `192.168.1.10` or `homeassistant.local`). Don't use `localhost` unless the LED matrix is running on the HA host itself.
- **Port**: `1883` (plain) is the default. If you've enabled TLS on Mosquitto, use `8883` — note this plugin does not currently support TLS, so stick with 1883 on your LAN.

### 3. Configure BirdNET-Go to publish to the broker

In BirdNET-Go's web UI (**Settings → Integrations → MQTT**):
- Broker URL: `tcp://<ha-ip>:1883`
- Username / Password: the `ledmatrix` user you just made (or a separate `birdnet` user — the plugin doesn't care who publishes)
- Topic: `birdnet` (this is what the plugin defaults to; can be any topic you want, just make it match)
- Enable the integration and restart BirdNET-Go

Verify it works from any machine on the LAN:
```bash
mosquitto_sub -h <ha-ip> -p 1883 -u ledmatrix -P <password> -t 'birdnet/#' -v
```
When a bird is detected you'll see a JSON payload print out.

### 4. Fill in the plugin config

Via the LEDMatrix web UI (easier): open the BirdNET-Go plugin's settings panel and paste:

| Field | Value |
| --- | --- |
| `mqtt.host` | HA broker IP, e.g. `192.168.1.10` |
| `mqtt.port` | `1883` |
| `mqtt.username` | `ledmatrix` |
| `mqtt.password` | the password you set in step 1 |
| `mqtt.topic` | `birdnet` (same as BirdNET-Go) |
| `birdnet_api.base_url` | `http://<birdnet-host>:8080` |

Or edit `config/config.json` directly:

```json
"birdnet-go": {
  "enabled": true,
  "mqtt": {
    "host": "192.168.1.10",
    "port": 1883,
    "username": "ledmatrix",
    "password": "REPLACE_ME",
    "topic": "birdnet"
  },
  "birdnet_api": {
    "base_url": "http://birdnet-go.local:8080"
  }
}
```
Then `sudo systemctl restart ledmatrix`.

### 5. Confirm the plugin connected

```bash
sudo journalctl -u ledmatrix -f | grep -i birdnet
```
You should see `Connected to MQTT broker` and `Subscribed to topic: birdnet`. If not, check:
- broker IP reachable from the Pi (`ping <ha-ip>`)
- username/password correct (try `mosquitto_sub` from the Pi with the same creds)
- the HA Mosquitto add-on is running and listening on 1883

The plugin tolerates the common BirdNET-Go payload shapes (`CommonName` / `commonName` / `common_name`). If your fork publishes with different keys, override them via `field_mapping`.

## How images are fetched

The plugin calls `GET {birdnet_api.base_url}/api/v2/media/species-image?name=<scientific_name>` in the background after each new detection. Results are cached in memory and in the LEDMatrix cache for 30 days, keyed by scientific name. Failed lookups are remembered for the session so we don't hammer the API.

If `birdnet_api.base_url` is empty or the endpoint returns non-200, the plugin falls back to text-only layout.

## Troubleshooting

- **Nothing appears** — verify broker connectivity (`mosquitto_sub -h <host> -t 'birdnet/#' -v`) and that `min_confidence` isn't set too high. Check plugin logs for "Dropping low-confidence detection".
- **Name but no image** — check `birdnet_api.base_url` is reachable from the LEDMatrix host. `curl "<base_url>/api/v2/media/species-image?name=Cardinalis%20cardinalis"` should return an image.
- **Wrong field parsed** — enable debug logging to see the raw payload, then override the relevant key under `field_mapping`.

## Display modes supported

`birdnet_go`
