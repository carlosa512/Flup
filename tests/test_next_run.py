import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import next_run  # noqa: E402

from pipeline.build import workflow_crons  # noqa: E402

UTC = timezone.utc


def test_cron_fields():
    assert next_run.matches("7,37", 37) and not next_run.matches("7,37", 8)
    assert next_run.matches("17-23", 20) and not next_run.matches("17-23", 0)
    assert next_run.matches("*/3", 21) and not next_run.matches("*/3", 22)
    assert next_run.matches("*", 5) and next_run.matches("12,1", 1)


def test_next_slot_from_the_real_schedule():
    crons = workflow_crons()
    # Monday 2026-10-12 11:50 PM ET (03:50Z Tue): the Monday-night slots run to 04:37Z
    assert next_run.next_slot(crons, datetime(2026, 10, 13, 3, 50, tzinfo=UTC)) == \
        datetime(2026, 10, 13, 4, 7, tzinfo=UTC)
    # After the last Monday-night slot: Tuesday about 7 AM Eastern
    assert next_run.next_slot(crons, datetime(2026, 10, 13, 4, 40, tzinfo=UTC)) == \
        datetime(2026, 10, 13, 11, 7, tzinfo=UTC)
    # Sunday during the games: every 30 minutes
    assert next_run.next_slot(crons, datetime(2026, 10, 18, 18, 8, tzinfo=UTC)) == \
        datetime(2026, 10, 18, 18, 37, tzinfo=UTC)
    # Exactly on a slot: the following one, never the same minute twice
    assert next_run.next_slot(crons, datetime(2026, 10, 18, 18, 37, 30, tzinfo=UTC)) == \
        datetime(2026, 10, 18, 19, 7, tzinfo=UTC)


def test_saturdays_only_in_december_and_january():
    crons = workflow_crons()
    # Saturday 2026-10-17 midday: no Saturday games yet, next is Sunday 11:45 AM ET
    assert next_run.next_slot(crons, datetime(2026, 10, 17, 17, 0, tzinfo=UTC)) == \
        datetime(2026, 10, 18, 15, 45, tzinfo=UTC)
    # Saturday 2026-12-19: every 30 minutes from about 1 PM ET
    assert next_run.next_slot(crons, datetime(2026, 12, 19, 17, 0, tzinfo=UTC)) == \
        datetime(2026, 12, 19, 17, 7, tzinfo=UTC)


def run_main(monkeypatch, capsys, now, hours=5.5):
    slept = []

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr(next_run, "datetime", Clock)
    monkeypatch.setattr(next_run.time, "sleep", slept.append)
    monkeypatch.setattr(sys, "argv", ["next_run.py", "--wait", str(hours)])
    next_run.main()
    return capsys.readouterr().out.strip(), slept


def test_the_link_started_right_after_a_slot_waits_for_the_next_one(monkeypatch, capsys):
    # Seen 2026-10-13: the link started by the 11:07 one must not take 11:07
    # again (17 links in 3 minutes did). Sunday 18:37:10Z: 18:37 just ran
    out, slept = run_main(monkeypatch, capsys, datetime(2026, 10, 18, 18, 37, 10, tzinfo=UTC))
    assert out == "due=true" and slept == [29 * 60 + 50]   # 19:07
    # Tuesday 11:07:10Z: next is 12:07Z (7 AM is listed for both EDT and EST)
    out, slept = run_main(monkeypatch, capsys, datetime(2026, 10, 13, 11, 7, 10, tzinfo=UTC))
    assert out == "due=true" and slept == [59 * 60 + 50]


def test_a_far_off_slot_hands_over_ten_minutes_early(monkeypatch, capsys):
    # Friday 2026-10-16 12:00Z: next is Friday 22:07Z (about 6 PM Eastern), 10 h away
    out, slept = run_main(monkeypatch, capsys, datetime(2026, 10, 16, 12, 0, tzinfo=UTC))
    assert out == "due=false" and slept == [5.5 * 3600]
    # 5 h 35 min before it: wait 5 h 25 min, so the next link wakes 10 min ahead
    out, slept = run_main(monkeypatch, capsys, datetime(2026, 10, 16, 16, 32, tzinfo=UTC))
    assert out == "due=false" and slept == [5 * 3600 + 25 * 60]
