# Contributing to ledmatrix-plugins

This is the official plugin monorepo for
[LEDMatrix](https://github.com/ChuckBuilds/LEDMatrix). Contributions are
welcome — bug reports, plugin updates, brand-new plugins, and
documentation fixes all help.

## Quick links

- **Plugin submission flow**: see [SUBMISSION.md](SUBMISSION.md)
- **Plugin verification checklist**: see [VERIFICATION.md](VERIFICATION.md)
- **Real-time discussion**: the
  [LEDMatrix Discord](https://discord.gg/uW36dVAtcT)
- **Bugs / feature requests**:
  [open an issue](https://github.com/ChuckBuilds/ledmatrix-plugins/issues)
- **Security issues**: see [SECURITY.md](SECURITY.md). Don't open
  public issues for vulnerabilities.

## Repository layout

```text
ledmatrix-plugins/
├── plugins/
│   └── <plugin-id>/
│       ├── manifest.json        # Plugin metadata, entry point, class name
│       ├── manager.py           # Plugin class (inherits from BasePlugin)
│       ├── config_schema.json   # JSON Schema for the web UI form
│       ├── requirements.txt     # Python deps
│       ├── README.md            # User-facing docs
│       └── LICENSE              # Per-plugin license (usually GPL-3.0)
├── plugins.json                 # Auto-generated registry consumed by the Plugin Store
├── update_registry.py           # Syncs plugins.json from manifests
├── scripts/
│   └── pre-commit               # Git hook that auto-runs update_registry.py
└── docs/                        # Plugin Store and contributor docs
```

## Setting up a development environment

You'll typically work on a plugin alongside the main LEDMatrix repo:

```bash
# Clone both repos
git clone https://github.com/ChuckBuilds/LEDMatrix.git
git clone https://github.com/ChuckBuilds/ledmatrix-plugins.git

# Symlink the plugin you want to work on into LEDMatrix's
# plugin loader path. Default plugin location in LEDMatrix is
# plugin-repos/ (or plugins/ as a fallback for the dev workflow).
cd LEDMatrix
ln -s ../ledmatrix-plugins/plugins/<plugin-id> plugin-repos/<plugin-id>

# Test without hardware
python3 scripts/dev_server.py    # then open http://localhost:5001
# Or test the plugin in the full emulator path
EMULATOR=true python3 run.py
```

For a more managed dev setup, LEDMatrix ships
`scripts/dev/dev_plugin_setup.sh` which automates the symlink + clone
flow. See LEDMatrix's
[`docs/PLUGIN_DEVELOPMENT_GUIDE.md`](https://github.com/ChuckBuilds/LEDMatrix/blob/main/docs/PLUGIN_DEVELOPMENT_GUIDE.md).

## Working on an existing plugin

1. **Open an issue first** if the change is non-trivial. This avoids
   wasted work on PRs that don't fit the project direction.
2. **Branch off `main`**: `fix/<plugin-id>-<short-description>` or
   `feat/<plugin-id>-<short-description>`.
3. **Make your changes** in `plugins/<plugin-id>/`.
4. **Bump the version in `manifest.json`.** This is critical — the
   Plugin Store uses version comparison (manifest version vs
   `plugins.json` `latest_version`) to decide whether to ship updates
   to users. If you forget, users won't receive your fix.
   - **Patch** (1.0.0 → 1.0.1): bug fixes, doc tweaks
   - **Minor** (1.0.0 → 1.1.0): new features, schema additions
   - **Major** (1.0.0 → 2.0.0): breaking config changes
5. **Update the plugin's README** if you added/changed config keys.
   The web UI form is generated from `config_schema.json`, so the
   schema is the source of truth — README tables should match.
6. **Commit.** The pre-commit hook automatically runs
   `update_registry.py` and stages `plugins.json`. If the hook isn't
   installed, run `cp scripts/pre-commit .git/hooks/pre-commit`.
7. **Open a PR** using the template in
   `.github/PULL_REQUEST_TEMPLATE.md`.

## Adding a new plugin

See [SUBMISSION.md](SUBMISSION.md) for the full submission flow. The
short version:

1. Copy the
   [`plugins/hello-world/`](plugins/hello-world/) directory as a
   starting template — it's intentionally tiny and well-commented.
2. Rename the directory to your plugin id (lowercase, hyphens, e.g.
   `my-cool-plugin`).
3. Update `manifest.json`:
   - `id` must match the directory name
   - `class_name` must match the actual class name in `manager.py`
     **exactly** (case-sensitive, no spaces — see
     [VERIFICATION.md](VERIFICATION.md) for why this matters)
   - Set `entry_point` (defaults to `manager.py` if omitted)
   - Set `version`, `author`, `category`, `tags`, `display_modes`
4. Implement `update()` and `display()` in your plugin class.
5. Define the configuration schema in `config_schema.json`. The web
   UI form is generated automatically from this — every key you want
   users to be able to configure should be here with `default`,
   `description`, and constraints.
6. Write a `README.md` covering: what the plugin does, install,
   configuration, and any external service / API key requirements.
7. Add a `LICENSE` (usually a copy of the project GPL-3.0).
8. Test locally via the symlink + dev_server flow above.
9. Open a PR.

## Commit message convention

Conventional Commits is encouraged but not strictly enforced:

- `feat(hockey-scoreboard): add power-play indicator`
- `fix(stocks): handle empty Yahoo Finance response`
- `docs(weather): document the radar zoom config key`
- `chore: bump masters-tournament to 2.0.1`

Plugin-scoped prefixes help when you need to find the history of a
specific plugin later.

## Testing

Per-plugin tests live in the LEDMatrix repo at `test/plugins/`. If
you're adding a test for your plugin, open a corresponding PR in
LEDMatrix. The dev preview server (`scripts/dev_server.py` in
LEDMatrix) is the fastest way to iterate visually.

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md).
By participating you agree to abide by its terms.

## License

ledmatrix-plugins is licensed under [GPL-3.0](LICENSE). By
submitting a contribution you agree to license it under the same terms
(the standard "inbound = outbound" rule that GitHub applies by
default). Individual plugins may ship their own `LICENSE` file but
should remain GPL-3.0 compatible.
