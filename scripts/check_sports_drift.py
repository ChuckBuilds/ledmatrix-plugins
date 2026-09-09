#!/usr/bin/env python3
"""Keep the copied sports modules from silently drifting apart.

The scoreboard plugins deliberately ship *copies* of `sports.py`,
`manager.py`, `game_renderer.py` and `scroll_display.py` rather than sharing
them (CLAUDE.md non-negotiable #7). The rule that makes that safe is "a fix in
one lineage must be ported to its siblings in the same PR", and until now
nothing enforced it.

It has been missed repeatedly. The `has_live_content()` logging throttle was
fixed in baseball (1.20.4), then football, then hockey/basketball/lacrosse
(#308) -- and ufc-scoreboard was still unfixed months later, logging once per
display frame whenever a card was live.

## What this checks

Not "all copies must be identical" -- they are not, and should not be. It
checks the weaker, useful property:

    a function that agrees across its lineages today must not start
    disagreeing tomorrow.

Functions that already differ are recorded in the baseline and ignored. So the
check costs nothing on the current tree, and fires exactly when someone edits
one copy of a function that all its siblings share.

## Normalisation

Bodies are compared as normalised ASTs: docstrings dropped, and sport-specific
identifiers folded to a placeholder so `mlb_live` and `nfl_live` compare equal.
That is what lets structurally identical code in different sports match.

Usage:
    python scripts/check_sports_drift.py              # check; non-zero on drift
    python scripts/check_sports_drift.py --update-baseline
    python scripts/check_sports_drift.py --verbose
"""

from __future__ import annotations

import argparse
import ast
import collections
import hashlib
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGINS_DIR = os.path.join(REPO, "plugins")
BASELINE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "sports_drift_baseline.json")

#: The files the lineages copy between each other.
TRACKED_FILES = ("sports.py", "manager.py", "game_renderer.py", "scroll_display.py")

#: Sport, league and competition tokens that legitimately differ between
#: lineages. Folded to a single placeholder before comparing, so that
#: `self.mlb_live` and `self.nfl_live` are the same shape.
SPORT_TOKENS = (
    "baseball", "basketball", "football", "hockey", "soccer", "lacrosse",
    "cricket", "ufc", "mma", "afl", "nrl", "f1", "formula",
    "mlb", "milb", "nhl", "nfl", "nba", "wnba", "ncaa", "ncaafb", "ncaam",
    "ncaaw", "ncaa_fb", "ncaa_baseball", "ncaa_basketball", "epl", "uefa",
    "mls", "laliga", "bundesliga", "seriea", "ligue1",
    "fighter", "fighters", "team", "teams", "game", "games", "match",
    "matches", "bout", "bouts", "race", "races", "fight", "fights",
)
_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])(" + "|".join(sorted(SPORT_TOKENS, key=len, reverse=True))
    + r")(?![A-Za-z0-9])", re.IGNORECASE)


_TOKEN_SET = {t.lower() for t in SPORT_TOKENS}
#: CamelCase word splitter, so UFCScoreboardPlugin -> [UFC, Scoreboard, Plugin].
_CAMEL_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+|_")


def fold(name: str) -> str:
    """Replace sport-specific tokens in an identifier with a placeholder.

    Handles both snake_case (`mlb_live` -> `S_live`) and CamelCase
    (`UFCScoreboardPlugin` -> `SScoreboardPlugin`). The CamelCase half matters
    more than it looks: each plugin names its manager class after its own
    sport, so without it no function in manager.py is ever compared against
    its siblings -- which is precisely where has_live_content() lives, and
    precisely the drift this check exists to catch.
    """
    name = _TOKEN_RE.sub("S", name)
    parts = _CAMEL_RE.findall(name)
    if not parts:
        return name
    return "".join("S" if p.lower() in _TOKEN_SET else p for p in parts)


class _Normalise(ast.NodeTransformer):
    """Fold identifiers and drop docstrings, so only shape remains."""

    def visit_Name(self, node):
        return ast.copy_location(ast.Name(id=fold(node.id), ctx=node.ctx), node)

    def visit_Attribute(self, node):
        self.generic_visit(node)
        node.attr = fold(node.attr)
        return node

    def visit_arg(self, node):
        node.arg = fold(node.arg)
        node.annotation = None
        return node

    def visit_keyword(self, node):
        self.generic_visit(node)
        if node.arg:
            node.arg = fold(node.arg)
        return node

    def visit_Constant(self, node):
        # String literals carry league names and log text; fold them too, and
        # collapse numbers so a tuned interval is not read as a shape change.
        if isinstance(node.value, str):
            return ast.copy_location(ast.Constant(value=fold(node.value)), node)
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return ast.copy_location(ast.Constant(value=0), node)
        return node

    def _strip_docstring(self, node):
        body = node.body
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            node.body = body[1:] or [ast.Pass()]
        return node

    def visit_FunctionDef(self, node):
        self.generic_visit(node)
        node.name = fold(node.name)
        node.decorator_list = []
        node.returns = None
        return self._strip_docstring(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        self.generic_visit(node)
        node.name = fold(node.name)
        node.decorator_list = []
        return self._strip_docstring(node)


def shape(node: ast.AST) -> str:
    """A stable hash of one function's normalised shape."""
    clone = _Normalise().visit(ast.parse(ast.unparse(node)))
    return hashlib.sha256(ast.dump(clone).encode()).hexdigest()[:16]


def collect(path: str):
    """Yield (qualified_name, node) for every function defined in a file."""
    try:
        tree = ast.parse(open(path, encoding="utf-8", errors="replace").read())
    except SyntaxError as exc:
        print(f"  ! {path}: {exc}", file=sys.stderr)
        return

    def walk(node, prefix=""):
        for child in node.body:
            if isinstance(child, ast.ClassDef):
                yield from walk(child, f"{prefix}{fold(child.name)}.")
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield f"{prefix}{fold(child.name)}", child
                # nested defs are closures; their shape rides along with the parent

    yield from walk(tree)


def build_index():
    """{(file, qualified_name): {plugin: shape_hash}}"""
    index = collections.defaultdict(dict)
    for plugin in sorted(os.listdir(PLUGINS_DIR)):
        pdir = os.path.join(PLUGINS_DIR, plugin)
        if not os.path.isdir(pdir) or not plugin.endswith("-scoreboard"):
            continue
        for fname in TRACKED_FILES:
            fpath = os.path.join(pdir, fname)
            if not os.path.isfile(fpath):
                continue
            for qname, node in collect(fpath):
                index[(fname, qname)][plugin] = shape(node)
    return index


def divergent(index):
    """Keys whose lineages do not all agree, with the grouping that shows it."""
    out = {}
    for key, per_plugin in index.items():
        if len(per_plugin) < 2:
            continue  # only one lineage has it; nothing to be out of step with
        groups = collections.defaultdict(list)
        for plugin, h in per_plugin.items():
            groups[h].append(plugin)
        if len(groups) > 1:
            out[key] = {h: sorted(v) for h, v in groups.items()}
    return out


#: Functions the core calls from the display path. has_live_content() and
#: display() run once per *frame* in Vegas mode, so an unguarded log line in
#: one is not a style nit -- it is hundreds of journal lines a second.
DISPLAY_PATH_FUNCTIONS = frozenset({
    "has_live_content", "display", "get_vegas_content", "get_live_modes",
    "get_all_vegas_content_items",
})

#: A guard mentioning any of these reads as a deliberate throttle.
THROTTLE_HINTS = ("log", "throttle", "interval", "changed", "due", "state",
                  "last_", "elapsed", "since", "verbose", "debug")

#: Only the levels that actually flood. An error on the display path is
#: exceptional by definition and should be logged; info/warning are the
#: ones that fire on the happy path once per frame.
NOISY_LEVELS = ("info", "warning", "warn")


def _parents(tree):
    out = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            out[child] = node
    return out


def _is_throttled(call, func, parents):
    """True if `call` sits under an `if` whose test looks like a throttle."""
    node = parents.get(call)
    while node is not None and node is not func:
        if isinstance(node, ast.If):
            names = {n.id.lower() for n in ast.walk(node.test) if isinstance(n, ast.Name)}
            names |= {n.attr.lower() for n in ast.walk(node.test) if isinstance(n, ast.Attribute)}
            blob = " ".join(names)
            if any(h in blob for h in THROTTLE_HINTS):
                return True
        node = parents.get(node)
    return False


def _in_except_handler(call, func, parents):
    """True if `call` sits inside an `except:` block within `func`."""
    node = parents.get(call)
    while node is not None and node is not func:
        if isinstance(node, ast.ExceptHandler):
            return True
        node = parents.get(node)
    return False


def unthrottled_display_logging():
    """Log calls on the display path with no throttle guard above them.

    This is the check that would have caught the ufc-scoreboard regression:
    has_live_content() guarded its False branch and left an INFO call in the
    live branch entirely unguarded, so a live card logged once per frame. It
    is deliberately a property check rather than a similarity check --
    has_live_content() legitimately differs between sports (one league vs
    three), so comparing shapes across lineages cannot separate "different
    because the sport is different" from "different because the throttle is
    missing".
    """
    findings = []
    for plugin in sorted(os.listdir(PLUGINS_DIR)):
        pdir = os.path.join(PLUGINS_DIR, plugin)
        if not os.path.isdir(pdir) or not plugin.endswith("-scoreboard"):
            continue
        for fname in TRACKED_FILES:
            fpath = os.path.join(pdir, fname)
            if not os.path.isfile(fpath):
                continue
            try:
                tree = ast.parse(open(fpath, encoding="utf-8", errors="replace").read())
            except SyntaxError:
                continue
            parents = _parents(tree)
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if node.name not in DISPLAY_PATH_FUNCTIONS:
                    continue
                for call in ast.walk(node):
                    if not (isinstance(call, ast.Call)
                            and isinstance(call.func, ast.Attribute)
                            and call.func.attr in NOISY_LEVELS):
                        continue
                    owner = call.func.value
                    owner_name = getattr(owner, "attr", getattr(owner, "id", ""))
                    if "log" not in str(owner_name).lower():
                        continue
                    if _in_except_handler(call, node, parents):
                        # Something went wrong; saying so is not noise, and by
                        # construction it is not the per-frame happy path.
                        continue
                    if not _is_throttled(call, node, parents):
                        findings.append((plugin, fname, node.name,
                                         call.func.attr, call.lineno))
    return findings


def _noisy_key(finding):
    """Identify a log call by plugin/file/function, not by line number.

    Line numbers move whenever anything above them is edited; keying on them
    would make the baseline churn on every unrelated change.
    """
    plugin, fname, func, level, _lineno = finding
    return f"{plugin}/{fname}::{func}::{level}"


def load_baseline():
    if not os.path.exists(BASELINE):
        return set(), set()
    with open(BASELINE, encoding="utf-8") as fh:
        data = json.load(fh)
    divergent_keys = {tuple(k.split("::", 1)) for k in data.get("known_divergent", [])}
    return divergent_keys, set(data.get("known_unthrottled", []))


def save_baseline(keys, noisy):
    payload = {
        "_comment": (
            "Generated by scripts/check_sports_drift.py --update-baseline. Two "
            "lists, both recording what is already true so the check starts "
            "green and fails only on NEW problems."),
        "_known_divergent": (
            "Functions whose sports-plugin copies already differ. The check "
            "fails only when a function that currently AGREES across its "
            "lineages starts to differ -- i.e. a fix landed in one copy and not "
            "its siblings. Removing an entry asserts a function is back in line."),
        "_known_unthrottled": (
            "Log calls on the display path with no throttle guard, keyed by "
            "plugin/file::function::level rather than line number so the "
            "baseline does not churn. Each is a candidate for the same fix "
            "ufc-scoreboard's has_live_content() got; the check exists to stop "
            "the list growing."),
        "known_divergent": sorted(f"{f}::{q}" for f, q in keys),
        "known_unthrottled": sorted(noisy),
    }
    with open(BASELINE, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--update-baseline", action="store_true",
                    help="record the current divergences and exit 0")
    ap.add_argument("--verbose", action="store_true",
                    help="also list what is already known-divergent")
    args = ap.parse_args()

    index = build_index()
    lineages = {p for per in index.values() for p in per}
    print(f"Scanned {len(lineages)} scoreboard lineages, "
          f"{len(index)} function(s) across {len(TRACKED_FILES)} tracked files.")

    now = divergent(index)

    all_noisy = unthrottled_display_logging()

    if args.update_baseline:
        save_baseline(set(now), {_noisy_key(f) for f in all_noisy})
        print(f"Baseline written: {len(now)} known-divergent function(s), "
              f"{len({_noisy_key(f) for f in all_noisy})} known-unthrottled log call(s).")
        print(f"  {os.path.relpath(BASELINE, REPO)}")
        return 0

    known, known_noisy = load_baseline()
    new = {k: v for k, v in now.items() if k not in known}
    healed = sorted(known - set(now))

    if args.verbose and known:
        print(f"\n{len(known)} function(s) known-divergent and ignored.")

    if healed:
        print(f"\n{len(healed)} function(s) are back in sync and can be dropped "
              f"from the baseline:")
        for fname, qname in healed[:20]:
            print(f"  {fname}::{qname}")
        print("  (run --update-baseline)")

    noisy = [f for f in all_noisy if _noisy_key(f) not in known_noisy]

    if not new and not noisy:
        print("\nOK: no sports-lineage function has newly drifted, and no "
              "unthrottled logging on the display path.")
        return 0

    if noisy:
        print(f"\nNEW UNTHROTTLED LOGGING: {len(noisy)} log call(s) on the "
              f"display path with no throttle guard.\n")
        for plugin, fname, func, level, lineno in noisy:
            print(f"  {plugin}/{fname}:{lineno}  {func}() -> logger.{level}()")
        print()
        print("These functions run once per frame in Vegas mode. Guard the call")
        print("on a state change plus an interval -- see baseball-scoreboard's")
        print("has_live_content() for the reference shape.")

    if not new:
        return 1

    print(f"\nDRIFT: {len(new)} function(s) that used to agree across their "
          f"lineages no longer do.\n")
    for (fname, qname), groups in sorted(new.items()):
        print(f"  {fname}::{qname}")
        for h, plugins in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            print(f"      [{h}] {', '.join(plugins)}")
        print()
    print("A fix in one scoreboard must be ported to its siblings in the same PR")
    print("(CLAUDE.md non-negotiable #7). Port it, or -- if the difference is")
    print("intended -- run --update-baseline to record that.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
