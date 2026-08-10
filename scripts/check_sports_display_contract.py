#!/usr/bin/env python3
"""A bundled `sports.py` display() must return a bool on every path.

The display controller skips a mode whose `display()` returns False, and the
sports managers' dispatcher treats anything that is not a bool as success:

    else:
        # Result is None or other - assume success
        return True, actual_mode

So a display() that returns None reports content whether or not it has any.
For a sports scoreboard that is not hypothetical -- "this league has no games
right now" is a routine state (out of season, or favorite_teams_only with a
team that is not playing). The mode is then never skipped, and because the
no-games branch clears the display, what it reports as content is a blank
panel held until the display duration expires.

That is exactly what shipped: hockey-scoreboard and lacrosse-scoreboard both
carried a stale fork of sports.py whose three display() methods had lost their
returns -- the base was annotated `-> None`. It was wrong from the monorepo
migration in February and only surfaced in August, because until the NHL
offseason those modes always had games and a wrong return value is invisible
whenever there is something to draw.

Nothing caught it. The safety harness calls display() and discards the result,
and its fixtures deliberately seed games so the empty path never renders. This
check is the cheap part of closing that: it is a property of the source, so it
does not need data, a display, or a core to run.

Deliberately scoped to the bundled sports.py copies. Returning None from
display() is normal and correct for most plugins -- a clock always has content,
so "nothing to show" never arises and the controller's default is right for
them. It is only the sports managers that have a real no-content state and a
dispatcher that reads the return value.

Run: python scripts/check_sports_display_contract.py [plugin-id ...]
Exit code 0 when clean, 1 when a display() can return a non-bool.
"""

import ast
import sys
from pathlib import Path
from typing import List, Optional, Tuple

PLUGINS_DIR = Path(__file__).resolve().parent.parent / "plugins"

# The manager classes whose display() the dispatcher's return-value handling
# applies to. A class that does not define display() inherits one that is
# checked here, so it needs no entry of its own.
SPORTS_CLASSES = ("SportsCore", "SportsUpcoming", "SportsRecent", "SportsLive")


def _is_bool_literal(node: Optional[ast.expr]) -> bool:
    """True for a literal True/False, and nothing else.

    Deliberately strict. The dispatcher branches on `result is True` and
    `result is False`, so a value that is merely truthy -- 1, a non-empty
    string, an object -- falls through to the "assume success" path just as
    None does. Accepting anything but the literals would let the original bug
    back in wearing a different type.
    """
    return isinstance(node, ast.Constant) and isinstance(node.value, bool)


def _is_super_display_call(node: Optional[ast.expr]) -> bool:
    """True for `return super().display(...)`.

    A subclass that adds behaviour and then hands off to its parent is fine:
    the parent is one of SPORTS_CLASSES too, so this check has already proved
    that what comes back is a bool. Four plugins delegate their live mode this
    way. Only `super()` qualifies -- an arbitrary `other.display()` could be
    anything, and the point of this check is to not take that on trust.
    """
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return (isinstance(func, ast.Attribute)
            and func.attr == "display"
            and isinstance(func.value, ast.Call)
            and isinstance(func.value.func, ast.Name)
            and func.value.func.id == "super")


# Constructs that open a new scope. A `return` inside one belongs to that
# scope, not to the display() being checked.
_NESTED_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)

# Constructs a `break` binds to. A break inside one of these does not leave an
# enclosing loop.
_LOOPS = (ast.For, ast.AsyncFor, ast.While)


def _walk_scope(node: ast.AST, stop_at: tuple = ()) -> "object":
    """
    Yield descendants of ``node`` without crossing into a nested scope.

    ``ast.walk`` is a flat traversal of every descendant, so it happily reports
    a nested helper's ``return`` as the outer function's, and an inner loop's
    ``break`` as breaking the outer one. Skipping the nested node when it comes
    round does nothing -- its children are already queued. Recursing manually
    and refusing to enter is what actually scopes the search.
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, _NESTED_SCOPES) or (stop_at and isinstance(child, stop_at)):
            continue
        yield child
        yield from _walk_scope(child, stop_at)


def _breaks_out_of(loop: ast.AST) -> bool:
    """Whether a ``break`` in this loop's own body targets it."""
    return any(isinstance(n, ast.Break) for n in _walk_scope(loop, stop_at=_LOOPS))


def _terminates(body: List[ast.stmt]) -> bool:
    """Whether a statement list always exits, so control cannot fall off it.

    A function that runs off the end returns None, which is the failure this
    check exists for -- and it is invisible to a scan that only inspects
    `return` statements, since the offending path has none. Recursion covers
    the compound statements a display() realistically ends on.
    """
    if not body:
        return False
    last = body[-1]

    if isinstance(last, (ast.Return, ast.Raise)):
        return True

    if isinstance(last, ast.If):
        # An `if` without an `else` can always fall through.
        return bool(last.orelse) and _terminates(last.body) and _terminates(last.orelse)

    if isinstance(last, ast.Try):
        # `finally` that exits ends the function whatever happened before it.
        if last.finalbody and _terminates(last.finalbody):
            return True
        # Otherwise every ordinary path must exit: the body (or its else),
        # and each handler.
        main = _terminates(last.orelse) if last.orelse else _terminates(last.body)
        return main and bool(last.handlers) and all(
            _terminates(h.body) for h in last.handlers)

    if isinstance(last, (ast.With, ast.AsyncWith)):
        return _terminates(last.body)

    if isinstance(last, (ast.While, ast.For, ast.AsyncFor)):
        # `while True:` with no break is the only loop that reliably never
        # falls through; anything else may run zero times or break out.
        if isinstance(last, ast.While) and _is_bool_literal(last.test) \
                and last.test.value is True and not last.orelse:
            return not _breaks_out_of(last)
        return False

    match_cls = getattr(ast, "Match", None)
    if match_cls is not None and isinstance(last, match_cls):
        # Exhaustive when some case cannot fail to match and every case exits.
        # An irrefutable case is an unguarded `case _:` or a bare capture
        # (`case other:`) -- both are ast.MatchAs carrying no sub-pattern. A
        # guard makes even those refutable, so the match can fall through.
        irrefutable = any(
            case.guard is None
            and isinstance(case.pattern, ast.MatchAs)
            and case.pattern.pattern is None
            for case in last.cases
        )
        return irrefutable and all(_terminates(case.body) for case in last.cases)

    return False


def _check_function(fn: ast.FunctionDef) -> List[str]:
    """Reasons this display() can hand back something other than a bool."""
    problems = []

    # Scoped to this function: a nested helper's `return` is that helper's
    # result, and flagging it would fail a perfectly correct display().
    for node in _walk_scope(fn):
        if isinstance(node, ast.Return) and not (
                _is_bool_literal(node.value) or _is_super_display_call(node.value)):
            if node.value is None:
                problems.append(f"line {node.lineno}: bare `return` (yields None)")
            else:
                rendered = getattr(ast, "unparse", lambda n: "<expr>")(node.value)
                problems.append(
                    f"line {node.lineno}: returns `{rendered}`, not a bool literal")

    if not _terminates(fn.body):
        problems.append(
            f"line {fn.lineno}: can fall off the end of the function (yields None)")

    return problems


def _check_plugin(sports_py: Path) -> Tuple[List[str], Optional[str]]:
    """(problems, unreadable_reason) for one plugin's sports.py."""
    try:
        tree = ast.parse(sports_py.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, OSError) as exc:
        return [], f"{type(exc).__name__}: {exc}"

    problems = []
    for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
        if cls.name not in SPORTS_CLASSES:
            continue
        for fn in [n for n in cls.body
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and n.name == "display"]:
            for reason in _check_function(fn):
                problems.append(f"{cls.name}.display {reason}")
    return problems, None


def main(argv: List[str]) -> int:
    if argv:
        candidates = [PLUGINS_DIR / pid for pid in argv]
    else:
        candidates = sorted(p for p in PLUGINS_DIR.iterdir() if p.is_dir())

    checked = 0
    failures = {}
    unreadable = {}

    for plugin_dir in candidates:
        sports_py = plugin_dir / "sports.py"
        if not sports_py.exists():
            continue
        checked += 1
        problems, reason = _check_plugin(sports_py)
        if reason:
            unreadable[plugin_dir.name] = reason
        elif problems:
            failures[plugin_dir.name] = problems

    for pid, problems in failures.items():
        detail = "; ".join(problems)
        print(f"::error::{pid}/sports.py: display() must return a bool on every "
              f"path so an empty mode can be skipped, but {detail}. Returning "
              f"None makes the dispatcher assume success, and the mode then "
              f"holds a blank panel for its whole display duration.")

    for pid, reason in unreadable.items():
        print(f"::error::{pid}/sports.py could not be parsed ({reason}). Treating "
              f"that as a pass would let a malformed file skip this check.")

    if failures or unreadable:
        if failures:
            print(f"\nFAIL: {len(failures)} of {checked} plugin(s) with a sports.py "
                  f"can return a non-bool from display().")
        if unreadable:
            print(f"FAIL: {len(unreadable)} of {checked} plugin(s) could not be parsed.")
        return 1

    print(f"OK: {checked} plugin(s) with a sports.py, all returning a bool from "
          f"every display() path.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
