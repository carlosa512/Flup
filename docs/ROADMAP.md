# Roadmap

Phases are built one at a time: clarifying questions -> plan -> owner's OK
-> build on a `claude/**` branch -> owner tries the preview site -> owner
merges. Each phase is reviewed (bugs, modeling, data, phone UI) before it's
handed over.

## Done

### Phase 1: tiers in the league's scoring (merged, PR #1)
- Sleeper projections rescored with the league's settings; settings check
  (12 rules) and scoring check (finished weeks vs Sleeper's official points,
  755/755 so far) behind the "Data from ... / ✓ All checks pass" line.
- Local-gap tiers per position; filters All / My team / Free agents / My
  matchup; your players green, opponent's purple.
- ESPN Vegas lines (spread, total, implied team total) and kickoff times.
- Scheduled GitHub Actions runs; GitHub Pages; add-to-home-screen app with
  instant load from the saved copy; dark by default with a light toggle.

### Phase 2: My Score (merged, PR #2)
- Blend: 60% projection + 40% FantasyPros consensus rank turned into points
  with a curve built from the league's own scoring.
- Capped adjustments, each with a one-line reason (settings.toml
  `[adjust.*]`): usage trend (snap/target/carry share, last 3 games vs
  season), game environment (implied total + spread script), matchup
  (points allowed to the position, shrunk early in the season), QB habits
  (penalty for picks above league rate, bonus for low-INT runners), return
  men (bump + return yards the projection lacks), injury (Questionable 8%
  off the projection's part, Doubtful 60%, Out 100%, flagged).
- Floor/ceiling (25th/90th percentile) from each player's weekly scores in
  league scoring (this season + last 12 games of last season), scaled to
  this week's score, shrunk toward the position's typical spread; backup-role
  games ignored. `range.sd` is stored for win probability (every kicker and
  player with a game has one).
- Player card: score + floor/ceiling, blend line, adjustments of 0.5+ shown
  (smaller ones folded), projection math behind a tap, game, tier.

### Phase 3: lineup, win %, close calls, free agents (PR #4)
- Lineup tab (the app opens on it; Tiers is the other tab): win % and
  mode at the top ("Underdog 15%: swinging for upside"), my total vs
  theirs, the math behind a tap, the best lineup with a one-line reason
  per starter, the changes to make in Sleeper (slides first), their
  lineup as set behind a tap. pipeline/lineup.py.
- Close calls (case for each side behind a tap), late-swap tip (with a
  deadline), bench options and up to 5 free agents with Boom/Steady,
  trending adds, FAAB left, "Dropped Fri: maybe on waivers".
- Game phases: finished = Sleeper's points, live = points so far + My
  Score x share left (ESPN quarter/clock), locked starters stay. Without
  ESPN, Sleeper points/game dates decide (and the page says so).
- Played players: real points and their breakdown first (owner's idea);
  the big number in Tiers becomes the real score with "My Score" small.
  The app marks kickoffs that pass while it's open ("Started"), crosses
  out moves Sleeper has locked and hides their close calls.
- Card-style player rows (design panel + judge; owner: "feels flat"),
  FLEX pills show the real position, tiers grouped in one card each.
- Reviewed twice by multi-angle reviews with skeptics; fixes for Doubtful
  percentiles, live DEF brackets, ESPN-down fallback, change pairing,
  rounding, bye-week empty slots, label math.

Phase 3 decisions (owner, 2026-10-10/11):
1. Favored/underdog leans **halfway**: players are ranked by My Score moved
   `[lineup] lean` (0.5) of the way to the floor (favored, "safe score") or
   ceiling (underdog, "upside score"). Win % from the My Score lineup sets
   the mode; the final win % is from the re-picked lineup.
2. Close calls: within 1.5 pts (`[lineup] close_call`) on the number the
   mode uses.
3. Boom/bust label: "Boom" when ceiling/score is well above the position's
   usual ratio, "Steady" when floor/score is. No label otherwise.
4. Two tabs, Lineup | Tiers; the app always opens on Lineup.
5. Free agents are instant adds in this league (only recently dropped
   players go through waivers): a free agent can start this week if his
   game hasn't kicked off.
6. Opponent lineup is used **exactly as set** in Sleeper (an Out starter
   counts 0).
7. Live games: points so far + My Score x share of the game left (quarter
   and clock from ESPN); sd x sqrt(share left). Finished: actual points.
8. Doubtful stays 60% off. Never start Out/IR. No FAAB bid suggestions;
   show Sleeper's trending-adds count instead.
9. Keep the lean even when it lowers the bell-curve win % a little; the
   math box says so (owner, after piece 2).

## Open questions for the owner
- Doubtful: spec says "flag"; currently flagged AND 60% off
  (`[adjust.injury] doubtful`). Owner hasn't confirmed.
- `always_break_gap` = 1.5 for tiers (1.0 splits TE/DEF tops more).

## What the data already has (site/data/latest.json, version 3)

Per player (in `positions[POS].players`): `id, name, pos, team, opp, home,
kickoff, game_status, implied, spread, injury, injury_detail, proj, parts,
roster (roster_id or null = free agent), rank, tier, score, base, blend,
note, cons {rank, pts, url}, adj [{key,label,pts,why}], range {floor,
ceiling, sd, games, if_plays?}, flag`.
League: `id, name, teams {"rid" (string keys "1".."12"): name, user, wins,
losses, ties, points_for, faab_left}`, `my_rid` / `opp_rid` (ints, same as
player `roster`; in Python use `teams[str(rid)]`), `roster_positions`,
`scoring`. Top level: `version, generated, season, week, league, sources,
checks, settings, positions, lineup, games`. `positions[POS]` =
`{players, breaks}`. `games[]` also has `state` (pre/in/post),
`completed`, `period`, `clock` (seconds left in the quarter),
`score_home`, `score_away`. Players also carry `game_date` (Sleeper's
Eastern date, the fallback when ESPN doesn't load), and once they've played
or are playing this week `actual {pts, parts, official}`: this week's real
stat line from Sleeper's stats endpoint scored with the league's settings
(`parts` like the projection's), plus Sleeper's own points for rostered
players (`official`, shown first; the card says so when they differ).

`lineup` (null if my team isn't found): `slots` (starting slots only),
`mode` (favored/underdog/even), `win` (final, null without an opponent),
`lean, favored, underdog, close_call`, `first {total, sd, win}` (the My
Score lineup that set the mode), `me` and `opp` = `{total, sd, starters}`
(`opp` null without an opponent), `current` (my Sleeper starter ids, "0" =
empty), `moves [{id, to}]` (kept starters who must slide first so a
newcomer's slot opens), `changes [{slot, in, out}]` (`in` or `out` may be
null), `times_known` (false = ESPN didn't load; anyone with Sleeper points
counts as played). Each
starter: `slot, id (null = empty), pts, sd, state (pre/live/final/none/
empty/unknown), actual, left`; mine also `why, new, replaces?`.
`close_calls [{slot, start, bench, gap, measure, values [start, bench],
for_start [text], for_bench [text]}]`: each healthy, not-yet-played bench
player vs the weakest starter he could replace, kept when `gap` (on the
mode's number: My Score / upside score / safe score) is under
`close_call`; at most 2 per starter and 4 in all. `late_swap` (null when
FLEX already has the latest games or no rearrangement can):
`{moves [{id, to}], latest, kickoff, deadline}`, same starters, slots only;
`deadline` is the earliest kickoff among the moved players (the app hides
the tip after it). `bench_flex [{id, value, behind, gap, label, why}]`: my
best 3 healthy, not-yet-played bench RB/WR/TE. Bench players and free
agents are compared with the weakest not-yet-played starter in a slot they
can play (the close-call rule); an empty slot counts as 0. `gap` = his
number minus that starter's (negative = behind); in a leaned mode `why`
shows both numbers. `free_agents [{id, value, can_start, start_over,
fills, gap, label, trending, dropped, why}]` (settings `[lineup]
free_agents`, default 5): first those who fill an empty slot or beat the
starter they'd replace (biggest gap first; K/DEF/QB only then), then the
best RB/WR/TE, players whose game started last; at most 2 per position.
Doubtful players get no label. Trades aren't counted as drops. `label` is "Boom" / "Steady" / "" (settings `[labels]`:
ceiling/score or floor/score vs the position's usual from
model.position_ratios). `trending` = Sleeper adds in all leagues over 48h;
`dropped` = when he was dropped in this league, if within
waiver_clear_days + 1 day (shown as "Maybe on waivers").

Modeling notes (from the Phase 3 review):
- A Doubtful player's floor/ceiling are percentiles of "plays with chance
  q, else 0": floor 0 at 60% off; ceiling = the 75th percentile of his
  if-he-plays range (a bell curve through floor/healthy/ceiling). Once he
  scores in a live game, the discount is dropped.
- A live DEF: points so far minus the bracket for the current score, plus
  the rest of his projection without its bracket part, plus the bracket
  blend for the points he's expected to allow by the end. Assumes Sleeper's
  live DEF points include the current points-allowed bracket: verify on a
  real Sunday capture (piece 4).
- The mode is decided on the whole percent shown, so "35%" is never called
  "under 35%"; a close call's gap is the difference of the two numbers as
  shown.

Nullable: `range` (players with no projection or no game; their `note`
says which), `cons` (no consensus rank), `tier` (below the top-N cut).
Only the top N per position (settings `[positions]`) plus every player on
my roster or my opponent's is included. In week 5 that covered every
rostered player on both teams, including IR and bye players (score 0 with a
note), because Sleeper gives them projection rows too.

## Phase 3 leftovers: check live scoring on a real Sunday
Nothing here was seen on real live data yet (only Thursday finals, which
matched Sleeper 11/11). During a Sunday's games, trigger update.yml on the
branch (GitHub MCP `actions_run_trigger`, `run_workflow`, ref = the
branch), wait for `dev-raw` to change, keep a copy of each capture (it's
overwritten by the next run), replay it and check:
1. ESPN live parse: `state` "in", `period`, `clock` (seconds left in the
   quarter), `score_home`/`score_away`; lineup phase "live" with a
   sensible share left; halftime/end-of-quarter statuses.
2. Live totals: Sleeper `players_points` so far + My Score x share left.
3. **Live DEF assumption**: lineup._live_def assumes Sleeper's live DEF
   points already include the bracket for the current points allowed.
   Compare a live DEF's `players_points` with score_line on its live stat
   line (does the live line carry pts_allow_* flags?). Fix if wrong.
4. `actual` breakdowns vs Sleeper's points (should match; a stat
   correction can lag), "Started" marks in the app at the right times.
Good times (Eastern): ~10:45 AM if there's a London game, ~2:30 PM (1 PM
games live), ~5:30 PM (1 PM final, late games live).

## Phase 4: news, write-ups, refresh
- News links per player from RSS/public feeds (ESPN, Pro Football Talk,
  beat writers' Bluesky RSS, etc.): headline, source, date, link only;
  tag each "beat reporter" or "aggregator"; paywalled sites link-only.
  If a feed is down or against its terms, tell the owner. The consensus
  data already carries each player's FantasyPros page URL (`cons.url`).
- Template write-ups (2-4 sentences from the breakdown; lead with the
  biggest factor; say where consensus disagrees and why; vary wording; only
  real numbers).
- "Copy for Claude" buttons (player and full lineup) with all inputs.
- A Claude Code command (`.claude/commands/writeups.md`) the owner runs on
  their subscription to write smarter write-ups for starters and close calls
  into a data file the site prefers over templates.
- Refresh button: live Sleeper fetch in the browser if CORS allows
  (unverified), else show the next scheduled run and link to "Run workflow".
- Staleness warnings, e.g. injury news older than 24h before kickoff.

## Phase 5: polish
- Week 17 flag: players on teams that may rest starters (clinched teams).
- Anything left over from the owner's feedback.
