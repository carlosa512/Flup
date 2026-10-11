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
- Slots (`roster_positions`): QB, RB, RB, WR, WR, TE, FLEX, FLEX (RB/WR/TE),
  K, DEF, 6 BN. Plus 1 IR slot, which is `rosters[].reserve`, not a slot in
  roster_positions.
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
  lineup.py          best lineup, game phase (pre/live/final), win %, mode
  news.py            news links per player (ESPN, PFT, RotoBaller, Bluesky beat)
  writeups.py        template write-ups; attaches Claude's (inputs/writeups.json)
  validate.py        rescores finished weeks vs Sleeper's official points
site/                static app, no build step: index.html app.js app.css sw.js
settings.toml        every weight/cap/threshold (the owner edits this)
inputs/consensus/    optional FantasyPros CSV uploads (weekNN_pos.csv)
inputs/writeups.json Claude's write-ups from /writeups (pushed straight to main)
.claude/commands/    writeups.md: the owner's /writeups command
tests/               pytest; test_real_snapshot.py runs only with FLUP_REPLAY
.github/workflows/   update.yml (scheduled data runs + deploy), snapshot.yml (dev)
tools/               snapshot.py (dev raw capture + news/CORS probe), make_icons.py,
                     check_writeups.py (/writeups must pass it before pushing)
```

Data format: `site/data/latest.json`, `"version": 3` (field list in
docs/ROADMAP.md). It's gitignored, so generate it first (below). app.js
refuses other versions (DATA_VERSION) and reloads itself. Bump both
together when the shape changes.

## Running and testing

The cloud container can't reach Sleeper, ESPN or github.io (proxy 403);
raw.githubusercontent.com and PyPI work. Real data comes from GitHub's
runners, saved on two branches:

- `dev-raw`: exactly what the last `claude/**` pipeline run fetched
  (files r000.gz...). Use it to run the pipeline offline.
- `dev-snapshots`: tools/snapshot.py output with readable names, including
  every finished week's matchups/stats, last season's stats, the Sleeper
  players DB and trending adds. Use it for tests/test_real_snapshot.py (it
  fails with `assert 0 > 0` on dev-raw). Refresh it by pushing a change to
  tools/snapshot.py or Actions > Dev snapshot > Run workflow.

```
git fetch origin dev-raw dev-snapshots
mkdir -p /tmp/raw /tmp/snap
git archive origin/dev-raw | tar -x -C /tmp/raw
git archive origin/dev-snapshots | tar -x -C /tmp/snap

python3 -m pytest -q
FLUP_REPLAY=/tmp/snap python3 -m pytest -q tests/test_real_snapshot.py   # 755/755 proof
FLUP_REPLAY=/tmp/raw python3 -m pipeline       # writes site/data/latest.json
cd site && python3 -m http.server 8765         # then Playwright at iPhone 13 size
```

Pipeline code that depends on time must take build()'s `now` and never
read the clock directly; a replay of old data runs "now".

Screenshots: Playwright via node (`NODE_PATH=$(npm root -g)`), device
iPhone 13, `timezoneId: 'America/Chicago'` (the owner's local time).

## Deploy and schedule

- update.yml runs on schedule (Wed ~9 AM, Fri ~6 PM, Sun ~11:45 AM, then
  every 30 min from ~1 PM to 12:30 AM Eastern; Thu and Mon nights from
  ~6 PM; Saturdays in Dec/Jan; listed for EDT and EST in UTC), by "Run
  workflow",
  and on pushes to `main` or `claude/**` that touch pipeline/, site/,
  tests/, inputs/, settings.toml, requirements*.txt or update.yml
  (docs-only pushes don't run it). Tests run first; a failed run publishes
  nothing.
- `main` publishes the gh-pages root; `claude/**` publishes gh-pages
  `/preview/` and overwrites `dev-raw`; each keeps the other's files.
- Scheduled runs only happen from `main`, so preview data never refreshes on
  its own. GitHub starts scheduled runs late or drops them under load: on
  2026-10-11 the first ever scheduled run came at 3:42 PM ET, and only 2
  of ~8 half-hour slots ran that afternoon (a theory that the "Claude"
  commit author blocked schedules was wrong). The browser's live card
  covers live scores either way. For fresh preview data: Run workflow on the branch (the GitHub MCP
  `actions_run_trigger` can do it; the owner granted the Claude app
  Actions access on 2026-10-11 after a 403).
- The service worker serves the cached shell first, so the first open after
  a deploy shows the previous app once. GitHub Pages also caches files for
  ~10 minutes, so right after a deploy the owner may need to wait a few
  minutes, close the app fully and open it twice.

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
  (game_status from ESPN). Projections still exist for them, and their
  actual points are in this week's Sleeper matchups (`players_points`).
- Kickers have a team snap count but no player snap count; snap share is
  only computed when the player's own count exists (real zeros are kept).
- Live games: Sleeper's matchup `players_points` can trail its stats
  endpoint by a few minutes, so live starters count the stat line (scored
  here); finals count `players_points`. A live DEF's line carries the
  pts_allow_* flag for the score so far (checked 2026-10-11).
- Sleeper and ESPN send `Access-Control-Allow-Origin: *` (checked
  2026-10-11), so the app fetches live matchup points, the scoreboard and
  DEF stat lines in the browser. Sleeper's matchups are CDN-cached 60 s
  (stale up to 5 min more); its stats endpoint only 4 s.
- News: ESPN's per-player feed is `apis/fantasy/v2/games/ffl/news/players
  ?playerId=<espn_id>` (ESPN IDs from DynastyProcess db_playerids.csv);
  it also files league-wide stories under each player, so stories must
  name him. RotoWire items there have no link. FantasyPros has no public
  news feed (robots.txt blocks /xml/), so it isn't used. Bluesky public
  API needs no key; beat writers are listed in settings.toml [news.beat].
- Images: Sleeper's CDN serves headshots at
  `sleepercdn.com/content/nfl/players/thumb/<player_id>.jpg` (a default
  silhouette for unknown ids, not a 404) and team logos at
  `sleepercdn.com/images/team_logos/nfl/<team lowercase>.png`; both load
  with the site as Referer, cached a month. Not an official API: same grey
  area as ESPN.
- ESPN standings (`apis/v2/sports/football/nfl/standings?season=YYYY`):
  stat `clincher` is "*" (#1 seed), "z" (division), "y" (wild card), "x"
  (playoff spot), "e" (eliminated); `playoffSeed` too.
- Sleeper transactions (`/v1/league/<id>/transactions/<week>`): types
  free_agent / waiver / trade, status complete / failed, times in ms. A
  trade lists each traded player in both `adds` and `drops`, so it is not
  a release. Trending adds counts are across all Sleeper leagues.

## Commits

Imperative summary line plus short bullets of what and why.
