"""Expert consensus rankings, turned into points in your scoring.

Source: FantasyPros' weekly expert consensus (ECR), re-posted publicly by
DynastyProcess on GitHub. A FantasyPros CSV saved as
inputs/consensus/weekNN*.csv (NN = this week, e.g. week05_wr.csv) replaces it.

Ranks become points with a curve made from this week's projections in your
scoring: a consensus TE3 gets the points of the 3rd-best projected TE. The
TE premium and other league rules are therefore counted once, by the curve.
"""

import csv
import io
import re
from datetime import datetime
from pathlib import Path

from .fetch import FetchError, get_text

DP = "https://raw.githubusercontent.com/dynastyprocess/data/master/files"
WEEKLY_URL = f"{DP}/fp_latest_weekly.csv"
IDS_URL = f"{DP}/db_playerids.csv"
PAGES = {"qb": "QB", "ppr-rb": "RB", "ppr-wr": "WR", "ppr-te": "TE", "k": "K", "dst": "DEF"}
TEAM_FIX = {"JAC": "JAX", "WSH": "WAS"}
POS_FIX = {"DST": "DEF", "D/ST": "DEF", "PK": "K"}
_SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b")


def norm_name(name):
    s = (name or "").lower().replace("’", "'")
    s = re.sub(r"[.'\-]", "", s)
    s = _SUFFIX.sub("", s)
    return " ".join(s.split())


def player_index(rows_by_pos):
    """(normalized name, position) -> [(sleeper id, team)] from projection rows."""
    index = {}
    for pos, rows in rows_by_pos.items():
        for r in rows:
            info = r.get("player") or {}
            name = f"{info.get('first_name', '')} {info.get('last_name', '')}"
            index.setdefault((norm_name(name), pos), []).append(
                (str(r.get("player_id")), r.get("team") or info.get("team")))
    return index


def match(index, name, pos, team):
    candidates = index.get((norm_name(name), pos)) or []
    if len(candidates) == 1:
        return candidates[0][0]
    for pid, t in candidates:
        if t == team:
            return pid
    return None


def _current(kickoffs, games, dates=()):
    """True when the file's kickoff times fall inside this week's games.
    Uses ESPN's kickoffs, or the game dates on Sleeper's projection rows
    when ESPN didn't load."""
    starts = [datetime.fromisoformat(g["kickoff"].replace("Z", "+00:00")).timestamp()
              for g in games if g.get("kickoff")]
    for d in dates or ():
        try:
            day = datetime.fromisoformat(d + "T00:00:00+00:00").timestamp()
            starts += [day, day + 86400]
        except (TypeError, ValueError):
            pass
    if not kickoffs or not starts:
        return True  # can't tell; trust it
    first, last = min(starts), max(starts)
    inside = sum(1 for k in kickoffs if first - 86400 <= k <= last + 86400)
    return inside >= 0.5 * len(kickoffs)


def from_dynastyprocess(index, games, dates=()):
    """sleeper id -> consensus entry, plus a note about the file."""
    ids = {}
    for r in csv.DictReader(io.StringIO(get_text(IDS_URL))):
        sid = (r.get("sleeper_id") or "").strip()
        if r.get("fantasypros_id") and sid and sid != "NA":
            ids[r["fantasypros_id"]] = sid
    out, dates, kickoffs = {}, set(), []
    for r in csv.DictReader(io.StringIO(get_text(WEEKLY_URL))):
        pos = PAGES.get(r.get("page"))
        if not pos:
            continue
        try:
            ecr, rank = float(r["ecr"]), int(float(r["rank"]))
        except (KeyError, TypeError, ValueError):
            continue
        team = TEAM_FIX.get(r.get("team"), r.get("team"))
        pid = team if pos == "DEF" else (ids.get(r.get("fantasypros_id"))
                                         or match(index, r.get("player_name"), pos, team))
        if not pid:
            continue
        try:
            kickoffs.append(float(r["player_game_kickoff_ts"]))
        except (KeyError, TypeError, ValueError):
            pass
        dates.add(r.get("scrape_date"))
        out[pid] = {"pos": pos, "ecr": ecr, "rank": rank, "url": r.get("player_page_url") or ""}
    if not out:
        raise FetchError("the consensus file had no usable rankings")
    if not _current(kickoffs, games, dates):
        raise FetchError(f"the consensus file (from {max(dates)}) is for a different week")
    return out, f"FantasyPros consensus via DynastyProcess, posted {max(dates)}"


def _column(fields, *names):
    lookup = {f.strip().strip('"').lower(): f for f in fields}
    for n in names:
        if n in lookup:
            return lookup[n]
    return None


def parse_fantasypros_csv(text, filename, index):
    """A FantasyPros rankings export -> sleeper id -> consensus entry.
    Works with single-position pages and overall/FLEX pages."""
    reader = csv.DictReader(io.StringIO(text))
    fields = reader.fieldnames or []
    rank_col = _column(fields, "rk", "rank", "ecr")
    name_col = _column(fields, "player name", "player", "name")
    team_col = _column(fields, "team")
    pos_col = _column(fields, "pos", "position")
    if not rank_col or not name_col:
        raise ValueError(f"{filename}: needs RK and PLAYER NAME columns")
    file_pos = None
    for token in re.split(r"[^a-z]+", Path(filename).stem.lower()):
        if token.upper() in ("QB", "RB", "WR", "TE", "K", "DST", "DEF"):
            file_pos = POS_FIX.get(token.upper(), token.upper())
    seen, out, unmatched = {}, {}, []
    for r in reader:
        name = (r.get(name_col) or "").strip()
        raw_pos = (r.get(pos_col) or "").strip().upper() if pos_col else ""
        pos = POS_FIX.get(re.sub(r"\d+", "", raw_pos), re.sub(r"\d+", "", raw_pos)) or file_pos
        if not name or pos not in ("QB", "RB", "WR", "TE", "K", "DEF"):
            continue
        seen[pos] = seen.get(pos, 0) + 1
        digits = re.search(r"\d+", raw_pos)
        rank = int(digits.group()) if digits else seen[pos]
        team = (r.get(team_col) or "").strip().upper() if team_col else ""
        team = TEAM_FIX.get(team, team)
        pid = team if pos == "DEF" else match(index, name, pos, team)
        if pid:
            out[pid] = {"pos": pos, "ecr": float(rank), "rank": rank, "url": ""}
        else:
            unmatched.append(name)
    return out, unmatched


def from_uploads(folder, week, index):
    """Your own FantasyPros CSVs for this week -> (ranks, note, problems)."""
    out, used, problems = {}, [], []
    for f in sorted(Path(folder).glob(f"week{int(week):02d}*.csv")):
        ranks, unmatched = parse_fantasypros_csv(f.read_text(encoding="utf-8-sig"), f.name, index)
        if not ranks:
            problems.append(f"{f.name} had no players I could read (name the file with the "
                            "position, like week05_wr.csv, if it has no POS column)")
            continue
        out.update(ranks)
        used.append(f.name)
        if unmatched:
            problems.append(f"{f.name}: couldn't match {len(unmatched)} name(s), e.g. "
                            + ", ".join(unmatched[:3]) + " (they keep the automatic rank)")
    note = "Your FantasyPros CSV: " + ", ".join(used) if used else ""
    return out, note, problems


def curve(projections):
    """Projected points sorted best first: curve[k-1] = k-th best."""
    return sorted((p for p in projections if p > 0), reverse=True)


def rank_points(points_curve, ecr):
    """Points for a (possibly fractional) consensus rank on the curve. Ranks
    past the end of the curve (deeper than anyone Sleeper projects) get None."""
    if not points_curve or ecr is None:
        return None
    x = max(float(ecr), 1.0) - 1
    if x > len(points_curve) - 1:
        return None
    i = int(x)
    if i >= len(points_curve) - 1:
        return points_curve[-1]
    return points_curve[i] + (points_curve[i + 1] - points_curve[i]) * (x - i)
