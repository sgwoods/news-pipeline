"""Campaigns (2026-11-04): invites, sign-ups, conversions, abandonments and replies, worked out from the data."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path

from pipeline import campaigns as cm

ROOT = Path(__file__).resolve().parents[1]
BODY = "Hi {first},\n\nTry it: {signup}\n\nSteven"


class Campaigns(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        cm.create(self.root, "friends-trial", "Friends trial", "Try my AI briefing?", BODY, "https://x.example/#email")
        for e, n in (("a@x.com", "Ann Lee"), ("b@x.com", "Bo"), ("c@x.com", ""), ("d@x.com", "Di"), ("e@x.com", "Ed")):
            cm.add_person(self.root, "friends-trial", e, n)

    def test_add_validation(self):
        with self.assertRaises(ValueError):
            cm.add_person(self.root, "friends-trial", "A@X.com")              # already there (case-insensitive)
        with self.assertRaises(ValueError):
            cm.add_person(self.root, "friends-trial", "not an address")
        with self.assertRaises(ValueError):
            cm.create(self.root, "../etc", "x", "s", "b", "u")

    def test_invite_text(self):
        c = cm.load(self.root, "friends-trial")
        t = cm.invite_text(c, c["people"][0])
        self.assertIn("Hi Ann,", t["body"])
        self.assertIn("https://x.example/#email", t["body"])
        self.assertIn("Hi there,", cm.invite_text(c, c["people"][2])["body"])

    def test_report_statuses_and_funnel(self):
        today = dt.date(2026, 11, 20)
        for e in ("a@x.com", "b@x.com", "c@x.com", "d@x.com"):
            cm.mark(self.root, "friends-trial", e, "invited", "2026-11-04")
        cm.mark(self.root, "friends-trial", "e@x.com", "declined", True)
        subs = [{"email": "A@x.com", "status": "active", "created": "2026-11-05T10:00", "confirmed": "2026-11-05T10:05"},
                {"email": "b@x.com", "status": "pending", "created": "2026-11-06"},
                {"email": "c@x.com", "status": "unsubscribed"},
                {"email": "z@x.com", "status": "active"}]
        fb = [{"sender": "a@x.com", "received": "2026-11-07T08:00"}, {"sender": "q@x.com"}]
        r = cm.report(self.root, "friends-trial", subs, fb, today)
        st = {x["email"]: x["status"] for x in r["rows"]}
        self.assertEqual(st, {"a@x.com": "subscribed", "b@x.com": "signed up", "c@x.com": "abandoned",
                              "d@x.com": "abandoned", "e@x.com": "declined"})       # d: no sign-up 16 days on
        self.assertEqual(r["funnel"]["subscribed"], 1)
        self.assertEqual(r["funnel"]["replied"], 1)
        self.assertEqual(r["funnel"]["conversion_pct"], 25)
        self.assertEqual(next(x for x in r["rows"] if x["email"] == "a@x.com")["subscribed_at"], "2026-11-05")


@unittest.skipUnless((ROOT / "config.yaml").exists(), "needs a checkout with config.yaml")
class Pages(unittest.TestCase):
    def test_pages_render(self):
        from dashboard.app import create_app
        c = create_app(ROOT).test_client()
        self.assertEqual(c.get("/campaigns", headers={"Host": "127.0.0.1:8775"}).status_code, 200)
        self.assertEqual(c.get("/campaigns/nope", headers={"Host": "127.0.0.1:8775"}).status_code, 404)


if __name__ == "__main__":
    unittest.main()
