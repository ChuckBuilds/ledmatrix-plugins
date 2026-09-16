#!/usr/bin/env python3
"""Render the animated preview and the store hero image.

The contact sheets in assets/ sample a hand at chosen instants, which is the
right way to inspect a layout and the wrong way to judge motion: the deal
slide, the flip and the banner's shutter are all sub-second, and a still of
one cannot show whether it reads. This writes the hand out as it actually
plays, in real time, so the pacing can be judged rather than imagined.

    python test/render_preview.py [--size 128x32] [--fps 20] [--scale 3]

Frames come from the plugin's own renderer at the true panel size and are
scaled with nearest-neighbour, so nothing here is a mock-up.

Seeded ``random.Random`` appears here and is flagged B311 by static analysis.
It is deliberate and not a security question: a fixed seed is what makes these
reproducible. The shoe a *player* is dealt from uses ``random.SystemRandom``
(see ``blackjack_engine.Shoe``), and an engine test asserts that seeding the
``random`` module anywhere in the process cannot change it.
"""

from __future__ import annotations

import argparse
import os
import random
import sys

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from blackjack_engine import Rules, Shoe, play_hand  # noqa: E402
from blackjack_render import Theme, compute_layout, render  # noqa: E402
from render_examples import build_timeline, state_at  # noqa: E402


def parse_size(token: str):
    width, height = token.lower().split("x", 1)
    return int(width), int(height)


def find_hand(seed: int, predicate, limit: int = 4000):
    shoe = Shoe(6, random.Random(seed))  # nosec B311
    for _ in range(limit):
        script = play_hand(shoe, Rules())
        if predicate(script):
            timeline, total = build_timeline(script)
            return script, timeline, total
    raise SystemExit(f"no hand matching the predicate in {limit} deals from seed {seed}")


def frames_for(script, timeline, total, width, height, fps, scale, tail=0.6):
    """Every frame of the hand, in order, already scaled up.

    `tail` holds a little past the end so the GIF does not cut the banner off
    the instant it is finished -- the loop point is the most-looked-at frame in
    a preview and it should be the result, not a wipe.
    """
    layout = compute_layout(width, height, script.dealer_card_count,
                            script.player_card_count)
    theme = Theme()
    step = 1.0 / fps
    out = []
    when = 0.0
    while when < total + tail:
        image = render(width, height, layout, state_at(script, timeline, min(when, total)),
                       theme)
        out.append(image.resize((width * scale, height * scale), Image.NEAREST))
        when += step
    return out


def write_gif(path, frames, fps):
    # A palette built from the whole hand rather than per frame: an adaptive
    # palette recomputed per frame makes the dim table behind the banner shift
    # hue from frame to frame, which on a near-black image reads as noise.
    montage = Image.new("RGB", (frames[0].width, frames[0].height * len(frames)))
    for index, frame in enumerate(frames):
        montage.paste(frame, (0, index * frames[0].height))
    palette = montage.quantize(colors=128, method=Image.MEDIANCUT).getpalette()
    reference = Image.new("P", (1, 1))
    reference.putpalette(palette)
    quantized = [frame.quantize(palette=reference, dither=Image.NONE) for frame in frames]
    quantized[0].save(path, save_all=True, append_images=quantized[1:],
                      duration=int(round(1000.0 / fps)), loop=0, optimize=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", default="128x32")
    parser.add_argument("--fps", type=float, default=20.0)
    parser.add_argument("--scale", type=int, default=3)
    parser.add_argument("--out", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets"))
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)
    width, height = parse_size(args.size)

    # A hand worth watching: the player draws, so there is a call and a hit,
    # and the dealer draws too, so the reveal is not the last thing that
    # happens. A two-card stand would show half the plugin's vocabulary.
    script, timeline, total = find_hand(
        11, lambda s: s.player_card_count >= 3 and s.dealer_card_count >= 3)
    frames = frames_for(script, timeline, total, width, height, args.fps, args.scale)
    gif_path = os.path.join(args.out, "preview.gif")
    write_gif(gif_path, frames, args.fps)
    size_kb = os.path.getsize(gif_path) / 1024.0
    print(f"wrote {gif_path} ({len(frames)} frames, {total:.1f}s of play, "
          f"{width}x{height} at {args.scale}x, {size_kb:.0f} KB)")

    # The store hero: a natural, caught the instant before the banner opens.
    #
    # The obvious choice is the banner itself -- it is the loudest frame and it
    # says the plugin's name. It is also the frame where the table is dimmed to
    # 28% and the cards are three-quarters hidden behind a band, so a gallery
    # thumbnail of it shows a word and no blackjack. The frame that sells the
    # plugin is the one it spends most of its time on: a full table, cards
    # readable, both totals up.
    hero_script, hero_timeline, hero_total = find_hand(
        100, lambda s: s.outcome_text == "BLACKJACK!")
    hero_w, hero_h, hero_scale = 128, 64, 4
    hero_layout = compute_layout(hero_w, hero_h, hero_script.dealer_card_count,
                                 hero_script.player_card_count)
    banner_at = next(start for start, _, event in hero_timeline
                     if event.kind == "outcome")
    hero = render(hero_w, hero_h, hero_layout,
                  state_at(hero_script, hero_timeline, banner_at - 0.25), Theme())
    hero = hero.resize((hero_w * hero_scale, hero_h * hero_scale), Image.NEAREST)
    hero_path = os.path.join(args.out, "hero.png")
    hero.save(hero_path)
    print(f"wrote {hero_path} ({hero_w}x{hero_h} at {hero_scale}x)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
