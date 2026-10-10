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
        reserve=None, now=NOW, cfg=CFG):
    positions = {}
    for p in players:
        positions.setdefault(p["pos"], {"players": [], "breaks": []})["players"].append(p)
    lineups = {1: {"starters": starters, "points": points or {}}}
    if opp_starters is not None:
        lineups[2] = {"starters": opp_starters, "points": opp_points or {}}
    ctx = {"my_rid": 1, "opp_rid": 2 if opp_starters is not None else None,
           "lineups": lineups, "reserve": {1: reserve or []}}
    games = games if games is not None else {p["team"]: game() for p in players}
    return lineup.build(positions, ctx, SLOTS, games, cfg, now)


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

def test_doubtful_range_is_scaled_by_chance_to_play():
    # Healthy 10, Doubtful takes 6 off: plays 40% of the time
    p = player("d", "WR", 4.0, floor=6, ceiling=16, sd=5,
               adj=[{"key": "injury", "pts": -6.0}], flag="Doubtful")
    p["range"]["if_plays"] = True
    floor, ceiling, sd = lineup.outcome(p)
    assert floor == pytest.approx(2.4) and ceiling == pytest.approx(6.4)
    assert sd == pytest.approx(math.sqrt(0.4 * 25 + 0.4 * 0.6 * 100))


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
    assert te["why"] == "Played: 21.4 pts"
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
