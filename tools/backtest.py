#!/usr/bin/env python3
"""Backtest: would nflverse stats (EPA, CPOE, WOPR...) make Predicted
points more accurate?

Dev tool, standard library only. For each finished week of a season it
rebuilds Predicted the way the site does, from what was known before that
week: Sleeper's projection for the week, rescored in the league's scoring
(the base: there's no history of FantasyPros' ranks, so the base is the
projection alone, as on the site before FantasyPros posts a week), plus
the current adjustments (usage, Vegas game environment from nflverse's
closing lines, matchup, QB habits, return men) and floor/ceiling. Injury
status is left out: Sleeper's player info is today's, not that week's.

Then each candidate stat, worked out from the weeks before, is tested
against what really happened:
- accuracy: fit "points per standard deviation of the stat" on half the
  season, apply it (capped like the other adjustments) to the other half,
  and see whether the average miss gets smaller, both ways round;
- start/sit: same-position pairs predicted within the close-call gap
  (1.5 pts); how often the higher one really scored more;
- boom/bust: how well the stat picks out big games (1.5x the prediction
  or more) and duds (half or less), next to the current Boom/Steady
  ratios (AUC: 0.5 = no better than a coin flip).
It also checks the current adjustments: a slope near 1 means one is the
right size, near 0 means it doesn't help.

    python3 tools/backtest.py SNAP_DIR NFLVERSE_DIR [--season 2025] [--out FILE]

SNAP_DIR is the dev-snapshots branch (sleeper/league.json,
stats_<season>_<w>_all.json.gz, proj_<season>_<w>_all.json.gz; this
season's stats are stats_<w>_all.json.gz). NFLVERSE_DIR holds
stats_player_week_<season>.csv.gz and stats_team_week_<season>.csv.gz
(github.com/nflverse/nflverse-data releases, CC-BY 4.0), nfldata's
games.csv and DynastyProcess's db_playerids.csv.
"""

import argparse
import csv
import gzip
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean, pstdev

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline import history, lineup, model  # noqa: E402
from pipeline.build import RELEVANT_MEAN, load_settings, player_rows  # noqa: E402
from pipeline.scoring import score_line  # noqa: E402

TEAM = {"LA": "LAR"}  # nflverse -> Sleeper
FIRST_WEEK = 4        # weeks before this have too few games behind them
SPLIT = 11            # fold A: weeks FIRST_WEEK-SPLIT, fold B: the rest
CAP = 1.5             # the most a new adjustment could move a player (as the others)
CLOSE = 1.5           # close-call gap
MIN_PROJ = {"QB": 8, "RB": 4, "WR": 4, "TE": 3, "K": 3, "DEF": 3}


def team(t):
    return TEAM.get(t, t)


def read_gz_json(path):
    return json.loads(gzip.decompress(path.read_bytes())) if path.exists() else None


def sleeper_week(snap, kind, season, week, current):
    found = read_gz_json(snap / f"sleeper/{kind}_{season}_{week}_all.json.gz")
    if found is None and kind == "stats" and str(season) == str(current):
        found = read_gz_json(snap / f"sleeper/stats_{week}_all.json.gz")
    return found


def nfl_games(rows, season, week):
    """nfldata games.csv -> the site's per-team game info (espn.by_team).
    spread_line is the home team's margin (positive = home favored); the
    site's spread is a team's own line (negative = favored)."""
    out = {}
    for r in rows:
        if r["season"] != str(season) or r["game_type"] != "REG" or int(r["week"]) != week:
            continue
        try:
            line, total = float(r["spread_line"]), float(r["total_line"])
        except ValueError:
            line = total = None
        for me, opp, home in ((r["home_team"], r["away_team"], True), (r["away_team"], r["home_team"], False)):
            spread = None if line is None else (-line if home else line)
            implied = None if spread is None else round(total / 2 - spread / 2, 2)
            out[team(me)] = {"opp": team(opp), "home": home, "kickoff": None, "status": "STATUS_FINAL",
                             "spread": spread, "total": total, "implied": implied}
    return out


def return_points(stats, scoring, projected=False):
    pts = 0.0
    for kind in ("kr", "pr"):
        yds = stats.get(f"{kind}_yd")
        if yds is None and projected:
            yds = stats.get(f"def_{kind}_yd")
        pts += (yds or 0) * (scoring.get(f"{kind}_yd") or 0)
    return pts


# ---------- rebuilding Predicted week by week ----------

def predictions(snap, settings, scoring, season, games_csv, current):
    stats = {w: sleeper_week(snap, "stats", season, w, current) for w in range(1, 19)}
    stats = {w: rows for w, rows in stats.items() if rows}
    prev = str(int(season) - 1)
    prev_weeks = [(prev, w, rows) for w in range(1, 19)
                  if (rows := sleeper_week(snap, "stats", prev, w, current))]
    fc, labels_cfg = settings["floor_ceiling"], settings.get("labels", {"boom": 1.05, "steady": 1.10})
    pcts = (fc["floor_pct"], fc["ceiling_pct"])
    no_league = {"owners": {}, "my_rid": None, "opp_rid": None}
    out = []
    for week in sorted(stats):
        proj_rows = sleeper_week(snap, "proj", season, week, current)
        if not proj_rows:
            continue
        hist = history.build(prev_weeks + [(season, w, stats[w]) for w in stats if w < week], scoring, season)
        games = nfl_games(games_csv, season, week)

        def season_games(pid):
            return [g for g in hist["games"].get(pid, []) if g["season"] == str(season)]

        def recent_games(pid):
            gs = hist["games"].get(pid, [])
            last = [g for g in gs if g["season"] != str(season)][-fc["last_season_games"]:]
            return last + [g for g in gs if g["season"] == str(season)]
        qb_games = [g for gs in hist["games"].values() for g in gs if g["pos"] == "QB"]
        att = sum(g.get("pass_att", 0) for g in qb_games)
        implied = {t: g["implied"] for t, g in games.items() if g.get("implied") is not None}
        by_pos_hist = {}
        for pid, gs in hist["games"].items():
            if gs:
                by_pos_hist.setdefault(gs[-1]["pos"], []).append(recent_games(pid))
        ctx = {
            "relevant_mean": RELEVANT_MEAN, "settings": settings, "scoring": scoring, "history": hist,
            "season_games": season_games, "recent_games": recent_games, "implied": implied,
            "avg_implied": sum(implied.values()) / len(implied) if implied else None,
            "league_int_rate": sum(g.get("pass_int", 0) for g in qb_games) / att if att else 0.022,
            "pos_ratios": {pos: model.position_ratios({pos: hs}, fc["shrink_games"], RELEVANT_MEAN.get(pos, 5),
                                                      fc["floor_pct"], fc["ceiling_pct"]).get(pos)
                           for pos, hs in by_pos_hist.items()},
        }
        actual, returned = {}, {}
        for r in stats[week]:
            pos, s = (r.get("player") or {}).get("position"), r.get("stats") or {}
            if pos and (s.get("gp") or 0) >= 1:
                actual[str(r.get("player_id"))] = score_line(s, pos, scoring)[0]
                returned[str(r.get("player_id"))] = return_points(s, scoring)
        by_pos = defaultdict(list)
        for r in proj_rows:
            by_pos[(r.get("player") or {}).get("position")].append(r)
        smooth = settings.get("scoring", {}).get("smooth_def_brackets", True)
        for pos in MIN_PROJ:
            players, raw = player_rows(by_pos.get(pos, []), pos, scoring, no_league, games, smooth, {})
            for p in players:
                p["injury"], p["injury_detail"] = "", ""  # today's status, not that week's
                p.update(model.my_score(p, raw.get(p["id"], {}), None, ctx))
                if p["note"] or p["proj"] < MIN_PROJ[pos]:
                    continue
                rng = p["range"] or {}
                out.append({
                    "week": week, "id": p["id"], "name": p["name"], "pos": pos, "team": p["team"],
                    "opp": p["opp"], "proj": p["proj"], "score": p["score"],
                    "adj": {a["key"]: a["pts"] for a in p["adj"]},
                    "floor": rng.get("floor"), "ceiling": rng.get("ceiling"), "sd": rng.get("sd"),
                    # return points in his projection (kick returns are filed
                    # under def_kr_yd, some punt returns under def_pr_yd) and in the game
                    "ret_proj": return_points(raw.get(p["id"], {}), scoring, projected=True),
                    "ret_real": returned.get(p["id"]),
                    "label": lineup.label(p, ctx["pos_ratios"], labels_cfg, pcts, fc.get("stretch", 1.0)),
                    "actual": actual.get(p["id"]),
                })
        print(f"  week {week}: {sum(1 for r in out if r['week'] == week)} players", file=sys.stderr)
    return out


# ---------- nflverse stats, from the weeks before ----------

def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def nflverse_features(nv_dir, season, ids):
    """(player features, defense features): functions (id or team, week) ->
    {name: value} from that season's games before the week."""
    g2s = {}
    for r in csv.DictReader(open(nv_dir / "db_playerids.csv", encoding="utf-8")):
        if r.get("gsis_id") and r.get("sleeper_id") not in (None, "", "NA"):
            g2s[r["gsis_id"]] = r["sleeper_id"]
    games = defaultdict(dict)  # sleeper id -> week -> row
    with gzip.open(nv_dir / f"stats_player_week_{season}.csv.gz", "rt", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            sid = g2s.get(r["player_id"])
            if sid and r["season_type"] == "REG" and sid in ids:
                games[sid][int(r["week"])] = r
    teams = []
    with gzip.open(nv_dir / f"stats_team_week_{season}.csv.gz", "rt", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["season_type"] == "REG":
                teams.append(r)

    def total(rows, key):
        return sum(num(r.get(key)) or 0.0 for r in rows)

    def player(sid, week):
        rows = [r for w, r in sorted(games.get(sid, {}).items()) if w < week]
        if len(rows) < 3:
            return {}
        f = {}
        tgt = total(rows, "targets")
        if tgt >= 10:
            def avg(key, rs):
                vals = [num(r[key]) for r in rs if num(r.get(key)) is not None]
                return mean(vals) if vals else None
            w_all, w_last = avg("wopr", rows), avg("wopr", rows[-3:])
            f["wopr"] = w_all
            if w_all is not None and w_last is not None:
                f["wopr_trend"] = w_last - w_all
            f["air_share"] = avg("air_yards_share", rows)
            f["rec_epa_tgt"] = total(rows, "receiving_epa") / tgt
            f["adot"] = total(rows, "receiving_air_yards") / tgt
            air = total(rows, "receiving_air_yards")
            if air > 0:
                f["racr"] = total(rows, "receiving_yards") / air
        car = total(rows, "carries")
        if car >= 15:
            f["rush_epa_car"] = total(rows, "rushing_epa") / car
        drop = total(rows, "attempts") + total(rows, "sacks_suffered")
        if drop >= 50:
            f["pass_epa_db"] = total(rows, "passing_epa") / drop
            att = total(rows, "attempts")
            cp = [(num(r["passing_cpoe"]), num(r["attempts"]) or 0) for r in rows if num(r.get("passing_cpoe")) is not None]
            if cp and att:
                f["cpoe"] = sum(c * a for c, a in cp) / sum(a for _, a in cp)
        f["epa_game"] = sum(total(rows, k) for k in ("passing_epa", "rushing_epa", "receiving_epa")) / len(rows)
        return f

    def rate(rows, epa_keys, play_keys):
        plays = sum(total(rows, k) for k in play_keys)
        return (sum(total(rows, k) for k in epa_keys) / plays, len(rows)) if plays else (None, 0)

    def defense(abbr, week):
        """What abbr's defense allows (offenses facing it) and what its
        offense does, per play, vs the league, shrunk like the matchup
        adjustment (half at 4 games)."""
        before = [r for r in teams if int(r["week"]) < week]
        if not before:
            return {}
        f = {}
        for name, epa, plays, side in (
                ("def_pass_epa", ["passing_epa"], ["attempts", "sacks_suffered"], "opponent_team"),
                ("def_rush_epa", ["rushing_epa"], ["carries"], "opponent_team"),
                ("off_epa", ["passing_epa", "rushing_epa"], ["attempts", "sacks_suffered", "carries"], "team")):
            mine, n = rate([r for r in before if team(r[side]) == abbr], epa, plays)
            league, _ = rate(before, epa, plays)
            if mine is not None and league is not None:
                f[name] = (mine - league) * n / (n + 4)
        return f

    return player, defense


# Which stats to try for which positions: (name, where it comes from)
CANDIDATES = {
    "QB": [("pass_epa_db", "player"), ("cpoe", "player"), ("rush_epa_car", "player"),
           ("epa_game", "player"), ("def_pass_epa", "opp")],
    "RB": [("rush_epa_car", "player"), ("wopr", "player"), ("wopr_trend", "player"),
           ("rec_epa_tgt", "player"), ("epa_game", "player"), ("def_rush_epa", "opp"),
           ("def_pass_epa", "opp")],
    "WR": [("wopr", "player"), ("wopr_trend", "player"), ("air_share", "player"),
           ("rec_epa_tgt", "player"), ("adot", "player"), ("racr", "player"),
           ("epa_game", "player"), ("def_pass_epa", "opp"), ("qb_pass_epa", "team")],
    "TE": [("wopr", "player"), ("wopr_trend", "player"), ("air_share", "player"),
           ("rec_epa_tgt", "player"), ("adot", "player"), ("racr", "player"),
           ("epa_game", "player"), ("def_pass_epa", "opp"), ("qb_pass_epa", "team")],
    "DEF": [("opp_off_epa", "opp")],
    "K": [("own_off_epa", "team")],
}


def attach(rows, player, defense):
    """Each row gets the candidate stats known before its week."""
    qb_of = {}  # (team, week) -> the QB with the most projected points: his pass EPA
    for r in rows:
        if r["pos"] == "QB" and r["proj"] > qb_of.get((r["team"], r["week"]), (None, -1))[1]:
            qb_of[(r["team"], r["week"])] = (r["id"], r["proj"])
    for r in rows:
        f = dict(player(r["id"], r["week"])) if r["pos"] not in ("DEF", "K") else {}
        opp, own = defense(r["opp"], r["week"]), defense(r["team"], r["week"])
        f["def_pass_epa"], f["def_rush_epa"] = opp.get("def_pass_epa"), opp.get("def_rush_epa")
        f["opp_off_epa"], f["own_off_epa"] = opp.get("off_epa"), own.get("off_epa")
        qb = qb_of.get((r["team"], r["week"]))
        f["qb_pass_epa"] = player(qb[0], r["week"]).get("pass_epa_db") if qb else None
        r["f"] = {k: v for k, v in f.items() if v is not None}


# ---------- measuring ----------

def mae(xs):
    return mean(abs(x) for x in xs) if xs else float("nan")


def corr(xs, ys):
    if len(xs) < 3:
        return float("nan")
    mx, my = mean(xs), mean(ys)
    sx, sy = pstdev(xs), pstdev(ys)
    if not sx or not sy:
        return float("nan")
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (len(xs) * sx * sy)


def auc(values, hits):
    """Chance a random hit has a higher value than a random miss."""
    pairs = sorted(zip(values, hits))
    ranks, i = [0.0] * len(pairs), 0
    while i < len(pairs):
        j = i
        while j + 1 < len(pairs) and pairs[j + 1][0] == pairs[i][0]:
            j += 1
        for k in range(i, j + 1):
            ranks[k] = (i + j) / 2 + 1
        i = j + 1
    n1 = sum(h for _, h in pairs)
    n0 = len(pairs) - n1
    if not n1 or not n0:
        return float("nan")
    return (sum(r for r, (_, h) in zip(ranks, pairs) if h) - n1 * (n1 + 1) / 2) / (n1 * n0)


def pair_accuracy(rows, value):
    """Same position, same week, predicted within CLOSE on the site's
    number: how often the higher `value` really scored more."""
    by = defaultdict(list)
    for r in rows:
        by[(r["week"], r["pos"])].append(r)
    right = total = 0
    for group in by.values():
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                if abs(a["score"] - b["score"]) >= CLOSE or a["actual"] == b["actual"]:
                    continue
                va, vb = value(a), value(b)
                if va == vb:
                    continue
                total += 1
                right += (va > vb) == (a["actual"] > b["actual"])
    return right, total


def fit(rows, key):
    """Points per standard deviation of the stat, from these rows' misses
    (real minus predicted). Returns (slope, mean, sd)."""
    xs = [r["f"][key] for r in rows]
    es = [r["actual"] - r["score"] for r in rows]
    m, s = mean(xs), pstdev(xs)
    if not s:
        return 0.0, m, 1.0
    zs = [(x - m) / s for x in xs]
    me = mean(es)
    return sum(z * (e - me) for z, e in zip(zs, es)) / len(zs), m, s


def try_feature(rows, key):
    """Out of sample, both ways round: fit on one half, apply to the other."""
    have = [r for r in rows if key in r["f"]]
    a = [r for r in have if r["week"] <= SPLIT]
    b = [r for r in have if r["week"] > SPLIT]
    if len(a) < 40 or len(b) < 40:
        return None
    out = {"n": len(have), "folds": []}
    for train, test in ((a, b), (b, a)):
        slope, m, s = fit(train, key)

        def adjusted(r):
            return r["score"] + max(-CAP, min(CAP, slope * (r["f"][key] - m) / s))
        before = mae([r["actual"] - r["score"] for r in test])
        after = mae([r["actual"] - adjusted(r) for r in test])
        pr_before = pair_accuracy(test, lambda r: r["score"])
        pr_after = pair_accuracy(test, adjusted)
        out["folds"].append({"slope": slope, "r": corr([r["f"][key] for r in test],
                                                       [r["actual"] - r["score"] for r in test]),
                             "mae": (before, after), "pairs": (pr_before, pr_after), "n": len(test)})
    return out


def pct(right_total):
    right, total = right_total
    return f"{100 * right / total:.1f}% of {total}" if total else "–"


def report(rows, season, first=FIRST_WEEK):
    played = [r for r in rows if r["actual"] is not None and r["week"] >= first]
    lines = [f"# Backtest: {season}, weeks {first}-{max(r['week'] for r in played)}", ""]
    lines.append("Players who played, projected at least " + ", ".join(f"{p} {v}" for p, v in MIN_PROJ.items())
                 + " pts. Predicted = Sleeper's projection + the current adjustments (no consensus, no injury).")
    lines += ["", "## How good is Predicted now?", "",
              "| Pos | Players | Avg miss: projection | Avg miss: Predicted | Bias (real − Predicted) | Close calls right: projection | Predicted |",
              "|---|---|---|---|---|---|---|"]
    for pos in MIN_PROJ:
        g = [r for r in played if r["pos"] == pos]
        if not g:
            continue
        lines.append(f"| {pos} | {len(g)} | {mae([r['actual'] - r['proj'] for r in g]):.2f} | "
                     f"{mae([r['actual'] - r['score'] for r in g]):.2f} | {mean(r['actual'] - r['score'] for r in g):+.2f} | "
                     f"{pct(pair_accuracy(g, lambda r: r['proj']))} | {pct(pair_accuracy(g, lambda r: r['score']))} |")

    lines += ["", "## Are the current adjustments the right size?", "",
              "Slope of the miss before each adjustment on its points: 1 = right size, 0 = no help, "
              "above 1 = too timid. ± is one standard error.", "",
              "| Adjustment | Pos | Players | Slope | Avg miss without → with |", "|---|---|---|---|---|"]
    for key in ("usage", "environment", "matchup", "qb", "returns"):
        for pos in MIN_PROJ:
            g = [r for r in played if r["pos"] == pos and r["adj"].get(key)]
            if len(g) < 30:
                continue
            xs = [r["adj"][key] for r in g]
            ys = [r["actual"] - (r["score"] - r["adj"][key]) for r in g]
            mx, my = mean(xs), mean(ys)
            sxx = sum((x - mx) ** 2 for x in xs)
            if not sxx:
                continue
            slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
            resid = [y - my - slope * (x - mx) for x, y in zip(xs, ys)]
            se = math.sqrt(sum(e * e for e in resid) / max(1, len(g) - 2) / sxx)
            lines.append(f"| {key} | {pos} | {len(g)} | {slope:.2f} ± {se:.2f} | "
                         f"{mae(ys):.2f} → {mae([r['actual'] - r['score'] for r in g]):.2f} |")

    lines += ["", "## Do nflverse stats help? (out of sample)", "",
              f"Fit on weeks {first}-{SPLIT}, tested on {SPLIT + 1}+ (A), and the other way round (B). "
              f"r = correlation with what Predicted missed; slope = points per standard deviation (capped at ±{CAP}). "
              "A stat helps if the average miss drops in both halves.", "",
              "| Pos | Stat | Players | r (A / B) | Slope (A / B) | Avg miss A | Avg miss B | Close calls A | Close calls B |",
              "|---|---|---|---|---|---|---|---|---|"]
    for pos, cands in CANDIDATES.items():
        g = [r for r in played if r["pos"] == pos]
        for key, _ in cands:
            res = try_feature(g, key)
            if not res:
                continue
            fa, fb = res["folds"]
            lines.append(
                f"| {pos} | {key} | {res['n']} | {fa['r']:+.3f} / {fb['r']:+.3f} | {fa['slope']:+.2f} / {fb['slope']:+.2f} | "
                f"{fa['mae'][0]:.3f} → {fa['mae'][1]:.3f} | {fb['mae'][0]:.3f} → {fb['mae'][1]:.3f} | "
                f"{pct(fa['pairs'][0])} → {pct(fa['pairs'][1])} | {pct(fb['pairs'][0])} → {pct(fb['pairs'][1])} |")

    lines += ["", "## Boom and bust", "",
              "Ranges: the floor is the 25th percentile and the ceiling the 90th, so about 25% of games "
              "should land at or under the floor and 10% at or over the ceiling.", "",
              "| Pos | Players | At/under floor | At/over ceiling | Boom label: over ceiling | Others | Steady label: under floor | Others |",
              "|---|---|---|---|---|---|---|---|"]
    for pos in MIN_PROJ:
        g = [r for r in played if r["pos"] == pos and r["floor"] is not None]
        if not g:
            continue

        def rate(rs, test):
            return f"{100 * sum(1 for r in rs if test(r)) / len(rs):.0f}% of {len(rs)}" if rs else "–"
        under, over = (lambda r: r["actual"] <= r["floor"]), (lambda r: r["actual"] >= r["ceiling"])
        lines.append(f"| {pos} | {len(g)} | {rate(g, under)} | {rate(g, over)} | "
                     f"{rate([r for r in g if r['label'] == 'Boom'], over)} | {rate([r for r in g if r['label'] != 'Boom'], over)} | "
                     f"{rate([r for r in g if r['label'] == 'Steady'], under)} | {rate([r for r in g if r['label'] != 'Steady'], under)} |")

    lines += ["", "## Is the \"give or take\" (sd) right?", "",
              "Win % adds up each starter's sd. If the sd is right, misses divided by it spread out "
              "with a standard deviation of 1.0 and 68% of them land within ±1 sd. Under 1.0 / over 68% = "
              "the sd is too big (win % too timid); over 1.0 / under 68% = too small (win % too sure).", "",
              "| Pos | Players | Miss ÷ sd: spread | Within ±1 sd | sd should be × |", "|---|---|---|---|---|"]
    for pos in MIN_PROJ:
        g = [r for r in played if r["pos"] == pos and r.get("sd")]
        if len(g) < 30:
            continue
        zs = [(r["actual"] - r["score"]) / r["sd"] for r in g]
        spread = math.sqrt(mean(z * z for z in zs))
        lines.append(f"| {pos} | {len(g)} | {spread:.2f} | {100 * sum(abs(z) <= 1 for z in zs) / len(zs):.0f}% | {spread:.2f} |")

    lines += ["", "## Return yards", "",
              "Recent returners (the return man adjustment's players): the return points in their "
              "projection, what Predicted added for returns, and what they really got.", "",
              "| RB/WR/TE return men | Games | Return pts projected | Added by Predicted | Really got | Still returned |",
              "|---|---|---|---|---|---|"]
    men = [r for r in played if r["pos"] in ("RB", "WR", "TE") and r["adj"].get("returns")]
    for name, grp in (("Projection has return yards", [r for r in men if r["ret_proj"] > 0]),
                      ("Projection has none", [r for r in men if r["ret_proj"] <= 0])):
        if grp:
            lines.append(f"| {name} | {len(grp)} | {mean(r['ret_proj'] for r in grp):.2f} | "
                         f"{mean(r['adj']['returns'] for r in grp):.2f} | {mean(r['ret_real'] or 0 for r in grp):.2f} | "
                         f"{100 * sum(1 for r in grp if (r['ret_real'] or 0) > 0) / len(grp):.0f}% |")
    others = [r for r in played if r["pos"] in ("RB", "WR", "TE") and not r["adj"].get("returns") and r["ret_proj"] > 0]
    if others:
        lines.append(f"| No adjustment, projection has return yards | {len(others)} | {mean(r['ret_proj'] for r in others):.2f} | 0 | "
                     f"{mean(r['ret_real'] or 0 for r in others):.2f} | "
                     f"{100 * sum(1 for r in others if (r['ret_real'] or 0) > 0) / len(others):.0f}% |")

    lines += ["", "Picking out big games (1.5× Predicted or more) and duds (half or less): AUC, "
              "0.5 = coin flip. ceiling/score and floor/score are what the Boom/Steady labels use now "
              "(a high floor/score should mean fewer duds, so its dud AUC should be under 0.5).", "",
              "| Pos | Stat | Players | Big games | AUC big | AUC dud |", "|---|---|---|---|---|---|"]
    for pos in ("QB", "RB", "WR", "TE"):
        g = [r for r in played if r["pos"] == pos and r["score"] > 0 and r["floor"] is not None]
        g = [dict(r, f=dict(r["f"], **{"ceiling/score": r["ceiling"] / r["score"],
                                       "floor/score": r["floor"] / r["score"]})) for r in g]
        for key in ["ceiling/score", "floor/score"] + [k for k, _ in CANDIDATES[pos]]:
            have = [r for r in g if key in r["f"]]
            if len(have) < 60:
                continue
            big = [r["actual"] >= 1.5 * r["score"] for r in have]
            dud = [r["actual"] <= 0.5 * r["score"] for r in have]
            vals = [r["f"][key] for r in have]
            lines.append(f"| {pos} | {key} | {len(have)} | {sum(big)} | {auc(vals, big):.3f} | {auc(vals, dud):.3f} |")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("snap", type=Path)
    ap.add_argument("nflverse", type=Path)
    ap.add_argument("--season", default="2025")
    ap.add_argument("--first-week", type=int, default=FIRST_WEEK,
                    help="first week counted (the nflverse stats need 3 games before it)")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--rows", type=Path, help="also save every player-week as JSON")
    args = ap.parse_args()
    settings = load_settings()
    current = json.loads((args.snap / "index.json").read_text()).get("season")
    scoring = json.loads((args.snap / "sleeper/league.json").read_text())["scoring_settings"]
    games_csv = list(csv.DictReader(open(args.nflverse / "games.csv", encoding="utf-8")))
    print(f"Rebuilding Predicted for {args.season}...", file=sys.stderr)
    rows = predictions(args.snap, settings, scoring, args.season, games_csv, current)
    player, defense = nflverse_features(args.nflverse, args.season, {r["id"] for r in rows})
    attach(rows, player, defense)
    if args.rows:
        args.rows.write_text(json.dumps(rows))
    text = report(rows, args.season, args.first_week)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
