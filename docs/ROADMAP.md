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

## Open questions for the owner
- Doubtful: spec says "flag"; currently flagged AND 60% off
  (`[adjust.injury] doubtful`). Owner hasn't confirmed.
- `always_break_gap` = 1.5 for tiers (1.0 splits TE/DEF tops more).


Phase 3 decisions (owner, 2026-10-10):
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
Eastern date, the fallback when ESPN doesn't load).

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

## Phase 3: lineup, win %, close calls, waivers (in progress)

Built in pieces on `claude/phase-3-planning-z9glru`:
1. Done: Lineup tab with win %, mode, totals, the math, changes from the
   Sleeper lineup, one-line reasons, their lineup behind a tap
   (pipeline/lineup.py; live/finished/locked games are already handled).
2. Close calls (case for each side, behind a tap) + late-swap tip; more
   depth in the player rows (owner: "feels flat").
3. Done: bench FLEX options + free agents with Boom/Steady labels,
   kickoff, trending count, FAAB left and "Maybe on waivers" (from this
   league's transactions, this week and last). New Sleeper calls:
   `/v1/players/nfl/trending/add?lookback_hours=48&limit=50` and
   `/v1/league/<id>/transactions/<week>` (both optional; a failure shows in
   the sources list). Checked against the first real capture (Oct 11):
   formats match.
4. Sunday afternoon: app marks players whose kickoff passed while viewing;
   check live/locked handling against a real Sunday dev-raw capture.

From the spec ("Win probability and boom/bust" and "What the dashboard
shows" 1-3 and 6):
1. **Recommended lineup** from my roster for the league's slots (QB, 2 RB,
   2 WR, TE, 2 FLEX of RB/WR/TE, K, DEF) using My Score; never start Out/IR;
   one-line reason per starter.
2. **Win %** = Φ((my total - opponent total) / sqrt(my variance + their
   variance)), player sd from `range.sd` (assumes independence; QB-WR
   stacks make it slightly overconfident; say so). Opponent lineup: their
   set starters from Sleeper matchups if set, else their best lineup.
3. **Mode**: favored (65%+) lean on floor, underdog (under 35%) lean on
   ceiling, else median. Thresholds in settings.toml. Show plainly at the
   top, e.g. "Favored 68%: playing it safe".
4. **Close calls**: any start/sit within ~1.5 pts, with the case for each
   side (from the adjustments and floor/ceiling).
5. **FLEX options** from the bench, plus 3-5 **free agents** worth starting
   or grabbing, labeled boom/bust. The owner is the most active waiver user
   in the league; lean into it (Sleeper trending adds
   `/v1/players/nfl/trending/add` are free; FAAB is $200, consider showing
   bid context only if the owner wants it).
6. **Late-swap tip**: put the latest-kickoff eligible player in FLEX.
7. Top of the page answers first: lineup, win %, my total vs theirs.

Things Phase 3 will need:
- Current starters: build.py already fetches `sleeper.rosters` and this
  week's `sleeper.matchups`, but league.context keeps only owners and the
  opponent. Both have `starters`: player ids in roster_positions order,
  "0" for an empty slot, DEF ids are team codes like "HOU". They're always
  set (carried over from last week). Add both teams' starters to
  latest.json and show my lineup as changes from my current Sleeper
  starters.
- Locked and finished games: a player whose game has started is locked
  (keep him in his slot). Finished: use actual `players_points` from this
  week's matchups (sd 0). Live: actual points plus My Score x the share of
  the game left (needs period/clock from espn.parse) or a simpler rule the
  owner OKs. Not started: My Score. In week 5 the opponent already had 43.7
  actual points from Thursday.
- Compute the lineup, win % and close calls in the pipeline (unit tests +
  replay). Time-based logic takes build()'s `now`; tests pass a fixed time.
  app.js only marks players whose kickoff passed while viewing.
- Win % needs an sd for every starter; `range` is null for no-projection /
  no-game players (score 0 anyway, use sd 0).
- The Sleeper players DB is probably not needed (every rostered player had
  a projection row in week 5). If it is: `/v1/players/nfl` is ~15 MB raw /
  ~2 MB gzipped and Sleeper asks for at most one call a day. A copy is on
  `dev-snapshots` (sleeper/players_nfl.json.gz), as are trending adds
  (sleeper/trending_add.json).
- Anything the pipeline newly fetches lands in `dev-raw` on the next
  `claude/**` run; add it to tools/snapshot.py too if a test needs it.
- Bump the data version (and DATA_VERSION in app.js) if the shape changes.

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
