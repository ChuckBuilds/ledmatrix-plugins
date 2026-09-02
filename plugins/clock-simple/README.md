# Simple Clock

A clean time-and-date clock for your LED matrix. It picks the largest text that
fits your panel, shrinks and abbreviates when it has to, and lets you restyle
the time, the date and the AM/PM marker independently.

![The clock on a 128x32 panel showing 3:07 PM in white with PM in pale yellow,
and Wednesday over September 2nd in
orange](../../docs/assets/clock-simple/hero.png)

*Every image in this README is real plugin output, rendered at the true panel
size against a frozen clock and then scaled up so the pixels stay pixels.
Nothing here is a mockup.*

---

## Table of Contents

1. [What's On Screen](#whats-on-screen)
2. [Installation](#installation)
3. [Quick Start](#quick-start)
4. [Configuration Reference](#configuration-reference)
   - [enabled](#enabled)
   - [display_duration](#display_duration)
   - [update_interval](#update_interval)
   - [timezone](#timezone)
   - [time_format](#time_format)
   - [show_seconds](#show_seconds)
   - [center_time_with_ampm](#center_time_with_ampm)
   - [show_date](#show_date)
   - [date_format](#date_format)
   - [position_x and position_y](#position_x-and-position_y)
5. [Fonts and Colours](#fonts-and-colours)
6. [Panel Sizes and How Text Shrinks](#panel-sizes-and-how-text-shrinks)
7. [Troubleshooting](#troubleshooting)
8. [Development](#development)
9. [Support](#support)

---

## What's On Screen

Up to three elements, each styled separately:

```text
  3:07 PM      <- the time, and the AM/PM marker (12-hour mode only)
 Wednesday     <- the weekday, in the OLD_CLOCK date format only
September 2nd  <- the date
```

The weekday line is specific to the default `OLD_CLOCK` date format. The
numeric formats draw a single date line and no weekday.

---

## Installation

**From the Plugin Store (recommended).** Open the LEDMatrix web interface at
`http://<your-pi-ip>:5000`, go to **Plugin Manager**, find **Simple Clock** in
the **Plugin Store** section, and click **Install**.

**Manually.** Copy this directory into your LEDMatrix `plugin-repos/` and
restart the display service.

Note that `enabled` defaults to **`false`**, so the clock does nothing until
you switch it on — unlike most plugins in this repo.

---

## Quick Start

```json
{
  "clock-simple": {
    "enabled": true
  }
}
```

Everything else has a sensible default. A fully specified configuration:

```json
{
  "clock-simple": {
    "enabled": true,
    "display_duration": 15,
    "update_interval": 1,
    "timezone": "America/Chicago",
    "time_format": "12h",
    "show_seconds": false,
    "center_time_with_ampm": false,
    "show_date": true,
    "date_format": "OLD_CLOCK",
    "position_x": 0,
    "position_y": 0,
    "customization": {
      "time_text": { "font": "PressStart2P-Regular.ttf", "font_size": 8,
                     "text_color": [255, 255, 255] },
      "date_text": { "font": "PressStart2P-Regular.ttf", "font_size": 8,
                     "text_color": [255, 128, 64] },
      "ampm_text": { "font": "PressStart2P-Regular.ttf", "font_size": 8,
                     "text_color": [255, 255, 128] }
    }
  }
}
```

---

## Configuration Reference

| Option | Type | Default | What it does |
|--------|------|---------|--------------|
| [`enabled`](#enabled) | boolean | `false` | Whether the clock runs at all |
| [`display_duration`](#display_duration) | number | `15` | Seconds the clock holds the panel per turn |
| [`update_interval`](#update_interval) | integer | `1` | Seconds between refreshes |
| [`timezone`](#timezone) | string / null | `null` | IANA timezone, or inherit |
| [`time_format`](#time_format) | string | `12h` | `12h` or `24h` |
| [`show_seconds`](#show_seconds) | boolean | `false` | Append `:SS` |
| [`center_time_with_ampm`](#center_time_with_ampm) | boolean | `false` | Centre time and AM/PM as one block |
| [`show_date`](#show_date) | boolean | `true` | Draw the date at all |
| [`date_format`](#date_format) | string | `OLD_CLOCK` | Which date style |
| [`position_x`](#position_x-and-position_y) | integer | `0` | Horizontal nudge, in pixels |
| [`position_y`](#position_x-and-position_y) | integer | `0` | Vertical nudge, in pixels |

### `enabled`

Turns the clock on. **It defaults to `false`**, which is the single most common
reason a fresh install shows nothing.

### `display_duration`

How many seconds the clock holds the panel each time the rotation reaches it.
This does not affect accuracy — the time is re-read every frame, so it stays
correct for the whole turn however long you make it.

### `update_interval`

Seconds between refreshes, default `1`. With `show_seconds` on you want `1`;
with it off you could raise it, but there is little to gain — the plugin only
pushes pixels to the panel when the rendered image actually changes, so an
unchanged minute costs nothing either way.

### `timezone`

An IANA timezone name such as `America/Chicago`, `Europe/London` or
`Australia/Sydney`. Resolution order, first match wins:

1. `timezone` in this plugin's config
2. The global LEDMatrix `timezone` setting
3. The host system's timezone

Leave it unset on a normal install. Set it only when you want this clock to
show a *different* zone from the rest of your board — a second clock for a
remote office, for instance.

### `time_format`

`12h` (the default) draws `3:07` with a separate `PM` marker that you can
colour independently. `24h` draws `15:07` and no marker at all — the AM/PM
element simply is not used.

### `show_seconds`

Appends `:SS`, giving `3:07:09` or `15:07:09`. The string is wider, so on a
narrow panel the clock picks a smaller size to fit it.

![Four panels comparing 12-hour against 24-hour, and seconds off against
on](../../docs/assets/clock-simple/time-format.png)

### `center_time_with_ampm`

By default the time is centred on the panel and the `PM` marker sits beside it,
which means the digits stay put as the hour changes between one and two
characters. Set this to `true` to centre the time *and* the marker together as
one block — tidier at a glance, at the cost of the digits shifting slightly
when the hour rolls from `9:59` to `10:00`.

### `show_date`

Set to `false` for a time-only clock. The time is then drawn larger, since it
has the whole panel to itself.

### `date_format`

| Value | Renders as | Notes |
|-------|------------|-------|
| `OLD_CLOCK` | `Wednesday` over `September 2nd` | The default. The only format with a weekday line |
| `MM/DD/YYYY` | `09/02/2026` | US numeric |
| `DD/MM/YYYY` | `02/09/2026` | Day-first numeric |
| `YYYY-MM-DD` | `2026-09-02` | ISO 8601 |

![Six panels showing the four date formats, a time-only clock, and the centred
AM/PM variant](../../docs/assets/clock-simple/date-format.png)

`OLD_CLOCK` is the format the original LEDMatrix clock used, with a full month
name and an ordinal day. It is the widest of the four, which is what makes the
shrink-to-fit behaviour below most visible.

### `position_x` and `position_y`

Pixel offsets applied to the whole clock, both defaulting to `0`. Positive `x`
moves right, positive `y` moves down. These are for nudging the layout on a
panel where it sits slightly wrong — for centring, leave them alone, since the
clock already centres itself on the panel it is given.

---

## Fonts and Colours

Three elements are styled independently under `customization`: `time_text`,
`date_text` and `ampm_text`. Each takes `font`, `font_size` and `text_color`.

`text_color` is an `[R, G, B]` array. The defaults are deliberately not all
white — white time, orange date, pale yellow AM/PM — so the three read as
distinct at a glance.

![Four panels showing the default colours, an amber scheme, a cyan scheme and
all-white](../../docs/assets/clock-simple/colors.png)

`font` takes one of five faces:

![Five panels showing each available font rendering the same
time](../../docs/assets/clock-simple/fonts.png)

| Font | Kind | Notes |
|------|------|-------|
| `PressStart2P-Regular.ttf` | Scalable | The default; chunky 8-bit, very legible across a room |
| `4x6-font.ttf` | Scalable | Small, fits noticeably more on a line |
| `5by7.regular.ttf` | Scalable | A rounder 5×7 face |
| `5x7.bdf` | Bitmap | Crisp; always drawn at its native 7px size |
| `4x6.bdf` | Bitmap | The smallest option; native 6px |

**`font_size` only applies to the scalable `.ttf` faces.** A `.bdf` is a bitmap
font that exists at exactly one pixel size, so the plugin loads it at the size
the file declares and ignores `font_size`. That is why the two `.bdf` faces
look sharp while a `.ttf` scaled to an odd size looks soft.

---

## Panel Sizes and How Text Shrinks

The clock measures its text against the panel and steps down rather than
overflowing.

![The same clock on 64x32, 128x32, 128x64 and 256x32
panels](../../docs/assets/clock-simple/panel-sizes.png)

Two behaviours worth knowing, both visible in the 64×32 panel above:

- **The weekday abbreviates.** `Wednesday` becomes `Wed` when the full name
  will not fit.
- **The date falls back through shorter forms.** `September 2nd` becomes
  `Sep 2nd`, then `Sep 2`; the numeric formats drop to a two-digit year
  (`09/02/26`) and then to `09-02`.

The clock only shortens what it must, so a wider panel keeps the full text. On
a 128×64 panel the time and date sit in separate bands with the space between
them; on a 256×32 chain the clock centres and simply has more black around it.

---

## Troubleshooting

**Nothing appears at all.**
`enabled` defaults to `false` in this plugin. Check it is `true`.

**The time is wrong by a whole number of hours.**
That is the timezone. Check `timezone` here, then the global LEDMatrix
`timezone`, then the host clock. Remember an unset value inherits rather than
defaulting to UTC.

**The time is wrong by minutes.**
That is the Pi's system clock, not the plugin. Check `timedatectl` and that NTP
is reaching a time server.

**I picked a font and nothing changed.**
On a current version all five faces work. On older versions the two `.bdf`
options silently fell back to the default, because they were requested at
`font_size` rather than at the pixel size the file declares. If you are on an
older build, use one of the `.ttf` faces.

**The date is abbreviated and I want it in full.**
That is the fit logic — the full text does not fit at the current font size.
Use a smaller font (`4x6.bdf` or `4x6-font.ttf`), a shorter `date_format`, or a
wider panel.

**Text is cut off at an edge.**
Check `position_x` / `position_y` are `0`. The clock centres itself, so a
non-zero offset is the usual cause.

### Debug logging

The plugin logs the formatted time once a minute at INFO, and font-loading
problems at WARNING:

```bash
journalctl -t ledmatrix -f
```

A line like `Could not load font <name>@<size>` means the face was found but
could not be loaded at that size; `Font file not found` means the file is
missing from `assets/fonts/`.

---

## Development

### Plugin structure

```text
clock-simple/
├── manifest.json        # Plugin metadata and version history
├── manager.py           # ClockSimplePlugin
├── config_schema.json   # Settings schema; source of truth for defaults
├── README.md
└── LICENSE
```

Fonts are not shipped with the plugin — they come from the core's
`assets/fonts/` directory.

### Previewing a change without a panel

The fastest way to see a change is the core's dev preview server, which renders
the plugin in a browser with no hardware:

```bash
cd /path/to/LEDMatrix
python3 scripts/dev_server.py --extra-dir /path/to/ledmatrix-plugins/plugins/clock-simple
# then open http://localhost:5001
```

To render a single still frame to a PNG instead, use `scripts/render_plugin.py`
in the core — see
[docs/DEV_PREVIEW.md](https://github.com/ChuckBuilds/LEDMatrix/blob/main/docs/DEV_PREVIEW.md).

### Regenerating the images in this README

Every screenshot comes from a declarative shot list against a frozen clock, so
re-rendering is reproducible:

```bash
python scripts/render_docs_assets.py --plugin clock-simple
```

`--check` verifies the committed images still match what the plugin renders.

---

## Support

- YouTube: <https://www.youtube.com/@ChuckBuilds>
- Instagram: <https://www.instagram.com/ChuckBuilds/>
- Discord: <https://discord.com/invite/uW36dVAtcT>
- Sponsor: [GitHub Sponsors](https://github.com/sponsors/ChuckBuilds) ·
  [Buy Me a Coffee](https://buymeacoffee.com/chuckbuilds) ·
  [Ko-fi](https://ko-fi.com/chuckbuilds/)

Released under the GNU General Public License v3.0 — see [LICENSE](LICENSE).
