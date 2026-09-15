#!/usr/bin/env python3
"""Regression tests for scripts/check_secrets_template.py.

Pins that the gate catches a missing placeholder (top-level, nested and array
secrets, following the core's find_secret_fields traversal), a real-looking
value in the template, and stale or misnamed entries -- and that it passes on
the real tree while reading a plausible number of schemas.

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
import check_secrets_template as gate  # noqa: E402

failures = []


def check(label, ok):
    print(("  PASS  " if ok else "  FAIL  ") + label)
    if not ok:
        failures.append(label)


SCHEMA = {"type": "object", "properties": {
    "api_key": {"type": "string", "x-secret": True},
    "mqtt": {"type": "object", "properties": {
        "host": {"type": "string"},
        "password": {"type": "string", "x-secret": True}}},
    "accounts": {"type": "array", "items": {"type": "object", "properties": {
        "token": {"type": "string", "x-secret": True}}}},
    "plain": {"type": "string"},
}}

GOOD = {"github": {"api_token": "YOUR_GITHUB_PERSONAL_ACCESS_TOKEN"},
        "p": {"api_key": "", "mqtt": {"password": ""}, "accounts": []}}


def run(template, schemas=None):
    root = Path(tempfile.mkdtemp())
    try:
        for pid, schema in (schemas or {"p": SCHEMA}).items():
            (root / "plugins" / pid).mkdir(parents=True)
            (root / "plugins" / pid / "config_schema.json").write_text(json.dumps(schema))
        tpl = root / "config_secrets.template.json"
        tpl.write_text(json.dumps(template))
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = gate.main(root / "plugins", tpl, min_schemas=1)
        return code, out.getvalue()
    finally:
        shutil.rmtree(root, ignore_errors=True)


print("traversal matches the core")
found = gate.find_secret_fields(SCHEMA["properties"])
check(f"top-level, nested and array-item secrets found ({sorted(found)})",
      found == {"api_key", "mqtt.password", "accounts[].token"})
untyped = {"obj": {"properties": {"k": {"x-secret": True}}}}
check("an object without type: object is not recursed (as in the core)",
      gate.find_secret_fields(untyped) == set())

print("\nsynthetic templates")
code, out = run(GOOD)
check(f"a complete placeholder template passes (exit {code})", code == 0)

bad = json.loads(json.dumps(GOOD))
del bad["p"]["mqtt"]
code, out = run(bad)
check(f"a missing nested secret fails (exit {code})", code == 1 and "'mqtt.password'" in out)

bad = json.loads(json.dumps(GOOD))
del bad["p"]
code, out = run(bad)
check(f"a plugin with secrets but no namespace fails (exit {code})",
      code == 1 and "'api_key'" in out)

bad = json.loads(json.dumps(GOOD))
del bad["p"]["accounts"]
code, out = run(bad)
check(f"a missing array secret fails (exit {code})", code == 1 and "accounts[].token" in out)

bad = json.loads(json.dumps(GOOD))
bad["p"]["api_key"] = "sk-live-1234"
code, out = run(bad)
check(f"a real-looking value fails (exit {code})", code == 1 and "not a placeholder" in out)

bad = json.loads(json.dumps(GOOD))
bad["p"]["plain"] = ""
code, out = run(bad)
check(f"a stale non-secret entry fails (exit {code})", code == 1 and "stale" in out)

bad = json.loads(json.dumps(GOOD))
bad["ledmatrix-typo"] = {"api_key": ""}
code, out = run(bad)
check(f"a namespace that is not a plugin id fails (exit {code})",
      code == 1 and "not a plugin id" in out)

print("\nthe real tree")
problems, n_schemas, n_fields = gate.find_problems(gate.PLUGINS_DIR, gate.TEMPLATE)
check(f"{n_schemas} schemas read (>= {gate.MIN_PLAUSIBLE_SCHEMAS})",
      n_schemas >= gate.MIN_PLAUSIBLE_SCHEMAS)
check(f"{n_fields} x-secret fields found (a plausible amount, >= 5)", n_fields >= 5)
for p in problems:
    print(f"        {p}")
check("the committed template covers every x-secret field", not problems)

print("\n%s" % ("FAILED: %d" % len(failures) if failures else "All checks passed"))
sys.exit(1 if failures else 0)
