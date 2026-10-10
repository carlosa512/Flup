"""One data run: fetch, score, tier, check, and write site/data/latest.json."""

import argparse
import json
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from . import espn, sleeper
from .fetch import FetchError
from .league import context, sanity
from .scoring import score_line
from .tiers import local_gap_tiers
from .validate import rescore_check

ROOT = Path(__file__).resolve().parent.parent
COMPANY_NAMES = {"rotowire": "RotoWire"}


def iso(ts=None):
    dt = datetime.now(timezone.utc) if ts is None else datetime.fromtimestamp(ts, timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def load_settings(path=ROOT / "settings.toml"):
    return tomllib.loads(Path(path).read_text(encoding="utf-8"))


def player_rows(rows, pos, scoring, ctx, games, smooth):
    """Projection rows -> scored players, best first."""
    out = []
    for row in rows:
        info = row.get("player") or {}
        if info.get("position") and info["position"] != pos:
            continue
        pid = str(row.get("player_id"))
        proj, parts = score_line(row.get("stats") or {}, pos, scoring, smooth_def_brackets=smooth)
        rid = ctx["owners"].get(pid)
        in_matchup = rid is not None and rid in (ctx["my_rid"], ctx["opp_rid"])
        if proj <= 0 and not in_matchup:
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
    out.sort(key=lambda p: (-p["proj"], p["name"]))
    return out


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

    tier_cfg = settings["tiers"]
    smooth = settings.get("scoring", {}).get("smooth_def_brackets", True)
    positions, newest, failed = {}, 0, []
    for pos, top_n in settings["positions"].items():
        try:
            rows = sleeper.projections(season, week, pos)
        except FetchError as err:
            failed.append(f"{pos}: {err}")
            continue
        newest = max([newest] + [r.get("last_modified") or 0 for r in rows])
        companies = sorted({r.get("company") for r in rows if r.get("company")})
        players = player_rows(rows, pos, scoring, ctx, games, smooth)
        for rank, p in enumerate(players, start=1):
            p["rank"] = rank
        top = players[:top_n]
        tiers, breaks = local_gap_tiers(
            [p["proj"] for p in top], tier_cfg["gap_multiplier"], tier_cfg["window"],
            tier_cfg["min_tier_size"], tier_cfg["min_median_gap"],
            tier_cfg.get("always_break_gap", float("inf")))
        for p, t in zip(top, tiers):
            p["tier"] = t
        extra = [dict(p, tier=None) for p in players[top_n:]
                 if p["roster"] is not None and p["roster"] in (ctx["my_rid"], ctx["opp_rid"])]
        positions[pos] = {"players": top + extra, "breaks": breaks, "companies": companies}
    if not positions:
        raise FetchError("no projections came back: " + "; ".join(failed))
    companies = sorted({COMPANY_NAMES.get(c, c.title()) for p in positions.values()
                        for c in p.pop("companies")})
    sources.append({
        "id": "projections", "label": "Sleeper projections" + (f" ({', '.join(companies)})" if companies else ""),
        "ok": not failed, "fetched": now, "updated": iso(newest / 1000) if newest else None,
        "detail": "; ".join(failed) if failed else f"{sum(len(p['players']) for p in positions.values())} players scored"})

    # Prove the scoring engine on every finished week
    weeks = []
    try:
        for past in range(1, week):
            r = rescore_check(sleeper.stats(season, past), sleeper.matchups(lid, past), scoring)
            weeks.append({"week": past, **r})
    except FetchError as err:
        weeks.append({"week": None, "error": str(err)})

    return {
        "version": 1,
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
                     + ", ".join(f"{p['name']} {p['proj']:.1f}" for p in top))
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
