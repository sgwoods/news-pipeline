import datetime as dt
import logging
import tempfile
import unittest
from pathlib import Path

from pipeline import bluesky, editorial, mailsource, stages

LOG = logging.getLogger("t")
NOW = dt.datetime(2026, 10, 10, 12, 0, tzinfo=dt.timezone.utc)


class FakeResp:
    def __init__(self, d):
        self.d = d

    def raise_for_status(self):
        pass

    def json(self):
        return self.d


class FakeClient:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, url, params=None):
        self.calls.append((url.rsplit("/", 1)[-1], params))
        return FakeResp(self.routes[url.rsplit("/", 1)[-1]](params or {}))

    def close(self):
        pass


def post(handle, rkey, text, created, reply=False, reason=None, link=None):
    p = {"post": {"uri": f"at://did/app.bsky.feed.post/{rkey}", "author": {"handle": handle, "displayName": handle.split(".")[0].title()},
                  "record": {"text": text, "createdAt": created, **({"reply": {}} if reply else {})}}}
    if link:
        p["post"]["embed"] = {"external": {"uri": link, "title": "Article", "description": "desc"}}
    if reason:
        p["reason"] = reason
    return p


class TestBluesky(unittest.TestCase):
    def test_list_and_own(self):
        routes = {
            "com.atproto.identity.resolveHandle": lambda p: {"did": "did:plc:abc"},
            "app.bsky.graph.getList": lambda p: {"list": {"name": "Realistic AI", "description": "no hype"},
                                                 "items": [{"subject": {"handle": "gary.bsky.social", "displayName": "Gary", "did": "d1"}}]},
            "app.bsky.feed.getListFeed": lambda p: {"feed": [
                post("gary.bsky.social", "a1", "Benchmarks are theater", "2026-10-10T08:00:00Z", link="https://x.example/a"),
                post("gary.bsky.social", "a2", "old", "2026-10-01T08:00:00Z"),
                post("gary.bsky.social", "a3", "reply", "2026-10-10T09:00:00Z", reply=True),
                post("zoe.bsky.social", "a4", "reposted", "2026-10-10T09:00:00Z", reason={"$type": "repost"})]},
            "app.bsky.feed.getAuthorFeed": lambda p: {"feed": [post("stevenwoods.com", "o1", "Interesting", "2026-10-10T07:00:00Z")]},
        }
        cfg = {"bluesky": {"lists": ["https://bsky.app/profile/stevenwoods.com/lists/3latd6bmync2b"], "own": "stevenwoods.com", "lookback_hours": 36}}
        import unittest.mock as mock
        class FixedDT(dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return NOW
        with mock.patch.object(bluesky.dt, "datetime", FixedDT):
            res = bluesky.fetch(cfg, "r1", LOG, client=FakeClient(routes))
        names = [(i["person"], i["tier"]) for i in res["items"]]
        self.assertEqual(names, [("Gary", "list"), ("Steven Woods (own posts)", "own")])
        it = res["items"][0]
        self.assertEqual(it["url"], "https://bsky.app/profile/gary.bsky.social/post/a1")
        self.assertIn("Linked: Article desc", it["text"])
        self.assertIn("Realistic AI", it["source_note"])
        self.assertEqual(res["sources"][0]["members"], 1)
        self.assertEqual(bluesky.list_uri(FakeClient(routes), cfg["bluesky"]["lists"][0]), "at://did:plc:abc/app.bsky.graph.list/3latd6bmync2b")


RAW = b"""From: The Rundown AI <news@therundown.ai>
To: you+briefing@example.com
Subject: =?utf-8?q?OpenAI_just_changed_everything?=
Date: Fri, 10 Oct 2026 10:00:00 +0000
Message-ID: <abc123@mail.beehiiv.com>
Content-Type: text/html; charset=utf-8

<html><body><a href="https://link.example/view?id=9">View in browser</a><h1>Huge</h1><p>OpenAI released GPT-7 </item> today.</p></body></html>
"""
RAW2 = b"""From: Someone <who@unknown.example>
Subject: hello
Date: Fri, 10 Oct 2026 10:00:00 +0000
Message-ID: <zzz@unknown.example>
Content-Type: text/plain

plain body
"""


class TestNewsletters(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "newsletters.yaml").write_text(
            "- name: The Rundown AI\n  from: [therundown.ai]\n  web: https://www.therundown.ai/\n  tier: coverage-check\n"
            "  scrutiny: true\n  bias: AGI-pilled, sponsored.\n- name: TLDR AI\n  from: [tldr.tech]\n  web: https://tldr.tech/ai\n  tier: wire\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_parse_and_match(self):
        nl = mailsource.load_newsletters(self.root)
        self.assertEqual(mailsource.match_sender("News@TheRundown.ai", nl)["name"], "The Rundown AI")
        self.assertEqual(mailsource.match_sender("x@mail.tldr.tech", nl)["name"], "TLDR AI")
        self.assertIsNone(mailsource.match_sender("a@b.example", nl))
        it = mailsource.parse_message(RAW, nl, mailsource.mcfg({}), "r1", NOW)
        self.assertEqual(it["person"], "The Rundown AI")
        self.assertEqual(it["url"], "https://link.example/view?id=9")      # view-in-browser link wins
        self.assertEqual(it["public_url"], it["url"])
        self.assertEqual(it["title"], "OpenAI just changed everything")
        self.assertEqual(it["tier"], "coverage-check")
        self.assertTrue(it["scrutiny"])
        self.assertIn("GPT-7", it["text"])
        self.assertEqual(it["source_note"], "AGI-pilled, sponsored.")
        self.assertIn("about this source (Steven's note", stages.item_block({**it, "text": it["text"]}, 500))
        self.assertNotIn("</item> today", stages.item_block(it, 500))
        it2 = mailsource.parse_message(RAW2, nl, mailsource.mcfg({}), "r1", NOW)
        self.assertTrue(it2["unlisted"])
        self.assertTrue(it2["url"].startswith("email:"))
        self.assertEqual(it2["public_url"], "")

    def test_public_url_fragment_keeps_issues_distinct(self):
        nl = mailsource.load_newsletters(self.root)
        raw = RAW.replace(b'<a href="https://link.example/view?id=9">View in browser</a>', b"")
        a = mailsource.parse_message(raw, nl, mailsource.mcfg({}), "r1", NOW)
        b = mailsource.parse_message(raw.replace(b"abc123", b"def456"), nl, mailsource.mcfg({}), "r1", NOW)
        self.assertTrue(a["public_url"].startswith("https://www.therundown.ai/#issue-"))
        self.assertNotEqual(a["public_url"], b["public_url"])
        rec = stages.build_records([a], {a["id"]: {"keep": True}}, {a["id"]: {"claim": "c"}}, {},
                                   {"run_id": "r", "day": "2026-10-10", "models": {}, "prompt_versions": {}})[0]
        self.assertEqual(rec["url"], a["public_url"])


class TestWireRule(unittest.TestCase):
    def test_wire_only_story_cannot_lead(self):
        def rec(i, tier, imp=5):
            return {"id": f"i{i}", "url": f"https://x/{i}", "person": f"P{i}", "tier": tier, "importance": imp, "claim": "c", "headline": "h"}
        recs = [rec(1, "wire"), rec(2, "coverage-check"), rec(3, "follow closely"), rec(4, "own")]
        by_id = {r["id"]: r for r in recs}
        stories = editorial.build_stories([{"ids": ["i1", "i2"], "headline": "wire pair"}, {"ids": ["i3"], "headline": None},
                                           {"ids": ["i4"], "headline": None}], by_id)
        sel = editorial.select(stories, {})
        self.assertEqual([s["lead"]["id"] for s in sel["must"]], ["i3"])
        self.assertEqual({s["lead"]["id"] for s in sel["worth"]}, {"i1", "i4"})


if __name__ == "__main__":
    unittest.main()


RSS = b"""<?xml version="1.0"?><rss><channel><title>@karpathy</title>
<item><title>Tokens are</title><link>https://xcancel.com/karpathy/status/123</link><pubDate>Sat, 10 Oct 2026 09:00:00 GMT</pubDate><description>Tokens are &lt;b&gt;all&lt;/b&gt;</description></item>
<item><title>RT by @karpathy: hi</title><link>https://xcancel.com/other/status/5</link><pubDate>Sat, 10 Oct 2026 08:00:00 GMT</pubDate><description>x</description></item>
<item><title>old</title><link>https://xcancel.com/karpathy/status/1</link><pubDate>Mon, 1 Sep 2026 08:00:00 GMT</pubDate><description>old</description></item>
</channel></rss>"""


class XResp:
    def __init__(self, code, content=b""):
        self.status_code, self.content = code, content


class TestX(unittest.TestCase):
    def test_mirror_rotation_and_items(self):
        from pipeline import xsource
        root = Path(tempfile.mkdtemp())
        (root / "data").mkdir()
        (root / "data" / "index.jsonl").write_text("")
        (root / "x.yaml").write_text("instances: [https://dead.example, https://live.example]\naccounts:\n"
                                     "  - {handle: karpathy, name: Andrej Karpathy, tier: follow closely, why: clarity}\n")
        class C:
            def get(self, url):
                return XResp(200, RSS) if url.startswith("https://live.example") else XResp(503)
            def close(self):
                pass
        class FixedDT(dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return NOW
        import sys
        import types
        import unittest.mock as mock
        import xml.etree.ElementTree as ET
        fake = types.ModuleType("feedparser")           # the real one may be missing in the test environment
        def parse(content):
            root_el = ET.fromstring(content)
            found = [{"title": i.findtext("title"), "link": i.findtext("link"), "published": i.findtext("pubDate"),
                      "summary": i.findtext("description")} for i in root_el.iter("item")]
            class P(dict):
                entries = found           # a class body cannot see a same-named enclosing variable
            return P(version="rss20")
        fake.parse = parse
        with mock.patch.dict(sys.modules, {"feedparser": sys.modules.get("feedparser", fake)}), \
                mock.patch.object(xsource.dt, "datetime", FixedDT):
            res = xsource.fetch(root, {"fetch": {"lookback_hours": 36}}, "r1", LOG, client=C())
        self.assertEqual(res["instance"], "https://live.example")
        self.assertEqual([i["url"] for i in res["items"]], ["https://x.com/karpathy/status/123"])   # canonical, no RT, no old
        self.assertEqual(res["items"][0]["text"], "Tokens are all")
        self.assertEqual(res["items"][0]["source_note"], "clarity")
        st = xsource.status(root)
        self.assertEqual(st["last_good"], "https://live.example")
        self.assertFalse(st["instances"][0]["ok"])


class TestTodos(unittest.TestCase):
    def test_seed_done_markdown(self):
        from pipeline import todos
        root = Path(tempfile.mkdtemp())
        self.assertEqual(todos.seed(root, todos.STARTER), len(todos.STARTER))
        self.assertEqual(todos.seed(root, todos.STARTER), 0)
        t = todos.load(root)[0]["id"]
        todos.set_status(root, t, "done", "did it")
        md = todos.markdown(root)
        self.assertIn(f"- [x] `{t}`", md)
        self.assertIn("## newsletters", md)
