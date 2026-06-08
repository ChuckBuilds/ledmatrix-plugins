# LEDMatrix Plugins Monorepo

## Structure
- `plugins/<plugin-id>/` — Each plugin's source code, manifest, config schema, and README
- `plugins.json` — Central registry consumed by the LEDMatrix plugin store
- `update_registry.py` — Syncs `plugins.json` from local plugin manifests

## Plugin Version Workflow

**IMPORTANT:** When modifying any plugin, you MUST bump its version. This is how users receive updates — the LEDMatrix plugin store compares `manifest.json` version against `plugins.json` latest_version.

### Steps for every plugin change:
1. Make your code changes in `plugins/<plugin-id>/`
2. Bump `version` in `plugins/<plugin-id>/manifest.json` (semver: major.minor.patch)
3. Commit — the pre-commit hook automatically runs `update_registry.py` and stages `plugins.json`

> **Note:** The pre-commit hook only triggers when a `plugins/*/manifest.json` is staged. If it's not installed, run `cp scripts/pre-commit .git/hooks/pre-commit` to set it up.

### Version bump guidelines:
- **Patch** (1.0.0 → 1.0.1): Bug fixes, minor text changes
- **Minor** (1.0.0 → 1.1.0): New features, config schema additions
- **Major** (1.0.0 → 2.0.0): Breaking config changes, major rewrites

### If you forget to bump the version:
Users will NOT receive the update. The store uses version comparison, not git commits.

## Plugin Manifest Required Fields
Every `plugins/<id>/manifest.json` must have:
- `id` — Plugin identifier (must match directory name)
- `name` — Human-readable display name
- `version` — Semver string (e.g., "1.2.3")
- `class_name` — Python class name in manager.py
- `display_modes` — Array of supported display modes

## Registry Format
`plugins.json` entries for monorepo plugins use:
- `repo`: `https://github.com/ChuckBuilds/ledmatrix-plugins`
- `plugin_path`: `plugins/<plugin-id>`
- `branch`: `main`
- `latest_version`: Synced from manifest by `update_registry.py`

Third-party plugins keep their own `repo` URL and empty `plugin_path`.

## Scripts
- `python update_registry.py` — Update plugins.json from manifests
- `python update_registry.py --dry-run` — Preview without writing
- `scripts/archive_old_repos.sh` — Archive old individual repos (one-time, use `--apply`)

## Git Hooks
- `scripts/pre-commit` — Auto-syncs `plugins.json` when manifest versions change
- Install: `cp scripts/pre-commit .git/hooks/pre-commit`

## Plugin Safety Harness (cross-size / cross-screen)

Each plugin can expose multiple screens and must render on every supported matrix
size (64×32, 128×32, 128×64, 256×32). The harness lives in the **core** repo
(`LEDMatrix/scripts/check_plugin.py`) and renders every screen at every size,
failing on crashes, content drawn past the panel edge, or visual drift vs
committed golden images.

**Before opening a PR that changes a plugin:**
```bash
# from a LEDMatrix (core) checkout, with the monorepo plugins on the path:
python scripts/check_plugin.py --plugin <id> \
  --plugin-dir /path/to/ledmatrix-plugins/plugins --out-dir /tmp/preview
```
Eyeball the PNGs in `/tmp/preview`, then fix any FAIL (overflow/crash) before pushing.

**Golden images (optional, per plugin):** commit reference PNGs so visual drift is
caught automatically:
```text
plugins/<id>/test/harness.json           # deterministic config / mock data / frozen time
plugins/<id>/test/golden/<WxH>/<mode>.png
```
Regenerate with `check_plugin.py --update-golden` and review the diff. See
`clock-simple/test/` for a worked example and `LEDMatrix/docs/plugin-safety-harness.md`
for the full reference.

**CI:** `.github/workflows/test-plugins.yml` runs the harness against every
*changed* plugin on each PR (installs that plugin's `requirements.txt` first),
validates its manifest against `schema/manifest_schema.json`, and enforces the
version bump. Test-only changes (`plugins/<id>/test/**`) don't trigger the gate.
