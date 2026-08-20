#!/usr/bin/env python3
"""A logo cache must be read with the key it is written with.

Every sports renderer scopes its logo cache key by slot size --
"<abbr>@<slot>x<height>" -- because one cache dict is shared by renderers
built for different card widths. Five plugins wrote under that scoped key but
tested membership with the bare abbreviation:

    if team_abbrev in self._logo_cache:                     # never present
        return self._logo_cache[self._logo_cache_key(...)]  # what writes use

The guard never matched, so the cache never hit and every card re-decoded and
re-resized its source PNGs. That is cheap for a 64x64 asset and expensive for
the 4096x4096 ones some leagues ship -- most of a second per logo on a Pi,
paid once per game per scroll rebuild.

The failure is invisible: the cache fills up correctly, renders are correct,
and only the frame rate suffers. This checks the invariant instead.

Run: python scripts/test_logo_cache_key_consistency.py
"""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _uses_scoped_key(node: ast.AST) -> bool:
    """True when the expression routes through _logo_cache_key()."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) \
                and sub.func.attr == '_logo_cache_key':
            return True
    return False


def check(path: Path) -> list:
    """Return a list of (lineno, source) for guards that skip the scoped key."""
    try:
        tree = ast.parse(path.read_text(encoding='utf-8'))
    except (OSError, SyntaxError):
        return []

    # Does this renderer scope its keys at all? If it never calls
    # _logo_cache_key, bare keys are self-consistent and fine.
    writes_scoped = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) \
                and node.value.attr == '_logo_cache' and _uses_scoped_key(node.slice):
            writes_scoped = True
            break
    if not writes_scoped:
        return []

    bad = []
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        # Locals bound to a scoped key, so `k = self._logo_cache_key(x)`
        # followed by `if k in self._logo_cache` reads as scoped.
        scoped_names = set()
        for node in ast.walk(func):
            if isinstance(node, ast.Assign) and _uses_scoped_key(node.value):
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name):
                        scoped_names.add(tgt.id)

        for node in ast.walk(func):
            if not isinstance(node, ast.Compare):
                continue
            if not any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops):
                continue
            target = node.comparators[0] if node.comparators else None
            if not (isinstance(target, ast.Attribute) and target.attr == '_logo_cache'):
                continue
            if _uses_scoped_key(node.left):
                continue
            if isinstance(node.left, ast.Name) and node.left.id in scoped_names:
                continue
            bad.append((node.lineno, ast.unparse(node)))
    return bad


def main() -> int:
    failures = []
    for renderer in sorted(ROOT.glob('plugins/*/game_renderer.py')):
        for lineno, src in check(renderer):
            failures.append(f"{renderer.relative_to(ROOT)}:{lineno}: {src}")

    if failures:
        print("Logo cache guarded with an unscoped key while writes are scoped.")
        print("The lookup can never match, so the cache never hits:\n")
        for f in failures:
            print(f"  {f}")
        print("\nUse the same _logo_cache_key(...) the writes use.")
        return 1

    print(f"OK: every scoped logo cache is read with its scoped key "
          f"({len(list(ROOT.glob('plugins/*/game_renderer.py')))} renderers checked)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
