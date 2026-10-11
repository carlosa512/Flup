"""My recommended lineup, both teams' expected totals, and my win %.

1. Each starter's expected points and spread (sd) for the week: a finished
   game is his actual points (sd 0); a live game is points so far plus My
   Score x the share of the game left; a game not started is My Score.
2. Best lineup by My Score from healthy players whose game hasn't started.
   A player whose game has started is locked: a starter stays in his slot,
   a bench player can't come in.
3. Win % = Phi((my total - their total) / sqrt(my variance + theirs)),
   treating players as independent (teammates really move together, so
   the true chance can be a few points either way). The opponent's lineup
   is used exactly as set in Sleeper.
4. That win % sets the mode: favored -> rank players partway toward their
   floor, underdog -> partway toward their ceiling, then pick again and
   report the final win %.
"""

import math
from collections import deque
from datetime import datetime, timedelta, timezone
from itertools import combinations
from statistics import NormalDist

from .model import OUT_STATUSES
from .scoring import bracket_points, smooth_bracket_points

SLOT_POSITIONS = {
    "QB": {"QB"}, "RB": {"RB"}, "WR": {"WR"}, "TE": {"TE"}, "K": {"K"}, "DEF": {"DEF"},
    "FLEX": {"RB", "WR", "TE"}, "WRRB_FLEX": {"WR", "RB"}, "REC_FLEX": {"WR", "TE"},
    "SUPER_FLEX": {"QB", "RB", "WR", "TE"},
}
NOT_SLOTS = {"BN", "IR", "TAXI"}
NOT_PLAYED = {"STATUS_POSTPONED", "STATUS_CANCELED"}
QUARTER = 900  # seconds
POS_WORD = {"K": "kicker", "DEF": "defense"}
# What the ranking number is called when it leans toward floor or ceiling
VALUE_NAME = {"underdog": " upside score", "favored": " safe score"}
MEASURE = {"underdog": "upside score", "favored": "safe score", "even": "My Score"}
SUFFIXES = {"Jr", "Sr", "II", "III", "IV", "V"}
CALLS_PER_STARTER = 2
MAX_CALLS = 4
PCTS = (25, 90)  # floor and ceiling percentiles (settings.toml [floor_ceiling])
EARLIEST = datetime.min.replace(tzinfo=timezone.utc)
BELL = NormalDist()

try:
    from zoneinfo import ZoneInfo
    EASTERN = ZoneInfo("America/New_York")
except Exception:  # no time zone data: daylight time is close enough
    EASTERN = timezone(timedelta(hours=-4))


def _time(iso):
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None


def _accepts(slot):
    return SLOT_POSITIONS.get(slot, {slot})


def _healthy(p):
    """My Score before the injury discount."""
    return p["score"] - sum(a["pts"] for a in p.get("adj") or [] if a["key"] == "injury")


# ---------- one player's week ----------

def phase(p, game, now, actual=None):
    """('none' | 'pre' | 'live' | 'final', share of the game left)."""
    if game is None:
        # No ESPN data for his team: fall back to Sleeper. Points this week
        # or a game date before today (Eastern) mean his game has been played.
        if not p or not p.get("opp"):
            return "none", 0.0
        if actual:
            return "final", 0.0
        if p.get("game_date") and now is not None and p["game_date"] < now.astimezone(EASTERN).date().isoformat():
            return "final", 0.0
        return "pre", 1.0
    if game.get("status") in NOT_PLAYED:
        return "none", 0.0
    if game.get("completed") or game.get("state") == "post" or game.get("status") == "STATUS_FINAL":
        return "final", 0.0
    kickoff = _time(game.get("kickoff"))
    if game.get("state") != "in" and (kickoff is None or now is None or now < kickoff):
        return "pre", 1.0
    period = game.get("period") or 0
    if game.get("state") != "in" or period < 1:
        return "live", 1.0  # kickoff time passed, but the clock hasn't started
    if period > 4:
        return "live", 0.0  # overtime
    left = ((4 - period) * QUARTER + (game.get("clock") or 0)) / (4 * QUARTER)
    return "live", round(max(0.0, min(1.0, left)), 3)


def _plays_quantile(u, healthy, floor, ceiling, pcts):
    """His score at percentile u if he plays: a bell curve through his floor,
    healthy score (middle) and ceiling."""
    u = min(max(u, 0.001), 0.999)
    if u >= 0.5:
        return healthy + (ceiling - healthy) * BELL.inv_cdf(u) / BELL.inv_cdf(pcts[1] / 100)
    return healthy - (healthy - floor) * BELL.inv_cdf(1 - u) / BELL.inv_cdf(1 - pcts[0] / 100)


def outcome(p, pcts=PCTS):
    """(floor, ceiling, sd) this week, or None. A Doubtful player's range is
    'if he plays'. He plays with chance q = My Score / healthy score
    (Doubtful takes 60% off, so 40%), else scores 0, so his floor and
    ceiling are percentiles of that mix: with a 60% chance of 0 his floor
    (25th percentile) is 0, and his ceiling (90th) is the 75th percentile of
    his if-he-plays range."""
    r = p.get("range") if p else None
    if not r:
        return None
    floor, ceiling, sd = r["floor"], r["ceiling"], abs(r["sd"])
    if r.get("if_plays"):
        healthy = _healthy(p)
        q = max(0.0, min(1.0, p["score"] / healthy)) if healthy > 0 else 0.0
        sd = math.sqrt(q * sd ** 2 + q * (1 - q) * healthy ** 2)

        def mix(a):
            if q <= 0 or a <= 1 - q:
                return 0.0
            return max(0.0, _plays_quantile((a - (1 - q)) / q, healthy, floor, ceiling, pcts))
        floor, ceiling = mix(pcts[0] / 100), mix(pcts[1] / 100)
    return floor, ceiling, sd


def _def_bracket_part(p):
    """(projected points allowed, points the projection gives for it)."""
    allowed, pts = None, 0.0
    for stat, value, _, points in p.get("parts") or []:
        if stat == "pts_allow" or stat.startswith("pts_allow_"):
            pts += points
            if stat == "pts_allow":
                allowed = value
    return allowed, pts


def expected(p, game, actual, now, pcts=PCTS, scoring=None):
    """Expected points and sd for the rest of the week, by game phase."""
    if p is None:
        # Not in this week's data (no projection row): only his actual points
        return {"state": "unknown", "pts": actual or 0.0, "sd": 0.0, "actual": actual, "left": 0.0}
    state, left = phase(p, game, now, actual)
    score = p["score"]
    found = outcome(p, pcts)
    sd = found[2] if found else 0.0
    got = actual or 0.0
    if state == "final":
        return {"state": state, "pts": got, "sd": 0.0, "actual": got, "left": 0.0}
    if state == "live":
        rest = score
        if got and _healthy(p) > score:
            # He's scoring, so he's playing: no "might not play" discount
            rest = _healthy(p)
            sd = abs((p.get("range") or {}).get("sd") or sd)
        pts = got + rest * left
        if p["pos"] == "DEF" and scoring:
            pts = _live_def(p, game, got, rest, left, scoring)
        return {"state": state, "pts": pts, "sd": sd * math.sqrt(left), "actual": got, "left": left}
    if state == "none":
        return {"state": state, "pts": 0.0, "sd": 0.0, "actual": None, "left": 0.0}
    return {"state": state, "pts": score, "sd": sd, "actual": None, "left": 1.0}


def _live_def(p, game, got, rest, left, scoring):
    """A live defense's points so far already include the points-allowed
    bracket for the score right now (Sleeper scores the current stats).
    So: points so far without that bracket, plus the rest of his projection
    without its bracket part, plus the bracket for the points he's expected
    to allow by the end (so far + his projected rate x the game left)."""
    allowed_proj, bracket_proj = _def_bracket_part(p)
    rest_no_bracket = rest - bracket_proj
    allowed_now = (game or {}).get("opp_score")
    if allowed_now is None or allowed_proj is None:
        # No live score: at least don't count the bracket twice
        return got + rest_no_bracket * left
    allowed_end = allowed_now + allowed_proj * left
    return (got - bracket_points(scoring, "pts_allow", allowed_now) + rest_no_bracket * left
            + smooth_bracket_points(scoring, "pts_allow", allowed_end))


def lean_value(mode, lean, pcts=PCTS):
    """The number players are ranked by: My Score, moved `lean` of the way
    to the floor (favored) or the ceiling (underdog)."""
    def value(p):
        found = outcome(p, pcts)
        if mode not in ("favored", "underdog") or not found:
            return p["score"]
        target = found[1] if mode == "underdog" else found[0]
        return p["score"] + lean * (target - p["score"])
    return value


# ---------- picking ----------

def pick(slots, open_slots, pool, value):
    """Best players for the open slots. The most specific slot is filled
    first (QB before FLEX), which is exact for QB/RB/WR/TE/K/DEF + FLEX."""
    ranked = sorted(pool, key=lambda p: (-value(p), -p["score"], p["name"]))
    chosen, taken = {}, set()
    for i in sorted(open_slots, key=lambda i: (len(_accepts(slots[i])), i)):
        for p in ranked:
            if p["id"] not in taken and p["pos"] in _accepts(slots[i]):
                chosen[i] = p
                taken.add(p["id"])
                break
    return chosen


def arrange(slots, open_slots, chosen, current):
    """Put the chosen players in the open slots, keeping each in his
    current Sleeper slot when possible so there are as few moves as can be."""
    players = list(chosen.values())
    match = {i: p for i in open_slots for p in players
             if i < len(current) and current[i] == p["id"]}
    order = sorted(open_slots, key=lambda i: (len(_accepts(slots[i])), i))

    def place(p):
        # Shortest chain of moves that frees a slot for him (breadth-first)
        prev = {i: None for i in order if p["pos"] in _accepts(slots[i])}
        queue = deque(prev)
        while queue:
            i = queue.popleft()
            if i not in match:
                path = [i]
                while prev[path[-1]] is not None:
                    path.append(prev[path[-1]])
                for a, b in zip(path, path[1:]):
                    match[a] = match[b]  # the holder of b moves to a
                match[path[-1]] = p
                return
            for j in order:
                if j not in prev and match[i]["pos"] in _accepts(slots[j]):
                    prev[j] = i
                    queue.append(j)

    placed = {p["id"] for p in match.values()}
    for p in players:
        if p["id"] not in placed:
            place(p)
    return match if len(match) == len(players) else chosen


# ---------- win % ----------

def win_prob(mine, theirs):
    diff = mine["total"] - theirs["total"]
    var = mine["sd"] ** 2 + theirs["sd"] ** 2
    if var <= 1e-9:
        return 1.0 if diff > 0 else 0.0 if diff < 0 else 0.5
    return 0.5 * (1 + math.erf(diff / math.sqrt(2 * var)))


def mode_for(win, cfg):
    """Decided on the whole percent shown on the page, so "35%" is never
    called "under 35%"."""
    if win is None:
        return "even"
    win = math.floor(win * 100 + 0.5) / 100  # the same rounding as the page
    if win >= cfg["favored"]:
        return "favored"
    if win < cfg["underdog"]:
        return "underdog"
    return "even"


def _totals(entries):
    return {"total": sum(e["pts"] for e in entries),
            "sd": math.sqrt(sum(e["sd"] ** 2 for e in entries))}


# ---------- one line per starter ----------

def _signed(x):
    return f"{x:+.1f}".replace("-", "−")  # a real minus sign, as on the player card


def _why(p, e, close, swapped_for, mode, pcts=PCTS):
    if e["state"] == "final":
        return f"Played: {e['actual']:.1f} pts (My Score was {p['score']:.1f})"
    if e["state"] == "live":
        return (f"Playing now: {e['actual']:.1f} so far, {round(e['left'] * 100)}% of the game left"
                f" (My Score {p['score']:.1f})")
    main = None
    mine, theirs = outcome(p, pcts), outcome(swapped_for, pcts)
    if mine and theirs:
        if mode == "underdog" and mine[1] > theirs[1]:
            main = f"Higher ceiling than {swapped_for['name']} ({mine[1]:.1f} vs {theirs[1]:.1f})"
        elif mode == "favored" and mine[0] > theirs[0]:
            main = f"Safer floor than {swapped_for['name']} ({mine[0]:.1f} vs {theirs[0]:.1f})"
    if main is None and close is not None:
        main = f"Close call over {close[0]['name']} ({_signed(close[1])}{VALUE_NAME.get(mode, '')})"
    if main is None:
        main = f"#{p['rank']} {POS_WORD.get(p['pos'], p['pos'])} this week"
    if p.get("injury") in ("Questionable", "Doubtful"):
        extra = p["injury"] + (f" ({p['injury_detail']})" if p.get("injury_detail") else "")
    else:
        moves = [a for a in p.get("adj") or [] if a["key"] != "injury" and abs(a["pts"]) >= 0.5]
        top = max(moves, key=lambda a: abs(a["pts"]), default=None)
        extra = f"{top['label'].lower()} ({_signed(top['pts'])})" if top else ""
    return main + (" · " + extra if extra else "")


# ---------- close calls ----------

def _last(name):
    parts = name.split()
    while len(parts) > 1 and parts[-1].rstrip(".") in SUFFIXES:
        parts.pop()
    return parts[-1] if parts else name


def case_for(p, other, mode, pcts=PCTS):
    """Short reasons to play p over other, all real numbers from the data.
    What the mode cares about comes first (ceiling when underdog, floor
    when favored, expected points otherwise). Adjustments are compared by
    kind, so a matchup both players share isn't listed as a difference."""
    reasons = []  # (priority, text)
    mine, theirs = outcome(p, pcts), outcome(other, pcts)
    if p["score"] - other["score"] >= 0.1:
        reasons.append((1 if mode == "even" else 3,
                        f"More expected points: {p['score']:.1f} vs {other['score']:.1f}"))
    if mine and theirs:
        if mine[1] - theirs[1] >= 0.5:
            reasons.append((1 if mode == "underdog" else 4,
                            f"Higher ceiling: {mine[1]:.1f} vs {theirs[1]:.1f}"))
        if mine[0] - theirs[0] >= 0.5:
            reasons.append((1 if mode == "favored" else 4,
                            f"Safer floor: {mine[0]:.1f} vs {theirs[0]:.1f}"))
    tagged = ("Questionable", "Doubtful")
    if other.get("injury") in tagged and p.get("injury") not in tagged:
        detail = f" ({other['injury_detail']})" if other.get("injury_detail") else ""
        reasons.append((2, f"{_last(other['name'])} is {other['injury']}{detail}"))
    own = {a["key"]: a for a in p.get("adj") or [] if a["key"] != "injury"}
    theirs_adj = {a["key"]: a for a in other.get("adj") or [] if a["key"] != "injury"}
    for key in sorted(set(own) | set(theirs_adj)):
        a, b = own.get(key), theirs_adj.get(key)
        diff = (a["pts"] if a else 0.0) - (b["pts"] if b else 0.0)
        if diff < 0.5:
            continue
        rank = 5 - min(diff, 3) / 10
        if a and a["pts"] >= 0.5:
            vs = f" vs {_signed(b['pts'])} for {_last(other['name'])}" if b else ""
            text = f"{a['label']} ({_signed(a['pts'])}{vs}): {a['why']}"
        else:
            vs = f" vs {_signed(a['pts'])} for {_last(p['name'])}" if a else ""
            text = f"{_last(other['name'])} has a {b['label'].lower()} ({_signed(b['pts'])}{vs})"
        reasons.append((rank, text))
    c1, c2 = (p.get("cons") or {}).get("pts"), (other.get("cons") or {}).get("pts")
    if c1 is not None and c2 is not None and c1 - c2 >= 0.5:
        reasons.append((6, f"Experts like him more: {c1:.1f} vs {c2:.1f} pts"))
    reasons.sort(key=lambda r: r[0])
    return [text for _, text in reasons[:4]]


def close_calls(slots, entries, bench, value, mode, gap, by_id, pcts=PCTS):
    """Each bench player against the starter he'd replace (the weakest one
    in a slot he can play), kept when they're within `gap` on the mode's
    number. The gap is taken from the two numbers as shown (rounded), so
    the page always adds up. At most CALLS_PER_STARTER per starter and
    MAX_CALLS in all."""
    starters = [(i, by_id[e["id"]]) for i, e in enumerate(entries)
                if e["state"] == "pre" and e["id"] in by_id]
    calls = []
    for b in bench:
        options = [(i, s) for i, s in starters if b["pos"] in _accepts(slots[i])]
        if not options:
            continue
        i, s = min(options, key=lambda o: (value(o[1]), o[1]["score"], o[0]))
        values = [round(value(s), 1), round(value(b), 1)]
        margin = max(0.0, round(values[0] - values[1], 1))
        if margin < gap:
            calls.append({"slot": slots[i], "start": s["id"], "bench": b["id"],
                          "gap": margin, "measure": MEASURE[mode], "values": values,
                          "for_start": case_for(s, b, mode, pcts),
                          "for_bench": case_for(b, s, mode, pcts)})
    calls.sort(key=lambda c: (c["gap"], c["start"], c["bench"]))
    kept, per = [], {}
    for c in calls:
        if per.get(c["start"], 0) < CALLS_PER_STARTER and len(kept) < MAX_CALLS:
            per[c["start"]] = per.get(c["start"], 0) + 1
            kept.append(c)
    return kept


# ---------- late swap ----------

def _match(slots, idxs, players):
    """Any way to seat all players in these slots (or None)."""
    match = {}

    def place(p, seen):
        for i in idxs:
            if i in seen or p["pos"] not in _accepts(slots[i]):
                continue
            seen.add(i)
            if i not in match or place(match[i], seen):
                match[i] = p
                return True
        return False

    for p in players:
        if not place(p, set()):
            return None
    return match


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%MZ") if dt else None


def late_swap(slots, open_slots, final, kickoff):
    """Same starters, rearranged so the FLEX slots hold the latest games.
    Sleeper locks a slot when its player's game starts, so a late player
    in FLEX keeps the most options: if news breaks before his game, any
    RB/WR/TE whose game hasn't started (a free agent too) can go in.
    Returns the moves and the deadline (the earliest kickoff among the
    players who move), or None when FLEX already has the latest games."""
    if any(i not in final for i in open_slots):
        return None  # an empty slot is the bigger problem
    multi = [i for i in open_slots if len(_accepts(slots[i])) > 1]
    singles = [i for i in open_slots if i not in multi]
    players = [final[i] for i in open_slots]
    if not multi or any(kickoff(p) is None for p in players):
        return None  # no kickoff times to compare
    in_multi = {final[i]["id"] for i in multi}

    def kicks(group):
        return tuple(sorted((kickoff(p) for p in group), reverse=True))

    best, best_key = None, (kicks(final[i] for i in multi), 0)
    for combo in combinations(players, len(multi)):
        if _match(slots, multi, combo) is None:
            continue
        rest = [p for p in players if p not in combo]
        if _match(slots, singles, rest) is None:
            continue
        moved = sum(p["id"] not in in_multi for p in combo)
        key = (kicks(combo), -moved)
        if key[0] > best_key[0] or (best is not None and key[0] == best_key[0] and key[1] > best_key[1]):
            best, best_key = combo, key
    if best is None:
        return None
    ins = [p for p in best if p["id"] not in in_multi]
    outs = [final[i] for i in multi if final[i]["id"] not in {p["id"] for p in best}]
    freed = [i for i in singles if final[i]["id"] in {p["id"] for p in ins}]
    seats = _match(slots, freed, outs) or {}
    to = "FLEX" if all(slots[i] == "FLEX" for i in multi) else slots[multi[0]]
    moves = [{"id": p["id"], "to": to} for p in ins]
    moves += [{"id": p["id"], "to": slots[i]} for i, p in sorted(seats.items())]
    latest = max(ins, key=kickoff)
    return {"moves": moves, "latest": latest["id"], "kickoff": _iso(kickoff(latest)),
            "deadline": _iso(min(kickoff(p) for p in ins + outs))}


# ---------- bench and free agents ----------

def label(p, ratios, cfg, pcts=PCTS):
    """"Boom" when his ceiling/score is well above the usual for his
    position, "Steady" when his floor/score is; "" otherwise. Ratios are
    (floor, ceiling, sd) per score point, from model.position_ratios."""
    if (p.get("range") or {}).get("if_plays"):
        return ""  # a Doubtful player's spread is mostly "will he play", not his style
    found, usual = outcome(p, pcts), (ratios or {}).get(p["pos"])
    if not found or not usual or p["score"] <= 0 or usual[0] <= 0 or usual[1] <= 0:
        return ""
    boom = found[1] / p["score"] / usual[1] - cfg["boom"]
    steady = found[0] / p["score"] / usual[0] - cfg["steady"]
    if boom >= 0 and boom >= steady:
        return "Boom"
    return "Steady" if steady >= 0 else ""


def _dropped_recently(pid, market, now):
    """When he was dropped, if recent enough that he may still be on waivers
    (dropped within the league's waiver_clear_days, plus a day for the
    daily waiver run)."""
    when = (market.get("dropped") or {}).get(pid)
    if not when or now is None:
        return None
    dropped = datetime.fromtimestamp(when / 1000, timezone.utc)
    if now - dropped <= timedelta(days=market.get("clear_days", 1) + 1):
        return _iso(dropped)
    return None


def pickups(slots, entries, bench, by_id, value, mode, cfg, market, now, phase_of, pcts=PCTS):
    """Best options on my bench, and the free agents most worth starting
    (they beat the starter they'd replace, or fill an empty slot) or
    grabbing. Each player is compared with the weakest not-yet-played
    starter in a slot he can play, the same rule as close calls; an empty
    slot (bye, injury) counts as 0. In a leaned mode both numbers are in
    the line, because the rows themselves show My Score."""
    ratios, labels = market.get("ratios"), market.get("labels") or {"boom": 1.05, "steady": 1.10}
    starters = [(i, by_id[e["id"]]) for i, e in enumerate(entries)
                if e["state"] == "pre" and e["id"] in by_id]
    empty = [slots[i] for i, e in enumerate(entries) if e["state"] == "empty"]
    m = VALUE_NAME.get(mode, "")

    def compare(p):
        """(gap, starter or None, empty slot or None, text) for p vs the
        spot he'd take; None when no unplayed slot fits him."""
        vp = round(value(p), 1)
        hole = next((slot for slot in empty if p["pos"] in _accepts(slot)), None)
        if hole:
            return vp, None, hole, f"Fills your empty {hole} slot ({_signed(vp)}{m})"
        options = [s for i, s in starters if p["pos"] in _accepts(slots[i])]
        low = min(options, key=lambda s: (value(s), s["score"]), default=None)
        if low is None:
            return None, None, None, ""
        vs = round(value(low), 1)
        g = round(vp - vs, 1)
        nums = f": {vp:.1f} vs {vs:.1f}{m}" if m else ""
        if g > 0:
            text = f"Start over {low['name']}" + (nums if m else f" ({_signed(g)})")
        else:
            text = f"{abs(g):.1f} behind {low['name']}{nums}"
        return g, low, None, text

    bench_flex = []
    for b in sorted((b for b in bench if b["pos"] in ("RB", "WR", "TE")), key=value, reverse=True):
        g, low, hole, text = compare(b)
        if g is None:
            continue
        bench_flex.append({"id": b["id"], "value": round(value(b), 1),
                           "behind": low["id"] if low else None, "gap": g,
                           "label": label(b, ratios, labels, pcts), "why": text})
        if len(bench_flex) == 3:
            break

    rows = []
    for p in by_id.values():
        if p["roster"] is not None or p.get("flag") in OUT_STATUSES or not p.get("opp"):
            continue
        can_start = phase_of(p) == "pre"
        g, low, hole, text = compare(p) if can_start else (None, None, None, "")
        rows.append({"p": p, "can_start": can_start, "gap": g, "low": low, "hole": hole, "text": text})
    worth = sorted((r for r in rows if r["gap"] is not None and r["gap"] > 0), key=lambda r: -r["gap"])
    rest = sorted((r for r in rows if r not in worth and r["p"]["pos"] in ("RB", "WR", "TE")),
                  key=lambda r: (not r["can_start"], -value(r["p"]), r["p"]["name"]))
    chosen, per_pos = [], {}
    for r in worth + rest:
        if len(chosen) >= cfg.get("free_agents", 5):
            break
        pos = r["p"]["pos"]
        if per_pos.get(pos, 0) >= 2:
            continue
        per_pos[pos] = per_pos.get(pos, 0) + 1
        chosen.append(r)

    free_agents = []
    for r in chosen:
        p = r["p"]
        if not r["can_start"]:
            why = "His game has started: one to grab for later weeks"
        elif r["gap"] is not None and r["gap"] > 0:
            why = r["text"]
        else:
            why = f"#{p['rank']} {POS_WORD.get(p['pos'], p['pos'])} this week"
            if r["text"]:
                why += f" · {r['text']}"
        worth_it = r["gap"] is not None and r["gap"] > 0
        free_agents.append({"id": p["id"], "value": round(value(p), 1), "can_start": r["can_start"],
                            "start_over": r["low"]["id"] if worth_it and r["low"] else None,
                            "fills": r["hole"], "gap": r["gap"],
                            "label": label(p, ratios, labels, pcts),
                            "trending": (market.get("trending") or {}).get(p["id"]),
                            "dropped": _dropped_recently(p["id"], market, now), "why": why})
    return bench_flex, free_agents


def _entry(slot, pid, p, game, actual, now, pcts, scoring):
    if not pid or pid == "0":
        return {"slot": slot, "id": None, "pts": 0.0, "sd": 0.0, "state": "empty",
                "actual": None, "left": 0.0}
    return {"slot": slot, "id": pid, **expected(p, game, actual, now, pcts, scoring)}


def _round(e):
    e["pts"], e["sd"] = round(e["pts"], 1), round(e["sd"], 2)
    if e.get("actual") is not None:
        e["actual"] = round(e["actual"], 2)
    return e


# ---------- putting it together ----------

def build(positions, ctx, roster_positions, games, cfg, now, scoring=None, market=None):
    """positions: latest.json's positions; ctx: league.context(); games:
    espn.by_team(); cfg: settings.toml [lineup] plus floor_pct/ceiling_pct;
    now: ISO time of the run; scoring: the league's scoring_settings;
    market: trending adds, recent drops, waiver days, position ratios and
    label cutoffs (build.fetch_market)."""
    my_rid, opp_rid = ctx.get("my_rid"), ctx.get("opp_rid")
    if my_rid is None:
        return None
    now_dt = _time(now)
    pcts = (cfg.get("floor_pct", PCTS[0]), cfg.get("ceiling_pct", PCTS[1]))
    slots = [s for s in roster_positions if s not in NOT_SLOTS]
    by_id = {p["id"]: p for block in positions.values() for p in block["players"]}

    def game_of(p):
        return games.get(p["team"]) if p else None

    mine = ctx["lineups"].get(my_rid) or {"starters": [], "points": {}}
    current = (mine["starters"] + ["0"] * len(slots))[:len(slots)]
    reserve = set(ctx.get("reserve", {}).get(my_rid) or [])
    roster = [p for p in by_id.values() if p["roster"] == my_rid]
    phases = {p["id"]: phase(p, game_of(p), now_dt, mine["points"].get(p["id"]))[0] for p in roster}

    # Locked starters stay put; the rest of the healthy, not-yet-played
    # roster competes for the open slots
    fixed = {i: by_id[pid] for i, pid in enumerate(current)
             if pid in by_id and phases.get(pid) in ("live", "final")}
    open_slots = [i for i in range(len(slots)) if i not in fixed]
    fixed_ids = {p["id"] for p in fixed.values()}
    pool = [p for p in roster
            if p["id"] not in reserve and p["id"] not in fixed_ids
            and p.get("flag") not in OUT_STATUSES and phases[p["id"]] == "pre"]

    def lineup_entries(chosen):
        out = []
        for i, slot in enumerate(slots):
            p = fixed.get(i) or chosen.get(i)
            pid = p["id"] if p else None
            out.append(_entry(slot, pid, p, game_of(p), mine["points"].get(pid), now_dt, pcts, scoring))
        return out

    theirs = None
    if opp_rid is not None and opp_rid in ctx["lineups"]:
        opp = ctx["lineups"][opp_rid]
        starters = (opp["starters"] + ["0"] * len(slots))[:len(slots)]
        opp_entries = [_entry(slot, pid, by_id.get(pid), game_of(by_id.get(pid)),
                              opp["points"].get(pid), now_dt, pcts, scoring)
                       for slot, pid in zip(slots, starters)]
        theirs = {**_totals(opp_entries), "starters": opp_entries}

    # Pass 1: best lineup by My Score -> win % -> mode
    first = pick(slots, open_slots, pool, lambda p: p["score"])
    first_tot = _totals(lineup_entries(first))
    win0 = win_prob(first_tot, theirs) if theirs else None
    mode = mode_for(win0, cfg)

    # Pass 2: rank by the mode's number and pick again
    value = lean_value(mode, cfg["lean"], pcts)
    final = first if mode == "even" else pick(slots, open_slots, pool, value)
    final = arrange(slots, open_slots, final, current)
    entries = lineup_entries(final)
    me = _totals(entries)
    win = win_prob(me, theirs) if theirs else None

    # Close calls, one line per starter, and what changes from the Sleeper lineup
    final_ids = {p["id"] for p in final.values()} | fixed_ids
    first_ids = {p["id"] for p in first.values()}
    dropped = [p for p in first.values() if p["id"] not in final_ids]
    bench = [b for b in pool if b["id"] not in final_ids]
    calls = close_calls(slots, entries, bench, value, mode, cfg["close_call"], by_id, pcts)
    closest = {}
    for c in calls:  # sorted closest first
        closest.setdefault(c["start"], (by_id[c["bench"]], c["gap"]))
    for i, e in enumerate(entries):
        p = by_id.get(e["id"])
        if not p:
            continue
        swapped = None
        if mode != "even" and p["id"] not in first_ids:
            # The leaned pick he displaced: someone who could play an open slot he can
            options = [d for d in dropped
                       if any(p["pos"] in _accepts(slots[j]) and d["pos"] in _accepts(slots[j])
                              for j in open_slots)]
            swapped = max(options, key=lambda d: d["score"], default=None)
        e["why"] = _why(p, e, closest.get(p["id"]), swapped, mode, pcts)
        e["new"] = p["id"] not in current

    # Changes, in the order to make them in Sleeper: slide kept starters
    # first (so a newcomer's slot opens up), then starts, then benchings.
    outs = [pid for pid in current if pid and pid != "0" and pid not in final_ids]
    moves = [{"id": e["id"], "to": slots[i]} for i, e in enumerate(entries)
             if e["id"] and not e.get("new") and e["id"] != current[i] and i not in fixed]
    changes, waiting = [], []
    for i, e in enumerate(entries):
        if e.get("new") and e["id"]:
            if current[i] in outs:
                outs.remove(current[i])
                e["replaces"] = current[i]
                changes.append({"slot": slots[i], "in": e["id"], "out": current[i]})
            else:
                waiting.append(i)
    for i in waiting:
        e = entries[i]
        here = None if current[i] in ("0", "", None) or not outs else outs.pop(0)
        e["replaces"] = here
        changes.append({"slot": slots[i], "in": e["id"], "out": here})
    changes += [{"slot": None, "in": None, "out": pid} for pid in outs]

    def kickoff(p):
        return _time((game_of(p) or {}).get("kickoff"))
    swap = late_swap(slots, open_slots, final, kickoff)
    bench_flex, free_agents = pickups(
        slots, entries, bench, by_id, value, mode, cfg, market or {}, now_dt,
        lambda p: phase(p, game_of(p), now_dt)[0], pcts)

    return {
        "slots": slots, "mode": mode, "win": None if win is None else round(win, 3),
        "lean": cfg["lean"], "favored": cfg["favored"], "underdog": cfg["underdog"],
        "close_call": cfg["close_call"],
        # Without ESPN, game times are guessed from Sleeper (points = played)
        "times_known": bool(games),
        "first": {"total": round(first_tot["total"], 1), "sd": round(first_tot["sd"], 2),
                  "win": None if win0 is None else round(win0, 3)},
        "me": {"total": round(me["total"], 1), "sd": round(me["sd"], 2),
               "starters": [_round(e) for e in entries]},
        "opp": None if theirs is None else {
            "total": round(theirs["total"], 1), "sd": round(theirs["sd"], 2),
            "starters": [_round(e) for e in theirs["starters"]]},
        "current": current,
        "moves": moves,
        "changes": changes,
        "close_calls": calls,
        "late_swap": swap,
        "bench_flex": bench_flex,
        "free_agents": free_agents,
    }
