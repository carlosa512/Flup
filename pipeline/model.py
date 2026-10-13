"""Predicted points (called "My Score" until 2026-10-13): this week's
projection (your scoring) blended with the expert consensus, plus small
capped adjustments, then injury.

Every adjustment comes back as {key, label, pts, why} so the site can show
exactly what moved a player and by how much. All weights and caps live in
settings.toml. Base, adjustments and score are rounded to 0.1 so the lines
on the card add up to the big number.
"""

from statistics import mean, median, pstdev

from .history import percentile, points_allowed

OUT_STATUSES = {"Out", "IR", "PUP", "Sus", "NA", "DNR", "COV"}
BACKUP_SNAP_SHARE = 0.25  # games below this share of snaps don't shape a starter's range


def _clamp(x, cap):
    return max(-cap, min(cap, x))


def _pct(x):
    return f"{round(x * 100)}%"


def _adj(key, label, pts, why):
    return {"key": key, "label": label, "pts": round(pts, 2), "why": why}


# ---------- adjustments (each returns an _adj dict or None) ----------

USAGE_METRICS = {
    "RB": [("snap_share", "snaps", 0.4), ("tgt_share", "targets", 0.3), ("rush_share", "carries", 0.3)],
    "WR": [("snap_share", "snaps", 0.5), ("tgt_share", "targets", 0.5)],
    "TE": [("snap_share", "snaps", 0.5), ("tgt_share", "targets", 0.5)],
}
USAGE_MIN = {"snap_share": 0.10, "tgt_share": 0.04, "rush_share": 0.05}


def usage(pos, base, season_games, cfg):
    """Last few games' share of snaps/targets/carries vs the whole season.
    Games missing a number (Sleeper sometimes skips snap counts) are left
    out of that number instead of counting as zero."""
    metrics = USAGE_METRICS.get(pos)
    if not metrics or len(season_games) < cfg["min_games"]:
        return None
    recent = season_games[-cfg["recent_games"]:]
    trend, moves = 0.0, []
    for key, name, weight in metrics:
        season_vals = [g[key] for g in season_games if key in g]
        recent_vals = [g[key] for g in recent if key in g]
        if len(season_vals) < cfg["min_games"] or len(recent_vals) < 2:
            continue
        whole, lately = mean(season_vals), mean(recent_vals)
        if whole < USAGE_MIN[key]:
            continue
        change = max(-0.5, min(0.5, lately / whole - 1))
        trend += weight * change
        moves.append((abs(change), name, lately, whole, len(recent_vals)))
    if not moves:
        return None
    pts = _clamp(base * trend * cfg["weight"], cfg["cap"])
    _, name, lately, whole, n = max(moves)
    return _adj("usage", f"Usage {'up' if pts > 0 else 'down'}", pts,
                f"{_pct(lately)} of team {name} in the last {n} games vs {_pct(whole)} this season")


def environment(p, base, avg_implied, opp_implied, cfg):
    """Vegas: implied team total vs this week's average, plus game script
    (favored teams run more late, trailing teams throw more)."""
    if p.get("implied") is None or not avg_implied:
        return None
    pos, spread = p["pos"], p.get("spread") or 0
    if pos == "DEF":
        if not opp_implied:
            return None
        pts = base * (avg_implied / opp_implied - 1) * cfg["weight"]
        why = f"{p['opp']} is implied for {opp_implied:.1f} pts (average team {avg_implied:.1f})"
    else:
        pts = base * (p["implied"] / avg_implied - 1) * cfg["weight"]
        why = f"{p['team']} is implied for {p['implied']:.1f} pts (average team {avg_implied:.1f})"
        script = 0.0
        if pos == "RB":
            script = -spread * cfg["spread_rb"]
        elif pos in ("WR", "TE"):
            script = spread * cfg["spread_pass"]
        if abs(script) >= 0.05:
            favored = spread < 0
            effect = (("more" if favored else "fewer") + " carries late") if pos == "RB" \
                else (("fewer" if favored else "more") + " passes late")
            why += f"; {'favored' if favored else 'underdog'} by {abs(spread):g}, so {effect}"
        pts += script
    pts = _clamp(pts, cfg["cap"])
    return _adj("environment", "Good game" if pts > 0 else "Tough game", pts, why)


def matchup(p, base, hist, cfg):
    """Points the opponent allows to this position vs the league average,
    shrunk toward average while the opponent has few games of data."""
    found = points_allowed(hist, p.get("opp"), p["pos"])
    if not found:
        return None
    allowed, n, league = found
    if league <= 0:
        return None
    ratio = 1 + (allowed / league - 1) * n / (n + cfg["shrink_games"])
    pts = _clamp(base * (ratio - 1) * cfg["weight"], cfg["cap"])
    if p["pos"] == "DEF":
        why = f"{p['opp']} gives up {allowed:.1f} pts/game to defenses (average {league:.1f})"
    else:
        why = f"{p['opp']} allows {allowed:.1f} pts/game to {p['pos']}s (average {league:.1f})"
    return _adj("matchup", "Good matchup" if pts > 0 else "Tough matchup", pts, why)


def qb_style(base, games, proj_stats, scoring, league_int_rate, cfg):
    """Penalty for QBs who throw picks above the league rate; small bonus
    for low-INT QBs whose points lean on running. From game logs."""
    if not games or base <= 0:
        return None
    att = sum(g.get("pass_att", 0) for g in games)
    ints = sum(g.get("pass_int", 0) for g in games)
    rate = (ints + cfg["shrink_attempts"] * league_int_rate) / (att + cfg["shrink_attempts"])
    if rate > league_int_rate:
        proj_att = proj_stats.get("pass_att") or (att / len(games))
        per_int = abs(scoring.get("pass_int") or 0)
        pts = -min((rate - league_int_rate) * proj_att * per_int * cfg["int_weight"], cfg["int_cap"])
        if pts > -0.05:
            return None
        return _adj("qb", "Turnover risk", pts,
                    f"Throws picks on {rate * 100:.1f}% of passes (league {league_int_rate * 100:.1f}%)")
    total = sum(g["pts"] for g in games)
    rush = sum(g.get("rush_yd", 0) * (scoring.get("rush_yd") or 0)
               + g.get("rush_td", 0) * (scoring.get("rush_td") or 0) for g in games)
    share = rush / total if total > 0 else 0
    start, full = cfg["rush_share_start"], cfg["rush_share_full"]
    bonus = cfg["rush_bonus"] * max(0.0, min(1.0, (share - start) / (full - start)))
    if bonus < 0.05:
        return None
    return _adj("qb", "Low-INT runner", bonus,
                f"{_pct(share)} of his points come from running, and he throws picks on "
                f"{rate * 100:.1f}% of passes (league {league_int_rate * 100:.1f}%)")


def returns(season_games, proj_stats, scoring, cfg):
    """Return men: a small bump for return-TD upside, plus recent return
    yards for any kind of return the projection leaves out."""
    recent = season_games[-cfg["recent_games"]:]
    if not recent:
        return None
    if mean(g.get("kr", 0) + g.get("pr", 0) for g in recent) < cfg["min_returns_per_game"]:
        return None
    pts, missing = cfg["bonus"], []
    for kind, label in (("kr", "kick"), ("pr", "punt")):
        yds = mean(g.get(f"{kind}_yd", 0) for g in recent)
        weight = scoring.get(f"{kind}_yd") or 0
        if weight and yds and f"{kind}_yd" not in proj_stats:
            pts += yds * weight
            missing.append(f"{yds:.0f} {label} return yds")
    why = ("Returns kicks or punts" if not missing else
           f"Averaging {' + '.join(missing)}/game lately (not in his projection)")
    return _adj("returns", "Return man", min(pts, cfg["cap"]),
                why + f", plus {cfg['bonus']:g} for return-TD upside")


def injury(status, detail, pre, cfg, consensus_part=0.0):
    """Questionable comes off the projection's part only: the experts'
    ranks already account for injury news. Doubtful and Out come off all."""
    if status == "Questionable":
        share, applies_to = cfg["questionable"], max(pre - consensus_part, 0)
    elif status == "Doubtful":
        share, applies_to = cfg["doubtful"], max(pre, 0)
    elif status in OUT_STATUSES:
        share, applies_to = cfg["out"], max(pre, 0)
    else:
        return None
    why = f"{detail + ', ' if detail else ''}{round(share * 100)}% off"
    return _adj("injury", status, -applies_to * share, why)


# ---------- spread of outcomes ----------

def spread_ratios(games, floor_pct, ceiling_pct, min_mean=1.0):
    """(floor/mean, ceiling/mean, sd/mean) of a player's weekly scores.
    Games in a backup role (low snap share) are left out, and a history
    averaging under min_mean isn't trusted."""
    vals = [g["pts"] for g in games
            if g.get("snap_share") is None or g["snap_share"] >= BACKUP_SNAP_SHARE]
    if len(vals) < 2:
        return None
    m = mean(vals)
    if m < max(min_mean, 1.0):
        return None
    return (percentile(vals, floor_pct) / m, percentile(vals, ceiling_pct) / m, pstdev(vals) / m), len(vals)


def position_ratios(histories_by_pos, min_games, min_mean, floor_pct, ceiling_pct):
    """Typical floor/ceiling/sd ratios per position, from players with
    enough games: the fallback for rookies and thin histories."""
    out = {}
    for pos, histories in histories_by_pos.items():
        ratios = []
        for games in histories:
            found = spread_ratios(games, floor_pct, ceiling_pct, min_mean)
            if found and found[1] >= min_games:
                ratios.append(found[0])
        if ratios:
            out[pos] = tuple(median(r[i] for r in ratios) for i in range(3))
    return out


def outcome_range(score, games, pos_ratio, fc, min_mean=1.0):
    """Floor, ceiling and sd scaled to this week's score. A player's own
    history counts more the more games he has (half at shrink_games)."""
    found = spread_ratios(games, fc["floor_pct"], fc["ceiling_pct"], min_mean)
    own, n = found if found else (None, 0)
    if not pos_ratio and not own:
        return None
    if own and pos_ratio:
        k = fc["shrink_games"]
        r = tuple((n * a + k * b) / (n + k) for a, b in zip(own, pos_ratio))
    else:
        r = own or pos_ratio
    return {"floor": round(score * r[0], 1), "ceiling": round(score * r[1], 1),
            "sd": round(score * r[2], 2), "games": n}


# ---------- putting it together ----------

def _empty(note, cons=None):
    return {"score": 0.0, "base": 0.0, "blend": note, "note": note, "cons": cons,
            "adj": [], "range": None, "flag": ""}


def my_score(p, proj_stats, cons, ctx):
    """p: player dict (proj, pos, team, opp, implied, spread, injury...).
    cons: {"pts", "rank", ...} or None. ctx: shared inputs for the week."""
    cfg = ctx["settings"]
    adj_cfg = cfg["adjust"]
    proj = p["proj"]
    cons_out = None if cons is None else {
        "rank": cons["rank"], "pts": None if cons.get("pts") is None else round(cons["pts"], 1),
        "url": cons.get("url", "")}
    flag = p.get("injury") if p.get("injury") in OUT_STATUSES | {"Doubtful"} else ""
    if not p.get("opp"):
        return dict(_empty("No game this week", cons_out), flag=flag)
    has_cons = cons is not None and cons.get("pts") is not None
    wp, wc = cfg["blend"]["projection"], cfg["blend"]["consensus"]
    consensus_part = 0.0
    if not has_cons:
        if proj <= 0:
            return dict(_empty("No projection this week", cons_out), flag=flag)
        base, how = proj, "projection only (no consensus rank)"
    elif proj <= 0:
        base, how = cons["pts"], "consensus only (no projection)"
        consensus_part = base
    else:
        consensus_part = wc * cons["pts"] / (wp + wc)
        base = wp * proj / (wp + wc) + consensus_part
        how = f"{round(wp / (wp + wc) * 100)}% projection, {round(wc / (wp + wc) * 100)}% consensus"
    base = round(base, 1)

    season = ctx["season_games"](p["id"])
    recent_all = ctx["recent_games"](p["id"])
    small = [a for a in (
        usage(p["pos"], base, season, adj_cfg["usage"]),
        environment(p, base, ctx["avg_implied"], ctx["implied"].get(p.get("opp")), adj_cfg["environment"]),
        matchup(p, base, ctx["history"], adj_cfg["matchup"]),
        qb_style(base, recent_all, proj_stats, ctx["scoring"], ctx["league_int_rate"], adj_cfg["qb"])
        if p["pos"] == "QB" else None,
    ) if a]
    # Combined cap: scale the small adjustments down together so they still add up
    total = sum(a["pts"] for a in small)
    cap = adj_cfg["total_cap"]
    if abs(total) > cap:
        for a in small:
            a["pts"] *= cap / abs(total)
    adjustments = small
    if p["pos"] in ("RB", "WR", "TE"):
        ret = returns(season, proj_stats, ctx["scoring"], adj_cfg["returns"])
        if ret:
            adjustments.append(ret)
    for a in adjustments:
        a["pts"] = round(a["pts"], 1)
    adjustments = [a for a in adjustments if a["pts"]]
    pre = round(base + sum(a["pts"] for a in adjustments), 1)
    inj = injury(p.get("injury"), p.get("injury_detail"), pre, adj_cfg["injury"], consensus_part)
    if inj:
        inj["pts"] = round(inj["pts"], 1)
        if inj["pts"]:
            adjustments.append(inj)
    score = round(pre + (inj["pts"] if inj else 0), 1)
    if p["pos"] != "DEF":
        score = max(score, 0.0)

    # A likely scratch's range is shown as "if he plays", from the healthy score
    range_from = pre if flag else score
    rng = outcome_range(range_from, recent_all, ctx["pos_ratios"].get(p["pos"]),
                        cfg["floor_ceiling"], ctx.get("relevant_mean", {}).get(p["pos"], 1.0))
    if rng and flag:
        rng["if_plays"] = True
    return {"score": score, "base": base, "blend": how, "note": "", "cons": cons_out,
            "adj": adjustments, "range": rng, "flag": flag}
