"""One data run: fetch, score, tier, check, and write site/data/latest.json."""

import argparse
import json
import os
import re
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from . import consensus, espn, history, lineup, model, news, scoring as scoring_mod, sleeper, writeups
from .fetch import FetchError
from .league import context, sanity
from .scoring import score_line
from .tiers import local_gap_tiers
from .validate import rescore_check

ROOT = Path(__file__).resolve().parent.parent
COMPANY_NAMES = {"rotowire": "RotoWire"}
UPLOADS = ROOT / "inputs" / "consensus"
CLAUDE_WRITEUPS = ROOT / "inputs" / "writeups.json"
MAX_WEEK = 18  # the last regular-season week
# Average weekly points a player needs before his spread of outcomes helps
# set the position's typical floor/ceiling (keeps deep backups out of it)
RELEVANT_MEAN = {"QB": 12, "RB": 7, "WR": 7, "TE": 5, "K": 6, "DEF": 5}


def iso(ts=None):
    dt = datetime.now(timezone.utc) if ts is None else datetime.fromtimestamp(ts, timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def workflow_crons(path=ROOT / ".github" / "workflows" / "update.yml"):
    """The scheduled run times (cron, UTC) from the workflow, so the site can
    say when the next update is."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return []
    return re.findall(r"""^\s*-\s*cron:\s*["']([^"']+)["']""", text, re.M)


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
            "game_date": row.get("date"),  # Sleeper's (Eastern) game date: a fallback without ESPN
            "game_status": game.get("status"),
            "implied": game.get("implied"), "spread": game.get("spread"),
            "injury": info.get("injury_status") or "",
            "injury_detail": info.get("injury_body_part") or info.get("injury_notes") or "",
            # Sleeper's latest news about him (for "no injury news since ...")
            "news_at": iso(info["news_updated"] / 1000) if info.get("news_updated") else None,
            "proj": proj, "parts": parts, "roster": rid,
        })
        raw[pid] = stats
    return out, raw


def actual_lines(rows, scoring):
    """This week's real stat lines (live or final) in your scoring, with
    the parts that make up each total: {player_id: (points, parts)}.
    A game counts once gp >= 1, as in the history."""
    out = {}
    for r in rows:
        pos = (r.get("player") or {}).get("position")
        stats = r.get("stats") or {}
        if not pos or (stats.get("gp") or 0) <= 0:
            continue
        out[str(r.get("player_id"))] = score_line(stats, pos, scoring)
    return out


def attach_actuals(positions, lines, official):
    """Give everyone who has played (or is playing) this week his real
    points and their breakdown. official: Sleeper's own points for
    rostered players; the card shows Sleeper's number and says so if the
    stat line adds up differently (a stat correction still pending)."""
    for block in positions.values():
        for p in block["players"]:
            found = lines.get(p["id"])
            if not found:
                continue
            pts, parts = found
            p["actual"] = {"pts": round(pts, 2), "parts": parts,
                           "official": official.get(p["id"])}


CLINCHED = {"*": "the #1 seed", "z": "its division", "y": "a wild card spot", "x": "a playoff spot"}


def add_rest_flags(positions, standings, week, cfg):
    """Late in the season, players on teams that have clinched (settings
    [rest] clinchers, "*" = the #1 seed, "z" = the division) may sit: flag
    them, no points off. Only the #1 seed's place is surely settled; for the
    others the flag says so. Returns how many players were flagged."""
    weeks = cfg.get("weeks") or []
    if week not in weeks:
        return 0
    last = max(weeks)
    when = "this week" if week == last else f"in week {last}"
    n = 0
    for block in positions.values():
        for p in block["players"]:
            mark = (standings.get(p.get("team")) or {}).get("clincher")
            if mark and mark in (cfg.get("clinchers") or []):
                maybe = "" if mark == "*" else " if its seed is locked"
                p["rest"] = (f"{p['team']} has clinched {CLINCHED.get(mark, 'a playoff spot')}: "
                             f"starters may rest {when}{maybe}.")
                n += 1
    return n


def add_news(positions, ctx, my_lineup, rows_by_pos, cfg, now, sources):
    """Attach `news` (newest links) to the players worth reading about."""
    by_id = {p["id"]: p for block in positions.values() for p in block["players"]}
    want = [pid for pid, p in by_id.items() if p["roster"] is not None and p["roster"] == ctx["my_rid"]]
    opp = ctx["lineups"].get(ctx["opp_rid"]) or {}
    want += [pid for pid in opp.get("starters") or [] if pid in by_id]
    want += [fa["id"] for fa in (my_lineup or {}).get("free_agents") or []]
    players = [by_id[pid] for pid in dict.fromkeys(want) if pid in by_id]
    teammates = {}
    for rows in rows_by_pos.values():
        for r in rows:
            info = r.get("player") or {}
            teammates.setdefault(r.get("team") or info.get("team"), []).append(
                f"{info.get('first_name', '')} {info.get('last_name', '')}".strip())
    try:
        ids = consensus.espn_ids()
    except FetchError:
        ids = {}
    found, detail, ok = news.collect(players, ids, teammates, cfg,
                                     datetime.fromisoformat(now.replace("Z", "+00:00")))
    for pid, links in found.items():
        by_id[pid]["news"] = links
    sources.append({"id": "news", "label": "News links (ESPN, RotoWire, Rotoworld, PFT, RotoBaller, beat writers)",
                    "ok": ok, "fetched": now, "detail": detail})


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
    except consensus.NotPostedYet as err:
        # Expected Monday night to about Wednesday: not a problem
        cons = {}
        notes.append(f"{err}, so predictions use Sleeper's projection alone for now")
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


def fetch_market(lid, week):
    """Sleeper trending adds (all leagues) and this league's drops from this
    week and last, with when each happened. Optional: lineups work without."""
    market, problems = {"trending": {}, "dropped": {}}, []
    try:
        for row in sleeper.trending_adds():
            try:
                if row.get("player_id"):
                    market["trending"][str(row["player_id"])] = int(row.get("count") or 0)
            except (TypeError, ValueError):
                continue
    except FetchError as err:
        problems.append(f"trending adds: {err}")
    for leg in (week - 1, week):
        if leg < 1:
            continue
        try:
            moves = sleeper.transactions(lid, leg)
        except FetchError as err:
            problems.append(f"week {leg} moves: {err}")
            continue
        for t in moves:
            if t.get("status") != "complete":
                continue
            when = t.get("status_updated") or t.get("created")
            adds = t.get("adds") or {}
            for pid in (t.get("drops") or {}):
                if pid in adds:
                    continue  # traded to another team, not released
                if when and when > market["dropped"].get(str(pid), 0):
                    market["dropped"][str(pid)] = when
    return market, problems


def pick_week(st, season, scoreboard=espn.scoreboard):
    """The week to show: Sleeper's display_week, or the next one once its
    last game is over (Monday night). Sleeper keeps display_week on the old
    week until about Wednesday, but lineups, trades and waivers are already
    for the next one. Returns (week, its ESPN games if fetched, moved on)."""
    week = int(st.get("display_week") or st["week"])
    try:
        games = scoreboard(season, week)
        # ESPN files postponed and canceled games as "post" too
        over = bool(games) and all(g["completed"] or g["state"] == "post" for g in games)
    except FetchError:
        games, over = None, int(st.get("week") or 0) > week  # no ESPN: Sleeper's own week
    if over and week < MAX_WEEK:
        return week + 1, None, True
    return week, games, False


def build(settings, week=None, league_id=None, now=None):
    now = now or iso()
    lid = league_id or settings["league"]["id"]
    username = settings["league"]["username"]
    sources = []

    st = sleeper.state()
    season = str(st["season"])
    if week:
        week, week_list, moved_on = int(week), None, False
    else:
        week, week_list, moved_on = pick_week(st, season)

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
        game_list = week_list if week_list is not None else espn.scoreboard(season, week)
        games = espn.by_team(game_list)
        lined = sum(1 for g in game_list if g["total"] is not None)
        books = sorted({g["book"] for g in game_list if g["book"]})
        sources.append({"id": "lines", "label": "Vegas lines (ESPN)", "ok": True, "fetched": now,
                        "detail": f"{lined} of {len(game_list)} games have lines"
                                  + (f" ({', '.join(books)})" if books else "")
                                  + (f"; week {week - 1} is over, so this is week {week}" if moved_on else "")})
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
    sources.append({"id": "consensus", "label": "Expert consensus", "ok": bool(cons) or not cons_problems,
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

    # This week's real points so far (Thursday games, then Sunday as it goes)
    try:
        lines = actual_lines(sleeper.stats(season, week), scoring)
        official = {pid: pts for lu in ctx["lineups"].values() for pid, pts in lu["points"].items()}
        attach_actuals(positions, lines, official)
        sources.append({"id": "live", "label": "This week's stats so far (Sleeper)", "ok": True,
                        "fetched": now, "detail": f"{len(lines)} players have played or are playing"})
    except FetchError as err:
        sources.append({"id": "live", "label": "This week's stats so far (Sleeper)", "ok": False,
                        "fetched": now, "detail": str(err)})

    # Free-agent market: who's trending, who was just dropped (maybe on waivers)
    market, market_problems = fetch_market(lid, week)
    sources.append({"id": "market", "label": "Trending adds and league moves (Sleeper)",
                    "ok": not market_problems, "fetched": now,
                    "detail": "; ".join(market_problems) or
                    f"{len(market['trending'])} trending players, {len(market['dropped'])} recent drops"})
    market["clear_days"] = (lg.get("settings") or {}).get("waiver_clear_days", 1)
    market["ratios"] = model_ctx["pos_ratios"]
    market["stretch"] = fc.get("stretch", 1.0)
    market["labels"] = settings.get("labels", {"boom": 1.05, "steady": 1.10})

    # My best lineup, both teams' totals and my win %
    my_lineup = lineup.build(positions, ctx, lg.get("roster_positions") or [], games,
                             dict(settings["lineup"], floor_pct=fc["floor_pct"],
                                  ceiling_pct=fc["ceiling_pct"]),
                             now, scoring, market)
    if my_lineup:
        # My whole roster (IR too) as of this run: the app compares it with
        # Sleeper's when it opens, so trades and drops show right away
        my_lineup["roster"] = sorted(pid for pid, rid in ctx["owners"].items() if rid == ctx["my_rid"])
        # Who's in the IR slot: they don't take a roster spot, so the app
        # can tell whether adding a free agent means dropping someone
        my_lineup["reserve"] = sorted(ctx.get("reserve", {}).get(ctx["my_rid"]) or [])

    # Teams that may rest starters late in the season (flag only)
    rest_cfg = settings.get("rest") or {}
    if week in (rest_cfg.get("weeks") or []):
        try:
            n = add_rest_flags(positions, espn.standings(season), week, rest_cfg)
            sources.append({"id": "standings", "label": "NFL standings (ESPN)", "ok": True, "fetched": now,
                            "detail": f"{n} players on teams that have clinched"})
        except FetchError as err:
            sources.append({"id": "standings", "label": "NFL standings (ESPN)", "ok": False,
                            "fetched": now, "detail": str(err)})

    # A short write-up of each player's breakdown (the card shows it first)
    for block in positions.values():
        for p in block["players"]:
            p["writeup"] = writeups.writeup(p, week)
    # ...and Claude's, from the /writeups command, shown over the template
    if CLAUDE_WRITEUPS.exists():
        try:
            file = json.loads(CLAUDE_WRITEUPS.read_text(encoding="utf-8"))
            n = writeups.attach_claude(positions, file, season, week)
            sources.append({"id": "writeups", "label": "Claude write-ups (/writeups)", "ok": True,
                            "fetched": now, "detail": f"{n} players, written {file.get('written')}" if n
                            else f"the file is for week {file.get('week')}; run /writeups for week {week}"})
        except (ValueError, AttributeError) as err:
            sources.append({"id": "writeups", "label": "Claude write-ups (/writeups)", "ok": False,
                            "fetched": now, "detail": f"inputs/writeups.json didn't read: {err}"})

    # News links: my roster, their starters, the free agents suggested
    add_news(positions, ctx, my_lineup, rows_by_pos, settings.get("news") or {}, now, sources)

    # Prove the scoring engine on every finished week. The one that just
    # ended waits (as before the move to next week): Sleeper's official
    # points can trail its stats for minutes after the last game
    weeks = []
    for past in range(1, week - 1 if moved_on else week):
        if past not in this_season:
            weeks.append({"week": None, "error": f"week {past} stats didn't load"})
            continue
        try:
            r = rescore_check(this_season[past], sleeper.matchups(lid, past), scoring)
            weeks.append({"week": past, **r})
        except FetchError as err:
            weeks.append({"week": None, "error": str(err)})

    return {
        "version": 3,
        "generated": now,
        "season": season,
        "week": week,
        "league": {
            "id": lid, "name": lg.get("name") or "", "teams": ctx["teams"],
            "my_rid": ctx["my_rid"], "opp_rid": ctx["opp_rid"],
            "roster_positions": lg.get("roster_positions") or [],
            "scoring": {k: v for k, v in sorted(scoring.items()) if v},
            # Points-allowed brackets (midpoint, points), zeros included, for
            # the live defense math in the browser
            "def_brackets": scoring_mod.bracket_table(scoring, "pts_allow"),
        },
        # When the data updates itself (main only) and where to run it by hand
        "refresh": {"crons": workflow_crons(), "repo": os.environ.get("GITHUB_REPOSITORY"),
                    "scheduled": os.environ.get("GITHUB_REF_NAME", "main") == "main"},
        "sources": sources,
        "checks": {"settings": sanity(lg, settings["league"]["expect"]), "scoring": weeks},
        "settings": {"tiers": tier_cfg, "positions": settings["positions"],
                     "blend": settings["blend"], "floor_ceiling": fc,
                     "labels": settings.get("labels", {}),
                     "stale_hours": settings.get("stale", {}).get("data_hours", 36),
                     "stale_game_day_hours": settings.get("stale", {}).get("game_day_hours", 3),
                     "injury_news_hours": settings.get("stale", {}).get("injury_news_hours", 24)},
        "positions": positions,
        "lineup": my_lineup,
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
