#!/usr/bin/env python3
"""The "Logo Error" fallback must draw on the image it pastes.

Every copy did `ImageDraw.Draw(main_img.convert("RGB"))` -- a new image --
drew the text on that, then pasted `main_img.convert("RGB")`, another new
image without the text. A missing logo gave a black panel for the whole dwell.
baseball-scoreboard fixed its copy by keeping the converted image in a name.

The draw sits deep inside display paths that need fonts, logos and a display
manager, so this pins the shape of the code instead: a converted copy is never
passed straight to ImageDraw.Draw or paste, and each "Logo Error" block pastes
the image it drew on.

Run: <core-venv>/bin/python plugins/hockey-scoreboard/test_logo_error_is_drawn.py
"""

import re
import sys
from pathlib import Path

plugin_dir = Path(__file__).parent
failures = []


def check(name, ok, detail=None):
    if ok:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s%s" % (name, " -- %r" % (detail,) if detail is not None else ""))
        failures.append(name)


def main():
    blocks = 0
    for filename in ("hockey.py", "sports.py"):
        src = (plugin_dir / filename).read_text(encoding="utf-8")
        check("%s never draws on a throwaway converted copy" % filename,
              not re.search(r"ImageDraw\.Draw\(\s*\w+\.convert\(", src))
        for match in re.finditer(r'"Logo Error"', src):
            blocks += 1
            window = src[max(0, match.start() - 600): match.end() + 400]
            drawn_on = re.search(r"draw_final = ImageDraw\.Draw\((\w+)\)", window)
            pasted = re.search(r"\.paste\((\w+)\s*,", window[window.index('"Logo Error"'):])
            check("%s Logo Error block at offset %d pastes the image it drew on"
                  % (filename, match.start()),
                  bool(drawn_on and pasted and drawn_on.group(1) == pasted.group(1)),
                  (drawn_on and drawn_on.group(1), pasted and pasted.group(1)))
    check("found the three Logo Error fallbacks", blocks == 3, blocks)

    if failures:
        print("\n%d check(s) failed" % len(failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
