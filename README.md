# Flup

Phone-first lineup help for **The League** on Sleeper. It scores every player
with the league's own settings, splits each position into tiers, and shows
the math behind every number. Total cost: $0 (no paid APIs, no keys).

## Using it

1. Open the site on your phone (link from Settings → Pages once it's live).
2. Share → **Add to Home Screen**. It opens like an app, dark by default.
3. Tap any player to see his My Score: the blend, what moved it, and his
   floor and ceiling.
4. Tap the "Data from … / ✓ All checks pass" line for the checks: your league
   settings vs Sleeper's, and every finished week rescored against Sleeper's
   official points.

Data updates on its own: Wednesday (projections), Friday evening (injury
reports) and Sunday before the 1 PM and late games. For a fresh pull any
time: GitHub → **Actions** → **Update data** → **Run workflow**.

## How My Score works

1. **Projection:** Sleeper's projected stat line, scored with your league's
   settings (TE premium, 6-pt pass TDs, -3 INTs, return yards).
2. **Blend:** 60% projection, 40% expert consensus (FantasyPros, turned into
   points with your scoring).
3. **Small, capped adjustments**, each shown on the player's card: usage
   trend, Vegas game environment, matchup, QB interception/rushing habits,
   return yards, and injury.
4. **Floor and ceiling:** from each player's weekly scores (this season plus
   the end of last season), scaled to this week.

Want your own consensus for a week? See [inputs/consensus](inputs/consensus/README.md).

## Trying changes before they go live

Work in progress shows up at **/Flup/preview/** (same site address plus
`/preview/`). Your main site only changes when code is merged into `main`.

## Changing how it works

Every weight, cap and threshold lives in [`settings.toml`](settings.toml).
Edit it on GitHub (pencil icon) and commit; the next run uses it.

## Data sources

| Source | Used for | Notes |
|---|---|---|
| Sleeper API | league settings, rosters, matchups, projections, stats | public, no key |
| ESPN scoreboard | Vegas spreads/totals, kickoff times | public but undocumented |
| DynastyProcess (GitHub) | FantasyPros weekly expert consensus | public re-post of FantasyPros data |

## Running it yourself

```
python3 -m pipeline            # writes site/data/latest.json
cd site && python3 -m http.server 8000
python3 -m pytest -q           # tests
```

Needs Python 3.11+. The pipeline uses only the standard library.

`FLUP_REPLAY=folder` replays saved raw responses instead of the network
(GitHub's runners save them to the `dev-raw` branch on development
branches). `tools/snapshot.py` captures extra endpoints for exploring.
