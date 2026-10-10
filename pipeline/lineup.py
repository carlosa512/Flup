"""My recommended lineup, both teams' expected totals, and my win %.

1. Each starter's expected points and spread (sd) for the week: a finished
   game is his actual points (sd 0); a live game is points so far plus My
   Score x the share of the game left; a game not started is My Score.
2. Best lineup by My Score from healthy players whose game hasn't started.
   A player whose game has started is locked: a starter stays in his slot,
   a bench player can't come in.
3. Win % = Phi((my total - their total) / sqrt(my variance + theirs)),
   treating players as independent (QB-WR stacks make it a bit
   overconfident). The opponent's lineup is used exactly as set in Sleeper.
4. That win % sets the mode: favored -> rank players partway toward their
   floor, underdog -> partway toward their ceiling, then pick again and
   report the final win %.
"""

import math
from collections import deque
from datetime import datetime, timezone
from itertools import combinations

from .model import OUT_STATUSES

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
EARLIEST = datetime.min.replace(tzinfo=timezone.utc)


def _time(iso):
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None


def _accepts(slot):
    return SLOT_POSITIONS.get(slot, {slot})


# ---------- one player's week ----------

def phase(p, game, now):
    """('none' | 'pre' | 'live' | 'final', share of the game left)."""
    if game is None:
        # No ESPN data for his team: trust the projection's opponent
        return ("pre", 1.0) if p and p.get("opp") else ("none", 0.0)
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


def outcome(p):
    """(floor, ceiling, sd) this week, or None. A Doubtful player's range is
    'if he plays', so it's scaled by his chance of playing, taken as My
    Score / his healthy score (Doubtful takes 60% off, so 40%)."""
    r = p.get("range") if p else None
    if not r:
        return None
    floor, ceiling, sd = r["floor"], r["ceiling"], abs(r["sd"])
    if r.get("if_plays"):
        healthy = p["score"] - sum(a["pts"] for a in p.get("adj") or [] if a["key"] == "injury")
        q = max(0.0, min(1.0, p["score"] / healthy)) if healthy > 0 else 0.0
        # Plays (his usual spread) with chance q, else scores 0
        sd = math.sqrt(q * sd ** 2 + q * (1 - q) * healthy ** 2)
        floor, ceiling = q * floor, q * ceiling
    return floor, ceiling, sd


def expected(p, game, actual, now):
    """Expected points and sd for the rest of the week, by game phase."""
    if p is None:
        # Not in this week's data (no projection row): only his actual points
        return {"state": "unknown", "pts": actual or 0.0, "sd": 0.0, "actual": actual, "left": 0.0}
    state, left = phase(p, game, now)
    score = p["score"] if p else 0.0
    found = outcome(p)
    sd = found[2] if found else 0.0
    got = actual or 0.0
    if state == "final":
        return {"state": state, "pts": got, "sd": 0.0, "actual": got, "left": 0.0}
    if state == "live":
        return {"state": state, "pts": got + score * left, "sd": sd * math.sqrt(left),
                "actual": got, "left": left}
    if state == "none":
        return {"state": state, "pts": 0.0, "sd": 0.0, "actual": None, "left": 0.0}
    return {"state": state, "pts": score, "sd": sd, "actual": None, "left": 1.0}


def lean_value(mode, lean):
    """The number players are ranked by: My Score, moved `lean` of the way
    to the floor (favored) or the ceiling (underdog)."""
    def value(p):
        found = outcome(p)
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
    if win is None:
        return "even"
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
    return f"{x:+.1f}".replace("-", "\u2212")  # a real minus sign, as on the player card


def _why(p, e, close, swapped_for, mode):
    if e["state"] == "final":
        return f"Played: {e['actual']:.1f} pts"
    if e["state"] == "live":
        return f"Playing now: {e['actual']:.1f} so far, {round(e['left'] * 100)}% of the game left"
    mine, theirs = outcome(p), outcome(swapped_for)
    if mine and theirs:
        if mode == "underdog":
            main = f"Higher ceiling than {swapped_for['name']} ({mine[1]:.1f} vs {theirs[1]:.1f})"
        else:
            main = f"Safer floor than {swapped_for['name']} ({mine[0]:.1f} vs {theirs[0]:.1f})"
    elif close is not None:
        main = f"Close call over {close[0]['name']} ({_signed(close[1])}{VALUE_NAME.get(mode, '')})"
    else:
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


def case_for(p, other, mode):
    """Short reasons to play p over other, all real numbers from the data.
    What the mode cares about comes first (ceiling when underdog, floor
    when favored, expected points otherwise)."""
    reasons = []  # (priority, text)
    mine, theirs = outcome(p), outcome(other)
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
    for a in p.get("adj") or []:
        if a["key"] != "injury" and a["pts"] >= 0.5:
            reasons.append((5 - min(a["pts"], 3) / 10, f"{a['label']} ({_signed(a['pts'])}): {a['why']}"))
    for a in other.get("adj") or []:
        if a["key"] != "injury" and a["pts"] <= -0.5:
            reasons.append((5 - min(-a["pts"], 3) / 10,
                            f"{_last(other['name'])} has a {a['label'].lower()} ({_signed(a['pts'])})"))
    c1, c2 = (p.get("cons") or {}).get("pts"), (other.get("cons") or {}).get("pts")
    if c1 is not None and c2 is not None and c1 - c2 >= 0.5:
        reasons.append((6, f"Experts like him more: {c1:.1f} vs {c2:.1f} pts"))
    reasons.sort(key=lambda r: r[0])
    return [text for _, text in reasons[:4]]


def close_calls(slots, entries, bench, value, mode, gap, by_id):
    """Each bench player against the starter he'd replace (the weakest one
    in a slot he can play), kept when they're within `gap` on the mode's
    number. At most CALLS_PER_STARTER per starter and MAX_CALLS in all."""
    starters = [(i, by_id[e["id"]]) for i, e in enumerate(entries)
                if e["state"] == "pre" and e["id"] in by_id]
    calls = []
    for b in bench:
        options = [(i, s) for i, s in starters if b["pos"] in _accepts(slots[i])]
        if not options:
            continue
        i, s = min(options, key=lambda o: (value(o[1]), o[1]["score"], o[0]))
        margin = max(0.0, value(s) - value(b))
        if margin < gap:
            calls.append({"slot": slots[i], "start": s["id"], "bench": b["id"],
                          "gap": round(margin, 1), "measure": MEASURE[mode],
                          "values": [round(value(s), 1), round(value(b), 1)],
                          "for_start": case_for(s, b, mode), "for_bench": case_for(b, s, mode)})
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


def late_swap(slots, open_slots, final, kickoff):
    """Same starters, rearranged so the FLEX slots hold the latest games.
    Sleeper locks a slot when its player's game starts, so a late player
    in FLEX keeps the most options: if news breaks before his game, any
    RB/WR/TE whose game hasn't started (a free agent too) can go in.
    Returns the moves, or None when FLEX already has the latest games."""
    if any(i not in final for i in open_slots):
        return None  # an empty slot is the bigger problem
    multi = [i for i in open_slots if len(_accepts(slots[i])) > 1]
    singles = [i for i in open_slots if i not in multi]
    if not multi:
        return None
    players = [final[i] for i in open_slots]
    in_multi = {final[i]["id"] for i in multi}

    def kicks(group):
        return tuple(sorted((kickoff(p) or EARLIEST for p in group), reverse=True))

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
    moves = [{"id": p["id"], "to": "FLEX" if all(slots[i] == "FLEX" for i in multi) else slots[multi[0]]}
             for p in ins]
    moves += [{"id": p["id"], "to": slots[i]} for i, p in sorted(seats.items())]
    latest = max(ins, key=lambda p: kickoff(p) or EARLIEST)
    when = kickoff(latest)
    return {"moves": moves, "latest": latest["id"],
            "kickoff": when.strftime("%Y-%m-%dT%H:%MZ") if when else None}


def _entry(slot, pid, p, game, actual, now):
    if not pid or pid == "0":
        return {"slot": slot, "id": None, "pts": 0.0, "sd": 0.0, "state": "empty",
                "actual": None, "left": 0.0}
    return {"slot": slot, "id": pid, **expected(p, game, actual, now)}


def _round(e):
    e["pts"], e["sd"] = round(e["pts"], 1), round(e["sd"], 2)
    if e.get("actual") is not None:
        e["actual"] = round(e["actual"], 2)
    return e


# ---------- putting it together ----------

def build(positions, ctx, roster_positions, games, cfg, now):
    """positions: latest.json's positions; ctx: league.context(); games:
    espn.by_team(); cfg: settings.toml [lineup]; now: ISO time of the run."""
    my_rid, opp_rid = ctx.get("my_rid"), ctx.get("opp_rid")
    if my_rid is None:
        return None
    now_dt = _time(now)
    slots = [s for s in roster_positions if s not in NOT_SLOTS]
    by_id = {p["id"]: p for block in positions.values() for p in block["players"]}

    def game_of(p):
        return games.get(p["team"]) if p else None

    mine = ctx["lineups"].get(my_rid) or {"starters": [], "points": {}}
    current = (mine["starters"] + ["0"] * len(slots))[:len(slots)]
    reserve = set(ctx.get("reserve", {}).get(my_rid) or [])
    roster = [p for p in by_id.values() if p["roster"] == my_rid]
    phases = {p["id"]: phase(p, game_of(p), now_dt)[0] for p in roster}

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
            out.append(_entry(slot, pid, p, game_of(p), mine["points"].get(pid), now_dt))
        return out

    theirs = None
    if opp_rid is not None and opp_rid in ctx["lineups"]:
        opp = ctx["lineups"][opp_rid]
        starters = (opp["starters"] + ["0"] * len(slots))[:len(slots)]
        opp_entries = [_entry(slot, pid, by_id.get(pid), game_of(by_id.get(pid)),
                              opp["points"].get(pid), now_dt)
                       for slot, pid in zip(slots, starters)]
        theirs = {**_totals(opp_entries), "starters": opp_entries}

    # Pass 1: best lineup by My Score -> win % -> mode
    first = pick(slots, open_slots, pool, lambda p: p["score"])
    first_tot = _totals(lineup_entries(first))
    win0 = win_prob(first_tot, theirs) if theirs else None
    mode = mode_for(win0, cfg)

    # Pass 2: rank by the mode's number and pick again
    value = lean_value(mode, cfg["lean"])
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
    calls = close_calls(slots, entries, bench, value, mode, cfg["close_call"], by_id)
    closest = {}
    for c in calls:  # sorted closest first
        closest.setdefault(c["start"], (by_id[c["bench"]], c["gap"]))
    for i, e in enumerate(entries):
        p = by_id.get(e["id"])
        if not p:
            continue
        swapped = None
        if mode != "even" and p["id"] not in first_ids:
            options = [d for d in dropped if d["pos"] in _accepts(slots[i])] or dropped
            swapped = max(options, key=lambda d: d["score"], default=None)
        e["why"] = _why(p, e, closest.get(p["id"]), swapped, mode)
        e["new"] = p["id"] not in current

    def kickoff(p):
        return _time((game_of(p) or {}).get("kickoff"))
    swap = late_swap(slots, open_slots, final, kickoff)

    current_ids = [pid for pid in current if pid and pid != "0"]
    outs = [pid for pid in current_ids if pid not in final_ids]
    changes = []
    for i, e in enumerate(entries):
        if not e.get("new") or not e["id"]:
            continue
        here = current[i] if current[i] in outs else (outs[0] if outs else None)
        if here:
            outs.remove(here)
        e["replaces"] = here
        changes.append({"slot": slots[i], "in": e["id"], "out": here})
    changes += [{"slot": None, "in": None, "out": pid} for pid in outs]

    return {
        "slots": slots, "mode": mode, "win": None if win is None else round(win, 3),
        "lean": cfg["lean"], "favored": cfg["favored"], "underdog": cfg["underdog"],
        "close_call": cfg["close_call"],
        "first": {"total": round(first_tot["total"], 1), "sd": round(first_tot["sd"], 2),
                  "win": None if win0 is None else round(win0, 3)},
        "me": {"total": round(me["total"], 1), "sd": round(me["sd"], 2),
               "starters": [_round(e) for e in entries]},
        "opp": None if theirs is None else {
            "total": round(theirs["total"], 1), "sd": round(theirs["sd"], 2),
            "starters": [_round(e) for e in theirs["starters"]]},
        "current": current,
        "changes": changes,
        "close_calls": calls,
        "late_swap": swap,
    }
