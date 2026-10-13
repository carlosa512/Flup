"""News links per player: headline, source, date and link only (never the
article text). All free, no keys:

- ESPN's per-player fantasy news (same public ESPN API as the lines),
  matched by ESPN ID. Mostly RotoWire one-liners, which have no article
  link, so they link to the player's ESPN page.
- Pro Football Talk and RotoBaller RSS (aggregators), matched by full name.
- One or two beat writers per team on Bluesky (settings.toml
  [news.beat]): their posts that name the player (full name, or a last
  name no teammate shares).
- League-wide fantasy news accounts on Bluesky (settings.toml [news]
  league_wide: RotoWire, Rotoworld): posts that name the player in full,
  or by a last name no other projected player has. A week of posts is a
  few pages.

Each player keeps his newest few links from the last few days; a headline
that names him beats one that doesn't (ESPN also files league-wide
articles, like waiver lists, under each player).
"""

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from .consensus import norm_name
from .fetch import FetchError, get_json, get_text

ESPN_NEWS = "https://site.api.espn.com/apis/fantasy/v2/games/ffl/news/players?limit=10&playerId={eid}"
ESPN_PLAYER = "https://www.espn.com/nfl/player/_/id/{eid}"
RSS = {"Pro Football Talk": "https://profootballtalk.nbcsports.com/feed/",
       "RotoBaller": "https://www.rotoballer.com/category/nfl/feed"}
BSKY_FEED = ("https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed"
             "?actor={handle}&filter=posts_no_replies&limit=30")
BSKY_POST = "https://bsky.app/profile/{handle}/post/{rkey}"
BSKY_PAGE = ("https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed"
             "?actor={handle}&filter=posts_no_replies&limit=100")
BEAT, AGGREGATOR = "beat reporter", "aggregator"
TITLE_MAX = 140
GIVE_UP = 3  # requests that fail in a row, with none working, before a source is skipped


def _when(text):
    """ISO or RFC 822 date -> aware datetime, or None."""
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _short(text):
    text = " ".join((text or "").split())
    return text if len(text) <= TITLE_MAX else text[:TITLE_MAX - 1].rstrip() + "…"


def _web(url):
    """Only real web links (a feed could carry javascript: or data: ones)."""
    url = (url or "").strip()
    return url if url.startswith(("https://", "http://")) else None


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------- parsing each source ----------

def parse_espn(data, eid, name):
    out = []
    for a in (data or {}).get("feed") or []:
        when = _when(a.get("published") or a.get("lastModified"))
        title = a.get("headline") or a.get("title")
        if not when or not title:
            continue
        if a.get("type") == "Rotowire":
            out.append({"title": _short(title), "source": "RotoWire (ESPN)", "tag": AGGREGATOR,
                        "date": when, "url": ESPN_PLAYER.format(eid=eid), "page": True})
            continue
        url = _web(((a.get("links") or {}).get("web") or {}).get("href"))
        if url and (names_full(title, name) or names_last(title, _last(name), _first(name))):
            # ESPN files league-wide stories under each player they mention
            out.append({"title": _short(title), "source": "ESPN", "tag": AGGREGATOR,
                        "date": when, "url": url})
    return out


def parse_rss(text, source):
    try:
        root = ET.fromstring(text.encode("utf-8") if isinstance(text, str) else text)
    except ET.ParseError:
        raise FetchError(f"{source}'s feed isn't valid RSS")
    out = []
    for it in root.iter("item"):
        title, url, when = it.findtext("title"), _web(it.findtext("link")), _when(it.findtext("pubDate"))
        if title and url and when:
            out.append({"title": _short(title.strip()), "source": source, "tag": AGGREGATOR,
                        "date": when, "url": url})
    return out


def _facet_link(record):
    """The first link in a post's text (RotoWire's posts have no link card)."""
    for facet in record.get("facets") or []:
        for feature in facet.get("features") or []:
            if _web(feature.get("uri")):
                return feature["uri"]
    return None


def parse_bsky(data, handle, tag=BEAT):
    """A writer's own posts (no reposts): the linked article's headline when
    the post links one, else the post's words (links taken out)."""
    out = []
    for item in (data or {}).get("feed") or []:
        if item.get("reason"):
            continue  # a repost of someone else
        post = item.get("post") or {}
        if (post.get("author") or {}).get("handle", handle) != handle:
            continue
        record = post.get("record") or {}
        when = _when(record.get("createdAt"))
        text = record.get("text") or ""
        if not when or not (text or post.get("embed")):
            continue
        ext = (post.get("embed") or {}).get("external") or {}
        if not _web(ext.get("uri")):
            ext = {}
        rkey = (post.get("uri") or "").rsplit("/", 1)[-1]
        url = ext.get("uri") or _facet_link(record) or BSKY_POST.format(handle=handle, rkey=rkey)
        words = re.sub(r"https?://\S+", " ", text)
        out.append({"title": _short(ext.get("title") or words), "text": words + " " + (ext.get("title") or ""),
                    "source": (post.get("author") or {}).get("displayName") or handle,
                    "tag": tag, "date": when, "url": url,
                    # RotoWire links every note to the player's page
                    **({"page": True} if "/player/" in url else {})})
    return out


# ---------- who a headline is about ----------

def _words(text):
    """Lowercase words without punctuation or a possessive 's:
    "Josh Allen's," -> "josh allen"."""
    t = norm_name(re.sub(r"['’]s\b", "", text or ""))
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", t).split())


def names_full(text, name):
    """Does the text name him in full (any case, punctuation ignored)?"""
    return f" {_words(name)} " in f" {_words(text)} "


def names_last(text, last, first="", team=()):
    """Capitalized last name as a whole word ("Love", not "love"), and not
    right after someone else's first name ("Tyleik Williams" isn't Jameson).
    A position, team possessive or sentence start before it is fine. team:
    his teammates' full names, so a teammate whose first name this is
    ("Chase Brown" when he's Ja'Marr Chase) doesn't count."""
    if not last:
        return False
    text = re.sub(r"['’]s\b", "", text or "")  # possessive: "Allen's" -> "Allen"
    others = {_words(n) for n in team}
    for m in re.finditer(rf"(?<![\w']){re.escape(last)}(?![\w'])", text):
        after = re.match(r"\s+([A-Z][\w'’.-]*)", text[m.end():])
        if after and _words(f"{last} {after.group(1)}") in others:
            continue
        before = re.search(r"(\S+)\s+$", text[:m.start()])
        word = before.group(1).strip("#(\"“") if before else ""
        other_first = (word[:1].isupper() and not word.isupper()
                       and not re.search(r"['’]s?$", word) and not word.endswith((".", ":", "!", "?"))
                       and norm_name(word) != norm_name(first))
        if not other_first:
            return True
    return False


def _first(name):
    return (name or "").split()[0] if name else ""


def _last(name):
    parts = [w for w in (name or "").replace(".", "").split() if w not in ("Jr", "Sr", "II", "III", "IV", "V")]
    return parts[-1] if len(parts) > 1 else ""


# ---------- putting it together ----------

def _few(names, n=3):
    return ", ".join(names[:n]) + (f" and {len(names) - n} more" if len(names) > n else "")


def _week_of_posts(fetch_json, handle, since, pages):
    """An account's own posts back to since, a page of 100 at a time."""
    posts, cursor = [], None
    for _ in range(pages):
        data = fetch_json(BSKY_PAGE.format(handle=handle) + (f"&cursor={cursor}" if cursor else ""))
        page = parse_bsky(data, handle, AGGREGATOR)
        posts += [x for x in page if x["date"] >= since]
        cursor = (data or {}).get("cursor")
        dates = [d for d in (_when(((x.get("post") or {}).get("record") or {}).get("createdAt"))
                             for x in (data or {}).get("feed") or []) if d]
        if not cursor or not dates or min(dates) < since:
            break
    return posts


def pick(items, name, cfg, now):
    """Newest links from the last cfg days, at most cfg max_links; ones that
    name him come first. Returned newest first."""
    since = now - timedelta(days=cfg.get("days", 7))
    seen, fresh = set(), []
    for it in sorted(items, key=lambda x: x["date"], reverse=True):
        # RotoWire notes all link to his player page: tell them apart by text
        keys = {_words(it["title"])} | ({it["url"]} if not it.get("page") else set())
        if not since <= it["date"] <= now + timedelta(hours=1) or keys & seen:
            continue
        seen |= keys
        fresh.append(it)
    last, first = _last(name), _first(name)
    ranked = sorted(fresh, key=lambda x: (not (names_full(x["title"], name) or names_last(x["title"], last, first)),
                                          -x["date"].timestamp()))
    chosen = sorted(ranked[:cfg.get("max_links", 3)], key=lambda x: x["date"], reverse=True)
    walls = cfg.get("paywalled") or []
    return [{"title": x["title"], "source": x["source"], "tag": x["tag"], "date": _iso(x["date"]),
             "url": x["url"], **({"paywall": True} if any(w in x["url"] for w in walls) else {})}
            for x in chosen]


def collect(players, espn_ids, teammates, cfg, now, fetch_json=get_json, fetch_text=get_text):
    """players: the ones who get news ({id, name, team, pos}); espn_ids:
    sleeper id -> ESPN id; teammates: team -> list of every projected
    player's name (to tell whether a last name is unique on the team).
    Returns ({player id: [links]}, source status text, ok)."""
    found = {p["id"]: [] for p in players}
    problems, notes = [], []

    # ESPN, one request per player
    asked = got = 0
    for p in players:
        eid = espn_ids.get(p["id"])
        if not eid or p["pos"] == "DEF":
            continue
        if asked >= GIVE_UP and not got:
            break  # down: don't spend minutes on retries
        asked += 1
        try:
            found[p["id"]] += parse_espn(fetch_json(ESPN_NEWS.format(eid=eid)), eid, p["name"])
            got += 1
        except FetchError:
            pass
    if asked:
        # A player or two missing is a note; the feed being down is a problem
        (notes if got * 2 >= asked else problems).append(f"ESPN {got}/{asked} players")

    # Aggregator feeds: full name in the headline
    for source, url in RSS.items():
        try:
            items = parse_rss(fetch_text(url), source)
        except FetchError:
            problems.append(f"{source} didn't load")
            continue
        notes.append(f"{source} ok")
        for p in players:
            if p["pos"] != "DEF":
                found[p["id"]] += [it for it in items if names_full(it["title"], p["name"])]

    # Beat writers: the teams these players are on
    beat = cfg.get("beat") or {}
    teams = sorted({p["team"] for p in players if p.get("team") in beat})
    quiet, failed, reached, wanted = [], [], 0, 0
    for team in teams:
        lasts = {}
        for n in teammates.get(team, []):
            lasts[_last(n)] = lasts.get(_last(n), 0) + 1
        on_team = [p for p in players if p.get("team") == team and p["pos"] != "DEF"]
        for handle in beat[team]:
            if len(failed) >= GIVE_UP and not reached:
                break  # Bluesky is down
            wanted += 1
            try:
                posts = parse_bsky(fetch_json(BSKY_FEED.format(handle=handle)), handle)
            except FetchError:
                failed.append(f"@{handle}")
                continue
            reached += 1
            newest = max((x["date"] for x in posts), default=None)
            if newest is None or newest < now - timedelta(days=cfg.get("inactive_days", 14)):
                quiet.append(f"@{handle}")
            for p in on_team:
                last = _last(p["name"])
                unique = lasts.get(last, 0) <= 1
                for it in posts:
                    if names_full(it["text"], p["name"]) or \
                            (unique and names_last(it["text"], last, _first(p["name"]), teammates.get(team, ()))):
                        found[p["id"]].append({k: v for k, v in it.items() if k != "text"})
    if wanted and not failed:
        notes.append(f"Bluesky {reached} beat writers")
    if failed:
        (problems if len(failed) * 2 > wanted else notes).append(
            f"Bluesky: {len(failed)} didn't load ({_few(failed)})")
    if quiet:
        notes.append(f"no posts in {cfg.get('inactive_days', 14)} days: {_few(quiet)}")

    # League-wide accounts: his full name, or a last name nobody else has
    lasts = {}
    for names in teammates.values():
        for n in names:
            lasts[_last(n)] = lasts.get(_last(n), 0) + 1
    everyone = [n for names in teammates.values() for n in names]
    since = now - timedelta(days=cfg.get("days", 7))
    for handle in cfg.get("league_wide") or []:
        try:
            posts = _week_of_posts(fetch_json, handle, since, cfg.get("league_wide_pages", 6))
        except FetchError:
            problems.append(f"@{handle} didn't load")
            continue
        notes.append(f"@{handle} {len(posts)} posts")
        for it in posts:  # "RotoWire Fantasy Football" -> "RotoWire"
            it["source"] = re.sub(r"\s+(Fantasy\s+)?Football$", "", it["source"])
        for p in players:
            if p["pos"] == "DEF":
                continue
            last, first = _last(p["name"]), _first(p["name"])
            unique = lasts.get(last, 0) <= 1
            for it in posts:
                # RotoWire's "Terry McLaurin: Likely to have restrictions" is
                # about him alone, not Isaiah Likely
                who = re.match(r"\s*([A-Z][\w'’.-]*(?: [A-Z][\w'’.-]*){1,3}):\s", it["text"])
                if who:
                    hit = names_full(who.group(1), p["name"])
                else:
                    hit = names_full(it["text"], p["name"]) or (
                        unique and last in it["text"] and names_last(it["text"], last, first, everyone))
                if hit:
                    found[p["id"]].append({k: v for k, v in it.items() if k != "text"})

    by_id = {p["id"]: p for p in players}
    news = {pid: pick(items, by_id[pid]["name"], cfg, now) for pid, items in found.items()}
    detail = "; ".join(notes + problems) or "no players to look up"
    return news, detail, not problems
