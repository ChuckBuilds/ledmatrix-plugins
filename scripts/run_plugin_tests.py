#!/usr/bin/env python3
"""Run a plugin's `test_*.py` scripts and report pass / skip / fail honestly.

    python scripts/run_plugin_tests.py baseball-scoreboard
    python scripts/run_plugin_tests.py --all
    python scripts/run_plugin_tests.py baseball-scoreboard --core /path/to/LEDMatrix

## Why this exists

These are standalone scripts, not a pytest suite, and they signal only through
an exit code. Without a shared convention every non-zero exit looks the same,
so a script that is *not applicable* here — it wants a tty, or an LED matrix,
or a font that ships with the core — was indistinguishable from a real
regression.

That cost real time: during one session the same seven "failures" were
re-baselined three separate times to prove a change hadn't caused them. Three
of the seven were only a missing `RGBMatrixEmulator` in the runner's
virtualenv, one was a deliberate skip, two were interactive scripts, and
exactly one was a genuinely broken test — which had been silently
non-functional, dying before its first assertion, for as long as it had been
"failing".

Noise that everyone learns to ignore is worse than no signal at all, because a
real regression hides in it.

## The convention

    0  pass
    2  skip — prerequisites absent (no tty, no matrix, no font). Not a failure.
    1  fail — a genuine problem. Anything else is treated as a failure too.

Scripts opt into skipping by printing `SKIP: <reason>` and exiting 2.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGINS = REPO_ROOT / "plugins"

PASS, FAIL, SKIP = 0, 1, 2


def run_one(script: Path, core: Path | None, timeout: int) -> tuple[int, str]:
    env = dict(os.environ)
    if core:
        env["PYTHONPATH"] = f"{core}{os.pathsep}{env.get('PYTHONPATH', '')}"
    try:
        proc = subprocess.run(
            [sys.executable, script.name],
            cwd=script.parent, env=env, capture_output=True,
            text=True, timeout=timeout, stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return FAIL, f"timed out after {timeout}s"

    if proc.returncode == SKIP:
        for line in proc.stdout.splitlines():
            if line.startswith("SKIP:"):
                return SKIP, line[len("SKIP:"):].strip()
        return SKIP, "skipped"
    if proc.returncode == PASS:
        return PASS, ""

    tail = [ln for ln in (proc.stdout + proc.stderr).splitlines() if ln.strip()]
    return FAIL, (tail[-1][:120] if tail else f"exit {proc.returncode}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("plugin_ids", nargs="*")
    ap.add_argument("--all", action="store_true", help="Every plugin")
    ap.add_argument("--core", type=Path, default=None,
                    help="Path to a LEDMatrix checkout to put on PYTHONPATH")
    ap.add_argument("--timeout", type=int, default=180)
    args = ap.parse_args()

    ids = (sorted(p.name for p in PLUGINS.iterdir() if p.is_dir())
           if args.all else args.plugin_ids)
    if not ids:
        ap.error("give plugin ids or --all")

    totals = {PASS: 0, SKIP: 0, FAIL: 0}
    failures: list[str] = []

    for pid in ids:
        scripts = sorted((PLUGINS / pid).glob("test_*.py"))
        if not scripts:
            continue
        print(f"\n{pid}")
        for script in scripts:
            status, detail = run_one(script, args.core, args.timeout)
            totals[status] += 1
            label = {PASS: "pass", SKIP: "SKIP", FAIL: "FAIL"}[status]
            print(f"  [{label}] {script.name}" + (f" -- {detail}" if detail else ""))
            if status == FAIL:
                failures.append(f"{pid}/{script.name}: {detail}")

    print(f"\n{totals[PASS]} passed, {totals[SKIP]} skipped, {totals[FAIL]} failed")
    if failures:
        print("\nFailures:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
