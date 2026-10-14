"""Weekly history in your scoring, from Sleeper's actual stat lines.

Used for floor/ceiling, usage trends, return-man detection, QB tendencies
and points each defense allows by position. The same scoring engine that
matches Sleeper's official points (see the checks) scores every game.
"""

from collections import defaultdict
from statistics import mean

from .scoring import score_line

POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF")
MIN_TEAM_AIR = 50  # team air yards on catches; under this a game's air share is noise
KEEP = ("off_snp", "tm_off_snp", "rec_tgt", "rush_att", "rec_air_yd", "kr", "kr_yd",
        "pr", "pr_yd", "pass_att", "pass_int", "rush_yd", "rush_td")


def build(weeks, scoring, current_season):
    """weeks: [(season, week, stat rows)] -> history dict.

    games[pid]   list of played games, oldest first, each with its points in
                 your scoring, raw usage numbers and shares of team volume
                 (snaps, targets, carries, and WOPR from targets + air yards)
    allowed[team][pos]  {week: points} the team's defense gave up to that
                 position this season (all players at the position summed)
    """
    games = defaultdict(list)
    team_tgt, team_rush, team_air = defaultdict(float), defaultdict(float), defaultdict(float)
    allowed = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    for season, week, rows in sorted(weeks, key=lambda w: (str(w[0]), w[1])):
        for r in rows:
            pos = (r.get("player") or {}).get("position")
            stats = r.get("stats") or {}
            if pos not in POSITIONS or (stats.get("gp") or 0) <= 0:
                continue
            team, opp = r.get("team"), r.get("opponent")
            pts, _ = score_line(stats, pos, scoring)
            game = {"season": str(season), "week": week, "team": team, "opp": opp,
                    "pts": pts, "pos": pos}
            for k in KEEP:
                if isinstance(stats.get(k), (int, float)):  # real zeros kept
                    game[k] = stats[k]
            games[str(r.get("player_id"))].append(game)
            key = (str(season), week, team)
            team_tgt[key] += stats.get("rec_tgt") or 0
            team_rush[key] += stats.get("rush_att") or 0
            team_air[key] += stats.get("rec_air_yd") or 0
            if str(season) == str(current_season) and opp:
                allowed[opp][pos][week] += pts
    for player_games in games.values():
        for g in player_games:
            key = (g["season"], g["week"], g["team"])
            # Only when his own snap count exists: kickers (and some weeks of
            # data) have a team count but no player count, which isn't zero
            if g.get("tm_off_snp") and "off_snp" in g:
                g["snap_share"] = g["off_snp"] / g["tm_off_snp"]
            if team_tgt[key]:
                g["tgt_share"] = (g.get("rec_tgt") or 0) / team_tgt[key]
            if team_rush[key]:
                g["rush_share"] = (g.get("rush_att") or 0) / team_rush[key]
            # WOPR-style: 1.5 x target share + 0.7 x air yards share (how much
            # of the passing game runs through him). Sleeper's air yards count
            # catches only and go negative on screens, so the share is kept to
            # 0-100% and a game with a tiny team total (under MIN_TEAM_AIR)
            # is skipped: one such game made a share of 250%.
            if team_tgt[key] and team_air[key] >= MIN_TEAM_AIR:
                air = max(0.0, min(1.0, (g.get("rec_air_yd") or 0) / team_air[key]))
                g["wopr"] = 1.5 * g["tgt_share"] + 0.7 * air
    return {"games": games, "allowed": allowed, "current": str(current_season)}


def points_allowed(hist, opp, pos):
    """(avg points opp's defense allows to pos per game, games, league avg)."""
    per_team = {}
    for team, by_pos in hist["allowed"].items():
        weeks = by_pos.get(pos) or {}
        if weeks:
            per_team[team] = (mean(weeks.values()), len(weeks))
    if not per_team or opp not in per_team:
        return None
    league = mean(v for v, _ in per_team.values())
    value, n = per_team[opp]
    return value, n, league


def this_season(hist, pid):
    return [g for g in hist["games"].get(pid, []) if g["season"] == hist["current"]]


def percentile(values, q):
    """Linear-interpolated percentile, q in 0-100."""
    s = sorted(values)
    if not s:
        return None
    x = (len(s) - 1) * q / 100
    i = int(x)
    return s[i] if i + 1 >= len(s) else s[i] + (s[i + 1] - s[i]) * (x - i)
