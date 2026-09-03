# Christmas Countdown

A festive countdown to Christmas — a pixel-art tree beside the number of days
left, switching to "MERRY CHRISTMAS" on the day itself.

![114 DAYS UNTIL CHRISTMAS in red beside a green pixel-art tree, on a 128x32
panel](../../docs/assets/christmas-countdown/hero.png)

*Every image in this README is real plugin output, rendered at the true panel
size against a frozen clock and then scaled up so the pixels stay pixels. The
day counts are what the plugin computes for the dates shown.*

---

## Table of Contents

1. [What's On Screen](#whats-on-screen)
2. [Installation](#installation)
3. [Configuration Reference](#configuration-reference)
   - [Settings that have no effect](#settings-that-have-no-effect)
4. [Panel Sizes](#panel-sizes)
5. [The Tree Image](#the-tree-image)
6. [Troubleshooting](#troubleshooting)
7. [Development](#development)
8. [Support](#support)

---

## What's On Screen

The tree sits on the **left** and the countdown text on the **right**, at every
panel size. The panel is split down the middle: the tree is fitted into the
left half less a 2px margin, and the text is centred in the right half.

The text has three states, driven by the date:

| When | Shows |
|------|-------|
| Before 25 December | `N DAYS UNTIL CHRISTMAS` |
| On 25 December | `MERRY CHRISTMAS` |
| After 25 December | `MERRY CHRISTMAS`, until the count to next year begins |

![The countdown 114 days out, a week out, the day before, and on Christmas Day
itself](../../docs/assets/christmas-countdown/countdown.png)

On a panel **narrower than 64 pixels** the last word is abbreviated to `XMAS`
so the text still fits. Everything is computed from the host's local date, so
the count changes at local midnight.

---

## Installation

**From the Plugin Store (recommended).** Open the LEDMatrix web interface at
`http://<your-pi-ip>:5000`, go to **Plugin Manager**, find **Christmas
Countdown** in the **Plugin Store** section, and click **Install**.

**Manually.** Copy this directory into your LEDMatrix `plugin-repos/` and
restart the display service.

`enabled` defaults to **`false`**. Being seasonal, it is also worth turning
back off in January rather than leaving it counting down 300-odd days.

---

## Configuration Reference

Five settings work:

| Option | Type | Default | What it does |
|--------|------|---------|--------------|
| `enabled` | boolean | `false` | Whether the plugin runs at all |
| `display_duration` | number | `15` | Seconds on screen before the rotation moves on (1–300) |
| `update_interval` | integer | `3600` | Seconds between recomputes (60–86400). The count changes daily, so an hour is already generous |
| `text_color` | array | `[255, 0, 0]` | Countdown text colour, `[R, G, B]` |
| `tree_color` | array | `[0, 128, 0]` | Tree colour — **only used when the tree image is missing**, see [The Tree Image](#the-tree-image) |

![The countdown in red, white, gold and pale
blue](../../docs/assets/christmas-countdown/text-color.png)

`text_color` is the one worth changing. The default red is traditional but the
least bright colour an LED panel produces; white or gold reads considerably
further across a room.

### Settings that have no effect

The remaining five appear in the web UI with descriptions, and **do nothing**.
This is documented rather than quietly omitted, because a setting that silently
ignores you is worse than one that is absent — and each of these is checked
against the source, not guessed:

| Option | Schema promises | Reality |
|--------|-----------------|---------|
| `transition.type` | One of `redraw`, `fade`, `slide`, `wipe`, `dissolve`, `pixelate` | The string `transition` does not appear anywhere in `manager.py`, and the core implements no display transitions |
| `transition.speed` | "1=slow, 10=fast" | As above |
| `transition.enabled` | "Enable or disable transitions" | As above |
| `high_performance_transitions` | "120 FPS instead of 30 FPS" | `high_performance` does not appear in `manager.py` |
| `tree_size` | "Size of the Christmas tree logo in pixels" | Read and *validated* — a value ≤ 0 is rejected with a warning — but never applied. The tree is always fitted to the left half minus a 2px margin |

`tree_size` is the most misleading of the five, because rejecting a bad value
is fair evidence to anyone testing that the setting is live.

Tracked in [#377](https://github.com/ChuckBuilds/ledmatrix-plugins/issues/377).
Leave all five alone; changing them costs nothing but will do nothing.

---

## Panel Sizes

![The countdown on 64x32, 128x32, 128x64 and 256x32
panels](../../docs/assets/christmas-countdown/panel-sizes.png)

- **64×32** is where the `XMAS` abbreviation kicks in; tree and text share very
  little width.
- **128×32** is the size the layout suits best.
- **128×64** gives the tree real presence — it is the most attractive size for
  this plugin by some margin.
- **256×32** keeps the same proportions, so the tree stays small and a wide gap
  opens between it and the text. A long chain does not improve this plugin the
  way extra height does.

---

## The Tree Image

The tree is `assets/christmas_tree.png`, a small pixel-art PNG that ships with
the plugin and is scaled to the space available.

If that file is missing, the plugin draws a simple tree programmatically
instead — and **that** is the only situation in which `tree_color` applies. With
the bundled image present, as it is on any normal install, `tree_color` has no
visible effect. The schema says so; it is repeated here because "green tree
colour" reads like a setting that should work.

To regenerate the bundled image:

```bash
python3 generate_tree_image.py
```

That script writes `assets/christmas_tree.png` and nothing else — it is an
asset generator, not a preview of the plugin, so it cannot drift from what the
plugin draws.

---

## Troubleshooting

**Nothing appears.**
`enabled` defaults to `false`.

**The day count looks off by one.**
The count is computed from the host's local date and changes at local midnight,
not UTC midnight. Check the Pi's timezone if it disagrees with your calendar.

**It says MERRY CHRISTMAS in July.**
It should not — that message is shown on and shortly after 25 December only. If
you see it out of season, check the system date.

**The text says XMAS instead of CHRISTMAS.**
That is deliberate on panels narrower than 64 pixels, where the full word does
not fit.

**I changed the tree colour and nothing happened.**
`tree_color` only applies when `assets/christmas_tree.png` is missing. With the
bundled image in place the tree comes from the PNG.

**I changed the tree size and nothing happened.**
`tree_size` is not applied — see
[Settings that have no effect](#settings-that-have-no-effect).

**I changed the transition and nothing happened.**
None of the transition settings are implemented. Same section.

---

## Development

### Project structure

```text
christmas-countdown/
├── manifest.json            # Plugin metadata and version history
├── manager.py               # ChristmasCountdownPlugin
├── config_schema.json       # Settings schema; source of truth for defaults
├── generate_tree_image.py   # Regenerates assets/christmas_tree.png
├── assets/
│   └── christmas_tree.png
├── test/
└── README.md
```

### Requirements

None beyond the LEDMatrix core. The plugin uses only the standard library and
Pillow, which the core already provides — `requirements.txt` says as much and
pins nothing.

### Testing

The plugin ships a harness fixture and golden images, so the core's safety
harness can check it renders correctly at every panel size:

```bash
# from a LEDMatrix core checkout
python scripts/check_plugin.py --plugin christmas-countdown   --plugin-dir /path/to/ledmatrix-plugins/plugins --out-dir /tmp/preview
```

To watch it live in the emulator instead:

```bash
python run.py --emulator
```

### Regenerating the images in this README

```bash
python scripts/render_docs_assets.py --plugin christmas-countdown
```

`--check` verifies the committed images still match. The clock is frozen in the
shot list, which is what pins the day counts — without that every image would
change daily.

---

## Support

- YouTube: <https://www.youtube.com/@ChuckBuilds>
- Instagram: <https://www.instagram.com/ChuckBuilds/>
- Discord: <https://discord.com/invite/uW36dVAtcT>
- Sponsor: [GitHub Sponsors](https://github.com/sponsors/ChuckBuilds) ·
  [Buy Me a Coffee](https://buymeacoffee.com/chuckbuilds) ·
  [Ko-fi](https://ko-fi.com/chuckbuilds/)

Released under the GNU General Public License v3.0 — see [LICENSE](LICENSE).
