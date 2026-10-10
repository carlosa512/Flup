"""Prove the scoring engine: rescore a finished week's real stat lines and
compare with the points Sleeper officially awarded in the league."""

from .scoring import score_line


def rescore_check(stat_rows, matchups, scoring, tolerance=0.011):
    official = {}
    for m in matchups:
        for pid, pts in (m.get("players_points") or {}).items():
            official[str(pid)] = pts
    lines = {str(r.get("player_id")): r for r in stat_rows}

    checked, misses = 0, []
    for pid, want in official.items():
        row = lines.get(pid)
        if row is None:
            continue  # no stat line: didn't play
        pos = (row.get("player") or {}).get("position") or ""
        got, _ = score_line(row.get("stats") or {}, pos, scoring)
        checked += 1
        if abs(got - want) > tolerance:
            p = row.get("player") or {}
            misses.append({"player_id": pid, "name": f"{p.get('first_name', '')} {p.get('last_name', '')}".strip(),
                           "pos": pos, "official": want, "ours": got, "diff": round(got - want, 2)})
    misses.sort(key=lambda x: -abs(x["diff"]))
    return {"checked": checked, "matched": checked - len(misses), "misses": misses[:10]}
