from pipeline.tiers import local_gap_tiers


def test_clear_gap_starts_new_tier():
    scores = [20, 19.8, 19.6, 19.4, 15, 14.8, 14.6, 14.4]
    tiers, breaks = local_gap_tiers(scores, min_median_gap=0.1)
    assert tiers == [1, 1, 1, 1, 2, 2, 2, 2]
    assert breaks[0]["after_rank"] == 4 and breaks[0]["gap"] == 4.4


def test_near_ties_stay_together():
    scores = [10.0, 10.0, 9.9, 9.9, 9.8, 9.8, 9.7, 9.7]
    tiers, _ = local_gap_tiers(scores)
    assert set(tiers) == {1}


def test_small_gap_respects_min_tier_size():
    # 1.0 gap after the 2nd player is "big" locally but under always_break_gap
    scores = [20, 19, 18.0, 17.9, 17.8, 17.7, 17.6, 17.5]
    tiers, _ = local_gap_tiers(scores, min_median_gap=0.1, always_break_gap=1.5)
    assert tiers[:3] == [1, 1, 1]


def test_big_gap_breaks_even_below_min_size():
    scores = [25, 21, 20.9, 20.8, 20.7, 20.6, 20.5]
    tiers, breaks = local_gap_tiers(scores, always_break_gap=1.5)
    assert tiers == [1, 2, 2, 2, 2, 2, 2]
    assert breaks[0]["big_gap"] is True


def test_empty_and_single():
    assert local_gap_tiers([]) == ([], [])
    assert local_gap_tiers([5.0]) == ([1], [])
