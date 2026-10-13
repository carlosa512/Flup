---
description: Write Claude write-ups for this week's starters and close calls, check them, and publish them to the Flup site
---

Write smarter write-ups for this week's Flup lineup and publish them. The
site shows them in place of the template write-ups. Work through these
steps in order, and keep messages to the owner short (they read on a phone).

## 1. Get the live data

```
git fetch origin gh-pages main
git show origin/gh-pages:data/latest.json > /tmp/latest.json
```

This is the data the live site shows right now. Read `generated`, `week`,
`season`, `league` (my team is `my_rid`) and `lineup` from it.

## 2. Pick the players

- Every starter in `lineup.me.starters` (skip empty slots).
- Both players in every `lineup.close_calls` entry.
- Everyone in `lineup.bench_flex` and the first 3 of `lineup.free_agents`.

Find each player in `positions[POS].players` by `id`.

## 3. Write 2-4 sentences per player

For each one, read his whole entry: `score` (Predicted: the card calls it that, never "My Score"), `proj` (Sleeper's
projection in this league's scoring), `cons` (expert rank and its points),
`base` (projection and expert points blended; `blend` says how), every `adj` (label, pts, why), `range` (floor,
ceiling), `injury`, `implied`/`spread`, `news` (headlines), and `writeup`
(the template version, to improve on). Then write:

1. Lead with the biggest factor (whatever moves him most from the
   projection), in plain words.
2. Say where the experts disagree with Sleeper and why the prediction differs.
3. Anything from his news headlines or the matchup that matters (who's
   out, his role, the game script), naming the source.
4. For a close call, compare him with the other player directly.

Rules:
- Only use numbers that are in the data (his entry, the lineup, the
  scoring). Rounding a real number is fine. Don't invent stats.
- If you add something you know from outside the data, say so
  ("Not in the data: ...") and keep it to one clause.
- Get his role from `lineup.me.starters`: starters start, everyone else
  is bench or a free agent (the checker flags a mismatch).
- Plain words, no betting language, vary the wording between players.
- At most about 600 characters each.

## 4. Save the file

Write `inputs/writeups.json`:

```json
{
  "season": "<season from the data>",
  "week": <week from the data, a number>,
  "written": "<now, UTC ISO like 2026-10-10T21:14:00Z>",
  "data_generated": "<generated from the data>",
  "players": {
    "<player id>": {"text": "<the write-up>", "status": "<his injury field, \"\" if healthy>"}
  }
}
```

## 5. Check it

```
python3 tools/check_writeups.py inputs/writeups.json /tmp/latest.json
```

Fix every PROBLEM it prints (usually a number that isn't in his data) and
run it again until it says 0 problems.

## 6. Publish to main

The owner chose to publish write-ups straight to `main`, with no pull
request (Phase 4 decision, 2026-10-11). Only this one file is committed:

```
git checkout main && git pull origin main
git add inputs/writeups.json
git commit -m "Add Claude write-ups for week <week>"
git push origin main
```

If a different branch is checked out with other work, stash or commit that
work on its own branch first; never commit anything but
`inputs/writeups.json` to `main` here. The push runs "Update data", and
the site shows the write-ups in about 2 minutes (close the app fully and
reopen it twice if it still shows the old ones).

## 7. Tell the owner

Three short lines: how many write-ups, the one most worth reading (a close
call or a big disagreement), and that the site updates in about 2 minutes.
