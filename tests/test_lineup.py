import math

import pytest

from pipeline import lineup

SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX", "K", "DEF", "BN", "BN"]
CFG = {"favored": 0.65, "underdog": 0.35, "lean": 0.5, "close_call": 1.5}
NOW = "2026-10-11T16:00:00Z"   # Sunday, before the 1 PM Eastern games
SUNDAY = "2026-10-11T17:00Z"


def player(pid, pos, score, roster=1, team=None, floor=None, ceiling=None, sd=None, **kw):
    p = {"id": pid, "name": f"P{pid}", "pos": pos, "team": team or f"T{pid}", "opp": "OPP",
         "score": score, "roster": roster, "rank": 1, "adj": [], "flag": "", "injury": "",
         "injury_detail": "",
         "range": {"floor": score * 0.6 if floor is None else floor,
                   "ceiling": score * 1.6 if ceiling is None else ceiling,
                   "sd": score * 0.5 if sd is None else sd, "games": 8}}
    p.update(kw)
    return p


def game(state="pre", kickoff=SUNDAY, period=0, clock=0.0, status=None):
    return {"state": state, "kickoff": kickoff, "period": period, "clock": clock,
            "completed": state == "post",
            "status": status or {"pre": "STATUS_SCHEDULED", "in": "STATUS_IN_PROGRESS",
                                 "post": "STATUS_FINAL"}[state]}


def run(players, starters, opp_starters=None, games=None, points=None, opp_points=None,
        reserve=None, now=NOW, cfg=CFG, market=None):
    positions = {}
    for p in players:
        positions.setdefault(p["pos"], {"players": [], "breaks": []})["players"].append(p)
    lineups = {1: {"starters": starters, "points": points or {}}}
    if opp_starters is not None:
        lineups[2] = {"starters": opp_starters, "points": opp_points or {}}
    ctx = {"my_rid": 1, "opp_rid": 2 if opp_starters is not None else None,
           "lineups": lineups, "reserve": {1: reserve or []}}
    games = games if games is not None else {p["team"]: game() for p in players}
    return lineup.build(positions, ctx, SLOTS, games, cfg, now, market=market)


def roster():
    """A full roster plus bench, all with games at 1 PM Sunday."""
    return [
        player("qb1", "QB", 20), player("qb2", "QB", 15),
        player("rb1", "RB", 14), player("rb2", "RB", 12), player("rb3", "RB", 9), player("rb4", "RB", 5),
        player("wr1", "WR", 15), player("wr2", "WR", 13), player("wr3", "WR", 10), player("wr4", "WR", 6),
        player("te1", "TE", 11), player("te2", "TE", 7),
        player("k1", "K", 8), player("def1", "DEF", 7),
    ]


BEST = ["qb1", "rb1", "rb2", "wr1", "wr2", "te1", "wr3", "rb3", "k1", "def1"]


def ids(result, side="me"):
    return [e["id"] for e in result[side]["starters"]]


# ---------- game phase ----------

def test_phase_before_during_after():
    now = lineup._time(NOW)
    assert lineup.phase({}, game(), now) == ("pre", 1.0)
    assert lineup.phase({}, game("post"), now) == ("final", 0.0)
    # 3rd quarter, 7:30 left: one quarter plus half a quarter = 37.5% of the game
    assert lineup.phase({}, game("in", period=3, clock=450), now) == ("live", 0.375)
    assert lineup.phase({}, game("in", period=2, clock=0), now) == ("live", 0.5)  # halftime
    assert lineup.phase({}, game("in", period=5, clock=300), now) == ("live", 0.0)  # overtime


def test_kickoff_passed_counts_as_started():
    later = lineup._time("2026-10-11T17:05:00Z")
    assert lineup.phase({}, game(), later) == ("live", 1.0)


def test_no_game_data_trusts_projection_opponent():
    now = lineup._time(NOW)
    assert lineup.phase({"opp": "GB"}, None, now) == ("pre", 1.0)
    assert lineup.phase({"opp": ""}, None, now) == ("none", 0.0)
    assert lineup.phase({}, game(status="STATUS_POSTPONED"), now) == ("none", 0.0)


# ---------- one player's spread ----------

def test_doubtful_range_is_a_mix_of_playing_and_zero():
    # Healthy 10, Doubtful takes 6 off: plays 40% of the time, else 0
    p = player("d", "WR", 4.0, floor=6, ceiling=16, sd=5,
               adj=[{"key": "injury", "pts": -6.0}], flag="Doubtful")
    p["range"]["if_plays"] = True
    floor, ceiling, sd = lineup.outcome(p)
    assert floor == 0.0                              # a 60% chance of 0 is below the 25th percentile
    # 90th percentile of the mix = 75th of his if-he-plays range
    assert ceiling == pytest.approx(10 + 6 * 0.6745 / 1.2816, abs=0.01)
    assert sd == pytest.approx(math.sqrt(0.4 * 25 + 0.4 * 0.6 * 100))


def test_favored_mode_does_not_call_a_doubtful_player_safe():
    players = roster()
    players[11].update(score=9.5, flag="Doubtful", injury="Doubtful",
                       adj=[{"key": "injury", "pts": -14.25, "label": "Doubtful", "why": ""}])
    players[11]["range"] = {"floor": 18, "ceiling": 30, "sd": 6, "games": 8, "if_plays": True}
    weak = [player("o1", "K", 5, roster=2)]
    r = run(players + weak, BEST, opp_starters=["0"] * 8 + ["o1", "0"])
    assert r["mode"] == "favored" and "te2" not in ids(r)


def test_out_player_has_no_spread():
    p = player("o", "WR", 0.0, floor=6, ceiling=16, sd=5,
               adj=[{"key": "injury", "pts": -10.0}], flag="Out")
    p["range"]["if_plays"] = True
    assert lineup.outcome(p)[2] == 0.0


# ---------- win % ----------

def test_win_prob():
    assert lineup.win_prob({"total": 100, "sd": 10}, {"total": 100, "sd": 10}) == 0.5
    # 10 points ahead, combined sd sqrt(36 + 64) = 10: one sd ahead = 84%
    assert lineup.win_prob({"total": 110, "sd": 6}, {"total": 100, "sd": 8}) == pytest.approx(0.8413, abs=1e-4)
    assert lineup.win_prob({"total": 90, "sd": 0}, {"total": 80, "sd": 0}) == 1.0
    assert lineup.win_prob({"total": 80, "sd": 0}, {"total": 90, "sd": 0}) == 0.0


def test_mode_thresholds():
    assert lineup.mode_for(0.65, CFG) == "favored"
    assert lineup.mode_for(0.64, CFG) == "even"
    assert lineup.mode_for(0.35, CFG) == "even"
    assert lineup.mode_for(0.34, CFG) == "underdog"
    assert lineup.mode_for(None, CFG) == "even"


# ---------- picking ----------

def test_best_lineup_fills_flex_with_best_left():
    r = run(roster(), ["0"] * 10)
    assert ids(r) == BEST
    assert r["mode"] == "even" and r["win"] is None   # no opponent
    assert r["me"]["total"] == pytest.approx(20 + 14 + 12 + 15 + 13 + 11 + 10 + 9 + 8 + 7)


def test_never_starts_out_ir_or_bye():
    players = roster()
    players[2]["flag"] = "Out"                       # rb1
    players[6]["opp"] = ""                           # wr1 on bye
    games = {p["team"]: game() for p in players}
    del games[players[6]["team"]]
    r = run(players, ["0"] * 10, games=games, reserve=["rb2"])
    chosen = ids(r)
    assert "rb1" not in chosen and "rb2" not in chosen and "wr1" not in chosen
    assert chosen[1:3] == ["rb3", "rb4"]


def test_empty_slot_when_no_one_healthy():
    players = [p for p in roster() if p["pos"] != "K"]
    r = run(players, ["0"] * 10)
    assert r["me"]["starters"][8] == {"slot": "K", "id": None, "pts": 0.0, "sd": 0.0,
                                      "state": "empty", "actual": None, "left": 0.0}


def test_locked_starter_stays_and_uses_actual_points():
    players = roster()
    players[11]["team"] = "THU"                      # te2 played Thursday and is starting
    games = {p["team"]: game() for p in players}
    games["THU"] = game("post", kickoff="2026-10-09T00:15Z")
    current = BEST[:5] + ["te2"] + BEST[6:]
    r = run(players, current, games=games, points={"te2": 21.4})
    te = r["me"]["starters"][5]
    assert te["id"] == "te2" and te["pts"] == 21.4 and te["sd"] == 0 and te["state"] == "final"
    assert te["why"] == "Played: 21.4 pts (predicted 7.0)"
    assert "te1" in ids(r)                           # te1 still starts, in a FLEX


def test_locked_bench_player_cannot_come_in():
    players = roster()
    players[0]["score"] = 10                         # qb1 now worse than qb2...
    games = {p["team"]: game() for p in players}
    games[players[1]["team"]] = game("in", period=1, clock=600)   # ...but qb2's game started
    current = ["qb1"] + BEST[1:]
    r = run(players, current, games=games)
    assert ids(r)[0] == "qb1"


def test_live_player_counts_points_so_far_plus_rest():
    players = roster()
    games = {p["team"]: game() for p in players}
    games[players[0]["team"]] = game("in", period=3, clock=450)   # 37.5% left
    r = run(players, BEST, games=games, points={"qb1": 8.0})
    qb = r["me"]["starters"][0]
    assert qb["state"] == "live" and qb["pts"] == pytest.approx(8 + 20 * 0.375, abs=0.05)
    assert qb["sd"] == pytest.approx(10 * math.sqrt(0.375), abs=0.01)


# ---------- opponent, mode and changes ----------

def opponent():
    return [player("o1", "QB", 22, roster=2), player("o2", "RB", 15, roster=2),
            player("o3", "WR", 0.0, roster=2, flag="Out", sd=6,
                   adj=[{"key": "injury", "pts": -12.0}])]


def test_opponent_lineup_as_set_counts_out_player_as_zero():
    opp = opponent()
    opp[2]["range"]["if_plays"] = True
    r = run(roster() + opp, BEST, opp_starters=["o1", "o2", "0", "o3"] + ["0"] * 6)
    assert ids(r, "opp")[:4] == ["o1", "o2", None, "o3"]
    out = r["opp"]["starters"][3]
    assert out["pts"] == 0 and out["sd"] == 0
    assert r["opp"]["total"] == 37.0
    assert r["mode"] == "favored" and r["win"] > 0.65


def test_underdog_leans_on_ceiling():
    players = roster()
    players[4]["range"].update(ceiling=11.0)               # rb3: 9.0, steady
    players[11].update(score=8.8)
    players[11]["range"].update(floor=3.0, ceiling=19.0)   # te2: 8.8, boom or bust
    strong = [player(f"o{i}", "QB", 30, roster=2) for i in range(10)]
    r = run(players + strong, BEST, opp_starters=[p["id"] for p in strong])
    assert r["mode"] == "underdog" and r["first"]["win"] < 0.35
    flex = r["me"]["starters"][7]
    assert flex["id"] == "te2" and flex["new"] and flex["replaces"] == "rb3"
    assert flex["why"].startswith("Higher ceiling than Prb3 (19.0 vs 11.0)")
    assert r["changes"] == [{"slot": "FLEX", "in": "te2", "out": "rb3"}]


def test_favored_leans_on_floor():
    players = roster()
    players[4]["range"].update(floor=8.0)                  # rb3: 9.0, safe
    players[11].update(score=9.2)
    players[11]["range"].update(floor=2.0)                 # te2: 9.2, shaky
    weak = [player("o1", "K", 5, roster=2)]
    r = run(players + weak, BEST, opp_starters=["0"] * 8 + ["o1", "0"])
    assert r["mode"] == "favored"
    assert ids(r)[7] == "rb3" and r["changes"] == []
    assert r["first"]["win"] >= 0.65
    assert r["me"]["starters"][7]["why"].startswith("Safer floor than Pte2 (8.0 vs 2.0)")


def test_close_call_reason():
    players = roster()
    players[11]["score"] = 8.5                       # te2 just behind rb3 (9.0)
    r = run(players, BEST)
    assert r["me"]["starters"][7]["why"] == "Close call over Pte2 (+0.5)"
    assert r["me"]["starters"][0]["why"] == "#1 QB this week"


def test_changes_keep_players_in_their_current_slots():
    # Sleeper has wr3 at WR and wr2 in FLEX; wr2 > wr3 but nobody needs to move
    current = ["qb1", "rb1", "rb2", "wr1", "wr3", "te1", "wr2", "rb3", "k1", "def1"]
    r = run(roster(), current)
    assert ids(r) == current and r["changes"] == []


def test_benching_out_starter_pairs_the_change():
    players = roster()
    players[6]["flag"] = "Out"                       # wr1 is Out but starting
    r = run(players, BEST)
    # te2 (7.0) is the best one left; wr3 slides from FLEX to WR to make room
    assert ids(r) == ["qb1", "rb1", "rb2", "wr3", "wr2", "te1", "te2", "rb3", "k1", "def1"]
    assert r["changes"] == [{"slot": "FLEX", "in": "te2", "out": "wr1"}]
    assert r["me"]["starters"][6]["replaces"] == "wr1"


# ---------- close calls ----------

def test_close_call_pairs_bench_player_with_the_starter_he_would_replace():
    players = roster()
    players[11]["score"] = 8.5                       # te2 just behind rb3 (9.0) in FLEX
    r = run(players, BEST)
    assert len(r["close_calls"]) == 1
    c = r["close_calls"][0]
    assert (c["start"], c["bench"], c["slot"], c["gap"], c["measure"]) == ("rb3", "te2", "FLEX", 0.5, "predicted points")
    assert c["for_start"][0] == "More expected points: 9.0 vs 8.5"


def test_close_calls_skip_big_gaps_and_locked_players():
    players = roster()
    players[11]["score"] = 8.5
    games = {p["team"]: game() for p in players}
    games[players[11]["team"]] = game("in", period=1, clock=800)   # te2 already playing
    r = run(players, BEST, games=games)
    assert r["close_calls"] == []                    # te2 is locked on the bench; the rest are 2+ apart


def test_case_for_each_side():
    a = player("a", "WR", 9.2, floor=5.5, ceiling=15.4, injury="Questionable", injury_detail="Groin",
               adj=[{"key": "matchup", "label": "Tough matchup", "pts": -0.6, "why": "x"}])
    b = player("b", "WR", 8.4, floor=4.8, ceiling=14.2,
               adj=[{"key": "returns", "label": "Return man", "pts": 1.2, "why": "84 kick return yds"}],
               cons={"rank": 40, "pts": 7.9})
    a["cons"] = {"rank": 50, "pts": 7.0}
    assert lineup.case_for(a, b, "underdog") == [
        "Higher ceiling: 15.4 vs 14.2", "More expected points: 9.2 vs 8.4", "Safer floor: 5.5 vs 4.8"]
    assert lineup.case_for(b, a, "underdog") == [
        "Pa is Questionable (Groin)", "Return man (+1.2): 84 kick return yds",
        "Pa has a tough matchup (−0.6)", "Experts like him more: 7.9 vs 7.0 pts"]


def test_last_name_skips_suffixes():
    assert lineup._last("Marvin Harrison Jr.") == "Harrison"
    assert lineup._last("Houston Texans") == "Texans"


# ---------- late swap ----------

LATE = "2026-10-11T20:25Z"


def test_late_swap_moves_latest_game_into_flex():
    players = roster()
    games = {p["team"]: game() for p in players}
    games[players[6]["team"]] = game(kickoff=LATE)   # wr1 plays late, from a WR slot
    r = run(players, BEST, games=games)
    # Do it before wr3's 1 PM game locks him in FLEX
    assert r["late_swap"] == {"moves": [{"id": "wr1", "to": "FLEX"}, {"id": "wr3", "to": "WR"}],
                              "latest": "wr1", "kickoff": LATE, "deadline": SUNDAY}
    assert r["changes"] == []                        # a tip, not a lineup change


def test_no_late_swap_when_flex_already_late_or_impossible():
    players = roster()
    games = {p["team"]: game() for p in players}
    games[players[8]["team"]] = game(kickoff=LATE)   # wr3 plays late and is already in FLEX
    assert run(players, BEST, games=games)["late_swap"] is None
    games = {p["team"]: game() for p in players}
    games[players[10]["team"]] = game(kickoff=LATE)  # te1 is late, but no other TE could take his slot
    assert run(players, BEST, games=games)["late_swap"] is None


def test_no_late_swap_without_kickoff_times():
    players = roster()
    games = {p["team"]: game() for p in players}
    games[players[6]["team"]] = game(kickoff=LATE)
    del games[players[8]["team"]]                    # wr3's game has no ESPN entry
    assert run(players, BEST, games=games)["late_swap"] is None


# ---------- review fixes ----------

def test_without_espn_sleeper_points_mean_played():
    players = roster()
    players[11]["game_date"] = "2026-10-08"          # te2 played Thursday (no points)
    current = BEST[:5] + ["te2"] + BEST[6:]
    r = run(players, current, games={}, points={"wr1": 12.5}, now="2026-10-11T19:00:00Z")
    assert r["times_known"] is False
    by_slot = {e["id"]: e for e in r["me"]["starters"]}
    assert by_slot["wr1"]["state"] == "final" and by_slot["wr1"]["pts"] == 12.5
    assert by_slot["te2"]["state"] == "final"        # locked in his slot, not benched
    assert ids(r)[5] == "te2"


def test_live_doubtful_player_who_is_scoring_counts_in_full():
    p = player("d", "WR", 4.0, sd=5, adj=[{"key": "injury", "pts": -6.0}], flag="Doubtful")
    p["range"].update(if_plays=True, sd=5)
    e = lineup.expected(p, game("in", period=2, clock=0), 9.0, lineup._time(NOW))
    assert e["pts"] == pytest.approx(9 + 10 * 0.5) and e["sd"] == pytest.approx(5 * math.sqrt(0.5))


SCORING = {"pts_allow_0": 10, "pts_allow_1_6": 7, "pts_allow_7_13": 4, "pts_allow_14_20": 1,
           "pts_allow_21_27": 0, "pts_allow_28_34": -1, "pts_allow_35p": -4}


def test_live_defense_does_not_count_the_bracket_twice():
    d = player("hou", "DEF", 12.0, parts=[["sack", 3, 1.0, 3.0], ["pts_allow", 16.0, None, 1.0]])
    g = dict(game("in", period=2, clock=0), opp_score=0.0)   # halftime, shutout so far
    # Sleeper shows 13: 3 sacks + 10 for a shutout so far
    e = lineup.expected(d, g, 13.0, lineup._time(NOW), scoring=SCORING)
    # (13 - 10) + (12 - 1) x 0.5 + the bracket blend for 8 allowed by the end
    # (bracket midpoints: 7 pts at 3.5 allowed, 4 pts at 10)
    assert e["pts"] == pytest.approx(3 + 11 * 0.5 + (7 - 3 * 4.5 / 6.5))
    assert lineup.bracket_points(SCORING, "pts_allow", 17) == 1
    assert lineup.bracket_points(SCORING, "pts_allow", 35) == -4


def test_live_defense_before_sleeper_scores_him_keeps_his_projection():
    # Kickoff time passed, ESPN shows 0-0 (still "pre"), Sleeper has no line
    # yet: there's no shutout bonus in his 0 points to take back out
    d = player("hou", "DEF", 12.0, parts=[["sack", 3, 1.0, 3.0], ["pts_allow", 16.0, None, 1.0]])
    g = dict(game("pre"), opp_score=0.0)
    e = lineup.expected(d, g, 0.0, lineup._time("2026-10-11T17:03:00Z"), scoring=SCORING)
    assert e["state"] == "live" and e["left"] == 1.0
    # (12 - 1) + the bracket blend for 16 allowed (4 pts at 10, 1 pt at 17)
    assert e["pts"] == pytest.approx(11 + 4 - 3 * 6 / 7)


def test_live_defense_takes_back_the_bracket_sleeper_counted():
    # ESPN already shows the TD that made it 14-0; Sleeper's line still says
    # 7 allowed (4 pts) + a 4th-down stop (1 pt) = 5
    d = player("hou", "DEF", 12.0, parts=[["sack", 3, 1.0, 3.0], ["pts_allow", 16.0, None, 1.0]],
               actual={"pts": 5.0, "official": 5.0,
                       "parts": [["pts_allow_7_13", 1, 4, 4.0], ["def_4_and_stop", 1, 1, 1.0]]})
    g = dict(game("in", period=2, clock=0), opp_score=14.0)
    e = lineup.expected(d, g, 5.0, lineup._time(NOW), scoring=SCORING)
    # (5 - 4) + (12 - 1) x 0.5 + the bracket blend for 14 + 16 x 0.5 = 22 allowed
    assert e["pts"] == pytest.approx(1 + 11 * 0.5 + 1 - 1 * 5 / 7)


# Seen 2026-10-11 (PHI-JAX, Q2): Sleeper's stats had a TD that its matchup
# points didn't yet (Hurts 10.08 vs 1.6; JAX DEF 2.0 vs 5.0)

def test_live_player_counts_the_fresher_stat_line():
    p = player("qb", "QB", 20.0, actual={"pts": 10.08, "official": 1.6, "parts": []})
    e = lineup.expected(p, game("in", period=3, clock=900), 1.6, lineup._time(NOW))
    assert e["actual"] == 10.08 and e["pts"] == pytest.approx(10.08 + 20 * 0.5)


def test_finished_player_counts_sleepers_official_points():
    p = player("qb", "QB", 20.0, actual={"pts": 10.08, "official": 9.9, "parts": []})
    e = lineup.expected(p, game("post"), 9.9, lineup._time(NOW))
    assert e["actual"] == 9.9 and e["pts"] == 9.9


def test_live_defense_while_sleepers_matchup_points_lag():
    d = player("jax", "DEF", 12.0, parts=[["sack", 3, 1.0, 3.0], ["pts_allow", 16.0, None, 1.0]],
               actual={"pts": 2.0, "official": 5.0,
                       "parts": [["def_4_and_stop", 1, 1, 1.0], ["pts_allow_14_20", 1, 1, 1.0]]})
    g = dict(game("in", period=2, clock=0), opp_score=14.0)
    e = lineup.expected(d, g, 5.0, lineup._time(NOW), scoring=SCORING)
    # (2 - 1) + (12 - 1) x 0.5 + the bracket blend for 22 allowed
    assert e["actual"] == 2.0
    assert e["pts"] == pytest.approx(1 + 11 * 0.5 + 1 - 1 * 5 / 7)


def test_empty_slot_is_filled_without_pairing_an_unrelated_player():
    players = roster()
    players[6]["flag"] = "Out"                       # wr1 is Out, starting at WR
    current = ["qb1", "rb1", "0", "wr1", "wr2", "te1", "wr3", "rb3", "k1", "def1"]
    r = run(players, current)
    assert {"slot": "RB", "in": "rb2", "out": None} in r["changes"]
    assert any(c["out"] == "wr1" and c["in"] != "rb2" for c in r["changes"])


def test_slides_needed_for_a_newcomer_are_listed():
    players = roster()
    players[6]["flag"] = "Out"                       # wr1 Out; the best one left is te2
    r = run(players, BEST)
    assert r["moves"] == [{"id": "wr3", "to": "WR"}]
    assert r["changes"] == [{"slot": "FLEX", "in": "te2", "out": "wr1"}]


def test_case_for_skips_a_matchup_both_players_share():
    a = player("a", "WR", 9.2, adj=[{"key": "matchup", "label": "Tough matchup", "pts": -0.5, "why": "x"}])
    b = player("b", "WR", 8.4, adj=[{"key": "matchup", "label": "Tough matchup", "pts": -0.2, "why": "x"}])
    assert not any("matchup" in r for r in lineup.case_for(b, a, "even"))


def test_close_call_gap_matches_the_numbers_shown():
    players = roster()
    players[11]["score"] = 7.66                      # rb3 9.0 vs te2 7.66, shown as 7.7
    r = run(players, BEST)
    c = r["close_calls"][0]
    assert c["gap"] == round(c["values"][0] - c["values"][1], 1) and c["gap"] < 1.5


def test_mode_uses_the_percent_shown():
    assert lineup.mode_for(0.347, CFG) == "even"     # shows as 35%, so not "under 35%"
    assert lineup.mode_for(0.646, CFG) == "favored"  # shows as 65%


# ---------- bench and free agents ----------

RATIOS = {"QB": (0.6, 1.6, 0.5), "RB": (0.6, 1.6, 0.5), "WR": (0.6, 1.6, 0.5), "TE": (0.6, 1.6, 0.5),
          "K": (0.6, 1.6, 0.5), "DEF": (0.6, 1.6, 0.5)}
MARKET = {"ratios": RATIOS, "labels": {"boom": 1.05, "steady": 1.10}, "trending": {}, "dropped": {},
          "clear_days": 1}


def test_labels_against_the_position_usual():
    usual = {"boom": 1.05, "steady": 1.10}
    assert lineup.label(player("a", "WR", 10, floor=6, ceiling=17), RATIOS, usual) == "Boom"      # 1.7 vs 1.6
    assert lineup.label(player("b", "WR", 10, floor=6.8, ceiling=16), RATIOS, usual) == "Steady"  # 0.68 vs 0.6
    assert lineup.label(player("c", "WR", 10, floor=6, ceiling=16), RATIOS, usual) == ""


def test_te_steady_comes_from_wopr():
    cfg = {"boom": 1.05, "steady": 1.10, "wopr_positions": ["TE"], "wopr_steady": 0.45}
    # A big share of the passing game: Steady, even with a boom-sized ceiling
    assert lineup.label(player("a", "TE", 10, floor=5, ceiling=17, wopr=0.5), RATIOS, cfg) == "Steady"
    # Under the cutoff: no Steady from his floor, but Boom still can come
    assert lineup.label(player("b", "TE", 10, floor=6.8, ceiling=16, wopr=0.3), RATIOS, cfg) == ""
    assert lineup.label(player("c", "TE", 10, floor=6, ceiling=17, wopr=0.3), RATIOS, cfg) == "Boom"
    # No WOPR yet (under 3 games): the floor rule
    assert lineup.label(player("d", "TE", 10, floor=6.8, ceiling=16), RATIOS, cfg) == "Steady"
    # WRs keep the floor rule
    assert lineup.label(player("e", "WR", 10, floor=5, ceiling=16, wopr=0.7), RATIOS, cfg) == ""


def test_labels_compare_the_range_before_its_stretch():
    # The same players with ranges stretched 1.2x from the score get the same labels
    usual, s = {"boom": 1.05, "steady": 1.10}, 1.2
    def stretched(pid, floor, ceiling):
        return player(pid, "WR", 10, floor=10 - s * (10 - floor), ceiling=10 + s * (ceiling - 10))
    assert lineup.label(stretched("a", 6, 17), RATIOS, usual, stretch=s) == "Boom"
    assert lineup.label(stretched("b", 6.8, 16), RATIOS, usual, stretch=s) == "Steady"
    assert lineup.label(stretched("c", 6, 16), RATIOS, usual, stretch=s) == ""


def test_free_agent_who_beats_a_starter_comes_first():
    fa = [player("fa1", "WR", 9.5, roster=None, ceiling=16), player("fa2", "RB", 6, roster=None),
          player("fa3", "K", 7, roster=None), player("fa4", "K", 9, roster=None)]
    r = run(roster() + fa, BEST, market=MARKET)
    got = {f["id"]: f for f in r["free_agents"]}
    # Biggest upgrade first: the kicker by 1.0, then the WR by 0.5 over rb3 in FLEX
    assert [f["id"] for f in r["free_agents"][:2]] == ["fa4", "fa1"]
    assert got["fa1"]["start_over"] == "rb3" and got["fa1"]["gap"] == 0.5
    assert got["fa1"]["why"] == "Start over Prb3 (+0.5)"
    assert "fa4" in got and got["fa4"]["start_over"] == "k1"   # a better kicker is worth streaming
    assert "fa3" not in got                        # a worse kicker isn't listed at all
    assert got["fa2"]["why"].endswith("3.0 behind Prb3")


def test_free_agents_already_played_rank_last_and_can_be_flagged_as_dropped():
    fa = [player("fa1", "WR", 9.5, roster=None, team="THU"), player("fa2", "WR", 6, roster=None)]
    games = {p["team"]: game() for p in roster() + fa}
    games["THU"] = game("post", kickoff="2026-10-09T00:15Z")
    market = dict(MARKET, dropped={"fa2": 1791636000000}, trending={"fa2": 5400})   # dropped 2026-10-10 12:40Z
    r = run(roster() + fa, BEST, games=games, market=market)
    assert [f["id"] for f in r["free_agents"]] == ["fa2", "fa1"]
    assert r["free_agents"][1]["why"] == "Game played"
    assert r["free_agents"][0]["dropped"] == "2026-10-10T12:40Z" and r["free_agents"][0]["trending"] == 5400


def test_free_agents_whose_game_is_on_or_off_say_just_that():
    fa = [player("fa1", "WR", 9, roster=None, team="LIV"), player("fa2", "RB", 8, roster=None, team="OFF")]
    games = {p["team"]: game() for p in roster() + fa}
    games["LIV"] = game("in", period=2, clock=300)
    games["OFF"] = game(status="STATUS_POSTPONED")
    r = run(roster() + fa, BEST, games=games, market=MARKET)
    got = {f["id"]: f["why"] for f in r["free_agents"]}
    assert got == {"fa1": "Playing now", "fa2": "No game this week"}


def test_bench_flex_options():
    r = run(roster(), BEST, market=MARKET)
    assert [b["id"] for b in r["bench_flex"]] == ["te2", "wr4", "rb4"]
    assert r["bench_flex"][0] == {"id": "te2", "value": 7.0, "behind": "rb3", "gap": -2.0, "label": "",
                                  "why": "2.0 behind Prb3"}


def test_bench_rows_compare_with_the_same_starter_as_close_calls():
    # The weakest starter a bench WR could replace is the WR2 (8.0), not a FLEX RB (10.5+)
    players = [player("qb1", "QB", 20), player("rb1", "RB", 14), player("rb2", "RB", 12),
               player("rb3", "RB", 11), player("rb4", "RB", 10.5), player("wr1", "WR", 15),
               player("wr2", "WR", 8.0), player("wr3", "WR", 7.5), player("te1", "TE", 11),
               player("k1", "K", 8), player("def1", "DEF", 7)]
    current = ["qb1", "rb1", "rb2", "wr1", "wr2", "te1", "rb3", "rb4", "k1", "def1"]
    r = run(players, current, market=MARKET)
    wr3 = next(b for b in r["bench_flex"] if b["id"] == "wr3")
    assert (wr3["behind"], wr3["gap"]) == ("wr2", -0.5)
    call = next(c for c in r["close_calls"] if c["bench"] == "wr3")
    assert (call["start"], call["gap"]) == ("wr2", 0.5)    # same pair, same distance


def test_empty_slot_gets_a_free_agent_to_fill_it():
    players = [p for p in roster() if p["id"] != "k1"]   # no kicker with a game (bye)
    fa = [player("faK", "K", 7.0, roster=None), player("faW", "WR", 6.0, roster=None)]
    r = run(players + fa, BEST, market=MARKET)
    top = r["free_agents"][0]
    assert top["id"] == "faK" and top["fills"] == "K" and top["why"] == "Fills your empty K slot (+7.0)"


def test_doubtful_players_get_no_boom_or_steady_label():
    p = player("d", "WR", 4.0, floor=6, ceiling=16, sd=5, adj=[{"key": "injury", "pts": -6.0}], flag="Doubtful")
    p["range"]["if_plays"] = True
    assert lineup.label(p, RATIOS, {"boom": 1.05, "steady": 1.10}) == ""


def test_leaned_rows_show_both_numbers():
    players = roster()
    strong = [player(f"o{i}", "QB", 30, roster=2) for i in range(10)]
    fa = [player("faW", "WR", 6.0, roster=None)]
    r = run(players + strong + fa, BEST, opp_starters=[p["id"] for p in strong], market=MARKET)
    assert r["mode"] == "underdog"
    why = next(f for f in r["free_agents"] if f["id"] == "faW")["why"]
    assert why.endswith(" upside score") and " vs " in why


# ---------- Doubtful: flagged, never started over a healthy player ----------

def test_a_doubtful_player_is_not_started_when_a_healthy_one_fits():
    players = roster()
    players[6].update(flag="Doubtful", injury="Doubtful")    # wr1 (15) is Doubtful
    r = run(players, BEST)
    assert "wr1" not in ids(r) and "te2" in ids(r)   # the next best for FLEX
    # ...but he's the first close call, marked Doubtful, so the owner can choose him
    call = r["close_calls"][0]
    assert call["bench"] == "wr1" and call["doubtful"] and call["values"][1] > call["values"][0]
    assert call["gap"] == round(call["values"][1] - call["values"][0], 1)
    assert any("Doubtful" in t for t in call["for_start"])


def test_a_doubtful_player_starts_when_no_one_else_can():
    players = [p for p in roster() if p["id"] != "qb2"]
    players[0].update(flag="Doubtful", injury="Doubtful")    # qb1, the only QB
    r = run(players, BEST)
    assert ids(r)[0] == "qb1"


def test_live_defense_with_no_time_left_counts_just_his_points():
    # Found in review: at 0:00 of the 4th (or in overtime) the smoothed
    # bracket was still added, so 13.0 so far showed as about 13.4
    d = player("hou", "DEF", 12.0, parts=[["sack", 3, 1.0, 3.0], ["pts_allow", 16.0, None, 1.0]],
               actual={"pts": 13.0, "official": 13.0,
                       "parts": [["pts_allow_1_6", 1, 7, 7.0], ["sack", 6, 1, 6.0]]})
    for g in (dict(game("in", period=4, clock=0), opp_score=3.0),
              dict(game("in", period=5, clock=300), opp_score=3.0)):
        e = lineup.expected(d, g, 13.0, lineup._time(NOW), scoring=SCORING)
        assert e["left"] == 0.0 and e["pts"] == pytest.approx(13.0)
