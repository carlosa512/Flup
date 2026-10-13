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
