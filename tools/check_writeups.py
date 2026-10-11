#!/usr/bin/env python3
"""Check inputs/writeups.json (written by /writeups) against the data it
was written from, before it's pushed:

- same season and week as the data, every player id is in the data
- each write-up is 2-4 sentences and not too long
- every number in the text is in that player's data, the matchup (win %,
  totals, close calls) or the league's scoring: "only real numbers"

    python3 tools/check_writeups.py inputs/writeups.json /tmp/latest.json

Prints each problem and exits 1 if there are any.
"""

import json
import re
import sys

NUM = re.compile(r"(?<![\w.])\d+(?:\.\d+)?")
MAX_CHARS = 700


def _forms(x):
    """The ways a number can be written: 9.7, 9.70, 10, 13.7% -> 14%."""
    x = abs(float(x))
    out = {f"{x:.1f}", f"{x:.2f}", f"{x:g}", str(round(x))}
    if x == int(x):
        out.add(str(int(x)))
    return out


def _walk(x, out):
    if isinstance(x, bool) or x is None:
        return
    if isinstance(x, (int, float)):
        out |= _forms(x)
    elif isinstance(x, str):
        out.update(NUM.findall(x))
    elif isinstance(x, dict):
        for v in x.values():
            _walk(v, out)
    elif isinstance(x, list):
        for v in x:
            _walk(v, out)


def allowed_numbers(pid, data, player):
    out = {str(data.get("week")), str(data.get("season"))}
    _walk(player, out)
    lg = data.get("league") or {}
    _walk(lg.get("scoring"), out)
    _walk([t for t in (lg.get("teams") or {}).values()], out)
    L = data.get("lineup") or {}
    for key in ("win", "first"):
        v = L.get(key)
        if isinstance(v, (int, float)):
            out |= _forms(v * 100) | _forms(v)
        elif isinstance(v, dict) and isinstance(v.get("win"), (int, float)):
            out |= _forms(v["win"] * 100)
    for side in ("me", "opp"):
        s = L.get(side) or {}
        _walk([s.get("total"), s.get("sd")], out)
        for e in s.get("starters") or []:
            if e.get("id") == pid:
                _walk(e, out)
    for c in L.get("close_calls") or []:
        if pid in (c.get("start"), c.get("bench")):
            _walk([c.get("gap"), c.get("values")], out)
    for key in ("bench_flex", "free_agents"):
        for b in L.get(key) or []:
            if b.get("id") == pid:
                _walk(b, out)
    return out


def sentences(text):
    return [s for s in re.split(r"(?<=[.!?])\s+(?=[A-Z\"“(])", text.strip()) if s]


def check(file, data):
    problems = []
    if str(file.get("season")) != str(data.get("season")) or file.get("week") != data.get("week"):
        problems.append(f"file is for {file.get('season')} week {file.get('week')}, "
                        f"data is {data.get('season')} week {data.get('week')}")
    if not file.get("written"):
        problems.append('missing "written" (ISO time)')
    players = {p["id"]: p for b in data.get("positions", {}).values() for p in b["players"]}
    entries = file.get("players") or {}
    if not entries:
        problems.append("no players")
    for pid, e in entries.items():
        p = players.get(pid)
        if p is None:
            problems.append(f"{pid}: not in the data")
            continue
        text = (e or {}).get("text") or ""
        name = p["name"]
        n = len(sentences(text))
        if not 2 <= n <= 4:
            problems.append(f"{name}: {n} sentences (want 2-4)")
        if len(text) > MAX_CHARS:
            problems.append(f"{name}: {len(text)} characters (max {MAX_CHARS})")
        status = p.get("injury") or ""
        if (e or {}).get("status", "") != status:
            problems.append(f"{name}: status should be {status or 'empty (healthy)'}")
        stray = sorted(set(NUM.findall(text)) - allowed_numbers(pid, data, p))
        if stray:
            problems.append(f"{name}: numbers not in his data: {', '.join(stray)}")
    return problems


def main(argv):
    if len(argv) != 3:
        sys.exit(__doc__)
    with open(argv[1], encoding="utf-8") as f:
        file = json.load(f)
    with open(argv[2], encoding="utf-8") as f:
        data = json.load(f)
    problems = check(file, data)
    for p in problems:
        print("PROBLEM:", p)
    print(f"{len(file.get('players') or {})} write-ups checked, {len(problems)} problem(s)")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main(sys.argv)
