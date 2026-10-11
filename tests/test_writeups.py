import re

from pipeline.writeups import writeup

GOFF = {"id": "3163", "name": "Jared Goff", "pos": "QB", "proj": 25.06, "score": 27.0, "base": 24.1,
        "blend": "60% projection, 40% consensus", "note": "", "flag": "", "injury": "", "injury_detail": "",
        "cons": {"rank": 2, "pts": 22.6},
        "adj": [{"key": "environment", "label": "Good game", "pts": 1.5,
                 "why": "DET is implied for 30.0 pts (average team 22.2)"},
                {"key": "matchup", "label": "Good matchup", "pts": 1.4,
                 "why": "ARI allows 25.7 pts/game to QBs (average 18.7)"}],
        "range": {"floor": 21.2, "ceiling": 41.1, "sd": 11.9, "games": 16}}
HIGGINS = {"id": "6801", "name": "Tee Higgins", "pos": "WR", "proj": 12.03, "score": 9.7, "base": 10.3,
           "blend": "60% projection, 40% consensus", "note": "", "flag": "", "injury": "Questionable",
           "injury_detail": "Groin", "cons": {"rank": 67, "pts": 7.6},
           "adj": [{"key": "usage", "label": "Usage up", "pts": 0.2, "why": "27% of team targets"},
                   {"key": "environment", "label": "Good game", "pts": 0.3, "why": "CIN is implied for 25.8"},
                   {"key": "matchup", "label": "Tough matchup", "pts": -0.5,
                    "why": "MIA allows 20.4 pts/game to WRs (average 30.6)"},
                   {"key": "injury", "label": "Questionable", "pts": -0.6, "why": "Groin, 8% off"}],
           "range": {"floor": 5.8, "ceiling": 16.2, "sd": 5.07, "games": 16}}


def numbers(text):
    return re.findall(r"\d+(?:\.\d+)?", text)


def data_numbers(p):
    """Every number the write-up may use: the player's own data, as shown."""
    out = set()
    def walk(x):
        if isinstance(x, bool):
            return
        if isinstance(x, (int, float)):
            out.update({f"{abs(x):.1f}", str(abs(x)), f"{abs(x):g}"})
        elif isinstance(x, str):
            out.update(numbers(x))
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(p)
    small = sum(a["pts"] for a in p["adj"] if abs(a["pts"]) < 0.5)
    out.add(f"{abs(small):.1f}")   # the small tweaks, added up
    return out


def sentences(text):
    return [s for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", text) if s]


def test_leads_with_the_biggest_factor():
    text = writeup(GOFF, 5)
    assert sentences(text)[0].count("Vegas line (+1.5)") == 1


def test_experts_lead_when_they_move_him_most():
    text = writeup(HIGGINS, 5)
    first = sentences(text)[0]
    assert "WR67" in first and "7.6" in first and "12.0" in first
    assert "60% of Sleeper's number, so it starts at 10.3" in text
    assert "his Questionable tag (−0.6) and the matchup (−0.5)" in text and "9.7" in text


def test_two_to_four_sentences_and_only_real_numbers():
    for p in (GOFF, HIGGINS):
        text = writeup(p, 5)
        assert 2 <= len(sentences(text)) <= 4, text
        stray = set(numbers(text)) - data_numbers(p)
        assert not stray, (stray, text)


def test_wording_is_fixed_per_player_and_week_but_varies():
    assert writeup(GOFF, 5) == writeup(GOFF, 5)
    texts = {writeup(dict(GOFF, id=str(i)), 5) for i in range(30)}
    assert len(texts) >= 3


def test_out_and_no_game():
    out = dict(HIGGINS, flag="Out", injury="Out")
    assert writeup(out) == "He's listed Out (Groin), so he counts 0 this week."
    bye = dict(GOFF, note="No game this week", adj=[], range=None)
    assert writeup(bye) == "No game this week."


# ---------- Claude's write-ups (inputs/writeups.json from /writeups) ----------

from pipeline.writeups import attach_claude  # noqa: E402


def positions():
    return {"WR": {"players": [dict(HIGGINS)], "breaks": []}, "QB": {"players": [dict(GOFF)], "breaks": []}}


def test_claude_writeups_attach_for_this_week():
    pos = positions()
    file = {"season": "2026", "week": 5, "written": "2026-10-10T21:14:00Z",
            "players": {"6801": {"text": "Start him.", "status": "Questionable"},
                        "999": {"text": "Not in the data.", "status": ""}}}
    n = attach_claude(pos, file, "2026", 5)
    assert n == 1
    assert pos["WR"]["players"][0]["claude"] == {"text": "Start him.", "written": "2026-10-10T21:14:00Z"}
    assert "claude" not in pos["QB"]["players"][0]


def test_claude_writeups_from_another_week_are_ignored():
    pos = positions()
    file = {"season": "2026", "week": 4, "written": "x", "players": {"6801": {"text": "Old.", "status": ""}}}
    assert attach_claude(pos, file, "2026", 5) == 0 and "claude" not in pos["WR"]["players"][0]


def test_a_status_change_since_writing_is_flagged():
    pos = positions()
    pos["WR"]["players"][0]["injury"] = "Out"
    file = {"season": "2026", "week": 5, "written": "w", "players": {"6801": {"text": "Start him.", "status": "Questionable"}}}
    attach_claude(pos, file, "2026", 5)
    assert pos["WR"]["players"][0]["claude"]["changed"] == "Questionable -> Out"


def test_doubtful_leads_the_writeup():
    p = dict(GOFF, flag="Doubtful", injury="Doubtful", injury_detail="Knee")
    first = sentences(writeup(p, 5))[0]
    assert first == "He's Doubtful (Knee): My Score assumes he plays, so have a backup ready."
    assert 2 <= len(sentences(writeup(p, 5))) <= 4


def test_the_cut_to_four_sentences_keeps_my_score():
    p = dict(HIGGINS, flag="Doubtful", injury="Doubtful", cons={"rank": 90, "pts": 3.0},
             adj=[{"key": "matchup", "label": "Good matchup", "pts": 3.0, "why": "MIA allows a lot"}],
             score=15.0)
    text = writeup(p, 5)
    assert len(sentences(text)) == 4 and sentences(text)[-1] == "My Score: 15.0.", text
