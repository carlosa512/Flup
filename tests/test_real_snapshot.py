"""Runs only when FLUP_REPLAY points at a saved snapshot of real responses
(tools/snapshot.py). Proves the scoring engine against Sleeper's official
points for every finished week in it."""

import json
import os
from pathlib import Path

import pytest

SNAP = os.environ.get("FLUP_REPLAY")
pytestmark = pytest.mark.skipif(not SNAP, reason="no FLUP_REPLAY snapshot")


def test_rescoring_matches_official_points():
    from pipeline import sleeper
    from pipeline.validate import rescore_check

    index = json.loads((Path(SNAP) / "index.json").read_text())
    lg = sleeper.league(index.get("league_id", "1374496898462785536"))
    weeks = [int(f["file"].split("_")[1].split(".")[0]) for f in index["files"]
             if f["file"].startswith("sleeper/matchups_")]
    checked = 0
    for wk in sorted(weeks)[:-1]:  # the last one is the current, unplayed week
        r = rescore_check(sleeper.stats(index["season"], wk),
                          sleeper.matchups(lg["league_id"], wk), lg["scoring_settings"])
        assert r["misses"] == [], f"week {wk}: {r['misses']}"
        checked += r["checked"]
    assert checked > 0
