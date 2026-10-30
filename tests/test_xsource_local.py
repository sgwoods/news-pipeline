"""2026-10-30: X via the local xsukax-X-RSS-Generator ("http://127.0.0.1:8787/?x={handle}&l=20") and the members of
Steven's X lists as accounts."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import xsource

RSS = ("<?xml version='1.0'?><rss version='2.0'><channel><title>t</title><item><title>Hello</title>"
       "<link>https://x.com/{h}/status/123</link><description>A post by {h} about models.</description>"
       "<pubDate>{d}</pubDate></item></channel></rss>")


class Resp:
    def __init__(self, body):
        self.status_code, self.content = 200, body.encode()


class Local(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "x.yaml").write_text(
            "instances:\n  - http://127.0.0.1:8787/?x={handle}&l=20\n  - https://nitter.net\n"
            "lists: [AI Realists]\ndelay_seconds: 0\n"
            "accounts:\n  - {handle: karpathy, name: Andrej Karpathy, tier: follow closely, why: internals}\n", "utf-8")
        (self.root / "data" / "state").mkdir(parents=True)
        (self.root / xsource.LISTS).write_text(json.dumps({"lists": [
            {"name": "AI Realists", "members": [{"handle": "karpathy"}, {"handle": "GaryMarcus", "name": "Gary Marcus",
                                                 "bio": "sceptic"}, {"handle": "bad handle!"}]},
            {"name": "Venture", "members": [{"handle": "vkhosla"}]}]}), "utf-8")

    def test_template_instances_and_list_members(self):
        x = xsource.load_x(self.root)
        self.assertEqual([a["handle"] for a in x["accounts"]], ["karpathy", "GaryMarcus"])   # deduped, only named lists
        self.assertEqual(x["accounts"][1]["tier"], "list")
        self.assertIn("AI Realists", x["accounts"][1]["why"])
        self.assertEqual(xsource.feed_url(x["instances"][0], "simonw"), "http://127.0.0.1:8787/?x=simonw&l=20")
        self.assertEqual(xsource.feed_url("https://nitter.net", "simonw"), "https://nitter.net/simonw/rss")

    def test_fetch_reads_every_account_through_the_local_feed(self):
        import email.utils
        import datetime as dt
        d = email.utils.format_datetime(dt.datetime.now(dt.timezone.utc))
        asked = []

        class C:
            def get(self, url):
                asked.append(url)
                h = url.split("x=")[1].split("&")[0]
                return Resp(RSS.format(h=h, d=d))
        log = mock.Mock()
        r = xsource.fetch(self.root, {}, "run", log, client=C())
        self.assertEqual(r["instance"], "http://127.0.0.1:8787/?x={handle}&l=20")
        self.assertEqual({i["url"] for i in r["items"]}, {"https://x.com/karpathy/status/123",
                                                         "https://x.com/GaryMarcus/status/123"})
        self.assertTrue(all(u.startswith("http://127.0.0.1:8787/?x=") for u in asked))


if __name__ == "__main__":
    unittest.main()
