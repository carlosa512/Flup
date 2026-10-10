import tomllib
from pathlib import Path

import pytest

from pipeline import consensus, history, model

SETTINGS = tomllib.loads((Path(__file__).resolve().parent.parent / "settings.toml").read_text())
ADJ = SETTINGS["adjust"]
SCORING = {"rec": 0.5, "rec_yd": 0.1, "rush_yd": 0.1, "rush_td": 6, "pass_yd": 0.04,
           "pass_td": 6, "pass_int": -3, "kr_yd": 0.05, "pr_yd": 0.05}


def game(**kw):
    g = {"season": "2026", "week": 1, "team": "DET", "opp": "GB", "pts": 10.0, "pos": "WR"}
    g.update(kw)
    return g


# ---------- usage ----------

def test_usage_up_when_recent_share_rises():
    games = [game(snap_share=0.6, tgt_share=0.15)] + [game(snap_share=0.9, tgt_share=0.25)] * 3
    a = model.usage("WR", 12.0, games, ADJ["usage"])
    assert a["pts"] > 0 and a["label"] == "Usage up"
    assert "last 3 games" in a["why"]


def test_usage_needs_enough_games():
    games = [game(snap_share=0.9, tgt_share=0.25)] * 3
    assert model.usage("WR", 12.0, games, ADJ["usage"]) is None


def test_usage_ignores_games_missing_snap_counts():
    steady = [game(snap_share=0.8, tgt_share=0.2)] * 4
    missing = [game(tgt_share=0.2)] * 3  # no snap counts those weeks
    a = model.usage("WR", 12.0, steady + missing, ADJ["usage"])
    assert a is None or abs(a["pts"]) < 0.05  # no made-up snap drop


def test_usage_capped():
    games = [game(snap_share=0.2, tgt_share=0.05)] * 5 + [game(snap_share=0.9, tgt_share=0.4)] * 3
    a = model.usage("WR", 40.0, games, dict(ADJ["usage"], weight=5))
    assert a["pts"] == ADJ["usage"]["cap"]


def test_no_usage_for_qbs():
    assert model.usage("QB", 20.0, [game()] * 5, ADJ["usage"]) is None


# ---------- game environment ----------

def test_environment_high_implied_total_helps():
    p = {"pos": "WR", "team": "DET", "opp": "ARI", "implied": 30.0, "spread": -5.5}
    a = model.environment(p, 10.0, 22.0, 24.5, ADJ["environment"])
    assert a["pts"] > 0 and "implied for 30.0" in a["why"]


def test_environment_favored_rb_gets_spread_bump():
    rb = {"pos": "RB", "team": "JAX", "opp": "PHI", "implied": 22.0, "spread": -7.5}
    a = model.environment(rb, 12.0, 22.0, 14.5, ADJ["environment"])
    assert a["pts"] == pytest.approx(7.5 * ADJ["environment"]["spread_rb"], abs=0.01)
    assert "favored by 7.5" in a["why"]


def test_environment_defense_uses_opponent_total():
    d = {"pos": "DEF", "team": "HOU", "opp": "TEN", "implied": 26.0, "spread": -7}
    a = model.environment(d, 10.0, 22.0, 15.8, ADJ["environment"])
    assert a["pts"] > 0 and "TEN is implied for 15.8" in a["why"]


def test_environment_skipped_without_line():
    assert model.environment({"pos": "WR", "implied": None}, 10, 22, None, ADJ["environment"]) is None


# ---------- matchup ----------

def hist_with_allowed(allowed):
    return {"allowed": allowed, "games": {}, "current": "2026"}


def test_matchup_soft_defense_helps_and_shrinks_with_few_games():
    allowed = {"MIA": {"TE": {1: 20, 2: 20}}, "NE": {"TE": {1: 8, 2: 8}}, "GB": {"TE": {1: 14, 2: 14}}}
    p = {"pos": "TE", "opp": "MIA"}
    a = model.matchup(p, 10.0, hist_with_allowed(allowed), ADJ["matchup"])
    league = (20 + 8 + 14) / 3
    expected = 10.0 * ((20 / league - 1) * 2 / (2 + ADJ["matchup"]["shrink_games"])) * ADJ["matchup"]["weight"]
    assert a["pts"] == pytest.approx(expected, abs=0.01)
    assert "MIA allows 20.0 pts/game to TEs" in a["why"]


def test_matchup_none_for_unknown_opponent():
    assert model.matchup({"pos": "TE", "opp": "XYZ"}, 10, hist_with_allowed({}), ADJ["matchup"]) is None


# ---------- QB style ----------

def test_high_int_passer_penalized_with_matching_reason():
    games = [game(pos="QB", pass_att=35, pass_int=2, pts=15)] * 6
    a = model.qb_style(18.0, games, {"pass_att": 35, "pass_int": 0.6}, SCORING, 0.022, ADJ["qb"])
    assert a["pts"] < 0 and a["label"] == "Turnover risk"
    assert "league 2.2%" in a["why"]


def test_low_int_runner_bonus():
    games = [game(pos="QB", pass_att=25, pass_int=0, rush_yd=60, rush_td=0.5, pts=22)] * 6
    a = model.qb_style(20.0, games, {"pass_att": 25, "pass_int": 0.5}, SCORING, 0.022, ADJ["qb"])
    assert a["pts"] > 0 and a["label"] == "Low-INT runner" and "running" in a["why"]


def test_high_int_runner_gets_no_rushing_bonus():
    games = [game(pos="QB", pass_att=25, pass_int=2, rush_yd=60, rush_td=0.5, pts=22)] * 6
    a = model.qb_style(20.0, games, {"pass_att": 25, "pass_int": 0.5}, SCORING, 0.022, ADJ["qb"])
    assert a["label"] == "Turnover risk"


def test_low_int_pocket_passer_gets_nothing():
    games = [game(pos="QB", pass_att=35, pass_int=0, rush_yd=5, pts=20)] * 6
    assert model.qb_style(20.0, games, {"pass_att": 35}, SCORING, 0.022, ADJ["qb"]) is None


# ---------- returns ----------

def test_kick_return_yards_added_when_not_projected():
    games = [game(kr=3, kr_yd=70, pr=0)] * 3
    a = model.returns(games, {"rec": 3}, SCORING, ADJ["returns"])
    assert a["pts"] == pytest.approx(70 * 0.05 + ADJ["returns"]["bonus"])
    assert "70 kick return yds" in a["why"]


def test_projected_kick_returns_only_get_the_bump():
    games = [game(kr=3, kr_yd=70, pr=0)] * 3
    a = model.returns(games, {"kr_yd": 60}, SCORING, ADJ["returns"])
    assert a["pts"] == ADJ["returns"]["bonus"] and a["why"].startswith("Returns kicks")


def test_projected_punt_returns_not_added_twice():
    games = [game(kr=0, pr=3, pr_yd=30)] * 3
    a = model.returns(games, {"pr_yd": 25}, SCORING, ADJ["returns"])
    assert a["pts"] == ADJ["returns"]["bonus"]


def test_not_a_returner():
    assert model.returns([game()] * 3, {}, SCORING, ADJ["returns"]) is None


def test_returns_capped():
    a = model.returns([game(kr=6, kr_yd=200)] * 3, {}, SCORING, ADJ["returns"])
    assert a["pts"] == ADJ["returns"]["cap"]


# ---------- injury ----------

@pytest.mark.parametrize("status,share", [("Questionable", "questionable"), ("Doubtful", "doubtful"), ("Out", "out"), ("IR", "out")])
def test_injury_discounts(status, share):
    a = model.injury(status, "Ankle", 10.0, ADJ["injury"])
    assert a["pts"] == pytest.approx(-10.0 * ADJ["injury"][share])
    assert a["why"] == f"Ankle, {round(ADJ['injury'][share] * 100)}% off"


def test_questionable_spares_the_consensus_part():
    a = model.injury("Questionable", "", 10.0, ADJ["injury"], consensus_part=4.0)
    assert a["pts"] == pytest.approx(-6.0 * ADJ["injury"]["questionable"])


def test_healthy_no_injury_line():
    assert model.injury("", "", 10.0, ADJ["injury"]) is None


# ---------- floor / ceiling ----------

def test_range_scales_to_score_and_leans_on_position_with_few_games():
    fc = SETTINGS["floor_ceiling"]
    pos_ratio = (0.6, 1.6, 0.4)
    few = [game(pts=10), game(pts=10)]  # no spread of his own
    r = model.outcome_range(20.0, few, pos_ratio, fc)
    n, k = 2, fc["shrink_games"]
    assert r["floor"] == pytest.approx(20 * (n * 1.0 + k * 0.6) / (n + k), abs=0.1)
    assert r["ceiling"] == pytest.approx(20 * (n * 1.0 + k * 1.6) / (n + k), abs=0.1)


def test_range_ignores_backup_role_games():
    fc = SETTINGS["floor_ceiling"]
    backup = [game(pts=1, snap_share=0.1)] * 10
    starter = [game(pts=12, snap_share=0.8), game(pts=16, snap_share=0.8)]
    r = model.outcome_range(14.0, backup + starter, (0.6, 1.6, 0.4), fc)
    assert r["games"] == 2 and r["ceiling"] < 14.0 * 1.6


def test_range_not_trusted_from_low_scoring_history():
    r = model.outcome_range(10.0, [game(pts=0), game(pts=3)] * 4, (0.5, 1.8, 0.45),
                            SETTINGS["floor_ceiling"], min_mean=7)
    assert (r["floor"], r["ceiling"], r["games"]) == (5.0, 18.0, 0)


def test_range_without_history_uses_position():
    r = model.outcome_range(10.0, [], (0.5, 1.8, 0.45), SETTINGS["floor_ceiling"])
    assert (r["floor"], r["ceiling"], r["games"]) == (5.0, 18.0, 0)


# ---------- My Score ----------

def ctx(**kw):
    c = {"settings": SETTINGS, "scoring": SCORING, "history": hist_with_allowed({}),
         "season_games": lambda pid: [], "recent_games": lambda pid: [],
         "implied": {}, "avg_implied": None, "league_int_rate": 0.022, "pos_ratios": {}}
    c.update(kw)
    return c


def player(**kw):
    p = {"id": "1", "name": "A", "pos": "WR", "team": "DET", "opp": "GB", "proj": 10.0,
         "implied": None, "spread": None, "injury": "", "injury_detail": ""}
    p.update(kw)
    return p


def test_bye_week_player_gets_no_score():
    out = model.my_score(player(opp="", proj=0.0), {}, None, ctx())
    assert out["score"] == 0 and out["adj"] == [] and out["note"] == "No game this week"


def test_no_projection_no_consensus_gets_no_score():
    out = model.my_score(player(proj=0.0, pos="QB"), {}, None,
                         ctx(recent_games=lambda pid: [game(pos="QB", rush_yd=50, pts=10)] * 6))
    assert out["score"] == 0 and out["note"] == "No projection this week"


def test_card_lines_add_up():
    allowed = {"GB": {"WR": {1: 40, 2: 38}}, "X": {"WR": {1: 25, 2: 27}}}
    out = model.my_score(player(proj=13.37, implied=27.3, spread=-4.5, injury="Questionable"), {},
                         {"pts": 11.83, "rank": 20, "url": ""},
                         ctx(history=hist_with_allowed(allowed), implied={"DET": 27.3, "GB": 22.8},
                             avg_implied=22.1))
    assert out["score"] == pytest.approx(out["base"] + sum(a["pts"] for a in out["adj"]), abs=1e-9)


def test_blend_is_60_40_by_default():
    out = model.my_score(player(proj=10.0), {}, {"pts": 15.0, "rank": 12, "url": ""}, ctx())
    assert out["base"] == pytest.approx(round(0.6 * 10 + 0.4 * 15, 1))
    assert out["score"] == out["base"]


def test_projection_only_when_no_consensus():
    out = model.my_score(player(proj=10.0), {}, None, ctx())
    assert out["base"] == 10.0 and "projection only" in out["blend"]


def test_consensus_only_fallback_when_no_projection():
    out = model.my_score(player(proj=0.0), {}, {"pts": 7.0, "rank": 40, "url": ""}, ctx())
    assert out["base"] == 7.0 and "consensus only" in out["blend"]


def test_out_player_scores_zero_and_is_flagged():
    out = model.my_score(player(injury="Out"), {}, None, ctx())
    assert out["score"] == 0 and out["flag"] == "Out"


def test_combined_cap_scales_small_adjustments_together():
    allowed = {"GB": {"WR": {1: 60}}, "X": {"WR": {1: 10}}}
    settings = dict(SETTINGS, adjust=dict(ADJ, total_cap=0.5,
                                          matchup=dict(ADJ["matchup"], weight=5, cap=9),
                                          environment=dict(ADJ["environment"], weight=5, cap=9)))
    out = model.my_score(player(proj=20.0, implied=30.0, spread=-3), {}, None,
                         ctx(settings=settings, history=hist_with_allowed(allowed),
                             implied={"DET": 30.0, "GB": 27.0}, avg_implied=20.0))
    small = [a["pts"] for a in out["adj"] if a["key"] in ("usage", "environment", "matchup", "qb")]
    assert sum(small) == pytest.approx(0.5, abs=0.11)


# ---------- consensus ----------

def test_rank_points_interpolates_and_clamps():
    c = consensus.curve([18, 15, 12, 0, 9])
    assert c == [18, 15, 12, 9]
    assert consensus.rank_points(c, 2.5) == pytest.approx(13.5)
    assert consensus.rank_points(c, 0.4) == 18
    assert consensus.rank_points(c, 4) == 9
    assert consensus.rank_points(c, 40) is None  # deeper than anyone projected


def test_name_matching():
    assert consensus.norm_name("Amon-Ra St. Brown") == consensus.norm_name("Amon-Ra St Brown")
    assert consensus.norm_name("Marvin Harrison Jr.") == "marvin harrison"
    index = {("dk metcalf", "WR"): [("1", "PIT")], ("josh allen", "QB"): [("2", "BUF")]}
    assert consensus.match(index, "DK Metcalf", "WR", "PIT") == "1"


def test_parse_fantasypros_position_csv_and_defense():
    index = {("jaxon smithnjigba", "WR"): [("9", "SEA")]}
    wr, unmatched = consensus.parse_fantasypros_csv(
        '"RK","TIERS","PLAYER NAME","TEAM","OPP","MATCHUP","START SIT","PROJ. FPTS"\n'
        '"1","1","Jaxon Smith-Njigba","SEA","vs. SF","4/5","A","19.4"\n'
        '"2","1","Nobody Known","SEA","vs. SF","4/5","A","15.0"\n', "week05_wr.csv", index)
    assert wr == {"9": {"pos": "WR", "ecr": 1.0, "rank": 1, "url": ""}}
    assert unmatched == ["Nobody Known"]
    dst, _ = consensus.parse_fantasypros_csv("RK,PLAYER NAME,TEAM,POS\n1,Jacksonville Jaguars,JAC,DST1\n",
                                             "week05.csv", {})
    assert dst["JAX"]["pos"] == "DEF" and dst["JAX"]["rank"] == 1


def test_upload_without_position_reports_a_problem(tmp_path):
    (tmp_path / "week05.csv").write_text('"RK","PLAYER NAME","TEAM"\n"1","Someone","SEA"\n')
    ranks, note, problems = consensus.from_uploads(tmp_path, 5, {})
    assert ranks == {} and note == "" and "week05.csv" in problems[0]


def test_stale_consensus_rejected_using_projection_dates_when_espn_is_down():
    last_week = [1790000000.0] * 10  # kickoffs a week before the dates below
    assert consensus._current(last_week, [], {"2026-10-11"}) is False
    this_week = [1791763200.0] * 10  # 2026-10-11 00:00 UTC
    assert consensus._current(this_week, [], {"2026-10-11"}) is True


# ---------- history ----------

def stat_row(pid, pos, team, opp, **stats):
    return {"player_id": pid, "team": team, "opponent": opp, "player": {"position": pos},
            "stats": dict({"gp": 1}, **stats)}


def test_history_shares_and_points_allowed():
    rows = [stat_row("1", "WR", "DET", "GB", rec=5, rec_yd=60, rec_tgt=8, off_snp=50, tm_off_snp=60),
            stat_row("2", "WR", "DET", "GB", rec=2, rec_yd=20, rec_tgt=2, off_snp=30, tm_off_snp=60),
            stat_row("3", "WR", "DET", "GB", stats_only=1, gp=0)]
    h = history.build([("2026", 1, rows)], SCORING, "2026")
    g = h["games"]["1"][0]
    assert g["tgt_share"] == 0.8 and g["snap_share"] == pytest.approx(50 / 60)
    assert "3" not in h["games"]  # didn't play
    assert h["allowed"]["GB"]["WR"][1] == pytest.approx(5 * 0.5 + 6 + 2 * 0.5 + 2)


def test_last_season_not_counted_in_points_allowed():
    rows = [stat_row("1", "WR", "DET", "GB", rec=5)]
    h = history.build([("2025", 3, rows)], SCORING, "2026")
    assert "GB" not in h["allowed"] and h["games"]["1"][0]["season"] == "2025"


def test_kickers_keep_their_games_for_floor_and_ceiling():
    # Kicker stat lines have a team snap count but no player snap count
    rows = [stat_row("K1", "K", "DAL", "TB", fgm_30_39=1, xpm=w % 4, tm_off_snp=64) for w in range(6)]
    weeks = [("2026", w + 1, [dict(rows[w])]) for w in range(6)]
    h = history.build(weeks, {"fgm_30_39": 3, "xpm": 1}, "2026")
    games = h["games"]["K1"]
    assert all("snap_share" not in g for g in games)
    r = model.outcome_range(8.0, games, None, SETTINGS["floor_ceiling"])
    assert r is not None and r["games"] == 6


def test_real_zero_snaps_still_count_as_backup_games():
    rows = [stat_row("9", "WR", "DET", "GB", off_snp=0, tm_off_snp=60, kr=2, kr_yd=40)]
    h = history.build([("2026", 1, rows)], {"kr_yd": 0.05}, "2026")
    assert h["games"]["9"][0]["snap_share"] == 0
