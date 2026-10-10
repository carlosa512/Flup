"""One data run: fetch, score, tier, check, and write site/data/latest.json."""

import argparse
import json
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from . import consensus, espn, history, model, sleeper
from .fetch import FetchError
from .league import context, sanity
from .scoring import score_line
from .tiers import local_gap_tiers
from .validate import rescore_check

ROOT = Path(__file__).resolve().parent.parent
COMPANY_NAMES = {"rotowire": "RotoWire"}
UPLOADS = ROOT / "inputs" / "consensus"
# Average weekly points a player needs before his spread of outcomes helps
# set the position's typical floor/ceiling (keeps deep backups out of it)
RELEVANT_MEAN = {"QB": 12, "RB": 7, "WR": 7, "TE": 5, "K": 6, "DEF": 5}


def iso(ts=None):
    dt = datetime.now(timezone.utc) if ts is None else datetime.fromtimestamp(ts, timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def load_settings(path=ROOT / "settings.toml"):
    return tomllib.loads(Path(path).read_text(encoding="utf-8"))


def player_rows(rows, pos, scoring, ctx, games, smooth, cons):
    """Projection rows -> scored players, plus each one's raw projected stats."""
    out, raw = [], {}
    for row in rows:
        info = row.get("player") or {}
        if info.get("position") and info["position"] != pos:
            continue
        pid = str(row.get("player_id"))
        stats = dict(row.get("stats") or {})
        if pos != "DEF" and "kr_yd" not in stats and stats.get("def_kr_yd"):
            # Sleeper files a player's projected kick return yards under def_kr_yd
            stats["kr_yd"] = stats["def_kr_yd"]
        proj, parts = score_line(stats, pos, scoring, smooth_def_brackets=smooth)
        rid = ctx["owners"].get(pid)
        in_matchup = rid is not None and rid in (ctx["my_rid"], ctx["opp_rid"])
        if proj <= 0 and not in_matchup and pid not in cons:
            continue  # byes, inactive, deep backups
        team = row.get("team") or info.get("team") or "FA"
        game = games.get(team) or {}
        name = f"{info.get('first_name', '')} {info.get('last_name', '')}".strip() or pid
        out.append({
            "id": pid, "name": name, "pos": pos, "team": team,
            "opp": game.get("opp") or row.get("opponent") or "",
            "home": game.get("home"), "kickoff": game.get("kickoff"),
            "game_status": game.get("status"),
            "implied": game.get("implied"), "spread": game.get("spread"),
            "injury": info.get("injury_status") or "",
            "injury_detail": info.get("injury_body_part") or info.get("injury_notes") or "",
            "proj": proj, "parts": parts, "roster": rid,
        })
        raw[pid] = stats
    return out, raw


def fetch_history(season, week, scoring):
    """This season's finished weeks and all of last season, scored."""
    weeks, problems = [], []
    this_season = {}
    for past in range(1, week):
        try:
            rows = sleeper.stats(season, past)
            this_season[past] = rows
            weeks.append((season, past, rows))
        except FetchError as err:
            problems.append(f"{season} week {past}: {err}")
    prev = str(int(season) - 1)
    for past in range(1, 19):
        try:
            weeks.append((prev, past, sleeper.stats(prev, past)))
        except FetchError as err:
            problems.append(f"{prev} week {past}: {err}")
    return history.build(weeks, scoring, season), this_season, problems


def load_consensus(rows_by_pos, game_list, week):
    """FantasyPros consensus by Sleeper id. Your uploaded CSV replaces the
    automatic file for the positions it covers."""
    index = consensus.player_index(rows_by_pos)
    dates = {r.get("date") for rows in rows_by_pos.values() for r in rows if r.get("date")}
    notes, problems = [], []
    try:
        cons, note = consensus.from_dynastyprocess(index, game_list, dates)
        notes.append(note)
    except (FetchError, ValueError, KeyError) as err:
        cons = {}
        problems.append(f"automatic file: {err}")
    try:
        mine, note, upload_problems = consensus.from_uploads(UPLOADS, week, index)
        problems += upload_problems
    except (OSError, ValueError) as err:
        mine, note = {}, ""
        problems.append(f"your CSV: {err}")
    if mine:
        # Your ranks replace the automatic ones player by player; anyone your
        # file didn't match keeps the automatic rank
        cons.update(mine)
        notes.insert(0, note)
    return cons, notes, problems


def build(settings, week=None, league_id=None, now=None):
    now = now or iso()
    lid = league_id or settings["league"]["id"]
    username = settings["league"]["username"]
    sources = []

    st = sleeper.state()
    season = str(st["season"])
    week = int(week or st.get("display_week") or st["week"])

    lg = sleeper.league(lid)
    if not lg:
        raise FetchError(f"Sleeper has no league with ID {lid}")
    scoring = lg.get("scoring_settings") or {}
    me = sleeper.user(username)
    ctx = context(lg, sleeper.users(lid), sleeper.rosters(lid),
                  sleeper.matchups(lid, week), username, me.get("user_id"))
    sources.append({"id": "league", "label": "Sleeper league and rosters", "ok": True,
                    "fetched": now, "detail": lg.get("name") or ""})

    # Vegas lines (optional: everything still works without them)
    games, game_list = {}, []
    try:
        game_list = espn.scoreboard(season, week)
        games = espn.by_team(game_list)
        lined = sum(1 for g in game_list if g["total"] is not None)
        books = sorted({g["book"] for g in game_list if g["book"]})
        sources.append({"id": "lines", "label": "Vegas lines (ESPN)", "ok": True, "fetched": now,
                        "detail": f"{lined} of {len(game_list)} games have lines"
                                  + (f" ({', '.join(books)})" if books else "")})
    except FetchError as err:
        sources.append({"id": "lines", "label": "Vegas lines (ESPN)", "ok": False,
                        "fetched": now, "detail": str(err)})

    # Projections for every position first: consensus matching needs them all
    rows_by_pos, newest, failed = {}, 0, []
    for pos in settings["positions"]:
        try:
            rows_by_pos[pos] = sleeper.projections(season, week, pos)
        except FetchError as err:
            failed.append(f"{pos}: {err}")
            continue
        newest = max([newest] + [r.get("last_modified") or 0 for r in rows_by_pos[pos]])
    if not rows_by_pos:
        raise FetchError("no projections came back: " + "; ".join(failed))
    companies = sorted({COMPANY_NAMES.get(r.get("company"), (r.get("company") or "").title())
                        for rows in rows_by_pos.values() for r in rows if r.get("company")})

    hist, this_season, hist_problems = fetch_history(season, week, scoring)
    n_games = sum(len(g) for g in hist["games"].values())
    sources.append({"id": "history", "label": "Game logs (Sleeper)", "ok": not hist_problems,
                    "fetched": now,
                    "detail": "; ".join(hist_problems[:3]) if hist_problems else
                    f"{n_games:,} player-games from {int(season) - 1} and {season} weeks 1-{week - 1}, scored your way"})

    cons, cons_notes, cons_problems = load_consensus(rows_by_pos, game_list, week)
    sources.append({"id": "consensus", "label": "Expert consensus", "ok": bool(cons),
                    "fetched": now,
                    "detail": "; ".join(cons_notes + cons_problems) or "no consensus this week"})

    # Shared inputs for the model
    fc = settings["floor_ceiling"]
    def season_games(pid):
        return [g for g in hist["games"].get(pid, []) if g["season"] == season]
    def recent_games(pid):
        games_ = hist["games"].get(pid, [])
        last = [g for g in games_ if g["season"] != season][-fc["last_season_games"]:]
        return last + [g for g in games_ if g["season"] == season]
    qb_games = [g for gs in hist["games"].values() for g in gs if g["pos"] == "QB"]
    att = sum(g.get("pass_att", 0) for g in qb_games)
    implied = {t: g["implied"] for t, g in games.items() if g.get("implied") is not None}
    by_pos_hist = {}
    for pid, gs in hist["games"].items():
        if gs:
            by_pos_hist.setdefault(gs[-1]["pos"], []).append(recent_games(pid))
    model_ctx = {
        "relevant_mean": RELEVANT_MEAN,
        "settings": settings, "scoring": scoring, "history": hist,
        "season_games": season_games, "recent_games": recent_games,
        "implied": implied,
        "avg_implied": sum(implied.values()) / len(implied) if implied else None,
        "league_int_rate": sum(g.get("pass_int", 0) for g in qb_games) / att if att else 0.022,
        "pos_ratios": {pos: model.position_ratios({pos: hs}, fc["shrink_games"], RELEVANT_MEAN.get(pos, 5),
                                                  fc["floor_pct"], fc["ceiling_pct"]).get(pos)
                       for pos, hs in by_pos_hist.items()},
    }

    tier_cfg = settings["tiers"]
    smooth = settings.get("scoring", {}).get("smooth_def_brackets", True)
    positions = {}
    for pos, top_n in settings["positions"].items():
        if pos not in rows_by_pos:
            continue
        pos_cons = {pid: c for pid, c in cons.items() if c["pos"] == pos}
        players, raw = player_rows(rows_by_pos[pos], pos, scoring, ctx, games, smooth, pos_cons)
        points_curve = consensus.curve(p["proj"] for p in players)
        for p in players:
            c = pos_cons.get(p["id"])
            if c:
                c = dict(c, pts=consensus.rank_points(points_curve, c["ecr"]))
            p.update(model.my_score(p, raw.get(p["id"], {}), c, model_ctx))
        players.sort(key=lambda p: (-p["score"], -p["proj"], p["name"]))
        for rank, p in enumerate(players, start=1):
            p["rank"] = rank
        top = players[:top_n]
        tiers, breaks = local_gap_tiers(
            [p["score"] for p in top], tier_cfg["gap_multiplier"], tier_cfg["window"],
            tier_cfg["min_tier_size"], tier_cfg["min_median_gap"],
            tier_cfg.get("always_break_gap", float("inf")))
        for p, t in zip(top, tiers):
            p["tier"] = t
        extra = [dict(p, tier=None) for p in players[top_n:]
                 if p["roster"] is not None and p["roster"] in (ctx["my_rid"], ctx["opp_rid"])]
        positions[pos] = {"players": top + extra, "breaks": breaks}
    sources.append({
        "id": "projections", "label": "Sleeper projections" + (f" ({', '.join(companies)})" if companies else ""),
        "ok": not failed, "fetched": now, "updated": iso(newest / 1000) if newest else None,
        "detail": "; ".join(failed) if failed else f"{sum(len(p['players']) for p in positions.values())} players scored"})

    # Prove the scoring engine on every finished week
    weeks = []
    for past in range(1, week):
        if past not in this_season:
            weeks.append({"week": None, "error": f"week {past} stats didn't load"})
            continue
        try:
            r = rescore_check(this_season[past], sleeper.matchups(lid, past), scoring)
            weeks.append({"week": past, **r})
        except FetchError as err:
            weeks.append({"week": None, "error": str(err)})

    return {
        "version": 2,
        "generated": now,
        "season": season,
        "week": week,
        "league": {
            "id": lid, "name": lg.get("name") or "", "teams": ctx["teams"],
            "my_rid": ctx["my_rid"], "opp_rid": ctx["opp_rid"],
            "roster_positions": lg.get("roster_positions") or [],
            "scoring": {k: v for k, v in sorted(scoring.items()) if v},
        },
        "sources": sources,
        "checks": {"settings": sanity(lg, settings["league"]["expect"]), "scoring": weeks},
        "settings": {"tiers": tier_cfg, "positions": settings["positions"],
                     "blend": settings["blend"], "floor_ceiling": fc,
                     "stale_hours": settings.get("stale", {}).get("data_hours", 36)},
        "positions": positions,
        "games": game_list,
    }


def summary(data):
    lg = data["league"]
    teams = lg["teams"]
    mine, opp = lg["my_rid"], lg["opp_rid"]
    lines = [f"{lg['name']}: season {data['season']}, week {data['week']}"]
    lines.append(f"  {teams.get(mine, {}).get('name', '?')} vs {teams.get(opp, {}).get('name', 'no opponent')}")
    bad = [c for c in data["checks"]["settings"] if not c["ok"]]
    lines.append(f"  Settings check: {len(data['checks']['settings']) - len(bad)}/"
                 f"{len(data['checks']['settings'])} match"
                 + "".join(f"\n    MISMATCH {c['label']}: expected {c['expected']}, Sleeper says {c['actual']}" for c in bad))
    for w in data["checks"]["scoring"]:
        if w.get("week"):
            lines.append(f"  Scoring check week {w['week']}: {w['matched']}/{w['checked']} match official points")
    for s in data["sources"]:
        lines.append(f"  [{'ok' if s['ok'] else 'FAIL'}] {s['label']}: {s['detail']}")
    for pos, block in data["positions"].items():
        top = [p for p in block["players"] if p["tier"] == 1]
        lines.append(f"  {pos}: {len(block['breaks']) + 1} tiers; tier 1 = "
                     + ", ".join(f"{p['name']} {p['score']:.1f}" for p in top))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Fetch, score and tier this week's players")
    ap.add_argument("--week", type=int, help="NFL week (default: current)")
    ap.add_argument("--league-id", help="Sleeper league ID (default: settings.toml)")
    ap.add_argument("--out", default=str(ROOT / "site" / "data"), help="output folder")
    args = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(errors="replace")  # emoji team names
    except AttributeError:
        pass

    try:
        data = build(load_settings(), week=args.week, league_id=args.league_id)
    except FetchError as err:
        sys.exit(f"Data run failed, so the site keeps its last data: {err}")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    (out / "latest.json").write_text(text, encoding="utf-8")
    print(summary(data))
    print(f"Wrote {out / 'latest.json'} ({len(text) / 1024:.0f} KB)")
