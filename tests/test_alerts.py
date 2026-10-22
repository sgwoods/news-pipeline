import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import alerts, mailer

CFG = {"email": {"test_to": "owner@example.com", "script_url": "https://script.google.com/macros/s/x/exec"}}


class Alerts(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_message_says_what_and_what_to_do(self):
        m = alerts.build("approval", "2026-10-19", detail="security-sensitive files changed", files=["run.py"],
                         next_try="07:30")
        self.assertIn("What happened", m["text"])
        self.assertIn("./np release-check approve", m["text"])
        self.assertIn("approval sends what was held back", m["text"])
        self.assertIn("- run.py", m["text"])
        self.assertIn("07:30", m["text"])
        self.assertTrue(m["subject"].startswith("AI Briefing · Action needed"))   # Code.gs subject pin

    def test_once_per_issue_per_day_owner_only_and_not_gated(self):
        sent = []

        def fake_call(cfg, action, _alert=False, **p):
            sent.append((action, _alert, p["to"]))
            return {"ok": True}
        with mock.patch.object(mailer, "call", fake_call), mock.patch.object(mailer, "privacy_gate", lambda m, c: []):
            self.assertTrue(alerts.send(self.root, CFG, "run", day="2026-10-19", log=lambda *a: None))
            self.assertFalse(alerts.send(self.root, CFG, "run", day="2026-10-19", log=lambda *a: None))
            self.assertTrue(alerts.send(self.root, CFG, "email", day="2026-10-19", log=lambda *a: None))
        self.assertEqual(sent, [("send", True, "owner@example.com"), ("send", True, "owner@example.com")])

    def test_alert_flag_refuses_anyone_but_the_owner(self):
        with mock.patch.object(mailer, "ready", lambda c: ""):
            with self.assertRaises(mailer.MailError):
                mailer.call(CFG, "send", _alert=True, to="someone@else.com", subject="x", html="x", text="x")
            with self.assertRaises(mailer.MailError):
                mailer.call(CFG, "add", _alert=True, to="owner@example.com")


if __name__ == "__main__":
    unittest.main()
