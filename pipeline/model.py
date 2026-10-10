"""My Score: this week's projection (your scoring) blended with the expert
consensus, plus small capped adjustments, then injury.

Every adjustment comes back as {key, label, pts, why} so the site can show
exactly what moved a player and by how much. All weights and caps live in
settings.toml.
"""

from statistics import mean, median, pstdev

from .history import percentile, points_allowed

OUT_STATUSES = {"Out", "IR", "PUP", "Sus", "NA", "DNR", "COV"}


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
    """Last few games' share of snaps/targets/carries vs the whole season."""
    metrics = USAGE_METRICS.get(pos)
    if not metrics or len(season_games) < cfg["min_games"]:
        return None
    recent = season_games[-cfg["recent_games"]:]
    trend, moves = 0.0, []
    for key, name, weight in metrics:
        whole = mean(g.get(key, 0) for g in season_games)
        lately = mean(g.get(key, 0) for g in recent)
        if whole < USAGE_MIN[key]:
            continue
        change = max(-0.5, min(0.5, lately / whole - 1))
        trend += weight * change
        moves.append((abs(change), name, lately, whole))
    if not moves:
        return None
    pts = _clamp(base * trend * cfg["weight"], cfg["cap"])
    _, name, lately, whole = max(moves)
    word = "up" if pts > 0 else "down"
    return _adj("usage", f"Usage {word}",  pts,
                f"{_pct(lately)} of team {name} in the last {len(recent)} games vs {_pct(whole)} this season")


def environment(p, base, avg_implied, opp_implied, cfg):
    """Vegas: implied team total vs this week's average, plus game script."""
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
        if pos == "RB":
            pts += -spread * cfg["spread_rb"]
        elif pos in ("WR", "TE"):
            pts += spread * cfg["spread_pass"]
        if pos in ("RB", "WR", "TE") and abs(spread) >= 3:
            why += f", {'favored' if spread < 0 else 'underdog'} by {abs(spread):g}"
    pts = _clamp(pts, cfg["cap"])
    return _adj("environment", "Good game" if pts > 0 else "Tough game", pts, why)


def matchup(p, base, hist, cfg):
    """Points the opponent allows to this position vs the league average,
    shrunk toward average until the opponent has a few games of data."""
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
    """Interception habit vs what the projection assumes, plus a small
    bump for QBs whose points lean on rushing (a steadier floor)."""
    if not games:
        return None
    att = sum(g.get("pass_att", 0) for g in games)
    ints = sum(g.get("pass_int", 0) for g in games)
    rate = (ints + cfg["shrink_attempts"] * league_int_rate) / (att + cfg["shrink_attempts"])
    pts, why = 0.0, []
    proj_att, proj_int = proj_stats.get("pass_att") or 0, proj_stats.get("pass_int") or 0
    int_weight = scoring.get("pass_int") or 0
    if proj_att and int_weight:
        int_pts = _clamp((rate * proj_att - proj_int) * int_weight * cfg["int_weight"], cfg["int_cap"])
        if abs(int_pts) >= 0.05:
            pts += int_pts
            why.append(f"throws picks on {rate * 100:.1f}% of passes (league {league_int_rate * 100:.1f}%)")
    total = sum(g["pts"] for g in games)
    rush = sum((g.get("rush_yd", 0) * (scoring.get("rush_yd") or 0))
               + (g.get("rush_td", 0) * (scoring.get("rush_td") or 0)) for g in games)
    share = rush / total if total > 0 else 0
    start, full = cfg["rush_share_start"], cfg["rush_share_full"]
    bonus = cfg["rush_bonus"] * max(0.0, min(1.0, (share - start) / (full - start)))
    if bonus >= 0.05:
        pts += bonus
        why.append(f"{_pct(share)} of his points come from running")
    if not why:
        return None
    label = "Rushing QB" if pts > 0 else "Turnover risk"
    return _adj("qb", label, pts, "; ".join(why).capitalize())


def returns(season_games, proj_stats, scoring, cfg):
    """Return men: kick return yards aren't in projections, so add them
    from recent games, plus a small bump for return-TD upside."""
    recent = season_games[-cfg["recent_games"]:]
    if not recent:
        return None
    per_game = mean(g.get("kr", 0) + g.get("pr", 0) for g in recent)
    if per_game < cfg["min_returns_per_game"]:
        return None
    kr_yd = mean(g.get("kr_yd", 0) for g in recent)
    pr_yd = mean(g.get("pr_yd", 0) for g in recent)
    pts, parts = cfg["bonus"], []
    if scoring.get("kr_yd") and "kr_yd" not in proj_stats and kr_yd:
        pts += kr_yd * scoring["kr_yd"]
        parts.append(f"{kr_yd:.0f} kick return yds")
    if scoring.get("pr_yd") and "pr_yd" not in proj_stats and pr_yd:
        pts += pr_yd * scoring["pr_yd"]
        parts.append(f"{pr_yd:.0f} punt return yds")
    why = (f"Averaging {' + '.join(parts)}/game lately (not in projections)" if parts
           else "Returns kicks or punts")
    return _adj("returns", "Return man", min(pts, cfg["cap"]), why + f", plus {cfg['bonus']:g} for return-TD upside")


def injury(status, detail, pre, cfg):
    if status == "Questionable":
        share = cfg["questionable"]
    elif status == "Doubtful":
        share = cfg["doubtful"]
    elif status in OUT_STATUSES:
        share = cfg["out"]
    else:
        return None
    why = f"{detail + ', ' if detail else ''}{round(share * 100)}% off"
    return _adj("injury", status, -max(pre, 0) * share, why)


# ---------- spread of outcomes ----------

def spread_ratios(games, floor_pct, ceiling_pct):
    """(floor/mean, ceiling/mean, sd/mean) of a player's weekly scores."""
    vals = [g["pts"] for g in games]
    if len(vals) < 2:
        return None
    m = mean(vals)
    if m < 1:
        return None
    return (percentile(vals, floor_pct) / m, percentile(vals, ceiling_pct) / m, pstdev(vals) / m)


def position_ratios(histories_by_pos, min_games, min_mean, floor_pct, ceiling_pct):
    """Typical floor/ceiling/sd ratios per position, from players with
    enough games: the fallback for rookies and thin histories."""
    out = {}
    for pos, histories in histories_by_pos.items():
        ratios = []
        for games in histories:
            if len(games) >= min_games and mean(g["pts"] for g in games) >= min_mean:
                r = spread_ratios(games, floor_pct, ceiling_pct)
                if r:
                    ratios.append(r)
        if ratios:
            out[pos] = tuple(median(r[i] for r in ratios) for i in range(3))
    return out


def outcome_range(score, games, pos_ratio, fc):
    """Floor, ceiling and sd scaled to this week's score. A player's own
    history counts more the more games he has."""
    shrink_games = fc["shrink_games"]
    own = spread_ratios(games, fc["floor_pct"], fc["ceiling_pct"])
    n = len(games) if own else 0
    if not pos_ratio and not own:
        return None
    if own and pos_ratio:
        r = tuple((n * a + shrink_games * b) / (n + shrink_games) for a, b in zip(own, pos_ratio))
    else:
        r = own or pos_ratio
    return {"floor": round(score * r[0], 1), "ceiling": round(score * r[1], 1),
            "sd": round(score * r[2], 2), "games": n}


# ---------- putting it together ----------

def my_score(p, proj_stats, cons, ctx):
    """p: player dict (proj, pos, team, opp, implied, spread, injury...).
    cons: {"pts", "rank", ...} or None. ctx: shared inputs for the week."""
    cfg = ctx["settings"]
    adj_cfg = cfg["adjust"]
    proj = p["proj"]
    if cons is None or cons.get("pts") is None:
        base, how = proj, "projection only (no consensus rank)"
    elif proj <= 0:
        base, how = cons["pts"], "consensus only (no projection)"
    else:
        wp, wc = cfg["blend"]["projection"], cfg["blend"]["consensus"]
        base = (wp * proj + wc * cons["pts"]) / (wp + wc)
        how = f"{round(wp / (wp + wc) * 100)}% projection, {round(wc / (wp + wc) * 100)}% consensus"

    season = ctx["season_games"](p["id"])
    recent_all = ctx["recent_games"](p["id"])
    small = [a for a in (
        usage(p["pos"], base, season, adj_cfg["usage"]),
        environment(p, base, ctx["avg_implied"], ctx["implied"].get(p.get("opp")), adj_cfg["environment"]),
        matchup(p, base, ctx["history"], adj_cfg["matchup"]),
        qb_style(base, recent_all, proj_stats, ctx["scoring"], ctx["league_int_rate"], adj_cfg["qb"])
        if p["pos"] == "QB" else None,
    ) if a and abs(a["pts"]) >= 0.05]
    # Combined cap: scale the small adjustments down together so they still add up
    total = sum(a["pts"] for a in small)
    cap = adj_cfg["total_cap"]
    if abs(total) > cap:
        for a in small:
            a["pts"] = round(a["pts"] * cap / abs(total), 2)
    adjustments = small
    if p["pos"] in ("RB", "WR", "TE"):
        ret = returns(season, proj_stats, ctx["scoring"], adj_cfg["returns"])
        if ret and ret["pts"] >= 0.05:
            adjustments.append(ret)
    pre = base + sum(a["pts"] for a in adjustments)
    inj = injury(p.get("injury"), p.get("injury_detail"), pre, adj_cfg["injury"])
    if inj:
        adjustments.append(inj)
    score = pre + (inj["pts"] if inj else 0)
    if p["pos"] != "DEF":
        score = max(score, 0.0)

    rng = outcome_range(score, recent_all, ctx["pos_ratios"].get(p["pos"]), cfg["floor_ceiling"])
    flag = p.get("injury") if p.get("injury") in OUT_STATUSES | {"Doubtful"} else ""
    return {
        "score": round(score, 2),
        "base": round(base, 2),
        "blend": how,
        "cons": None if cons is None else {"rank": cons["rank"], "pts": round(cons["pts"], 2)
                                           if cons.get("pts") is not None else None,
                                           "url": cons.get("url", "")},
        "adj": adjustments,
        "range": rng,
        "flag": flag,
    }
