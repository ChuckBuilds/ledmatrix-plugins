# Geochron World Clock

A real-time "Geochron"-style world map: a high-fidelity equirectangular map
of the Earth with a live day/night terminator, smooth twilight bands, the
subsolar point, configurable city markers, and a digital clock - scaled to
fit any LED matrix panel size or shape.

**Data source:** [Natural Earth](https://www.naturalearthdata.com/) 110m
Admin-0 Countries (public domain), vendored locally - no network access
required.

---

## How it works

- The sun's subsolar point (the location on Earth where the sun is directly
  overhead) is computed from a NOAA simplified solar position algorithm,
  accurate to a fraction of a degree.
- A 720x360 equirectangular base map is rasterized once at startup from the
  vendored country outlines, then cropped/resized per panel size for crisp,
  high-resolution output regardless of matrix dimensions.
- Every `update_interval` seconds, the night side of the map is darkened and
  tinted, with smooth civil/nautical/astronomical twilight bands across the
  terminator (or a hard day/night line if bands are disabled).
- The digital clock ticks every frame for smooth seconds, independent of the
  map update cadence.

---

## Layout modes

The map and overlays adapt automatically based on panel aspect ratio:

| Aspect ratio | Mode | Layout |
|---|---|---|
| >= 3.0 (e.g. 128x32, 256x32) | Wide sidebar | Map + a sidebar with UTC time/date, local time, and subsolar coordinates |
| 1.5 - 3.0 (e.g. 64x32, 128x64) | Near bleed | Full-bleed map with a small corner time readout |
| < 1.5 (e.g. 64x64, 128x96) | Square/tall | Full-bleed map cropped to a configurable longitude band, with a corner readout |

---

## Configuration

| Option | Default | Description |
|--------|---------|-------------|
| `display_duration` | `20` | Seconds to show before rotating to the next plugin |
| `update_interval` | `45` | How often (seconds) to recompute the sun position and re-render the map |
| `timezone` | `null` | IANA timezone for the local time readout and default map centering. `null` inherits the global LEDMatrix timezone |
| `map_center_longitude` | `null` | Longitude to center on for square/tall panels. `null` auto-derives from the local timezone's UTC offset |
| `show_terminator_bands` | `true` | Smooth civil/nautical/astronomical twilight gradient vs. a hard day/night line |
| `night_brightness` | `0.20` | Brightness multiplier for the night side of the map |
| `show_grid` | `true` | Draw a lat/lon graticule |
| `graticule_step_deg` | `30` | Graticule line spacing in degrees (15/30/45/90) |
| `show_sun_marker` | `true` | Draw a marker at the subsolar point |
| `show_cities` | `true` | Draw configured city markers |
| `cities` | 8 classic cities | Up to 8 `{name, lat, lon, timezone}` entries |
| `show_digital_clock` | `true` | Show the digital time readout |
| `clock_format` | `24h` | `12h` or `24h` |
| `show_seconds` | `true` | Show seconds in the clock readout |
| `colors` | see `config_schema.json` | Ocean, land, coastline, night tint, sun marker, city marker, grid, and text colors |

---

## Default cities

| City | Timezone |
|------|----------|
| New York | America/New_York |
| Los Angeles | America/Los_Angeles |
| Rio de Janeiro | America/Sao_Paulo |
| London | Europe/London |
| Cairo | Africa/Cairo |
| Moscow | Europe/Moscow |
| Tokyo | Asia/Tokyo |
| Sydney | Australia/Sydney |

Edit, remove, or add to this list (up to 8 entries) in the plugin
configuration.

---

## Notes

- Map data is vendored at `data/world-countries.geojson` (simplified Natural
  Earth 110m countries, public domain) - the plugin makes no network calls.
- All computation is done with `numpy` over a fixed lat/lon grid, so it's
  cheap enough to run on Pi-class hardware every `update_interval` seconds.
