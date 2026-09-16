#!/usr/bin/env python3
"""Render the contact sheets in ``plugins/blackjack/assets/``.

Every panel in the output is a real frame from the plugin's own renderer at the
true panel size, scaled up with nearest-neighbour -- not a mock-up -- so the
images cannot drift from what the display does. Run it from the plugin
directory with a Python that has Pillow:

    python test/render_examples.py [--out ../assets]

The hands are dealt from fixed seeds so re-running reproduces the same images.
"""

from __future__ import annotations

import argparse
import os
import random
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import blackjack_render as br  # noqa: E402
from blackjack_engine import (  # noqa: E402
    ACTION,
    DEAL,
    OUTCOME,
    REVEAL,
    TONE_BLACKJACK,
    TONE_LOSE,
    Rules,
    Shoe,
    hand_total,
    play_hand,
)
from blackjack_render import Theme, ViewState, compute_layout, render  # noqa: E402

CAPTION_COLOR = (150, 156, 172)
TITLE_COLOR = (228, 232, 244)
BG = (14, 14, 18)

# Beat durations, matching the plugin's schema defaults, so the timeline these
# sheets sample is the one a stock install plays.
INTRO, CARD, ACT, REVEAL_S, RESULT = 0.8, 2.0, 1.2, 1.8, 4.0
DEAL_ANIM, FLIP, BANNER_IN = 0.45, 0.55, 0.7
# Derived in the plugin, not configured, so they are derived the same way here.
SETTLED_AT = 0.8
HOLD = min(0.35, max(0.0, (REVEAL_S - FLIP) * 0.4))
GLOW = 0.5


def build_timeline(script):
    """``[(start, duration, event)]`` plus the total, at the schema defaults."""
    durations = {DEAL: CARD, ACTION: ACT, REVEAL: REVEAL_S, OUTCOME: RESULT}
    timeline, cursor = [], INTRO
    for event in script.events:
        duration = durations.get(event.kind, CARD)
        timeline.append((cursor, duration, event))
        cursor += duration
    return timeline, cursor


def call_out(state, seat, cards, local, duration):
    """Mirror of ``BlackjackPlugin._call_out``."""
    total = hand_total(cards)[0]
    if total > 21:
        text, tone = "BUST", TONE_LOSE
    elif seat == "player" and len(cards) == 2 and total == 21:
        text, tone = "21", TONE_BLACKJACK
    else:
        return
    settled_at = DEAL_ANIM * SETTLED_AT
    state.action_text = text
    state.action_tone = tone
    state.action_seat = seat
    state.action_progress = min(1.0, max(0.0, (local - settled_at)) / max(
        1e-6, duration - settled_at))


def state_at(script, timeline, elapsed):
    """The same replay the plugin does, kept in step with ``manager.py``."""
    state = ViewState()
    state.dealer_final = script.dealer_card_count
    state.player_final = script.player_card_count
    dealer_settled = player_settled = 0
    for start, duration, event in timeline:
        if elapsed < start:
            break
        local = elapsed - start
        running = local < duration
        if event.kind == DEAL:
            cards = state.dealer_cards if event.seat == "dealer" else state.player_cards
            cards.append(event.card)
            index = len(cards) - 1
            progress = min(1.0, local / DEAL_ANIM)
            if running and progress < 1.0:
                state.dealing = (event.seat, index, progress)
            if progress >= SETTLED_AT:
                if event.seat == "dealer":
                    dealer_settled = index + 1
                else:
                    player_settled = index + 1
                if running:
                    call_out(state, event.seat, cards, local, duration)
        elif event.kind == ACTION and running:
            state.action_text = event.text
            state.action_seat = "player"
            state.action_progress = local / duration
        elif event.kind == REVEAL:
            state.hole_flip = min(1.0, max(0.0, (local - HOLD) / FLIP))
            settled_at = HOLD + FLIP
            if local >= settled_at:
                state.reveal_glow = max(0.0, 1.0 - (local - settled_at) / GLOW)
                if running and len(state.dealer_cards) == 2 \
                        and hand_total(state.dealer_cards)[0] == 21:
                    state.action_text = "21"
                    state.action_tone = TONE_LOSE
                    state.action_seat = "dealer"
                    state.action_progress = min(1.0, (local - settled_at) / max(
                        1e-6, duration - settled_at))
        elif event.kind == OUTCOME:
            state.banner_text = event.text
            state.banner_subtext = event.subtext
            state.banner_flourish = script.flourish
            state.banner_tone = event.tone
            state.banner_progress = min(1.0, local / BANNER_IN)
            state.banner_elapsed = local
    state.hole_down = state.hole_flip < 1.0
    if state.player_cards and player_settled:
        state.player_total = hand_total(state.player_cards[:player_settled])[0]
    if state.hole_flip >= 0.5 and dealer_settled:
        state.dealer_total = hand_total(state.dealer_cards[:dealer_settled])[0]
    state.clock = elapsed
    return state


def frame(script, timeline, elapsed, width, height, theme=None):
    theme = theme or Theme()
    layout = compute_layout(width, height, script.dealer_card_count,
                            script.player_card_count)
    return render(width, height, layout, state_at(script, timeline, elapsed), theme)


def deal_until(seed, predicate, rules=None, limit=4000):
    """First hand from ``seed`` that satisfies ``predicate``, and its timeline."""
    rules = rules or Rules()
    shoe = Shoe(rules.decks, random.Random(seed))
    for _ in range(limit):
        script = play_hand(shoe, rules)
        if predicate(script):
            timeline, total = build_timeline(script)
            return script, timeline, total
    raise SystemExit(f"no hand matching the predicate in {limit} deals from seed {seed}")


# --------------------------------------------------------------------------
# Sheet assembly
# --------------------------------------------------------------------------


def caption(draw, x, y, text, color=CAPTION_COLOR, scale=1):
    br.draw_text(draw, x, y, text, color, scale)


def panel(sheet, image, x, y, zoom, border=(48, 50, 62)):
    scaled = image.resize((image.width * zoom, image.height * zoom), Image.NEAREST)
    sheet.paste(scaled, (x, y))
    ImageDraw.Draw(sheet).rectangle(
        [x - 1, y - 1, x + scaled.width, y + scaled.height], outline=border)
    return scaled.width, scaled.height


def sheet_moments(path, width=128, height=32, zoom=4):
    """One hand, beat by beat, on the baseline panel."""
    script, timeline, total = deal_until(
        11, lambda s: s.player_card_count >= 3 and s.dealer_card_count >= 3)
    beats = []
    for start, duration, event in timeline:
        if event.kind == DEAL:
            label = f"DEAL {event.seat.upper()}"
            # Early in the slide, not a quarter of a second in: under an
            # ease-out the card has already covered most of the distance by
            # then, so the old sample showed a card that had all but landed
            # and the sheet read as if there were no animation at all.
            beats.append((start + 0.08, "  " + label + " (IN FLIGHT)"))
            beats.append((start + duration - 0.2, "  " + label + " SETTLED"))
        elif event.kind == ACTION:
            beats.append((start + duration * 0.5, "  PLAYER CALLS " + event.text))
        elif event.kind == REVEAL:
            beats.append((start + HOLD * 0.6, "  HOLE CARD - THE PAUSE"))
            beats.append((start + HOLD + FLIP * 0.5, "  HOLE CARD MID FLIP"))
            beats.append((start + HOLD + FLIP + 0.1, "  HOLE CARD REVEALED"))
            beats.append((start + duration - 0.2, "  HOLE CARD UP"))
        elif event.kind == OUTCOME:
            beats.append((start + 0.09, "  BANNER - RULES SWEEP"))
            beats.append((start + 0.30, "  BANNER - WORD LANDING"))
            beats.append((start + duration * 0.6, "  RESULT"))
    beats = [beats[0]] + beats[2:]  # the first card's two frames say the same thing

    pad, gap, top = 12, 6, 26
    cell_h = height * zoom + 8 + gap
    sheet = Image.new("RGB", (width * zoom + pad * 2, top + cell_h * len(beats) + pad), BG)
    draw = ImageDraw.Draw(sheet)
    caption(draw, pad, 8, "BLACKJACK - ONE HAND, BEAT BY BEAT  128x32", TITLE_COLOR, 2)
    for index, (when, label) in enumerate(beats):
        y = top + index * cell_h
        caption(draw, pad, y, f"{when:5.1f}S{label}")
        panel(sheet, frame(script, timeline, when, width, height), pad, y + 8, zoom)
    sheet.save(path)
    return path, total


def sheet_sizes(path, zoom_for=None):
    """The same instant of the same hand on every size the harness renders."""
    sizes = [(64, 32), (128, 32), (64, 64), (96, 48),
             (128, 64), (256, 32), (128, 96), (256, 128)]
    script, timeline, _ = deal_until(4, lambda s: s.player_card_count == 3)
    reveal_start = next(start for start, _, event in timeline if event.kind == REVEAL)
    when = reveal_start + REVEAL_S - 0.2

    zoom = zoom_for or 2
    pad, gap, head = 12, 14, 28
    cells = [(w, h, frame(script, timeline, when, w, h)) for w, h in sizes]
    col_w = max(w for w, _, _ in cells) * zoom
    sheet_h = head + sum(h * zoom + 10 + gap for _, h, _ in cells) + pad
    sheet = Image.new("RGB", (col_w + pad * 2, sheet_h), BG)
    draw = ImageDraw.Draw(sheet)
    caption(draw, pad, 8, "ONE TABLE, EVERY PANEL SHAPE", TITLE_COLOR, 2)
    y = head
    for w, h, image in cells:
        note = "COLUMNS" if w >= 5 * h else "STACKED"
        caption(draw, pad, y, f"{w}X{h}  {note}")
        panel(sheet, image, pad, y + 8, zoom)
        y += h * zoom + 10 + gap
    sheet.save(path)
    return path


def sheet_outcomes(path, width=128, height=32, zoom=4):
    """Every banner the plugin can end on."""
    wanted = [
        ("BLACKJACK!", lambda s: s.outcome_text == "BLACKJACK!"),
        ("YOU WIN!", lambda s: s.outcome_text == "YOU WIN!"),
        ("DEALER BUST", lambda s: s.outcome_text == "DEALER BUST"),
        ("BUST!", lambda s: s.outcome_text == "BUST!"),
        ("DEALER WINS", lambda s: s.outcome_text == "DEALER WINS"),
        ("PUSH", lambda s: s.outcome_text == "PUSH"),
        ("DEALER 21", lambda s: s.outcome_text == "DEALER 21"),
    ]
    pad, gap, head = 12, 6, 26
    cell_h = height * zoom + 8 + gap
    sheet = Image.new("RGB", (width * zoom + pad * 2, head + cell_h * len(wanted) + pad), BG)
    draw = ImageDraw.Draw(sheet)
    caption(draw, pad, 8, "HOW A HAND CAN END", TITLE_COLOR, 2)
    for index, (label, predicate) in enumerate(wanted):
        script, timeline, total = deal_until(100 + index, predicate)
        when = total - RESULT * 0.35
        y = head + index * cell_h
        caption(draw, pad, y, label)
        panel(sheet, frame(script, timeline, when, width, height), pad, y + 8, zoom)
    sheet.save(path)
    return path


def sheet_styles(path, width=128, height=64, zoom=3):
    """Card styles and the two seat treatments, side by side."""
    script, timeline, _ = deal_until(23, lambda s: s.player_card_count == 3)
    reveal_start = next(start for start, _, event in timeline if event.kind == REVEAL)
    when = reveal_start + REVEAL_S - 0.2

    variants = []
    outline = Theme()
    variants.append(("OUTLINE (DEFAULT)", frame(script, timeline, when, width, height, outline)))
    solid = Theme()
    solid.card_style = "solid"
    variants.append(("SOLID CARD FACES", frame(script, timeline, when, width, height, solid)))
    warm = Theme()
    warm.dealer, warm.player, warm.felt = (255, 90, 90), (120, 255, 170), (70, 60, 130)
    variants.append(("CUSTOM ACCENTS", frame(script, timeline, when, width, height, warm)))
    bare = Theme()
    bare.table_style = "void"
    variants.append(("VOID TABLE", frame(script, timeline, when, width, height, bare)))
    # 64x32 rather than 128x32: a 128-wide seat has room to set its name
    # beside the hand, so the panel that still shows the bar fallback is a
    # narrower one.
    variants.append(("TOO NARROW FOR NAMES, SEAT BARS",
                     frame(script, timeline, when, 64, 32, outline)))

    pad, gap, head = 12, 14, 28
    col_w = width * zoom
    sheet_h = head + sum(image.height * zoom + 10 + gap for _, image in variants) + pad
    sheet = Image.new("RGB", (col_w + pad * 2, sheet_h), BG)
    draw = ImageDraw.Draw(sheet)
    caption(draw, pad, 8, "APPEARANCE OPTIONS", TITLE_COLOR, 2)
    y = head
    for label, image in variants:
        caption(draw, pad, y, label)
        panel(sheet, image, pad, y + 8, zoom)
        y += image.height * zoom + 10 + gap
    sheet.save(path)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets"))
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)

    hand, total = sheet_moments(os.path.join(args.out, "hand.png"))
    print(f"wrote {hand} (hand runs {total:.1f}s)")
    print("wrote", sheet_sizes(os.path.join(args.out, "sizes.png")))
    print("wrote", sheet_outcomes(os.path.join(args.out, "outcomes.png")))
    print("wrote", sheet_styles(os.path.join(args.out, "styles.png")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
