#!/usr/bin/env python3
"""A null period or period text must not crash the live "is it over" check.

SportsLive._is_game_really_over read ``game.get("period_text", "").lower()``.
That default only applies when the key is missing; if the value is None the
key is present, and ``None.lower()`` raised AttributeError.
The copy also compared ``game.get("period", 0) >= 4``, which raised
TypeError for a null or non-numeric period.

SportsLive.update() calls it for every non-final game in the feed with no
try/except, so one such game abandoned the whole live refresh for that league:
the live list was never replaced and the panel kept showing the last one.

These checks pin that a null or junk value is treated as empty / period 0, and
that the football end-of-game rules themselves are unchanged.

Run: <core-venv>/bin/python plugins/football-scoreboard/test_null_period_really_over.py
Exit 0 pass, 1 fail, 2 skip (no LEDMatrix core checkout found).
"""

import logging
import os
import sys
from pathlib import Path
from types import SimpleNamespace

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))


def _add_core_to_path():
    """Put a LEDMatrix core on sys.path, or skip when there is none."""
    try:
        import src.plugin_system  # noqa: F401  (already importable)
        return
    except ImportError:
        pass
    for candidate in (os.environ.get("LEDMATRIX_CORE", ""),
                      str(PLUGIN_DIR.parents[2] / "LEDMatrix")):
        if candidate and (Path(candidate) / "src" / "plugin_system").is_dir():
            sys.path.insert(0, candidate)
            return
    print("SKIP: no LEDMatrix core checkout found (set LEDMATRIX_CORE)")
    sys.exit(2)


_add_core_to_path()

import sports  # noqa: E402

FAILURES = []


def check(label, is_over, game, expected):
    """Call is_over(game) and record whether it returned `expected`."""
    game = dict({"away_abbr": "AWY", "home_abbr": "HOM"}, **game)
    try:
        got = is_over(game)
    except Exception as exc:  # pylint: disable=broad-except
        print(f"  FAIL  {label}  [raised {type(exc).__name__}: {exc}]")
        FAILURES.append(label)
        return
    ok = got is expected
    print(f"  {'PASS' if ok else 'FAIL'}  {label}"
          + ("" if ok else f"  [expected {expected}, got {got!r}]"))
    if not ok:
        FAILURES.append(label)


# The method only touches self.logger, so a stand-in instance is enough.
_probe = SimpleNamespace(logger=logging.getLogger("null_period_probe"))


def shared_is_over(game):
    return sports.SportsLive._is_game_really_over(_probe, game)


print("SportsLive._is_game_really_over")

# Unchanged behaviour.
check("live game is not over", shared_is_over,
      {"period_text": "Q2", "period": 2, "clock": "5:00"}, False)
check("'Final' in period_text is over", shared_is_over,
      {"period_text": "Final", "period": 4, "clock": "0:00"}, True)
check("0:00 in period 4 is over", shared_is_over,
      {"period_text": "Q4", "period": 4, "clock": "0:00"}, True)
check("0:00 in period 1 is not over", shared_is_over,
      {"period_text": "Q2", "period": 1, "clock": "0:00"}, False)

# Null / junk values.
check("period_text None, live", shared_is_over,
      {"period_text": None, "period": 2, "clock": "5:00"}, False)
check("period_text None still reaches the 0:00 check", shared_is_over,
      {"period_text": None, "period": 4, "clock": "0:00"}, True)
check("period None is period 0 (not over at 0:00)", shared_is_over,
      {"period_text": "Q2", "period": None, "clock": "0:00"}, False)
check("non-numeric period string is period 0", shared_is_over,
      {"period_text": "Q2", "period": "OT", "clock": "0:00"}, False)
check("period_text and period both None", shared_is_over,
      {"period_text": None, "period": None, "clock": "5:00"}, False)

print("\n" + "=" * 60)
if FAILURES:
    print(f"{len(FAILURES)} check(s) failed: {FAILURES}")
    sys.exit(1)
print("All checks passed.")
