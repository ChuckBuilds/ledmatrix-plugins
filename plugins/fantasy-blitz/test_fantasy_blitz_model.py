"""Fantasy Blitz rules on recorded data: points, busts, big plays, phases, awards.

Pure logic -- no network, no core. The raw payloads are real Sleeper and
ESPN responses for 2026 week 2 (test/fixtures/raw_payloads.json).
"""

import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import fantasy_blitz_model as model  # noqa: E402
from fantasy_blitz_data import normalize_scoring_plays  # noqa: E402

with open(os.path.join(HERE, "test", "fixtures", "raw_payloads.json"), encoding="utf-8") as fh:
    RAW = json.load(fh)

STATS = model.normalize_sleeper_rows(RAW["sleeper_stats"], "stats")
PROJ = model.normalize_sleeper_rows(RAW["sleeper_projections"], "projections")
WEEK = model.merge_week(STATS, PROJ)
JSN, ALLEN, DART, TAYLOR, CAR, KICKER = "9488", "4984", "12508", "6813", "CAR", "6650"


def player(pid="p1", name="Test Player", pos="WR", team="SEA", pts=10.0, proj=None, **stats):
    first, _, last = name.partition(" ")
    return {"id": pid, "first": first, "last": last, "name": name, "pos": pos, "team": team,
            "opp": "ARI", "pts": {"ppr": pts, "half_ppr": pts, "standard": pts},
            "proj": {"ppr": proj, "half_ppr": proj, "standard": proj} if proj is not None else {},
            "stats": dict({"gp": 1.0}, **stats), "injury": None}


# ----------------------------------------------------------------------
# normalising
# ----------------------------------------------------------------------

def test_points_in_every_format_come_from_sleeper():
    jsn = STATS[JSN]
    assert jsn["name"] == "Jaxon Smith-Njigba"
    assert (jsn["pos"], jsn["team"], jsn["opp"]) == ("WR", "SEA", "ARI")
    assert model.points(jsn, "ppr") == 42.5
    assert model.points(jsn, "half_ppr") == 38.0
    assert model.points(jsn, "standard") == 33.5
    assert jsn["stats"]["rec"] == 9 and jsn["stats"]["rec_td"] == 3


def test_projections_land_under_proj_and_merge():
    assert model.projection(WEEK[JSN], "ppr") == pytest.approx(19.55)
    assert model.points(WEEK[JSN], "ppr") == 42.5
    assert "pts" not in PROJ[JSN]


def test_defence_and_kicker_rows_normalise():
    assert WEEK[CAR]["pos"] == "DEF" and model.display_last(WEEK[CAR]) == "Panthers"
    assert WEEK[KICKER]["pos"] == "K"


def test_unknown_positions_are_dropped():
    rows = [{"player_id": "x", "player": {"position": "OL", "first_name": "A", "last_name": "B"}, "stats": {}}]
    assert model.normalize_sleeper_rows(rows) == {}


def test_has_results():
    assert model.has_results(WEEK)
    assert not model.has_results(PROJ)


# ----------------------------------------------------------------------
# rankings, busts, booms
# ----------------------------------------------------------------------

def test_ranked_is_highest_first_with_stable_ties():
    players = {"a": player("a", "Ann Zed", pts=10), "b": player("b", "Bob Able", pts=10), "c": player("c", "Cy", pts=12)}
    assert [p["id"] for p in model.ranked(players, "ppr", limit=3)] == ["c", "a", "b"]
    assert [p["id"] for p in model.ranked(WEEK, "ppr", limit=2)] == [JSN, ALLEN]


def test_ranked_respects_positions():
    assert all(p["pos"] == "QB" for p in model.ranked(WEEK, "ppr", ("QB",), 5))


def test_dart_is_a_bust_who_left_early():
    busts = model.busts(WEEK, "ppr", 12.0)
    dart = next(b for b in busts if b["player"]["id"] == DART)
    assert dart["proj"] == pytest.approx(18.4, abs=0.05)
    assert dart["pts"] == pytest.approx(0.8)
    assert dart["left_early"], "7 of 58 snaps is leaving early"


def test_busts_wait_for_final_games_and_need_a_projection():
    assert not [b for b in model.busts(WEEK, "ppr", 12.0, final_teams=set()) if b]
    assert model.busts(WEEK, "ppr", 99.0) == []


def test_busts_skip_players_who_did_not_play():
    idle = player("x", "Healthy Scratch", pts=0.0, proj=15.0, gp=0.0)
    assert model.busts({"x": idle}, "ppr", 12.0) == []


def test_booms_rank_by_margin_over_projection():
    top = model.booms(WEEK, "ppr", 1)[0]
    assert top["player"]["id"] == JSN and top["gain"] == pytest.approx(22.95)


def test_kings_has_every_position():
    cells = model.kings(WEEK, "ppr")
    assert [pos for pos, _ in cells] == list(model.POSITIONS)
    assert dict(cells)["WR"]["id"] == JSN


# ----------------------------------------------------------------------
# stat lines and names
# ----------------------------------------------------------------------

def test_receiver_stat_line_and_shorthand():
    assert model.stat_lines(WEEK[JSN])[0] == [("9", "REC"), ("155", "YD"), ("3", "TD")]
    assert model.stat_compact(WEEK[JSN]) == "9-155-3"


def test_quarterback_lines_include_rushing():
    lines = model.stat_lines(WEEK[ALLEN])
    assert lines[0][:2] == [("248", "PASS YD"), ("3", "TD")]
    assert lines[1] == [("69", "RUSH YD"), ("2", "TD")]


def test_kicker_and_defence_lines():
    assert model.stat_lines(WEEK[KICKER])[0][0][1] == "FG"
    labels = [label for line in model.stat_lines(WEEK[CAR]) for _, label in line]
    assert "INT" in labels and "PTS ALLOWED" in labels


def test_display_names():
    assert model.display_initial_last(WEEK[JSN]) == "J. Smith-Njigba"
    assert model.display_initial_last(WEEK[CAR]) == "Panthers"


def test_formatting():
    assert model.fmt_points(40.82) == "40.8" and model.fmt_points(None) == "-"
    assert model.fmt_thousands(483993) == "484K" and model.fmt_thousands(1_260_000) == "1.3M"
    assert model.fmt_count(3.0) == "3"


def test_tiers_and_overrides():
    assert model.tier_for(42.5) == "legendary"
    assert model.tier_for(25) == "epic"
    assert model.tier_for(12) == "rare"
    assert model.tier_for(3) == "common" and model.tier_for(None) == "common"
    assert model.tier_for(25, {"legendary": 24}) == "legendary"


# ----------------------------------------------------------------------
# injuries and watchlist
# ----------------------------------------------------------------------

def test_injury_report_uses_importance_when_projection_is_zero():
    out = player("o", "Out Starter", pts=None, proj=0.0)
    out["injury"] = "Out"
    q = player("q", "Question Mark", pts=None, proj=9.0)
    q["injury"] = "Questionable"
    assert [e["player"]["id"] for e in model.injury_report({"o": out, "q": q}, "ppr")] == ["q"]
    report = model.injury_report({"o": out, "q": q}, "ppr", importance={"o": 18.0})
    assert [(e["player"]["id"], e["tag"]) for e in report] == [("o", "O"), ("q", "Q")]


def test_injury_tags():
    assert model.injury_tag("Questionable") == "Q"
    assert model.injury_tag("IR") == "IR"
    assert model.injury_tag("NA") is None and model.injury_tag(None) is None


def test_watchlist_matching():
    players = {
        "1": player("1", "Josh Allen", "QB", "BUF"), "2": player("2", "Keenan Allen", "WR", "IND"),
        "3": player("3", "Davante Adams", "WR", "LAR"),
    }
    found = model.match_watchlist(["Josh Allen", "Adams", "Allen", "Keenan Allen IND", "Nobody"], players)
    assert found == {"1": "Josh Allen", "3": "Adams", "2": "Keenan Allen IND"}


# ----------------------------------------------------------------------
# phases
# ----------------------------------------------------------------------

@pytest.mark.parametrize("states,weekday,expected", [
    (["pre", "in", "post"], 6, (model.PHASE_LIVE, True)),
    (["pre", "post"], 6, (model.PHASE_INTERMISSION, True)),
    (["post", "post"], 0, (model.PHASE_RECAP, True)),
    (["pre", "pre"], 1, (model.PHASE_RECAP, False)),
    (["pre", "pre"], 3, (model.PHASE_PREGAME, False)),
    ([], 6, (model.PHASE_PREGAME, False)),
])
def test_game_phase(states, weekday, expected):
    games = [{"state": s} for s in states]
    assert model.game_phase("regular", games, weekday) == expected


def test_off_season_is_idle():
    assert model.game_phase("off", [{"state": "in"}], 6)[0] == model.PHASE_IDLE
    assert model.game_phase("post", [], 6)[0] == model.PHASE_IDLE


# ----------------------------------------------------------------------
# big plays
# ----------------------------------------------------------------------

def test_first_look_is_never_an_alert():
    assert model.detect_big_plays(None, WEEK, "ppr", 6.0) == []


def test_big_play_threshold_and_teams():
    before = {JSN: 27.3, ALLEN: 38.0}
    alerts = model.detect_big_plays(before, WEEK, "ppr", 6.0, active_teams={"SEA", "BUF"}, now=100.0)
    assert [a["id"] for a in alerts] == [JSN]
    assert alerts[0]["gain"] == pytest.approx(15.2) and alerts[0]["detected_at"] == 100.0
    assert model.detect_big_plays(before, WEEK, "ppr", 6.0, active_teams={"BUF"}) == []


def test_watchlist_players_alert_at_a_lower_threshold():
    before = dict(model.points_snapshot(WEEK, "ppr"), **{ALLEN: 36.82})
    assert model.detect_big_plays(before, WEEK, "ppr", 6.0) == []
    alerts = model.detect_big_plays(before, WEEK, "ppr", 6.0, watch_ids={ALLEN}, watch_threshold=3.0)
    assert [a["id"] for a in alerts] == [ALLEN] and alerts[0]["watch"]


PLAYS = normalize_scoring_plays(RAW["espn_summary"])


def test_describe_receiving_and_passing_touchdowns():
    assert model.describe_scoring_play(PLAYS, WEEK[JSN]) == ("12-YD TD CATCH", True)
    lock = player("q", "Drew Lock", "QB", "SEA")
    assert model.describe_scoring_play(PLAYS, lock) == ("12-YD TD PASS", True)


def test_describe_run_and_field_goal():
    barner = player("b", "AJ Barner", "TE", "SEA")
    assert model.describe_scoring_play(PLAYS, barner) == ("1-YD TD RUN", True)
    myers = player("k", "Jason Myers", "K", "SEA")
    assert model.describe_scoring_play(PLAYS, myers) == ("33-YD FIELD GOAL", False)


def test_describe_defence_return():
    plays = [{"text": "Jaycee Horn 45 Yd Interception Return (Kicker Kick)", "type": {"text": "Interception Return Touchdown"}, "team": "CAR"}]
    defence = {"id": "CAR", "name": "Carolina Panthers", "pos": "DEF", "team": "CAR"}
    assert model.describe_scoring_play(plays, defence) == ("45-YD PICK SIX", True)


def test_no_scoring_play_means_no_description():
    assert model.describe_scoring_play(PLAYS, player("z", "Nobody Here")) is None


def test_alert_queue_spoiler_delay_gap_and_expiry():
    q = model.AlertQueue(min_gap=60, max_age=900)
    q.add([{"key": "a", "detected_at": 1000.0, "gain": 7}, {"key": "b", "detected_at": 1010.0, "gain": 9}])
    assert q.take(1005.0, delay=30) is None, "held for the spoiler delay"
    first = q.take(1031.0, delay=30)
    assert first["key"] == "a"
    assert q.take(1032.0, delay=30) is first, "stays on screen until finished"
    q.finish()
    assert q.take(1040.0) is None, "one alert a minute"
    assert q.take(1095.0)["key"] == "b"
    q.finish()
    q.add([{"key": "a", "detected_at": 1100.0}])
    assert not q.pending, "a shown alert never repeats"
    q.add([{"key": "c", "detected_at": 1100.0}])
    assert q.take(3000.0) is None, "expired after max_age"


def test_delayed_view():
    view = model.DelayedView(keep_seconds=300)
    view.push(0, "a")
    view.push(60, "b")
    view.push(120, "c")
    assert view.view(130, 0) == "c"
    assert view.view(130, 60) == "b"
    assert view.view(130, 500) == "a"


# ----------------------------------------------------------------------
# awards and trending
# ----------------------------------------------------------------------

def test_weekly_awards():
    awards = {a["key"]: a for a in model.weekly_awards(WEEK, "ppr", 12.0, waiver_ids=[TAYLOR])}
    assert awards["mvp"]["player"]["id"] == JSN
    assert awards["bust"]["player"]["id"] == DART and awards["bust"]["note"] == "LEFT EARLY"
    assert awards["waiver"]["player"]["id"] == TAYLOR
    assert all(a["short"] for a in awards.values())


def test_trending_entries_skip_unknown_players():
    rows = [{"player_id": "nope", "count": 5}, {"player_id": JSN, "count": 3}]
    assert [e["player"]["id"] for e in model.trending_entries(rows, WEEK)] == [JSN]
