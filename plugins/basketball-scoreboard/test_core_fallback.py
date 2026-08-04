#!/usr/bin/env python3
"""The guarded core import must behave on every core this plugin can meet.

Adopting core code (B5) is only safe because `scroll_display.py` falls back to
`scroll_display_legacy.py` when the core lacks `src.common.sports_scroll`.
Nothing verified that claim — the safety harness renders against the *current*
core, so it exercises exactly one of the cases below.

That gap matters because the version floor does not close it. A user who
installed from the v3.1.0 release reports `__version__ = "1.0.0"`, which the
install gate treats as untrustworthy and lets through, and that core has no
`src.common.sports_scroll`. The fallback is the only thing standing between
them and a scoreboard that fails to load.

    core module        bundled copy      expected
    -----------------  ----------------  ------------------------------------
    present            present           core implementation (today)
    absent             present           legacy implementation, fully working
    absent             absent            the B6 state: fails, and names the
                                         exact missing module

The third row is not a supported configuration — it is what the sunset looks
like on a core that is too old. It is asserted so that when the fallback is
finally deleted, the failure is specific and attributable rather than a vague
crash, and so nobody deletes the fallback without meeting it.

Run: <core-venv>/bin/python plugins/basketball-scoreboard/test_core_fallback.py
"""

import importlib
import os
import sys

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

CORE_MODULE = "src.common.sports_scroll"


class _BlockModules:
    """Make named modules un-importable, simulating an older core.

    A meta-path finder is used rather than deleting files: it is reversible,
    leaves the checkout untouched, and reproduces exactly what Python does when
    the module genuinely is not there — `ModuleNotFoundError` with `.name` set.
    """

    def __init__(self, *names):
        self.names = set(names)
        self._saved = {}

    def find_module(self, fullname, path=None):  # pragma: no cover - legacy API
        return self if fullname in self.names else None

    def find_spec(self, fullname, path=None, target=None):
        if fullname in self.names:
            raise ModuleNotFoundError(f"No module named {fullname!r}", name=fullname)
        return None

    def __enter__(self):
        for name in list(sys.modules):
            if name in self.names or name.startswith("scroll_display"):
                self._saved[name] = sys.modules.pop(name)
        sys.meta_path.insert(0, self)
        return self

    def __exit__(self, *exc):
        sys.meta_path.remove(self)
        for name in list(sys.modules):
            if name.startswith("scroll_display"):
                del sys.modules[name]
        sys.modules.update(self._saved)
        return False


def _fresh_scroll_display():
    for name in list(sys.modules):
        if name.startswith("scroll_display"):
            del sys.modules[name]
    return importlib.import_module("scroll_display")


def test_core_present_uses_core():
    mod = _fresh_scroll_display()
    assert mod._USING_CORE_SCROLL is True, (
        "core ships src.common.sports_scroll, so the plugin should be using it"
    )
    bases = [c.__name__ for c in mod.ScrollDisplay.__mro__]
    assert "SportsScrollDisplay" in bases, bases
    assert mod.ScrollDisplayManager.display_class is mod.ScrollDisplay


def test_core_absent_falls_back_and_still_works():
    """The B5 guarantee. This is the case the harness cannot reach."""
    with _BlockModules(CORE_MODULE):
        mod = _fresh_scroll_display()

        assert mod._USING_CORE_SCROLL is False, (
            "with the core module gone the plugin must fall back, not import it"
        )
        assert mod.ScrollDisplay.__name__ == "LegacyScrollDisplay", (
            f"expected the bundled implementation, got {mod.ScrollDisplay.__name__}"
        )
        # A fallback that loads but cannot draw is no fallback at all.
        for method in ("prepare_scroll_content", "display_scroll_frame",
                       "is_scroll_complete", "get_dynamic_duration",
                       "_load_separator_icons"):
            assert hasattr(mod.ScrollDisplay, method), f"fallback lost {method}()"
        assert hasattr(mod.ScrollDisplayManager, "prepare_and_display")


def test_sunset_state_fails_specifically():
    """The B6 state: no core module and no bundled copy.

    Not supported — asserted so the failure names the missing module rather
    than surfacing as something unattributable.
    """
    with _BlockModules(CORE_MODULE, "scroll_display_legacy"):
        for name in list(sys.modules):
            if name.startswith("scroll_display"):
                del sys.modules[name]
        try:
            importlib.import_module("scroll_display")
        except ModuleNotFoundError as exc:
            assert exc.name in {CORE_MODULE, "scroll_display_legacy"}, (
                f"failure should name the missing module, got {exc.name!r}"
            )
        else:
            raise AssertionError(
                "expected ModuleNotFoundError with neither implementation present"
            )



def _unresolvable_globals(cls, module):
    """Globals a class's own methods read that nothing can resolve.

    Walks each method's AST for `Name` loads rather than its bytecode: the
    bytecode's co_names mixes in attribute names, so `Image.Resampling.LANCZOS`
    looked like a missing global. Locals, arguments and comprehension targets
    are excluded, leaving only names Python would resolve globally.

    Reading the source rather than calling the method is deliberate -- building
    a real display needs a display manager, fonts and assets, but an
    unresolvable global is a load-time fact and needs none of that. `hasattr`
    could not see this at all: the method exists; what it reaches for does not.
    """
    import ast
    import builtins
    import inspect
    import textwrap
    import types

    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(cls)))
    except (OSError, TypeError):  # pragma: no cover - source always available here
        return []

    missing = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        bound = {a.arg for a in node.args.args + node.args.kwonlyargs}
        if node.args.vararg:
            bound.add(node.args.vararg.arg)
        if node.args.kwarg:
            bound.add(node.args.kwarg.arg)
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, (ast.Store,)):
                bound.add(sub.id)
            elif isinstance(sub, (ast.Import, ast.ImportFrom)):
                for alias in sub.names:
                    bound.add((alias.asname or alias.name).split(".")[0])
            elif isinstance(sub, ast.ExceptHandler) and sub.name:
                bound.add(sub.name)
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                name = sub.id
                if (name in bound or hasattr(module, name) or hasattr(cls, name)
                        or hasattr(builtins, name)):
                    continue
                missing.add(name)
    return sorted(missing)


def test_content_methods_can_resolve_what_they_use():
    """The core path must be able to draw, not merely import.

    `_load_separator_icons` and `prepare_scroll_content` were lifted out of the
    legacy module; their dependencies were not. Nothing caught it: the safety
    harness renders the scoreboard screens rather than scroll mode, and the
    earlier version of this file only checked that method names existed.
    """
    mod = _fresh_scroll_display()
    missing = _unresolvable_globals(mod.ScrollDisplay, mod)
    assert not missing, (
        f"ScrollDisplay methods reference {missing}, which this module cannot "
        f"resolve — they raise NameError on the core path"
    )


def test_fallback_content_methods_can_resolve_what_they_use():
    """Same check on the bundled implementation."""
    with _BlockModules(CORE_MODULE):
        mod = _fresh_scroll_display()
        missing = _unresolvable_globals(mod.ScrollDisplay, mod)
        assert not missing, (
            f"the fallback's methods reference {missing}, which its module "
            f"cannot resolve"
        )

if __name__ == "__main__":
    # Pre-flight, deliberately BEFORE any test runs. Deciding "skip" from an
    # exception raised *during* a test is what this suite is guarding against:
    # when the fallback was removed, the escaping ModuleNotFoundError named the
    # core module and an in-test skip handler swallowed it as "no core on
    # PYTHONPATH" -- hiding the exact regression this file exists to catch.
    # Once we know the core is importable, any ModuleNotFoundError from here on
    # is a real failure.
    try:
        importlib.import_module(CORE_MODULE)
    except ModuleNotFoundError as exc:
        print(f"SKIP: needs a LEDMatrix core with {CORE_MODULE} on PYTHONPATH "
              f"({exc})")
        sys.exit(2)

    print("guarded core-import fallback tests")
    print("=" * 55)
    failures = []
    for t in (test_core_present_uses_core,
              test_core_absent_falls_back_and_still_works,
              test_content_methods_can_resolve_what_they_use,
              test_fallback_content_methods_can_resolve_what_they_use,
              test_sunset_state_fails_specifically):
        try:
            t()
            print(f"PASS {t.__name__}")
        except (AssertionError, ModuleNotFoundError) as e:
            failures.append(t.__name__)
            print(f"FAIL {t.__name__}: {e}")
    print("=" * 55)
    if failures:
        print(f"{len(failures)} test(s) failed: {failures}")
        sys.exit(1)
    print("All tests passed.")
