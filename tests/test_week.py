import gzip
import json
import os
from pathlib import Path

import pytest

from pipeline import build, espn
from pipeline.fetch import FetchError

# Sleeper's state right after Monday night's game, 2026-10-13 04:44Z (dev-raw)
STATE = {"week": 6, "leg": 6, "season": "2026", "display_week": 5}


def games(*states):
    return [{"completed": s == "post" and status != "STATUS_POSTPONED", "state": s, "status": status}
            for s, status in states]


def test_once_the_last_game_is_over_it_shows_next_week():
    sb = lambda season, week: games(("post", "STATUS_FINAL"), ("post", "STATUS_FINAL"))
    assert build.pick_week(STATE, "2026", sb) == (6, None, True)


def test_while_a_game_is_left_it_stays_on_this_week_and_keeps_the_games():
    left = games(("post", "STATUS_FINAL"), ("in", "STATUS_IN_PROGRESS"))
    assert build.pick_week(dict(STATE, week=5), "2026", lambda s, w: left) == (5, left, False)


def test_a_postponed_game_doesnt_hold_the_week_back():
    sb = lambda season, week: games(("post", "STATUS_FINAL"), ("post", "STATUS_POSTPONED"))
    assert build.pick_week(STATE, "2026", sb)[0] == 6


def test_without_espn_it_goes_by_sleepers_own_week():
    def down(season, week):
        raise FetchError("ESPN down")
    assert build.pick_week(STATE, "2026", down) == (6, None, True)
    assert build.pick_week(dict(STATE, week=5), "2026", down) == (5, None, False)


def test_the_last_regular_season_week_stays_put():
    st = {"week": 18, "display_week": 18, "season": "2026"}
    assert build.pick_week(st, "2026", lambda s, w: games(("post", "STATUS_FINAL")))[0] == 18


@pytest.mark.skipif(not os.environ.get("FLUP_RAW"), reason="needs FLUP_RAW (a dev-raw copy)")
def test_real_week_5_scoreboard_after_monday_night():
    root = Path(os.environ["FLUP_RAW"])
    files = json.loads((root / "index.json").read_text())["files"]
    raw = next(f for f in files if "scoreboard" in f["url"] and "week=5" in f["url"])
    week5 = espn.parse(json.loads(gzip.decompress((root / raw["file"]).read_bytes())))
    assert build.pick_week(STATE, "2026", lambda s, w: week5) == (6, None, True)
