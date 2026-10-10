"""Local-gap tiers, the method from the draft boards, measured in points.

Walk down the list (best first). Between each pair of neighbors there is a
gap. A new tier starts when a gap is bigger than `multiplier` x the median of
the nearby gaps, as long as both sides keep at least `min_size` players.
Retuned for points: a gap of `always_break_gap` points or more always starts
a new tier, even if that leaves a tier of one (elite players often stand
alone at the top).
"""

from statistics import median


def local_gap_tiers(scores, multiplier=2.2, window=24, min_size=3, min_median_gap=0.2,
                    always_break_gap=1.5):
    """scores sorted high to low -> (tier per player, list of breaks).

    Each break records the math: which rank it follows, the gap, the local
    median gap and the ratio between them.
    """
    n = len(scores)
    if n == 0:
        return [], []
    gaps = [scores[i] - scores[i + 1] for i in range(n - 1)]
    tiers, breaks = [1], []
    tier, size = 1, 1
    for i, gap in enumerate(gaps):
        # The `window` gaps around this one, shifted inward at the list ends
        lo = max(0, min(i - window // 2, len(gaps) - window))
        hi = min(len(gaps), lo + window + 1)
        nearby = [gaps[j] for j in range(lo, hi) if j != i]
        local = max(median(nearby) if nearby else 0.0, min_median_gap)
        roomy = size >= min_size and n - (i + 1) >= min_size
        if gap > multiplier * local and (roomy or gap >= always_break_gap):
            breaks.append({"after_rank": i + 1, "gap": round(gap, 2),
                           "local_median": round(local, 2),
                           "ratio": round(gap / local, 1),
                           "big_gap": not roomy})
            tier += 1
            size = 0
        size += 1
        tiers.append(tier)
    return tiers, breaks
