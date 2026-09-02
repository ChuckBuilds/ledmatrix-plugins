# Countdown

Count down to the things you care about — birthdays, holidays, a holiday, a
launch — or count up from a date that has passed. Each countdown gets a name, a
target, an optional image, and its own styling, and the plugin rotates through
however many you configure.

![A countdown to Christmas on a 128x32 panel: a gift image on the left, the
name and "113 Days" on the right](../../docs/assets/countdown/hero.png)

*Every image in this README is real plugin output, rendered at the true panel
size against a frozen clock so the figures are reproducible. The gift icon is a
plain sample standing in for your own image.*

---

## Table of Contents

1. [What's On Screen](#whats-on-screen)
2. [Installation](#installation)
3. [Quick Start](#quick-start)
4. [How the Countdown Value Is Written](#how-the-countdown-value-is-written)
5. [Per-Countdown Settings](#per-countdown-settings)
   - [Layout presets](#layout-presets)
   - [Text alignment](#text-alignment)
   - [until and since](#until-and-since)
   - [Per-countdown overrides](#per-countdown-overrides)
6. [Global Settings](#global-settings)
   - [Fonts and colours](#fonts-and-colours)
   - [Images](#images)
7. [Panel Sizes](#panel-sizes)
8. [Troubleshooting](#troubleshooting)
9. [Development](#development)
10. [Support](#support)

---

## What's On Screen

One countdown at a time, drawn as an optional image beside two lines of text:

```text
┌──────────────────────────────┐
│          │   Countdown name  │
│  IMAGE   │                   │
│  (1/3)   │     113 Days      │
└──────────────────────────────┘
```

With several countdowns configured the plugin rotates through them in
`display_order`, holding each for `display_duration` seconds.

---

## Installation

**From the Plugin Store (recommended).** Open the LEDMatrix web interface at
`http://<your-pi-ip>:5000`, go to **Plugin Manager**, find **Countdown Display**
in the **Plugin Store** section, and click **Install**. Countdowns are managed
from the plugin's own tab.

**Manually.** Copy this directory into your LEDMatrix `plugin-repos/` and
restart the display service.

---

## Quick Start

A countdown needs only a `name` and a `target_date` — those two are the schema's
only required fields:

```json
{
  "countdown": {
    "enabled": true,
    "countdowns": [
      { "name": "Christmas", "target_date": "2026-12-25" }
    ]
  }
}
```

Several countdowns, with images and ordering:

```json
{
  "countdown": {
    "enabled": true,
    "display_duration": 15,
    "countdowns": [
      {
        "name": "Christmas",
        "target_date": "2026-12-25",
        "image_path": "assets/countdown/tree.png",
        "layout_preset": "image-left",
        "display_order": 1
      },
      {
        "name": "Doors Open",
        "target_date": "2026-09-02",
        "target_time": "21:30",
        "layout_preset": "text-only",
        "display_order": 2
      },
      {
        "name": "Launched",
        "target_date": "2026-04-07",
        "mode": "since",
        "display_order": 3
      }
    ]
  }
}
```

---

## How the Countdown Value Is Written

The second line adapts to how close the event is. It is **not** always a day
count, and there is no separate "today" state:

| Time to target | Renders as | Example |
|----------------|------------|---------|
| More than 2 days | `N Days` | `113 Days` |
| 1 to 2 days | `Tomorrow` | *(no number at all)* |
| 1 to 24 hours | `Nh Nm` | `10h 30m` |
| 1 to 60 minutes | `Nm` | `30m` |
| Under a minute | `NOW!` | |
| Already passed | `Nd ago` | `3d ago` |

![Six panels showing each rung of that ladder: 113 Days, Tomorrow, 10h 30m,
30m, NOW! and 3d ago](../../docs/assets/countdown/count-formats.png)

Two consequences worth knowing:

- **The hours-and-minutes rungs only appear if you set `target_time`.** Without
  it the target is midnight, so an event "today" is already in the past by the
  time anyone is looking at the panel. Set `target_time` for anything where the
  hour matters.
- **A passed countdown is hidden by default.** `Nd ago` is only ever visible
  with [`show_expired`](#global-settings) turned on.

In `since` mode the same granularity applies with elapsed wording: `Just now`,
`Nm ago`, `Nh Nm ago`, `N Days ago`.

---

## Per-Countdown Settings

Each object in the `countdowns` array takes these:

| Key | Type | Default | What it does |
|-----|------|---------|--------------|
| `name` | string | *required* | The label on the top line |
| `target_date` | string | *required* | `YYYY-MM-DD`. The date to count to, or from in `since` mode |
| `target_time` | string | `"00:00"` | `HH:MM`, 24-hour. Gives sub-day precision — see the table above |
| `enabled` | boolean | `true` | Include this entry in the rotation |
| `mode` | string | `until` | `until` counts down; `since` counts up |
| `layout_preset` | string | `image-left` | `image-left`, `image-right`, `text-only`, `image-only` |
| `text_align` | string | `center` | `left`, `center`, `right` — within the text area |
| `image_path` | string / null | `null` | Image to show beside the text |
| `display_order` | integer | `0` | Rotation order; lower goes first |
| `id` | string | *auto* | Unique identifier, generated for you |
| `layout` | object / null | `null` | Pixel position and size overrides |
| `style` | object / null | `null` | Per-entry font and colour overrides |

### Layout presets

![Four panels showing image-left, image-right, text-only and
image-only](../../docs/assets/countdown/layout-presets.png)

`text-only` ignores any `image_path` you have set rather than erroring, so you
can switch a countdown to text without deleting its image. `image-only` draws
no name and no value — useful as a static picture in the rotation.

### Text alignment

`text_align` positions the name and value inside the text area, which is the
whole panel under `text-only` and the remaining two thirds otherwise.

![Three panels showing text_align set to left, center and
right](../../docs/assets/countdown/text-align.png)

### `until` and `since`

`until` (the default) counts down to `target_date`. `since` counts up from it,
which is what you want for "days since we shipped" or an anniversary.

![Two panels: until mode counting down to New Year, since mode counting up from
a launch date](../../docs/assets/countdown/modes.png)

### Per-countdown overrides

`style` overrides the global fonts and colours for one entry. Every key is
`null` by default, meaning "inherit the global setting":

```json
{
  "name": "Birthday",
  "target_date": "2026-11-14",
  "style": { "font_color": [255, 105, 180], "name_font_color": [255, 182, 193] }
}
```

`style` accepts `font_family`, `font_size`, `font_color`, `name_font_family`,
`name_font_size`, `name_font_color` and `background_color`.

`layout` overrides the automatic positioning, in pixels. Leave it out unless
something sits wrong — the defaults place the image on the left third and the
text on the right two thirds.

| Key | Default | Meaning |
|-----|---------|---------|
| `image_x` / `image_y` | `0` | Image top-left corner |
| `image_width` | `0` | `0` means auto — a third of the panel width |
| `image_height` | `0` | `0` means auto — the full panel height |
| `name_x` / `name_y` | `null` | `null` means auto: centred in the text area, upper third |
| `value_x` / `value_y` | `null` | `null` means auto: centred, lower two thirds |

Both `layout` and `style` also accept `null` or an empty string, which the web
UI may write when you clear a field.

---

## Global Settings

These apply to every countdown that does not override them.

| Option | Type | Default | What it does |
|--------|------|---------|--------------|
| `enabled` | boolean | `true` | Whether the plugin runs at all |
| `display_duration` | number | `15` | Seconds each countdown holds the panel |
| `show_expired` | boolean | `false` | Keep showing a countdown after its date has passed |
| `fit_to_display` | boolean | `true` | Scale images to fit the space they are given |
| `preserve_aspect_ratio` | boolean | `true` | Keep image proportions when scaling |
| `background_color` | array | `[0, 0, 0]` | Panel background, `[R, G, B]` |
| `font_family` | string | `press_start` | Face for the countdown value |
| `font_size` | integer | `8` | Size for the countdown value |
| `font_color` | array | `[255, 255, 255]` | Colour for the countdown value |
| `name_font_family` | string / null | `null` | Face for the name; `null` inherits `font_family` |
| `name_font_size` | integer | `8` | Size for the name |
| `name_font_color` | array | `[200, 200, 200]` | Colour for the name |

`show_expired` is the one to reach for if a countdown vanishes the moment it
lands. With it off — the default — a passed entry is dropped from the rotation
entirely, and if it was the only one the panel shows "No Active Countdowns".

### Fonts and colours

Four faces are available, and all four render distinctly:

![Four panels showing press_start, four_by_six, five_by_seven and tom_thumb
rendering the same countdown](../../docs/assets/countdown/fonts.png)

| Family | Kind | Notes |
|--------|------|-------|
| `press_start` | Scalable | The default; chunky 8-bit, very legible across a room |
| `four_by_six` | Scalable | Fits noticeably more text per line |
| `five_by_seven` | Bitmap | Crisp; always drawn at its native 7px |
| `tom_thumb` | Bitmap | The smallest option; native 6px |

**`font_size` only affects the scalable faces.** A bitmap font exists at exactly
one pixel size, so `five_by_seven` and `tom_thumb` are drawn at the size their
file declares and ignore `font_size`. That is why they look sharp while a
scalable face at an awkward size looks soft.

Name and value are styled separately, so a dimmer name over a bright value
(the default) reads well at a glance. Setting `name_font_family` to `null`
makes the name inherit `font_family`.

### Images

`image_path` may be absolute, relative to the working directory, or relative to
the plugins repository root — the plugin tries each in that order.

- Square images work best; the image area is a third of the panel width by the
  full height.
- PNG with transparency is fine. Transparent pixels show `background_color`.
- `fit_to_display` scales the image into its area; `preserve_aspect_ratio`
  keeps it from stretching. Both default to on, which is what you want unless
  you are deliberately filling the area.
- An image that cannot be found logs a warning and the countdown draws as
  text — it does not fail the render.

---

## Panel Sizes

![The same countdown on 64x32, 128x32, 128x64 and 256x32
panels](../../docs/assets/countdown/panel-sizes.png)

- **64×32** leaves the image about 21 pixels of width. Consider `text-only` at
  this size, or a very simple image.
- **128×32** is the size the defaults are tuned for.
- **128×64** gives the image real room and separates the two text lines.
- **256×32** keeps the same proportions across a longer panel.

---

## Troubleshooting

**Nothing shows, or "No Active Countdowns".**
Every countdown has either been disabled or has passed its date. Check
`enabled` on each entry, and turn on `show_expired` if you want passed ones to
stay.

**A countdown disappeared the day it arrived.**
That is `show_expired` (off by default). With no `target_time`, the target is
midnight, so the entry expires at the start of the day rather than the end.

**It says "Tomorrow" and I want a number.**
That is the format ladder, not a fault — between 1 and 2 days out the plugin
writes `Tomorrow` rather than `1 Day`. See
[the table above](#how-the-countdown-value-is-written).

**The image is not showing.**
Check the log for `Image not found` — the path is tried absolute, then relative
to the working directory, then relative to the repository root. Also check
`layout_preset` is not `text-only`, which ignores images by design.

**I picked a font and nothing changed.**
On a current version all four families work. Older versions offered `tiny` and
`picopixel`, which had no font file at all, and silently fell back to the
default for every bitmap family. If you had one of those selected, pick again.

**The date arithmetic looks off by a day.**
Countdowns are computed in the host's local time against `target_date` at
`target_time` (midnight if unset). A target early in the morning can therefore
tick over a day sooner than you expect.

---

## Development

### Project structure

```text
countdown/
├── manifest.json        # Plugin metadata and version history
├── manager.py           # CountdownPlugin
├── config_schema.json   # Settings schema; source of truth for defaults
├── requirements.txt
├── test/                # Harness config and golden images
└── README.md
```

### Requirements and compatibility

| | |
|---|---|
| LEDMatrix core | `>= 2.0.0` |
| Pillow | `>= 12.2.0` |
| python-dateutil | `>= 2.8.0` |

The plugin subclasses `BasePlugin`, renders text through the core font manager,
supports dynamic duration so the rotation stays smooth, and **caches loaded
images** so a countdown that comes round repeatedly does not re-decode its
picture each time.

### Where to keep images

There is no enforced location — `image_path` is whatever you set. A convention
that keeps uploads out of the plugin directory (and so survives a plugin
update) is:

```text
assets/plugins/countdown/uploads/
```

### Regenerating the images in this README

Every screenshot comes from a declarative shot list against a frozen clock:

```bash
python scripts/render_docs_assets.py --plugin countdown
```

`--check` verifies the committed images still match what the plugin renders.
The sample gift icon lives in `docs/assets/countdown/sample/`.

---

## Support

- YouTube: <https://www.youtube.com/@ChuckBuilds>
- Instagram: <https://www.instagram.com/ChuckBuilds/>
- Discord: <https://discord.com/invite/uW36dVAtcT>
- Sponsor: [GitHub Sponsors](https://github.com/sponsors/ChuckBuilds) ·
  [Buy Me a Coffee](https://buymeacoffee.com/chuckbuilds) ·
  [Ko-fi](https://ko-fi.com/chuckbuilds/)

Released under the GNU General Public License v3.0 — see [LICENSE](LICENSE).
