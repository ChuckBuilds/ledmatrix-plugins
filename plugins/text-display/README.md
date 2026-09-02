# Scrolling Text

Put any message on your LED matrix — a greeting, an announcement, a ticker.
Either scroll it continuously or sit it statically on the panel, in any font,
size and colour.

![The text "Subscribe to ChuckBuilds" fitted across a 128x32 panel in white on
black](../../docs/assets/text-display/hero.png)

*Every image in this README is real plugin output, rendered at the true panel
size and then scaled up so the pixels stay pixels. Nothing here is a mockup.*

---

## Table of Contents

1. [What's On Screen](#whats-on-screen)
2. [Installation](#installation)
3. [Quick Start](#quick-start)
4. [Text and Sizing](#text-and-sizing)
   - [font_mode](#font_mode)
   - [font_path and font_size](#font_path-and-font_size)
5. [Scrolling](#scrolling)
   - [How fast it moves](#how-fast-it-moves)
   - [Looping and the gap](#looping-and-the-gap)
6. [Colours](#colours)
7. [Timing](#timing)
8. [Recipes](#recipes)
9. [Panel Sizes](#panel-sizes)
10. [Troubleshooting](#troubleshooting)
11. [Development](#development)
12. [Support](#support)

---

## What's On Screen

One line of text, vertically centred, drawn either statically or scrolling
right-to-left.

Static text is centred horizontally. If it is wider than the panel it simply
overflows both edges — the plugin does not shrink it for you unless you ask it
to with [`font_mode: auto`](#font_mode), and does not wrap onto a second line.

Scrolling text starts fully off the right edge and travels left, so at the
instant a scroll begins the panel is legitimately empty.

---

## Installation

**From the Plugin Store (recommended).** Open the LEDMatrix web interface at
`http://<your-pi-ip>:5000`, go to **Plugin Manager**, find **Scrolling Text** in
the **Plugin Store** section, and click **Install**.

**Manually.** Copy this directory into your LEDMatrix `plugin-repos/` and
restart the display service.

`enabled` defaults to **`false`**, so nothing appears until you switch the
plugin on.

---

## Quick Start

```json
{
  "text-display": {
    "enabled": true,
    "text": "Welcome to the workshop"
  }
}
```

A fully specified configuration:

```json
{
  "text-display": {
    "enabled": true,
    "text": "Subscribe to ChuckBuilds",
    "font_mode": "auto",
    "font_path": "assets/fonts/PressStart2P-Regular.ttf",
    "font_size": 8,
    "scroll": true,
    "scroll_loop": true,
    "scroll_speed": 1,
    "scroll_delay": 0.01,
    "target_fps": 120,
    "scroll_gap_width": 32,
    "text_color": [255, 255, 255],
    "background_color": [0, 0, 0],
    "display_duration": 10,
    "update_interval": 60
  }
}
```

---

## Text and Sizing

| Option | Type | Default | What it does |
|--------|------|---------|--------------|
| `text` | string | `"Subscribe to ChuckBuilds"` | The message to display |
| `font_mode` | string | `manual` | `manual` or `auto` — see below |
| `font_path` | string | `assets/fonts/PressStart2P-Regular.ttf` | Font file, relative to the project root or absolute |
| `font_size` | number | `8` | Size in pixels. **Manual mode only** |

### `font_mode`

This is the setting that decides whether you have to think about sizing at all.

![Four panels comparing manual and auto font mode on long and short
text](../../docs/assets/text-display/font-mode.png)

- **`manual`** (the default) uses `font_size` exactly as configured. Long text
  overflows the panel; short text stays small.
- **`auto`** ignores `font_size` and picks the largest crisp size that fits the
  panel. Long text is shrunk to fit; short text is grown to fill.

`auto` is the right choice for a static message you want readable across a
room, and for any text whose length you do not control. Stay on `manual` when
you want a consistent size regardless of what the message says — a ticker that
changes text should not change size with it.

### `font_path` and `font_size`

`font_path` accepts both TrueType (`.ttf`) and bitmap (`.bdf`) fonts:

- **TTF** scales to any `font_size`. `PressStart2P-Regular.ttf` (the default) is
  a chunky 8-bit face that stays legible at a distance; `4x6-font.ttf` fits far
  more characters per line.
- **BDF** is a bitmap face drawn at one fixed pixel size. It renders crisply,
  but `font_size` cannot change it — the file's own size wins.

![Four panels showing font_size 6, 8, 12 and 16 with the same long
text](../../docs/assets/text-display/font-size.png)

Larger sizes are more readable but fit less on the panel, which is what makes
`scroll` or `font_mode: auto` necessary for anything longer than a word or two.

---

## Scrolling

| Option | Type | Default | What it does |
|--------|------|---------|--------------|
| `scroll` | boolean | `true` | Scroll the text, or draw it statically |
| `scroll_loop` | boolean | `true` | Loop continuously, or scroll once and stop |
| `scroll_speed` | number | `1` | Pixels moved per frame |
| `scroll_delay` | number | `0.01` | Seconds per frame |
| `target_fps` | number | `120` | Target frame rate hint |
| `scroll_gap_width` | number | `32` | Blank pixels between the end and the restart |

### How fast it moves

Three settings look like they control speed. Only two of them actually set it:

```text
pixels per second = scroll_speed / scroll_delay
```

So the defaults — 1 pixel per frame every 0.01s — give 100 px/s.

- **`scroll_speed`** is pixels per *frame*, not per second. It is clamped to a
  maximum of 5; above that the movement reads as jumping rather than scrolling,
  and the plugin logs a warning if you set more. Values above 5 in an old config
  usually mean it was written when this was pixels-per-second.
- **`scroll_delay`** is the throttle — seconds between frames. Lowering it
  raises both the frame rate and the CPU cost.
- **`target_fps`** is a pacing hint passed to the core's scroll helper, clamped
  to 30–200. It does not by itself change the pixels-per-second figure above;
  raising it without lowering `scroll_delay` will not make text move faster.

To make text move faster, prefer raising `scroll_speed` a little (1 → 2) over
driving `scroll_delay` very low. To make it smoother, lower `scroll_delay`.

### Looping and the gap

With `scroll_loop: true` the message repeats forever, and `scroll_gap_width`
sets how much blank panel passes between the last character and the first
coming round again. A gap roughly equal to your panel width gives the cleanest
loop — the message is fully gone before it returns. The default of 32 suits a
64-wide panel; on a 128-wide chain, try 128.

With `scroll_loop: false` the text scrolls past once and stops. Pair it with
`display_duration` long enough for a full pass, or the plugin's turn will end
mid-message.

> **A still cannot show motion.** There is no screenshot of scrolling in this
> README because a single frame captured at the start of a scroll is an empty
> panel — the text has not entered yet. That is correct behaviour, not a fault.

---

## Colours

| Option | Type | Default | What it does |
|--------|------|---------|--------------|
| `text_color` | array | `[255, 255, 255]` | Text colour, `[R, G, B]` |
| `background_color` | array | `[0, 0, 0]` | Panel background, `[R, G, B]` |

![Four panels showing white, amber and green text, and black text on a red
background](../../docs/assets/text-display/colors.png)

A non-black `background_color` lights every pixel on the panel, which draws
noticeably more power and is much brighter in a dark room. Use it for a
deliberate alert, not as a default.

---

## Timing

| Option | Type | Default | What it does |
|--------|------|---------|--------------|
| `display_duration` | number | `10` | Seconds the plugin holds the panel per turn |
| `update_interval` | integer | `60` | Seconds between refreshes of the text |

For scrolling text, `display_duration` should be long enough for at least one
full pass, or viewers only ever see the middle of the message. A rough guide:

```text
seconds for one pass ≈ (text width + panel width + scroll_gap_width) / (scroll_speed / scroll_delay)
```

`update_interval` matters little here because the text is static configuration
rather than fetched data — it only decides how quickly a config change is
picked up.

---

## Recipes

**A static announcement.** Large, centred, no motion:

```json
{ "text": "WELCOME!", "scroll": false, "font_mode": "auto",
  "text_color": [0, 255, 0] }
```

**A news-style ticker.** Long message, continuous loop, slightly quicker:

```json
{ "text": "Breaking: LED matrices are awesome. Stay tuned for more...",
  "scroll": true, "scroll_speed": 1.5, "scroll_gap_width": 128,
  "display_duration": 30 }
```

**A call to action.** Coloured, looping, sized to the panel:

```json
{ "text": "Subscribe to ChuckBuilds on YouTube!", "scroll": true,
  "scroll_speed": 2, "text_color": [255, 0, 0] }
```

**A one-shot message.** Scrolls past once and stops, then hands the panel back:

```json
{ "text": "Build complete", "scroll": true, "scroll_loop": false,
  "display_duration": 20 }
```

### Choosing a font for a panel

Bitmap (`.bdf`) faces are drawn pixel-exact and stay crisp, which suits an LED
matrix better than a scaled outline font. TrueType gives more choice and any
size you like, at the cost of soft edges at awkward sizes. Whichever you pick,
prefer a face designed for small sizes — a display font intended for print
turns to mush below about 10 pixels.

---

## Panel Sizes

![The same message on 64x32, 128x32, 128x64 and 256x32 panels in auto
mode](../../docs/assets/text-display/panel-sizes.png)

In `auto` mode the plugin uses whatever the panel gives it: a 64-wide panel
forces a small face, while a 256-wide chain lets the same message render large.
In `manual` mode the size is fixed, so a wider panel simply shows more of the
message before it overflows.

---

## Troubleshooting

**Nothing appears.**
`enabled` defaults to `false`. Check it is `true`.

**The panel is blank but I set text.**
If `scroll` is on, the message begins off the right edge — a blank panel at the
start of a pass is expected. If it stays blank, check `text_color` is not the
same as `background_color`.

**The text is cut off at both edges.**
That is static `manual` mode with text wider than the panel. Switch to
`font_mode: auto`, lower `font_size`, or turn on `scroll`.

**Scrolling looks jumpy.**
`scroll_speed` is pixels per *frame*. Values above 2 visibly step; above 5 the
plugin clamps and logs a warning. Lower `scroll_speed` and lower `scroll_delay`
instead.

**I raised `target_fps` and nothing got faster.**
It is a pacing hint, not the speed control. Speed is
`scroll_speed / scroll_delay` — see [How fast it moves](#how-fast-it-moves).

**I only ever see the middle of the message.**
`display_duration` is ending the turn before a full pass completes. Raise it,
or shorten the text.

**`font_size` has no effect.**
Either `font_mode` is `auto` (which chooses the size itself) or `font_path`
points at a `.bdf`, which is drawn at its own fixed pixel size.

**The font did not change.**
`font_path` is resolved relative to the LEDMatrix project root, not to the
plugin directory. Check the log for a font-loading warning.

---

## Development

### Project structure

```text
text-display/
├── manifest.json        # Plugin metadata and version history
├── manager.py           # TextDisplayPlugin
├── config_schema.json   # Settings schema; source of truth for defaults
└── README.md
```

Scrolling is delegated to the core's `ScrollHelper` in frame-based mode, which
is the same mechanism the stock and leaderboard tickers use — so scrolling here
behaves consistently with those.

### Performance

Scrolling redraws the panel every frame, so it costs meaningfully more CPU than
static text. On a Raspberry Pi driving a large chain, prefer the default
`scroll_delay` of `0.01` over lower values, and remember that a non-black
`background_color` lights every pixel.

### Regenerating the images in this README

```bash
python scripts/render_docs_assets.py --plugin text-display
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
