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
    # Backtests: Sleeper's own weekly projections for every finished week,
    # last season and this one, to test new inputs (nflverse EPA, WOPR...)
    # against what Sleeper already projected
    for yr, last in ((prev_season, 18), (season, int(week) - 1)):
        for past in range(1, last + 1):
            save(f"sleeper/proj_{yr}_{past}_all.json",
                 f"{SLEEPER}/projections/nfl/{yr}/{past}?season_type=regular&"
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
    phase5_probe(save, out, season)
    beat_check(save, out)

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

    # Bluesky: each team's beat writers are the accounts whose bio names the
    # team and says beat/covers/reporter. Keep up to 4 per team, with their
    # latest posts (are they active?). Plus the "NFL beat writers" starter
    # packs' members.
    words = ("beat", "cover", "reporter", "insider")
    found = {}
    for abbr, nick in TEAMS.items():
        seen = {}
        for q in (f"{nick} beat", f"{nick} reporter"):
            status, body = fetch(f"{BSKY}/app.bsky.actor.searchActors?q={q.replace(' ', '%20')}&limit=50")
            try:
                actors = json.loads(body).get("actors") or [] if status == 200 else []
            except ValueError:
                actors = []
            for a in actors:
                bio = ((a.get("description") or "") + " " + (a.get("displayName") or "")).lower()
                if nick.lower() in bio and any(w in bio for w in words):
                    seen.setdefault(a["handle"], {"handle": a["handle"], "name": a.get("displayName"),
                                                  "bio": a.get("description")})
        found[abbr] = list(seen.values())[:4]
        for a in found[abbr]:
            status, body = fetch(f"{BSKY}/app.bsky.feed.getAuthorFeed?actor={a['handle']}&limit=5")
            try:
                posts = json.loads(body).get("feed") or [] if status == 200 else []
            except ValueError:
                posts = []
            a["latest"] = [((x.get("post") or {}).get("record") or {}).get("createdAt") for x in posts]
    (out / "news").mkdir(exist_ok=True)
    (out / "news/bsky_beat.json").write_text(json.dumps(found, indent=1))
    print("Bluesky beat candidates:", {k: len(v) for k, v in found.items()})
    for uri in ("at://did:plc:pgxejfwpltr73b6amkirahwd/app.bsky.graph.starterpack/3lasn45dohl2n",
                "at://did:plc:nbzyzqrzjx7ydz2vwxv3j7uw/app.bsky.graph.starterpack/3moleluakei24"):
        status, body = fetch(f"{BSKY}/app.bsky.graph.getStarterPack?starterPack={uri}")
        try:
            lst = json.loads(body)["starterPack"]["list"]["uri"]
        except (ValueError, KeyError, TypeError):
            continue
        save(f"news/bsky_pack_{uri.rsplit('/', 1)[1]}.json",
             f"{BSKY}/app.bsky.graph.getList?list={lst}&limit=100")
    save("news/bsky_profile.rss", "https://bsky.app/profile/davebirkett.bsky.social/rss")

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


# ---------- Phase 5 probe: player headshots and NFL standings ----------

def image_check(url):
    """Status, type and size of an image, and whether it's hotlink-safe
    (answers with a Referer from the site, too)."""
    out = {"url": url}
    for label, headers in (("plain", {}), ("from_site", {"Referer": ORIGIN + "/Flup/"})):
        req = Request(url, headers={"User-Agent": "Mozilla/5.0 flup-snapshot", **headers})
        try:
            with urlopen(req, timeout=30) as resp:
                body = resp.read()
                out[label] = {"status": resp.status, "type": resp.headers.get("Content-Type"),
                              "bytes": len(body), "cache": resp.headers.get("Cache-Control")}
        except HTTPError as err:
            out[label] = {"status": err.code}
        except (URLError, TimeoutError) as err:
            out[label] = {"status": 0, "error": str(err)}
    return out


def phase5_probe(save, out, season):
    try:
        rosters = json.loads((out / "sleeper/rosters.json").read_text())
        players = json.loads(gzip.decompress((out / "sleeper/players_nfl.json.gz").read_bytes()))
    except (OSError, ValueError) as err:
        print(f"Phase 5 probe skipped: {err}")
        return
    mine = next((r for r in rosters if r.get("roster_id") == 12), rosters[0])
    ids = [p for p in mine.get("players") or [] if p in players][:3]
    espn = [players[p].get("espn_id") for p in ids if players[p].get("espn_id")][:2]
    urls = [f"https://sleepercdn.com/content/nfl/players/thumb/{pid}.jpg" for pid in ids]
    urls += [f"https://sleepercdn.com/content/nfl/players/{ids[0]}.jpg" if ids else "",
             "https://sleepercdn.com/content/nfl/players/thumb/0.jpg",          # a missing one
             "https://sleepercdn.com/images/team_logos/nfl/hou.png",
             "https://sleepercdn.com/images/team_logos/nfl/was.png"]
    urls += [f"https://a.espncdn.com/i/headshots/nfl/players/full/{e}.png" for e in espn]
    checks = [image_check(u) for u in urls if u]
    (out / "phase5").mkdir(exist_ok=True)
    (out / "phase5/images.json").write_text(json.dumps(checks, indent=1))
    for c in checks:
        print("IMG", c.get("plain"), c.get("from_site", {}).get("status"), c["url"])
    # Standings with clinch marks: this season now, and last season's final
    for yr in (season, str(int(season) - 1)):
        save(f"phase5/standings_{yr}.json",
             f"https://site.api.espn.com/apis/v2/sports/football/nfl/standings?season={yr}")


# ---------- Beat writers: is each Bluesky account in settings.toml
# [news.beat] (plus candidates for teams with few or none) real and posting?
# Own posts only (reposts don't count), over the last 14 days. ----------

BEAT_CANDIDATES = [
    ("ATL", "willmcfadden.bsky.social"), ("ATL", "marcraimondi.bsky.social"),
    ("ATL", "danielflick.bsky.social"), ("ATL", "thefalcoholic.bsky.social"),
    ("ATL", "falcfans.bsky.social"),
    ("DAL", "saadyousuf126.bsky.social"), ("DAL", "calvinwatkins.bsky.social"),
    ("DAL", "joejhoyt.bsky.social"), ("DAL", "jctsports.bsky.social"),
    ("LAC", "elliottteaford.bsky.social"), ("LAC", "realframirez.bsky.social"),
    ("TEN", "paulkuharsky.bsky.social"), ("TEN", "jwyattsports.bsky.social"),
    # League-wide news accounts: would cover every team at once
    ("ALL", "rotoworld-fb.bsky.social"), ("ALL", "rotowirenfl.bsky.social"),
    ("ALL", "rapsheet.bsky.social"), ("ALL", "insidenflnews.bsky.social"),
    ("ALL", "nflnewsposter.bsky.social"),
]
# Other free per-team feeds to try (official team site, SB Nation blog,
# Google News search), for the four teams with no beat writer yet
TEAM_FEEDS = {
    "ATL": ("atlantafalcons", "thefalcoholic", "Atlanta Falcons"),
    "DAL": ("dallascowboys", "bloggingtheboys", "Dallas Cowboys"),
    "LAC": ("chargers", "boltsfromtheblue", "Los Angeles Chargers"),
    "TEN": ("tennesseetitans", "musiccitymiracles", "Tennessee Titans"),
}


def beat_check(save, out):
    # League-wide fantasy news accounts: two pages each, to see the format
    # and how many posts a week they make
    for handle in ("rotowirenfl.bsky.social", "rotoworld-fb.bsky.social"):
        url = f"{BSKY}/app.bsky.feed.getAuthorFeed?actor={handle}&filter=posts_no_replies&limit=100"
        status, body = save(f"news/bsky_feed_{handle.split('.')[0]}_1.json", url)
        try:
            cursor = json.loads(body).get("cursor") if status == 200 else None
        except ValueError:
            cursor = None
        if cursor:
            save(f"news/bsky_feed_{handle.split('.')[0]}_2.json", f"{url}&cursor={cursor}")
    for team, (club, blog, name) in TEAM_FEEDS.items():
        save(f"news/feeds/{team}_team_site.xml", f"https://www.{club}.com/rss/news")
        save(f"news/feeds/{team}_sbnation.xml", f"https://www.{blog}.com/rss/index.xml")
        q = f"%22{name.replace(' ', '%20')}%22%20when:2d"
        save(f"news/feeds/{team}_google_news.xml",
             f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en")
    import tomllib
    cfg = tomllib.loads((Path(__file__).resolve().parent.parent / "settings.toml").read_text())
    beat = (cfg.get("news") or {}).get("beat") or {}
    todo = {(t, h): "configured" for t, hs in beat.items() for h in hs}
    for t, h in BEAT_CANDIDATES:
        todo.setdefault((t, h), "candidate")
    since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 14 * 86400))
    rows = []
    for (team, handle), kind in sorted(todo.items()):
        row = {"team": team, "handle": handle, "kind": kind}
        status, body = fetch(f"{BSKY}/app.bsky.actor.getProfile?actor={handle}")
        try:
            prof = json.loads(body) if status == 200 else {}
        except ValueError:
            prof = {}
        row.update(status=status, name=prof.get("displayName"), bio=prof.get("description"),
                   posts=prof.get("postsCount"))
        status, body = fetch(f"{BSKY}/app.bsky.feed.getAuthorFeed?actor={handle}&limit=50&filter=posts_no_replies")
        try:
            feed = json.loads(body).get("feed") or [] if status == 200 else []
        except ValueError:
            feed = []
        own = [((x.get("post") or {}).get("record") or {}).get("createdAt") or "" for x in feed
               if not x.get("reason") and ((x.get("post") or {}).get("author") or {}).get("handle") == handle]
        row.update(latest=max(own, default=None), last_14_days=sum(1 for t in own if t >= since))
        rows.append(row)
    (out / "news").mkdir(exist_ok=True)
    (out / "news/bsky_beat_check.json").write_text(json.dumps(rows, indent=1))
    quiet = [f"{r['team']} {r['handle']}" for r in rows if r["kind"] == "configured" and not r["last_14_days"]]
    print(f"Beat writers checked: {len(rows)}; configured with no posts in 14 days: {quiet}")

if __name__ == "__main__":
    main()
