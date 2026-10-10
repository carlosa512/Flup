# Flup

Phone-first lineup help for **The League** on Sleeper. It scores every player
with the league's own settings, splits each position into tiers, and shows
the math behind every number. Total cost: $0 (no paid APIs, no keys).

## Using it

1. Open the site on your phone (link from Settings → Pages once it's live).
2. Share → **Add to Home Screen**. It opens like an app, dark by default.
3. Tap any player to see how his points are built.
4. **Checks** tab: your league settings vs Sleeper's, and the scoring engine
   rescoring every finished week against Sleeper's official points.

Data updates on its own: Wednesday (projections), Friday evening (injury
reports) and Sunday before the 1 PM and late games. For a fresh pull any
time: GitHub → **Actions** → **Update data** → **Run workflow**.

## Changing how it works

Every weight, cap and threshold lives in [`settings.toml`](settings.toml).
Edit it on GitHub (pencil icon) and commit; the next run uses it.

## Data sources

| Source | Used for | Notes |
|---|---|---|
| Sleeper API | league settings, rosters, matchups, projections, stats | public, no key |
| ESPN scoreboard | Vegas spreads/totals, kickoff times | public but undocumented |

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
