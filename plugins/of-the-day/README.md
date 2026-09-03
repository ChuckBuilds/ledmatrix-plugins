# Of The Day

A different word, quote, verse or fact each day, from JSON files you control.
Ships with an English and a Slovenian word-of-the-day list, and takes any
number of your own.

![The word "Opportune" on a 128x64 panel, underlined, with its definition
wrapped below](../../docs/assets/of-the-day/hero.png)

*Every image in this README is real plugin output, rendered at the true panel
size against a frozen clock — "Opportune" is genuinely the entry for 2 September
in the bundled list. Nothing here is a mockup.*

---

## Table of Contents

1. [What's On Screen](#whats-on-screen)
2. [Installation](#installation)
3. [Adding a Category](#adding-a-category)
4. [The Data File Format](#the-data-file-format)
5. [Configuration Reference](#configuration-reference)
   - [Rotation and timing](#rotation-and-timing)
   - [auto_fit_text](#auto_fit_text)
   - [Fonts and colours](#fonts-and-colours)
6. [Panel Sizes](#panel-sizes)
7. [Troubleshooting](#troubleshooting)
8. [Development](#development)
9. [Support](#support)

---

## What's On Screen

A title, underlined, with body text beneath it:

```text
      Opportune          <- title, from the entry's "title"
──────────────────
  Well-chosen or         <- body, from "subtitle" then "description"
favorable or appropriate
```

The body rotates between the entry's `subtitle` and `description` every
`display_rotate_interval` seconds, so a definition and an example sentence both
get their turn without needing a taller panel.

With more than one category configured, the plugin also rotates between
categories — a word today, a quote next turn — in `category_order`.

---

## Installation

**From the Plugin Store (recommended).** Open the LEDMatrix web interface at
`http://<your-pi-ip>:5000`, go to **Plugin Manager**, find **Of The Day** in the
**Plugin Store** section, and click **Install**.

**Manually.** Copy this directory into your LEDMatrix `plugin-repos/` and
restart the display service.

> **A fresh install shows "No Data".** Two things are off by default:
> `enabled` is `false`, and — more surprisingly — **the `categories` block is
> empty**. The bundled data files exist, but nothing points at them until you
> add a category. See below.

---

## Adding a Category

The easiest route is the plugin's own tab in the web interface, which lists the
bundled files, lets you upload your own, and writes the config for you.

By hand, a category is an entry in the `categories` object keyed by an id of
your choosing:

```json
{
  "of-the-day": {
    "enabled": true,
    "categories": {
      "word_of_the_day": {
        "enabled": true,
        "data_file": "of_the_day/word_of_the_day.json",
        "display_name": "Word of the Day"
      }
    },
    "category_order": ["word_of_the_day"]
  }
}
```

| Key | Type | Default | What it does |
|-----|------|---------|--------------|
| `enabled` | boolean | `true` | Include this category in the rotation |
| `data_file` | string | — | Path to the JSON file, relative to the plugin directory |
| `display_name` | string | — | Label shown in the configuration UI |

Two lists ship with the plugin:

![Two panels: the English word of the day, and the Slovenian
one](../../docs/assets/of-the-day/categories.png)

| File | Contents |
|------|----------|
| `of_the_day/word_of_the_day.json` | An English word a day, with definition and example |
| `of_the_day/slovenian_word_of_the_day.json` | A Slovenian word a day, with its English meaning |

`category_order` controls the order categories are shown in. A category listed
in `category_order` but missing from `categories` is skipped, and one present
in `categories` but absent from `category_order` is appended after the
listed ones.

---

## The Data File Format

A data file is a JSON object keyed by **day of the year as a string**, `"1"`
through `"365"`:

```json
{
  "1": {
    "title": "Abstruse",
    "subtitle": "Difficult to understand; obscure",
    "description": "The philosopher's work was filled with abstruse concepts."
  },
  "245": {
    "title": "Opportune",
    "subtitle": "Well-chosen or particularly favorable or appropriate",
    "description": "She waited for an opportune moment to raise the subject."
  }
}
```

| Field | Shown as |
|-------|----------|
| `title` | The underlined heading |
| `subtitle` | The first body line — a definition or short gloss |
| `description` | The second body line, rotated in after `display_rotate_interval` |

Selection is by calendar date, not random: day 245 of any year shows entry
`"245"`. That makes the display stable — it will not change halfway through the
day — and means a file needs 365 entries for full coverage. Missing days are
skipped rather than erroring.

Because it is keyed by day rather than date, the same file works every year.
For a leap year, day 366 has no entry unless you add one.

> Earlier documentation described these files as keyed by `YYYY-MM-DD`. They are
> not — the bundled files and the loader both use the day-of-year number. A file
> written with date keys will load without error and then show nothing, because
> no key ever matches.

### Writing your own list

- **Keep the subtitle short.** It is the line most often shown, and on a 128×32
  panel roughly 24 characters survive before truncation. The description can be
  longer since it only needs to fit when it takes its turn.
- **Use the same fields throughout.** An entry missing `subtitle` or
  `description` simply shows less; it does not fall back to another field.
- **Cover all 365 days** if you want the category to appear every day. Gaps are
  skipped, so a sparse file means the category quietly disappears on the missing
  days.
- **Generate rather than type.** The format is a flat JSON object, so a
  dictionary API, an RSS feed or a spreadsheet export can all be turned into one
  with a short script. Nothing in the plugin cares how the file was produced —
  drop the result in via the file manager.

---

## Configuration Reference

| Option | Type | Default | What it does |
|--------|------|---------|--------------|
| `enabled` | boolean | `false` | Whether the plugin runs at all |
| `categories` | object | *(empty)* | Your categories — see [above](#adding-a-category) |
| `category_order` | array | `["word_of_the_day", "slovenian_word_of_the_day"]` | Display order |
| `display_duration` | number | `40` | Seconds each category holds the panel |
| `display_rotate_interval` | number | `20` | Seconds between body elements within a category |
| `subtitle_rotate_interval` | number | `10` | Seconds between subtitle variants |
| `update_interval` | integer | `3600` | Seconds between checks for a new day |
| `auto_fit_text` | boolean | `true` | Shrink the body font so long text fits |
| `customization` | object | *(defaults)* | Fonts, sizes, colours and offsets |
| `file_manager` | — | — | Not a setting; the data-file widget in the web UI |

### Rotation and timing

Three intervals stack, from slowest to fastest:

- **`display_duration`** (default `40`) — how long the whole category holds the
  panel before the display controller moves on.
- **`display_rotate_interval`** (default `20`) — within that turn, how often the
  body swaps between the entry's subtitle and description. At the defaults, a
  40-second turn shows each of the two for 20 seconds.
- **`subtitle_rotate_interval`** (default `10`) — how often the subtitle line
  itself cycles, for entries carrying more than one.

If you shorten `display_duration` below `display_rotate_interval`, the second
body element never appears — the turn ends first.

`update_interval` is only a check for the date rolling over. Since entries
change once a day, the hourly default is already far more often than needed.

### `auto_fit_text`

When the body text will not fit at the configured size, this steps the font
down until it does — largest size that fits wins. Only scalable fonts can
shrink; a bitmap font is left alone. Text that still cannot fit at the smallest
size is cut to the lines that fit, with the last one ellipsized.

![Two 128x64 panels with body font_size 12: with auto-fit the definition
shrinks and fits in three lines, without it the text is cut and ends in an
ellipsis](../../docs/assets/of-the-day/auto-fit.png)

It has no visible effect when the text already fits, or when the panel has room
for only one body line whatever the size — on a 128×32 panel the result is the
same either way. It earns its keep on taller panels and with larger body fonts.

### Fonts and colours

Two elements are styled independently under `customization`: `title_text` and
`body_text`.

![Four 128x64 panels: the default white-on-grey, an amber scheme, a cyan
scheme, and larger title and body
sizes](../../docs/assets/of-the-day/customization.png)

| Element | `font` | `font_size` | `text_color` |
|---------|--------|-------------|--------------|
| `title_text` | `PressStart2P-Regular.ttf` | `8` (4–16) | `[255, 255, 255]` |
| `body_text` | `4x6-font.ttf` | `6` (4–12) | `[200, 200, 200]` |

```json
{
  "customization": {
    "title_text": { "text_color": [255, 176, 0], "font_size": 10 },
    "body_text":  { "text_color": [200, 130, 0], "font_size": 8 }
  }
}
```

> **The key names are `font_size` and `text_color`.** The schema declares these
> elements in an `x-style-elements` block that uses the short names `size` and
> `color`, but that is the *declaration* format — the core expands it into the
> config properties `font`, `font_size` and `text_color`. Writing `size` or
> `color` in your config is silently ignored, with no warning and no visible
> change. It is an easy mistake to make from reading the schema.

Both elements also accept `x_offset` and `y_offset` for nudging position.

Customization needs a LEDMatrix core with the element-style system. On an older
core the section is not offered and the classic styling above is used, which is
why an untouched config renders identically either way.

---

## Panel Sizes

![The same word on 64x32, 128x32, 128x64 and 256x32
panels](../../docs/assets/of-the-day/panel-sizes.png)

Height matters far more than width here, because the body wraps:

- **64×32** fits the title and a fragment of the definition.
- **128×32** fits the title and one truncated body line.
- **128×64** is where the plugin comes into its own — the definition wraps and
  fits in full.
- **256×32** buys a longer single body line, but is still one line.

If the definitions matter to you, 64 rows is worth more than 256 columns.

---

## Troubleshooting

**It says "No Data".**
The most likely cause is that no category is configured — the `categories`
block is empty on a fresh install even though the data files ship with the
plugin. Add one from the plugin's tab in the web UI, or by hand as
[shown above](#adding-a-category).

**Nothing appears at all.**
`enabled` defaults to `false`.

**A category is configured but never shows.**
Check its own `enabled` flag, that `data_file` resolves relative to the plugin
directory, and that the file has an entry for today's day-of-year number.

**The definition is cut off.**
That is the panel height. Turn on `auto_fit_text` (it is on by default), reduce
`body_text.font_size`, or use a taller panel — see
[Panel Sizes](#panel-sizes).

**I changed a colour or size and nothing happened.**
Check the key names: they are `font_size` and `text_color`, not `size` and
`color`. See [Fonts and colours](#fonts-and-colours).

**The example sentence never appears.**
`display_duration` is probably shorter than `display_rotate_interval`, so the
turn ends before the body rotates. Raise the former or lower the latter.

**The word did not change at midnight.**
`update_interval` decides how often the date is re-checked; at the default it
can be up to an hour late.

---

## Development

### Project structure

```text
of-the-day/
├── manifest.json         # Plugin metadata and version history
├── manager.py            # OfTheDayPlugin
├── config_schema.json    # Settings schema; source of truth for defaults
├── of_the_day/           # Bundled data files
│   ├── word_of_the_day.json
│   └── slovenian_word_of_the_day.json
├── scripts/              # Backend actions for the web UI file manager
├── web_ui/               # The file-manager interface
├── test/                 # Harness config and golden images
└── README.md
```

The `scripts/` directory holds the actions the file manager calls —
`list_files`, `get_file`, `save_file`, `create_file`, `delete_file`,
`upload_file`, `toggle_category` and `update_config`. They are invoked by the
web UI rather than run directly.

### Tests

```bash
python plugins/of-the-day/test_text_fitting.py
python plugins/of-the-day/test_element_styles.py
```

### Regenerating the images in this README

```bash
python scripts/render_docs_assets.py --plugin of-the-day
```

`--check` verifies the committed images still match what the plugin renders.
The clock is frozen in the shot list, which is what pins the entry to
"Opportune" — without that the images would change daily.

---

## Support

- YouTube: <https://www.youtube.com/@ChuckBuilds>
- Instagram: <https://www.instagram.com/ChuckBuilds/>
- Discord: <https://discord.com/invite/uW36dVAtcT>
- Sponsor: [GitHub Sponsors](https://github.com/sponsors/ChuckBuilds) ·
  [Buy Me a Coffee](https://buymeacoffee.com/chuckbuilds) ·
  [Ko-fi](https://ko-fi.com/chuckbuilds/)

Released under the GNU General Public License v3.0 — see [LICENSE](LICENSE).
