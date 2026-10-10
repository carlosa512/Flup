"""Score a stat line (projected or actual) with the league's own settings.

Returns the total and every piece of it, so the site can show the math:
    rec_yd 65.4 x 0.1 = 6.54
"""


def _bracket_table(scoring, prefix):
    """Settings like pts_allow_7_13 or pts_allow_35p -> sorted
    (bracket midpoint, points) pairs."""
    table = []
    for key, pts in scoring.items():
        if not key.startswith(prefix + "_") or not isinstance(pts, (int, float)):
            continue
        rng = key[len(prefix) + 1:]
        try:
            if rng.endswith("p"):
                mid = float(rng[:-1]) + (5 if prefix == "pts_allow" else 50)
            elif "_" in rng:
                lo, hi = (float(x) for x in rng.split("_"))
                mid = (lo + hi) / 2
            else:
                mid = float(rng)
        except ValueError:
            continue
        table.append((mid, pts))
    return sorted(table)


def _interpolate(table, x):
    if not table:
        return 0.0
    if x <= table[0][0]:
        return table[0][1]
    if x >= table[-1][0]:
        return table[-1][1]
    for (x0, y0), (x1, y1) in zip(table, table[1:]):
        if x0 <= x <= x1:
            return y0 if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return 0.0


def score_line(stats, position, scoring, smooth_def_brackets=False):
    """(total points, parts). Each part is [stat, value, weight, points].

    Projections give a defense's average points allowed plus a 0/1 flag for
    the bracket it lands in. With smooth_def_brackets the flag is replaced by
    a blend between bracket midpoints (part weight is None for that line).
    """
    stats = dict(stats or {})
    parts = []
    raw_total = 0.0  # unrounded, so the total isn't off by rounding each part

    # Missed field goals: projections only give them by distance
    if "fgmiss" in scoring and "fgmiss" not in stats:
        missed = sum(v for k, v in stats.items()
                     if k.startswith("fgmiss_") and isinstance(v, (int, float)))
        if missed:
            stats["fgmiss"] = missed

    smoothed = set()
    if position == "DEF" and smooth_def_brackets:
        for prefix in ("pts_allow", "yds_allow"):
            avg = stats.get(prefix)
            table = _bracket_table(scoring, prefix)
            if isinstance(avg, (int, float)) and table:
                smoothed.add(prefix)
                pts = _interpolate(table, avg)
                raw_total += pts
                parts.append([prefix, round(avg, 2), None, round(pts, 2)])

    for key, value in stats.items():
        weight = scoring.get(key)
        if not isinstance(weight, (int, float)) or not isinstance(value, (int, float)):
            continue
        if weight == 0 or value == 0:
            continue
        if any(key.startswith(p + "_") for p in smoothed):
            continue
        raw_total += value * weight
        parts.append([key, round(value, 2), weight, round(value * weight, 2)])

    # Position catch bonus (TE premium). Sleeper usually puts bonus_rec_te in
    # the stat line already; only derive it from catches when it's missing,
    # otherwise the premium counts twice.
    bonus_key = f"bonus_rec_{position.lower()}"
    bonus = scoring.get(bonus_key)
    if isinstance(bonus, (int, float)) and bonus and bonus_key not in stats:
        catches = stats.get("rec") or 0
        if catches:
            raw_total += catches * bonus
            parts.append([bonus_key, round(catches, 2), bonus, round(catches * bonus, 2)])

    parts.sort(key=lambda p: -abs(p[3]))
    return round(raw_total, 2), parts
