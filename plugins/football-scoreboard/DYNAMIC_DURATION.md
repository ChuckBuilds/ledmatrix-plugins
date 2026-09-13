# Dynamic Cycle Duration

## Overview

The football scoreboard plugin supports both **dynamic cycle duration** (automatic calculation based on game count) and **fixed mode durations** (explicit time limits per mode). This provides flexibility to control display timing at different levels.

## Duration Types

### 1. Per-Game Duration
Controls how long each individual game displays **within a mode**.

**Configuration Keys:**
- `live_game_duration`: Seconds per live game (default: 30s)
- `recent_game_duration`: Seconds per recent game (default: 15s)
- `upcoming_game_duration`: Seconds per upcoming game (default: 15s)

**Example:** With `recent_game_duration: 15`, each recent game shows for 15 seconds before moving to the next.

### 2. Per-Mode Duration
Controls the **total time** a mode displays before rotating, regardless of game count.

**Configuration Keys** (per league, under `<league>.mode_durations`):
- `recent_mode_duration`: Total seconds for Recent mode (default: unset = dynamic)
- `upcoming_mode_duration`: Total seconds for Upcoming mode (default: unset = dynamic)
- `live_mode_duration`: Total seconds for Live mode (default: unset = dynamic)

> These keys are not in `config_schema.json`, so the web UI does not show
> them; add them to the plugin's config JSON by hand. They are read **only**
> inside a league's `mode_durations` block. A top-level
> `recent_mode_duration` is ignored.

**Example:** With `recent_mode_duration: 60` and `recent_game_duration: 15`, Recent mode shows 4 games (60s ÷ 15s = 4) before rotating.

### 3. Dynamic Calculation (Fallback)
When per-mode duration is **not set**, the plugin calculates duration dynamically.

**Formula:**
```
total_duration = sum(games_per_league × per_game_duration_for_league)
```

The duration is then clamped to configured min/max bounds if set.

## How Mode-Level Duration Works

### Basic Example

```json
{
  "nfl": {
    "recent_game_duration": 15,
    "mode_durations": { "recent_mode_duration": 60 }
  }
}
```

**Behavior:**
```
Recent Mode (60s total, 10 games available):
  ├─ Game 1 (0-15s) ✓
  ├─ Game 2 (15-30s) ✓
  ├─ Game 3 (30-45s) ✓
  ├─ Game 4 (45-60s) ✓
  └─ Time expires (60s) → Rotate to Upcoming Mode
     Games 5-10 NOT shown yet (progress preserved)
```

### Resume Functionality

When a mode times out before showing all games, it **resumes from where it left off** on the next cycle:

```
Cycle 1: Recent Mode (60s, 10 games available)
  ├─ Game 1 (0-15s) ✓
  ├─ Game 2 (15-30s) ✓
  ├─ Game 3 (30-45s) ✓
  ├─ Game 4 (45-60s) ✓
  └─ Time expires (60s) → Rotate to Upcoming Mode
     Progress: [game_1, game_2, game_3, game_4] preserved

Cycle 2: Upcoming Mode (60s)
  └─ ... (shows upcoming games)

Cycle 3: Recent Mode resumes
  ├─ Game 5 (0-15s) ✓ (continues from game 4, not restarting)
  ├─ Game 6 (15-30s) ✓
  ├─ Game 7 (30-45s) ✓
  ├─ Game 8 (45-60s) ✓
  └─ Time expires (60s) → Rotate to Upcoming Mode
     Progress: [game_1, game_2, game_3, game_4, game_5, game_6, game_7, game_8] preserved

Cycle 4: Recent Mode resumes again
  ├─ Game 9 (0-15s) ✓
  ├─ Game 10 (15-30s) ✓
  └─ All games shown → Full cycle complete → Reset progress for next cycle
```

**Key Points:**
- Progress tracking persists across mode rotations
- Only resets when full cycle completes (all games shown)
- No repetition of already-shown games when mode cycles back
- Mode start time resets when mode changes or full cycle completes

## Configuration

### Global Configuration
Set the default per-game duration for all modes:

```json
{
  "game_display_duration": 15
}
```

### Per-Mode Duration Configuration
Set explicit time limits for each mode. Mode durations are per league (see
the next sections); there is no top-level form:

```json
{
  "nfl": {
    "mode_durations": {
      "recent_mode_duration": 60,
      "upcoming_mode_duration": 60,
      "live_mode_duration": 90
    }
  }
}
```

**Behavior:**
- Recent mode: Shows games for 60 seconds total, then rotates
- Upcoming mode: Shows games for 60 seconds total, then rotates
- Live mode: Shows games for 90 seconds total, then rotates
- Games not shown due to time limits will resume on next cycle

### Per-League Configuration
Override durations for specific leagues:

```json
{
  "nfl": {
    "enabled": true,
    "live_game_duration": 20,
    "recent_game_duration": 15,
    "upcoming_game_duration": 10
  },
  "ncaa_fb": {
    "enabled": true,
    "live_game_duration": 25,
    "recent_game_duration": 15,
    "upcoming_game_duration": 12
  }
}
```

### Per-League Mode Duration Overrides
Override mode-level durations per league:

```json
{
  "nfl": {
    "enabled": true,
    "mode_durations": {
      "recent_mode_duration": 45,
      "upcoming_mode_duration": 30,
      "live_mode_duration": 60
    }
  },
  "ncaa_fb": {
    "enabled": true,
    "mode_durations": {
      "recent_mode_duration": 60,
      "upcoming_mode_duration": 45
    }
  }
}
```

**Multi-League Behavior:**
- If multiple leagues have different mode durations, the system uses the **maximum**
- Example: NFL=45s, NCAA FB=60s → uses 60s (ensures both leagues get their time)

### Duration Constraints (Min/Max)

You can set minimum and maximum duration constraints to ensure modes don't cycle too quickly (with few games) or stay too long (with many games):

```json
{
  "nfl": {
    "enabled": true,
    "dynamic_duration": {
      "enabled": true,
      "min_duration_seconds": 30,
      "max_duration_seconds": 180,
      "modes": {
        "live": {
          "min_duration_seconds": 45,
          "max_duration_seconds": 300
        },
        "recent": {
          "min_duration_seconds": 30,
          "max_duration_seconds": 120
        },
        "upcoming": {
          "min_duration_seconds": 20,
          "max_duration_seconds": 90
        }
      }
    }
  }
}
```

#### Constraint Behavior

| Setting | Description |
|---------|-------------|
| `min_duration_seconds` | Mode will display for at least this long, even with few games |
| `max_duration_seconds` | Mode will not exceed this duration, even with many games |

**Example with constraints:**
- 1 game × 15s = 15s calculated
- `min_duration_seconds: 30` configured
- **Final duration: 30s** (clamped up to minimum)

### Configuration Hierarchy

**For Per-Game Duration:**
1. **Most Specific**: `config.nfl.live_game_duration`
2. **Fallback**: `config.game_display_duration`

**For Per-Mode Duration:**
1. **Only source**: `config.nfl.mode_durations.recent_mode_duration` (per league)
2. **Fallback**: Dynamic calculation (games × per_game_duration)

**For Duration Constraints:**
1. **Most Specific**: `config.nfl.dynamic_duration.modes.live.min_duration_seconds`
2. **Per-League**: `config.nfl.dynamic_duration.min_duration_seconds`
3. **Fallback**: No constraint (use calculated duration)

## Integration with Dynamic Duration Caps

If you have dynamic duration caps configured:

```json
{
  "nfl": {
    "dynamic_duration": {
      "enabled": true,
      "max_duration_seconds": 120
    }
  }
}
```

**Integration Logic:**
- If both mode duration and dynamic cap are set: uses **minimum**
- Example: `recent_mode_duration: 180`, `max_duration_seconds: 120` → uses 120s
- Ensures dynamic caps are always respected

## Mode-Specific Durations

Each mode type can have its own duration:

| Mode Type | Configuration Key | Use Case |
|-----------|------------------|----------|
| **Live** | `live_game_duration` | Games currently in progress |
| **Recent** | `recent_game_duration` | Recently completed games |
| **Upcoming** | `upcoming_game_duration` | Future scheduled games |

## Integration with Display Controller

The plugin provides a `get_cycle_duration(display_mode)` method that the display controller can call to get the expected duration:

```python
# Display controller calls this for granular modes
duration = plugin.get_cycle_duration("nfl_recent")
# Returns: 30.0 (for 2 games @ 15s each, or min_duration if higher)

duration = plugin.get_cycle_duration("ncaa_fb_upcoming")
# Returns: 45.0 (for 3 games @ 15s each)
```

## Architecture: Controller vs Internal Cycling

### Recommended Architecture

The football scoreboard plugin is designed for the LEDMatrix display controller to manage
mode rotation. The controller:

1. Calls `plugin.display(display_mode="nfl_live", force_clear=True)` with specific mode
2. Queries `plugin.get_cycle_duration("nfl_live")` for timing
3. Handles live priority via `has_live_priority()` and `has_live_content()`

### Internal Cycling (Deprecated)

When `display()` is called without `display_mode`, the plugin uses internal mode cycling.
This is **deprecated** and exists only for legacy/testing support.

**Why it's deprecated:**
- Duplicates controller timing logic
- Previously used fixed duration, ignoring dynamic calculations (fixed in v2.x)
- Creates two competing timing systems

### Live Priority vs Dynamic Duration

These features serve different purposes and work together:

| Feature | Purpose | Value Type |
|---------|---------|------------|
| `live_priority` | "Stay on live mode while content exists" | Boolean signal |
| `get_cycle_duration()` | "How long content takes to display" | Numeric (seconds) |

The controller uses both:
- If `has_live_priority() and has_live_content()`: Don't rotate away from live mode
- Query `get_cycle_duration()` for logging/metrics regardless of priority

**Example interaction:**
```python
# Controller logic (simplified)
if plugin.has_live_priority() and plugin.has_live_content():
    # Don't rotate, but still query duration for logging
    duration = plugin.get_cycle_duration("nfl_live")
    logger.info(f"Live priority active, staying on nfl_live (duration={duration}s)")
else:
    # Normal rotation using dynamic duration
    duration = plugin.get_cycle_duration(current_mode)
    # Rotate after duration expires
```

## Benefits

1. **Automatic Scaling**: Duration adjusts based on available games (dynamic mode)
2. **Predictable Rotation**: Fixed mode durations ensure consistent timing (mode duration)
3. **Resume Functionality**: Games continue from where they left off (no repetition)
4. **Consistent Display Time**: Each game gets equal viewing time
5. **Flexible Configuration**: Set different durations per league and mode
6. **Prevents Premature Cycling**: Mode stays active until time expires or all games shown
7. **Dynamic Integration**: Mode durations work seamlessly with dynamic caps
8. **Duration Bounds**: Min/max constraints prevent too-short or too-long displays

## Example Scenarios

### Scenario 1: Fixed Mode Duration with Truncation
- **Configuration**: `recent_mode_duration: 60`, `recent_game_duration: 15`
- **Games Available**: 10 recent games
- **Behavior**: Shows 4 games (60s ÷ 15s), then rotates. Resumes with game 5 next cycle.
- **Total Duration**: 60 seconds

### Scenario 2: Dynamic Calculation (No Mode Duration Set)
- **Configuration**: TB and DAL as favorites, 15s per game, no mode duration
- **Games Available**: 2 games (TB, DAL)
- **Behavior**: Shows both games (2 × 15s)
- **Total Duration**: 30 seconds (dynamic)

### Scenario 3: Mode Duration with Dynamic Cap
- **Configuration**: `recent_mode_duration: 180`, `max_duration_seconds: 120`, 15s per game
- **Games Available**: 10 games
- **Behavior**: Cap applies → 120s total (shows 8 games)
- **Total Duration**: 120 seconds (min of 180 and 120)

### Scenario 4: Granular Modes with Resume
- **Configuration**: `nfl_recent` @ 15s/game, `ncaa_fb_recent` @ 15s/game, `recent_mode_duration: 60`
- **Games**: 20 NFL games, 30 NCAA FB games
- **Display Controller Rotation**: `nfl_recent` → `nfl_upcoming` → `ncaa_fb_recent` → `ncaa_fb_upcoming` → ...
- **Cycle 1 (nfl_recent)**: Shows NFL games 1-4 (60s) → rotates to next mode
- **Cycle 2 (ncaa_fb_recent)**: Shows NCAA FB games 1-4 (60s) → rotates
- **Cycle 3 (nfl_recent resumes)**: Shows NFL games 5-8 → continues until all NFL shown
- **Cycle 4 (ncaa_fb_recent resumes)**: Shows NCAA FB games 5-8 → continues across cycles
- **Total Cycles**: ~13 cycles to show all games (4 per 60s cycle per mode)

### Scenario 5: Single Favorite Team with Min Duration
- **Configuration**: TB as favorite, 15s per game, `min_duration_seconds: 30`
- **Games Available**: 1 TB game in recent
- **Calculated Duration**: 1 × 15s = 15 seconds
- **Final Duration**: **30 seconds** (clamped up to minimum)

### Scenario 6: Full League with Max Duration
- **Configuration**: Show all NFL games, 10s per game, `max_duration_seconds: 120`
- **Games Available**: 16 games this week
- **Calculated Duration**: 16 × 10s = 160 seconds
- **Final Duration**: **120 seconds** (clamped down to maximum)

### Scenario 7: Per-League Mode Duration Overrides
- **Configuration**:
  - NFL: `mode_durations.recent_mode_duration: 45` (for `nfl_recent`)
  - NCAA FB: `mode_durations.recent_mode_duration: 60` (for `ncaa_fb_recent`)
- **Behavior**:
  - `nfl_recent` uses 45s
  - `ncaa_fb_recent` uses 60s
  - Each granular mode has its own independent duration

### Scenario 8: Mixed Leagues (Weighted Calculation)
- **Configuration**: NFL @ 15s/game, NCAA FB @ 12s/game
- **Mode**: a combined Recent cycle over both leagues (the plugin registers
  only per-league modes such as `nfl_recent`; there is no `football_recent`
  display mode, and the code only keeps a legacy fallback for that name)
- **Games**: 2 NFL + 3 NCAA FB = 5 total
- **Total Duration**: (2 × 15s) + (3 × 12s) = **66 seconds**

This correctly weights each league's games by their configured duration, rather than applying a single duration to all games.

## Technical Details

### Method Signature
```python
def get_cycle_duration(self, display_mode: str = None) -> Optional[float]:
    """
    Calculate the expected cycle duration for a display mode.

    Priority order:
    1. Mode-level duration (if configured)
    2. Dynamic calculation (if no mode-level duration)
    3. Apply min/max duration constraints
    4. Dynamic duration cap applies to both if enabled

    Args:
        display_mode: The granular mode name (e.g., 'nfl_live', 'nfl_recent', 'ncaa_fb_upcoming')

    Returns:
        Total duration in seconds (clamped to min/max if configured),
        or None if not applicable
    """
```

### Return Values
- **Positive Number**: Total calculated duration in seconds
- **None**: No games available for this mode (controller should skip)

### Duration Resolution Logic

**For Mode-Level Duration (Granular Modes):**
1. Check the league's override: `config.nfl.mode_durations.recent_mode_duration` (for `nfl_recent`)
2. If both mode duration and dynamic cap exist: `min(mode_duration, dynamic_cap)`
3. If neither, use dynamic calculation

**For Dynamic Calculation (Granular Modes):**
1. Count games from the specific league (e.g., only NFL games for `nfl_recent`)
2. Get per-game duration for that league
3. Calculate: `total_games × per_game_duration`
4. Apply min/max duration constraints if configured
5. Apply dynamic duration cap if enabled

### Progress Tracking

The plugin uses `_dynamic_manager_progress` to track which games have been shown:

```python
# Format: {manager_key: {game_id_1, game_id_2, ...}}
_dynamic_manager_progress: Dict[str, Set[str]] = {}
```

**Behavior:**
- Game IDs are added when a game completes its full display duration
- Progress persists across mode rotations (for resume functionality)
- Progress resets when full cycle completes (all games shown)

### Mode Start Time Tracking

The plugin tracks when each mode started displaying:

```python
# Format: {display_mode: start_time}
_mode_start_time: Dict[str, float] = {}
```

**Behavior:**
- Set when mode first displays
- Used to check if mode duration has expired
- Reset when mode changes or full cycle completes
- Not cleared on time expiry (preserves for resume)

### Game Filtering
The calculation automatically filters out:
- **Live mode**: Games marked as final
- **Live mode**: Games that appear to be over (stuck clock, final period)
- **All modes**: Games not matching favorite team filters (if configured)

## Logging

When enabled, the plugin logs cycle duration calculations:

```
INFO - get_cycle_duration: using mode-level duration for nfl_recent = 60s
INFO - get_cycle_duration: nfl recent has 2 games, per_game_duration=15s
INFO - get_cycle_duration: nfl_recent = 2 games × 15s = 30s
INFO - Mode duration expired for nfl_recent: 60.2s >= 60s. Rotating to next mode (progress preserved for resume).
```

When min/max clamping occurs:
```text
INFO - get_cycle_duration: clamped 15s up to min_duration=30s
INFO - get_cycle_duration: clamped 160s down to max_duration=120s
```

For mixed leagues:
```text
INFO - get_cycle_duration(<combined recent>): mixed leagues - nfl: 2 × 15s = 30s, ncaa_fb: 3 × 12s = 36s = 66s total
```

## Migration from Fixed Duration

### Before (Fixed Duration)
```json
{
  "display_duration": 30  // Always 30s regardless of games
}
```

### After (Dynamic Duration)
```json
{
  "game_display_duration": 15,  // 15s per game, scales automatically
  "nfl": {
    "dynamic_duration": {
      "min_duration_seconds": 30,  // Never less than 30s
      "max_duration_seconds": 180  // Never more than 3 minutes
    }
  }
}
```

### After (Fixed Mode Duration)
```json
{
  "game_display_duration": 15,     // 15s per game within each mode
  "nfl": {
    "mode_durations": {
      "recent_mode_duration": 60,  // 60s total for nfl_recent
      "upcoming_mode_duration": 60,
      "live_mode_duration": 90
    }
  }
}
```

**Benefits of Mode Duration:**
- Predictable rotation timing
- Resume functionality (no repetition)
- Works with dynamic caps
- Scales to large game counts

The display controller's dynamic duration system will automatically use `get_cycle_duration()` to calculate the proper duration.

## Troubleshooting

### Mode Not Rotating
- **Symptom**: Stuck on one mode for very long time
- **Cause**: Too many games with dynamic calculation (no mode duration set)
- **Solution**: Set `recent_mode_duration`, `upcoming_mode_duration`, `live_mode_duration` inside the league's `mode_durations` block

### Games Repeating
- **Symptom**: Same games show every cycle
- **Cause**: Progress tracking not working
- **Solution**: Check logs for "progress preserved" messages, ensure dynamic duration is enabled

### Mode Duration Not Working
- **Symptom**: Mode doesn't rotate after configured time
- **Cause**: Dynamic cap may be overriding
- **Solution**: Check if `max_duration_seconds` is set lower than mode duration

### Games Skipped
- **Symptom**: Not all games are shown
- **Cause**: Mode duration too short for game count
- **Solution**: Increase mode duration or decrease per-game duration

### Duration Too Short
- **Symptom**: Mode cycles away too quickly with few games
- **Cause**: No minimum duration configured
- **Solution**: Set `min_duration_seconds` in `dynamic_duration` config
