# Original request (verbatim)

This is the owner's original request, kept word for word. Changes agreed
since then, which override the text below:

- League: `1374496898462785536` "The League" (2026). "Los Pollos Hermanos"
  was last year's team; this year's team is "Raider of the Lost Bowers".
- Hosting: public repo + GitHub Pages.
- No keyed APIs at all: The Odds API was dropped. Vegas lines come from
  ESPN's public (undocumented) scoreboard, a grey area the owner accepted.
- Expert consensus: FantasyPros consensus re-posted by DynastyProcess on
  GitHub (license unclear, owner accepted); an uploaded FantasyPros CSV wins.
- Consensus rank -> points uses a curve built from the league's own scoring;
  the draft-board rank factors are NOT applied (they'd double-count the TE
  premium).
- Tiers: local-gap method, plus "a gap of 1.5+ points always starts a new
  tier" (settings.toml `always_break_gap`), because a strict minimum tier
  size of 3 lumped clear elites together.
- nflverse turned out not to be needed: Sleeper's weekly stats include
  snaps, targets, red-zone looks, air yards and return yards. Routes run
  aren't available from any free source; snap and target share stand in.

---

# Fantasy lineup dashboard for my Sleeper league

## Goal
Build a phone-first web dashboard for my Sleeper fantasy league that tells
me who to start each week, ranks players in tiers using MY league's scoring,
explains each call, and links to the articles behind it.

Total cost must be $0. No paid APIs or AI API keys anywhere.

Before writing code: ask me clarifying questions, then propose a plan
(stack, hosting, data sources) and wait for my OK. Build in small phases
I can test on my phone.

## My league
- Sleeper username: clos512, team "Los Pollos Hermanos" (12 teams, 2026).
  Find the league through the Sleeper API, or ask me for the league ID.
- Pull scoring_settings and roster_positions from the API, don't hardcode.
  Sanity check against what I know:
  - Half PPR, but TEs get +0.5 per catch (full PPR for TEs)
  - 6 pt passing TDs, -3 per INT
  - 0.05 pts per kick/punt return yard
  - 2 RB + 2 FLEX starters
  - Playoffs Weeks 15 to 17, 8 of 12 teams make it

## Data (free and allowed sources only)
- Sleeper API: rosters, matchups, players, injury status, current week,
  and its weekly projections endpoint if it still works
- nflverse (nflreadpy): snap share, target share, routes, red zone usage,
  EPA, weekly stat history
- Vegas lines (free tier, e.g. The Odds API): implied team totals, spreads
- Expert consensus: find a free source I'm allowed to use. If none, let me
  upload a weekly FantasyPros rankings CSV
- News: RSS/public feeds (FantasyPros, NBC/Rotoworld, ESPN, team beat
  writers). Paywalled sites (4for4, Sharp Football, FantasyLife) are
  link-only. Tag every link "beat reporter" or "aggregator"
- Never copy article text into the app: headline, source, date, link only
- If a source is down or against its terms, tell me and suggest another.
  Don't quietly scrape it

## The scoring model (not just raw consensus)
Each player gets a "My Score":
1. Projected points in MY scoring: rescore projected stat lines with my
   league settings, so the TE premium, 6 pt TDs, INT penalty, and return
   yards count automatically
2. Blend: start at 60% my-scoring projection, 40% consensus (converted to
   points). All weights live in one settings file I can edit
3. Small, capped adjustments, each shown in the breakdown:
   - Usage trend (last 3 weeks vs season: snaps, targets, routes)
   - Game environment (implied team total, spread)
   - Matchup (opponent points allowed to the position)
   - QB: bonus for low-INT rushers, penalty for high-INT passers,
     computed from data, not a hardcoded name list
   - Return men: small bump if they currently return kicks/punts
   - Injury: discount Questionable, flag Doubtful/Out
   - Week 17: flag players on teams that may rest starters
4. Floor and ceiling from each player's weekly history in my scoring
   (25th and 90th percentile)

Fallback when only a consensus RANK exists (no stat projection), use our
draft board factors: TE rank 1-3 x0.62, 4-8 x0.72, 9-16 x0.80, rest x0.90;
QBs x0.85 (top 24) or x0.94; return men x0.95. Lower = better.

Tiers: the local-gap method from our draft boards. A new tier starts when
the gap to the next player is bigger than 2.2x the median gap of nearby
players (window 24, minimum tier size 3). Run per position on My Score,
retuned for points instead of ADP.

## Win probability and boom/bust
- Estimate my win % from both teams' projected totals and their variance
- Favored (65%+): lean on floor. Underdog (under 35%): lean on ceiling.
  In between: median. Thresholds editable
- Show it plainly at the top, e.g. "Favored 68%: playing it safe"

## What the dashboard shows (answer first, details tap to expand)
1. Top: recommended lineup, win %, my projection vs opponent's.
   One-line reason per starter
2. Close calls: any start/sit within ~1.5 pts, with the case for each side
3. Flex and sleeper options: best FLEX choices from my bench, plus 3-5
   free agents worth starting or grabbing, labeled boom/bust. I'm the most
   active waiver user in my league, so lean into this
4. Tiers by position, my players highlighted
5. Player detail: My Score breakdown, floor/ceiling, injury status,
   news links, and a short write-up
6. Late-swap tip: put late-game players in FLEX to keep swap options
7. "Last updated" on every data source, with a warning if anything is
   stale (e.g. injury news older than 24h before kickoff)

## Write-ups (free, no paid APIs)
- Built-in write-ups: 2-4 sentences generated from the score breakdown
  with sentence templates. Lead with the biggest factor, then where
  consensus disagrees and why my model differs. Vary the wording so it
  doesn't read robotic. Only state numbers that exist in the data.
- "Copy for Claude" button on each player and on the full lineup:
  copies a ready-to-paste prompt with all inputs (My Score breakdown,
  floor/ceiling, win %, injury status, news links) so I can paste it
  into the Claude app for a deeper take.
- Weekly refresh command I can run in Claude Code (on my subscription,
  no API key) that writes smarter write-ups for my starters and close
  calls into a data file. Show those over the template version when
  they exist.

## Refresh, phone, and hosting (free)
- Show cached data instantly, refresh in the background on open, plus
  a Refresh button
- Free static hosting (GitHub Pages, Cloudflare Pages, or similar).
  If the repo must be public for free hosting, that's fine
- Scheduled free jobs (e.g. GitHub Actions) pull data Wednesday
  (projections), Friday (injury reports), and Sunday morning (inactives),
  saved as files the site reads. Keys for any free data sources (like
  odds) stay in the host's secret settings, never in the code
- Refresh button: re-fetch live Sleeper data in the browser if Sleeper
  allows it; otherwise trigger or show the next scheduled pull
- Mobile-first, dark mode, big tap targets, can save to home screen
- I know Python, so Python is preferred for the data scripts

## Working with me
- Short explanations, clear numbered steps
- Show your math: every recommendation traceable to its inputs
- Flag anything you're unsure about instead of guessing
