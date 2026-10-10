from pipeline.scoring import score_line

LEAGUE = {"rec": 0.5, "bonus_rec_te": 0.5, "rec_yd": 0.1, "rec_td": 6, "pass_td": 6,
          "pass_int": -3, "pass_yd": 0.04, "fum": -1, "fum_lost": -2, "kr_yd": 0.05,
          "fgm_30_39": 3, "fgm_40_49": 4, "fgmiss": -1, "xpm": 1,
          "pts_allow_0": 10, "pts_allow_1_6": 7, "pts_allow_7_13": 4, "pts_allow_14_20": 1,
          "pts_allow_21_27": 0, "pts_allow_28_34": -1, "pts_allow_35p": -4, "sack": 1}


def test_te_premium_counts_once_when_sleeper_includes_it():
    # Sleeper's TE lines carry bonus_rec_te (= catches) already
    stats = {"rec": 7.0, "bonus_rec_te": 7.0, "rec_yd": 60.0}
    total, parts = score_line(stats, "TE", LEAGUE)
    assert total == 7 * 0.5 + 7 * 0.5 + 6.0  # 13.0, not 16.5
    assert [p[0] for p in parts].count("bonus_rec_te") == 1


def test_te_premium_derived_from_catches_when_missing():
    total, parts = score_line({"rec": 4.0}, "TE", LEAGUE)
    assert total == 4.0
    assert ["bonus_rec_te", 4.0, 0.5, 2.0] in parts


def test_no_te_premium_for_wide_receivers():
    total, _ = score_line({"rec": 4.0}, "WR", LEAGUE)
    assert total == 2.0


def test_qb_line_with_int_penalty_and_six_point_tds():
    total, _ = score_line({"pass_yd": 250, "pass_td": 2, "pass_int": 1}, "QB", LEAGUE)
    assert total == 10 + 12 - 3


def test_return_yards_score():
    total, _ = score_line({"kr_yd": 100}, "WR", LEAGUE)
    assert total == 5.0


def test_kicker_misses_come_from_distance_buckets():
    stats = {"fgm_30_39": 1.0, "fgm_40_49": 1.0, "fgmiss_40_49": 0.25, "fgmiss_50p": 0.25, "xpm": 3}
    total, parts = score_line(stats, "K", LEAGUE)
    assert total == 3 + 4 - 0.5 + 3
    assert ["fgmiss", 0.5, -1, -0.5] in parts


def test_defense_brackets_smoothed_between_midpoints():
    # 15.5 allowed sits between the 7-13 (mid 10, +4) and 14-20 (mid 17, +1) brackets
    stats = {"pts_allow": 15.5, "pts_allow_14_20": 1.0, "sack": 2.0}
    total, parts = score_line(stats, "DEF", LEAGUE, smooth_def_brackets=True)
    expected = 4 + (1 - 4) * (5.5 / 7)
    assert abs(total - (expected + 2)) < 0.01
    assert not any(p[0] == "pts_allow_14_20" for p in parts)


def test_defense_bracket_flag_used_when_not_smoothing():
    stats = {"pts_allow": 15.5, "pts_allow_14_20": 1.0}
    total, _ = score_line(stats, "DEF", LEAGUE, smooth_def_brackets=False)
    assert total == 1.0


def test_parts_add_up_to_total():
    stats = {"rec": 5.3, "rec_yd": 61.7, "rec_td": 0.43, "fum": 0.07, "fum_lost": 0.03}
    total, parts = score_line(stats, "WR", LEAGUE)
    assert abs(sum(p[3] for p in parts) - total) < 0.03
