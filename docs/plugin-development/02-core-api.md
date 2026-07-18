# 2. The Core API Surface

[← Guide index](./README.md) · [← Plugin anatomy](./01-plugin-anatomy.md)

`super().__init__(...)` wires five objects onto your plugin. Everything you can
call "from the main project" flows through these. This page is the reference for
what each provides.

| Attribute | What it is |
|-----------|------------|
| `self.plugin_id` | Your plugin's id — use it to namespace fonts and cache keys |
| `self.config` | Your plugin's config dict (from the web UI / config file) |
| `self.logger` | A standard Python logger scoped to your plugin |
| `self.display_manager` | The render surface — draw text/images, push frames |
| `self.cache_manager` | Shared network/data cache — use it for anything fetched |
| `self.plugin_manager` | Access to shared services: `font_manager`, `config_manager`, other plugins |

The base class also derives some convenience values from config that most plugins
read directly: `self.enabled` (default `True`), `self.display_duration`,
`self.update_interval`, and `self.global_config` (the `global` config block,
where cross-cutting settings like `target_fps` live).

## `self.logger`

A ready-to-use logger. Prefer it over `print`. Use `exc_info=True` on caught
exceptions so tracebacks reach the log:

```python
self.logger.info("Weather updated")
self.logger.error(f"Fetch failed: {e}", exc_info=True)
```

## `self.config`

Your plugin's resolved config dict. Read with `.get(key, default)`, and **mirror
the `default` from your `config_schema.json`** so behavior matches the form even
when a key is absent (see [topic 6](./06-manifest-and-config-schema.md)).

```python
self.update_interval = config.get("update_interval", 3600)
self.show_time = config.get("show_time", True)
```

## `self.display_manager`

The drawing surface. The most common members:

| Member | Purpose |
|--------|---------|
| `.width` / `.height` | Logical panel dimensions in pixels |
| `.matrix` | The raw matrix handle — `.matrix.width` / `.matrix.height` give live panel size |
| `.image` | The PIL image buffer you can draw onto directly |
| `.draw` | A PIL `ImageDraw` handle for the current buffer |
| `.clear()` | Clear the buffer |
| `.draw_text(text, x=, y=, color=, font=)` | Draw a string |
| `.update_display()` | **Push the buffer to the panel — call this at the end of `display()`** |
| `.get_text_width(text, font=)` | Measure text for centering / fitting |
| `.get_font_height(font=)` | Measure line height |
| `.small_font` / `.extra_small_font` / `.regular_font` | Pre-loaded fonts you can use without registering your own |

Scrolling plugins additionally coordinate with the core loop through
`.set_scrolling_state(...)`, `.is_currently_scrolling`, `.defer_update(...)`, and
`.process_deferred_updates()` — see [topic 3](./03-advanced-features.md#high-fps--smooth-scrolling).

Two rendering styles coexist: draw with `draw_text` for simple text (like
[`hello-world`](../../plugins/hello-world/manager.py)), or build a PIL image and
assign it to `self.display_manager.image` for complex layouts (like the
scoreboards). Either way, finish with `update_display()`.

## `self.cache_manager`

The shared cache. **Use it for anything you fetch over the network** so restarts
and multiple plugins don't re-hit APIs. Fetch in `update()`, never in
`display()`.

| Method | Purpose |
|--------|---------|
| `get(key, max_age=<seconds>)` | Return the cached value, or `None` if missing/older than `max_age` |
| `set(key, value, ttl=<seconds>)` | Store a value with an optional time-to-live |
| `get_cached_data_with_strategy(key, strategy)` | Strategy-driven read (e.g. `'leaderboard'`) that layers a TTL/refresh policy on top of raw get/set |
| `save_cache(key, data)` | Strategy-driven write partner to the above |
| `get_with_auto_strategy(...)` | Auto-selected strategy variant |
| `delete(key)` / `clear_cache()` | Invalidate one key / everything |

**Always namespace keys with your plugin id** so they never collide with another
plugin's entries:

```python
key = f"{self.plugin_id}:standings:{league}"
data = self.cache_manager.get(key, max_age=self.update_interval)
if data is None:
    data = fetch_standings(league)
    self.cache_manager.set(key, data, ttl=self.update_interval)
```

The strategy-based API is worth it for anything with a real refresh policy — see
[`plugins/ledmatrix-leaderboard/data_fetcher.py`](../../plugins/ledmatrix-leaderboard/data_fetcher.py)
for `get_cached_data_with_strategy` / `save_cache` in practice.

## `self.plugin_manager`

Access to shared, cross-plugin services:

| Member | Purpose |
|--------|---------|
| `.font_manager` | The shared font registry (below) |
| `.config_manager` | The core config manager |
| `.get_plugin(id)` | Look up another loaded plugin (rare — e.g. stock-news syncing with stocks) |

**Guard access to newer members** — older cores may not have them:

```python
if hasattr(self.plugin_manager, "font_manager"):
    ...
```

## Fonts: `self.plugin_manager.font_manager`

The font manager lets you register named fonts once and fetch them per frame.
This is also what the [styling system](./04-styling-and-skins.md) feeds
user-customized fonts/sizes/colors into.

**Register in `__init__`** (parameter order `manager_id, element_key, family,
size_px, color`):

```python
fm = self.plugin_manager.font_manager
fm.register_manager_font(
    manager_id=self.plugin_id,
    element_key=f"{self.plugin_id}.message",   # dot-separated, plugin-id-prefixed
    family="press_start",
    size_px=10,
    color=self.color,                          # RGB tuple
)
```

**Fetch in `display()`:**

```python
message_font = fm.get_font(f"{self.plugin_id}.message")
self.display_manager.draw_text(self.message, x=..., y=..., font=message_font)
```

The `element_key` convention is `f"{self.plugin_id}.<element>"` — prefixing with
the plugin id avoids collisions with other plugins' registered fonts. Common
families seen across plugins include `press_start` and `four_by_six`. Provide a
local fallback font (e.g. a bundled BDF loaded with `freetype`) for cores whose
font manager is missing — [`hello-world`](../../plugins/hello-world/manager.py)
does exactly this.

**Next:** [Advanced features →](./03-advanced-features.md)
