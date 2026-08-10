#!/usr/bin/env python3
"""Smoke test: the entry point imports and declares the class the manifest names.

Cheap, but it catches the two failures that stop a plugin loading at all --
a syntax error, and a manifest whose ``class_name`` no longer matches the code.
The second is not hypothetical: this file used to import a hardcoded
``BasketballPluginManager``, a name the plugin had long since stopped using, so
it failed on every run for a reason that had nothing to do with the plugin. It
now reads the name from the manifest, which is the thing the loader actually
uses, so a rename is either reflected in both places or caught here.

Needs the core on the path for ``src.plugin_system.base_plugin``; run via
scripts/run_plugin_tests.py, which supplies it.

Exit codes: 0 pass, 2 skip (no core), 1 fail.
"""

import json
import os
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))

# Emulator mode must be set before the plugin imports anything from the core.
os.environ.setdefault("EMULATOR", "true")

core = os.environ.get("LEDMATRIX_CORE")
if core:
    sys.path.insert(0, core)

try:
    import src.plugin_system.base_plugin  # noqa: F401
except ImportError as exc:
    print(f"SKIP: needs a LEDMatrix core on the path ({exc}); "
          f"set LEDMATRIX_CORE or run via scripts/run_plugin_tests.py --core")
    sys.exit(2)

manifest = json.loads((PLUGIN_DIR / "manifest.json").read_text(encoding="utf-8"))
class_name = manifest["class_name"]
entry_point = manifest.get("entry_point", "manager.py")
module_name = entry_point[:-3] if entry_point.endswith(".py") else entry_point

try:
    module = __import__(module_name)
except SyntaxError as e:
    print(f"FAIL: syntax error in {entry_point}: {e}")
    sys.exit(1)
except ImportError as e:
    print(f"FAIL: {entry_point} could not be imported: {e}")
    sys.exit(1)

cls = getattr(module, class_name, None)
if cls is None:
    available = sorted(
        n for n, v in vars(module).items() if isinstance(v, type)
        and v.__module__ == module.__name__)
    print(f"FAIL: manifest class_name is {class_name!r}, but {entry_point} "
          f"defines no such class. It defines: {', '.join(available) or '(none)'}")
    sys.exit(1)

print(f"PASS: {entry_point} imports and defines {class_name}")
print(f"      base classes: {', '.join(b.__name__ for b in cls.__bases__)}")
sys.exit(0)
