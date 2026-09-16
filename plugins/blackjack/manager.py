"""Blackjack — a hand of Vegas blackjack dealt on the matrix, once per rotation.

How it fits together:

* :mod:`blackjack_engine` simulates the whole hand *before the first pixel is
  drawn* and returns a script of beats (deal, call, reveal, result).
* This file turns that script into a timeline by giving each beat a duration
  from config, and converts ``elapsed`` into a
  :class:`~blackjack_render.ViewState`.
* :mod:`blackjack_render` turns a ``ViewState`` into an image.

Simulating up front is what makes the rest simple. The plugin can tell the
display controller exactly how long this rotation needs
(``get_cycle_duration``), every frame is a pure function of elapsed time with
no animation state to drift, and the card slots can be laid out from the final
card count so nothing slides sideways when a fifth card arrives.
"""

from __future__ import annotations

import random
import time
from typing import Any, Dict, List, Optional, Tuple

from PIL import ImageDraw

from src.plugin_system.base_plugin import BasePlugin

from blackjack_engine import (
    ACTION,
    DEAL,
    OUTCOME,
    REVEAL,
    TONE_BLACKJACK,
    TONE_LOSE,
    Event,
    HandScript,
    Rules,
    Shoe,
    hand_total,
    play_hand,
)
from blackjack_render import (
    Theme,
    ViewState,
    DECK_COLOR_SCHEMES,
    DECK_FOUR,
    TABLE_FELT,
    TABLE_STYLES,
    compute_layout,
    render,
)

#: Fraction of a deal beat spent on the slide, before the card flips face up.
#: Mirrors ``_draw_dealing_card`` in the renderer -- a card counts toward the
#: running total once its flip is past halfway, which is this plus a bit.
_DEAL_SETTLED_AT = 0.8

#: How long the just-revealed hole card keeps its bright edge. Long enough to
#: register at a glance, short enough to be over before the dealer draws.
_REVEAL_GLOW_SECONDS = 0.5

#: A gap longer than this between display() calls means the rotation left and
#: came back, so the next frame starts a fresh hand. Comfortably longer than
#: the slowest frame the core will ask for (1s in the non-high-FPS loop) and
#: far shorter than any rotation.
_TURN_GAP_SECONDS = 2.5


class BlackjackPlugin(BasePlugin):
    """Deals one hand of blackjack per rotation and plays it out on the panel."""

    def __init__(self, plugin_id, config, display_manager, cache_manager, plugin_manager):
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)

        # Render at every frame the core offers. The deal, the flip and the
        # banner are all sub-second moves; at the standard one-frame-per-second
        # cadence they would be a slideshow of three stills.
        self.needs_high_fps = True

        self._script: Optional[HandScript] = None
        self._timeline: List[Tuple[float, float, Event]] = []
        self._total_duration = 0.0
        self._hand_started = 0.0
        self._last_display = 0.0
        self._last_render = 0.0
        self._layout = None
        self._layout_key: Optional[Tuple[int, int, int, int]] = None
        self._hands_played = 0
        #: Consecutive player wins, for the streak call-out. Session-only: a
        #: streak that survived a restart would be a statistic, not a moment.
        self._win_streak = 0
        self._shoe: Optional[Shoe] = None

        self._apply_config(config)

        self.logger.info(
            "Blackjack ready: %d decks, dealer %s soft 17, double %s",
            self.rules.decks,
            "hits" if self.rules.hit_soft_17 else "stands on",
            "on" if self.rules.allow_double else "off",
        )

    def _apply_config(self, config: Dict[str, Any]) -> None:
        """Read every setting into the shape the render path wants.

        Separate from ``__init__`` so ``on_config_change`` can re-read settings
        without re-running the base constructor -- which would re-register the
        plugin's services and, more visibly, throw away the shoe mid-shoe.
        """
        self.rules = Rules(
            decks=int(config.get("decks", 6)),
            hit_soft_17=bool(config.get("dealer_hits_soft_17", False)),
            allow_double=bool(config.get("allow_double", True)),
        )

        seed = config.get("random_seed", 0)
        # Seeded only for tests and goldens. Unseeded means SystemRandom, whose
        # sequence nothing in the process can influence -- so two panels booted
        # together still deal different hands.
        self._rng: Optional[random.Random] = random.Random(seed) if seed else None
        if self._shoe is None or self._shoe.decks != self.rules.decks or seed:
            self._shoe = Shoe(self.rules.decks, self._rng, self.rules.penetration)

        self.theme = self._build_theme(config)
        self.show_labels = bool(config.get("show_labels", True))
        self.show_totals = bool(config.get("show_totals", True))

        self.intro_seconds = self._positive(config, "intro_seconds", 0.8)
        self.card_interval = self._positive(config, "card_interval", 2.0)
        self.action_seconds = self._positive(config, "action_seconds", 1.2)
        self.reveal_seconds = self._positive(config, "reveal_seconds", 1.8)
        self.result_seconds = self._positive(config, "result_seconds", 4.0)
        self.deal_animation = self._positive(config, "deal_animation", 0.45)
        self.flip_seconds = self._positive(config, "flip_seconds", 0.55)
        # An animation longer than the beat it lives in would be cut off, so
        # clamp rather than let a config edit desynchronise the two.
        self.deal_animation = min(self.deal_animation, self.card_interval)
        self.flip_seconds = min(self.flip_seconds, self.reveal_seconds)
        self.banner_in_seconds = min(0.7, self.result_seconds * 0.35)
        # A dealer pauses with a hand on the hole card before turning it. Taken
        # out of the slack the reveal beat already has rather than added as a
        # knob: it is a fraction of a duration the user already controls, and a
        # hold that could be set longer than its own beat would be a way to
        # break the flip rather than a way to tune it.
        self._reveal_hold = min(
            0.35, max(0.0, (self.reveal_seconds - self.flip_seconds) * 0.4))

        render_fps = self._positive(config, "render_fps", 40.0)
        self._min_frame_interval = 1.0 / max(5.0, min(120.0, render_fps))
        self._layout_key = None

    # -- config helpers ---------------------------------------------------

    @staticmethod
    def _positive(config: Dict[str, Any], key: str, default: float) -> float:
        """A positive float from config, falling back on anything unusable.

        Every one of these is a duration. A zero or a string would either
        divide by zero in the progress maths or collapse a beat to nothing, so
        a bad value takes the default rather than the panel.
        """
        try:
            value = float(config.get(key, default))
        except (TypeError, ValueError):
            return float(default)
        return value if value > 0 else float(default)

    @staticmethod
    def _color(config: Dict[str, Any], key: str, default) -> Tuple[int, int, int]:
        value = config.get(key)
        if isinstance(value, (list, tuple)) and len(value) == 3:
            try:
                return tuple(max(0, min(255, int(component))) for component in value)
            except (TypeError, ValueError):
                return default
        return default

    def _build_theme(self, config: Dict[str, Any]) -> Theme:
        theme = Theme()
        theme.dealer = self._color(config, "dealer_color", theme.dealer)
        theme.player = self._color(config, "player_color", theme.player)
        theme.felt = self._color(config, "felt_color", theme.felt)
        style = str(config.get("card_style", "outline")).lower()
        theme.card_style = style if style in ("outline", "solid") else "outline"
        table = str(config.get("table_style", TABLE_FELT)).lower()
        theme.table_style = table if table in TABLE_STYLES else TABLE_FELT
        deck = str(config.get("deck_colors", DECK_FOUR)).lower()
        theme.deck_colors = deck if deck in DECK_COLOR_SCHEMES else DECK_FOUR
        return theme

    # -- hand lifecycle ---------------------------------------------------

    def _start_hand(self) -> None:
        """Simulate a fresh hand and lay its beats out on a timeline."""
        if self._shoe.needs_shuffle:
            # Between hands only. A shoe that reshuffled mid-hand would be able
            # to deal the same physical card twice.
            self._shoe.shuffle()
            self.logger.debug("Shoe reshuffled (%d decks)", self._shoe.decks)

        if self._script is not None:
            self._win_streak = (self._win_streak + 1
                                if self._script.payout > 0 else 0)
        script = play_hand(self._shoe, self.rules)
        if not script.flourish and script.payout > 0 and self._win_streak >= 2:
            # The hand about to be dealt would be the (streak + 1)th win, and
            # only an engine flourish outranks it -- a three-seven hand is a
            # better story than a run of three.
            script.flourish = f"RUN OF {self._win_streak + 1}"
        timeline: List[Tuple[float, float, Event]] = []
        cursor = self.intro_seconds
        for event in script.events:
            duration = {
                DEAL: self.card_interval,
                ACTION: self.action_seconds,
                REVEAL: self.reveal_seconds,
                OUTCOME: self.result_seconds,
            }.get(event.kind, self.card_interval)
            timeline.append((cursor, duration, event))
            cursor += duration

        self._script = script
        self._timeline = timeline
        self._total_duration = cursor
        self._hand_started = time.monotonic()
        self._layout_key = None      # card counts changed, so the slots move
        self._hands_played += 1
        self.logger.debug(
            "Dealt hand %d: player %d, dealer %d -> %s (%.1fs)",
            self._hands_played, script.player_total, script.dealer_total,
            script.outcome_text, self._total_duration,
        )

    def _elapsed(self) -> float:
        return max(0.0, time.monotonic() - self._hand_started)

    # -- state assembly ---------------------------------------------------

    def _view_state(self, elapsed: float) -> ViewState:
        """Replay the timeline up to ``elapsed`` and describe what is on the felt.

        Replaying from the start each frame rather than mutating state forward
        is O(20) on a hand and removes the whole class of bug where a dropped
        or repeated frame leaves the table showing something that never
        happened.
        """
        script = self._script
        state = ViewState()
        if script is None:
            return state

        state.dealer_final = script.dealer_card_count
        state.player_final = script.player_card_count

        dealer_settled = 0
        player_settled = 0

        for start, duration, event in self._timeline:
            if elapsed < start:
                break
            local = elapsed - start
            running = local < duration

            if event.kind == DEAL:
                cards = (state.dealer_cards if event.seat == "dealer"
                         else state.player_cards)
                cards.append(event.card)
                index = len(cards) - 1
                progress = min(1.0, local / self.deal_animation)
                if running and progress < 1.0:
                    state.dealing = (event.seat, index, progress)
                if progress >= _DEAL_SETTLED_AT:
                    if event.seat == "dealer":
                        dealer_settled = index + 1
                    else:
                        player_settled = index + 1
                    if running:
                        self._call_out(state, event.seat, cards, local, duration)

            elif event.kind == ACTION:
                if running:
                    state.action_text = event.text
                    state.action_seat = "player"
                    state.action_progress = local / duration

            elif event.kind == REVEAL:
                # The flip waits out the hold, so the pivotal card of the hand
                # gets a beat of stillness first. Starting it on the reveal
                # beat's first frame meant the turn began in the same frame the
                # player's call finished fading, and the two ran together.
                state.hole_flip = min(1.0, max(
                    0.0, (local - self._reveal_hold) / self.flip_seconds))
                settled_at = self._reveal_hold + self.flip_seconds
                if local >= settled_at:
                    state.reveal_glow = max(
                        0.0, 1.0 - (local - settled_at) / _REVEAL_GLOW_SECONDS)
                    if running and len(state.dealer_cards) == 2 \
                            and hand_total(state.dealer_cards)[0] == 21:
                        # A dealer natural otherwise passed unremarked: the
                        # hole card turned over and the banner simply said
                        # DEALER 21 four seconds later.
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
                state.banner_progress = min(1.0, local / self.banner_in_seconds)
                # Seconds, not a fraction: the burst, the gleam and the score
                # tally all have to last a fixed time, and ``banner_progress``
                # is a slice of an opening the user can configure to anything.
                state.banner_elapsed = local

        state.hole_down = state.hole_flip < 1.0
        if state.player_cards and player_settled:
            state.player_total = hand_total(state.player_cards[:player_settled])[0]
        # The hole card stays a question mark until it is more than half turned
        # over -- that is the moment the viewer can read it too.
        if state.hole_flip >= 0.5 and dealer_settled:
            state.dealer_total = hand_total(state.dealer_cards[:dealer_settled])[0]
        state.clock = elapsed
        return state

    def _call_out(self, state: ViewState, seat: str, cards, local: float,
                  duration: float) -> None:
        """Announce a hand that just went dead, or a natural, at the seat.

        These are the two moments of a hand the table said nothing about. A
        bust showed only as the running total quietly passing 21 -- the same
        silent number change as any other card -- and a two-card 21 looked
        exactly like a two-card 20 until the banner arrived. Both are announced
        out loud at a real table, and both are free here: the call tag already
        exists, so this only has to decide what it says and when.

        Timed from the moment the card *settles* rather than from the start of
        the beat, so the word does not arrive before the card it is about. The
        dealer's own two-card 21 is deliberately not called here -- its second
        card is the hole card, and shouting BLACKJACK over a face-down card
        would give the hand away.
        """
        total = hand_total(cards)[0]
        if total > 21:
            text, tone = "BUST", TONE_LOSE
        elif seat == "player" and len(cards) == 2 and total == 21:
            text, tone = "21", TONE_BLACKJACK
        else:
            return
        settled_at = self.deal_animation * _DEAL_SETTLED_AT
        state.action_text = text
        state.action_tone = tone
        state.action_seat = seat
        state.action_progress = min(1.0, max(0.0, (local - settled_at)) / max(
            1e-6, duration - settled_at))

    def _ensure_layout(self):
        width = self.display_manager.width
        height = self.display_manager.height
        dealer_n = self._script.dealer_card_count if self._script else 2
        player_n = self._script.player_card_count if self._script else 2
        key = (width, height, dealer_n, player_n)
        if key != self._layout_key:
            self._layout = compute_layout(width, height, dealer_n, player_n,
                                          self.show_labels, self.show_totals)
            self._layout_key = key
        return self._layout

    # -- core hooks -------------------------------------------------------

    def update(self) -> None:
        """Nothing to fetch. A hand of blackjack needs no network, and the
        cards are dealt in display() time so the animation stays in step."""
        return

    def display(self, force_clear: bool = False, display_mode: Optional[str] = None):
        try:
            now = time.monotonic()
            gap = now - self._last_display if self._last_display else None
            self._last_display = now

            # A new hand when the rotation hands us the screen: either the
            # controller says so (force_clear on a mode switch) or we were away
            # long enough that the last hand is stale. The 0.5s guard matters:
            # the controller calls reset_cycle_state() and *then* displays with
            # force_clear=True, and dealing twice for one turn would throw the
            # first hand away unseen.
            if self._script is None:
                self._start_hand()
                self._last_render = 0.0
            elif (force_clear or (gap is not None and gap > _TURN_GAP_SECONDS)) \
                    and self._elapsed() > 0.5:
                self._start_hand()
                self._last_render = 0.0

            elapsed = self._elapsed()
            if elapsed > self._total_duration and not self.supports_dynamic_duration():
                # Fixed-duration installs never get told the hand is over, so
                # the table deals another one rather than freezing on the
                # banner for the rest of the slot.
                self._start_hand()
                elapsed = 0.0
                self._last_render = 0.0

            if self._last_render and now - self._last_render < self._min_frame_interval:
                # The core offers 125 fps; the eye does not need it and a Pi
                # rendering a 256x128 table that often has better things to do.
                # Holding the frame is safe: the panel refreshes itself.
                return True
            self._last_render = now

            layout = self._ensure_layout()
            state = self._view_state(elapsed)
            image = render(self.display_manager.width, self.display_manager.height,
                           layout, state, self.theme)

            # Replace the buffer rather than clearing it: DisplayManager.clear()
            # writes straight to the matrix, so using it as a per-frame reset
            # makes the panel flash black between frames.
            self.display_manager.image = image
            self.display_manager.draw = ImageDraw.Draw(image)
            self.display_manager.update_display()
            return True
        except Exception as exc:  # noqa: BLE001 - a render bug must not kill rotation
            self.logger.error("Blackjack display failed: %s", exc, exc_info=True)
            return True

    # -- dynamic duration -------------------------------------------------

    def supports_dynamic_duration(self) -> bool:
        """On by default, unlike the base class.

        A hand is as long as it is -- two cards and a natural, or six cards and
        a dealer bust. Handing the controller a fixed slot either cuts the
        banner off or holds a finished table on screen; this is exactly the
        case dynamic duration exists for, so it is opt-*out* here.
        """
        config = self._get_dynamic_duration_config()
        return bool(config.get("enabled", True))

    def get_display_duration(self) -> float:
        return self._hand_duration()

    def get_cycle_duration(self, display_mode: Optional[str] = None) -> Optional[float]:
        return self._hand_duration()

    def get_dynamic_duration_cap(self) -> Optional[float]:
        config = self._get_dynamic_duration_config()
        cap = config.get("max_duration_seconds", 75)
        try:
            cap = float(cap)
        except (TypeError, ValueError):
            return 75.0
        return cap if cap > 0 else None

    def _hand_duration(self) -> float:
        """Seconds this hand needs, deal to banner.

        Before the first hand is dealt the controller still asks, so fall back
        to a typical hand: four cards, one call, the reveal and the result.
        """
        if self._total_duration > 0:
            return self._total_duration
        return (self.intro_seconds + 5 * self.card_interval + self.action_seconds
                + self.reveal_seconds + self.result_seconds)

    def is_cycle_complete(self) -> bool:
        if self._script is None:
            return False
        return self._elapsed() >= self._total_duration

    def reset_cycle_state(self) -> None:
        """The controller is about to give us the screen: deal a fresh hand."""
        super().reset_cycle_state()
        self._start_hand()
        self._last_render = 0.0

    # -- lifecycle / web UI ----------------------------------------------

    def on_config_change(self, new_config) -> None:
        super().on_config_change(new_config)
        self._apply_config(new_config or {})
        # The hand in progress was timed with the old durations; start a fresh
        # one so the timeline and the config agree.
        self._script = None

    def validate_config(self) -> bool:
        if not super().validate_config():
            return False
        decks = self.config.get("decks", 6)
        if not isinstance(decks, int) or isinstance(decks, bool) or not 1 <= decks <= 8:
            self.logger.error("'decks' must be an integer from 1 to 8")
            return False
        style = self.config.get("card_style", "outline")
        if style not in ("outline", "solid"):
            self.logger.error("'card_style' must be 'outline' or 'solid'")
            return False
        table = self.config.get("table_style", TABLE_FELT)
        if table not in TABLE_STYLES:
            self.logger.error("'table_style' must be one of %s",
                              ", ".join(TABLE_STYLES))
            return False
        deck = self.config.get("deck_colors", DECK_FOUR)
        if deck not in DECK_COLOR_SCHEMES:
            self.logger.error("'deck_colors' must be one of %s",
                              ", ".join(DECK_COLOR_SCHEMES))
            return False
        for key in ("dealer_color", "player_color", "felt_color"):
            if key in self.config:
                color = self.config[key]
                if (not isinstance(color, (list, tuple)) or len(color) != 3
                        or not all(isinstance(c, int) and 0 <= c <= 255 for c in color)):
                    self.logger.error("'%s' must be an RGB array [R, G, B]", key)
                    return False
        return True

    def get_info(self) -> Dict[str, Any]:
        info = super().get_info()
        info["hands_played"] = self._hands_played
        info["shoe_remaining"] = self._shoe.remaining
        if self._script is not None:
            info["last_result"] = self._script.outcome_text
            info["last_player_total"] = self._script.player_total
            info["last_dealer_total"] = self._script.dealer_total
        return info
