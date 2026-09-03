# Geochron World Clock

A real-time Geochron-style world map: an equirectangular map of the Earth with
a live day/night terminator, smooth twilight bands, the subsolar point,
configurable city markers, and a digital clock — scaled to fit any panel size
or shape.

![The world map on a 256x128 panel at 12:00 UTC, with the terminator over the
Pacific and the Atlantic, city markers, and a UTC clock in the
corner](../../docs/assets/geochron/hero.png)

*Every image in this README is real plugin output, rendered at the true panel
size against a frozen clock and then scaled up so the pixels stay pixels. The
terminator positions are what the plugin actually computes for the dates
shown.*

**Data source:** [Natural Earth](https://www.naturalearthdata.com/) 110m
Admin-0 Countries (public domain), vendored locally — **no network access
required**.

---

## Table of Contents

1. [How It Works](#how-it-works)
2. [Installation](#installation)
3. [Layout Modes](#layout-modes)
4. [Configuration Reference](#configuration-reference)
   - [The terminator](#the-terminator)
   - [The graticule](#the-graticule)
   - [Markers](#markers)
   - [The clock](#the-clock)
   - [Cities](#cities)
   - [Map centring](#map-centring)
   - [Colours](#colours)
5. [Through the Year](#through-the-year)
6. [Troubleshooting](#troubleshooting)
7. [Development](#development)
8. [Support](#support)

---

## How It Works

- The **subsolar point** — where the sun is directly overhead — is computed
  from a NOAA simplified solar position algorithm, accurate to a fraction of a
  degree.
- A **720×360 equirectangular base map** is rasterised once at startup from the
  vendored country outlines, then cropped and resized per panel size, so output
  stays crisp whatever the matrix dimensions.
- Every `update_interval` seconds the night side is darkened and tinted, with
  smooth civil, nautical and astronomical twilight bands across the terminator
  — or a hard line if bands are off.
- The **digital clock ticks every frame** for smooth seconds, independent of
  the map's update cadence. That is why `update_interval` can be generous
  without the clock stuttering.

All computation is `numpy` over a fixed lat/lon grid, cheap enough to run on
Pi-class hardware.

---

## Installation

**From the Plugin Store (recommended).** Open the LEDMatrix web interface at
`http://<your-pi-ip>:5000`, go to **Plugin Manager**, find **Geochron World
Clock** in the **Plugin Store** section, and click **Install**.

**Manually.** Copy this directory into your LEDMatrix `plugin-repos/` and
restart the display service.

`enabled` defaults to **`false`**. There is nothing else to configure — the map
data ships with the plugin and no API key or account is involved.

---

## Layout Modes

The map and overlays adapt to the panel's **aspect ratio**, not its absolute
size:

| Aspect ratio | Mode | Layout |
|--------------|------|--------|
| ≥ 3.0 (128×32, 256×32) | Wide sidebar | Map plus a sidebar with UTC time and date, local time, and subsolar coordinates |
| 1.5 – 3.0 (64×32, 128×64) | Near bleed | Full-bleed map with a small corner readout |
| < 1.5 (64×64, 128×96) | Square / tall | Full-bleed map cropped to a longitude band, with a corner readout |

![The same map on 64x32, 128x32, 128x64 and 256x128
panels](../../docs/assets/geochron/panel-sizes.png)

This plugin rewards width more than most: a 256×128 panel shows the full 360°
at a glance, while a 64-wide panel can only show a slice — which is why
[map centring](#map-centring) exists.

---

## Configuration Reference

| Option | Type | Default | What it does |
|--------|------|---------|--------------|
| `enabled` | boolean | `false` | Whether the plugin runs at all |
| `display_duration` | number | `20` | Seconds on screen before the rotation moves on |
| `update_interval` | integer | `45` | Seconds between recomputing the sun and re-rendering the map |
| `timezone` | string / null | `null` | IANA zone for the local readout and default centring; `null` inherits the global setting |
| `map_center_longitude` | number / null | `null` | Longitude to centre on for square/tall panels |
| `show_terminator_bands` | boolean | `true` | Twilight gradient, or a hard day/night line |
| `night_brightness` | number | `0.2` | Brightness multiplier for the night side |
| `show_grid` | boolean | `true` | Draw the lat/lon graticule |
| `graticule_step_deg` | integer | `30` | Graticule spacing: `15`, `30`, `45` or `90` |
| `show_sun_marker` | boolean | `true` | Marker at the subsolar point |
| `show_cities` | boolean | `true` | Markers for the configured cities |
| `cities` | array | 8 cities | Up to 8 `{name, lat, lon, timezone}` entries |
| `show_digital_clock` | boolean | `true` | The digital time readout |
| `clock_format` | string | `24h` | `12h` or `24h` |
| `show_seconds` | boolean | `true` | Seconds in the readout |
| `colors.*` | array | see below | Nine RGB colours for map and text elements |

The terminator drifts about a quarter of a degree a minute, so
`update_interval: 45` is already finer than the panel can show. Raising it to
several minutes costs nothing visible and saves CPU; the clock is unaffected
either way.

### The terminator

![The map with twilight bands and with a hard day/night
line](../../docs/assets/geochron/terminator.png)

With `show_terminator_bands` on — the default — the night side fades in through
civil, nautical and astronomical twilight, which is what makes the boundary
look like dusk rather than a cut. Turning it off draws a hard line, which is
sharper on a small panel where a gradient has only a few pixels to work in.

`night_brightness` controls how dark the night side goes:

![The map at night_brightness 0.0, 0.2, 0.5 and
1.0](../../docs/assets/geochron/night-brightness.png)

At `0.0` the night side goes black and only the terminator reads. The default
`0.2` keeps continents faintly visible. At `1.0` there is no darkening at all
and only the tint remains, which makes the day/night boundary nearly invisible
— useful only if you want the map for its own sake.

### The graticule

![The graticule at 15, 30, 45 and 90 degree spacing, and turned
off](../../docs/assets/geochron/graticule.png)

`graticule_step_deg: 15` gives one line per hour of longitude, which is
handsome on a large panel and noise on a small one. `90` leaves just the
equator and the prime meridian. All four values render distinctly.

### Markers

![The map with both markers, sun only, cities only, and
neither](../../docs/assets/geochron/markers.png)

The **subsolar point** is the yellow marker — the single place on Earth where
the sun is directly overhead at that instant. It tracks west at roughly 15° an
hour and north/south with the seasons, which is what the
[seasonal comparison](#through-the-year) below shows.

**City markers** are red dots at each configured city. Labels and local times
appear when the panel has room for them.

### The clock

![The clock in 24-hour, 12-hour, without seconds, and turned
off](../../docs/assets/geochron/clock.png)

The readout shows UTC time and date, and on a wide panel the local time and the
subsolar coordinates as well. It redraws every frame regardless of
`update_interval`, so seconds tick smoothly.

### Cities

`cities` takes up to eight entries:

```json
{
  "cities": [
    { "name": "New York", "lat": 40.71, "lon": -74.01, "timezone": "America/New_York" },
    { "name": "Tokyo",    "lat": 35.68, "lon": 139.65, "timezone": "Asia/Tokyo" }
  ]
}
```

| Key | What it does |
|-----|--------------|
| `name` | Label, shown when there is room |
| `lat` / `lon` | Decimal degrees; negative is south and west |
| `timezone` | IANA zone, used for that city's local time |

The defaults are eight well-spread cities, chosen to span the map rather than
for any other reason. Replace them with your own — these are here so you can
copy the exact timezone strings:

| City | Latitude | Longitude | Timezone |
|------|----------|-----------|----------|
| New York | `40.71` | `-74.01` | `America/New_York` |
| Los Angeles | `34.05` | `-118.24` | `America/Los_Angeles` |
| Rio de Janeiro | `-22.91` | `-43.17` | `America/Sao_Paulo` |
| London | `51.51` | `-0.13` | `Europe/London` |
| Cairo | `30.04` | `31.24` | `Africa/Cairo` |
| Moscow | `55.75` | `37.62` | `Europe/Moscow` |
| Tokyo | `35.68` | `139.65` | `Asia/Tokyo` |
| Sydney | `-33.87` | `151.21` | `Australia/Sydney` |

### Map centring

On a square or tall panel the map cannot show all 360°, so it is cropped to a
band. `map_center_longitude` picks the centre of that band:

![A 64x64 panel centred automatically, on 0, on -100 and on
140](../../docs/assets/geochron/map-centre.png)

Left at `null` it is derived from your timezone's UTC offset, which puts your
part of the world in the middle — usually what you want. Set it explicitly to
watch somewhere else. It has no effect on wide panels, which show everything
anyway.

### Colours

Nine settings under `colors`, each an `[R, G, B]` array:

| Key | Default | Colours |
|-----|---------|---------|
| `ocean_color` | `[10, 35, 90]` | Water |
| `land_color` | `[40, 110, 50]` | Land masses |
| `coastline_color` | `[90, 160, 100]` | Coastlines and country borders |
| `night_tint_color` | `[10, 10, 40]` | What the night side is tinted toward |
| `sun_marker_color` | `[255, 220, 0]` | The subsolar point |
| `city_marker_color` | `[255, 60, 60]` | City dots |
| `grid_color` | `[70, 70, 70]` | The graticule |
| `text_primary_color` | `[255, 255, 255]` | Clock and headings |
| `text_secondary_color` | `[180, 180, 180]` | Dates and labels |

Keep `coastline_color` lighter than `land_color` — the coastline is what gives
the continents their shape at small sizes, and losing the contrast turns the
map into green blobs.

---

## Through the Year

The terminator's shape is the plugin's most visible output, and it is not
decorative — it is computed, and it changes with the season:

![The map at the March equinox, June solstice, September equinox and December
solstice, all at 12:00 UTC](../../docs/assets/geochron/seasons.png)

At the **equinoxes** the terminator runs nearly pole to pole and day and night
are equal everywhere. At the **June solstice** the subsolar point sits over the
Tropic of Cancer and the Arctic never gets dark; at the **December solstice**
it is the Antarctic's turn. All four are rendered from the same code that runs
on your panel, at 12:00 UTC on the real dates.

---

## Troubleshooting

**Nothing appears.**
`enabled` defaults to `false`.

**The local time is wrong.**
`timezone` is `null` by default and inherits the global LEDMatrix setting.
Check that first, then set it here if you want this plugin to differ.

**The map is centred on the wrong part of the world.**
On a square or tall panel that is `map_center_longitude` — see
[Map centring](#map-centring). On a wide panel the whole map is shown and there
is nothing to centre.

**The day/night boundary is hard to see.**
`night_brightness` may be too high. The default is `0.2`; at `1.0` there is
effectively no darkening.

**City labels do not appear.**
They are drawn only when the panel has room. The dots are always drawn — on a
small panel that is all you get.

**The map looks like green blobs.**
Coastlines are probably too close in colour to the land. Keep
`coastline_color` clearly lighter than `land_color`.

**The seconds stutter.**
They should not — the clock redraws every frame independently of
`update_interval`. If they do, the panel's overall frame rate is the
constraint, not this setting.

---

## Development

### Project structure

```text
geochron/
├── manifest.json          # Plugin metadata and version history
├── manager.py             # GeochronPlugin — config, layout modes, overlays
├── geochron_renderer.py   # The drawing, shared with render_preview.py
├── solar.py               # Subsolar point and twilight bands
├── worldmap.py            # Rasterises the vendored country outlines
├── data/                  # Natural Earth 110m countries (public domain)
├── render_preview.py      # Standalone preview generator
├── config_schema.json     # Settings schema; source of truth for defaults
└── test/
```

`render_preview.py` imports `geochron_renderer` — the same module `manager.py`
draws with — so its previews cannot disagree with the plugin. That is worth
copying if you add a preview generator elsewhere: share the renderer rather
than keeping a second copy of the drawing code.

### Regenerating the images in this README

```bash
python scripts/render_docs_assets.py --plugin geochron
```

`--check` verifies the committed images still match. The clock is frozen in the
shot list, which is what pins the terminator — without that every image would
change by the minute.

---

## Support

- YouTube: <https://www.youtube.com/@ChuckBuilds>
- Instagram: <https://www.instagram.com/ChuckBuilds/>
- Discord: <https://discord.com/invite/uW36dVAtcT>
- Sponsor: [GitHub Sponsors](https://github.com/sponsors/ChuckBuilds) ·
  [Buy Me a Coffee](https://buymeacoffee.com/chuckbuilds) ·
  [Ko-fi](https://ko-fi.com/chuckbuilds/)

Released under the GNU General Public License v3.0 — see [LICENSE](LICENSE).
