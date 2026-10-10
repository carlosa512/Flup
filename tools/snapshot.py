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

    (out / "index.json").write_text(json.dumps(
        {"season": season, "week": week, "taken_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
         "files": index}, indent=2))
    bad = [i for i in index if i["status"] != 200]
    if bad:
        print(f"{len(bad)} request(s) did not return 200", file=sys.stderr)


if __name__ == "__main__":
    main()
