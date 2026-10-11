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
