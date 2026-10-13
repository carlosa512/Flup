# Backtest: does advanced data make Predicted better? (2026-10-13)

Owner's question (Phase 7): nflverse publishes free EPA, CPOE, WOPR and
more. Add them only if they make Predicted points or the Boom/Steady
labels more accurate.

## How it was tested

`tools/backtest.py` rebuilds Predicted for every week of the 2025 season
from what was known before that week, the same way the site does:

- Sleeper's projection for the week, rescored in our scoring. Sleeper keeps
  each week's last pre-game projection: re-fetched 2026 week 5 projections
  matched a copy saved on game day exactly for all 181 players whose games
  had started (only not-yet-started games had changed).
- The current adjustments (usage, Vegas game environment from nflverse's
  closing lines, matchup, QB habits, return men) and floor/ceiling, with
  2024 as "last season".
- Left out: the FantasyPros blend (no free history of weekly ranks) and
  injury status (Sleeper's player info is today's, not that week's).

Then, against what really happened (weeks 4-18, players who played and
were projected at least QB 8, RB/WR 4, TE/K/DEF 3):

- **Average miss**: |real − predicted|.
- **Close calls**: same position, same week, predicted within 1.5 pts: how
  often the higher one really scored more (50% = coin flip).
- **Out of sample**: anything fitted is fitted on weeks 4-11 and checked on
  12-18, and the other way round. A change counts only if it helps in both.

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

| Adjustment | Weeks 4-11 | Weeks 12-18 | Verdict |
|---|---|---|---|
| Usage trend, RB | −1.70 | −0.48 | wrong way |
| Usage trend, WR | −0.53 | +0.45 | no help |
| Usage trend, TE | −1.48 | +0.61 | no help |
| Matchup, RB | +0.38 | −1.16 | flips |
| Matchup, WR | −1.28 | +0.43 | flips |
| Matchup, QB | +0.39 | +1.17 | helps |
| Matchup, TE | +1.30 | +0.09 | helps a little |
| Game environment, QB/RB/WR/TE | +0.33 to +1.24 | +0.41 to +0.83 | helps |
| Game environment, K/DEF | −1.04 / −0.22 | +0.46 / +0.45 | unclear (kept) |

### 3. The return man rule points the wrong way

| Return men (RB/WR/TE) | Games | Return pts projected | Predicted added | Really got |
|---|---|---|---|---|
| Projection has return yards | 211 | 1.13 | 0.30 | 2.33 |
| Projection has none | 96 | 0.00 | 2.11 | 0.92 |

When the projection has return yards, real returns came to about double
(both halves: 1.10 → 2.38 and 1.17 → 2.27). When it has none, he had often
lost the job (only 42% still returned), so adding his recent yards
overshoots. Better: count the projection's return points again, add
nothing when there are none (bias −0.08/−0.21 and the smallest misses).

### 4. "Give or take" and floor/ceiling are too narrow

Win % adds up each starter's sd; if the sd is right, 68% of games land
within ±1 sd. Floor = 25th percentile (25% of games at or under), ceiling
= 90th (10% at or over).

| Pos | Within ±1 sd | Under floor | Over ceiling | With everything × 1.2 |
|---|---|---|---|---|
| QB | 63% | 32% | 13% | 69% / 27% / 10% |
| RB | 61% | 34% | 14% | 71% / 27% / 11% |
| WR | 60% | 38% | 12% | 70% / 31% / 9% |
| TE | 60% | 32% | 15% | 69% / 26% / 12% |
| K | 61% | 29% | 16% | 72% / 24% / 11% |
| DEF | 69% | 27% | 13% | 74% / 20% / 10% |

So win % has been a bit too sure of itself: with the spread × 1.2, a 37% would read about 39%, and a 75% about 71%.

### 5. Boom and Steady labels

- Nothing tested picks out big games (1.5× Predicted or more): every AUC is
  0.42-0.54 (0.5 = coin flip), including ceiling/score, which the Boom label
  uses. A high ceiling/score does weakly mean a swingier player (AUC 0.52-0.54
  for big-or-dud games), so leaning toward ceilings as the underdog still
  makes sense.
- WOPR (1.5 × target share + 0.7 × air yards share) picks out reliable pass
  catchers (fewer duds, under half of Predicted). AUC for duds, lower =
  better: TE 0.38 vs 0.45 for floor/score (what Steady uses), WR 0.44 vs
  0.45, RB 0.46 vs 0.43. WOPR worked out from Sleeper's own targets and air
  yards gives the same answer as nflverse's (TE 0.380 vs 0.376), so no new
  data source is needed.

### Together

Usage off, matchup off for RB/WR, the new return rule:

| Pos | Avg miss: projection / now / changed | Close calls: projection / now / changed |
|---|---|---|
| QB | 8.33 / 8.32 / 8.32 | 50.2% / 51.6% / 51.6% |
| RB | 5.31 / 5.38 / 5.29 | 55.8% / 54.8% / 56.4% |
| WR | 4.85 / 4.89 / 4.86 | 53.2% / 54.2% / 56.0% |
| TE | 4.66 / 4.67 / 4.64 | 52.2% / 52.8% / 53.4% |

Both halves improve: average miss 5.30 → 5.28 and 5.13 → 5.09; close
calls 53.0% → 54.4% and 53.8% → 54.8%.

Check on 2026 weeks 2-4 (small, with 2025 as last season): the same
pattern (ranges too narrow: 27-40% under the floor, 12-24% over the ceiling).

## Caveats

- One season (about 4,800 player-games). Small effects can be noise; only
  changes that held in both halves are proposed.
- The FantasyPros blend (40% of Predicted) couldn't be tested.
- Credit if nflverse data is ever shown: CC-BY 4.0, "data from nflverse".
