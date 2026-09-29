#!/usr/bin/env python3
"""Regression tests for scripts/check_manifests_ascii.py.

Pins that the gate passes on the real tree while reading a plausible number of
manifests -- which is what puts it in CI at all, since the workflow globs
scripts/test_*.py rather than scripts/check_*.py -- and that it catches raw
UTF-8 (BMP and astral), a byte-order mark, a legacy-encoded byte and the
Unicode line separators, while leaving escaped text and other files alone.

Exit codes: 0 pass, 1 fail.
"""

import contextlib
import io
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_manifests_ascii as gate  # noqa: E402

failures = []


def check(label, ok):
    print(("  PASS  " if ok else "  FAIL  ") + label)
    if not ok:
        failures.append(label)


CLEAN = b'{\r\n  "id": "p",\r\n  "notes": "on a call \\u2014 stays on"\r\n}\r\n'
EM_DASH = '{\n  "id": "p",\n  "notes": "on a call \u2014 stays on"\n}\n'.encode("utf-8")


def run(manifests, min_manifests=1, extra=None):
    """Run the gate over a synthetic plugins/ tree of {plugin_id: raw bytes}."""
    root = Path(tempfile.mkdtemp())
    try:
        for pid, raw in manifests.items():
            (root / pid).mkdir(parents=True)
            (root / pid / "manifest.json").write_bytes(raw)
        for rel, raw in (extra or {}).items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_bytes(raw)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = gate.main(root, min_manifests=min_manifests)
        return code, out.getvalue()
    finally:
        shutil.rmtree(root, ignore_errors=True)


print("the real tree")
with contextlib.redirect_stdout(io.StringIO()) as real:
    code = gate.main()
print("        " + real.getvalue().strip().replace("\n", "\n        "))
n_real = len(list(gate.PLUGINS_DIR.glob("*/manifest.json")))
check(f"{n_real} manifests found (> 40)", n_real > 40)
check(f"every committed manifest is pure ASCII (exit {code})", code == 0)

print("\nwhat the gate must flag")
code, out = run({"p": EM_DASH})
check(f"a raw em dash fails (exit {code})", code == 1)
check("and the report names the plugin, the line and the escape to write",
      "p/manifest.json" in out and "line 3, col 23: U+2014" in out
      and "write \\u2014" in out)

astral = '{"id": "p", "name": "Kickoff \U0001F3C8"}'.encode("utf-8")
code, out = run({"p": astral})
check(f"an astral character fails, fix given as a surrogate pair (exit {code})",
      code == 1 and "U+1F3C8" in out and "write \\ud83c\\udfc8" in out)

code, out = run({"p": b"\xef\xbb\xbf" + CLEAN})
check(f"a UTF-8 byte-order mark fails, named as one (exit {code})",
      code == 1 and "byte-order mark" in out)

code, out = run({"p": '{"id": "p", "name": "Caf\u00e9"}'.encode("cp1252")})
check(f"a manifest saved as cp1252 fails as invalid UTF-8 (exit {code})",
      code == 1 and "not valid UTF-8" in out and "0xE9" in out)

for ch in ("\u0085", "\u2028", "\u2029"):
    raw = ('{"id": "p", "notes": "a%sb"}' % ch).encode("utf-8")
    code, out = run({"p": raw})
    check(f"U+{ord(ch):04X} fails, though str.splitlines() treats it as a "
          f"line break (exit {code})", code == 1 and f"U+{ord(ch):04X}" in out)

code, out = run({"clean": CLEAN, "dirty": EM_DASH})
check(f"one bad manifest fails the run, and only it is named (exit {code})",
      code == 1 and "dirty/manifest.json" in out and "clean/" not in out)

print("\nwhat the gate must not flag")
code, out = run({"p": CLEAN})
check(f"escaped non-ASCII with CRLF line endings passes (exit {code})",
      code == 0 and out.startswith("PASS"))

code, out = run({"p": CLEAN}, extra={"p/README.md": "caf\u00e9".encode("utf-8"),
                                     "p/config_schema.json": EM_DASH})
check(f"non-ASCII outside manifest.json is out of scope (exit {code})", code == 0)

print("\nthe plausibility floor")
code, out = run({"p": CLEAN}, min_manifests=2)
check(f"a clean tree with too few manifests fails (exit {code})",
      code == 1 and "only 1 manifest.json" in out)
code, out = run({}, min_manifests=gate.MIN_PLAUSIBLE_MANIFESTS)
check(f"an empty tree fails at the real floor (exit {code})", code == 1)
check(f"the floor is above 40 ({gate.MIN_PLAUSIBLE_MANIFESTS})",
      gate.MIN_PLAUSIBLE_MANIFESTS > 40)

print("\nthe suggested fix is right")
for ch in ("\u2014", "\u25b2", "\u00e9", "\U0001F3C8"):
    escaped = gate.escape_char(ch)
    check(f"U+{ord(ch):04X} -> {escaped} is ASCII and parses back to itself",
          escaped.isascii() and json.loads('"%s"' % escaped) == ch)

text = EM_DASH.decode("utf-8")
fixed = "".join(gate.escape_char(c) if not c.isascii() else c for c in text)
check("escaping a manifest leaves json.loads unchanged",
      json.loads(fixed) == json.loads(text))
check("the escaped file reads the same under cp1252 as under UTF-8",
      json.loads(fixed.encode("ascii").decode("cp1252")) == json.loads(text))
check("while the raw file does not (the bug this guards against)",
      json.loads(EM_DASH.decode("cp1252")) != json.loads(text))

print("\n%s" % ("FAILED: %d" % len(failures) if failures else "All checks passed"))
sys.exit(1 if failures else 0)
