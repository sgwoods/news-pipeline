import datetime as dt
import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path

from pipeline import feedback as fb

CFG = {}


def reply(body, frm="Jane Reader <jane@example.com>", subject="Re: AI Briefing · Tue Oct 13: Near-frontier at a fifth of the price"):
    m = EmailMessage()
    m["From"], m["Subject"], m["Date"] = frm, subject, "Wed, 14 Oct 2026 09:00:00 -0400"
    m["Message-ID"] = f"<{abs(hash(body))}@example.com>"
    m.set_content(body)
    return m.as_bytes()


class Fake:
    def __init__(self, out):
        self.out, self.prompts = out, []

    def complete_json(self, system, user, max_tokens=None):
        self.prompts.append(user)
        return self.out


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_reply_text_strips_quotes_signature_and_contacts(self):
        t = fb.reply_text("The $4B figure looks wrong.\nCall me at +1 416 555 0199 or jane@x.com\n\n"
                          "On Tue, Oct 13, 2026 at 6:45 AM AI Briefing <you@example.com> wrote:\n> old text\n")
        self.assertIn("$4B figure looks wrong", t)
        self.assertNotIn("old text", t)
        self.assertNotIn("555", t)
        self.assertNotIn("jane@x.com", t)

    def test_parse_reply_privacy_and_day(self):
        it = fb.parse_reply(reply("Loved the podcast, but Mistral was mispronounced."), CFG)
        self.assertEqual(it["day"], "2026-10-13")
        self.assertEqual(it["name"], "Jane")
        self.assertNotIn("example.com", str(it))
        self.assertFalse(it["from_editor"])
        self.assertIsNone(fb.parse_reply(reply("hi", subject="Lunch?"), CFG))
        self.assertTrue(fb.parse_reply(reply("test", frm="Steven <you@example.com>"), CFG)["from_editor"])

    def test_briefing_day_year_rollover(self):
        self.assertEqual(fb.briefing_day("Re: AI Briefing · Thu Dec 31: x", dt.datetime(2027, 1, 2)), "2026-12-31")

    def test_unsubscribe_rule_wins_and_triage(self):
        a = fb.parse_reply(reply("Please unsubscribe me."), CFG)
        b = fb.parse_reply(reply("The $4B in the Mistral story should be $2B."), CFG)
        fb.save(self.root, {"items": [a, b], "themes": []})
        llm = Fake({"items": [{"id": a["id"], "category": "praise", "severity": "low", "summary": "s"},
                              {"id": b["id"], "category": "correction", "severity": "high", "summary": "Figure wrong",
                               "action": "Check the figure"}, {"id": "nope", "category": "x"}],
                    "themes": [{"theme": "Accuracy", "ids": [b["id"], "zz"], "suggestion": "Check figures"}]})
        r = fb.triage(self.root, CFG, llm=llm, log=lambda *x: None)
        self.assertEqual(r["triaged"], 2)
        self.assertIn("should be $2B", llm.prompts[0])
        d = fb.load(self.root)
        by = {i["id"]: i for i in d["items"]}
        self.assertEqual(by[a["id"]]["triage"]["category"], "unsubscribe")
        self.assertEqual(by[b["id"]]["triage"]["severity"], "high")
        self.assertEqual(by[b["id"]]["status"], "triaged")
        self.assertEqual(d["themes"][0]["ids"], [b["id"]])
        self.assertEqual(fb.counts(self.root)["high"], 2)
        self.assertEqual(fb.triage(self.root, CFG, llm=llm, log=lambda *x: None)["triaged"], 0)   # nothing new
        fb.set_status(self.root, b["id"], "done", "fixed in rebrief")
        self.assertEqual(fb.counts(self.root)["open"], 1)
        with self.assertRaises(ValueError):
            fb.set_status(self.root, a["id"], "bogus")


if __name__ == "__main__":
    unittest.main()
