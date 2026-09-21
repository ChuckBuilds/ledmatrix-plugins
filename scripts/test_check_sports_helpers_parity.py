#!/usr/bin/env python3
"""Regression suite for scripts/check_sports_helpers_parity.py.

The unit section builds small synthetic core + plugin trees in temp dirs, so it
runs anywhere. The integration section runs the gate on this repo's real
scoreboards. It skips only when no core checkout can be found at all (someone
running the suite without one). A core that is found but does not ship
src/common/sports_helpers.py -- or a LEDMATRIX_CORE that is not a checkout --
is a failure rather than a skip: core main has shipped that module since
ChuckBuilds/LEDMatrix#583, so its absence means the checkout broke or the
module moved, which is exactly when this gate must go red instead of quiet.

Run: python scripts/test_check_sports_helpers_parity.py
"""

import contextlib
import io
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import check_sports_helpers_parity as gate  # noqa: E402

FAILURES = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILURES.append(label)


CORE_SRC = '''\
"""Synthetic core module."""
MIN_WINDOW_DAYS = 1
MAX_WINDOW_DAYS = 60


def clamp_window(value, fallback):
    """Core docstring."""
    try:
        days = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(MIN_WINDOW_DAYS, min(MAX_WINDOW_DAYS, days))


def clamp_seconds(value, fallback, low=5, high=86400):
    return max(low, min(high, int(value)))


def logo_needs_refresh(logo_file):
    return False


def spread_weighted_order(weights):
    return list(range(len(weights)))


class SportsHelpersMixin:
    _DWELL_REENTRY_GAP_SECONDS = 5.0
    favorite_rotation_boost = 1

    def _favorite_key(self, game, side):
        return game.get(f"{side}_abbr")

    _spread_weighted_order = staticmethod(spread_weighted_order)

    def _odds_color(self):
        return (0, 255, 0)
'''

PLUGIN_SRC = '''\
_MIN_WINDOW_DAYS = 1
_MAX_WINDOW_DAYS = 60


def _clamp_window(value, fallback):
    """A different plugin docstring."""
    try:
        days = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(_MIN_WINDOW_DAYS, min(_MAX_WINDOW_DAYS, days))


def _clamp_seconds(value, fallback, low=5, high=86400):
    return max(low, min(high, int(value)))


def _logo_needs_refresh(logo_file):
    return False


class SportsCore:
    _DWELL_REENTRY_GAP_SECONDS = 5.0

    @staticmethod
    def _spread_weighted_order(weights):
        return list(range(len(weights)))

    def _odds_color(self):
        return (0, 255, 0)
'''

SPORTS = ("afl", "baseball", "basketball", "football", "hockey",
          "lacrosse", "nrl", "soccer", "ufc")


def make_tree(root, core_src=CORE_SRC, plugins=SPORTS, plugin_src=PLUGIN_SRC,
              overrides=None):
    core = Path(root) / "core"
    (core / "src" / "common").mkdir(parents=True)
    if core_src is not None:
        (core / "src" / "common" / "sports_helpers.py").write_text(core_src, encoding="utf-8")
    plugins_dir = Path(root) / "plugins"
    plugins_dir.mkdir()
    for sport in plugins:
        pdir = plugins_dir / f"{sport}-scoreboard"
        pdir.mkdir()
        src = (overrides or {}).get(sport, plugin_src)
        (pdir / "sports.py").write_text(src, encoding="utf-8")
    return core, plugins_dir


def run(core, plugins_dir, **kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = gate.run(core, plugins_dir, **kw)
    return code, buf.getvalue()


def with_tree(fn, **tree_kw):
    tmp = tempfile.mkdtemp(prefix="parity-test-")
    try:
        return fn(*make_tree(tmp, **tree_kw))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------
print("synthetic trees")

code, out = with_tree(lambda c, p: run(c, p))
check("identical copies pass", code == 0, f"exit {code}")
check("every promoted copy is compared",
      "72 comparison(s): 72 identical" in out,   # 9 plugins x 8 promoted names
      next((l for l in out.splitlines() if "comparison(s)" in l), "no summary"))
check("docstrings differ but do not count as drift", "DRIFTED:" not in out)
check("_favorite_key and the staticmethod alias are not compared on their own",
      "_favorite_key" not in out.split("Scoreboards scanned")[0]
      and out.count("spread_weighted_order->_spread_weighted_order") == 1)

drifted = PLUGIN_SRC.replace("return (0, 255, 0)", "return (0, 254, 0)")
code, out = with_tree(lambda c, p: run(c, p), overrides={"hockey": drifted})
check("a changed literal in one plugin fails", code == 1, f"exit {code}")
check("the failure names that plugin and helper",
      "hockey-scoreboard: _odds_color" in out and "baseball-scoreboard: _odds_color" not in out)
check("the failure shows a diff", "-    return (0, 255, 0)" in out and "+    return (0, 254, 0)" in out)

const_drift = PLUGIN_SRC.replace("_MAX_WINDOW_DAYS = 60", "_MAX_WINDOW_DAYS = 90")
code, out = with_tree(lambda c, p: run(c, p), overrides={"nrl": const_drift})
check("a changed constant fails and names the plugin",
      code == 1 and "nrl-scoreboard: _MAX_WINDOW_DAYS" in out, f"exit {code}")

core_drift = CORE_SRC.replace("return max(low, min(high, int(value)))",
                              "return max(low, min(high, int(float(value))))")
code, out = with_tree(lambda c, p: run(c, p), core_src=core_drift)
check("a change on the core side reports every plugin DRIFTED",
      code == 1 and all(f"{s}-scoreboard: _clamp_seconds" in out for s in SPORTS),
      f"exit {code}")

no_odds = PLUGIN_SRC.replace("    def _odds_color(self):\n        return (0, 255, 0)\n", "")
code, out = with_tree(lambda c, p: run(c, p), overrides={"ufc": no_odds})
check("a missing copy passes", code == 0, f"exit {code}")
check("and is reported absent", "ufc-scoreboard: 7 identical, 0 DRIFTED, 1 absent" in out)

adopted = "from src.common.sports_helpers import SportsHelpersMixin\n\nclass SportsCore(SportsHelpersMixin):\n    pass\n"
code, out = with_tree(lambda c, p: run(c, p), overrides={"afl": adopted})
check("a plugin that deleted its copies and imports core passes", code == 0, f"exit {code}")

shadow = "from src.common import sports_helpers\n" + PLUGIN_SRC
code, out = with_tree(lambda c, p: run(c, p), overrides={"soccer": shadow})
check("copy + core import is a warning, not a failure",
      code == 0 and "WARN: soccer-scoreboard imports src.common.sports_helpers" in out,
      f"exit {code}")

code, out = with_tree(lambda c, p: run(c, p), core_src=None)
check("core without the module exits 2",
      code == 2 and "does not ship sports_helpers" in out, f"exit {code}")

code, out = run(None, Path(tempfile.gettempdir()))
check("missing core exits 2", code == 2 and "SKIP" in out, f"exit {code}")
check("find_core returns None for a path that is not a checkout",
      gate.find_core(os.path.join(tempfile.gettempdir(), "no-such-core-dir")) is None)

# --------------------------------------------------------------------------
print("\nself-checks")

code, out = with_tree(lambda c, p: run(c, p), plugins=())
check("the plausibility self-check trips on an empty plugins dir",
      code == 1 and "found 0 scoreboard(s)" in out, f"exit {code}")

code, out = with_tree(lambda c, p: run(c, p), plugins=SPORTS[:3])
check("too few scoreboards fails", code == 1 and "found 3 scoreboard(s)" in out, f"exit {code}")

code, out = with_tree(lambda c, p: run(c, p),
                      overrides={s: "class SportsCore:\n    pass\n" for s in SPORTS})
check("scoreboards carrying nothing (a blind finder) fail",
      code == 1 and "the finder is not seeing its copies" in out
      and "the name map is stale" in out, f"exit {code}")

unmapped = CORE_SRC + "\n\ndef brand_new_helper():\n    return 1\n"
promoted, problems = gate.load_promoted(unmapped)
check("an unmapped public core name is reported",
      any("brand_new_helper" in p for p in problems), "; ".join(problems))

promoted, problems = gate.load_promoted(CORE_SRC)
public = {"MIN_WINDOW_DAYS", "MAX_WINDOW_DAYS", "clamp_window", "clamp_seconds",
          "logo_needs_refresh", "spread_weighted_order"}
check("the name map covers every public name in the synthetic core",
      not problems and public <= {p.core_name for p in promoted}, "; ".join(problems))
check("mapped names use the plugins' private spelling",
      all(p.plugin_name == "_" + p.core_name for p in promoted if p.core_name in public))

stale = CORE_SRC.replace("def logo_needs_refresh(logo_file):\n    return False\n", "")
_, problems = gate.load_promoted(stale)
check("a RENAMES key core no longer defines is reported",
      any("logo_needs_refresh" in p and "stale" in p for p in problems), "; ".join(problems))

# --------------------------------------------------------------------------
print("\nintegration (this repo's scoreboards)")

core_env = os.environ.get("LEDMATRIX_CORE") or None
core = gate.find_core(core_env)
if core is None and not core_env:
    print("  SKIP  no LEDMatrix core checkout found "
          "(set LEDMATRIX_CORE to run this section)")
elif core is None:
    check("LEDMATRIX_CORE is a core checkout", False,
          f"{core_env} has no src/ directory")
elif not (core / gate.CORE_MODULE).is_file():
    check("core ships src/common/sports_helpers.py", False,
          f"{(core / gate.CORE_MODULE).as_posix()} not found")
else:
    code, out = run(core, gate.PLUGINS_DIR)
    check("the real tree matches core", code == 0, f"exit {code}")
    summary = next((l for l in out.splitlines() if "comparison(s)" in l), "")
    try:
        compared = int(summary.split()[0])
    except (IndexError, ValueError):
        compared = 0
    scanned = next((l for l in out.splitlines() if l.startswith("Scoreboards scanned")), "")
    check("at least nine scoreboards scanned", scanned.endswith(": 9") or
          (scanned.split(": ")[-1].isdigit() and int(scanned.split(": ")[-1]) >= 9), scanned)
    check("a plausible number of comparisons were made", compared >= 100, summary)
    if code != 0:
        print(out)

# --------------------------------------------------------------------------
print("\n" + "=" * 62)
if FAILURES:
    print(f"{len(FAILURES)} check(s) failed: {FAILURES}")
    sys.exit(1)
print("All checks passed.")
