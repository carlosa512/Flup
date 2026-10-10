from pipeline.espn import by_team, parse


def event(home, away, details=None, spread=None, total=None, status="STATUS_SCHEDULED"):
    comp = {"date": "2026-10-11T17:00Z", "status": {"type": {"name": status}},
            "competitors": [{"homeAway": "home", "team": {"abbreviation": home}},
                            {"homeAway": "away", "team": {"abbreviation": away}}]}
    if details is not None:
        comp["odds"] = [{"details": details, "spread": spread, "overUnder": total,
                         "provider": {"name": "DraftKings"}}]
    return {"id": "1", "date": comp["date"], "competitions": [comp]}


def test_home_favorite_implied_totals():
    games = parse({"events": [event("JAX", "PHI", "JAX -7.5", -7.5, 41.5)]})
    teams = by_team(games)
    assert teams["JAX"]["spread"] == -7.5 and teams["JAX"]["implied"] == 24.5
    assert teams["PHI"]["spread"] == 7.5 and teams["PHI"]["implied"] == 17.0
    assert teams["JAX"]["home"] is True and teams["PHI"]["opp"] == "JAX"


def test_away_favorite_and_washington_abbreviation():
    games = parse({"events": [event("NYG", "WSH", "WSH -3", 3.0, 44.0)]})
    teams = by_team(games)
    assert "WAS" in teams and teams["WAS"]["spread"] == -3.0
    assert teams["WAS"]["implied"] == 23.5 and teams["NYG"]["implied"] == 20.5


def test_pick_em():
    teams = by_team(parse({"events": [event("GB", "CHI", "EVEN", 0, 45.0)]}))
    assert teams["GB"]["implied"] == 22.5 == teams["CHI"]["implied"]


def test_finished_game_has_no_line():
    teams = by_team(parse({"events": [event("DAL", "TB", status="STATUS_FINAL")]}))
    assert teams["DAL"]["implied"] is None and teams["DAL"]["status"] == "STATUS_FINAL"
