# 7-Segment Clock

A retro seven-segment clock for LEDMatrix. It draws the current time from a set
of bitmap digit assets, recolours them to whatever hex colour you pick, and
scales the whole thing to fit whatever panel you have — from a single 64×32 up
to a long 256×32 chain.

![The 7-segment clock on a 128x32 panel showing 16:47 in white
digits](../../docs/assets/7-segment-clock/hero.png)

*Every image in this README is real plugin output, rendered at the true panel
size and then scaled up so the pixels stay pixels. Nothing here is a mockup.*

---

## Table of Contents

1. [How It Works](#how-it-works)
2. [Installation](#installation)
3. [Quick Start](#quick-start)
4. [Configuration Reference](#configuration-reference)
   - [enabled](#enabled)
   - [display_duration](#display_duration)
   - [location.timezone](#locationtimezone)
   - [is_24_hour_format](#is_24_hour_format)
   - [has_leading_zero](#has_leading_zero)
   - [has_flashing_separator](#has_flashing_separator)
   - [digit_spacing](#digit_spacing)
   - [color](#color)
5. [Panel Sizes and Auto-Scaling](#panel-sizes-and-auto-scaling)
6. [Troubleshooting](#troubleshooting)
7. [Development](#development)
8. [License and Credits](#license-and-credits)

---

## How It Works

The plugin ships eleven small bitmaps in `assets/images/`: one per digit
(13×32 pixels) plus a colon separator (4×14 pixels). A lit segment is a white
pixel in the bitmap; everything else is black.

On each frame the plugin:

1. Reads the current time in the configured timezone.
2. Formats it as `HH:MM` or `H:MM` according to your format settings.
3. Works out a scale factor that makes the whole string fit the panel.
4. Recolours each digit to your configured `color` and pastes it onto the
   panel, centred both horizontally and vertically.

There is no network access and no cache — the plugin only needs the system
clock, so it starts instantly and never shows stale data.

```text
system clock ──► timezone conversion ──► "16:47" ──► scale to panel ──► recolour ──► draw
```

---

## Installation

### From the Plugin Store (recommended)

1. Open the LEDMatrix web interface at `http://<your-pi-ip>:5000`.
2. Go to the **Plugin Manager** tab.
3. Find **7-Segment Clock** in the **Plugin Store** section and click
   **Install**.
4. Enable it and set the options from the generated settings form.

### Manual installation

```bash
cp -r ledmatrix-plugins/plugins/7-segment-clock /path/to/LEDMatrix/plugin-repos/
pip install -r /path/to/LEDMatrix/plugin-repos/7-segment-clock/requirements.txt
```

Then add the plugin to `config/config.json` and restart LEDMatrix.

---

## Quick Start

The smallest useful configuration is just `enabled`. Everything else has a
sensible default:

```json
{
  "7-segment-clock": {
    "enabled": true
  }
}
```

A fully specified configuration looks like this:

```json
{
  "7-segment-clock": {
    "enabled": true,
    "display_duration": 15,
    "location": {
      "timezone": "US/Eastern"
    },
    "is_24_hour_format": true,
    "has_leading_zero": false,
    "has_flashing_separator": true,
    "digit_spacing": 2,
    "color": "#FFFFFF"
  }
}
```

You can edit the same values from the web UI — the settings form is generated
from `config_schema.json`, which is the source of truth for defaults.

---

## Configuration Reference

| Option | Type | Default | Range | What it does |
|--------|------|---------|-------|--------------|
| [`enabled`](#enabled) | boolean | `true` | — | Whether the clock takes a turn in the rotation |
| [`display_duration`](#display_duration) | number | `15` | 5–300 | Seconds the clock stays on screen per turn |
| [`location.timezone`](#locationtimezone) | string | *inherited* | any tz name | Timezone to show the time in |
| [`is_24_hour_format`](#is_24_hour_format) | boolean | `true` | — | 24-hour clock, or 12-hour when `false` |
| [`has_leading_zero`](#has_leading_zero) | boolean | `false` | — | Pad single-digit hours with a zero |
| [`has_flashing_separator`](#has_flashing_separator) | boolean | `true` | — | Blink the colon once per second |
| [`digit_spacing`](#digit_spacing) | number | `2` | 0–10 | Pixel gap between digits |
| [`color`](#color) | string | `"#FFFFFF"` | hex colour | Colour of the lit segments |

### `enabled`

Turns the plugin on or off. When `false`, the clock is skipped in the display
rotation and consumes no time on the panel.

```json
{"7-segment-clock": {"enabled": true}}
```

### `display_duration`

How many seconds the clock holds the panel each time the rotation reaches it.
Accepts 5 to 300 seconds; the default of 15 keeps a busy rotation moving.

If you want the clock to be the main event, raise it:

```json
{"7-segment-clock": {"display_duration": 60}}
```

This does not change how often the time updates — the time is re-read every
frame, so the display stays correct for the whole duration.

### `location.timezone`

An IANA / `pytz` timezone name such as `US/Eastern`, `Europe/Berlin`,
`Australia/Sydney`, or `UTC`.

The timezone is resolved in this order, first match wins:

1. `location.timezone` in this plugin's configuration.
2. The `timezone` value in your main LEDMatrix `config/config.json`.
3. `UTC`, as a last resort.

So on a normal install you should leave this unset and let the clock inherit
your panel's timezone. Set it only when you want this clock to show a
*different* zone from the rest of the display — a second clock for a remote
office, for example.

```json
{"7-segment-clock": {"location": {"timezone": "Europe/Berlin"}}}
```

An unrecognised timezone name is not fatal: the plugin logs a warning and falls
back to UTC.

### `is_24_hour_format`

Chooses between a 24-hour clock (`true`, the default) and a 12-hour clock
(`false`). There is no AM/PM indicator — the digit set has no room for one — so
12-hour mode shows `4:47` for both 04:47 and 16:47.

### `has_leading_zero`

Controls whether an hour below ten is padded with a zero. It applies to both
formats: `09:05` versus `9:05` in 24-hour mode, `04:47` versus `4:47` in
12-hour mode. Minutes are always zero-padded.

Turning the leading zero off makes the remaining digits render larger, because
the string is one digit narrower and the auto-scaler has more room to work
with.

![Four panels comparing 24-hour against 12-hour format, and a leading zero
against no leading zero](../../docs/assets/7-segment-clock/time-formats.png)

| `is_24_hour_format` | `has_leading_zero` | 09:05 shows as | 16:47 shows as |
|---------------------|--------------------|----------------|----------------|
| `true` (default) | `false` (default) | `9:05` | `16:47` |
| `true` | `true` | `09:05` | `16:47` |
| `false` | `false` | `9:05` | `4:47` |
| `false` | `true` | `09:05` | `04:47` |

### `has_flashing_separator`

When `true` (the default) the colon blinks in step with the seconds: lit on
even seconds, blanked on odd ones. This is the classic digital-clock heartbeat,
and it doubles as a quiet "the panel has not frozen" indicator.

Set it to `false` to keep the colon permanently lit.

![The same clock on an even second with the colon lit, and on an odd second
with the colon blanked](../../docs/assets/7-segment-clock/separator.png)

The digits do not shift when the colon disappears — the separator keeps its
slot either way, so nothing jumps around.

### `digit_spacing`

The gap, in panel pixels, inserted between every element of the time string
(including either side of the colon). Accepts 0 to 10; the default is 2.

The gap is scaled along with the digits, so `digit_spacing: 2` on a panel where
the clock renders at 1.8× actually leaves a 3-pixel gap.

![Six panels comparing digit_spacing values of 0, 2, 6 and 10 on a 128x32
panel, plus spacing 2 and 10 on a 64x32
panel](../../docs/assets/7-segment-clock/digit-spacing.png)

**One caveat worth knowing.** The auto-scaler sizes the digits from the width
of the digits alone — it does not account for the spacing you add on top. On a
wide panel that is harmless. On a narrow one it is not: as the bottom row above
shows, `digit_spacing: 10` on a 64×32 panel pushes the outer digits off both
edges. If you are on a 64-wide panel, keep `digit_spacing` at 4 or below, or
turn off the leading zero to buy back a digit's width.

### `color`

The colour of the lit segments, as a hex string. Both `#RGB` and `#RRGGBB`
forms are accepted, and the leading `#` is optional. Unlit segments are always
black — this is an LED panel, so "black" means the LED is off.

![Four panels showing the clock in white, amber, red and
cyan](../../docs/assets/7-segment-clock/colors.png)

```json
{"7-segment-clock": {"color": "#FFA500"}}
```

Some colours worth knowing:

| Value | Look | Good for |
|-------|------|----------|
| `#FFFFFF` | White | Maximum brightness and contrast; the default |
| `#FFA500` | Amber | The classic clock-radio look |
| `#FF0000` | Red | The least disruptive colour in a dark room |
| `#00E5FF` | Cyan | Stands out against warm-coloured walls |
| `#33FF33` | Green | Vintage VFD / terminal look |

A malformed colour is not fatal: the plugin logs a warning and falls back to
white.

---

## Panel Sizes and Auto-Scaling

The clock has no fixed size. On every frame it computes a scale factor:

```text
scale = min( (panel_width  * 0.9) / total_digit_width,
             (panel_height * 0.9) / 32 )

clamped to the range 0.5 – 3.0
```

The 0.9 leaves a 5% margin on each side, and `32` is the native height of the
digit bitmaps. Because panel height is usually the binding constraint, a 32-pixel
tall panel renders the digits at 0.9×, and a 64-pixel tall panel renders them
close to 1.8×.

![The same 16:47 rendered on 64x32, 128x32, 128x64 and 256x32
panels](../../docs/assets/7-segment-clock/panel-sizes.png)

A few consequences that are easier to see than to describe:

- **Width rarely matters.** On a 256×32 chain the clock is capped by height, so
  it renders at the same size as on 128×32 and simply sits centred in a wider
  field of black. If you want a big clock, add rows, not columns.
- **A 64×32 panel is tight.** Four digits plus a colon barely fit. Keeping
  `has_leading_zero` off and `digit_spacing` low is what makes it work.
- **The digits are resampled.** Because the assets are 32 pixels tall and are
  almost always drawn at some non-integer scale, the segment edges are smoothed
  rather than hard. On a real panel this reads as a slight glow at the segment
  ends.

---

## Troubleshooting

**The panel stays black when the clock's turn comes round.**
Check that `enabled` is `true`, and that `assets/images/` contains
`number_0.png` through `number_9.png` plus `separator.png`. If the assets are
missing the plugin logs an error per missing file at startup:

```bash
journalctl -t ledmatrix -f
```

**The time is wrong by a whole number of hours.**
This is almost always the timezone rather than the clock. Confirm what the
plugin resolved to by checking, in order, `location.timezone` here, then
`timezone` in the main LEDMatrix config. Remember that leaving both unset
means UTC.

**The time is wrong by minutes.**
That is the Pi's system clock, not the plugin. Check `timedatectl` and that NTP
is reaching a time server.

**The outer digits are cut off.**
See the caveat under [`digit_spacing`](#digit_spacing) — reduce the spacing, or
move to a wider panel.

**The colon is missing.**
If it is missing only some of the time, that is
[`has_flashing_separator`](#has_flashing_separator) working as designed. If it
is missing permanently, check that `assets/images/separator.png` exists.

---

## Development

### File structure

```text
7-segment-clock/
├── manifest.json             # Plugin metadata and version history
├── manager.py                # SevenSegmentClockPlugin
├── config_schema.json        # Settings schema; source of truth for defaults
├── requirements.txt          # pytz
├── test_render_polarity.py   # Regression test for digit rendering
├── README.md
├── LICENSE
└── assets/
    └── images/
        ├── number_0.png … number_9.png   # 13x32 digit bitmaps
        └── separator.png                 # 4x14 colon
```

### Running the render test

The digit bitmaps encode a lit segment as a *bright* pixel. Getting that
polarity backwards produces either a completely blank panel or solid blocks
instead of digits, and neither failure raises an exception — so there is a
standalone regression test:

```bash
cd plugins/7-segment-clock
python test_render_polarity.py
```

### Regenerating the images in this README

Every screenshot above is produced from a declarative shot list at
`docs/assets/7-segment-clock/shots.json`, against a frozen clock so the output
is reproducible:

```bash
python scripts/render_docs_assets.py --plugin 7-segment-clock
```

---

## License and Credits

Released under the GNU General Public License v3.0 — see [LICENSE](LICENSE).

- Original Big Clock applet: [TronbyT Apps](https://github.com/tronbyt/apps)
- Digit bitmaps sourced from the TronbyT repository
- Adapted for the LEDMatrix plugin system
