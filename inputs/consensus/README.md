# Your own consensus rankings (optional)

The site uses FantasyPros' expert consensus automatically. To use your own
FantasyPros rankings instead for a week:

1. On FantasyPros, open the weekly rankings for a position and download the CSV.
2. Rename it to the week and position, e.g. `week05_wr.csv` (week 5, WRs).
   Overall/FLEX exports with a POS column like `WR12` can be named `week05.csv`.
3. On GitHub, open this folder, tap **Add file → Upload files**, and commit.

The data run starts on its own. Your ranks replace the automatic ones for the
players they cover. Anyone whose name doesn't match keeps the automatic rank,
and the site's checks line lists the names that didn't match.
