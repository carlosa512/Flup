# Flup: fantasy lineup dashboard for "The League" on Sleeper

Personal, phone-first web dashboard for one Sleeper league: who to start,
tiers in the league's own scoring, and the math behind every number.
Total cost must stay $0: no paid APIs, no API keys anywhere.

- Original request (verbatim): [docs/SPEC.md](docs/SPEC.md)
- What's done, decisions made, what's next: [docs/ROADMAP.md](docs/ROADMAP.md)
- Live site: https://carlosa512.github.io/Flup/ (from `main`)
- Preview of work in progress: https://carlosa512.github.io/Flup/preview/ (from `claude/**` branches)

## Working with the owner

- Neurodivergent (likely ADHD): short explanations, clear numbered steps,
  answer first. They read on a phone.
- Keep the UI light. They called a per-stat table "too much info"; details
  go behind a tap (`<details>`), not on the main card.
- Show the math: every number traceable to its inputs. Flag anything
  uncertain instead of guessing.
- For each phase: ask clarifying questions, propose a plan, wait for OK,
  then build in small pieces they can test on the preview site.
- They merge pull requests themselves on GitHub. Develop on a `claude/**`
  branch; restart it from `main` after each merge.
- Free-as-free-can-be: no keyed APIs (The Odds API was dropped; ESPN's
  public scoreboard is used for Vegas lines, a known grey area they accepted).

## League facts (verified against the Sleeper API)

- League `1374496898462785536` "The League", 2026, 12 teams. User `clos512`,
  team "Raider of the Lost Bowers", roster_id 12.
- Slots: QB, RB, RB, WR, WR, TE, FLEX, FLEX (RB/WR/TE), K, DEF, 6 BN, 1 IR.
- Half PPR (`rec` 0.5) + TE premium (`bonus_rec_te` 0.5); pass TD 6; INT -3;
  `kr_yd`/`pr_yd` 0.05; `fum` -1 and `fum_lost` -2 (a lost fumble is -3).
- Playoffs weeks 15-17, 8 teams. Waivers are FAAB, $200 budget.
- Scoring always comes from Sleeper's `scoring_settings`; settings.toml
  `[league.expect]` only checks it.

## Layout

```
pipeline/            Python 3.11+, standard library only; `python3 -m pipeline`
  build.py           one run: fetch -> score -> model -> tiers -> site/data/latest.json
  fetch.py           get_json/get_text with retries; FLUP_RECORD / FLUP_REPLAY
  sleeper.py espn.py consensus.py   data sources
  scoring.py         stat line x league settings, with per-stat parts
  history.py         every game this + last season rescored in league scoring
  model.py           My Score: blend, capped adjustments, injury, floor/ceiling
  tiers.py           local-gap tiers; league.py rosters + settings check
  validate.py        rescores finished weeks vs Sleeper's official points
site/                static app, no build step: index.html app.js app.css sw.js
settings.toml        every weight/cap/threshold (the owner edits this)
inputs/consensus/    optional FantasyPros CSV uploads (weekNN_pos.csv)
tests/               pytest; test_real_snapshot.py runs only with FLUP_REPLAY
.github/workflows/   update.yml (scheduled data runs + deploy), snapshot.yml (dev)
tools/               snapshot.py (dev raw capture), make_icons.py
```

Data format: `site/data/latest.json`, `"version": 2`. app.js refuses other
versions (DATA_VERSION) and reloads itself. Bump both together when the
shape changes.

## Running and testing

```
python3 -m pytest -q
FLUP_REPLAY=<dir> python3 -m pytest -q tests/test_real_snapshot.py
FLUP_REPLAY=<dir> python3 -m pipeline        # writes site/data/latest.json
cd site && python3 -m http.server 8765         # then Playwright at iPhone 13 size
```

The cloud container can't reach Sleeper, ESPN or github.io (proxy 403);
raw.githubusercontent.com and PyPI work. Real data comes from GitHub's
runners: every push to a `claude/**` branch runs the pipeline with
FLUP_RECORD and saves the raw responses to the `dev-raw` branch:

```
git fetch origin dev-raw && mkdir -p /tmp/raw && git archive origin/dev-raw | tar -x -C /tmp/raw
FLUP_REPLAY=/tmp/raw python3 -m pipeline
```

Screenshots: Playwright via node (`NODE_PATH=$(npm root -g)`), device
iPhone 13, `timezoneId: 'America/Chicago'` (the owner's local time).

## Deploy and schedule

- update.yml runs on schedule (Wed ~9 AM, Fri ~6 PM, Sun ~11:45 AM and
  ~3:15 PM Eastern; each listed for EDT and EST in UTC), on push, and by
  "Run workflow". Tests run first; a failed run publishes nothing.
- `main` publishes the gh-pages root; `claude/**` publishes gh-pages
  `/preview/`; each keeps the other's files.
- Scheduled runs only happen from `main`.
- The service worker serves the cached shell first, so the first open after
  a deploy shows the previous app once.

## Gotchas already learned (don't relearn them)

- Sleeper projections already include `bonus_rec_te`; never add the TE
  premium again (the owner's old script double-counted it).
- Players' projected kick return yards are filed under `def_kr_yd` in
  projections (actual stats use `kr_yd`); build.player_rows maps them.
- Sleeper weekly stats: a game counts as played when `gp >= 1`. Snap counts
  are missing for some weeks (2025 week 18): skip missing values, never
  treat them as 0.
- DEF projections give an average `pts_allow` plus a bracket flag; the
  projection blends between bracket midpoints (`smooth_def_brackets`).
  Actual stats use the flags, and that matches Sleeper exactly.
- ESPN: spread is from the home side; `details` like "JAX -7.5" is parsed
  first; finished games have no odds; ESPN `WSH` = Sleeper `WAS`.
- Consensus (DynastyProcess `fp_latest_weekly.csv`): RB/WR/TE pages are PPR;
  FantasyPros `JAC` = `JAX`; new kickers often lack a sleeper_id, so names
  are matched; ranks deeper than anyone Sleeper projects get no points.
- Shrinkage is n/(n+k): a number counts half at k, never fully.
- The scoring engine matches Sleeper's official points 755/755 (weeks 1-4,
  2026). Any scoring change must keep test_real_snapshot.py passing.
- Thursday games are already played by the weekend; players show "Played"
  (game_status from ESPN). Projections still exist for them.

## Commits

Imperative summary line plus short bullets of what and why.
