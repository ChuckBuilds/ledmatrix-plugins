#!/usr/bin/env python3
"""
Tests that an update returning the same headlines keeps the rendered strip.

Regression under test: update() discarded the scroll cache and the rendered
headline images on every refresh, whether or not the headlines had changed.
An RSS feed mostly returns what it returned last time, so a still-correct
strip was thrown away and the next Vegas fetch rebuilt it -- measured on a
512x64 rig at 427ms for a 10220x64 image, on the render thread, which is
where the marquee's stutter came from.

The risk of the fix is the opposite failure: holding a strip that should
have been replaced. So most of this file is about the cases that MUST still
rebuild -- changed headlines, reordered headlines, a font or colour change,
a feed-set change -- rather than the saving itself.

The methods are exercised against a stand-in ``self``, so the test needs no
display manager, no network and no cache -- only that manager.py imports.

Run: <core-venv>/bin/python plugins/news/test_unchanged_headlines_keep_strip.py
"""

import sys
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))
for candidate in (Path("/home/rackpi/projects/LEDMatrix"),
                  plugin_dir.parents[2] / "LEDMatrix"):
    if (candidate / "src" / "plugin_system" / "base_plugin.py").exists():
        sys.path.insert(0, str(candidate))
        break

from manager import NewsTickerPlugin  # noqa: E402

failures = []


def check(label, ok):
    print(("  PASS  " if ok else "  FAIL  ") + label)
    if not ok:
        failures.append(label)


def headline(feed, title):
    return {"feed_name": feed, "title": title, "link": "http://x"}


BASE = [headline("BBC", "One"), headline("BBC", "Two"), headline("NPR", "Three")]


class _Ticker:
    """Stand-in carrying only what the signature check touches."""

    _headline_signature = NewsTickerPlugin._headline_signature

    def __init__(self, headlines=None):
        self.current_headlines = list(headlines if headlines is not None else BASE)
        self._headlines_signature = None


def signature_of(headlines):
    return _Ticker(headlines)._headline_signature()


def main():
    print("the same headlines produce the same signature")
    check("identical lists match", signature_of(BASE) == signature_of(list(BASE)))
    check("a fresh copy of each dict still matches",
          signature_of(BASE) ==
          signature_of([dict(h) for h in BASE]))

    print("\nanything the strip is rendered from must move it")
    cases = [
        ("a changed title",
         [headline("BBC", "One"), headline("BBC", "CHANGED"), headline("NPR", "Three")]),
        ("a changed feed name",
         [headline("SKY", "One"), headline("BBC", "Two"), headline("NPR", "Three")]),
        ("an added headline", BASE + [headline("NPR", "Four")]),
        ("a removed headline", BASE[:-1]),
        ("reordered headlines", list(reversed(BASE))),
    ]
    for label, headlines in cases:
        check("%s rebuilds" % label, signature_of(BASE) != signature_of(headlines))

    print("\nfields the strip is NOT rendered from do not force a rebuild")
    with_links = [dict(h, link="http://changed") for h in BASE]
    check("a changed link alone does not rebuild",
          signature_of(BASE) == signature_of(with_links))

    print("\nthe update decision itself")

    def would_rebuild(ticker, new_headlines):
        """The guard from update(), against the shipped signature method."""
        ticker.current_headlines = list(new_headlines)
        signature = ticker._headline_signature()
        rebuild = bool(ticker.current_headlines) and signature != ticker._headlines_signature
        if rebuild:
            ticker._headlines_signature = signature
        return rebuild

    ticker = _Ticker()
    check("the first update rebuilds", would_rebuild(ticker, BASE) is True)
    check("an identical refresh does not", would_rebuild(ticker, BASE) is False)
    check("still does not on a third refresh", would_rebuild(ticker, BASE) is False)
    changed = BASE[:-1] + [headline("NPR", "Breaking")]
    check("a real change does rebuild", would_rebuild(ticker, changed) is True)
    check("and settles again", would_rebuild(ticker, changed) is False)

    print("\nempty headlines never claim a valid strip")
    empty = _Ticker([])
    check("an empty refresh does not rebuild", would_rebuild(empty, []) is False)
    check("and leaves no signature behind", empty._headlines_signature is None)

    print("\nupdate() really is guarded by the signature")
    # would_rebuild() above mirrors the guard; on its own it would pass even
    # with the guard deleted from update(), which mutation testing confirmed.
    # This reads the shipped code: the scroll-cache discard must sit inside a
    # branch that compares the signature, which is the whole fix.
    import ast
    tree = ast.parse((plugin_dir / "manager.py").read_text(encoding="utf-8"))
    update_fn = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.FunctionDef) and n.name == "update"), None)
    check("update() exists", update_fn is not None)

    guarded = []
    if update_fn is not None:
        for node in ast.walk(update_fn):
            if not isinstance(node, ast.If):
                continue
            mentions_signature = any(
                isinstance(sub, ast.Attribute)
                and sub.attr == "_headlines_signature"
                for sub in ast.walk(node.test))
            if not mentions_signature:
                continue
            clears = [c for c in ast.walk(node)
                      if isinstance(c, ast.Call)
                      and getattr(c.func, "attr", None) == "clear_cache"]
            if clears:
                guarded.append(node)
    check("the scroll-cache discard is inside a signature-guarded branch",
          bool(guarded))

    # The branch must also record the new signature. Without that the stored
    # value stays None, the guard passes every time, and the saving silently
    # disappears while every test above still passes.
    stores = [n for node in guarded for n in ast.walk(node)
              if isinstance(n, ast.Assign)
              and any(isinstance(t, ast.Attribute)
                      and t.attr == "_headlines_signature" for t in n.targets)]
    check("the guarded branch records the new signature", bool(stores))

    # ...and nowhere else in update() discards it unguarded.
    if update_fn is not None:
        all_clears = [c for c in ast.walk(update_fn)
                      if isinstance(c, ast.Call)
                      and getattr(c.func, "attr", None) == "clear_cache"]
        guarded_clears = [c for node in guarded for c in ast.walk(node)
                          if isinstance(c, ast.Call)
                          and getattr(c.func, "attr", None) == "clear_cache"]
        check("no unguarded scroll-cache discard remains in update()",
              len(all_clears) == len(guarded_clears))

    print("\nre-render paths clear the signature")
    # A font, colour or feed-set change leaves the headlines identical while
    # invalidating what was drawn from them. If those paths did not clear the
    # signature, the panel would keep the old rendering indefinitely.
    source = (plugin_dir / "manager.py").read_text(encoding="utf-8")
    resets = source.count("self._headlines_signature = None")
    check("cleared in __init__, on config reload and on feed change (%d sites)"
          % resets, resets >= 3)
    for marker, label in (
        ("Colors and fonts are baked into the rendered headline images",
         "the font/colour reload path"),
        ("# Clear headlines cache to force refresh", "the feed-set change path"),
    ):
        index = source.find(marker)
        window = source[index:index + 500] if index != -1 else ""
        check("%s clears it" % label,
              "self._headlines_signature = None" in window)

    print("\n%s" % ("FAILED: %d" % len(failures) if failures
                    else "All checks passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
