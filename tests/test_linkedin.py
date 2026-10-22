import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from pipeline import linkedin as li

SHARES = ('Date,ShareLink,ShareCommentary,SharedUrl,MediaUrl,Visibility\n'
          '2026-09-01 10:00:00,https://www.linkedin.com/feed/update/urn:li:share:1,"Agents need audits, not ""vibes"". ' + 'x' * 250 + '",https://example.com/a,,PUBLIC\n'
          '2026-09-02 10:00:00,https://www.linkedin.com/feed/update/urn:li:share:2,"Connections only post ' + 'y' * 250 + '",,,MEMBER_NETWORK\n')
CFG = {}


class LinkedInTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_shares_csv(self):
        posts = li.parse_shares(SHARES)
        self.assertEqual(len(posts), 2)
        self.assertIn('not "vibes"', posts[0]["text"])
        self.assertEqual(posts[0]["shared_url"], "https://example.com/a")
        self.assertEqual(posts[0]["date"], "2026-09-01")

    def test_zip_reads_only_shares_and_articles(self):
        inbox = self.root / li.INBOX
        inbox.mkdir(parents=True)
        z = inbox / "Basic_LinkedInDataExport.zip"
        with zipfile.ZipFile(z, "w") as f:
            f.writestr("Shares.csv", SHARES)
            f.writestr("messages.csv", "FROM,TO,CONTENT\nsomeone,me,private\n")
            f.writestr("Articles/Articles/My take.html",
                       "<html><title>My take</title><body>Created 2026-08-01 "
                       "https://www.linkedin.com/pulse/my-take-steven/ Long text here</body></html>")
        r = li.import_export(self.root)
        self.assertEqual((r["posts"], r["articles"], r["added"], r["public"]), (2, 1, 3, 2))
        self.assertNotIn("private", (self.root / li.STORE).read_text())
        self.assertEqual(li.import_export(self.root)["added"], 0)          # idempotent

    def test_own_words_sources_public_only(self):
        li.add_posts(self.root, li.parse_shares(SHARES))
        srcs = li.own_words_sources(self.root, CFG)
        self.assertEqual(len(srcs), 1)
        self.assertTrue(srcs[0]["text"].startswith("Agents need audits"))

    def test_own_post_from_slack(self):
        it = {"url": "https://lnkd.in/p/abc", "title": "I'm starting a series called CTO Musings… | Steven G. Woods",
              "text": "I'm starting a series called CTO Musings… | Steven G. Woods I'm starting a series.",
              "published": "2026-10-13T22:05:49+00:00"}
        self.assertTrue(li.is_own_post(it, CFG))
        self.assertFalse(li.is_own_post({**it, "title": "Big news | Andrew Ng", "text": ""}, CFG))
        self.assertFalse(li.is_own_post({**it, "url": "https://example.com/x"}, CFG))
        rec = li.from_item(it)
        self.assertEqual(rec["text"], "I'm starting a series.")
        self.assertTrue(li._public(rec["visibility"]))


if __name__ == "__main__":
    unittest.main()
