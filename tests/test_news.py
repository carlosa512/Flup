from datetime import datetime, timezone

from pipeline import news
from pipeline.fetch import FetchError

NOW = datetime(2026, 10, 11, 15, 0, tzinfo=timezone.utc)
CFG = {"max_links": 3, "days": 7, "inactive_days": 14, "paywalled": ["nytimes.com/athletic"],
       "beat": {"CIN": ["laurelpfahler.bsky.social"]}}

# Shapes as saved by the news probe (dev-snapshots news/, 2026-10-11)
ESPN = {"feed": [
    {"type": "Rotowire", "published": "2026-10-09T20:27:15Z",
     "headline": "Higgins (groin/neck) was a full practice participant Friday but is still "
                 "listed as questionable for Sunday's game at Miami.",
     "links": {"mobile": {"href": "http://m.espn.go.com/wireless/story?storyId=64157328"}}},
    {"type": "Story", "published": "2026-10-09T21:52:56Z",
     "headline": "Fantasy football buzz: Expect Bears' Swift to retain RB1 role",
     "links": {"web": {"href": "https://www.espn.com/fantasy/football/story/_/id/40699880/buzz"}}},
    {"type": "Rotowire", "published": "2026-09-21T15:34:29Z", "headline": "Higgins caught two passes."},
]}
PFT = """<?xml version="1.0"?><rss><channel>
<item><title>Tee Higgins expected to play Sunday</title>
<link>https://www.nbcsports.com/nfl/profootballtalk/rumor-mill/news/tee-higgins-expected</link>
<pubDate>Sun, 11 Oct 2026 10:47:29 -0400</pubDate></item>
<item><title>Darius Cooper 62-yard touchdown gives Eagles lead</title>
<link>https://www.nbcsports.com/nfl/profootballtalk/rumor-mill/news/darius-cooper</link>
<pubDate>Sun, 11 Oct 2026 10:47:29 -0400</pubDate></item>
</channel></rss>"""
ROTOBALLER = """<?xml version="1.0"?><rss><channel>
<item><title>Ja'Marr Chase Active for Week 5 Against Miami</title>
<link>https://www.rotoballer.com/player-news/jamarr-chase-active/196366</link>
<pubDate>Sun, 11 Oct 2026 14:21:09 +0000</pubDate></item></channel></rss>"""


def bsky_post(text, when, handle="laurelpfahler.bsky.social", repost=False, link=None):
    post = {"uri": f"at://did:plc:x/app.bsky.feed.post/{abs(hash(text)) % 10**8}",
            "author": {"handle": handle, "displayName": "Laurel Pfahler"},
            "record": {"text": text, "createdAt": when}}
    if link:
        post["embed"] = {"$type": "app.bsky.embed.external#view",
                         "external": {"uri": link[0], "title": link[1]}}
    item = {"post": post}
    if repost:
        item["reason"] = {"$type": "app.bsky.feed.defs#reasonRepost"}
    return item


BSKY = {"feed": [
    bsky_post("Higgins was a full participant again today.", "2026-10-10T18:00:00Z"),
    bsky_post("Brown and Brown both limited.", "2026-10-10T17:00:00Z"),
    bsky_post("Great read", "2026-10-10T16:00:00Z", repost=True),
    bsky_post("New story", "2026-10-10T15:00:00Z",
              link=("https://www.nytimes.com/athletic/123/bengals-chase", "Why Ja'Marr Chase is set for a big day")),
]}

PLAYERS = [
    {"id": "1", "name": "Tee Higgins", "team": "CIN", "pos": "WR"},
    {"id": "2", "name": "Ja'Marr Chase", "team": "CIN", "pos": "WR"},
    {"id": "3", "name": "Chase Brown", "team": "CIN", "pos": "RB"},
    {"id": "CIN", "name": "Cincinnati Bengals", "team": "CIN", "pos": "DEF"},
]
TEAMMATES = {"CIN": ["Tee Higgins", "Ja'Marr Chase", "Chase Brown", "Andrei Brown"]}


def fake_fetch(responses):
    def fetch(url):
        for key, value in responses.items():
            if key in url:
                if isinstance(value, Exception):
                    raise value
                return value
        raise FetchError(f"not faked: {url}")
    return fetch


def run(responses=None, cfg=CFG, players=PLAYERS):
    responses = responses or {"playerId=4239993": ESPN, "profootballtalk": PFT,
                              "rotoballer": ROTOBALLER, "laurelpfahler": BSKY}
    fetch = fake_fetch(responses)
    return news.collect(players, {"1": "4239993"}, TEAMMATES, cfg, NOW, fetch_json=fetch, fetch_text=fetch)


def test_espn_rotowire_lines_link_to_the_player_page():
    items = news.parse_espn(ESPN, "4239993", "Tee Higgins")
    assert items[0]["source"] == "RotoWire (ESPN)"
    assert items[0]["url"] == "https://www.espn.com/nfl/player/_/id/4239993"
    assert len(items) == 2  # the Swift story doesn't name him


def test_each_player_gets_his_newest_links_naming_him_first():
    found, detail, ok = run()
    higgins = found["1"]
    assert len(higgins) == 3
    # Newest first; the ESPN story that doesn't name him lost its spot to
    # three that do (PFT, the beat writer, RotoWire); the 3-week-old one is out
    assert [x["source"] for x in higgins] == ["Pro Football Talk", "Laurel Pfahler", "RotoWire (ESPN)"]
    assert higgins[1]["tag"] == "beat reporter" and higgins[0]["tag"] == "aggregator"
    assert higgins[0]["date"] == "2026-10-11T14:47:29Z"
    assert ok and "ESPN 1/1 players" in detail


def test_full_names_match_across_punctuation_and_case():
    found, _, _ = run()
    titles = [x["title"] for x in found["2"]]
    assert "Ja'Marr Chase Active for Week 5 Against Miami" in titles
    # The beat writer's linked story names him: its headline, the article's link, a lock
    story = next(x for x in found["2"] if x["tag"] == "beat reporter")
    assert story["url"].startswith("https://www.nytimes.com/athletic/") and story["paywall"]


def test_a_last_name_shared_on_the_team_needs_the_full_name():
    found, _, _ = run()
    # "Brown and Brown" could be Chase or Andrei Brown: no match
    assert all("Brown and Brown" not in x["title"] for x in found["3"])
    # A post saying "Chase" doesn't count for Chase Brown either (first names never do)
    assert found["3"] == []


def test_reposts_and_defenses_get_nothing():
    found, _, _ = run()
    assert all(x["title"] != "Great read" for links in found.values() for x in links)
    assert found["CIN"] == []


def test_a_feed_that_fails_is_reported_and_the_rest_still_work():
    found, detail, ok = run({"playerId=4239993": ESPN, "profootballtalk": FetchError("HTTP 503"),
                             "rotoballer": ROTOBALLER, "laurelpfahler": BSKY})
    assert not ok and "Pro Football Talk" in detail
    assert found["1"] and all(x["source"] != "Pro Football Talk" for x in found["1"])


def test_a_quiet_beat_writer_is_flagged():
    old = {"feed": [bsky_post("Higgins limited.", "2026-09-01T18:00:00Z")]}
    _, detail, ok = run({"playerId=4239993": ESPN, "profootballtalk": PFT,
                         "rotoballer": ROTOBALLER, "laurelpfahler": old})
    # Listed, but no warning on top of the app for it
    assert ok and "no posts in 14 days: @laurelpfahler.bsky.social" in detail


def test_names_last_is_a_capitalized_whole_word():
    assert news.names_last("Love throws a TD", "Love")
    assert not news.names_last("love this matchup", "Love")
    assert not news.names_last("Lovell was limited", "Love")


def test_a_last_name_after_someone_elses_first_name_is_someone_else():
    # Seen 2026-10-11: Lions beat posts about DT Tyleik Williams
    assert not news.names_last("Tyleik Williams back at Lions practice today.", "Williams", "Jameson")
    assert news.names_last("Need more from Jameson Williams", "Williams", "Jameson")
    assert news.names_last("Lions WR Williams (hamstring) is fine.", "Williams", "Jameson")
    assert news.names_last("Expect Lions' Williams to start", "Williams", "Jameson")
    assert news.names_last("Good news. Williams was full.", "Williams", "Jameson")


def test_espn_stories_must_name_him_but_rotowire_lines_are_his():
    found, _, _ = run({"playerId=4239993": ESPN})
    titles = [x["title"] for x in found["1"]]
    assert len(titles) == 1 and titles[0].startswith("Higgins")  # the Swift story isn't about him
    data = {"feed": [{"type": "Rotowire", "published": "2026-10-10T20:00:00Z",
                      "headline": "He was a full participant."}]}
    found, _, _ = run({"playerId=4239993": data})
    assert [x["title"] for x in found["1"]] == ["He was a full participant."]


def test_a_source_that_is_down_is_given_up_on_quickly():
    calls = []

    def down(url):
        calls.append(url)
        raise FetchError("HTTP 503")
    many = [{"id": str(i), "name": f"Player {i}", "team": "CIN", "pos": "WR"} for i in range(20)]
    cfg = dict(CFG, beat={"CIN": [f"w{i}.bsky.social" for i in range(10)]})
    _, detail, ok = news.collect(many, {str(i): str(i) for i in range(20)}, TEAMMATES, cfg, NOW,
                                 fetch_json=down, fetch_text=down)
    assert not ok
    assert sum("espn" in u for u in calls) == 3 and sum("bsky" in u for u in calls) == 3


# ---------- from the Phase 4 review ----------

def test_names_survive_punctuation_and_possessives():
    assert news.names_full("Josh Allen's ankle injury", "Josh Allen")
    assert news.names_full("Bijan Robinson, Falcons agree", "Bijan Robinson")
    assert news.names_full("Fantasy: Bijan Robinson?", "Bijan Robinson")
    assert news.names_last("Allen's ankle is fine", "Allen", "Josh")
    assert not news.names_full("Joshua Allenby signs", "Josh Allen")


def test_a_teammates_first_name_is_not_this_players_last_name():
    team = {"Ja'Marr Chase", "Chase Brown"}
    assert not news.names_last("Chase Brown runs for 120 yards", "Chase", "Ja'Marr", team)
    assert news.names_last("Chase caught 9 balls", "Chase", "Ja'Marr", team)


def test_several_rotowire_notes_on_one_player_page_all_count():
    data = {"feed": [{"type": "Rotowire", "published": f"2026-10-{d}T20:00:00Z",
                      "headline": f"Higgins practice note {d}."} for d in ("07", "08", "09", "10")]}
    found, _, _ = run({"playerId=4239993": data})
    assert [x["title"] for x in found["1"]] == ["Higgins practice note 10.", "Higgins practice note 09.",
                                                "Higgins practice note 08."]


def test_only_web_links_are_kept():
    bad = {"feed": [bsky_post("Higgins update", "2026-10-10T18:00:00Z",
                              link=("javascript:alert(1)", "Higgins is fine"))]}
    found, _, _ = run({"laurelpfahler": bad})
    assert all(x["url"].startswith("https://") for x in found["1"])
    rss = PFT.replace("https://www.nbcsports.com/nfl/profootballtalk/rumor-mill/news/tee-higgins-expected",
                      "data:text/html,hi")
    assert all(not x["url"].startswith("data:") for x in news.parse_rss(rss, "PFT"))


# League-wide accounts, shapes as saved 2026-10-12 (dev-snapshots
# news/bsky_feed_*): RotoWire puts the link in the text, Rotoworld in a card
def rotowire_post(text, url, when):
    return {"post": {"uri": f"at://did:plc:rw/app.bsky.feed.post/{abs(hash(text)) % 10**8}",
                     "author": {"handle": "rotowirenfl.bsky.social", "displayName": "RotoWire Fantasy Football"},
                     "record": {"text": f"{text}\n\n{url}", "createdAt": when,
                                "facets": [{"features": [{"$type": "app.bsky.richtext.facet#link", "uri": url}],
                                            "index": {"byteStart": len(text) + 2, "byteEnd": len(text) + 2 + len(url)}}]}}}


def rotoworld_post(text, when):
    return {"post": {"uri": f"at://did:plc:rd/app.bsky.feed.post/{abs(hash(text)) % 10**8}",
                     "author": {"handle": "rotoworld-fb.bsky.social", "displayName": "Rotoworld Football"},
                     "record": {"text": text, "createdAt": when},
                     "embed": {"$type": "app.bsky.embed.external#view",
                               "external": {"uri": f"http://dlvr.it/{abs(hash(text)) % 10**6}", "title": text}}}}


MOORE = "https://www.rotowire.com/football/player/dj-moore-12477"
ROTOWIRE_1 = {"cursor": "page2", "feed": [
    rotowire_post("DJ Moore: Inactive in Week 5", MOORE, "2026-10-11T07:49:41-07:00"),
    rotowire_post("DJ Moore: Questionable for Sunday", MOORE, "2026-10-09T13:00:00-07:00"),
]}
ROTOWIRE_2 = {"cursor": "page3", "feed": [
    # Seen 2026-10-12: the name before the colon is who it's about
    rotowire_post("Terry McLaurin: Likely to have restrictions Sunday",
                  "https://www.rotowire.com/football/player/terry-mclaurin-13025", "2026-10-08T14:00:00-07:00"),
    rotowire_post("DJ Moore: Limited again", MOORE, "2026-10-08T13:00:00-07:00"),
    rotowire_post("DJ Moore: Old news", MOORE, "2026-09-30T13:00:00-07:00"),   # past the week: stop here
]}
ROTOWORLD = {"feed": [
    rotoworld_post("Sirianni hints at Barkley (hammy) playing Week 6", "2026-10-11T12:49:00Z"),
    rotoworld_post("Smith (ankle) listed as limited on Monday", "2026-10-11T12:38:00Z"),
    rotoworld_post("Garafolo: DeVonta (hamstring) could return Week 6", "2026-10-11T12:30:00Z"),
    rotoworld_post("Kubiak: Barkley will handle a full load", "2026-10-11T12:20:00Z"),
]}
WIDE_PLAYERS = [{"id": "m", "name": "DJ Moore", "team": "CHI", "pos": "WR"},
                {"id": "b", "name": "Saquon Barkley", "team": "PHI", "pos": "RB"},
                {"id": "s", "name": "DeVonta Smith", "team": "PHI", "pos": "WR"},
                {"id": "l", "name": "Isaiah Likely", "team": "BAL", "pos": "TE"}]
WIDE_TEAMMATES = {"CHI": ["DJ Moore"], "PHI": ["Saquon Barkley", "DeVonta Smith"], "SEA": ["Geno Smith"],
                  "BAL": ["Isaiah Likely"], "WAS": ["Terry McLaurin"]}
WIDE_CFG = dict(CFG, beat={}, league_wide=["rotowirenfl.bsky.social", "rotoworld-fb.bsky.social"])


def run_wide(responses):
    fetch = fake_fetch(responses)
    return news.collect(WIDE_PLAYERS, {}, WIDE_TEAMMATES, WIDE_CFG, NOW, fetch_json=fetch, fetch_text=fetch)


def test_rotowire_posts_link_to_his_rotowire_page_without_the_url_in_the_title():
    it = news.parse_bsky(ROTOWIRE_1, "rotowirenfl.bsky.social", news.AGGREGATOR)[0]
    assert it["title"] == "DJ Moore: Inactive in Week 5"
    assert it["url"] == MOORE and it["page"] and it["tag"] == "aggregator"
    assert it["source"] == "RotoWire Fantasy Football"


def test_league_wide_accounts_match_full_names_and_unshared_last_names():
    found, detail, ok = run_wide({"cursor=page2": ROTOWIRE_2, "rotowirenfl": ROTOWIRE_1, "rotoworld-fb": ROTOWORLD,
                                  "profootballtalk": PFT, "rotoballer": ROTOBALLER})
    # A week of RotoWire across two pages; all link to his page, told apart by text
    assert [x["title"] for x in found["m"]] == ["DJ Moore: Inactive in Week 5", "DJ Moore: Questionable for Sunday",
                                                "DJ Moore: Limited again"]
    # "Barkley" is his alone; "Smith" isn't (Geno Smith), and a first name alone never counts
    # A one-word source before a colon ("Kubiak:") isn't who it's about
    assert [x["title"] for x in found["b"]] == ["Sirianni hints at Barkley (hammy) playing Week 6",
                                                "Kubiak: Barkley will handle a full load"]
    assert found["s"] == []
    assert {x["source"] for x in found["m"] + found["b"]} == {"RotoWire", "Rotoworld"}
    # RotoWire's name before the colon is who it's about: not Isaiah Likely
    assert found["l"] == []
    assert ok and "@rotowirenfl.bsky.social 4 posts" in detail and "@rotoworld-fb.bsky.social 4 posts" in detail


def test_a_league_wide_account_that_fails_is_a_problem_and_the_rest_still_work():
    found, detail, ok = run_wide({"rotowirenfl": FetchError("down"), "rotoworld-fb": ROTOWORLD,
                                  "profootballtalk": PFT, "rotoballer": ROTOBALLER})
    assert not ok and "@rotowirenfl.bsky.social didn't load" in detail
    assert len(found["b"]) == 2
