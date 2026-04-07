# Plugin Verification Checklist

Use this checklist when reviewing plugin submissions.

## Code Review

- [ ] Follows BasePlugin interface
- [ ] Has proper error handling
- [ ] Uses logging appropriately
- [ ] No hardcoded secrets/API keys
- [ ] Follows Python coding standards
- [ ] Has type hints where appropriate
- [ ] Has docstrings for classes/methods

## Manifest Validation

- [ ] All required fields present (`id`, `name`, `version`, `class_name`,
      `display_modes`)
- [ ] `class_name` matches the actual class name in the entry point
      (case-sensitive, no spaces) — the loader does
      `getattr(module, class_name)` and will fail with `AttributeError`
      otherwise
- [ ] `entry_point` either matches the real file name or is omitted
      (defaults to `manager.py`)
- [ ] `id` matches the directory name
- [ ] Valid JSON syntax
- [ ] Correct version format (semver)
- [ ] `version` field matches the latest entry in the `versions[]` array
- [ ] `last_updated` matches the release date of the latest version
- [ ] Category is valid
- [ ] Tags are descriptive
- [ ] **`display_modes` don't collide with any existing plugin's modes.**
      The display controller stores modes in a flat dict keyed by mode
      name (`src/display_controller.py:295`); a collision means
      whichever plugin loads second silently overrides the first.
      Quick check:
      ```bash
      python3 -c "
      import json, os
      modes = {}
      for d in sorted(os.listdir('plugins')):
          p = f'plugins/{d}/manifest.json'
          if not os.path.isfile(p): continue
          for mode in json.load(open(p)).get('display_modes', []):
              modes.setdefault(mode, []).append(d)
      for mode, pids in modes.items():
          if len(pids) > 1: print(f'COLLISION: {mode} → {pids}')
      "
      ```
      Prefix new plugins' modes with the plugin id or sport (e.g.
      `lax_ncaa_mens_recent` rather than `ncaa_mens_recent`) to avoid
      colliding with future plugins.

## Functionality

- [ ] Installs successfully via URL
- [ ] Dependencies install correctly
- [ ] Plugin loads without errors
- [ ] Display output works correctly
- [ ] Configuration schema validates
- [ ] Example config provided

## Documentation

- [ ] README.md exists and is comprehensive
- [ ] Installation instructions clear
- [ ] Configuration options documented
- [ ] Examples provided
- [ ] License specified
- [ ] **Per-plugin `LICENSE` file exists** in `plugins/<id>/`.
      Every plugin must ship its own LICENSE (typically a short-form
      GPL-3.0 notice — see `plugins/hello-world/LICENSE` as the
      template). Without it, downstream users have no per-plugin
      license declaration when they install via the Plugin Store.
      Quick check:
      ```bash
      for d in plugins/*/; do
        ls "$d"LICENSE >/dev/null 2>&1 || echo "MISSING: $d"
      done
      ```

## Security

- [ ] No malicious code
- [ ] Safe dependency versions
- [ ] Appropriate permissions
- [ ] No network access without disclosure
- [ ] No file system access outside plugin dir

## Testing

- [ ] Tested on Raspberry Pi
- [ ] Works with 64x32 matrix (minimum)
- [ ] No excessive CPU/memory usage
- [ ] No crashes or freezes

## Approval

Once all checks pass:
- [ ] Set `verified: true` in plugins.json
- [ ] Merge PR
- [ ] Welcome plugin author
- [ ] Update stats (downloads, stars)

