"""2026-10-31: a paid feed's per-reader token reached the public page, and an X repost was credited to the
account that reposted it. Tokens are stripped from links and blocked at publish; reposts are skipped."""
import email.utils
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import publish, textutil as T, xsource

JWT = "eyJhbGciOiJFUzI1NiJ9.eyJhdWQiOiJzdHJhdGVjaGVyeSJ9.c2ln"


class Credentials(unittest.TestCase):
    def test_clean_url_drops_tokens_keeps_ordinary_params(self):
        self.assertEqual(T.clean_url(f"https://stratechery.com/2026/at-long-last/?access_token={JWT}"),
                         "https://stratechery.com/2026/at-long-last/")
        self.assertEqual(T.clean_url("https://e.com/a?id=3&api_key=zz&author=sam&key=k"), "https://e.com/a?id=3&author=sam")

    def test_publish_scan_blocks_a_token_in_the_page(self):
        site = Path(tempfile.mkdtemp())
        (site / "index.html").write_text(f'<a href="https://s.com/p/?access_token={JWT}">x</a>', "utf-8")
        (site / "ok.html").write_text('<a href="https://s.com/p/?id=3">x</a> tokens of thanks', "utf-8")
        with mock.patch("pipeline.stages.private_names", return_value=[]):
            bad = publish.scan_site(site, site)
        self.assertEqual(len(bad), 1)
        self.assertIn("index.html: a credential", bad[0])


class Reposts(unittest.TestCase):
    def test_a_repost_is_not_the_accounts_own_post(self):
        root = Path(tempfile.mkdtemp())
        (root / "x.yaml").write_text("instances:\n  - http://127.0.0.1:8787/?x={handle}&l=20\ndelay_seconds: 0\n"
                                     "accounts:\n  - {handle: GaryMarcus, name: Gary Marcus, tier: follow closely, why: w}\n",
                                     "utf-8")
        (root / "data" / "state").mkdir(parents=True)
        d = email.utils.format_datetime(dt.datetime.now(dt.timezone.utc))
        item = "<item><title>t</title><link>https://x.com/{h}/status/{n}</link><description>p</description><pubDate>{d}</pubDate></item>"
        body = ("<?xml version='1.0'?><rss version='2.0'><channel><title>t</title>"
                + item.format(h="GaryMarcus", n=1, d=d) + item.format(h="someoneelse", n=2, d=d) + "</channel></rss>")

        class R:
            status_code, content = 200, body.encode()

        class C:
            def get(self, url):
                return R()
        r = xsource.fetch(root, {}, "run", mock.Mock(), client=C())
        self.assertEqual([i["url"] for i in r["items"]], ["https://x.com/GaryMarcus/status/1"])


if __name__ == "__main__":
    unittest.main()
