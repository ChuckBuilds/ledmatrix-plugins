# BirdNET-Go Plugin

Show what [BirdNET-Go](https://github.com/tphakala/birdnet-go) is hearing on your LED matrix, across two screens:

- **`birdnet_go`** — the latest identified bird: common name, scientific name, confidence, time since detection, and a species photo
- **`birdnet_stats`** — today's totals: species count, detection count, and the most-heard species with their counts

Everything comes from BirdNET-Go's REST API by polling. MQTT is optional and only buys sub-second pop-ups.

## Features

- No broker required — point it at your BirdNET-Go URL and it works
- Cycles a different species each turn, so a loud yard doesn't show the same bird every slot
- Size-adaptive layouts: a third line and larger type on tall panels, graceful degradation down to 64x32
- Species photos pulled on demand and cached for 30 days
- Three detection behaviours: `rotation`, `interrupt`, or `both`
- Configurable confidence threshold to filter noisy detections
- Optional MQTT push with auto-reconnect and exponential backoff
- Defensive payload parsing — tolerates `CommonName` / `commonName` / `common_name` and decimal-or-percent confidence
- Optional field mapping for unusual BirdNET-Go forks

## Quick start

The only setting that matters is your BirdNET-Go address:

```json
"birdnet-go": {
  "enabled": true,
  "birdnet_api": {
    "base_url": "http://birdnet-go.local:8080"
  },
  "display": {
    "mode": "rotation",
    "min_confidence": 0.6
  }
}
```

Then `sudo systemctl restart ledmatrix`. Both screens join the rotation.

Find your base URL by opening the BirdNET-Go web UI and copying scheme, host and port — no path. Verify it from the LED matrix host:

```bash
curl "http://<birdnet-host>:<port>/api/v2/health"
```

A healthy instance returns JSON containing `"status":"healthy"`.

Full option reference: see `config_schema.json`.

## Display modes

Two rotation entries, enabled independently.

`birdnet_go` shows the latest bird. Its behaviour is set by `display.mode`:

- **`rotation`** — renders the last detected bird during its rotation slot; nothing pops up mid-rotation
- **`interrupt`** — stays silent during rotation; new detections interrupt the current display for `interrupt_duration` seconds
- **`both`** (default) — rotation slot *and* interrupt on new detections

If more than `stale_after_minutes` pass without a detection, the slot shows "No recent birds".

`birdnet_stats` shows today's numbers. Turn it off with `"stats": {"enabled": false}` and its rotation slot is skipped. `stats.top_n` caps how many species are kept; the panel renders as many as physically fit, so a short panel shows fewer without any config change.

Interrupts only fire for a bird heard within the last couple of poll intervals. Polling surfaces old detections at startup, and popping those over the rotation is just noise.

## Species cycling

Showing "the latest bird" sounds right until you look at a real feed. A yard with 200 Fish Crow and 260 Blue Jay calls a day is one of those two almost every time you glance at the panel, and the other nine species never appear.

So by default the `birdnet_go` screen cycles: one distinct species per rotation slot, moving to the next species on the next slot. Each card carries that species' count for the day, so you get the frequency ranking as you watch rather than only on the stats screen.

```json
"display": {
  "unique_species": true,
  "max_species": 8,
  "species_order": "recent",
  "show_today_count": true
}
```

- **`species_order: "recent"`** (default) — most recently heard species first, so the panel reflects what's outside now
- **`species_order: "frequency"`** — most-heard species first, a running top-N countdown
- **`unique_species: false`** — the old behaviour: always show whatever called last

The cycle is built from today's per-species analytics, not the raw detection stream — `/detections/recent` caps at ten rows, which on a busy feed is often a single species. That does mean the cycle only covers species heard *today*; early in the morning it's short, and it grows as the day goes on.

Interrupt pop-ups always show the bird that just called, never the cycle's current card — an interrupt that showed some other species would defeat the point.

## How data is fetched

Every `birdnet_api.poll_interval` seconds (default 60) the plugin calls:

| Endpoint | Used for |
| --- | --- |
| `/api/v2/detections/recent` | the latest bird above `min_confidence` |
| `/api/v2/analytics/species/daily` | today's per-species counts |
| `/api/v2/media/species-image?name=<scientific_name>` | the species photo |

Photos are cached in memory and on disk for 30 days, keyed by scientific name; failed lookups are remembered for the session so we don't hammer the API. If the image endpoint is unreachable the layout falls back to text-only.

Polling keeps running even when MQTT is enabled, so a broker outage can't freeze the display.

## Optional: MQTT for instant pop-ups

Polling means a new bird appears within one `poll_interval`. If you want it on screen the moment it's heard, and BirdNET-Go is already publishing to a broker, enable MQTT. It supplements polling rather than replacing it.

Most people running BirdNET-Go alongside Home Assistant already have the **Mosquitto broker** add-on installed.

### 1. Create a dedicated MQTT user in Home Assistant

1. **Settings → People → Users → Add User**
2. Name it something like `ledmatrix` (not an admin, just a regular user)
3. Set a password — you'll paste this into the plugin config

The Mosquitto add-on authenticates against HA's user list by default, so no extra broker config is needed.

### 2. Find your broker's address and port

- **Host**: the LAN IP or hostname of the machine running Home Assistant (e.g. `192.168.1.10`). Don't use `localhost` unless the LED matrix runs on the HA host itself.
- **Port**: `1883` (plain) is the default. TLS on 8883 is not supported, so stick with 1883 on your LAN.

### 3. Configure BirdNET-Go to publish

In BirdNET-Go's web UI (**Settings → Integrations → MQTT**):
- Broker URL: `tcp://<ha-ip>:1883`
- Username / Password: the user you just made
- Topic: `birdnet` (any topic works, it just has to match the plugin)
- Enable the integration and restart BirdNET-Go

Verify from any machine on the LAN:
```bash
mosquitto_sub -h <ha-ip> -p 1883 -u ledmatrix -P <password> -t 'birdnet/#' -v
```

### 4. Turn it on in the plugin

```json
"mqtt": {
  "enabled": true,
  "host": "192.168.1.10",
  "port": 1883,
  "username": "ledmatrix",
  "password": "REPLACE_ME",
  "topic": "birdnet"
}
```

`paho-mqtt` must be installed (it's in `requirements.txt`). If it's missing, the plugin logs an error and falls back to polling rather than failing to load.

### 5. Confirm it connected

```bash
sudo journalctl -u ledmatrix -f | grep -i birdnet
```

You should see `Connected to MQTT broker` and `Subscribed to topic: birdnet`.

## Troubleshooting

- **Nothing appears** — check `curl "<base_url>/api/v2/health"` from the LED matrix host, and that `min_confidence` isn't set too high. Detections below it are logged at debug as "Dropping low-confidence detection".
- **"No bird stats"** — the daily analytics call failed or returned nothing. Check `curl "<base_url>/api/v2/analytics/species/daily"`; an empty array is normal before the first detection of the day.
- **Name but no photo** — `curl "<base_url>/api/v2/media/species-image?name=Cardinalis%20cardinalis"` should return an image.
- **Time-ago looks wrong** — the plugin uses the detection's own timestamp when BirdNET-Go supplies a full ISO-8601 one, and falls back to arrival time otherwise.
- **MQTT connects but nothing shows** — enable debug logging to see the raw payload, then override the relevant key under `field_mapping`.

## Display modes supported

`birdnet_go`, `birdnet_stats`
