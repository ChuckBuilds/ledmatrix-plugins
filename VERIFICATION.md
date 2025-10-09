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

- [ ] All required fields present
- [ ] Valid JSON syntax
- [ ] Correct version format (semver)
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

