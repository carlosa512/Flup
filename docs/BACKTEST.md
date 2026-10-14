# Backtest: does advanced data make Predicted better? (2026-10-13)

Owner's question (Phase 7): nflverse publishes free EPA, CPOE, WOPR and
more. Add them only if they make Predicted points or the Boom/Steady
labels more accurate.

Short answer: they don't. The test turned up fixes to the current model
instead (usage trend and RB/WR matchup off, a capped return-man rule, a
wider spread), checked on both halves of 2025 and on 2026 so far. This
page was corrected after a review (see "Review corrections" at the end).

## How it was tested

`tools/backtest.py` rebuilds Predicted for every week of the 2025 season
(and 2026 so far) from what was known before that week, the same way the
site does:

- Sleeper's projection for the week, rescored in our scoring. Sleeper keeps
  each week's last pre-game projection: re-fetched 2026 week 5 projections
  matched a copy saved on game day exactly for all 181 players whose games
  had started (only not-yet-started games had changed).
- The adjustments (usage, Vegas game environment from nflverse's closing
  lines, matchup, QB habits, return men) and floor/ceiling, with the
  season before as "last season".
- Left out: the FantasyPros blend (no free history of weekly ranks) and
  injury status (Sleeper's player info is today's, not that week's).

Then, against what really happened (2025 weeks 4-18, 2026 weeks 2-4;
players who played and were projected at least QB 8, RB/WR 4, TE/K/DEF 3):

- **Average miss**: |real − predicted|.
- **Close calls**: same position, same week, within 1.5 pts on Sleeper's
  projection (the same pairs for any version of the model): how often the
  one predicted higher really scored more (50% = coin flip).
- **Both halves**: anything fitted is fitted on weeks 4-11 and checked on
  12-18, and the other way round. A change counts only if it helps in both.
  2026 weeks 2-4 (none of the choices were tuned on them) is a last check.

Rerun: `python3 tools/backtest.py SNAP_DIR NFLVERSE_DIR --season 2025`
(dev-snapshots branch; nflverse files listed in the tool's docstring).

## What it found

### 1. nflverse's advanced stats don't make Predicted more accurate

Tried: passing EPA per dropback, CPOE, rushing EPA per carry, EPA per game,
WOPR (and its trend), air yards share, receiving EPA per target, aDOT,
RACR, defenses' EPA allowed per play, the QB's EPA for his receivers, and
the opponent's offensive EPA for defenses. None moved the average miss by
more than about 0.05 pts in both halves; most did nothing or flipped
direction. Sleeper's projection already has this information.

### 2. Some current adjustments don't help

Slope of what Predicted missed (before the adjustment) on the adjustment's
points, per half (1 = right size, 0 = no help, negative = wrong way):

| Adjustment | Weeks 4-11 | Weeks 12-18 | Verdict | Now |
|---|---|---|---|---|
| Usage trend, RB | −1.70 | −0.48 | wrong way | off |
| Usage trend, WR | −0.53 | +0.45 | flips | off |
| Usage trend, TE | −1.48 | +0.61 | flips | off |
| Matchup, RB | +0.38 | −1.16 | flips | off |
| Matchup, WR | −1.28 | +0.43 | flips | off |
| Matchup, TE | +1.30 | +0.09 | helps (close calls up both halves) | on |
| Matchup, QB | +0.39 | +1.17 | slope holds; average miss no better | off (2026-10-14) |
| Matchup, K | −0.57 | +1.17 | flips | off (2026-10-14) |
| Matchup, DEF | −0.57 | +0.66 | flips; average miss worse both halves | off (2026-10-14) |
| Game environment, QB/RB/WR/TE | +0.67 to +1.24 | +0.33 to +0.84 | helps | on |
| Game environment, K/DEF | −1.04 / −0.22 | +0.46 / +0.45 | unclear | on |

QB, K and DEF matchup fail the same test that turned it off for RB/WR (QB
on average miss, K and DEF on both); the owner turned them off on
2026-10-14, so matchup is now used for TEs only. The effect was small: 2025
average miss 5.270 → 5.262 and 5.088 → 5.085 (QB 8.32 → 8.30, DEF 4.82 →
4.79); close calls 54.2% → 54.6% and 55.6% → 55.2%; 2026 weeks 2-4 the
same average miss, close calls 53.8% → 53.6% (QBs 54.1% → 56.1%, DEFs
55.4% → 52.7% on 630 pairs).

### 3. The return man rule pointed the wrong way

| Return men (RB/WR/TE), 2025 | Games | Return pts projected | Predicted added | Really got |
|---|---|---|---|---|
| Projection has return yards | 211 | 1.13 | 0.30 | 2.33 |
| Projection has none | 96 | 0.00 | 2.11 | 0.92 |

Real return yards ran about double the projection at every level
(projected under 1 pt: 0.5 → 1.2; 1-2: 1.4 → 2.8; 2-3: 2.3 → 4.5). When the
projection had none, he had often lost the job (only 42% still returned),
so adding his recent yards overshot. But heavy returners' other points run
under their projection, so doubling their return points over-predicted
their totals (2026: −0.9). Counting the projection's return points again,
**up to 1.0**, kept return men's totals unbiased everywhere:

| Return rule | Bias 2025 wk 4-11 | 12-18 | 2026 wk 2-4 | rms miss (same three) |
|---|---|---|---|---|
| none | +0.87 | +1.09 | +0.96 | 5.76 / 6.20 / 5.63 |
| old (+0.3) | +0.48 | +0.75 | – | 5.73 / 6.13 / – |
| projected again, up to 1.0 (now) | +0.13 | +0.31 | +0.07 | 5.66 / 6.06 / 5.59 |
| projected again, up to 4.0 | −0.23 | −0.09 | −0.89 | 5.71 / 6.04 / 5.80 |

(The average miss of return men favors adding nothing, 4.39 vs 4.46,
because long returns come and go; Predicted aims at expected points, so
the bias and rms decide.)

### 4. "Give or take" and floor/ceiling were too narrow

Win % adds up each starter's sd, so the check is the spread of misses
divided by the sd (1.0 = right; weekly misses have fat tails, so the share
within ±1 sd runs above the bell curve's 68% even when the spread is
right). Floor = 25th percentile (25% of games at or under), ceiling =
90th (10% at or over).

| Pos | Spread of miss ÷ sd: before → after | Under floor: before → after | Over ceiling: before → after |
|---|---|---|---|
| QB | 1.19 → 0.99 | 32% → 27% | 13% → 10% |
| RB | 1.32 → 1.11 | 34% → 27% | 14% → 12% |
| WR | 1.21 → 1.00 | 38% → 32% | 12% → 9% |
| TE | 1.33 → 1.12 | 32% → 26% | 15% → 12% |
| K | 1.14 → 0.95 | 29% → 24% | 16% → 12% |
| DEF | 1.15 → 0.96 | 27% → 20% | 13% → 10% |

"After" = everything spread 1.2× as far from Predicted. 2026 weeks 2-4:
spread 1.12-1.38 before, 0.93-1.15 after. RB and TE are still about 10%
narrow, K and DEF about 5% wide; one setting for all keeps it simple. So win
% had been a bit too sure of itself: a 37% now reads about 39%, a 75%
about 71%.

### 5. Boom and Steady labels

- Nothing tested picks out big games (1.5× Predicted or more): every AUC is
  0.42-0.54 (0.5 = coin flip), including ceiling/score, which the Boom label
  uses. A high ceiling/score does weakly mean a swingier player (AUC 0.52-0.54
  for big-or-dud games), so leaning toward ceilings as the underdog still
  makes sense.
- Duds (under half of Predicted), AUC, lower = better: nflverse's WOPR vs
  floor/score (what Steady uses): TE 0.38 vs 0.44, WR 0.44 vs 0.46, RB 0.44
  vs 0.46. But as a yes/no label at a cutoff, it didn't hold up (below).
- WOPR from Sleeper's stats: Sleeper's air yards count catches only and go
  negative on screens, so a game's share is kept to 0-100% and games where
  the team's total is under 50 yards are skipped (one had made a share of
  250%). Then, for TEs, "Steady" at WOPR 0.45+ vs the floor rule: duds 20%
  vs 18% in weeks 4-11, 17% vs 29% in weeks 12-18, too few games in 2026.
  Not better in both halves, so it's **off** (`[labels] wopr_positions =
  []`); the code stays for another look with more data.
- The floor rule's Steady doesn't mean fewer busts for QBs and kickers
  (36% vs 23% and 31% vs 21% under the floor). Labels show only on bench and
  free-agent rows, mostly RB/WR/TE. Open.

## Built (owner's OK, 2026-10-13)

`settings.toml`: `[adjust.usage] positions = []`, `[adjust.matchup]
positions = ["TE"]` (QB/K/DEF turned off 2026-10-14, after the table
below), `[adjust.returns] extra = 1.0`,
`cap = 1.0`, `[floor_ceiling] stretch = 1.2`, `[labels] wopr_positions =
[]` (off, see 5).

Before (main) and after, through the real code, same 3,993 player-games
and the same close-call pairs:

| Pos | Avg miss: before → after (projection) | Close calls right: before → after (projection) |
|---|---|---|
| QB | 8.32 → 8.32 (8.33) | 55.2% → 55.2% (53.5%) |
| RB | 5.38 → 5.27 (5.31) | 53.1% → 53.7% (52.7%) |
| WR | 4.89 → 4.86 (4.85) | 55.5% → 56.3% (54.0%) |
| TE | 4.67 → 4.64 (4.66) | 53.3% → 54.4% (52.8%) |
| K | 3.85 → 3.85 (3.84) | 51.6% → 51.6% (51.0%) |
| DEF | 4.82 → 4.82 (4.79) | 55.5% → 55.5% (54.6%) |

| All positions | Avg miss: before → after | Close calls: before → after |
|---|---|---|
| 2025 weeks 4-11 | 5.304 → 5.270 | 53.2% → 54.2% |
| 2025 weeks 12-18 | 5.126 → 5.088 | 55.4% → 55.6% |
| 2026 weeks 2-4 | 4.972 → 4.963 | 53.3% → 53.8% |

## Review corrections (2026-10-13)

A review before the pull request found, and these were fixed:
- The return rule doubled heavy returners' return points with a 4.0 cap
  (Turpin 6.9 → 11.2); now capped at 1.0 (Turpin 8.2).
- WOPR divided by a team's air yards on catches, which can be near zero:
  now kept to 0-100% with tiny totals skipped, compared with the cutoff at
  3 decimals, and the TE label is off (it no longer beat the floor rule in
  both halves; the earlier "15-16% vs 18-28%" didn't survive the fix).
- Close calls were picked on each model's own Predicted, so runs weren't
  comparable; now picked on the projection. The earlier "within ±1 sd"
  check is replaced by the spread of miss ÷ sd.
- This page left out matchup's K and DEF rows; they're in section 2 now.

## Caveats

- One season plus three weeks (about 4,800 + 1,000 player-games). Small
  effects can be noise; only changes that held in both halves are made.
- The FantasyPros blend (40% of Predicted) couldn't be tested.
- Credit if nflverse data is ever shown: CC-BY 4.0, "data from nflverse".
