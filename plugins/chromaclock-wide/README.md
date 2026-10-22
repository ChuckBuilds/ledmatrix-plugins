# ChromaClock Wide

Native-width ChromaClock-inspired animations for **ChuckBuilds LEDMatrix** and wide, chained RGB panels. Developed for five 64×32 P5 panels in a row (**320×32**), but reads the display dimensions from LEDMatrix rather than hard-coding them.

Inspired by [alejoar's ChromaClock](https://github.com/tronbyt/apps/tree/main/apps/chromaclock). This **does not contain exact Starlark source or exact reproductions of the original styles**: it independently implements 28 wide-friendly styles.

## Live integrated web preview

On LEDMatrix releases supporting plugin-supplied custom widgets, the **Live LEDMatrix Preview** appears inside the ChromaClock Wide configuration tab. The 320×32 browser canvas updates as you change form controls, **before saving**. The canvas tracks time and style-cycle transitions automatically. This browser-based drawing is an approximation of the Python/Pillow output (not a physical LED feed). The preview operates entirely in your browser and **does not require changes to LEDMatrix core**. A page refresh may be needed after upgrading the plugin.

## Features

- Native-width clock drawing; no stretched 64×32 bitmap.
- 28 styles: neon, prism, starfield, matrix, fire, horizon, binary, minimal, pulse, wave, aurora, rain.
- **Cycle** mode changes styles every configurable number of seconds (default 20).
- **Preview Mode** pins the configured **Preview Style** to the *physical display* while you edit settings. Disable Preview Mode to resume normal style cycling. **This is not an embedded live preview in the LEDMatrix browser UI.**
- Date, seconds, progress bar, timezone, 12/24-hour setting, brightness, palette and glow.
- [Open the simulated visual preview gallery](docs/index.html).

## Installation

1. Use **Code → Download ZIP** and extract this repository.
2. In your existing Raspberry Pi LEDMatrix checkout, place `manager.py`, `manifest.json`, `config_schema.json`, and `requirements.txt` into `plugin-repos/chromaclock-wide/`. If your version offers third-party GitHub installation, you can try installing this repository directly through the Plugin Manager instead.
3. Ensure Pillow is available in LEDMatrix's Python environment; restart/rescan LEDMatrix if it does not discover the new plugin.
4. Enable **ChromaClock Wide** under the Plugin Manager and configure timezone, style and preferences.
5. For a preview on your matrix, set **Preview Mode** to true and choose **Preview Style**. Save; then disable preview when done.

LEDMatrix must already be configured with your physical 5-panel chain. The plugin follows its reported width and height.

## Important limitations

- The visual gallery is a simplified browser illustration, not a live feed from the Raspberry Pi or an exact rendering of its pixels.
- Animation advances when the LEDMatrix plugin framework calls `display()`. Frame rate and the ability to show style transitions during a single slot depend on LEDMatrix's display scheduling.
- The code is written against the LEDMatrix v2 `BasePlugin` API and has **not been tested on the user's physical hardware**. Plugin discovery and configuration schema behavior may vary by installed version.
- This project is an independent adaptation; see upstream for the original 23-style design.

## Source attribution

- [Tronbyt ChromaClock](https://github.com/tronbyt/apps/tree/main/apps/chromaclock)
- [ChuckBuilds LEDMatrix](https://github.com/ChuckBuilds/LEDMatrix)

## Additional ChromaClock-inspired styles (v1.3.0)

Added 16 native-width interpretations: **Pac-Man, Aquarium, Pong, Tetris, Moon, Snow, Lava lamp, Analog, Big hour, Split-flap, Morph, Outline, Words, Dot grid, Day progress and World clocks**. These are visually inspired wide adaptations, not exact pixel-for-pixel ports of the upstream Starlark animations. Available in both Style and Preview Style dropdowns, and in automatic cycle mode. Their animations depend on LEDMatrix's display refresh behavior.

## v1.3.2 — Preview selection and Pac-Man

When **Preview Mode** is on, **Preview Style** selects the browser preview immediately, and selects the physical panel after Save. When Preview Mode is off, the **Style** selector (including Cycle) drives both. Pac-Man now features blue arcade maze walls, pellets, a chomping yellow character and colored ghosts with eyes on both side bays. After updating, reload the web page with a cache-bypassing refresh to replace the older widget script.

## v1.4.0 — Full-width transparent clock overlay

All clock styles now draw their animation across the entire matrix width instead of reserving blank left/right bays. The time remains centered and is rendered on top of the scene, with only a one-pixel dark glyph outline for contrast and no solid text background or bounding box. The browser preview uses the same full-width layout. Pac-Man can travel behind clock glyphs; ghosts remain in their own vertical lanes. The clock characters themselves mask the pixels immediately underneath them, as normal foreground drawing.
