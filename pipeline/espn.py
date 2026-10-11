"""Vegas lines and kickoff times from ESPN's public scoreboard feed.

Unofficial and undocumented (no key). ESPN shows a sportsbook's spread and
over/under per game. Implied team total = total/2 minus own spread/2, so a
-7.5 favorite in a 41.5 game is implied for 24.5.
"""

import re

from .fetch import get_json

URL = ("https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
       "?seasontype=2&week={week}&dates={season}")

# ESPN abbreviation -> Sleeper abbreviation
TEAM_FIX = {"WSH": "WAS"}


def team(abbr):
    return TEAM_FIX.get(abbr, abbr)


def _home_spread(odds, home, away):
    """Home team's spread (negative = home favored). Read from the
    'details' text like "JAX -7.5" when possible, else the spread number."""
    details = (odds.get("details") or "").strip()
    if details.upper() in ("EVEN", "PK", "PICK"):
        return 0.0
    m = re.fullmatch(r"([A-Z]{2,4})\s+([+-]?\d+(?:\.\d+)?)", details)
    if m:
        fav, line = team(m.group(1)), float(m.group(2))
        if fav == home:
            return line
        if fav == away:
            return -line
    spread = odds.get("spread")
    return float(spread) if isinstance(spread, (int, float)) else None


def parse(data):
    """Scoreboard JSON -> list of games with lines (when posted)."""
    games = []
    for ev in data.get("events") or []:
        comp = (ev.get("competitions") or [{}])[0]
        sides, scores = {}, {}
        for c in comp.get("competitors") or []:
            if c.get("team"):
                sides[c.get("homeAway")] = team(c["team"]["abbreviation"])
                try:
                    scores[c.get("homeAway")] = float(c.get("score"))
                except (TypeError, ValueError):
                    pass
        home, away = sides.get("home"), sides.get("away")
        if not home or not away:
            continue
        status = comp.get("status") or ev.get("status") or {}
        kind = status.get("type") or {}
        clock = status.get("clock")
        game = {"id": ev.get("id"), "home": home, "away": away,
                "kickoff": comp.get("date") or ev.get("date"),
                "status": kind.get("name"),
                # pre / in / post, plus where a live game is: quarter and
                # seconds left in it
                "state": kind.get("state"), "completed": bool(kind.get("completed")),
                "period": status.get("period") or 0,
                "clock": float(clock) if isinstance(clock, (int, float)) else 0.0,
                "score_home": scores.get("home"), "score_away": scores.get("away"),
                "spread_home": None, "total": None, "book": None}
        odds = (comp.get("odds") or [None])[0]
        if odds:
            total = odds.get("overUnder")
            game["total"] = float(total) if isinstance(total, (int, float)) else None
            game["spread_home"] = _home_spread(odds, home, away)
            game["book"] = (odds.get("provider") or {}).get("name")
        games.append(game)
    return games


def by_team(games):
    """team -> what that team's players need: opponent, home/away, kickoff,
    own spread and implied total."""
    out = {}
    for g in games:
        for me, opp, home in ((g["home"], g["away"], True), (g["away"], g["home"], False)):
            mine, theirs = (g.get("score_home"), g.get("score_away")) if home else \
                (g.get("score_away"), g.get("score_home"))
            spread = None
            if g["spread_home"] is not None:
                spread = g["spread_home"] if home else -g["spread_home"]
            implied = None
            if g["total"] is not None and spread is not None:
                implied = round(g["total"] / 2 - spread / 2, 2)
            out[me] = {"opp": opp, "home": home, "kickoff": g["kickoff"],
                       "status": g["status"], "state": g.get("state"),
                       "completed": g.get("completed", False),
                       "period": g.get("period", 0), "clock": g.get("clock", 0.0),
                       "score": mine, "opp_score": theirs,
                       "spread": spread, "total": g["total"], "implied": implied}
    return out


def scoreboard(season, week):
    return parse(get_json(URL.format(season=season, week=week)))


STANDINGS_URL = "https://site.api.espn.com/apis/v2/sports/football/nfl/standings?season={season}"


def parse_standings(data):
    """Standings JSON -> team -> {clincher, seed, wins, losses}. ESPN's
    clinch marks: * = the #1 seed (bye), z = division, y = wild card,
    x = playoff spot, e = eliminated."""
    out = {}
    for conf in (data or {}).get("children") or []:
        for e in ((conf.get("standings") or {}).get("entries")) or []:
            abbr = team((e.get("team") or {}).get("abbreviation") or "")
            if not abbr:
                continue
            st = {x.get("name"): x.get("displayValue") for x in e.get("stats") or []}
            num = lambda k: int(st[k]) if str(st.get(k) or "").isdigit() else None
            out[abbr] = {"clincher": st.get("clincher") or "", "seed": num("playoffSeed"),
                         "wins": num("wins"), "losses": num("losses")}
    return out


def standings(season):
    return parse_standings(get_json(STANDINGS_URL.format(season=season)))
