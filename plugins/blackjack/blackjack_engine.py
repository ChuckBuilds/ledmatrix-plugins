"""Blackjack hand simulation for the LEDMatrix ``blackjack`` plugin.

Pure logic and nothing else: a shuffled shoe, Vegas basic strategy for the
player, house rules for the dealer, and a replayable *script* of everything
that happened. No PIL and no core imports, so this file is unit-testable
anywhere and the renderer stays a pure function of ``(script, elapsed)``.

Two deliberate scope decisions, both documented in the README:

* **No splitting.** A split turns one hand into two, which doubles both the
  rotation length and the layout problem (two player rows on a 32px-tall
  panel is not a layout, it is a compromise). Pairs are played by their total,
  which is exactly what basic strategy says for a game that does not offer the
  split -- so the play stays correct, it just never branches.
* **No insurance or surrender.** Basic strategy never takes insurance, and
  surrender ends a hand with nothing to watch.

Everything else is Strip rules: 6-deck shoe, dealer stands on soft 17
(configurable), blackjack pays 3:2, dealer peeks for blackjack on a ten or an
ace.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

#: Rank labels, in the order a deck is built. ``"10"`` is two characters wide
#: everywhere else in this plugin; the renderer has a dedicated glyph for it.
RANKS: Tuple[str, ...] = ("A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K")

#: Suit keys. Colour and pip shape are the renderer's business; the engine only
#: carries them so the table looks like a real deck.
SUITS: Tuple[str, ...] = ("S", "H", "D", "C")

#: Suits drawn in red. Spades and clubs render in the light "black" ink.
RED_SUITS = frozenset(("H", "D"))


@dataclass(frozen=True)
class Card:
    """One card. ``rank`` is a member of :data:`RANKS`, ``suit`` of :data:`SUITS`."""

    rank: str
    suit: str

    @property
    def value(self) -> int:
        """Pip value with an ace counted low; :func:`hand_total` promotes aces."""
        if self.rank == "A":
            return 1
        if self.rank in ("J", "Q", "K", "10"):
            return 10
        return int(self.rank)

    @property
    def is_ace(self) -> bool:
        return self.rank == "A"

    @property
    def is_red(self) -> bool:
        return self.suit in RED_SUITS

    def __str__(self) -> str:  # pragma: no cover - debugging aid
        return f"{self.rank}{self.suit}"


def hand_total(cards: Sequence[Card]) -> Tuple[int, bool]:
    """``(total, is_soft)`` for a hand.

    One ace at a time can be promoted from 1 to 11, and only one ever can
    without busting, so this is a single conditional rather than a search.
    """
    total = sum(card.value for card in cards)
    has_ace = any(card.is_ace for card in cards)
    if has_ace and total + 10 <= 21:
        return total + 10, True
    return total, False


def is_blackjack(cards: Sequence[Card]) -> bool:
    """A *natural*: exactly two cards totalling 21. Three cards to 21 is not."""
    return len(cards) == 2 and hand_total(cards)[0] == 21


def upcard_index(card: Card) -> int:
    """Strategy-table column for a dealer upcard: 2-9 as themselves, ten-value
    cards as 10, ace as 11."""
    if card.is_ace:
        return 11
    return card.value if card.value < 10 else 10


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


@dataclass
class Rules:
    """House rules. Defaults are Las Vegas Strip: 6 decks, dealer stands on all
    17s, double on any first two cards."""

    decks: int = 6
    hit_soft_17: bool = False
    allow_double: bool = True
    #: Fraction of the shoe dealt before the cut card comes out.
    penetration: float = 0.75

    def __post_init__(self) -> None:
        self.decks = max(1, min(8, int(self.decks)))
        self.penetration = max(0.2, min(0.95, float(self.penetration)))


# ---------------------------------------------------------------------------
# Shoe
# ---------------------------------------------------------------------------


class Shoe:
    """A multi-deck shoe that reshuffles when the cut card is reached.

    The shoe is *persistent across hands* on purpose: that is what makes the
    stream of hands look like a real table rather than an endless sequence of
    independent draws from a fresh deck. It only matters statistically, but the
    cost of getting it right is one attribute.
    """

    def __init__(self, decks: int = 6, rng: Optional[random.Random] = None,
                 penetration: float = 0.75) -> None:
        self.decks = max(1, min(8, int(decks)))
        self.penetration = max(0.2, min(0.95, float(penetration)))
        # SystemRandom by default: seeded only by the OS entropy pool, so two
        # plugins starting in the same second cannot deal the same hand, and
        # nothing a user does makes the sequence predictable.
        self.rng = rng if rng is not None else random.SystemRandom()
        self._cards: List[Card] = []
        self.shuffles = 0
        self.shuffle()

    @property
    def full_size(self) -> int:
        return self.decks * 52

    @property
    def remaining(self) -> int:
        return len(self._cards)

    @property
    def needs_shuffle(self) -> bool:
        """True once the cut card is reached. Checked between hands, never
        mid-hand -- a shoe that reshuffles halfway through would deal the same
        card twice."""
        return self.remaining <= self.full_size * (1.0 - self.penetration)

    def shuffle(self) -> None:
        self._cards = [Card(rank, suit)
                       for _ in range(self.decks)
                       for suit in SUITS
                       for rank in RANKS]
        self.rng.shuffle(self._cards)
        self.shuffles += 1

    def draw(self) -> Card:
        """Take the next card, reshuffling first if the shoe somehow ran dry.

        The dry case is unreachable at any sane penetration (a hand is at most
        ~11 cards and the cut card leaves at least 5% of a 52-card deck), but a
        renderer that raises IndexError on frame 400 is a worse failure than a
        shoe that quietly reshuffles.
        """
        if not self._cards:
            self.shuffle()
        return self._cards.pop()


# ---------------------------------------------------------------------------
# Basic strategy
# ---------------------------------------------------------------------------

#: Player decisions. Kept as single characters so the tables below stay legible.
HIT, STAND, DOUBLE = "H", "S", "D"

_ACTION_LABELS = {HIT: "HIT", STAND: "STAND", DOUBLE: "DOUBLE"}


def action_label(action: str) -> str:
    return _ACTION_LABELS.get(action, action)


def basic_strategy(cards: Sequence[Card], dealer_up: Card, rules: Rules,
                   can_double: bool) -> str:
    """The basic-strategy play for ``cards`` against ``dealer_up``.

    Multi-deck, dealer peeks, double on any two. Returns HIT, STAND or DOUBLE;
    DOUBLE is only ever returned when ``can_double`` is true, and each
    double-or-X cell names its own fallback rather than defaulting to hit --
    soft 18 against 3-6 stands when it cannot double, which a blanket
    "D becomes H" would get wrong.
    """
    total, soft = hand_total(cards)
    up = upcard_index(dealer_up)

    def double_or(fallback: str) -> str:
        return DOUBLE if (can_double and rules.allow_double) else fallback

    if soft:
        # Soft totals. `total` already counts the ace as 11, so soft 18 is A,7.
        if total >= 20:
            return STAND
        if total == 19:
            # The only soft 19 that is not a flat stand is against a dealer 6
            # in a game where the dealer hits soft 17.
            if rules.hit_soft_17 and up == 6:
                return double_or(STAND)
            return STAND
        if total == 18:
            if up in (2, 3, 4, 5, 6):
                if up == 2 and not rules.hit_soft_17:
                    return STAND
                return double_or(STAND)
            if up in (7, 8):
                return STAND
            return HIT
        if total == 17:
            return double_or(HIT) if up in (3, 4, 5, 6) else HIT
        if total in (15, 16):
            return double_or(HIT) if up in (4, 5, 6) else HIT
        if total in (13, 14):
            return double_or(HIT) if up in (5, 6) else HIT
        return HIT

    # Hard totals.
    if total >= 17:
        return STAND
    if 13 <= total <= 16:
        return STAND if up in (2, 3, 4, 5, 6) else HIT
    if total == 12:
        return STAND if up in (4, 5, 6) else HIT
    if total == 11:
        # Against an ace this is a hit under S17 and a double under H17.
        if up == 11:
            return double_or(HIT) if rules.hit_soft_17 else HIT
        return double_or(HIT)
    if total == 10:
        return double_or(HIT) if up <= 9 else HIT
    if total == 9:
        return double_or(HIT) if up in (3, 4, 5, 6) else HIT
    return HIT


def dealer_should_hit(cards: Sequence[Card], rules: Rules) -> bool:
    """House rule: draw to 16, stand on 17 -- and on *soft* 17 only when the
    table says so."""
    total, soft = hand_total(cards)
    if total < 17:
        return True
    return total == 17 and soft and rules.hit_soft_17


# ---------------------------------------------------------------------------
# The hand script
# ---------------------------------------------------------------------------

#: Event kinds, in the order they can appear.
DEAL = "deal"          #: A card arrives at a seat.
ACTION = "action"      #: The player announces HIT / STAND / DOUBLE.
REVEAL = "reveal"      #: The dealer turns the hole card over.
OUTCOME = "outcome"    #: The result banner.

#: Outcome tones. The renderer maps these to colours.
TONE_BLACKJACK = "blackjack"
TONE_WIN = "win"
TONE_LOSE = "lose"
TONE_PUSH = "push"


@dataclass
class Event:
    """One beat of the hand. Duration is assigned later, by the plugin, from
    config -- the engine has no opinion about pacing."""

    kind: str
    seat: str = ""            # 'player' | 'dealer' | ''
    card: Optional[Card] = None
    face_up: bool = True
    text: str = ""
    tone: str = ""
    subtext: str = ""


@dataclass
class HandScript:
    """Everything that happened in one hand, in order, plus the totals the
    renderer needs up front.

    ``player_cards`` / ``dealer_cards`` are the *final* hands. The renderer
    lays out card slots from these counts so nothing shifts sideways as the
    hand fills in -- positions are fixed from the first frame.
    """

    events: List[Event] = field(default_factory=list)
    player_cards: List[Card] = field(default_factory=list)
    dealer_cards: List[Card] = field(default_factory=list)
    player_total: int = 0
    dealer_total: int = 0
    outcome_text: str = ""
    outcome_tone: str = ""
    doubled: bool = False
    #: A short label for a rare thing that just happened, or "". Purely
    #: decorative -- none of these change what the hand pays.
    flourish: str = ""
    #: Net units won on a one-unit bet: +1.5 blackjack, +1/-1/+2/-2, 0 push.
    payout: float = 0.0

    @property
    def player_card_count(self) -> int:
        return len(self.player_cards)

    @property
    def dealer_card_count(self) -> int:
        return len(self.dealer_cards)


def _flourish(player: Sequence[Card], dealer: Sequence[Card],
              player_total: int, dealer_total: int,
              player_busted: bool, dealer_busted: bool) -> str:
    """A short label for a hand worth pointing at, or "".

    These are the moments a person watching would nudge someone about, and
    without them every hand resolves into one of seven words. None of them
    change the payout -- a five-card Charlie pays as an ordinary win here,
    because paying it would be a house rule this table does not advertise --
    they are there so a rare hand *looks* rare.

    Labels are kept to eight characters: the banner's second line has to fit a
    64px panel at the compact face, where nine characters is already 35 of the
    58 usable pixels.
    """
    if len(player) >= 3 and all(card.rank == "7" for card in player[:3]):
        # Three sevens is the oldest bonus in the game and the only hand here
        # anyone would recognise on sight.
        return "777"
    if not player_busted and len(player) >= 5:
        return "CHARLIE"
    if not player_busted and player_total == 21 and len(player) == 3:
        return "21 IN 3"
    if dealer_busted and len(dealer) >= 5:
        # The count, not a word for it: "D. RUN" was short enough to fit and
        # meant nothing to anyone. The headline already says DEALER BUST, so
        # the useful second line is how far they had to go to get there.
        return f"DEALER {len(dealer)}"
    if is_blackjack(player) and is_blackjack(dealer):
        return "BOTH 21"
    return ""


def _score_line(player_total: int, dealer_total: int) -> str:
    """The small "20-18" line under the banner.

    Busted totals are printed as they are rather than blanked: "24-20" says
    which hand went over and by how much, where an earlier "---20" put three
    dashes next to the separator and read as a single long rule.
    """
    return f"{player_total}-{dealer_total}"


def play_hand(shoe: Shoe, rules: Rules) -> HandScript:
    """Deal, play and resolve one hand, returning its full script.

    The hand is simulated to completion before a single pixel is drawn. That is
    what lets the plugin tell the display controller exactly how long this
    rotation needs (``get_cycle_duration``) and lets every frame be a pure
    function of elapsed time -- no animation state to get out of step.
    """
    script = HandScript()
    events = script.events

    player: List[Card] = []
    dealer: List[Card] = []

    # The casino deal order: player, dealer up, player, dealer hole.
    for seat, face_up in (("player", True), ("dealer", True),
                          ("player", True), ("dealer", False)):
        card = shoe.draw()
        (player if seat == "player" else dealer).append(card)
        events.append(Event(DEAL, seat=seat, card=card, face_up=face_up))

    player_bj = is_blackjack(player)
    # The dealer peeks at the hole card on a ten or an ace, so a dealer natural
    # ends the hand before the player ever acts.
    dealer_bj = is_blackjack(dealer)

    doubled = False
    player_busted = False

    if not player_bj and not dealer_bj:
        while True:
            total, _ = hand_total(player)
            if total >= 21:
                # 21 needs no announcement; busting is impossible here because
                # the loop breaks on the draw that causes it.
                events.append(Event(ACTION, seat="player", text="STAND"))
                break
            can_double = len(player) == 2
            action = basic_strategy(player, dealer[0], rules, can_double)
            events.append(Event(ACTION, seat="player", text=action_label(action)))
            if action == STAND:
                break
            card = shoe.draw()
            player.append(card)
            events.append(Event(DEAL, seat="player", card=card, face_up=True))
            if action == DOUBLE:
                doubled = True
                break
            if hand_total(player)[0] > 21:
                player_busted = True
                break

    script.doubled = doubled
    player_total = hand_total(player)[0]

    # The hole card always turns over -- including when the player busted. It
    # costs the house nothing and it is what a real table does, so the screen
    # never ends on a card the viewer was not shown.
    events.append(Event(REVEAL, seat="dealer"))

    dealer_busted = False
    if not player_bj and not dealer_bj and not player_busted:
        while dealer_should_hit(dealer, rules):
            card = shoe.draw()
            dealer.append(card)
            events.append(Event(DEAL, seat="dealer", card=card, face_up=True))
        dealer_busted = hand_total(dealer)[0] > 21

    dealer_total = hand_total(dealer)[0]

    # Resolve.
    if player_bj and dealer_bj:
        text, tone, payout = "PUSH", TONE_PUSH, 0.0
    elif player_bj:
        text, tone, payout = "BLACKJACK!", TONE_BLACKJACK, 1.5
    elif dealer_bj:
        text, tone, payout = "DEALER 21", TONE_LOSE, -1.0
    elif player_busted:
        text, tone, payout = "BUST!", TONE_LOSE, -1.0
    elif dealer_busted:
        text, tone, payout = "DEALER BUST", TONE_WIN, 1.0
    elif player_total > dealer_total:
        text, tone, payout = "YOU WIN!", TONE_WIN, 1.0
    elif player_total < dealer_total:
        text, tone, payout = "DEALER WINS", TONE_LOSE, -1.0
    else:
        text, tone, payout = "PUSH", TONE_PUSH, 0.0

    if doubled and payout:
        payout *= 2

    events.append(Event(
        OUTCOME,
        text=text,
        tone=tone,
        subtext=_score_line(player_total, dealer_total),
    ))

    script.flourish = _flourish(player, dealer, player_total, dealer_total,
                                player_busted, dealer_busted)
    script.player_cards = player
    script.dealer_cards = dealer
    script.player_total = player_total
    script.dealer_total = dealer_total
    script.outcome_text = text
    script.outcome_tone = tone
    script.payout = payout
    return script
