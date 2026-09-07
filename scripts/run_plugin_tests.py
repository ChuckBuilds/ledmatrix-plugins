#!/usr/bin/env python3
"""Run a plugin's `test_*.py` scripts and report pass / skip / fail honestly.

    <core-venv>/bin/python scripts/run_plugin_tests.py baseball-scoreboard \
        --core /path/to/LEDMatrix
    <core-venv>/bin/python scripts/run_plugin_tests.py --all --core /path/to/LEDMatrix

Invoke it with the interpreter that has the plugins' dependencies -- the core
checkout's venv. Scripts are spawned with `sys.executable`, so running this
under a bare `python3` that lacks e.g. pytz reports every suite as failed, when
the only thing wrong is the interpreter. `--core` sets PYTHONPATH; it does not
change which Python runs.

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
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGINS = REPO_ROOT / "plugins"

PASS, FAIL, SKIP = 0, 1, 2


def is_pytest_module(script: Path) -> bool:
    """True when a file is a pytest module rather than a standalone script.

    These declare `def test_*` / `class Test*` and have no `__main__` guard, so
    running them the way run_one() does merely imports them: the test functions
    are defined, none are called, and the process exits 0. That is reported as a
    pass, which is how four real failures in ledmatrix-flights and one in news
    sat green in CI. Hand such files to pytest instead.
    """
    try:
        src = script.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    has_items = re.search(r"^\s*(def test_|class Test|async def test_)", src, re.M)
    has_main_guard = "__main__" in src and "__name__" in src
    return bool(has_items and not has_main_guard)


def run_pytest_module(script: Path, core: Path | None, timeout: int) -> tuple[int, str]:
    """Run one pytest module and map its outcome onto the pass/skip/fail codes."""
    env = dict(os.environ)
    if core:
        core = core.resolve()
        env["PYTHONPATH"] = f"{core}{os.pathsep}{env.get('PYTHONPATH', '')}"
        env["LEDMATRIX_CORE"] = str(core)
    try:
        # Fixed interpreter (sys.executable) running pytest on a test file this
        # script discovered in the repo; argument list, no shell, so nothing is
        # word-split or expanded. Same suppression pair the rest of the repo
        # uses for this shape (see scripts/render_docs_assets.py).
        proc = subprocess.run(  # nosec B603 - no shell invoked (list-form argv)  # nosemgrep
            [sys.executable, "-m", "pytest", script.name, "-q", "--no-header",  # nosemgrep
             "--tb=line", "-p", "no:cacheprovider"],
            cwd=script.parent, env=env, capture_output=True,
            text=True, timeout=timeout, stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return FAIL, f"timed out after {timeout}s"

    out = (proc.stdout or "") + (proc.stderr or "")
    summary = ""
    for line in reversed(out.splitlines()):
        if "passed" in line or "failed" in line or "error" in line:
            summary = line.strip("= ").strip()
            break
    if proc.returncode == 0:
        return PASS, ""
    # pytest exit 5 is "no tests collected" -- for a file we classified as a
    # pytest module that means the classification was wrong, not that the file
    # is fine. Surface it rather than swallowing it as a pass.
    if proc.returncode == 5:
        return FAIL, "pytest collected no tests from a file that looks like a pytest module"
    failed = [ln.strip() for ln in out.splitlines() if ln.startswith("FAILED") or ln.startswith("ERROR")]
    reason = "; ".join(f[:100] for f in failed[:3]) or summary or f"exit {proc.returncode}"
    if len(failed) > 3:
        reason += f" (+{len(failed) - 3} more)"
    return FAIL, reason


def run_one(script: Path, core: Path | None, timeout: int) -> tuple[int, str]:
    env = dict(os.environ)
    if core:
        core = core.resolve()
        env["PYTHONPATH"] = f"{core}{os.pathsep}{env.get('PYTHONPATH', '')}"
        # Children run with cwd set to the plugin directory, so a script that
        # resolves a core asset relatively -- config/config.template.json, a
        # bundled font -- looks in the wrong place and skips even though a core
        # was supplied. PYTHONPATH alone cannot tell it where the core is.
        # LEDMATRIX_CORE is that contract, and it is absolute.
        env["LEDMATRIX_CORE"] = str(core)
    try:
        # Same contract as run_pytest_module above: fixed interpreter,
        # argument list, no shell.
        proc = subprocess.run(  # nosec B603 - no shell invoked (list-form argv)  # nosemgrep
            [sys.executable, script.name],  # nosemgrep
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

    # The reason has to name what actually failed. Reporting the last line
    # reported whatever the script logged LAST -- for a script that warns on
    # stderr, always that warning, whether it passed or failed. Nine plugins
    # failed in CI with an identical message that named a log line rather than
    # a check, and the run could not be diagnosed from its own output.
    lines = [ln.rstrip() for ln in (proc.stdout + proc.stderr).splitlines() if ln.strip()]
    failed_checks = [ln.strip() for ln in lines if "[FAIL]" in ln or ln.startswith("FAILED")]
    if failed_checks:
        reason = "; ".join(c[:100] for c in failed_checks[:3])
        if len(failed_checks) > 3:
            reason += f" (+{len(failed_checks) - 3} more)"
        return FAIL, reason
    if not lines:
        return FAIL, f"exit {proc.returncode}"
    # No named check failed, so the script died some other way -- a traceback,
    # an assertion, an exit code from somewhere else. The tail is the evidence,
    # taken from each stream separately: concatenating them put every stdout
    # line before every stderr line, so a script that printed its diagnostic
    # and then three warnings reported only the warnings.
    tails = []
    for name, stream in (("stdout", proc.stdout), ("stderr", proc.stderr)):
        kept = [ln.rstrip() for ln in stream.splitlines() if ln.strip()]
        if kept:
            tails.append("%s: %s" % (name, " | ".join(kept[-2:])))
    return FAIL, ("exit %d | %s" % (proc.returncode, " ; ".join(tails)))[:240]


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

    # A typo used to look like success: no scripts found, nothing run, exit 0.
    unknown = [pid for pid in ids if not (PLUGINS / pid).is_dir()]
    if unknown:
        print(f"Unknown plugin id(s): {', '.join(unknown)}", file=sys.stderr)
        return 1

    totals = {PASS: 0, SKIP: 0, FAIL: 0}
    failures: list[str] = []

    for pid in ids:
        # Top level plus one level of test/ or tests/. Fourteen files lived in
        # those subdirectories and had never once been run -- eleven of them
        # ledmatrix-flights' -- because the glob only ever looked at the plugin
        # root. They are the same standalone scripts as the rest, __main__ block
        # and all, and they put their own plugin root on sys.path rather than
        # relying on cwd, so they run correctly from where run_one() puts them.
        plugin_dir = PLUGINS / pid
        scripts = sorted(plugin_dir.glob("test_*.py"))
        for sub in ("test", "tests"):
            scripts.extend(sorted((plugin_dir / sub).glob("test_*.py")))
        if not scripts:
            continue
        print(f"\n{pid}")
        for script in scripts:
            if is_pytest_module(script):
                status, detail = run_pytest_module(script, args.core, args.timeout)
            else:
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
