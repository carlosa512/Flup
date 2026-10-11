#!/usr/bin/env python3
"""Save raw responses from the data sources into a folder, unchanged.

Development helper only. GitHub's runners can reach Sleeper and ESPN, so the
"Dev snapshot" workflow runs this and pushes the folder to the
dev-snapshots branch. That gives real responses to build parsers and tests
against without guessing at their shape.

    python3 tools/snapshot.py OUT_DIR [--league-id ID]
"""

import argparse
import gzip
import json
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SLEEPER = "https://api.sleeper.app"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"
POSITIONS = ["QB", "RB", "WR", "TE", "K", "DEF"]
LEAGUE_ID = "1374496898462785536"


def fetch(url):
    req = Request(url, headers={"User-Agent": "flup-snapshot"})
    for attempt in range(1, 4):
        try:
            with urlopen(req, timeout=60) as resp:
                return resp.status, resp.read()
        except HTTPError as err:
            return err.code, err.read()
        except (URLError, TimeoutError) as err:
            if attempt == 3:
                return 0, str(err).encode()
            time.sleep(2 * attempt)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--league-id", default=LEAGUE_ID)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    index = []

    def save(name, url, gz=False):
        status, body = fetch(url)
        path = out / (name + (".gz" if gz else ""))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(gzip.compress(body) if gz else body)
        index.append({"file": str(path.relative_to(out)), "url": url,
                      "status": status, "bytes": len(body)})
        print(f"{status}  {len(body):>9,} B  {name}")
        return status, body

    _, body = save("sleeper/state.json", f"{SLEEPER}/v1/state/nfl")
    state = json.loads(body)
    season, week = state["season"], state.get("display_week") or state["week"]
    lid = args.league_id

    save("sleeper/league.json", f"{SLEEPER}/v1/league/{lid}")
    save("sleeper/users.json", f"{SLEEPER}/v1/league/{lid}/users")
    save("sleeper/rosters.json", f"{SLEEPER}/v1/league/{lid}/rosters")
    save(f"sleeper/matchups_{week}.json", f"{SLEEPER}/v1/league/{lid}/matchups/{week}")
    save("sleeper/user_clos512.json", f"{SLEEPER}/v1/user/clos512")
    for pos in POSITIONS:
        save(f"sleeper/proj_{week}_{pos}.json",
             f"{SLEEPER}/projections/nfl/{season}/{week}?season_type=regular&position[]={pos}")
    # Past weeks: official league points (matchups) and raw stat lines, so
    # rescoring can be checked against what Sleeper actually awarded.
    for past in range(1, int(week)):
        save(f"sleeper/matchups_{past}.json", f"{SLEEPER}/v1/league/{lid}/matchups/{past}")
        save(f"sleeper/stats_{past}_all.json",
             f"{SLEEPER}/stats/nfl/{season}/{past}?season_type=regular&"
             + "&".join(f"position[]={p}" for p in POSITIONS), gz=True)
    prev_season = str(int(season) - 1)
    for past in range(1, 19):
        save(f"sleeper/stats_{prev_season}_{past}_all.json",
             f"{SLEEPER}/stats/nfl/{prev_season}/{past}?season_type=regular&"
             + "&".join(f"position[]={p}" for p in POSITIONS), gz=True)
    save("sleeper/trending_add.json",
         f"{SLEEPER}/v1/players/nfl/trending/add?lookback_hours=48&limit=50")
    save("sleeper/players_nfl.json", f"{SLEEPER}/v1/players/nfl", gz=True)

    _, body = save(f"espn/scoreboard_{week}.json",
                   f"{ESPN}/scoreboard?seasontype=2&week={week}&dates={season}")
    try:
        events = json.loads(body).get("events") or []
        if events:
            ev = events[0]
            comp = ev["competitions"][0]["id"]
            save("espn/core_odds_example.json",
                 "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/"
                 f"events/{ev['id']}/competitions/{comp}/odds")
    except (ValueError, KeyError, IndexError) as err:
        print(f"ESPN parse problem: {err}")

    news_probe(save, out, lid, season, week)

    (out / "index.json").write_text(json.dumps(
        {"season": season, "week": week, "taken_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
         "files": index}, indent=2))
    bad = [i for i in index if i["status"] != 200]
    if bad:
        print(f"{len(bad)} request(s) did not return 200", file=sys.stderr)


# ---------- Phase 4 probe: which news feeds work, and does CORS allow a
# browser refresh? Candidates marked "guess" may not exist; the statuses in
# index.json say which do. ----------

TEAMS = {
    "ARI": "Cardinals", "ATL": "Falcons", "BAL": "Ravens", "BUF": "Bills", "CAR": "Panthers",
    "CHI": "Bears", "CIN": "Bengals", "CLE": "Browns", "DAL": "Cowboys", "DEN": "Broncos",
    "DET": "Lions", "GB": "Packers", "HOU": "Texans", "IND": "Colts", "JAX": "Jaguars",
    "KC": "Chiefs", "LV": "Raiders", "LAC": "Chargers", "LAR": "Rams", "MIA": "Dolphins",
    "MIN": "Vikings", "NE": "Patriots", "NO": "Saints", "NYG": "Giants", "NYJ": "Jets",
    "PHI": "Eagles", "PIT": "Steelers", "SF": "49ers", "SEA": "Seahawks", "TB": "Buccaneers",
    "TEN": "Titans", "WAS": "Commanders",
}
ORIGIN = "https://carlosa512.github.io"
BSKY = "https://public.api.bsky.app/xrpc"


def cors(url):
    """Status and the CORS header a browser on the site would get."""
    req = Request(url, headers={"User-Agent": "flup-snapshot", "Origin": ORIGIN})
    try:
        with urlopen(req, timeout=30) as resp:
            return {"url": url, "status": resp.status,
                    "allow_origin": resp.headers.get("Access-Control-Allow-Origin"),
                    "cache_control": resp.headers.get("Cache-Control")}
    except HTTPError as err:
        return {"url": url, "status": err.code,
                "allow_origin": err.headers.get("Access-Control-Allow-Origin")}
    except (URLError, TimeoutError) as err:
        return {"url": url, "status": 0, "error": str(err)}


def news_probe(save, out, lid, season, week):
    try:
        rosters = json.loads((out / "sleeper/rosters.json").read_text())
        players = json.loads(gzip.decompress((out / "sleeper/players_nfl.json.gz").read_bytes()))
    except (OSError, ValueError) as err:
        print(f"News probe skipped: {err}")
        return
    mine = next((r for r in rosters if r.get("roster_id") == 12), rosters[0])
    espn_ids = [players[p]["espn_id"] for p in mine.get("players") or []
                if p in players and players[p].get("espn_id")][:3]

    # ESPN (the public API already used for lines; RSS for headlines)
    for eid in espn_ids:
        save(f"news/espn_fantasy_player_{eid}.json",
             f"https://site.api.espn.com/apis/fantasy/v2/games/ffl/news/players?limit=10&playerId={eid}")
    eid = espn_ids[0] if espn_ids else "3139477"
    save("news/espn_nfl_news.json", f"{ESPN}/news?limit=50")
    save(f"news/espn_nfl_news_athlete_{eid}.json", f"{ESPN}/news?athletes={eid}")  # guess
    save(f"news/espn_athlete_news_{eid}.json",
         f"https://site.web.api.espn.com/apis/common/v3/sports/football/nfl/athletes/{eid}/news")  # guess
    save("news/espn_rss.xml", "https://www.espn.com/espn/rss/nfl/news")

    # Aggregators with RSS
    save("news/pft_feed.xml", "https://profootballtalk.nbcsports.com/feed/")
    save("news/pft_nbc.rss", "https://www.nbcsports.com/profootballtalk.rss")  # guess
    save("news/nbc_player_news.rss", "https://www.nbcsports.com/fantasy/football/player-news/rss")  # guess
    save("news/fantasypros_news.xml", "https://www.fantasypros.com/nfl/rss/news.xml")  # guess
    save("news/fantasypros_player_news.xml", "https://www.fantasypros.com/rss/nfl/player-news.xml")  # guess
    save("news/cbs_nfl.rss", "https://www.cbssports.com/rss/headlines/nfl/")
    save("news/yahoo_nfl.rss", "https://sports.yahoo.com/nfl/rss.xml")
    save("news/rotoballer_nfl.rss", "https://www.rotoballer.com/category/nfl/feed")
    for host in ("www.espn.com", "profootballtalk.nbcsports.com", "www.nbcsports.com",
                 "www.fantasypros.com", "www.cbssports.com", "sports.yahoo.com",
                 "www.rotoballer.com", "bsky.app"):
        save(f"news/robots/{host}.txt", f"https://{host}/robots.txt")

    # Bluesky: find each team's beat writers by their bios, and see one
    # account's feed both as JSON and as RSS
    first = None
    for abbr, nick in TEAMS.items():
        status, body = save(f"news/bsky_search/{abbr}.json",
                            f"{BSKY}/app.bsky.actor.searchActors?q={nick}%20beat%20writer&limit=25")
        if status == 200 and first is None:
            try:
                actors = json.loads(body).get("actors") or []
            except ValueError:
                actors = []
            first = actors[0]["handle"] if actors else None
    save("news/bsky_starter_packs.json",
         f"{BSKY}/app.bsky.graph.searchStarterPacks?q=NFL%20beat%20writers&limit=25")
    if first:
        save("news/bsky_author_feed.json", f"{BSKY}/app.bsky.feed.getAuthorFeed?actor={first}&limit=20")
        save("news/bsky_profile.rss", f"https://bsky.app/profile/{first}/rss")

    # Can the browser call these directly (Refresh button)?
    checks = [cors(u) for u in (
        f"{SLEEPER}/v1/state/nfl",
        f"{SLEEPER}/v1/league/{lid}/matchups/{week}",
        f"{SLEEPER}/stats/nfl/{season}/{week}?season_type=regular&position[]=QB",
        f"{SLEEPER}/projections/nfl/{season}/{week}?season_type=regular&position[]=QB",
        f"{ESPN}/scoreboard?seasontype=2&week={week}&dates={season}",
        "https://site.api.espn.com/apis/fantasy/v2/games/ffl/news/players?limit=1",
    )]
    (out / "news").mkdir(exist_ok=True)
    (out / "news/cors.json").write_text(json.dumps(checks, indent=2))
    for c in checks:
        print(f"CORS {c['status']} allow={c.get('allow_origin')}  {c['url']}")


if __name__ == "__main__":
    main()
