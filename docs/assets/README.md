# README screenshots

Every image used in a plugin README lives here, under `docs/assets/<plugin-id>/`,
and every one of them is real plugin output — rendered headlessly at a true
panel size, then upscaled with nearest-neighbour so the pixels stay pixels.
None of them are mockups, and none are hand-drawn.

Keeping them out of `plugins/<id>/` means a plugin install stays lean: the
store only ships what the panel needs to run.

## Layout

```text
docs/assets/<plugin-id>/
├── shots.json     # declarative shot list — the source of truth
├── hero.png       # the one image at the top of the README
└── *.png          # comparison grids for individual settings
```

## Regenerating

```bash
python scripts/render_docs_assets.py --plugin <plugin-id>
```

This needs a sibling checkout of the LEDMatrix core, which owns the renderer:

```bash
git clone https://github.com/ChuckBuilds/LEDMatrix.git
```

Point at it explicitly with `--core-repo /path/to/LEDMatrix` or the
`LEDMATRIX_CORE` environment variable if it is not next to this repo.

To verify the committed images still match what the plugin renders today:

```bash
python scripts/render_docs_assets.py --all --check
```

## Writing a shot list

A shot list declares the panels to render and the grids to assemble from them.
`scripts/render_docs_assets.py` documents every key; the short version:

- **`defaults`** — width, height, upscale factor, config and `freeze_time`
  shared by every shot.
- **`shots`** — one render each. Anything set here overrides `defaults`. Set
  `"standalone": false` on a shot that only exists to be pasted into a grid, so
  it does not also get written out as its own file.
- **`composites`** — labelled grids built from named shots. Each cell takes a
  `label` and an optional `sublabel`; the sublabel is the place to name the
  exact config key being demonstrated.

Two conventions worth keeping:

- **Freeze the clock.** `freeze_time` pins what the plugin thinks "now" is, so
  a clock, a countdown, or a "starts in 2h" line renders identically on every
  run. Without it the committed images can never be checked against a
  re-render.
- **Show the failure modes too.** A grid that only shows settings working is
  less useful than one that also shows what happens at the extremes — a value
  that overflows a narrow panel is worth a cell.
