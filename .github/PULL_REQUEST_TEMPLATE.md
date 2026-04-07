# Pull Request

## Summary

<!-- 1-3 sentences describing what this PR does and why. -->

## Type of change

<!-- Check all that apply. -->

- [ ] Bug fix in an existing plugin
- [ ] New plugin (also fill out the SUBMISSION.md checklist below)
- [ ] New feature for an existing plugin
- [ ] Documentation only
- [ ] Repo-wide change (registry script, hook, top-level docs)

## Plugin(s) affected

<!-- List the plugin id(s) this PR touches, e.g. hockey-scoreboard,
ledmatrix-weather. Use "N/A" for repo-wide changes. -->

## Related issues

<!-- "Fixes #123" or "Refs #123". Use "Fixes" for bug PRs. -->

## Test plan

<!-- How did you test this? Check all that apply. Add details for any
checked box. -->

- [ ] Loaded the plugin in LEDMatrix on real hardware
- [ ] Loaded the plugin in LEDMatrix emulator mode
  (`EMULATOR=true python3 run.py`)
- [ ] Rendered the plugin in the dev preview server
  (`scripts/dev_server.py`)
- [ ] Verified the web UI configuration form against the schema
- [ ] N/A — repo-wide / docs-only change

## Required for plugin changes

- [ ] **Bumped `version` in `plugins/<id>/manifest.json`**
      (the Plugin Store uses version comparison to ship updates —
      forgetting this means users won't receive the change)
- [ ] `class_name` in `manifest.json` matches the actual class in
      `manager.py` exactly (case-sensitive, no spaces)
- [ ] `entry_point` matches the real file (or is omitted to use
      the `manager.py` default)
- [ ] Updated the plugin's `README.md` if config keys changed
- [ ] `config_schema.json` is the source of truth for the web UI
      form — any new option is in the schema with a `default`,
      `description`, and constraints
- [ ] Pre-commit hook ran successfully (auto-syncs `plugins.json`)

## SUBMISSION checklist (new plugins only)

<!-- See SUBMISSION.md for the full requirements. -->

- [ ] Plugin id matches the directory name and is unique
- [ ] `manifest.json` has all required fields (`id`, `name`,
      `version`, `class_name`, `display_modes`)
- [ ] `manager.py` inherits from `BasePlugin` and implements
      `update()` and `display()`
- [ ] `config_schema.json` exists and validates as JSON Schema Draft-7
- [ ] `requirements.txt` lists all Python dependencies
- [ ] `README.md` documents what the plugin does, how to install,
      and the configuration options
- [ ] `LICENSE` is GPL-3.0 (or compatible)
- [ ] No hardcoded API keys or secrets — secrets go in
      `config/config_secrets.json` under the plugin id
- [ ] Tested on a real LEDMatrix setup (or in the emulator)

## Checklist

- [ ] My commits follow the message convention in `CONTRIBUTING.md`
- [ ] I read `CONTRIBUTING.md` and `CODE_OF_CONDUCT.md`
- [ ] I've not committed any secrets

## Notes for reviewer

<!-- Anything reviewers should know — gotchas, decisions you'd like
a second opinion on, things you weren't sure about. -->
