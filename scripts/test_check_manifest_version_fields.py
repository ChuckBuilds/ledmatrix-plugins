#!/usr/bin/env python3
"""Regression tests for the manifest version-field gate.

The gate exists to guarantee the install gate has a floor to enforce. Its
failure mode is silent: a manifest that *looks* migrated but resolves to no
floor passes here, then reaches a core that cannot run it — which the B6
sunset turns from a degraded plugin into one that will not load at all.

So these pin the two things that are easy to get wrong:

- **Values, not key presence.** The core resolves the floor with
  ``head.get(NEW) or head.get(OLD)``. An empty string or ``null`` under either
  key is no floor, and a gate checking only for the key would accept exactly
  the manifests it exists to catch.
- **The floor may legitimately live above ``versions[]``.** Four published
  plugins declare a top-level ``min_ledmatrix_version``, which the core checks
  *first*. Demanding the key inside ``versions[0]`` would fail manifests that
  are already correct.

Exit codes follow the convention in `run_plugin_tests.py`: 0 pass, 1 fail.
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_manifest_version_fields as gate  # noqa: E402

BASE = {"id": "p", "compatible_versions": [">=2.0.0"]}

CLEAN, DEPRECATED, MISSING = "clean", "deprecated", "missing-floor"


def classify(manifest):
    """Run the gate over a synthetic manifest and bucket the outcome."""
    root = Path(tempfile.mkdtemp())
    (root / "p").mkdir()
    (root / "p" / "manifest.json").write_text(json.dumps(manifest))
    original = gate.PLUGINS
    gate.PLUGINS = root
    try:
        problems = [p for p in gate.check_plugin("p")
                    if "compatible_versions" not in p]
    finally:
        gate.PLUGINS = original
        shutil.rmtree(root, ignore_errors=True)

    if not problems:
        return CLEAN
    if "deprecated" in problems[0]:
        return DEPRECATED
    if "declares no minimum" in problems[0]:
        return MISSING
    return f"unexpected: {problems[0]}"


def entry(**kwargs):
    return {**BASE, "versions": [{"version": "1.0.0", **kwargs}]}


CASES = [
    # (label, manifest, expected)
    ("new spelling with a value",
     entry(ledmatrix_min_version="2.0.0"), CLEAN),
    ("deprecated spelling with a value",
     entry(ledmatrix_min="2.0.0"), DEPRECATED),

    # The regression this file was added for: a present-but-empty key.
    ('new spelling, empty string, no floor elsewhere',
     entry(ledmatrix_min_version=""), MISSING),
    ("new spelling, null, no floor elsewhere",
     entry(ledmatrix_min_version=None), MISSING),
    ('deprecated spelling, empty string, no floor elsewhere',
     entry(ledmatrix_min=""), MISSING),
    ("deprecated spelling, null, no floor elsewhere",
     entry(ledmatrix_min=None), MISSING),

    # An empty NEW alongside a real OLD is what the core's `or` falls through
    # to, so it is a spelling problem rather than a missing floor.
    ("empty new spelling but a valid deprecated one",
     entry(ledmatrix_min_version="", ledmatrix_min="2.0.0"), DEPRECATED),

    # The floor may live above versions[]; the core checks there first.
    ("no floor in versions[0], top-level declares it",
     {**BASE, "min_ledmatrix_version": "2.0.0", "versions": [{"version": "1.0.0"}]},
     CLEAN),
    ("no floor in versions[0], requires{} declares it",
     {**BASE, "requires": {"min_ledmatrix_version": "2.0.0"},
      "versions": [{"version": "1.0.0"}]}, CLEAN),
    ("empty key in versions[0], top-level declares it",
     {**BASE, "min_ledmatrix_version": "2.0.0",
      "versions": [{"version": "1.0.0", "ledmatrix_min_version": ""}]}, CLEAN),
    ("top-level present but empty, nothing else",
     {**BASE, "min_ledmatrix_version": "",
      "versions": [{"version": "1.0.0"}]}, MISSING),

    ("no floor anywhere", entry(), MISSING),
]


def main() -> int:
    failures = []
    for label, manifest, expected in CASES:
        got = classify(manifest)
        ok = got == expected
        print(f"  [{'pass' if ok else 'FAIL'}] {label:52} -> {got}")
        if not ok:
            failures.append(f"{label}: expected {expected}, got {got}")

    print()
    if failures:
        print(f"{len(failures)} failure(s):", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print(f"All {len(CASES)} cases passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
