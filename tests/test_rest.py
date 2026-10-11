import json
from pathlib import Path

from pipeline import build, espn

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "espn_standings_2025.json"
CFG = {"weeks": [16, 17], "clinchers": ["*"]}


def standings():
    return espn.parse_standings(json.loads(FIXTURE.read_text()))


def positions():
    mk = lambda pid, team, pos="WR": {"id": pid, "name": pid, "team": team, "pos": pos, "score": 12.0}
    return {"WR": {"players": [mk("den1", "DEN"), mk("ne1", "NE"), mk("sea1", "SEA")], "breaks": []},
            "DEF": {"players": [mk("DEN", "DEN", "DEF")], "breaks": []}}


def test_last_seasons_final_standings_parse():
    s = standings()
    # 2025 final: DEN and SEA were the #1 seeds, NE won its division
    assert s["DEN"]["clincher"] == "*" and s["DEN"]["seed"] == 1
    assert s["SEA"]["clincher"] == "*" and s["NE"]["clincher"] == "z"
    assert len(s) == 32 and "WAS" in s and "WSH" not in s


def test_number_one_seeds_are_flagged_in_the_last_two_weeks_only():
    pos = positions()
    n = build.add_rest_flags(pos, standings(), 17, CFG)
    flagged = {p["id"]: p.get("rest") for b in pos.values() for p in b["players"]}
    assert n == 3
    assert flagged["den1"] == "DEN has clinched the #1 seed: starters may rest this week."
    assert flagged["DEN"] and flagged["sea1"] and flagged["ne1"] is None
    # Flag only: nobody's score changes
    assert all(p["score"] == 12.0 for b in pos.values() for p in b["players"])


def test_week_16_looks_ahead_and_earlier_weeks_say_nothing():
    pos = positions()
    build.add_rest_flags(pos, standings(), 16, CFG)
    assert pos["WR"]["players"][0]["rest"] == "DEN has clinched the #1 seed: starters may rest in week 17."
    pos = positions()
    assert build.add_rest_flags(pos, standings(), 10, CFG) == 0
    assert all("rest" not in p for b in pos.values() for p in b["players"])
