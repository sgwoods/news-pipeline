"""One-click star ratings (email + site) and the share / subscribe blocks on the public pages."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import mailer, quality, site

MD = """# AI Briefing · Friday, October 16, 2026

**The day in brief.** Three threads today.

## Top of mind

- **A lead.** Something happened.

## Must read

### 1. A story
**Reuters** · report · [source](https://www.reuters.com/a)

- **What happened:** x
"""
SCRIPT = "https://script.google.com/macros/s/abc/exec"
ON = {"email": {"script_url": SCRIPT, "ratings": True}, "publish": {"site_url": "https://s.example/ai-briefing/"}}
OFF = {"email": {"script_url": SCRIPT}, "publish": {"site_url": "https://s.example/ai-briefing/"}}


class EmailStars(unittest.TestCase):
    def test_stars_only_when_enabled(self):
        on = mailer.render("2026-10-16", MD, ON)
        for n in range(1, 6):
            self.assertIn(f"{{{{RATE}}}}&amp;s={n}", on["html"])
        self.assertIn("How is today's briefing?", on["html"])
        self.assertIn("{{RATE}}", on["text"])
        self.assertIn("Subscribe a friend", on["html"])
        self.assertIn("Was this forwarded to you?", on["html"])
        off = mailer.render("2026-10-16", MD, OFF)
        self.assertNotIn("{{RATE}}", off["html"] + off["text"])       # old scripts would leave it unfilled
        self.assertIn("Reply with a number from 1 to 5", off["html"])

    def test_send_passes_the_day(self):
        root = Path(tempfile.mkdtemp())
        (root / "briefings").mkdir()
        (root / "briefings" / "2026-10-16.md").write_text(MD)
        seen = {}
        with mock.patch.object(mailer, "call", lambda cfg, a, **p: seen.update(p) or {"ok": True, "sent": 1}):
            mailer.send_day(root, ON, "2026-10-16", to="me@x.com")
        self.assertEqual(seen["day"], "2026-10-16")

    def test_ratings_export_is_not_gated(self):
        with mock.patch.object(mailer, "ready", lambda c: ""), mock.patch.object(mailer, "key", lambda: "k"), \
                mock.patch("pipeline.release.require", side_effect=AssertionError("gate")), \
                mock.patch("httpx.post") as post:
            post.return_value.json.return_value = {"ok": True, "ratings": []}
            self.assertEqual(mailer.ratings(ON), [])


class PlaceholderInjection(unittest.TestCase):
    def test_content_cannot_carry_placeholders(self):
        evil = MD.replace("[source](https://www.reuters.com/a)",
                          "[source](https://evil.example/{{UNSUBSCRIBE}}?x={{OWNER}})") + "\n- **Note.** {{RATE}} %7B%7BRATE}}\n"
        m = mailer.render("2026-10-16", evil, ON)
        body = m["html"] + m["text"]
        self.assertNotIn("evil.example/{{UNSUBSCRIBE}}", body)
        self.assertNotIn("{{OWNER}}", body)
        self.assertEqual(body.count("{{UNSUBSCRIBE}}"), 2)              # only the template's own (html + text)
        self.assertNotIn("%7B%7BRATE", body)


class PrivacyGate(unittest.TestCase):
    def test_blocks_names_owner_mentions_trackers_and_stray_placeholders(self):
        with mock.patch("pipeline.stages.private_names", lambda: ["Jane Example"]):
            ok = mailer.render("2026-10-16", MD, ON)
            self.assertEqual(mailer.privacy_gate(ok, ON), [])
            for bad_md, want in [(MD.replace("Three threads today.", "Jane Example says three threads."), "private name"),
                                 (MD + "\n- Board seat: Steven Woods sits on X's board.\n", None),
                                 (MD.replace("https://www.reuters.com/a", "https://info.deeplearning.ai/e3t/Ctc/x"), None)]:
                m = mailer.render("2026-10-16", bad_md, ON)
                m["html"] += "<p>Board seat</p>" if want is None and "e3t" not in bad_md else ""
                if "e3t" in bad_md:
                    m["html"] += '<a href="https://info.deeplearning.ai/e3t/Ctc/x">x</a>'
                self.assertTrue(mailer.privacy_gate(m, ON), bad_md[-60:])
            m = dict(ok, html=ok["html"] + "{{OWNER}}")
            self.assertIn("unexpected placeholder: {{OWNER}}", mailer.privacy_gate(m, ON))

    def test_send_refuses_when_the_gate_fails(self):
        root = Path(tempfile.mkdtemp())
        (root / "briefings").mkdir()
        (root / "briefings" / "2026-10-16.md").write_text(MD.replace("Three threads today.", "Jane Example says so."))
        with mock.patch("pipeline.stages.private_names", lambda: ["Jane Example"]), \
                mock.patch.object(mailer, "call", side_effect=AssertionError("must not send")):
            with self.assertRaises(mailer.MailError):
                mailer.send_day(root, ON, "2026-10-16")


class CatchUp(unittest.TestCase):
    def test_only_people_confirmed_after_the_send(self):
        root = Path(tempfile.mkdtemp())
        (root / "briefings").mkdir()
        (root / "data").mkdir()
        (root / "briefings" / "2026-10-16.md").write_text(MD)
        (root / mailer.LOG).write_text(json.dumps({"day": "2026-10-16", "at": "2026-10-16T12:41:08", "ok": True,
                                                    "sent": 2, "test": False}) + "\n")
        local = dt.datetime(2026, 10, 16, 12, 41, 8).astimezone()
        utc = lambda minutes: (local + dt.timedelta(minutes=minutes)).astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")
        subs = {"subscribers": [
            {"email": "old@x.com", "status": "active", "confirmed": utc(-600)},
            {"email": "new@x.com", "status": "active", "confirmed": utc(40)},
            {"email": "pend@x.com", "status": "pending", "confirmed": ""},
            {"email": "gone@x.com", "status": "unsubscribed", "confirmed": utc(50)}]}
        sent_to = []

        def fake(cfg, action, **p):
            if action == "list":
                return {"ok": True, **subs}
            sent_to.append(p["to"])
            return {"ok": True, "sent": 1}
        with mock.patch.object(mailer, "call", fake):
            rec = mailer.send_new(root, ON, "2026-10-16")
            self.assertEqual((sent_to, rec["sent"]), (["new@x.com"], 1))
            again = mailer.send_new(root, ON, "2026-10-16")              # nobody twice
            self.assertEqual((again["sent"], sent_to), (0, ["new@x.com"]))
        self.assertNotIn("@", (root / mailer.LOG).read_text())
        with self.assertRaises(mailer.MailError):
            mailer.send_new(root, ON, "2026-10-15")                       # never emailed: use send


class ScorecardStars(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "briefings").mkdir()
        (self.root / "data").mkdir()
        (self.root / "briefings/2026-10-16.md").write_text(MD + " word" * 900)

    def test_pull_and_merge(self):
        rows = [{"day": "2026-10-16", "who": "steven", "score": 5, "at": "2026-10-16T08:00:00Z", "id": "s1"},
                {"day": "2026-10-16", "who": "reader", "score": 3, "at": "2026-10-16T08:01:00Z", "id": "r1"},
                {"day": "2026-10-16", "who": "reader", "score": 4, "at": "2026-10-16T08:02:00Z", "id": "r2"},
                {"day": "2026-10-16", "who": "web", "score": 1, "at": "2026-10-16T08:03:00Z", "id": ""},
                {"day": "bad", "who": "reader", "score": 9},
                {"day": "2026-10-16", "who": "admin", "score": 5, "at": "x"}]          # unknown who -> web
        with mock.patch.object(mailer, "ratings", lambda cfg: rows):
            self.assertEqual(quality.pull_stars(self.root, ON), 5)
            self.assertEqual(quality.pull_stars(self.root, OFF), 0)                     # off: nothing fetched
        with (self.root / quality.RATINGS).open("a") as fh:                             # an earlier terminal rating
            fh.write(json.dumps({"day": "2026-10-16", "score": 3, "who": "steven", "at": "2026-10-15T23:00:00"}) + "\n")
        r = quality.score_day(self.root, {}, "2026-10-16")
        self.assertEqual(r["rating_steven"], 5)                                         # the latest of his
        self.assertEqual((r["rating_readers"], r["n_reader_ratings"]), (3.5, 2))
        self.assertEqual((r["rating_web"], r["n_web_ratings"]), (3.0, 2))               # never in the breakpoint
        self.assertNotIn("@", (self.root / quality.STARS).read_text())


class Pages(unittest.TestCase):
    def test_share_subscribe_and_stars(self):
        root = Path(tempfile.mkdtemp())
        (root / "briefings").mkdir()
        (root / "briefings/2026-10-16.md").write_text(MD)
        out = root / "site"
        site.build(root, ON, out=out, base_url="https://s.example/ai-briefing")
        day = (out / "2026-10-16" / "index.html").read_text()
        self.assertIn('data-share data-url="https://s.example/ai-briefing/2026-10-16/"', day)
        self.assertIn("Email it", day)
        self.assertIn('id="subscribe"', day)
        self.assertIn(f'action="{SCRIPT}"', day)
        self.assertIn("action=rate&amp;d=2026-10-16&amp;s=5", day)
        self.assertTrue((out / "share.js").exists())
        land = (out / "index.html").read_text()
        self.assertIn("Share the podcast", land)
        self.assertIn("Subscribe by email", land)
        site.build(root, OFF, out=root / "site2", base_url="https://s.example/ai-briefing")
        self.assertNotIn("action=rate", (root / "site2" / "2026-10-16" / "index.html").read_text())


if __name__ == "__main__":
    unittest.main()
