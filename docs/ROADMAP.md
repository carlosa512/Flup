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
  off the projection's part, Doubtful flagged only (was 60%), Out 100%).
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
8. Doubtful: flagged only, no points off (owner, 2026-10-11; was 60%
   off). Never start Out/IR. No FAAB bid suggestions;
   show Sleeper's trending-adds count instead.
9. Keep the lean even when it lowers the bell-curve win % a little; the
   math box says so (owner, after piece 2).

## Open questions for the owner
None. Settled 2026-10-11: Doubtful is flagged only (settings
`[adjust.injury] doubtful = 0`; the card warns "likely sits", the write-up
leads with it); `always_break_gap` stays 1.5 (1.0 would split the top
TE/DEF tiers over 1-point gaps, smaller than a week-to-week swing).

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
  q, else 0", with q = My Score / healthy score. Doubtful now takes nothing
  off, so q = 1 and it's just his range. (At the old 60% off, his floor was
  0 and his ceiling the 75th percentile of his if-he-plays range.) Once he
  scores in a live game, any discount is dropped.
- A live DEF: points so far minus the bracket for the current score, plus
  the rest of his projection without its bracket part, plus the bracket
  blend for the points he's expected to allow by the end. Verified
  2026-10-11: Sleeper's live DEF line carries the bracket flag for the
  score so far, and its points include it. The bracket taken back is read
  from that line (none before Sleeper posts one).
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

Check 1 (2026-10-11, 10:45 AM, JAX-PHI Q2; captures on branch
`dev-raw-live`): ESPN parse, share left and live DEF brackets right; 23/23
players matched Sleeper when in sync. Found: Sleeper's matchup
`players_points` can trail its stats feed by up to ~5 min (Hurts 1.6 vs
10.08 after a TD pass). Live starters now count the stat line; finished
games count Sleeper's official points.

Check 2 (2026-10-11, 3:32 PM ET, eight 1 PM games in Q4): 99 players vs
Sleeper, every finished game exact; the 9 live differences are the
matchup-feed lag. Live DEF exact again (HOU 3 allowed, 1-6 bracket, 13.0 =
Sleeper). Browser live card = server (their total 156.5 both). Main's
scheduled runs hadn't fired yet; they started on their own at 3:42 PM ET
(the "Claude commit author" theory was wrong), with only 2 of ~8 slots
run that afternoon: GitHub drops scheduled runs under load. Also fixed
(PR #9): lineup rows/details/Tiers use the browser's live numbers too.

Check 3 (5:31 PM ET, 1 PM games final, late games in Q2/halftime): 96
players in finished games all match Sleeper (NYG-WAS overtime tie too);
halftime parses as half the game left; live DEFs exact (DEN 11.0, DET 5.0);
only 2 live players differ, by the matchup-feed lag. All Phase 3 live
leftovers are now checked on real Sunday data.

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

Phase 4 decisions (owner, 2026-10-11):
1. News: ESPN per-player news (public API, matched by ESPN ID from the
   DynastyProcess ID map) + Pro Football Talk RSS + one beat writer per
   team on Bluesky (Claude drafts the list, marked unverified; owner fixes).
   FantasyPros only if a public feed works. Feeds are tested on GitHub's
   runners first (tools/snapshot.py news probe -> dev-snapshots `news/`).
2. News for my roster, the opponent's starters and suggested free agents;
   at most 3 links, last 7 days, behind the tap.
3. Template write-ups made in Python, 2-4 sentences, shown first in a
   player's details (not on the main card), for every player.
4. "Copy for Claude": one button in each player's details, one at the
   bottom of Lineup (the whole matchup).
5. `/writeups` command pushes one data file straight to `main` (no PR);
   live in about 2 minutes.
6. Refresh: all three. Button re-downloads the newest data and shows the
   next run; extra Sunday runs during games (~every 30 min); live Sleeper
   points in the browser if CORS allows it.
7. Staleness: banner when data is old (>3 h on game day); "no injury news
   since ..." on a Questionable/Doubtful starter with no Sleeper news in
   the 24 h before kickoff (`news_updated` comes with projection rows).

Plan: 1 feed test -> 2 news links + staleness -> 3 template write-ups ->
4 Copy for Claude -> 5 /writeups command -> 6 refresh.

Status (2026-10-11): all six built on `claude/phase-4-news`, waiting for
the owner to try the preview. Feed test results: ESPN per-player, PFT and
RotoBaller RSS and Bluesky work; FantasyPros has no public feed (skipped,
RotoBaller instead); beat writers found for 28 teams (none for ATL, DAL,
LAC, TEN), unverified. Reviewed 2026-10-11 (code review + real-data
checks): fixed name matching (punctuation, possessives, a teammate's first
name), RotoWire notes collapsing into one, non-web links, write-ups losing
the My Score sentence, the browser's DEF fallback and missing-ESPN team,
"no news" for players who never had any; phone width checked with every
card open. Doubtful players keep their full My Score but are only started
when no healthy player fits the slot (owner, 2026-10-11); a benched one
who'd otherwise start shows first in close calls, marked "Doubtful".

New data (no version bump, all additions): players get `news_at`
(Sleeper's latest news time), `writeup` (template), `news [{title, source,
tag, date, url, paywall?}]` (my roster, their starters, suggested free
agents), `claude {text, written, changed?}` (from inputs/writeups.json).
`league.def_brackets` [[midpoint, pts]] (zeros included) for the live DEF
math in the browser; `refresh {crons, repo, scheduled}` for "next update";
`settings.stale_game_day_hours`, `settings.injury_news_hours`.

## Phase 5: polish (merged, PR #9)
Phase 4 merged as PR #6 on 2026-10-11; Phase 5 as PR #9 the same day.

Decisions (owner, 2026-10-11), all built and merged:
1. Week 17 rest flag: players on a team that has clinched the #1 seed
   (ESPN standings clincher "*"), flag only, shown in weeks 16-17
   (settings `[rest]`). Card warning, "May rest" chip, Copy for Claude line.
   Tested on last season's real final standings (tests/fixtures).
2. Data runs during Thursday and Monday night games, and Saturdays in
   December/early January (fantasy playoffs), every 30 min.
3. Live card: "so far · N to play" under each total.
4. Lineup tab colors by group (owner's ask): starters solid green, bench
   outlined green, free agents blue, opponent purple (edge, slot pill,
   section-header dot).
5. Small circle headshots before names (owner's nice-to-have): Sleeper's
   image server (`sleepercdn.com/content/nfl/players/thumb/<id>.jpg`, team
   logos `images/team_logos/nfl/<team>.png` for DEF), no key, a grey
   silhouette while loading or when there's no photo.

## Phase 5b: more polish (on `claude/phase-5-polish`, restarted from main)
Owner's picks, 2026-10-12 ("Playing now" to match the starters' rows;
the lock everywhere for consistency):

1. Built, on the preview: a small drawn padlock (not the emoji, which
   already means "paywall" in news) before Played / Live / Started on
   every player row (Tiers, both lineups, bench, free agents) and on
   crossed-out moves. Tiers and free-agent rows say Started once kickoff
   passes (or he has points) instead of the kickoff time. Postponed or
   canceled games never count as started (ESPN files them as state
   "post", so the live scoreboard is checked for that first).
2. Built: free agents whose game is on or over say "Playing now" /
   "Game played" / "Game started"; postponed: "No game this week" (was
   "His game has started: one to grab for later weeks").
3. Built: the "may rest" flag also covers division winners (`[rest]
   clinchers = ["*", "z"]`). Their line adds "if its seed is locked":
   only the #1 seed's place is surely settled.
4. In progress: beat writers. tools/snapshot.py now checks every
   configured Bluesky account plus candidates on GitHub's runner (own
   posts in the last 14 days: `news/bsky_beat_check.json` on
   dev-snapshots), and fetches three other free per-team feeds for ATL,
   DAL, LAC, TEN (`news/feeds/`). Web research (2026-10-12) confirmed 28
   of the 39 configured handles; 11 weren't checked. Candidates:
   - ATL: willmcfadden (Falcons site), marcraimondi (ESPN, quiet on
     Bluesky), danielflick (AJC since May 2026), thefalcoholic (SB Nation)
   - DAL: saadyousuf126 (The Athletic, active Oct 2026), calvinwatkins and
     joejhoyt (Dallas Morning News, quiet)
   - LAC: elliottteaford (OC Register)
   - TEN: paulkuharsky (PaulKuharsky.com), jwyattsports (Titans site).
     Teresa Walker (AP) has retired.
   - League-wide accounts that would cover every team: rotoworld-fb,
     rotowirenfl, rapsheet, insidenflnews, nflnewsposter (needs a small
     news.py change: they're not per team).
   Other free sources: official team sites (`www.<club>.com/rss/news`),
   SB Nation blogs (`www.<blog>.com/rss/index.xml`), Google News search
   RSS (redirect links, so the paywall tag can't match; undocumented,
   may rate-limit). The owner picks once the runner's results are in.
5. EPA: the original request says "nflverse ... routes ... EPA". nflverse
   was dropped (routes aren't free), so EPA never came in. The owner
   doesn't remember asking; parked unless they want it.
6. Still open: reload once when a new version takes over (first open
   after a deploy shows the old app), and check that the Thu/Mon-night
   scheduled runs fire (Monday 2026-10-12, Actions history).
