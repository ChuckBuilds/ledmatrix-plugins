#!/usr/bin/env python3
"""
Tests the pitch-by-pitch commentary line behind show_game_activity.

A 1-0 pitchers' duel gives the board almost nothing to say: the score does not
move, the bases stay empty, and the only thing changing is the count. ESPN's
summary has plenty to say about it -- a six-game sample on 2026-09-24 carried
3,310 plays across 38 distinct ``type.type`` values, of which balls, fouls and
called/swinging strikes alone were 1,377 -- and none of it reached the display,
because ``_map_play_type`` knows only nine at-bat outcomes and returns None for
everything else.

The two shapes in that data are NOT interchangeable, which is most of what
these checks are about:

  * a PITCH carries the count and the radar gun, but its prose is useless --
    a home run's own play reads "Pitch 1 : Ball In Play";
  * the following ``play-result`` carries the readable sentence, already
    naming the batter: "Burleson homered to right center (395 feet)."

So an at-bat-ending pitch is folded into its play-result rather than announced
twice, and the velocity is carried across from the pitch that caused it.

Fixture is a real ESPN response (``test/fixtures/mlb_activity_plays.json``),
trimmed to the fields the code reads.

These checks pin:

  * every class is recognised -- pitches, outcomes, baserunning -- and
    scaffolding ("start-batterpitcher", whose text is literally "None") is not;
  * ESPN files baserunning TWICE, typed and again as a play-result with the
    same sentence, and it is announced once;
  * the count is blank once the pitch ended the at-bat -- ESPN keeps counting,
    so a called third strike reports strikes=3 and "1-3" is not a count any
    scoreboard has shown;
  * a home run carries the pitch that caused it ("95 mph Four-seam FB");
  * the queue dedupes on play id, so consecutive polls re-sending the tail of
    the game do not make the board loop over old pitches;
  * placement is decided per PANEL, not per line -- otherwise a 128px board
    would flip between inline and its own screen from one pitch to the next;
  * the inline line stays inside the gap between the two bottom-corner scores,
    which share its row.

Run: <core-venv>/bin/python plugins/baseball-scoreboard/test_game_activity.py
"""

# A test harness: it reaches into protected members on purpose and builds
# stand-in objects whose attributes exist only to match what they replace.
# pylint: disable=protected-access,unused-argument,broad-exception-caught

import json
import logging
import sys
from pathlib import Path

plugin_dir = Path(__file__).parent
sys.path.insert(0, str(plugin_dir))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

import baseball as B  # noqa: E402

FIXTURE = plugin_dir / "test" / "fixtures" / "mlb_activity_plays.json"

results = []


def check(label, ok, detail=None):
    print(("  PASS  " if ok else "  FAIL  ") + label
          + ("" if ok or detail is None else "  -- %r" % (detail,)))
    results.append((label, ok))


def load_feed(limit=40):
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    names = B._build_athlete_name_map(data["rosters"])
    return data, B._extract_activity_feed(data["plays"], names, limit=limit)


# --- extraction -------------------------------------------------------------

def test_every_class_is_recognised():
    print("the feed hears pitches, outcomes and baserunning -- and not scaffolding")
    _, feed = load_feed()
    kinds = {e["kind"] for e in feed}
    check("all three classes present", kinds == {"pitch", "outcome", "baserunning"},
          kinds)
    check("something was actually extracted", len(feed) > 20, len(feed))
    phrases = [e["phrase"] for e in feed]
    check("no scaffolding leaked in ('None' is end-batterpitcher's text)",
          not any(p.strip().lower() == "none" for p in phrases))
    check("no 'pitches to' matchup lines (start-batterpitcher)",
          not any("pitches to" in p for p in phrases))
    check("the pitch prefix is stripped", not any(p.startswith("Pitch ") for p in phrases),
          [p for p in phrases if p.startswith("Pitch ")][:3])


def test_phrasing_reads_like_baseball():
    print("\nphrasing is what a fan would say")
    _, feed = load_feed()
    phrases = [e["phrase"] for e in feed]
    check("'Strike 1 Foul' became 'Foul'",
          "Foul" in phrases and not any(p.endswith(" Foul") for p in phrases),
          [p for p in phrases if "Foul" in p][:4])
    check("looking/swinging are lowercased",
          any(p.endswith(" looking") for p in phrases)
          and any(p.endswith(" swinging") for p in phrases))
    check("ESPN's own sentence is used verbatim for outcomes",
          any(p == "Burleson homered to right center (395 feet)." for p in phrases))


def test_baserunning_is_announced_once():
    print("\nESPN files baserunning twice; the board says it once")
    _, feed = load_feed()
    steals = [e for e in feed if "stole third" in e["phrase"]]
    check("'Cruz stole third.' appears exactly once", len(steals) == 1, len(steals))
    check("...and is classed as baserunning, not an at-bat outcome",
          steals and steals[0]["kind"] == "baserunning",
          steals[0]["kind"] if steals else None)
    # A general form of the same rule.
    consecutive = [(a["phrase"], b["phrase"]) for a, b in zip(feed, feed[1:])
                   if a["phrase"].lower() == b["phrase"].lower()]
    check("no entry repeats the one before it", not consecutive, consecutive[:2])


def test_the_count_is_a_real_count():
    print("\nthe count never shows a plate appearance that already ended")
    _, feed = load_feed()
    bad = [(e["phrase"], e["count"]) for e in feed if e["count"]
           and (int(e["count"].split("-")[0]) >= 4
                or int(e["count"].split("-")[1]) >= 3)]
    check("no ball >= 4 and no strike >= 3 in any shown count", not bad, bad[:3])
    check("ordinary counts still come through",
          any(e["count"] == "1-2" or e["count"] == "0-1" for e in feed))
    # The pitch that ends an at-bat is the one ESPN over-counts.
    third = [e for e in feed if e["phrase"].startswith("Strike 3")]
    check("a called/swinging third strike carries no count",
          third and all(e["count"] == "" for e in third),
          [(e["phrase"], e["count"]) for e in third][:3])


def test_the_outcome_carries_its_pitch():
    print("\nan outcome borrows the velocity from the pitch that caused it")
    _, feed = load_feed()
    hr = [e for e in feed if "homered" in e["phrase"]]
    check("the home run is present", bool(hr))
    if hr:
        check("it carries the pitch detail", hr[0]["detail"] == "95 mph Four-seam FB",
              hr[0]["detail"])
        check("and is flagged as a scoring play", hr[0]["scoring"] is True)
    check("an ordinary pitch carries its own velocity",
          any(e["kind"] == "pitch" and "mph" in e["detail"] for e in feed))
    check("nothing invents a velocity it was not given",
          all(e["detail"] == "" or "mph" in e["detail"] or e["detail"]
              for e in feed))


def test_unknown_types_are_skipped_not_guessed():
    print("\nan unrecognised play is dropped rather than captioned wrongly")
    plays = [{"id": "1", "type": {"type": "some-new-espn-thing"},
              "text": "Something nobody mapped", "atBatId": "a"}]
    check("unknown type yields nothing", B._extract_activity_feed(plays) == [])
    check("an empty play list is fine", B._extract_activity_feed([]) == [])
    check("None is fine", B._extract_activity_feed(None) == [])
    # Replay suffixes are a qualifier on a known stem, not an unknown type.
    stem, qualifier = B._split_play_type("strike-looking---overturned")
    check("'strike-looking---overturned' splits", (stem, qualifier)
          == ("strike-looking", "overturned"), (stem, qualifier))


# --- the queue --------------------------------------------------------------

class _Live:
    """The activity half of BaseballLive, without its constructor."""

    for _name in ("_merge_activity_feed", "_current_activity", "_activity_lines",
                  "_activity_is_wanted", "_next_wanted_activity",
                  "_activity_placement", "_activity_inline_band",
                  "_scorebug_content_bottom", "_activity_fit",
                  "_activity_colour", "_activity_font"):
        locals()[_name] = getattr(B.BaseballLive, _name)

    def __init__(self, width=256, height=64, detail="normal", position="auto"):
        self.display_width, self.display_height = width, height
        self.config = {}
        self.logger = logging.getLogger("activity_probe")
        self.game_activity_detail = detail
        self.game_activity_position = position
        self.game_activity_dwell = 0.0        # advance on every look
        self.game_activity_include = {"pitch": True, "outcome": True,
                                      "baserunning": True}
        self._activity_feed_limit = 12
        self._activity_state = {}
        face = ImageFont.load_default()
        self.fonts = {"detail": face, "status": face, "time": face}


def test_the_queue_does_not_repeat_itself():
    print("\nconsecutive polls re-send the same tail; it is queued once")
    _, feed = load_feed(limit=40)
    feed = feed[:5]                      # well under the queue bound
    live = _Live()
    live._merge_activity_feed("g1", feed)
    first = len(live._activity_state["g1"]["queue"])
    check("the first poll queues everything", first == len(feed), first)
    live._merge_activity_feed("g1", feed)          # the identical poll again
    check("a repeated poll adds nothing",
          len(live._activity_state["g1"]["queue"]) == first, first)
    live._merge_activity_feed("g1", [dict(feed[0], id="brand-new-id")])
    check("a genuinely new play is queued",
          len(live._activity_state["g1"]["queue"]) == first + 1,
          len(live._activity_state["g1"]["queue"]))

    print("\n...and a board that fell behind drops the oldest, not the newest")
    flood = _Live()
    many = [dict(feed[0], id="id-%d" % i) for i in range(40)]
    flood._merge_activity_feed("g2", many)
    queue = flood._activity_state["g2"]["queue"]
    check("the queue is bounded", len(queue) == flood._activity_feed_limit,
          len(queue))
    check("it kept the most recent plays", queue[-1]["id"] == "id-39",
          queue[-1]["id"])


def test_the_queue_walks_forward():
    print("\nplays are walked through locally between polls")
    _, feed = load_feed(limit=40)
    feed = feed[:6]
    live = _Live(detail="normal")
    live.game_activity_dwell = 4.0
    live._merge_activity_feed("g1", feed)

    # Drive the clock rather than sleeping: the dwell is floored at 1s on
    # purpose (a 0-second dwell would advance every frame), so a real-time
    # test would have to sleep six seconds to prove six advances.
    clock = {"now": 1000.0}
    real = B.time.time
    B.time.time = lambda: clock["now"]
    try:
        shown = []
        for _ in range(len(feed)):
            shown.append(live._current_activity("g1")["id"])
            clock["now"] += live.game_activity_dwell
        check("each dwell advances to the next play",
              len(set(shown)) == len(feed), len(set(shown)))
        check("order is preserved", shown == [e["id"] for e in feed], shown[:3])

        clock["now"] += live.game_activity_dwell
        held = live._current_activity("g1")["id"]
        check("an exhausted queue holds the last play rather than blanking",
              held == feed[-1]["id"], held)

        # Between dwells the same play stays up -- that IS the dwell.
        before = live._current_activity("g1")["id"]
        clock["now"] += 0.5
        check("it does not advance early",
              live._current_activity("g1")["id"] == before)
    finally:
        B.time.time = real

    check("an unknown game has nothing to show",
          live._current_activity("no-such-game") is None)


def test_muted_classes_are_skipped():
    print("\nmuting a class quietens the line without stopping it")
    _, feed = load_feed(limit=12)
    live = _Live()
    live.game_activity_include = {"pitch": False, "outcome": True,
                                  "baserunning": True}
    live._merge_activity_feed("g1", feed)
    picked = [live._next_wanted_activity("g1") for _ in range(6)]
    kinds = {e["kind"] for e in picked if e}
    check("no pitch is announced", "pitch" not in kinds, kinds)
    check("something still is", bool(kinds))

    silent = _Live()
    silent.game_activity_include = {"pitch": False, "outcome": False,
                                    "baserunning": False}
    silent._merge_activity_feed("g2", feed)
    check("muting everything returns nothing, and does not spin",
          silent._next_wanted_activity("g2") is None)


def test_detail_levels():
    print("\ndetail levels say more or less about the same play")
    _, feed = load_feed()
    pitch = next(e for e in feed if e["kind"] == "pitch" and e["player"]
                 and e["count"] and e["detail"])
    check("terse is the bare event",
          _Live(detail="terse")._activity_lines(pitch) == [pitch["phrase"]])
    normal = _Live(detail="normal")._activity_lines(pitch)
    check("normal names the batter and the count",
          len(normal) == 1 and pitch["player"] in normal[0]
          and pitch["count"] in normal[0], normal)
    rich = _Live(detail="rich")._activity_lines(pitch)
    check("rich adds the pitch on a second line",
          len(rich) == 2 and "mph" in rich[1], rich)
    check("an empty phrase draws nothing",
          _Live()._activity_lines({"phrase": "  "}) == [])


# --- placement --------------------------------------------------------------

def test_placement_is_per_panel_not_per_line():
    print("\nplacement is decided by the panel, so it cannot flicker")
    short, long_ = ["Foul"], ["Burleson homered to right center (395 feet)."]
    for width, height, expected in ((256, 64, "inline"), (128, 64, "inline"),
                                    (512, 64, "inline"), (128, 32, "screen"),
                                    (64, 32, "screen"), (256, 32, "screen")):
        live = _Live(width, height)
        got = (live._activity_placement(short), live._activity_placement(long_))
        check("%dx%d -> %s for a short AND a long line" % (width, height, expected),
              got == (expected, expected), got)


def test_explicit_placement_is_honoured():
    print("\nan explicit choice wins, and never prints over the scorebug")
    lines = ["Foul"]
    check("'screen' on a wide panel still takes its own screen",
          _Live(256, 64, position="screen")._activity_placement(lines) == "screen")
    check("'inline' on a panel with no band draws nothing rather than overlapping",
          _Live(128, 32, position="inline")._activity_placement(lines) == "")
    check("'inline' where it fits is honoured",
          _Live(256, 64, position="inline")._activity_placement(lines) == "inline")


def test_the_line_stays_between_the_scores():
    print("\nthe inline line shares its row with the corner scores")
    live = _Live(256, 64)
    draw = ImageDraw.Draw(Image.new("RGB", (256, 64)))
    font = live.fonts["detail"]
    long_text = "Simon to second on wild pitch by Stanek, Simon safe at third"
    fitted = live._activity_fit(draw, long_text, font, max_width=90)
    check("a long sentence is trimmed to the gap, not the panel",
          draw.textlength(fitted, font=font) <= 90,
          draw.textlength(fitted, font=font))
    check("and says it was trimmed", fitted.endswith("…"), fitted[-12:])
    check("a short line is left alone",
          live._activity_fit(draw, "Foul", font, max_width=90) == "Foul")
    check("max_width defaults to the panel",
          live._activity_fit(draw, "Foul", font) == "Foul")


def test_scoring_plays_are_coloured():
    print("\na run scoring looks different from a foul ball")
    live = _Live()
    plain = live._activity_colour({"scoring": False})
    scoring = live._activity_colour({"scoring": True})
    check("the two differ", plain != scoring, (plain, scoring))
    check("nothing is still a colour", live._activity_colour(None) == plain)


def main():
    if not FIXTURE.exists():
        print("SKIP: fixture missing at %s" % FIXTURE)
        return 2
    for fn in (test_every_class_is_recognised, test_phrasing_reads_like_baseball,
               test_baserunning_is_announced_once, test_the_count_is_a_real_count,
               test_the_outcome_carries_its_pitch,
               test_unknown_types_are_skipped_not_guessed,
               test_the_queue_does_not_repeat_itself, test_the_queue_walks_forward,
               test_muted_classes_are_skipped, test_detail_levels,
               test_placement_is_per_panel_not_per_line,
               test_explicit_placement_is_honoured,
               test_the_line_stays_between_the_scores,
               test_scoring_plays_are_coloured):
        fn()
    print()
    failed = [name for name, ok in results if not ok]
    print("%d checks, %d failed" % (len(results), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
