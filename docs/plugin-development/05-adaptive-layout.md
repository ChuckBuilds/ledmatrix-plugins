# 5. Adaptive Layout & Multi-Size Rendering

[← Guide index](./README.md) · [← Styling & skins](./04-styling-and-skins.md)

Every plugin must render correctly on the **classic panel sizes** —
64×32, 128×32, 128×64, and 256×32 — with nothing drawn past the edge. The
[safety harness](./07-testing-ci-and-registry.md#the-safety-harness) enforces
this on every PR (and by default also exercises additional sizes — see topic 07).
This page covers how plugins adapt to size, from simple tier-branching up to the
core's opt-in `adaptive` layout engine.

---

## Reading the live panel size

The display manager exposes the current dimensions. Use them; never hard-code a
panel size.

```python
w = self.display_manager.width          # logical width
h = self.display_manager.height         # logical height
# or the raw matrix, which some plugins read per-frame:
w = self.display_manager.matrix.width
h = self.display_manager.matrix.height
```

## Pattern A — size-tier branching (no core support needed)

The most common approach: pick fonts, sprite scales, and which rows to show based
on width/height thresholds. This works on any core.
[`plugins/ledmatrix-flights/renderer.py`](../../plugins/ledmatrix-flights/renderer.py)
is the clearest example — it chooses three font tiers from both height and width,
and auto-selects a `wide` vs `condensed` detail layout by a width threshold
(`widescreen_threshold`, default 256). Other examples:

- **masters-tournament** switches to a `compact` hole card below a height
  threshold (`_HOLE_COMPACT_HEIGHT = 48`).
- **baseball-scoreboard** hides the batter headshot and shows two compact lines
  "on tiny panels (e.g. 64×32)."
- **7-segment-clock, christmas-countdown, news, text-display, olympics,
  elections, odds-ticker** all branch on width/height.

A good rule from
[`CONTRIBUTING.md`](../../CONTRIBUTING.md): **scale up, don't just avoid
overflow** — content should grow to use a bigger panel, not sit tiny in the
corner.

## Pattern B — the `adaptive` layout engine (opt-in, core-assisted)

Newer cores ship `src.adaptive_layout`, a system that scales fonts, logos, and
element regions proportionally to the panel. Two plugins expose it today:
[`football-scoreboard`](../../plugins/football-scoreboard/config_schema.json) and
[`ledmatrix-music`](../../plugins/ledmatrix-music/config_schema.json).

### The `layout_mode` config key

The switch is a config key named **`layout_mode`** (an enum, marked
`x-advanced`), *not* `layout_engine` — that phrase only appears in the field's
description text.

```json
"layout_mode": {
  "type": "string",
  "enum": ["classic", "adaptive"],
  "default": "classic",
  "x-advanced": true,
  "description": "Layout engine. 'classic' is the original fixed layout. 'adaptive' (beta) scales fonts, logos, and element regions to the panel size. Falls back to classic on older cores."
}
```

- **`classic`** — the original fixed-pixel layout. Renders byte-identically to
  previous releases. This is the default.
- **`adaptive` (beta)** — scales content to the actual panel: bigger on large
  panels, degrading gracefully on small ones.

### How adaptive scaling works (football, the fullest example)

The core provides the primitives; the plugin composes them. Import them behind a
capability flag so the plugin still loads on an older core:

```python
try:
    from src.adaptive_layout import (LayoutContext, Region, scoreboard_regions,
                                     measure_ink, FitResult, FontStep)
    ADAPTIVE_AVAILABLE = True
except ImportError:
    ADAPTIVE_AVAILABLE = False
```

The renderer then:

- Builds a `LayoutContext` with a fixed `design_size` (e.g. `(128, 32)`).
- Computes named regions for the panel via
  `scoreboard_regions(Region(0, 0, width, height), ctx=...)` — `away_slot`,
  `home_slot`, `score_area`, `status_band`, `detail_band`.
- Scales logos to their slot with `ctx.fit_image(raw, slot, mode="fill_height",
  crop_to_ink=True, ...)`, loading raw logos unresized and caching per size.
- Sizes text **proportionally** (not "largest that fits"), scaled by height so a
  128×32 → 128×64 panel grows text the way logos grow, using
  `ctx.fit_text_proportional(...)` over "crisp" font ladders (TTF sizes that
  rasterize cleanly — e.g. PressStart2P only at multiples of its 8px grid).

`ledmatrix-music` does the equivalent, splitting the space above the progress bar
into three equal rows and picking the largest crisp font whose line height fits
each row. See
[`plugins/football-scoreboard/game_renderer.py`](../../plugins/football-scoreboard/game_renderer.py)
and [`plugins/ledmatrix-music/manager.py`](../../plugins/ledmatrix-music/manager.py).

### Adaptive preserves user customizations

Adaptive mode is designed to respect the [styling](./04-styling-and-skins.md)
settings a user set:

- **User-forced fonts win over auto-sizing.** If the configured font/size
  genuinely differs from the schema default, the plugin uses it as-is instead of
  auto-fitting. (Note: the web UI writes the full default object into config on
  every save, so mere *presence* of a font key isn't user intent — the plugin
  compares against the classic defaults / uses the resolver's `user_forced`
  flag.)
- **User x/y offsets still apply.** Each computed region is translated by the
  `customization.layout.<element>` `x_offset`/`y_offset` as a final step —
  adaptive even applies these in scroll mode, which classic scroll didn't.

### Graceful fallback

The whole system degrades safely. A plugin computes
`self._adaptive = ADAPTIVE_AVAILABLE and layout_mode == "adaptive"`. If the user
selects `adaptive` but the core lacks `src.adaptive_layout`, it logs a warning
and silently runs classic. The branch point returns "adaptive frame shown"
vs. "caller should draw its classic layout," so there's always a working path.

## Related layout concepts

- **`customization.layout` offset blocks** — most scoreboards define per-element
  `x_offset`/`y_offset` under `customization.layout`; these are the offsets
  adaptive honors.
- **flights `layout` / `widescreen_threshold`** — flights has its own
  compact/wide selection independent of `layout_mode`.
- **`design_size` in the manifest** — declare your layout's reference size (e.g.
  `"display": {"design_size": [128, 32]}`) so the harness and adaptive scaling
  know the baseline. Opt into strict fill checking via
  `test/harness.json` `{"fill_check": "strict"}` once your plugin is adaptive.

> The core's own `docs/ADAPTIVE_LAYOUT.md` is the authoritative reference for the
> `src.adaptive_layout` primitives (`self.layout`, `draw_fit`, `draw_image`,
> `scoreboard_regions`, font ladders). This page covers how plugins in *this*
> repo consume them.

**Next:** [Manifest & config schema →](./06-manifest-and-config-schema.md)
