#!/usr/bin/env python3
"""Regression suite for scripts/check_sports_drift.py.

A gate that reports by *absence* has a failure mode its own output cannot
distinguish: "I looked and found nothing wrong" and "I did not really look"
both print OK and exit 0.

That is not hypothetical here. The first version of the drift check recursed
into class bodies with a bare `walk(child)` instead of `yield from
walk(child)`, so it collected 16 functions instead of 386 -- and reported a
clean, confident result on 96% of the codebase it never opened.

So these tests assert the gate still *detects*, and that it is still looking at
a plausible amount of code.

Run: python scripts/test_check_sports_drift.py
"""

import ast
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import check_sports_drift as gate  # noqa: E402

FAILURES = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILURES.append(label)


def _func(src):
    return ast.parse(src).body[0]


# --------------------------------------------------------------------------
print("identifier folding")

check("snake_case sport tokens fold together",
      gate.fold("mlb_live") == gate.fold("nfl_live") == "S_live")

check("CamelCase plugin classes fold together",
      gate.fold("UFCScoreboardPlugin") == gate.fold("BaseballScoreboardPlugin"),
      gate.fold("UFCScoreboardPlugin"))

check("a non-sport identifier is left alone",
      gate.fold("has_live_content") == "has_live_content")

# Without CamelCase folding, every manager.py function is keyed under a
# different class name and is never compared to its siblings -- which is
# exactly where has_live_content() lives.
check("folding is what makes manager.py comparable at all",
      gate.fold("HockeyScoreboardPlugin") == gate.fold("SoccerScoreboardPlugin"))


# --------------------------------------------------------------------------
print("\nshape hashing")

a = _func("def f(self):\n    return self.mlb_live and self.mlb_enabled\n")
b = _func("def f(self):\n    return self.nhl_live and self.nhl_enabled\n")
c = _func("def f(self):\n    return self.nhl_live or self.nhl_enabled\n")
check("the same shape in two sports hashes equal", gate.shape(a) == gate.shape(b))
check("a changed operator hashes differently", gate.shape(a) != gate.shape(c))

d = _func('def f(self):\n    """One docstring."""\n    return 1\n')
e = _func('def f(self):\n    """A completely different docstring."""\n    return 1\n')
check("docstrings do not count as drift", gate.shape(d) == gate.shape(e))

f_ = _func("def f(self):\n    return self.x + 1\n")
g_ = _func("def f(self):\n    return self.x + 2\n")
check("a tuned constant does not count as drift", gate.shape(f_) == gate.shape(g_))


# --------------------------------------------------------------------------
print("\nthrottle detection")


def _throttled(src):
    fn = _func(src)
    tree = ast.parse(ast.unparse(fn))
    parents = gate._parents(tree)
    func = tree.body[0]
    call = next(n for n in ast.walk(func)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "info")
    return gate._is_throttled(call, func, parents)


check("a bare log call is not throttled",
      not _throttled("def f(self):\n    self.logger.info('x')\n"))

check("a state-change guard reads as a throttle",
      _throttled("def f(self):\n"
                 "    if changed or due:\n"
                 "        self.logger.info('x')\n"))

check("an attribute-based guard reads as a throttle",
      _throttled("def f(self):\n"
                 "    if now - self._last_live_content_log >= self._interval:\n"
                 "        self.logger.info('x')\n"))

# The precise shape of the ufc-scoreboard bug: the guard exists, but the call
# is nested above it rather than inside it.
check("a guard elsewhere in the function does not cover an unguarded call",
      not _throttled("def f(self):\n"
                     "    if live:\n"
                     "        self.logger.info('x')\n"
                     "    if should_log and not live:\n"
                     "        self.logger.debug('y')\n"))


# --------------------------------------------------------------------------
print("\nthe gate is actually looking")

index = gate.build_index()
lineages = {p for per in index.values() for p in per}

# The recursion bug found 16. Anything in that region means the gate has
# stopped descending into class bodies again.
check("it collects a plausible number of functions", len(index) >= 200,
      f"{len(index)} functions")
check("it sees most of the scoreboard lineages", len(lineages) >= 8,
      f"{len(lineages)} lineages")

tracked_seen = {f for f, _ in index}
check("every tracked filename contributed something",
      tracked_seen >= {"sports.py", "manager.py", "game_renderer.py",
                       "scroll_display.py"},
      ", ".join(sorted(tracked_seen)))

# has_live_content is the function this gate was built for. If it stops being
# indexed -- a rename, a fold that over-matches -- the gate goes quiet.
check("has_live_content is under watch",
      any(q.endswith("has_live_content") for _, q in index))

multi = sum(1 for per in index.values() if len(per) >= 5)
check("a real set of functions is shared across >=5 lineages", multi >= 30,
      f"{multi} functions")


# --------------------------------------------------------------------------
print("\nbaseline behaviour")

known, known_noisy = gate.load_baseline()
check("a baseline exists", bool(known) or bool(known_noisy),
      f"{len(known)} divergent, {len(known_noisy)} unthrottled")

# Every baselined key must still parse into the shape the checker produces,
# or entries silently stop matching and the baseline quietly grows stale.
check("baselined divergences are all 2-part keys",
      all(len(k) == 2 for k in known))
check("baselined log calls are all 3-part keys",
      all(k.count("::") == 2 for k in known_noisy))

live_noisy = {gate._noisy_key(x) for x in gate.unthrottled_display_logging()}
stale = known_noisy - live_noisy
check("no baselined log call has gone missing", not stale,
      f"stale: {sorted(stale)[:3]}" if stale else "")


# --------------------------------------------------------------------------
print("\n" + "=" * 62)
if FAILURES:
    print(f"{len(FAILURES)} check(s) failed: {FAILURES}")
    sys.exit(1)
print("All checks passed.")
