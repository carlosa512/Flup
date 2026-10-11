"""Sleeper's public API. No login or key. Sleeper asks for fewer than 1000
calls a minute; a full run makes about 15."""

from .fetch import get_json

API = "https://api.sleeper.app"
POSITIONS = ["QB", "RB", "WR", "TE", "K", "DEF"]


def state():
    return get_json(f"{API}/v1/state/nfl")


def user(username):
    return get_json(f"{API}/v1/user/{username}") or {}


def league(league_id):
    return get_json(f"{API}/v1/league/{league_id}")


def users(league_id):
    return get_json(f"{API}/v1/league/{league_id}/users") or []


def rosters(league_id):
    return get_json(f"{API}/v1/league/{league_id}/rosters") or []


def matchups(league_id, week):
    return get_json(f"{API}/v1/league/{league_id}/matchups/{week}") or []


def projections(season, week, pos):
    """Undocumented but public: the endpoint Sleeper's own app uses. Each row
    has the projected stat line plus the player's name, team and injury."""
    return get_json(f"{API}/projections/nfl/{season}/{week}"
                    f"?season_type=regular&position[]={pos}") or []


def trending_adds(hours=48, limit=50):
    """Players added most across all Sleeper leagues lately: [{player_id, count}]."""
    return get_json(f"{API}/v1/players/nfl/trending/add?lookback_hours={hours}&limit={limit}") or []


def transactions(league_id, week):
    """This league's adds/drops/trades for one week (Sleeper calls it a leg)."""
    return get_json(f"{API}/v1/league/{league_id}/transactions/{week}") or []


def stats(season, week):
    """Actual stat lines for a finished week, same shape as projections."""
    query = "&".join(f"position[]={p}" for p in POSITIONS)
    return get_json(f"{API}/stats/nfl/{season}/{week}?season_type=regular&{query}") or []
