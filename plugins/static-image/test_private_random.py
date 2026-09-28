#!/usr/bin/env python3
"""
Regression test: a random_seed seeds this plugin's rotation, not the process.

_setup_rotation called random.seed(seed), which reseeds the one generator
every plugin in the display process shares: any other plugin drawing a random
number got the same "random" sequence after every restart and every save of
this plugin's settings. The rotation now uses a random.Random of its own.

Run: python plugins/static-image/test_private_random.py
Exit 0 pass, 1 fail.
"""

import random
import sys
import types
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))


def _stub_core():
    class BasePlugin:
        def __init__(self, *a, **k):
            pass

    for name in ("src", "src.plugin_system"):
        sys.modules.setdefault(name, types.ModuleType(name))
    mod = types.ModuleType("src.plugin_system.base_plugin")
    mod.BasePlugin = BasePlugin
    sys.modules["src.plugin_system.base_plugin"] = mod


try:
    from manager import StaticImagePlugin  # noqa: E402
except ImportError:
    _stub_core()
    from manager import StaticImagePlugin  # noqa: E402

results = []


def check(case, passed):
    results.append((case, passed))
    print(f"  [{'pass' if passed else 'FAIL'}] {case}")


def plugin(seed):
    p = object.__new__(StaticImagePlugin)
    p.rotation_mode = "random"
    p.rotation_settings = {"random_seed": seed}
    p.images_list = []
    p._setup_rotation()
    return p


random.seed(12345)
expected = [random.random() for _ in range(3)]  # nosec B311 - the shared generator under test
random.seed(12345)
plugin(7)
check("seeding the rotation leaves the shared generator alone",
      [random.random() for _ in range(3)] == expected)  # nosec B311

images = [{"id": i} for i in range(20)]
a, b = plugin(7), plugin(7)
check("the same seed gives the same order",
      [a._rng.choice(images)["id"] for _ in range(8)]
      == [b._rng.choice(images)["id"] for _ in range(8)])

print()
failed = [case for case, passed in results if not passed]
print(f"{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
