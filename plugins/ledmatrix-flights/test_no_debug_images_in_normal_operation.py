"""Building a map must not write PNGs into the working directory.

_get_map_background() saved debug_composite.png and debug_cropped.png on every
composite, unconditionally. On a Pi that is pointless SD-card wear (~27KB a
time), and the files land in whatever directory the service runs from -- for a
normal install, the checkout itself, where they show up as untracked files.
There was no config flag, so they could not be turned off.

They are useful when you are debugging the map, so they are kept behind the
debug log level rather than deleted.
"""
import ast
import logging
from pathlib import Path

MANAGER = Path(__file__).resolve().parent / "manager.py"
TREE = ast.parse(MANAGER.read_text(encoding="utf-8"))


def _save_calls():
    """(lineno, unparsed) for every .save(...) writing a debug_* path."""
    out = []
    for n in ast.walk(TREE):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                and n.func.attr == "save":
            src = ast.unparse(n)
            if "debug_" in src:
                out.append((n.lineno, src))
    return out


def _enclosing_tests(lineno):
    """Source of every `if` test whose body contains this line."""
    parents = {}
    for node in ast.walk(TREE):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    out = []
    for node in ast.walk(TREE):
        if isinstance(node, ast.If) and any(
                s.lineno <= lineno <= (s.end_lineno or s.lineno) for s in node.body):
            out.append(ast.unparse(node.test))
    return out


def test_the_debug_saves_still_exist():
    """Pin the premise -- if they are removed entirely this file is obsolete."""
    calls = _save_calls()
    assert calls, "no debug image saves found; delete this test if that was deliberate"


def test_every_debug_save_is_behind_a_debug_check():
    offenders = []
    for lineno, src in _save_calls():
        guards = " ".join(_enclosing_tests(lineno))
        if "isEnabledFor" not in guards and "DEBUG" not in guards:
            offenders.append((lineno, src[:60]))
    assert not offenders, (
        f"unconditional debug image write(s) at {offenders} -- these run on "
        "every map composite, wearing the SD card and dropping untracked PNGs "
        "into the service's working directory")


def test_the_guard_uses_the_real_logging_level():
    """isEnabledFor, not a hand-rolled flag that can drift from the log config."""
    src = MANAGER.read_text(encoding="utf-8")
    assert "self.logger.isEnabledFor(logging.DEBUG)" in src
    assert logging.DEBUG < logging.INFO      # sanity: DEBUG really is the quiet level
