#!/usr/bin/env python3
"""Every scoreboard's Upcoming manager must take its per-game time from config.

Six of the nine ``sports.py`` copies set ``self.game_display_duration = 15``
in ``SportsUpcoming.__init__``, so each upcoming game stayed up 15 s whatever
the schema's "upcoming game duration" said: soccer, afl and nrl forwarded the
setting to a manager that ignored it, and hockey, lacrosse and basketball did
not forward it at all. football, baseball and ufc read it. The lineages are
copies (CLAUDE.md non-negotiable #7), so one copy drifting back to a literal
is the likely regression; this pins all of them.

Run: python scripts/test_upcoming_game_duration_is_read.py
"""
import ast
import sys
from pathlib import Path

PLUGINS = Path(__file__).resolve().parents[1] / "plugins"


def upcoming_duration_source(tree):
    """The expression assigned to self.game_display_duration in
    SportsUpcoming.__init__, or None when there is no such assignment."""
    for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)
                and n.name == "SportsUpcoming"):
        for fn in (n for n in cls.body if isinstance(n, ast.FunctionDef)
                   and n.name == "__init__"):
            for node in ast.walk(fn):
                if (isinstance(node, ast.Assign)
                        and any(isinstance(t, ast.Attribute) and t.attr == "game_display_duration"
                                for t in node.targets)):
                    return node.value
    return None


def reads_config(expr):
    return (isinstance(expr, ast.Call) and isinstance(expr.func, ast.Attribute)
            and expr.func.attr == "get" and expr.args
            and isinstance(expr.args[0], ast.Constant)
            and expr.args[0].value == "upcoming_game_duration")


def main():
    copies = sorted(PLUGINS.glob("*/sports.py"))
    if not copies:
        print("SKIP: no sports.py copies found; the layout changed")
        return 2
    failed = 0
    for path in copies:
        expr = upcoming_duration_source(ast.parse(path.read_text(encoding="utf-8")))
        if expr is None:
            continue  # no SportsUpcoming in this copy
        ok = reads_config(expr)
        print("%s  %s: SportsUpcoming reads upcoming_game_duration%s"
              % ("PASS" if ok else "FAIL", path.parent.name,
                 "" if ok else " (found %s)" % ast.unparse(expr)))
        failed += not ok
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
