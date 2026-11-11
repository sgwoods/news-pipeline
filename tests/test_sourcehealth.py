"""Source health (pipeline/sourcehealth.py): status, category and priority for every known source."""
import datetime as dt
import unittest

from pipeline import sourcehealth as sh

TODAY = dt.date(2026, 11, 5)


class Table(unittest.TestCase):
    def build(self):
        rows = [{"person": "Feed A", "kind": "rss", "url": "https://a.example/feed", "tier": "follow closely",
                 "last": {"status": "error", "error": "HTTP 403"}, "archived": 12, "newest": "2026-10-01"},
                {"person": "Feed B", "kind": "rss", "url": "https://b.example/feed", "tier": "follow",
                 "last": {"status": "ok"}, "archived": 40, "newest": "2026-11-04"},
                {"person": "Page C", "kind": "page", "url": "https://c.example/blog", "tier": "follow",
                 "last": {"status": "ok"}, "archived": 3, "newest": "2026-09-01"}]
        last = {("X", "x"): {"person": "X", "url": "x", "kind": "x", "status": "error", "error": "no mirror answered"},
                ("Feed A", "https://a.example/feed"): rows[0]["last"]}
        news = [{"name": "Letter", "from": ["l@example.org"], "count": 0, "latest": "", "tier": "follow"}]
        xs = {"accounts": [{"name": "Someone", "handle": "someone", "count": 5, "latest": "2026-10-20"}],
              "last_good": "2026-10-20", "last_fail": "2026-11-05"}
        bl = {"lists": ["https://bsky.app/profile/did:plc:abc/lists/xyz"]}
        dropped = ["https://www.science.org/a", "https://science.org/b", "https://once.example/c"]
        return sh.table(rows, last, news, xs, bl, [], dropped, today=TODAY)

    def test_statuses_and_categories(self):
        t = {r["name"]: r for r in self.build()}
        self.assertEqual((t["Feed A"]["status"], t["Feed A"]["why"], t["Feed A"]["category"]), ("failing", "HTTP 403 blocked", "RSS feed"))
        self.assertEqual(t["Feed B"]["status"], "ingesting")
        self.assertEqual(t["Page C"]["status"], "quiet")
        self.assertEqual((t["Letter"]["status"], t["Letter"]["category"]), ("known, not ingested", "Email newsletter"))
        self.assertEqual((t["Someone"]["status"], t["Someone"]["why"]), ("failing", "no X mirror answered"))
        self.assertEqual(t["Bluesky list"]["status"], "known, not ingested")
        self.assertEqual((t["science.org"]["why"], t["science.org"]["category"]), ("bot wall / paywall", "Deep-dive citation"))
        self.assertNotIn("once.example", t)                        # one drop is noise

    def test_priority_order(self):
        t = self.build()
        self.assertEqual(t[0]["name"], "Feed A")                   # failing + follow closely first
        self.assertEqual([r["status"] for r in t if r["priority"]][-1], "quiet")
        self.assertEqual([r["priority"] for r in t if r["status"] == "ingesting"], [""])
        s = sh.summary(t)
        self.assertEqual(s["status"]["failing"], 3)

    def test_backup_newsletter_and_cadence(self):
        rows = [{"person": "Marcus web", "kind": "rss", "url": "https://garymarcus.substack.com/feed", "tier": "follow closely",
                 "last": {"status": "ok"}, "archived": 30, "newest": "2026-11-04"}]
        news = [{"name": "Marcus email", "from": ["garymarcus@substack.com"], "web": "https://garymarcus.substack.com/",
                 "count": 0, "latest": "", "tier": "follow closely", "backup": True},
                {"name": "Orphan backup", "from": ["o@example.org"], "web": "", "count": 0, "latest": "", "backup": True},
                {"name": "Monthly", "from": ["m@example.org"], "count": 4, "latest": "2026-10-10", "every_days": 31},
                {"name": "Weekly", "from": ["w@example.org"], "count": 9, "latest": "2026-10-10", "every_days": 7},
                {"name": "Plain", "from": ["p@example.org"], "count": 9, "latest": "2026-10-20"}]
        t = {r["name"]: r for r in sh.table(rows, {}, news, {}, {}, [], [], today=TODAY)}
        self.assertEqual((t["Marcus email"]["status"], t["Marcus email"]["why"]), ("ingesting", "via web feed; the email is a backup"))
        self.assertIn("2026-11-04", t["Marcus email"]["note"])
        self.assertEqual(t["Orphan backup"]["status"], "known, not ingested")       # backup with no web feed is still a gap
        self.assertIn("no web feed", t["Orphan backup"]["note"])
        self.assertEqual(t["Monthly"]["status"], "ingesting")                      # 26 days late is within 1.5 x 31
        self.assertEqual(t["Weekly"]["status"], "quiet")
        self.assertIn("expected every 7", t["Weekly"]["why"])
        self.assertEqual(t["Plain"]["status"], "quiet")                            # 16 days > NEWSLETTER_QUIET_DAYS

    def test_reasons(self):
        self.assertEqual(sh.reason("ReadTimeout: The read operation timed out"), "timeout")
        self.assertEqual(sh.reason("HTTP 404"), "HTTP 404 moved or gone")
        self.assertEqual(sh.reason("HTTP 429: Please limit requests"), "rate limited")
        self.assertEqual(sh.reason("unparseable feed: <x>"), "unreadable feed")


if __name__ == "__main__":
    unittest.main()
