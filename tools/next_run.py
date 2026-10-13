#!/usr/bin/env python3
"""When the next data update is due, from update.yml's cron lines (UTC).

GitHub drops most scheduled runs (on 2026-10-11 only 4 of about 24 Sunday
slots ran), so the Ticker workflow keeps a chain going instead: each link
waits here for the next slot, starts update.yml, then starts the next link.

    python3 tools/next_run.py               print the next slot
    python3 tools/next_run.py --wait HOURS  wait for it, at most HOURS; then
                                            print due=true (or due=false if
                                            it's further off) for $GITHUB_OUTPUT
"""

import argparse
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.build import workflow_crons  # noqa: E402


LOOK_BACK = 3      # minutes
HAND_OVER = 600    # seconds before a far-off slot that the next link takes over


def matches(spec, value):
    """One cron field ("7,37", "17-23", "*/4", "*") against a value."""
    for part in spec.split(","):
        rng, _, step_text = part.partition("/")
        step = int(step_text) if step_text else 1
        if rng == "*":
            lo, hi = 0, 99
        elif "-" in rng:
            lo, hi = (int(x) for x in rng.split("-"))
        else:
            lo = int(rng)
            hi = 99 if step_text else lo
        if lo <= value <= hi and (value - lo) % step == 0:
            return True
    return False


def next_slot(crons, now):
    """The first minute after now (UTC) that any cron line matches, within 8
    days, or None. Same rules as the app's nextRun (site/app.js)."""
    fields = [c.split() for c in crons if len(c.split()) == 5]
    t = now.astimezone(timezone.utc).replace(second=0, microsecond=0)
    for _ in range(8 * 24 * 60):
        t += timedelta(minutes=1)
        values = (t.minute, t.hour, t.day, t.month, (t.weekday() + 1) % 7)  # cron: Sunday = 0
        if any(all(matches(spec, v) for spec, v in zip(f, values)) for f in fields):
            return t
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", type=float, metavar="HOURS", help="wait for the next slot, at most this long")
    args = ap.parse_args()
    now = datetime.now(timezone.utc)
    # A link that starts a minute or two late (runner pickup, a restart)
    # still takes the slot it just missed; the Ticker won't start an update
    # twice in 10 minutes
    slot = next_slot(workflow_crons(), now - timedelta(minutes=LOOK_BACK))
    if slot is None:
        print("no cron lines found", file=sys.stderr)
        if args.wait:
            time.sleep(args.wait * 3600)  # never a tight loop of links
            print("due=false")
        return
    print(f"Next update slot: {slot:%a %Y-%m-%d %H:%M} UTC", file=sys.stderr)
    if not args.wait:
        print(slot.isoformat())
        return
    wait = (slot - now).total_seconds()
    if wait > args.wait * 3600:
        # Further off: wait most of it and hand over to the next link, which
        # then starts well before the slot
        time.sleep(max(60.0, min(args.wait * 3600, wait - HAND_OVER)))
        print("due=false")
    else:
        time.sleep(max(0.0, wait))
        print("due=true")


if __name__ == "__main__":
    main()
