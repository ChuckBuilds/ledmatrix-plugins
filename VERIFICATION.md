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

