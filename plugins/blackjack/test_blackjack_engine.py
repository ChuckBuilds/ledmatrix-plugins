#!/usr/bin/env python3
"""Engine tests for the blackjack plugin: shoe, totals, strategy, resolution.

Standalone script, per this repo's convention:
    0 pass, 2 skip (prerequisites absent), 1 fail.

    python plugins/blackjack/test_blackjack_engine.py
"""

from __future__ import annotations

import os
import random
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from blackjack_engine import (  # noqa: E402
    ACTION,
    DEAL,
    DOUBLE,
    HIT,
    OUTCOME,
    REVEAL,
    STAND,
    Card,
    Rules,
    Shoe,
    basic_strategy,
    dealer_should_hit,
    hand_total,
    is_blackjack,
    play_hand,
    upcard_index,
)

FAILURES = []


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        FAILURES.append(label)


def cards(*specs):
    """``cards("AS", "10H")`` -> two Card objects."""
    out = []
    for spec in specs:
        out.append(Card(spec[:-1], spec[-1]))
    return out


# ---------------------------------------------------------------------------


def test_totals():
    check("hard total", hand_total(cards("7S", "9D")) == (16, False))
    check("ace counts high when it fits", hand_total(cards("AS", "6D")) == (17, True))
    check("ace drops to 1 when 11 would bust",
          hand_total(cards("AS", "6D", "9C")) == (16, False))
    check("two aces never both count high",
          hand_total(cards("AS", "AD")) == (12, True))
    check("three aces plus a nine is soft 21",
          hand_total(cards("AS", "AD", "AC", "8H")) == (21, True))
    check("face cards are ten", hand_total(cards("KS", "QD")) == (20, False))
    check("natural is two cards", is_blackjack(cards("AS", "KD")))
    check("three cards to 21 is not a natural",
          not is_blackjack(cards("7S", "7D", "7C")))
    check("upcard index folds tens together",
          [upcard_index(c) for c in cards("KS", "10D", "AC", "4H")] == [10, 10, 11, 4])


def test_shoe():
    shoe = Shoe(decks=2, rng=random.Random(1))
    check("shoe holds decks x 52", shoe.remaining == 104, str(shoe.remaining))
    drawn = [shoe.draw() for _ in range(104)]
    counts = Counter((card.rank, card.suit) for card in drawn)
    check("every card appears exactly twice in a two-deck shoe",
          set(counts.values()) == {2} and len(counts) == 52)
    check("drawing empties the shoe", shoe.remaining == 0)
    check("drawing past empty reshuffles rather than raising",
          shoe.draw() is not None and shoe.remaining == 103)

    shoe = Shoe(decks=6, rng=random.Random(2), penetration=0.75)
    check("full shoe is not due a shuffle", not shoe.needs_shuffle)
    for _ in range(int(312 * 0.75) + 1):
        shoe.draw()
    check("cut card triggers a shuffle", shoe.needs_shuffle)

    # The default RNG must not be the module-global one, or seeding `random`
    # anywhere in the process would make every hand predictable.
    random.seed(42)
    first = [str(c) for c in (Shoe(decks=1).draw() for _ in range(5))]
    random.seed(42)
    second = [str(c) for c in (Shoe(decks=1).draw() for _ in range(5))]
    check("unseeded shoes ignore random.seed()", first != second,
          f"{first} == {second}")

    check("deck count is clamped to a sane range",
          Shoe(decks=99).decks == 8 and Shoe(decks=0).decks == 1)


def test_strategy_hard():
    rules = Rules()
    up = lambda rank: cards(rank + "S")[0]  # noqa: E731

    check("hard 8 always hits",
          all(basic_strategy(cards("5D", "3C"), up(r), rules, True) == HIT
              for r in ("2", "7", "10", "A")))
    check("hard 9 doubles against 3-6",
          [basic_strategy(cards("5D", "4C"), up(r), rules, True)
           for r in ("2", "3", "6", "7")] == [HIT, DOUBLE, DOUBLE, HIT])
    check("hard 10 doubles against 2-9, hits 10 and ace",
          [basic_strategy(cards("6D", "4C"), up(r), rules, True)
           for r in ("2", "9", "10", "A")] == [DOUBLE, DOUBLE, HIT, HIT])
    check("hard 11 doubles against everything but the ace under S17",
          [basic_strategy(cards("6D", "5C"), up(r), rules, True)
           for r in ("2", "10", "A")] == [DOUBLE, DOUBLE, HIT])
    check("hard 11 doubles against an ace under H17",
          basic_strategy(cards("6D", "5C"), up("A"), Rules(hit_soft_17=True), True) == DOUBLE)
    check("hard 12 stands only against 4-6",
          [basic_strategy(cards("10D", "2C"), up(r), rules, True)
           for r in ("2", "3", "4", "6", "7")] == [HIT, HIT, STAND, STAND, HIT])
    check("hard 16 stands against a small card, hits a big one",
          [basic_strategy(cards("10D", "6C"), up(r), rules, True)
           for r in ("2", "6", "7", "10", "A")] == [STAND, STAND, HIT, HIT, HIT])
    check("hard 17 always stands",
          all(basic_strategy(cards("10D", "7C"), up(r), rules, True) == STAND
              for r in ("2", "6", "10", "A")))
    check("a pair is played by its total, not split",
          basic_strategy(cards("8D", "8C"), up("6"), rules, True) == STAND)


def test_strategy_soft():
    rules = Rules()
    h17 = Rules(hit_soft_17=True)
    up = lambda rank: cards(rank + "S")[0]  # noqa: E731

    check("soft 13 doubles against 5-6 only",
          [basic_strategy(cards("AD", "2C"), up(r), rules, True)
           for r in ("4", "5", "6", "7")] == [HIT, DOUBLE, DOUBLE, HIT])
    check("soft 15 doubles against 4-6",
          [basic_strategy(cards("AD", "4C"), up(r), rules, True)
           for r in ("3", "4", "6", "7")] == [HIT, DOUBLE, DOUBLE, HIT])
    check("soft 17 doubles against 3-6",
          [basic_strategy(cards("AD", "6C"), up(r), rules, True)
           for r in ("2", "3", "6", "7")] == [HIT, DOUBLE, DOUBLE, HIT])
    check("soft 18 stands on 2 under S17 and doubles on 2 under H17",
          basic_strategy(cards("AD", "7C"), up("2"), rules, True) == STAND
          and basic_strategy(cards("AD", "7C"), up("2"), h17, True) == DOUBLE)
    check("soft 18 hits against 9, 10 and ace",
          [basic_strategy(cards("AD", "7C"), up(r), rules, True)
           for r in ("9", "10", "A")] == [HIT, HIT, HIT])
    check("soft 19 stands, and doubles on 6 only under H17",
          basic_strategy(cards("AD", "8C"), up("6"), rules, True) == STAND
          and basic_strategy(cards("AD", "8C"), up("6"), h17, True) == DOUBLE)
    check("soft 20 always stands",
          all(basic_strategy(cards("AD", "9C"), up(r), rules, True) == STAND
              for r in ("2", "6", "10", "A")))


def test_strategy_without_double():
    """Each double cell has to name its own fallback. A blanket "D becomes H"
    hits soft 18 against a 4, which is a real strategy error, not a rounding."""
    rules = Rules()
    up = lambda rank: cards(rank + "S")[0]  # noqa: E731
    check("soft 18 stands when it cannot double",
          basic_strategy(cards("AD", "7C"), up("4"), rules, False) == STAND)
    check("hard 11 hits when it cannot double",
          basic_strategy(cards("6D", "5C"), up("6"), rules, False) == HIT)
    check("soft 17 hits when it cannot double",
          basic_strategy(cards("AD", "6C"), up("5"), rules, False) == HIT)
    check("doubling off in the rules is the same as being unable to",
          basic_strategy(cards("6D", "5C"), up("6"), Rules(allow_double=False), True) == HIT)
    check("double is never offered on a third card",
          basic_strategy(cards("2D", "4C", "5H"), up("6"), rules, False) in (HIT, STAND))


def test_dealer():
    rules = Rules()
    h17 = Rules(hit_soft_17=True)
    check("dealer draws to 16", dealer_should_hit(cards("10D", "6C"), rules))
    check("dealer stands on hard 17", not dealer_should_hit(cards("10D", "7C"), rules))
    check("dealer stands on soft 17 under S17",
          not dealer_should_hit(cards("AD", "6C"), rules))
    check("dealer hits soft 17 under H17", dealer_should_hit(cards("AD", "6C"), h17))
    check("dealer stands on soft 18 either way",
          not dealer_should_hit(cards("AD", "7C"), rules)
          and not dealer_should_hit(cards("AD", "7C"), h17))


def test_hand_script():
    """A long run of real hands, checked for the invariants that keep the
    renderer honest: the script must describe a hand that could have happened."""
    rules = Rules()
    shoe = Shoe(6, random.Random(99))
    outcomes = Counter()
    for index in range(4000):
        script = play_hand(shoe, rules)
        outcomes[script.outcome_text] += 1

        kinds = [event.kind for event in script.events]
        if kinds[:4] != [DEAL] * 4:
            check(f"hand {index} opens with four cards", False, str(kinds[:4]))
            return
        if kinds.count(REVEAL) != 1:
            check(f"hand {index} turns the hole card exactly once", False, str(kinds))
            return
        if kinds[-1] != OUTCOME or kinds.count(OUTCOME) != 1:
            check(f"hand {index} ends on exactly one result", False, str(kinds))
            return
        if kinds.index(REVEAL) < 4:
            check(f"hand {index} deals before it reveals", False, str(kinds))
            return

        dealt = [event for event in script.events if event.kind == DEAL]
        if len(dealt) != script.player_card_count + script.dealer_card_count:
            check(f"hand {index} deals every card it ends with", False,
                  f"{len(dealt)} dealt, {script.player_card_count}+{script.dealer_card_count} held")
            return
        if [event.face_up for event in dealt[:4]] != [True, True, True, False]:
            check(f"hand {index} keeps the hole card down", False, str(dealt[:4]))
            return
        if script.player_total != hand_total(script.player_cards)[0]:
            check(f"hand {index} reports the player's real total", False, "")
            return

        player_busted = script.player_total > 21
        if player_busted and len(script.dealer_cards) != 2:
            check(f"hand {index} does not draw for the dealer after a bust", False, "")
            return
        if not player_busted and not is_blackjack(script.player_cards) \
                and not is_blackjack(script.dealer_cards):
            if dealer_should_hit(script.dealer_cards, rules):
                check(f"hand {index} plays the dealer out to a standing total",
                      False, str(script.dealer_total))
                return
        # Actions and the cards they cause must alternate: every HIT or DOUBLE
        # is followed by a card, and STAND ends the player's turn.
        for position, event in enumerate(script.events):
            if event.kind != ACTION:
                continue
            following = script.events[position + 1]
            if event.text == "STAND" and following.kind != REVEAL:
                check(f"hand {index} stops on STAND", False, str(following.kind))
                return
            if event.text in ("HIT", "DOUBLE") and (
                    following.kind != DEAL or following.seat != "player"):
                check(f"hand {index} deals a card after {event.text}", False, "")
                return

    check("4000 hands all well-formed", True)
    check("every outcome occurs in 4000 hands",
          set(outcomes) == {"BLACKJACK!", "YOU WIN!", "DEALER BUST", "BUST!",
                            "DEALER WINS", "PUSH", "DEALER 21"},
          str(sorted(outcomes)))
    # Basic strategy against a 6-deck S17 game runs about half a percent against
    # the player. A band this wide only catches a table that is grossly wrong --
    # a strategy inversion, or a dealer that never busts -- which is the point.
    edge = sum(count * _payout(text) for text, count in outcomes.items()) / 4000.0
    check("house edge is in the right neighbourhood", -0.08 < edge < 0.02,
          f"{edge:+.3f} units/hand")
    print(f"        outcomes over 4000 hands: {dict(outcomes)}")
    print(f"        result: {edge:+.3f} units per hand")


def _payout(text):
    return {"BLACKJACK!": 1.5, "YOU WIN!": 1.0, "DEALER BUST": 1.0,
            "BUST!": -1.0, "DEALER WINS": -1.0, "DEALER 21": -1.0, "PUSH": 0.0}[text]


def test_flourishes():
    """The rare-hand labels. They pay nothing, so the only thing that can be
    wrong about them is *when* they fire."""
    from blackjack_engine import _flourish

    def f(player, dealer, pt, dt, pb=False, db=False):
        return _flourish(cards(*player), cards(*dealer), pt, dt, pb, db)

    check("three sevens outranks everything",
          f(("7S", "7D", "7C"), ("KS", "9D"), 21, 19) == "777")
    check("five cards without busting is a Charlie",
          f(("2S", "3D", "4C", "5H", "5S"), ("KS", "9D"), 19, 19) == "CHARLIE")
    check("a busted five-card hand is not a Charlie",
          f(("2S", "3D", "4C", "5H", "KS"), ("KS", "9D"), 24, 19, pb=True) == "")
    check("21 on the third card is called",
          f(("7S", "4D", "KC"), ("KS", "9D"), 21, 19) == "21 IN 3")
    check("a two-card 21 is a natural, not a 21-in-3",
          f(("AS", "KD"), ("KS", "9D"), 21, 19) == "")
    check("a long dealer bust is called, with the count",
          f(("KS", "9D"), ("2S", "3D", "4C", "5H", "KS"), 19, 24, db=True) == "DEALER 5")
    check("the dealer count is the real one",
          f(("KS", "9D"), ("2S", "2D", "3C", "4H", "4S", "KS"), 19, 25, db=True) == "DEALER 6")
    check("two naturals is called",
          f(("AS", "KD"), ("AH", "QC"), 21, 21) == "BOTH 21")
    check("an ordinary hand gets nothing",
          f(("KS", "9D"), ("KH", "8C"), 19, 18) == "")

    # Every label has to fit the banner's second line on a 64px panel at the
    # compact face, which is 58 usable pixels.
    shoe = Shoe(6, random.Random(4))
    seen = set()
    for _ in range(20000):
        script = play_hand(shoe, rules := Rules())
        if script.flourish:
            seen.add(script.flourish)
    over = [label for label in seen if len(label) > 8]
    check("every label fits the banner's second line", not over, str(over))
    check("the rare labels all occur in 20000 hands",
          seen >= {"777", "CHARLIE", "21 IN 3", "DEALER 5", "BOTH 21"}, str(sorted(seen)))
    print(f"        labels seen: {sorted(seen)}")


def test_determinism():
    def deal(seed):
        shoe = Shoe(6, random.Random(seed))
        return [str(card) for _ in range(5)
                for card in play_hand(shoe, Rules()).player_cards]

    check("a seeded shoe repeats exactly", deal(7) == deal(7))
    check("different seeds deal differently", deal(7) != deal(8))


def main():
    for test in (test_totals, test_shoe, test_strategy_hard, test_strategy_soft,
                 test_strategy_without_double, test_dealer, test_hand_script,
                 test_flourishes, test_determinism):
        print(test.__name__)
        test()
    if FAILURES:
        print(f"\n{len(FAILURES)} failure(s): " + ", ".join(FAILURES))
        return 1
    print("\nall engine checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
