# 4. Styling & Skins

[← Guide index](./README.md) · [← Advanced features](./03-advanced-features.md)

"Skinning" is letting users customize how your plugin's text looks — fonts,
sizes, colors, and pixel offsets — from the web-UI config form, without touching
code. There are **two** mechanisms in this monorepo, plus a family of `x-`
extensions that shape the config form itself.

---

## Two ways to expose per-element styling

### A) The manual `customization` block (widely used)

The older, explicit form: a `customization` object in `config_schema.json` with
one sub-object per text element, each declaring `font`, `font_size`, and
`text_color`. About 17 plugins use a `customization` block. The canonical
per-element shape (from
[`plugins/clock-simple/config_schema.json`](../../plugins/clock-simple/config_schema.json),
element `time_text`):

```json
"time_text": {
  "type": "object",
  "x-propertyOrder": ["font", "font_size", "text_color"],
  "additionalProperties": false,
  "properties": {
    "font":       { "type": "string", "enum": ["PressStart2P-Regular.ttf", "4x6-font.ttf", "..."], "x-advanced": true },
    "font_size":  { "type": "integer", "minimum": 4, "maximum": 16, "default": 8, "x-advanced": true },
    "text_color": { "type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 255},
                    "minItems": 3, "maxItems": 3, "default": [255, 255, 255] }
  }
}
```

Your code then reads `config["customization"]["time_text"]["font_size"]` etc. and
feeds those into font registration / drawing. This is fully self-contained — it
works on any core.

### B) The `x-style-elements` shorthand (newer, core-assisted)

The compact form: instead of hand-writing each element object, you declare a
single `x-style-elements` map on the `customization` object, and a **newer core**
expands it into the full per-element style UI and a resolver. Only
[`plugins/of-the-day`](../../plugins/of-the-day/config_schema.json) uses it today
— it's the reference implementation.

```json
"customization": {
  "type": "object",
  "title": "Display Customization",
  "description": "... Requires a LEDMatrix core with the element-style system; older cores fall back to classic styling ...",
  "x-style-elements": {
    "title_text": {
      "title": "Title",
      "font":  { "default": "PressStart2P-Regular.ttf" },
      "size":  { "default": 8, "min": 4, "max": 16 },
      "color": { "default": [255, 255, 255] },
      "offsets": true
    },
    "body_text": {
      "title": "Body Text",
      "font":  { "default": "4x6-font.ttf" },
      "size":  { "default": 6, "min": 4, "max": 12 },
      "color": { "default": [200, 200, 200] },
      "offsets": true
    }
  }
}
```

Per-element sub-fields:

| Field | Meaning |
|-------|---------|
| `title` | Human label for the element in the UI |
| `font.default` | Default font filename |
| `size.default` / `size.min` / `size.max` | Default size in px and clamp bounds |
| `color.default` | Default RGB `[R, G, B]` (0–255) |
| `offsets: true` | Enables user-adjustable x/y pixel offsets (default `(0, 0)`) |

### Reading resolved style values at render time

The `x-style-elements` path is powered by the core's `src.element_style` module —
**not in this repo** — so import it defensively and keep a classic fallback:

```python
try:
    from src.element_style import ElementStyleResolver, defaults_from_schema_file
    STYLE_AVAILABLE = True
except ImportError:
    STYLE_AVAILABLE = False
```

At render time, build a resolver from the plugin's own schema and ask it for each
element, passing the **classic** defaults as fallback so an untouched config
renders byte-identically to the old styling:

```python
resolver = ElementStyleResolver(self.config, defaults_from_schema_file(schema_path))
title = resolver.style("title_text", classic_font="PressStart2P-Regular.ttf",
                       classic_size=8, classic_color=self.title_color)
# title.font (loaded font), title.color (RGB), title.offset (x, y)
title_x = (width - title_width) // 2 + title.offset[0]
title_y = margin_top + title.offset[1]
self.display_manager.draw_text(text, x=title_x, y=title_y, color=title.color, font=title.font)
```

See [`plugins/of-the-day/manager.py`](../../plugins/of-the-day/manager.py) for the
full `_element_styles()` helper, including the `STYLE_AVAILABLE == False` fallback
that loads bundled fonts directly with offset `(0, 0)`.

> **Which should I use?** For a new plugin, the manual `customization` block is
> the safe, universally-compatible choice. Reach for `x-style-elements` when you
> want the richer core-driven style UI (with offsets) and are targeting a core
> that ships `src.element_style`.

---

## `x-` config-form extensions

Beyond styling, the web UI honors a family of custom `x-` keys in
`config_schema.json`. They're all optional and standard-JSON-Schema-compatible
(validators ignore unknown `x-` keys). The ones in active use:

| Extension | Shape | What it does |
|-----------|-------|--------------|
| `x-advanced` | `true` on a property | Hides the field behind the form's **Advanced Settings** disclosure. By far the most used — reach for it on fine-tuning knobs (intervals, pixel offsets, layout tweaks) |
| `x-propertyOrder` | array of child keys | Explicit render order of an object's properties |
| `x-widget` | string | Picks a custom editor widget (see below) |
| `x-collapsed` | `true` | Renders a section collapsed by default |
| `x-secret` / `x-sensitive` | `true` | Masks the value in the UI (API keys, passwords) |
| `x-options` | `{ "labels": { value: label } }` | Friendly display labels for enum / checkbox items |
| `x-upload-config` | object | File-upload endpoint + limits for a `file-upload` widget |
| `x-widget-config` | object | Config payload for a complex widget (e.g. `plugin-file-manager`) |
| `x-columns` | array | Column keys for the `array-table` widget |
| `x-placeholder` | string | Input placeholder text |
| `x-display` | string (e.g. `"hidden"`) | Field display mode |

### `x-widget` values seen in the wild

`color-picker` (the common one), `checkbox-group`, `file-upload` /
`file-upload-single`, `array-table`, `radio`, `select`, `time-picker`,
`date-picker`, `schedule`, `tag-input`, `custom-feeds`, `plugin-file-manager`,
`google-calendar-picker`.

Examples: `color-picker` in
[`plugins/baseball-scoreboard/config_schema.json`](../../plugins/baseball-scoreboard/config_schema.json);
`file-upload` + `x-upload-config` in
[`plugins/calendar/config_schema.json`](../../plugins/calendar/config_schema.json);
`plugin-file-manager` + `x-widget-config` in
[`plugins/of-the-day/config_schema.json`](../../plugins/of-the-day/config_schema.json).

### Using `x-advanced` well

Most users should see a short, friendly form. Put everything that's fine-tuning —
update intervals, pixel offsets, per-frame delays, layout constants — behind
`x-advanced: true`, and leave only the meaningful choices (enable, favorites,
duration, colors) at the top level.

```json
"update_interval": {
  "type": "integer", "default": 3600, "minimum": 60,
  "description": "Seconds between data refreshes",
  "x-advanced": true
}
```

**Next:** [Adaptive layout →](./05-adaptive-layout.md)
