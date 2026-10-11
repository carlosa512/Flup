import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import check_writeups  # noqa: E402

DATA = {"season": "2026", "week": 5,
        "league": {"scoring": {"pass_td": 6}, "teams": {}},
        "lineup": {"win": 0.137, "me": {"total": 116.3, "sd": 20.7, "starters": [{"id": "6801", "pts": 9.7}]},
                   "close_calls": [{"start": "6801", "bench": "x", "gap": 1.0, "values": [12.9, 11.9]}]},
        "positions": {"WR": {"players": [{"id": "6801", "name": "Tee Higgins", "injury": "Questionable",
                                          "score": 9.7, "proj": 12.03, "cons": {"rank": 67, "pts": 7.6},
                                          "adj": [{"why": "MIA allows 20.4 pts/game to WRs (average 30.6)"}]}]}}}


def file(text, **kw):
    return {"season": "2026", "week": 5, "written": "2026-10-10T21:00:00Z",
            "players": {"6801": {"text": text, "status": kw.get("status", "Questionable")}}}


def test_real_numbers_pass():
    text = ("Sleeper's 12.0 is well above the experts' WR67 (7.6). MIA allows 20.4 pts/game to WRs, "
            "and he's the close call at 12.9 vs 11.9. You're at 14% to win, so keep him.")
    assert check_writeups.check(file(text), DATA) == []


def test_made_up_numbers_and_shape_fail():
    problems = check_writeups.check(file("He'll catch 4 balls for 95 yards."), DATA)
    assert any("1 sentences" in p for p in problems)
    assert any("numbers not in his data: 4, 95" in p for p in problems)


def test_wrong_week_unknown_player_and_old_status():
    f = file("Fine. Fine.", status="")
    f["week"] = 4
    f["players"]["123"] = {"text": "x. y.", "status": ""}
    problems = check_writeups.check(f, DATA)
    assert any("week 4" in p for p in problems)
    assert any("123: not in the data" in p for p in problems)
    assert any("status should be Questionable" in p for p in problems)
