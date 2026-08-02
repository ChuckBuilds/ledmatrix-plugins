# 3. Advanced Features

[← Guide index](./README.md) · [← Core API](./02-core-api.md)

These are the opt-in capabilities that make a plugin feature-rich. Each works by
implementing a hook method the core looks for, or by reading a config key — a
plugin participates in a feature only when it opts in. The sports scoreboards
(`hockey-scoreboard`, `football-scoreboard`, `baseball-scoreboard`, …) are the
best reference implementations and exercise nearly all of them.

Because these hooks live in newer cores, **guard any import of an optional core
symbol** (like `VegasDisplayMode`) with `try/except ImportError` and fall back —
so your plugin still loads on an older core.

---

## Dynamic duration

By default the core shows a plugin for a fixed `display_duration`. Dynamic
duration lets a plugin say "hold my screen for a computed time instead" — long
enough to finish a scroll, or to keep a live game up. You opt in by implementing
`supports_dynamic_duration()`; the rest of the family lets the core size and end
the turn.

| Hook | Signature | Role |
|------|-----------|------|
| `supports_dynamic_duration` | `(self) -> bool` (or `(self, mode_type=None)`) | Gate — return `True` to opt in |
| `get_display_duration` | `(self) -> float` | The computed seconds to display |
| `get_cycle_duration` | `(self, display_mode=None) -> Optional[float]` | Per-mode duration for one full cycle |
| `get_dynamic_duration` | `(self) -> int` | Simple computed duration (alt to the above) |
| `get_dynamic_duration_cap` | `(self) -> Optional[float]` | Upper bound the core will wait |
| `get_dynamic_duration_floor` | `(self) -> Optional[float]` | Lower bound |
| `is_cycle_complete` | `(self) -> bool` | Tell the core the scroll/animation finished |
| `reset_cycle_state` | `(self) -> None` | Reset between turns (call `super()` if you override) |

A common shape (see
[`plugins/ledmatrix-stocks/manager.py`](../../plugins/ledmatrix-stocks/manager.py)):
`supports_dynamic_duration` gates it, `get_cycle_duration` / `get_display_duration`
return the computed seconds, `get_dynamic_duration_cap` bounds how long the
controller waits, and `reset_cycle_state` / `is_cycle_complete` let the core
detect when a scroll has finished so it can move on.

Config side: plugins expose a `dynamic_duration` object (typically `enabled`,
`max_duration_seconds`, and per-mode settings). See
[`plugins/football-scoreboard/DYNAMIC_DURATION.md`](../../plugins/football-scoreboard/DYNAMIC_DURATION.md)
for the fullest treatment.

---

## Live priority & rotation

Sports plugins can prefer **live** games over scheduled or recent ones. This is
driven by a per-source `live_priority` boolean in config
(`config[<league>]["live_priority"]`) plus a few hook methods the core uses to
build the live rotation.

| Hook | Signature | Role |
|------|-----------|------|
| `get_live_modes` | `(self) -> list[str]` | Which of this plugin's modes represent live content |
| `has_live_priority` | `(self) -> bool` | Is live priority enabled anywhere? |
| `has_live_content` | `(self) -> bool` | Are there actually live games right now? |

When `live_priority` is on **and** real live games exist, the manager surfaces
only the live content; when nothing is live it falls back to the normal schedule.
Wire it up by reading the flag in `__init__` and filtering your display list in
the update/selection logic — see the `nhl_live_priority` handling in
[`plugins/hockey-scoreboard/manager.py`](../../plugins/hockey-scoreboard/manager.py).

Related live-rotation knobs the sports plugins expose in config:

- **`favorite_live_boost`** — how many rotation turns your favorite team's live
  game gets for every one turn other live games get; the favorite is also queued
  first whenever the live rotation refreshes. Set to `1` for even rotation.
- **`non_favorite_live` / live-duration overrides** — different display durations
  for favorite vs. non-favorite live games.

---

## High-FPS / smooth scrolling

Scrolling plugins render much faster than the default loop for smooth motion.
There are three mechanisms, used together:

1. **Global target FPS.** Read it from the global config and push it into your
   scroll helper, with a clamp fallback for older cores:

   ```python
   target_fps = self.global_config.get("target_fps") or self.global_config.get("scroll_target_fps", 100)
   if hasattr(self.scroll_helper, "set_target_fps"):
       self.scroll_helper.set_target_fps(target_fps)
   else:  # older ScrollHelper
       self.scroll_helper.target_fps = max(30.0, min(200.0, target_fps))
       self.scroll_helper.frame_time_target = 1.0 / self.scroll_helper.target_fps
   ```

   See [`plugins/odds-ticker/manager.py`](../../plugins/odds-ticker/manager.py),
   [`plugins/news/manager.py`](../../plugins/news/manager.py), and
   [`plugins/ledmatrix-leaderboard/manager.py`](../../plugins/ledmatrix-leaderboard/manager.py).

2. **Per-frame delay.** The `scroll_delay` config key (seconds per frame; `0.01`
   ≈ 100 FPS, lower = smoother) controls smoothness on the scoreboards.

3. **Per-plugin high-performance flag.** Some plugins expose their own toggle,
   e.g. `high_performance_transitions` in
   [`plugins/christmas-countdown/config_schema.json`](../../plugins/christmas-countdown/config_schema.json)
   switches 120 FPS transitions vs. 30 FPS.

Scrolling plugins also coordinate with the loop through the display manager's
`set_scrolling_state`, `defer_update`, and `process_deferred_updates` so the core
knows a scroll is in progress.

### Scroll-speed key semantics (know which one you're using)

Historically, plugins adopted `scroll_speed` with **three incompatible unit
semantics**. They cannot be renamed without breaking users' saved configs, so
the rule is: keep your plugin's existing semantics, document them in the key's
`description`, and pick semantics (1) for new plugins.

1. **Pixels per frame** (`scroll_speed` ≈ 0.5–5, typically `1.0`) paired with
   `scroll_delay` in seconds per frame (`0.01` ≈ 100 FPS). Used by
   `text-display`, `ledmatrix-elections`, `ledmatrix-stocks`, `odds-ticker`,
   `news`, `march-madness`, `stock-news`. Effective speed =
   `scroll_speed / scroll_delay` px/s.
2. **Pixels per second** (`scroll_speed` ≈ 30–50). Used by the sports
   scoreboards (their `scroll_display.py` converts internally via
   `pixels_per_frame = scroll_speed * scroll_delay`) and `mqtt-notifications`
   (delta-time integration).
3. **Frames-per-step divisor** (`scroll_speed` ≈ 1–20, **higher = slower** —
   inverted!). The marquee advances one pixel every N core frames. Used by
   `incoming-packages`, `jellyfin-now-playing`, and `ledmatrix-music`
   (`text_scrolling.*.speed`).

`target_fps` (mechanism 1 above) is orthogonal: it paces how often frames
render, not how far each frame moves. Mark all of these keys `x-advanced` in
your schema — they are fine-tuning knobs.

---

## Vegas mode (continuous marquee)

"Vegas" is the core's continuous marquee that stitches multiple plugins into one
endlessly-scrolling strip. A plugin opts in by implementing:

| Hook | Signature | Role |
|------|-----------|------|
| `get_vegas_content` | `(self) -> Optional[list[Image]]` | The PIL image(s) to splice into the strip, or `None` |
| `get_vegas_content_type` | `(self) -> str` | `'single'` or `'multi'` (multiple scrollable items, e.g. games) |
| `get_vegas_display_mode` | `(self) -> VegasDisplayMode` | How this plugin behaves in the strip |
| `get_supported_vegas_modes` | `(self) -> list[VegasDisplayMode]` | (Optional) modes the plugin supports |

Import the enum defensively — older cores don't ship it:

```python
try:
    from src.plugin_system.base_plugin import BasePlugin, VegasDisplayMode
except ImportError:
    VegasDisplayMode = None
```

The `vegas_mode` config key (mark it `x-advanced`) overrides the display mode and
is an enum:

- `scroll` — items scroll individually through the stream (default)
- `fixed` — the whole display scrolls by as one block
- `static` — the marquee pauses while the plugin shows for its duration

`get_vegas_display_mode` should honor the config override, falling back to the
plugin's natural default:

```python
def get_vegas_display_mode(self):
    if VegasDisplayMode:
        mode = self.config.get("vegas_mode")
        if mode:
            try:
                return VegasDisplayMode(mode)
            except ValueError:
                self.logger.warning(f"Invalid vegas_mode '{mode}', using SCROLL")
        return VegasDisplayMode.SCROLL
    return "scroll"
```

See the Vegas section of
[`plugins/hockey-scoreboard/manager.py`](../../plugins/hockey-scoreboard/manager.py)
and the `vegas_mode` config declarations in
[`plugins/nfl-draft/config_schema.json`](../../plugins/nfl-draft/config_schema.json)
and [`plugins/olympics/config_schema.json`](../../plugins/olympics/config_schema.json).
[`plugins/calendar/manager.py`](../../plugins/calendar/manager.py) shows
`get_supported_vegas_modes` returning multiple modes.

---

## Config & enable lifecycle hooks

The core notifies plugins of state changes through three optional hooks:

| Hook | Signature | Fires when |
|------|-----------|-----------|
| `on_config_change` | `(self, new_config) -> None` | The user saves new config (call `super()` if you override) |
| `on_enable` | `(self) -> None` | The plugin is enabled |
| `on_disable` | `(self) -> None` | The plugin is disabled |

`on_config_change` is where you re-read config and recompute derived state so a
change takes effect without a restart — e.g.
[`plugins/ledmatrix-music/manager.py`](../../plugins/ledmatrix-music/manager.py)
recomputes its layout mode there so a runtime switch isn't ignored.

**Next:** [Styling & skins →](./04-styling-and-skins.md)
