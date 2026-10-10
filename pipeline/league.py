"""Who owns whom in the league, this week's matchup, and the settings check."""

import math


def context(league, users, rosters, matchups, username, my_user_id=None):
    """Team names, player -> roster, my roster id and my opponent's."""
    names, mine_ids = {}, {my_user_id} if my_user_id else set()
    for u in users:
        meta = u.get("metadata") or {}
        names[u["user_id"]] = (meta.get("team_name") or "").strip() or u.get("display_name") or "Team"
        if (u.get("display_name") or "").lower() == username.lower():
            mine_ids.add(u["user_id"])
    display = {u["user_id"]: u.get("display_name") or "" for u in users}

    teams, owners, reserve, my_rid = {}, {}, {}, None
    for r in rosters:
        rid = r.get("roster_id")
        if rid is None:
            continue
        s = r.get("settings") or {}
        teams[rid] = {
            "name": names.get(r.get("owner_id"), f"Team {rid}"),
            "user": display.get(r.get("owner_id"), ""),
            "wins": s.get("wins", 0), "losses": s.get("losses", 0), "ties": s.get("ties", 0),
            "points_for": round((s.get("fpts") or 0) + (s.get("fpts_decimal") or 0) / 100, 2),
            "faab_left": (league.get("settings") or {}).get("waiver_budget", 0) - (s.get("waiver_budget_used") or 0),
        }
        if ({r.get("owner_id")} | set(r.get("co_owners") or [])) & mine_ids:
            my_rid = rid
        for pid in r.get("players") or []:
            owners[str(pid)] = rid
        reserve[rid] = [str(pid) for pid in r.get("reserve") or []]

    groups, lineups = {}, {}
    for m in matchups:
        if m.get("matchup_id") is not None:
            groups.setdefault(m["matchup_id"], []).append(m.get("roster_id"))
        # Starters in roster_positions order ("0" = empty slot) and this
        # week's points so far for everyone on the roster
        lineups[m.get("roster_id")] = {
            "starters": [str(pid) for pid in m.get("starters") or []],
            "points": {str(k): v for k, v in (m.get("players_points") or {}).items()
                       if isinstance(v, (int, float))}}
    pairs = {}
    for ids in groups.values():
        if len(ids) == 2:
            pairs[ids[0]], pairs[ids[1]] = ids[1], ids[0]
    return {"teams": teams, "owners": owners, "reserve": reserve, "lineups": lineups,
            "my_rid": my_rid, "opp_rid": pairs.get(my_rid), "pairs": pairs}


def playoff_weeks(settings):
    """(first, last) playoff week. playoff_round_type: 0 = one week per
    round, 1 = two-week final, 2 = two weeks per round."""
    start, teams = settings.get("playoff_week_start"), settings.get("playoff_teams")
    if not start or not teams:
        return start, None
    rounds = math.ceil(math.log2(teams))
    kind = settings.get("playoff_round_type", 0)
    length = {0: rounds, 1: rounds + 1, 2: rounds * 2}.get(kind, rounds)
    return start, start + length - 1


def sanity(league, expect):
    """Compare what you know about the league with what Sleeper reports."""
    scoring = league.get("scoring_settings") or {}
    settings = league.get("settings") or {}
    slots = league.get("roster_positions") or []
    first, last = playoff_weeks(settings)
    actual = {
        "teams": league.get("total_rosters"),
        "rec": scoring.get("rec"),
        "bonus_rec_te": scoring.get("bonus_rec_te"),
        "pass_td": scoring.get("pass_td"),
        "pass_int": scoring.get("pass_int"),
        "kr_yd": scoring.get("kr_yd"),
        "pr_yd": scoring.get("pr_yd"),
        "rb_slots": slots.count("RB"),
        "flex_slots": slots.count("FLEX"),
        "playoff_week_start": first,
        "playoff_week_end": last,
        "playoff_teams": settings.get("playoff_teams"),
    }
    labels = {
        "teams": "Teams", "rec": "Points per catch", "bonus_rec_te": "TE bonus per catch",
        "pass_td": "Passing TD", "pass_int": "Interception", "kr_yd": "Kick return yard",
        "pr_yd": "Punt return yard", "rb_slots": "RB starters", "flex_slots": "FLEX starters",
        "playoff_week_start": "Playoffs start", "playoff_week_end": "Playoffs end",
        "playoff_teams": "Playoff teams",
    }
    checks = []
    for key, want in expect.items():
        got = actual.get(key)
        ok = got is not None and float(got) == float(want)
        checks.append({"key": key, "label": labels.get(key, key), "expected": want,
                       "actual": got, "ok": ok})
    return checks
