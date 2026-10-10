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
from datetime import datetime

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


def _why(p, e, alt, margin, swapped_for, mode, gap):
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
    elif alt is not None and margin < gap:
        main = f"Close call over {alt['name']} ({_signed(margin)}{VALUE_NAME.get(mode, '')})"
    else:
        main = f"#{p['rank']} {POS_WORD.get(p['pos'], p['pos'])} this week"
    if p.get("injury") in ("Questionable", "Doubtful"):
        extra = p["injury"] + (f" ({p['injury_detail']})" if p.get("injury_detail") else "")
    else:
        moves = [a for a in p.get("adj") or [] if a["key"] != "injury" and abs(a["pts"]) >= 0.5]
        top = max(moves, key=lambda a: abs(a["pts"]), default=None)
        extra = f"{top['label'].lower()} ({_signed(top['pts'])})" if top else ""
    return main + (" · " + extra if extra else "")


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

    # One line per starter, and what changes from the Sleeper lineup
    final_ids = {p["id"] for p in final.values()} | fixed_ids
    first_ids = {p["id"] for p in first.values()}
    dropped = [p for p in first.values() if p["id"] not in final_ids]
    for i, e in enumerate(entries):
        p = by_id.get(e["id"])
        if not p:
            continue
        bench = [b for b in pool if b["id"] not in final_ids and b["pos"] in _accepts(slots[i])]
        alt = max(bench, key=value, default=None)
        margin = value(p) - value(alt) if alt else 0.0
        swapped = None
        if mode != "even" and p["id"] not in first_ids:
            options = [d for d in dropped if d["pos"] in _accepts(slots[i])] or dropped
            swapped = max(options, key=lambda d: d["score"], default=None)
        e["why"] = _why(p, e, alt, margin, swapped, mode, cfg["close_call"])
        e["new"] = p["id"] not in current

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
    }
