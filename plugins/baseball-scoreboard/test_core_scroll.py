"""After the sunset, the core import is the only implementation there is.

B5 shipped a guarded import: prefer `src.common.sports_scroll`, fall back to a
bundled `scroll_display_legacy.py`. B6 deleted that copy, so the guard went
with it -- wrapping an import that has nothing to fall back to would only
mislabel the failure.

This file used to prove the fallback worked. It now proves the fallback is gone
and cannot come back by accident, which is a narrower claim:

  * the core import is a plain top-level statement, not a guarded one
  * `scroll_display_legacy.py` is not in the plugin and is not imported
  * ScrollDisplay really is built on the core class, checked by identity
  * the manifest floors at or above the release that ships the module
  * on a core without the module, the import fails naming that exact module

The last one is the whole user-visible contract of the sunset.
`PluginManager.load_plugin` catches the ModuleNotFoundError and parks the
plugin in ERROR with a single log line, so the module name in that line is all
the user gets. If the guard ever came back and swallowed the error,
ScrollDisplay would simply be unbound and the symptom would surface much later
as a NameError from the display path.

The manifest check is here because nothing else in either repo asserts the
floor's VALUE. The safety harness runs against core main, which has the module
whatever the manifest says; the plugins repo's manifest gate checks the field's
spelling, not its number; and the registry carries no floor at all. Without
this, a plugin could sunset with a 2.0.0 floor and every gate would stay green
while the store handed it to a 3.1.0 core.

Run: <core-venv>/bin/python plugins/baseball-scoreboard/test_core_scroll.py
"""

import ast
import importlib
import json
import os
import sys

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

CORE_MODULE = "src.common.sports_scroll"
SCROLL_SOURCE = os.path.join(PLUGIN_DIR, "scroll_display.py")
#: The core release that first shipped CORE_MODULE.
FIRST_CORE_RELEASE = (3, 2, 0)


def _scroll_display_ast():
    with open(SCROLL_SOURCE, encoding="utf-8") as fh:
        return ast.parse(fh.read())


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


def test_the_core_import_is_unguarded():
    """A top-level `from ... import`, not one nested in a try or an if.

    Checked against `tree.body` rather than by walking the whole tree: putting
    the import back inside an `if` or a `try` is exactly how the guard would
    return, and both keep the statement inside module scope where a walk would
    still find it and call it top-level.
    """
    tree = _scroll_display_ast()

    assert any(isinstance(n, ast.ImportFrom) and n.module == CORE_MODULE
               for n in tree.body), (
        f"{CORE_MODULE} is not imported as a top-level statement in "
        f"scroll_display.py; after the sunset that import is the only source "
        f"of the scroll base classes"
    )

    for node in ast.walk(tree):
        if isinstance(node, ast.Try) and any(
                isinstance(sub, ast.ImportFrom) and sub.module == CORE_MODULE
                for sub in ast.walk(node)):
            raise AssertionError(
                f"the {CORE_MODULE} import is inside a try/except again. With "
                f"nothing to fall back to, catching the ModuleNotFoundError "
                f"only hides which module was missing"
            )


def test_the_bundled_copy_is_gone():
    """The file, and any import of it.

    An import check rather than a text search: the module docstring above
    mentions the old name on purpose. And a source check rather than trying the
    import for real -- until every sports plugin has sunset, a sibling's
    scroll_display_legacy.py is still importable on sys.path, so "cannot be
    imported" would be false for a reason that has nothing to do with this
    plugin.
    """
    legacy = os.path.join(PLUGIN_DIR, "scroll_display_legacy.py")
    assert not os.path.exists(legacy), (
        f"{legacy} is back. The manifest floor now guarantees the core module, "
        f"and a second implementation is where the separator-icon constants "
        f"hid last time"
    )
    for node in ast.walk(_scroll_display_ast()):
        if isinstance(node, ast.ImportFrom):
            assert node.module != "scroll_display_legacy", (
                "scroll_display.py imports scroll_display_legacy again; that "
                "raises ModuleNotFoundError naming the wrong module"
            )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "scroll_display_legacy", alias.name


def test_the_classes_are_defined_at_module_level():
    """The de-indent landed.

    Collapsing the guard meant lifting the whole class body out of an `else:`
    block. A stray four spaces leaves the classes defined inside a block that
    no longer exists -- or, worse because it still parses, inside one that does.
    """
    names = {n.name for n in _scroll_display_ast().body
             if isinstance(n, ast.ClassDef)}
    assert {"ScrollDisplay", "ScrollDisplayManager"} <= names, sorted(names)


def test_the_base_is_the_core_class():
    """Identity, not name.

    The pre-sunset version compared `__name__`, which a locally defined class
    called SportsScrollDisplay would satisfy just as well.
    """
    from src.common.sports_scroll import (
        SportsScrollDisplay, SportsScrollDisplayManager)

    mod = _fresh_scroll_display()
    assert SportsScrollDisplay in mod.ScrollDisplay.__mro__, mod.ScrollDisplay.__mro__
    assert SportsScrollDisplayManager in mod.ScrollDisplayManager.__mro__
    assert mod.ScrollDisplayManager.display_class is mod.ScrollDisplay


def test_the_manifest_floors_at_the_release_that_ships_the_module():
    """Nothing else in either repo checks the floor's value. See the header."""
    with open(os.path.join(PLUGIN_DIR, "manifest.json"), encoding="utf-8") as fh:
        manifest = json.load(fh)

    head = (manifest.get("versions") or [{}])[0]
    declared = head.get("ledmatrix_min_version") or head.get("ledmatrix_min")
    assert declared, "the newest versions[] entry declares no ledmatrix floor"

    parsed = tuple(int(part) for part in declared.lstrip("v").split(".")[:3])
    assert parsed >= FIRST_CORE_RELEASE, (
        f"floor is {declared}, but {CORE_MODULE} first shipped in "
        f"{'.'.join(str(n) for n in FIRST_CORE_RELEASE)}. Below that the "
        f"install gate lets this plugin through onto a core that cannot load it"
    )


def test_an_old_core_fails_naming_the_module():
    """The sunset's user-visible contract.

    Asserted as an exact name where the pre-sunset version accepted either the
    core module or `scroll_display_legacy`: with the copy gone there is only
    one right answer, and any other name means something swallowed the real
    failure and re-raised a substitute.
    """
    with _BlockModules(CORE_MODULE):
        for name in list(sys.modules):
            if name.startswith("scroll_display"):
                del sys.modules[name]
        try:
            importlib.import_module("scroll_display")
        except ModuleNotFoundError as exc:
            assert exc.name == CORE_MODULE, (
                f"failure named {exc.name!r}; it must name {CORE_MODULE!r}, "
                f"which is the only line the user gets"
            )
        else:
            raise AssertionError(
                "scroll_display imported with no scroll implementation present"
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

    # Resolve against the module the CLASS lives in, not the one we imported.
    # On the fallback path ScrollDisplay is LegacyScrollDisplay, whose globals
    # are scroll_display_legacy's -- checking scroll_display's namespace made
    # every fallback look broken.
    import sys as _sys
    module = _sys.modules.get(cls.__module__, module)

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
    for cls in (mod.ScrollDisplay, mod.ScrollDisplayManager):
        missing = _unresolvable_globals(cls, mod)
        assert not missing, (
            f"{cls.__name__} methods reference {missing}, which their module "
            f"cannot resolve — they raise NameError on the core path"
        )


class _StubMatrix:
    width = 128
    height = 32


class _StubDisplayManager:
    """The minimum a scroll display needs to be built.

    Carries a `matrix` as well as bare width/height because the two lineages
    read the size differently: the core base prefers `matrix` and falls back to
    getattr, while the soccer lineage's bundled manager goes straight for
    `display_manager.matrix.width`. A real display manager always has both, so
    a stub missing one tests a configuration that never ships.

    Nothing here draws, because nothing needs to: the bug this guards against
    fires in __init__, long before a frame is rendered.
    """

    width = 128
    height = 32
    matrix = _StubMatrix()


def _args_for(cls):
    """Build kwargs for a constructor by parameter NAME.

    The two implementations do not share a signature. The core base takes
    ``(display_manager, config, custom_logger, global_config)``; the soccer
    lineage's bundled class takes ``(display_manager, display_width,
    display_height, config, plugin_dir, global_config)``. Both are correct for
    their own caller, so this supplies whatever each one asks for rather than
    assuming one shape -- which is also why it keeps working if a plugin's
    constructor grows a parameter.
    """
    import inspect
    import logging
    import os

    known = {
        "display_manager": _StubDisplayManager(),
        "display_width": 128,
        "display_height": 32,
        "config": {},
        "custom_logger": logging.getLogger("test_core_fallback"),
        "logger": logging.getLogger("test_core_fallback"),
        "global_config": {},
        "plugin_dir": os.path.dirname(os.path.abspath(__file__)),
    }
    # Union the named parameters across the MRO, not just the class's own
    # __init__. Several plugins declare `__init__(self, *args, **kwargs)` purely
    # to set an attribute before delegating up, so inspecting that one alone
    # yields no parameters at all and constructs nothing. Passing the base's
    # names as keywords works because those wrappers forward **kwargs.
    kwargs = {}
    for klass in cls.__mro__:
        init = klass.__dict__.get("__init__")
        if init is None:
            continue
        for name, param in inspect.signature(init).parameters.items():
            if name == "self" or param.kind in (
                    param.VAR_POSITIONAL, param.VAR_KEYWORD):
                continue
            if name in known:
                kwargs.setdefault(name, known[name])
            elif param.default is param.empty:
                raise AssertionError(
                    f"{klass.__name__}.__init__ needs an unrecognised argument "
                    f"{name!r}; teach _args_for about it"
                )
    return kwargs


def _build(mod):
    """Construct both classes the way the plugin's manager does."""
    display = mod.ScrollDisplay(**_args_for(mod.ScrollDisplay))
    manager = mod.ScrollDisplayManager(**_args_for(mod.ScrollDisplayManager))
    # get_scroll_display() is where the manager first builds a display, so a
    # constructor that raises shows up here rather than at first render.
    manager.get_scroll_display("recent")
    return display


def _unset_self_attributes(instance, cls):
    """`self.X` reads that nothing in the class assigns and the object lacks.

    Replaces a comparative check. The old one diffed the constructed core
    object against the constructed legacy one, which is how afl's unset
    `_game_renderer` was found: the bundled __init__ set it to None, the
    adopted class did not, `prepare_scroll_content` opens with
    `if self._game_renderer is None`, and because the core base CATCHES
    exceptions out of that method the only symptom was scroll mode quietly
    drawing nothing.

    There is no legacy object to diff against after the sunset, so the same
    fact is established statically: an attribute a method reads, that no
    assignment in the class binds and no base sets on a real instance, raises
    AttributeError the first time that method runs.

    Assignments ANYWHERE in the class count as bound, not just those in
    __init__ -- a cache populated inside the same method that reads it is
    correct and must not be reported.
    """
    import inspect
    import textwrap

    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(cls)))
    except (OSError, TypeError):  # pragma: no cover - source is always here
        return []

    assigned, read = set(), set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "self"):
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                assigned.add(node.attr)
            else:
                read.add(node.attr)

    return sorted(name for name in read - assigned
                  if not hasattr(instance, name))


def test_scroll_display_constructs():
    """Building the display must work, and every attribute it reads must exist.

    This is the check that would have caught the separator-icon constants being
    left behind on the legacy class: `_load_separator_icons` was lifted verbatim
    and reads them off `self`, and the core base calls it from `__init__` -- so
    the miss was not a degraded icon, it was an AttributeError that stopped the
    display being constructed at all. Scroll mode was dead for three plugins
    while every other gate stayed green.
    """
    import logging

    logging.disable(logging.CRITICAL)
    try:
        display = _build(_fresh_scroll_display())
    finally:
        logging.disable(logging.NOTSET)

    assert hasattr(display, "_separator_icons"), (
        "_load_separator_icons is called from the core base's __init__; a "
        "missing *_SEPARATOR_ICON constant raises AttributeError there and "
        "stops the display being constructed at all"
    )

    unset = _unset_self_attributes(display, type(display))
    assert not unset, (
        f"{type(display).__name__} methods read {unset}, which nothing assigns "
        f"and the built object does not carry — they raise AttributeError the "
        f"first time those methods run"
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

    print("core scroll import tests (post-sunset)")
    print("=" * 55)
    failures = []
    for t in (test_the_core_import_is_unguarded,
              test_the_bundled_copy_is_gone,
              test_the_classes_are_defined_at_module_level,
              test_the_base_is_the_core_class,
              test_the_manifest_floors_at_the_release_that_ships_the_module,
              test_content_methods_can_resolve_what_they_use,
              test_scroll_display_constructs,
              test_an_old_core_fails_naming_the_module):
        try:
            t()
            print(f"PASS {t.__name__}")
        # Any exception is a failure. Narrower clauses let the construction
        # test's AttributeError escape and kill the runner mid-suite, so the
        # bug it caught was reported as a crash rather than against its name.
        except Exception as e:
            failures.append(t.__name__)
            print(f"[FAIL] {t.__name__}: {e}")
    print("=" * 55)
    if failures:
        print(f"{len(failures)} test(s) failed: {failures}")
        sys.exit(1)
    print("All tests passed.")
