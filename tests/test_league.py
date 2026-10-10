from pipeline.league import context, playoff_weeks, sanity

EXPECT = {"teams": 12, "rec": 0.5, "bonus_rec_te": 0.5, "rb_slots": 2, "flex_slots": 2,
          "playoff_week_start": 15, "playoff_week_end": 17, "playoff_teams": 8}


def league(**scoring):
    return {"total_rosters": 12,
            "scoring_settings": {"rec": 0.5, "bonus_rec_te": 0.5, **scoring},
            "roster_positions": ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX", "K", "DEF", "BN"],
            "settings": {"playoff_week_start": 15, "playoff_teams": 8, "playoff_round_type": 0}}


def test_playoff_weeks():
    assert playoff_weeks({"playoff_week_start": 15, "playoff_teams": 8, "playoff_round_type": 0}) == (15, 17)
    assert playoff_weeks({"playoff_week_start": 15, "playoff_teams": 6, "playoff_round_type": 1}) == (15, 18)


def test_sanity_all_match():
    assert all(c["ok"] for c in sanity(league(), EXPECT))


def test_sanity_flags_mismatch():
    checks = {c["key"]: c for c in sanity(league(rec=1.0), EXPECT)}
    assert checks["rec"]["ok"] is False and checks["rec"]["actual"] == 1.0


def test_context_finds_me_and_opponent():
    users = [{"user_id": "u1", "display_name": "clos512", "metadata": {"team_name": "Mine "}},
             {"user_id": "u2", "display_name": "rival", "metadata": {}}]
    rosters = [{"roster_id": 1, "owner_id": "u1", "players": ["10", "11"], "settings": {}},
               {"roster_id": 2, "owner_id": "u2", "players": ["20"], "settings": {}}]
    matchups = [{"roster_id": 1, "matchup_id": 3}, {"roster_id": 2, "matchup_id": 3}]
    ctx = context({"settings": {"waiver_budget": 200}}, users, rosters, matchups, "CLOS512")
    assert ctx["my_rid"] == 1 and ctx["opp_rid"] == 2
    assert ctx["teams"][1]["name"] == "Mine" and ctx["teams"][2]["name"] == "rival"
    assert ctx["owners"]["20"] == 2


def test_zero_projection_free_agents_dropped_even_without_opponent():
    from pipeline.build import player_rows
    rows = [{"player_id": "1", "team": "DET", "stats": {"rec": 0},
             "player": {"first_name": "Bye", "last_name": "Guy", "position": "WR"}},
            {"player_id": "2", "team": "DET", "stats": {"rec": 0},
             "player": {"first_name": "My", "last_name": "Guy", "position": "WR"}}]
    ctx = {"owners": {"2": 1}, "my_rid": 1, "opp_rid": None}
    names = [p["name"] for p in player_rows(rows, "WR", {"rec": 0.5}, ctx, {}, True)]
    assert names == ["My Guy"]
