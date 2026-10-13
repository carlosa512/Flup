"""Template write-ups: 2-4 plain sentences from a player's breakdown.

1. The biggest factor first: whatever moves predicted points most away from
   Sleeper's projection (the expert blend, or one adjustment).
2. Where the experts and Sleeper disagree, and where predicted points starts.
3. The other adjustments worth half a point or more, and predicted points.
4. His floor and ceiling.

The wording varies by player (a fixed pick per player and week, so it
doesn't change between runs). Only numbers already in the data are used.
"""

import re
import zlib

from .model import OUT_STATUSES

BIG = 0.5           # adjustments smaller than this aren't named
DISAGREE = 0.12     # experts vs Sleeper differ by this share of the projection...
DISAGREE_MIN = 1.5  # ...and at least this many points


def _n(x):
    return f"{abs(x):.1f}"


def _signed(x):
    return ("+" if x >= 0 else "−") + _n(x)


def _noun(a):
    """An adjustment as a phrase: 'the matchup', 'his Questionable tag'."""
    return {
        "usage": "his recent usage", "environment": "the Vegas line", "matchup": "the matchup",
        "returns": "his return work", "injury": f"his {a['label']} tag",
    }.get(a["key"], "his interception habits" if a["label"] == "Turnover risk"
          else "his low-INT running" if a["label"] == "Low-INT runner" else a["label"].lower())


def _and(items):
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def writeup(p, week=0):
    """The write-up for one player (latest.json player dict)."""
    def pick(slot, *options):
        return options[zlib.crc32(f"{p.get('id')}:{week}:{slot}".encode()) % len(options)]

    if p.get("flag") in OUT_STATUSES:
        why = f" ({p['injury_detail']})" if p.get("injury_detail") else ""
        return f"He's listed {p['flag']}{why}, so he counts 0 this week."
    if p.get("note"):
        return p["note"] + "."

    proj, base, score = p.get("proj") or 0.0, p.get("base") or 0.0, p["score"]
    cons = p.get("cons") or {}
    blended = "consensus" in (p.get("blend") or "") and "only" not in (p.get("blend") or "")
    has_cons = blended and cons.get("pts") is not None and proj > 0
    rank = f"{p['pos']}{cons.get('rank')}"
    adj = sorted(p.get("adj") or [], key=lambda a: -abs(a["pts"]))
    pull = base - proj if has_cons else 0.0
    share = re.match(r"(\d+)% projection", p.get("blend") or "")

    # The experts vs Sleeper
    gap = (cons.get("pts") or 0.0) - proj
    disagree = has_cons and abs(gap) >= max(DISAGREE_MIN, DISAGREE * proj)
    if disagree:
        lower = gap < 0
        experts = [pick("cons",
                       f"The experts are {'lower' if lower else 'higher'} on him than Sleeper: {rank} "
                       f"is worth about {_n(cons['pts'])} in your scoring, vs Sleeper's {_n(proj)}.",
                       f"Experts rank him {rank} (about {_n(cons['pts'])} pts), "
                       f"{'below' if lower else 'above'} Sleeper's {_n(proj)}.",
                       f"Sleeper projects {_n(proj)}, but the experts' {rank} is worth about "
                       f"{_n(cons['pts'])}."),
                   f"The prediction keeps {share.group(1)}% of Sleeper's number, so it starts at {_n(base)}."
                   if share else f"The prediction starts at {_n(base)}."]
    elif has_cons:
        experts = [pick("agree",
                       f"Sleeper ({_n(proj)}) and the experts ({rank}, about {_n(cons['pts'])}) "
                       "roughly agree.",
                       f"Sleeper projects {_n(proj)} and the experts have him {rank} "
                       f"(about {_n(cons['pts'])}), close enough.")]
    elif proj > 0:
        experts = [f"No expert rank for him, so the prediction starts from Sleeper's {_n(proj)}."]
    else:
        experts = [f"Sleeper has no projection for him; the experts' {rank} is worth about {_n(base)}."]

    # Lead with the biggest factor (a Doubtful tag beats any number)
    sentences, rest = [], adj
    if p.get("flag") == "Doubtful":
        why = f" ({p['injury_detail']})" if p.get("injury_detail") else ""
        sentences.append(f"He's Doubtful{why}: the prediction assumes he plays, so have a backup ready.")
    top = adj[0] if adj else None
    if top and abs(top["pts"]) >= BIG and abs(top["pts"]) >= abs(pull):
        word = "boost" if top["pts"] > 0 else "drag"
        what = f"{_noun(top)} ({_signed(top['pts'])}): {top['why']}"
        sentences.append(pick("lead",
                              f"The biggest {word} is {what}.",
                              f"Most of the move comes from {what}.",
                              f"Start with {what}."))
        rest = adj[1:]
    sentences += experts[:1]
    optional = experts[1:]  # "predicted points keeps 60%..., so it starts at X"

    sentences += optional
    named = [a for a in rest if abs(a["pts"]) >= BIG]
    small = round(sum(a["pts"] for a in rest if abs(a["pts"]) < BIG), 1)
    tail = f", plus {_signed(small)} from small tweaks" if small else ""
    if named:
        sentences.append(pick("rest", "Also: ", "Then ", "On top of that, ")
                         + _and([f"{_noun(a)} ({_signed(a['pts'])})" for a in named])
                         + f"{tail}, for a prediction of {_n(score)}.")
    elif adj:
        sentences.append(f"Small tweaks only ({_signed(small)}), so the prediction is {_n(score)}."
                         if small else f"Predicted: {_n(score)}.")
    else:
        sentences.append(pick("none", f"No adjustments, so the prediction is {_n(score)}.",
                              f"Nothing else moves him: predicted {_n(score)}."))

    # At most 4: drop the "starts at" sentence before the one with predicted points
    while len(sentences) > 4 and optional:
        sentences.remove(optional.pop())
    r = p.get("range")
    if r and len(sentences) < 4:
        lo, hi = _n(r["floor"]), _n(r["ceiling"])
        sentences.append(f"If he plays: floor {lo}, ceiling {hi}." if r.get("if_plays") else
                         pick("range", f"Floor {lo}, ceiling {hi}.",
                              f"A quiet week is about {lo}, a big one {hi}.",
                              f"Range: {lo} to {hi}."))
    return " ".join(sentences)


# ---------- Claude's write-ups ----------
# The /writeups command (.claude/commands/writeups.md) writes
# inputs/writeups.json: {"season", "week", "written", "players":
# {id: {"text", "status"}}}, status = his injury status when written.

def attach_claude(positions, file, season, week):
    """Give players Claude's write-up for this week; the site shows it over
    the template. Flags a status change since it was written. Returns how
    many were attached."""
    if not file or str(file.get("season")) != str(season) or file.get("week") != week:
        return 0
    entries = file.get("players") or {}
    n = 0
    for block in positions.values():
        for p in block["players"]:
            e = entries.get(p["id"])
            if not e or not e.get("text"):
                continue
            p["claude"] = {"text": e["text"], "written": file.get("written")}
            then, now = e.get("status") or "", p.get("injury") or ""
            if then != now:
                p["claude"]["changed"] = f"{then or 'healthy'} -> {now or 'healthy'}"
            n += 1
    return n
